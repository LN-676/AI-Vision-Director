import Foundation
import Combine
import Network

@MainActor
final class V13NetworkClient: ObservableObject {
    enum ConnectionStatus: String {
        case offline = "Offline"
        case connecting = "Connecting"
        case connected = "Connected"
        case receiving = "Receiving Tracking"
        case timedOut = "Timed Out"
        case failed = "Connection Failed"
    }

    @Published private(set) var status: ConnectionStatus = .offline
    @Published private(set) var lastCommand: TrackingCommand?
    @Published private(set) var desktopState: DesktopState?
    @Published private(set) var cameraFramesSent = 0
    @Published private(set) var cameraFramesDropped = 0
    @Published var serverURL: String {
        didSet { UserDefaults.standard.set(serverURL, forKey: Self.serverURLKey) }
    }

    var onCommand: ((TrackingCommand) async -> Void)?
    var onControl: ((ControlMessage) async -> Void)?
    var onTimeout: (() async -> Void)?

    private let logger: AppLogger
    private var timeoutTask: Task<Void, Never>?
    private var receiveTask: Task<Void, Never>?
    private var reconnectTask: Task<Void, Never>?
    private var socketTask: URLSessionWebSocketTask?
    private var latestCameraFrame: Data?
    private var cameraSendInFlight = false
    private var intentionalDisconnect = false
    private var bonjourURLs: [URL] = []
    private var sequenceValidator = TrackingCommandSequenceValidator()
    private var timeout: Duration = .milliseconds(500)
    private var timeoutLabel = "500 ms"
    private let handshakeTimeout: Duration = .seconds(4)
    private static let serverURLKey = "AIVisionDirectorServerURL"
    private static let legacyServerURLKey = "AI_Vison_DirectorServerURL"
    private static let fallbackServerURL = "ws://192.168.1.100:8765/ws/tracking"
    private lazy var bonjourBrowser = BonjourServerBrowser { [weak self] urls in
        Task { @MainActor [weak self] in
            self?.updateBonjourURLs(urls)
        }
    }

    init(logger: AppLogger) {
        self.logger = logger
        serverURL = UserDefaults.standard.string(forKey: Self.serverURLKey)
            ?? UserDefaults.standard.string(forKey: Self.legacyServerURLKey)
            ?? Self.fallbackServerURL
        bonjourBrowser.start()
    }

    deinit {
        timeoutTask?.cancel()
        receiveTask?.cancel()
        reconnectTask?.cancel()
        socketTask?.cancel(with: .goingAway, reason: nil)
    }

    func connect() async {
        let savedValue = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let savedURL = Self.validWebSocketURL(savedValue) else {
            status = .failed
            logger.log(.error, "Invalid WebSocket URL: \(savedValue)")
            await onTimeout?()
            return
        }

        closeSocket()
        sequenceValidator.reset()
        intentionalDisconnect = false
        status = .connecting
        let candidates = await connectionCandidates(savedURL: savedURL)
        logger.log(.info, "Checking \(candidates.count) AI Vision Director WebSocket endpoint(s).")

        for url in candidates {
            guard !Task.isCancelled else { return }
            logger.log(.info, "Connecting to AI Vision Director at \(url.absoluteString)")
            let task = URLSession.shared.webSocketTask(with: url)
            socketTask = task
            task.resume()
            do {
                let firstMessage = try await receiveHandshakeMessage(from: task)
                guard task === socketTask else { return }
                serverURL = url.absoluteString
                logger.log(.success, "WebSocket endpoint verified and saved: \(url.absoluteString)")
                await handle(firstMessage)
                receiveTask = Task { @MainActor [weak self, weak task] in
                    guard let self, let task else { return }
                    await self.receiveLoop(task: task)
                }
                await sendControl(action: "request_state")
                return
            } catch {
                guard task === socketTask else { return }
                task.cancel(with: .goingAway, reason: nil)
                socketTask = nil
                logger.log(.warning, "WebSocket check failed for \(url.absoluteString): \(error.localizedDescription)")
            }
        }

        status = .failed
        logger.log(.error, "No reachable AI Vision Director WebSocket endpoint was found.")
        await triggerTimeout(reason: "WebSocket handshake failed")
        scheduleReconnect()
    }

    func setTrackingTimeout(seconds: Double) {
        let clamped = max(0.2, min(2.0, seconds))
        timeout = .milliseconds(Int((clamped * 1_000).rounded()))
        timeoutLabel = String(format: "%.1f s", clamped)
        if lastCommand != nil {
            armTimeout()
        }
    }

    func receive(data: Data) async {
        guard let messageType = messageType(in: data) else {
            logger.log(.info, "Ignored malformed AI Vision Director message.")
            return
        }

        switch messageType {
        case "tracking":
            markConnectedIfNeeded()
            await receiveTrackingCommand(data)
        case "desktop_state":
            markConnectedIfNeeded()
            receiveDesktopState(data)
        case "control":
            markConnectedIfNeeded()
            await receiveControlMessage(data)
        default:
            logger.log(.info, "Ignored unsupported AI Vision Director message type: \(messageType).")
        }
    }

    private func receiveTrackingCommand(_ data: Data) async {
        switch JSONDecoder().decodeSafely(TrackingCommand.self, from: data) {
        case .success(let command):
            guard sequenceValidator.accept(command) else {
                logger.log(.error, "V1.0 JSON rejected: duplicate or out-of-order sequence.")
                await triggerTimeout(reason: "stale tracking command")
                return
            }
            lastCommand = command
            logger.log(
                .success,
                String(format: "V1.0 JSON decoded: locked=%@ error=(%.3f, %.3f) confidence=%.2f zoom=%@ predicted=%@.", String(command.targetLocked), command.errorX, command.errorY, command.confidence, command.zoomFactor.map { String(format: "%.2f", $0) } ?? "nil", String(command.predictedTarget ?? false))
            )
            await onCommand?(command)
            if command.targetLocked {
                status = .receiving
                armTimeout()
            } else {
                timeoutTask?.cancel()
                status = .connected
            }
        case .failure(let error):
            logger.log(.error, "V1.0 JSON decode failed: \(error.localizedDescription)")
            await triggerTimeout(reason: "JSON decode failure")
        }
    }

    private func receiveDesktopState(_ data: Data) {
        switch JSONDecoder().decodeSafely(DesktopState.self, from: data) {
        case .success(let state):
            desktopState = state
            if status == .timedOut || status == .connecting {
                status = .connected
            }
            logger.log(
                .info,
                "Desktop state updated: source=\(state.source), motor=\(state.motor.armed ? "armed" : "off"), gids=\(state.gids.count)."
            )
        case .failure(let error):
            logger.log(.error, "Desktop state decode failed: \(error.localizedDescription)")
        }
    }

    private func receiveControlMessage(_ data: Data) async {
        switch JSONDecoder().decodeSafely(ControlMessage.self, from: data) {
        case .success(let message):
            logger.log(.info, "Received desktop control action: \(message.action)")
            await onControl?(message)
        case .failure(let error):
            logger.log(.error, "Desktop control decode failed: \(error.localizedDescription)")
        }
    }

    func sendControl(action: String, source: String? = nil, gid: Int? = nil, framing: String? = nil) async {
        guard let socketTask, isHandshakeComplete else { return }
        let message = ControlMessage(action: action, source: source, gid: gid, framing: framing)
        do {
            let data = try JSONEncoder().encode(message)
            guard let text = String(data: data, encoding: .utf8) else { return }
            try await socketTask.send(.string(text))
            logger.log(.info, "Sent iPhone control action: \(action)")
        } catch {
            logger.log(.error, "Control send failed: \(error.localizedDescription)")
        }
    }

    func sendCameraFrame(_ data: Data) async {
        guard isHandshakeComplete else { return }
        if cameraSendInFlight {
            if latestCameraFrame != nil {
                cameraFramesDropped += 1
            }
            latestCameraFrame = data
            return
        }

        latestCameraFrame = data
        cameraSendInFlight = true
        defer { cameraSendInFlight = false }

        while let frame = latestCameraFrame {
            latestCameraFrame = nil
            guard let socketTask, isHandshakeComplete else { return }
            do {
                try await socketTask.send(.data(frame))
                cameraFramesSent += 1
            } catch {
                latestCameraFrame = nil
                logger.log(.error, "Camera frame send failed: \(error.localizedDescription)")
                return
            }
        }
    }

    func sendMotorStatus(
        docked: Bool,
        manualReady: Bool,
        systemTrackingEnabled: Bool?,
        lastError: String?,
        currentVelocity: GimbalVelocity? = nil,
        lastCommand: TrackingCommand? = nil,
        lastStopReason: String? = nil,
        cameraZoomFactor: Double? = nil,
        cameraDisplayZoomFactor: Double? = nil
    ) async {
        guard let socketTask, isHandshakeComplete else { return }
        let message = MotorStatusMessage(
            docked: docked,
            manualReady: manualReady,
            systemTrackingEnabled: systemTrackingEnabled,
            lastError: lastError,
            timestampMs: Int64(Date().timeIntervalSince1970 * 1_000),
            currentVelocity: currentVelocity,
            lastCommand: lastCommand,
            lastStopReason: lastStopReason,
            cameraZoomFactor: cameraZoomFactor,
            cameraDisplayZoomFactor: cameraDisplayZoomFactor,
            cameraFramesSent: cameraFramesSent,
            cameraFramesDropped: cameraFramesDropped
        )
        do {
            let data = try JSONEncoder().encode(message)
            guard let text = String(data: data, encoding: .utf8) else { return }
            try await socketTask.send(.string(text))
        } catch {
            logger.log(.error, "Motor status send failed: \(error.localizedDescription)")
        }
    }

    func sendFakeCommand() async {
        let json = #"{"type":"tracking","version":"1.0","source_version":"1.0","target_locked":true,"target_id":7,"error_x":0.18,"error_y":-0.04,"confidence":0.91,"timestamp_ms":1781770000000,"zoom_factor":2.0}"#
        logger.log(.info, "Injecting a fake V1.0 JSON command.")
        await receive(data: Data(json.utf8))
    }

    func disconnect() async {
        intentionalDisconnect = true
        closeSocket()
        status = .offline
        lastCommand = nil
        desktopState = nil
        sequenceValidator.reset()
        latestCameraFrame = nil
        cameraSendInFlight = false
        cameraFramesSent = 0
        cameraFramesDropped = 0
        logger.log(.warning, "AI Vision Director client disconnected; requesting safety stop.")
        await onTimeout?()
    }

    private func receiveLoop(task: URLSessionWebSocketTask) async {
        do {
            while !Task.isCancelled, task === socketTask {
                let message = try await task.receive()
                await handle(message)
            }
        } catch {
            guard !intentionalDisconnect, task === socketTask else { return }
            socketTask = nil
            status = .failed
            logger.log(.error, "WebSocket receive failed: \(error.localizedDescription)")
            await triggerTimeout(reason: "WebSocket disconnected")
            scheduleReconnect()
        }
    }

    private func closeSocket() {
        timeoutTask?.cancel()
        receiveTask?.cancel()
        reconnectTask?.cancel()
        socketTask?.cancel(with: .goingAway, reason: nil)
        socketTask = nil
        latestCameraFrame = nil
    }

    private var isHandshakeComplete: Bool {
        status == .connected || status == .receiving
    }

    private func connectionCandidates(savedURL: URL) async -> [URL] {
        if bonjourURLs.isEmpty {
            try? await Task.sleep(for: .milliseconds(1_200))
        }
        var candidates = bonjourURLs
        candidates.append(savedURL)
        var seen = Set<String>()
        return candidates.filter { seen.insert($0.absoluteString).inserted }
    }

    private func receiveHandshakeMessage(
        from task: URLSessionWebSocketTask
    ) async throws -> URLSessionWebSocketTask.Message {
        try await withThrowingTaskGroup(of: URLSessionWebSocketTask.Message.self) { group in
            group.addTask { try await task.receive() }
            group.addTask { [handshakeTimeout] in
                try await Task.sleep(for: handshakeTimeout)
                throw NetworkConnectionError.handshakeTimedOut
            }
            guard let message = try await group.next() else {
                throw NetworkConnectionError.handshakeTimedOut
            }
            group.cancelAll()
            return message
        }
    }

    private func handle(_ message: URLSessionWebSocketTask.Message) async {
        switch message {
        case .data(let data):
            await receive(data: data)
        case .string(let text):
            await receive(data: Data(text.utf8))
        @unknown default:
            logger.log(.warning, "Ignored an unknown WebSocket message type.")
        }
    }

    private func updateBonjourURLs(_ urls: [URL]) {
        let previous = Set(bonjourURLs.map(\.absoluteString))
        bonjourURLs = urls
        let current = Set(urls.map(\.absoluteString))
        guard current != previous, let preferred = urls.first else { return }
        logger.log(.info, "Bonjour discovered AI Vision Director at \(preferred.absoluteString)")
        if status == .failed || status == .timedOut {
            scheduleReconnect(immediately: true)
        }
    }

    private static func validWebSocketURL(_ value: String) -> URL? {
        guard
            let url = URL(string: value),
            ["ws", "wss"].contains(url.scheme?.lowercased() ?? ""),
            url.host != nil
        else {
            return nil
        }
        return url
    }

    private func messageType(in data: Data) -> String? {
        guard
            let object = try? JSONSerialization.jsonObject(with: data),
            let payload = object as? [String: Any]
        else {
            return nil
        }
        return payload["type"] as? String
    }

    private func markConnectedIfNeeded() {
        if status == .connecting || status == .timedOut {
            status = .connected
            logger.log(.success, "AI Vision Director WebSocket connected.")
        }
    }

    private func scheduleReconnect(immediately: Bool = false) {
        reconnectTask?.cancel()
        reconnectTask = Task { @MainActor [weak self] in
            do {
                if !immediately {
                    try await Task.sleep(for: .seconds(1))
                }
            } catch {
                return
            }
            guard let self, !self.intentionalDisconnect else { return }
            self.logger.log(.info, "Retrying AI Vision Director WebSocket connection.")
            self.reconnectTask = nil
            await self.connect()
        }
    }

    private func armTimeout() {
        timeoutTask?.cancel()
        timeoutTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                try await Task.sleep(for: self.timeout)
                await triggerTimeout(reason: "no V1.0 data for \(self.timeoutLabel)")
            } catch {
                return
            }
        }
    }

    private func triggerTimeout(reason: String) async {
        timeoutTask?.cancel()
        status = .timedOut
        logger.log(.warning, "V1.0 safety timeout: \(reason).")
        await onTimeout?()
    }
}

private enum NetworkConnectionError: LocalizedError {
    case handshakeTimedOut

    var errorDescription: String? {
        "WebSocket handshake timed out"
    }
}

private final class BonjourServerBrowser: @unchecked Sendable {
    private let browser = NWBrowser(
        for: .bonjour(type: "_autocamtracker._tcp", domain: "local."),
        using: .tcp
    )
    private let queue = DispatchQueue(label: "ai-vision-director.bonjour-browser")
    private let onURLs: @Sendable ([URL]) -> Void

    init(onURLs: @escaping @Sendable ([URL]) -> Void) {
        self.onURLs = onURLs
        browser.browseResultsChangedHandler = { [onURLs] results, _ in
            let urls = results.compactMap { result -> URL? in
                guard case let .service(name, _, _, _) = result.endpoint else { return nil }
                var components = URLComponents()
                components.scheme = "ws"
                components.host = "\(name).local"
                components.port = 8765
                components.path = "/ws/tracking"
                return components.url
            }
            .sorted { $0.absoluteString < $1.absoluteString }
            onURLs(urls)
        }
    }

    func start() {
        browser.start(queue: queue)
    }

    deinit {
        browser.cancel()
    }
}
