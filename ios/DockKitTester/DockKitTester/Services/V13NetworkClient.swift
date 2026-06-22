import Foundation
import Combine

@MainActor
final class V13NetworkClient: ObservableObject {
    enum ConnectionStatus: String {
        case stub = "Stub / Offline"
        case receiving = "Receiving Test Data"
        case timedOut = "Timed Out"
    }

    @Published private(set) var status: ConnectionStatus = .stub
    @Published private(set) var lastCommand: TrackingCommand?

    var onCommand: ((TrackingCommand) async -> Void)?
    var onTimeout: (() async -> Void)?

    private let logger: AppLogger
    private var timeoutTask: Task<Void, Never>?
    private let timeout: Duration = .milliseconds(500)

    init(logger: AppLogger) {
        self.logger = logger
    }

    deinit {
        timeoutTask?.cancel()
    }

    func receive(data: Data) async {
        switch JSONDecoder().decodeSafely(TrackingCommand.self, from: data) {
        case .success(let command):
            guard command.type == "tracking" else {
                logger.log(.error, "V1.3 JSON rejected: type must be 'tracking'.")
                await triggerTimeout(reason: "invalid message type")
                return
            }
            status = .receiving
            lastCommand = command
            logger.log(
                .success,
                String(format: "V1.3 JSON decoded: locked=%@ error=(%.3f, %.3f) confidence=%.2f.", String(command.targetLocked), command.errorX, command.errorY, command.confidence)
            )
            await onCommand?(command)
            armTimeout()
        case .failure(let error):
            logger.log(.error, "V1.3 JSON decode failed: \(error.localizedDescription)")
            await triggerTimeout(reason: "JSON decode failure")
        }
    }

    func sendFakeCommand() async {
        let json = #"{"type":"tracking","version":"1.3","target_locked":true,"target_id":7,"error_x":0.18,"error_y":-0.04,"confidence":0.91,"timestamp_ms":1781770000000}"#
        logger.log(.info, "Injecting the MVP fake V1.3 JSON command.")
        await receive(data: Data(json.utf8))
    }

    func disconnect() async {
        timeoutTask?.cancel()
        status = .stub
        lastCommand = nil
        logger.log(.warning, "V1.3 client disconnected; requesting safety stop.")
        await onTimeout?()
    }

    private func armTimeout() {
        timeoutTask?.cancel()
        timeoutTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                try await Task.sleep(for: self.timeout)
                await triggerTimeout(reason: "no V1.3 data for 500 ms")
            } catch {
                return
            }
        }
    }

    private func triggerTimeout(reason: String) async {
        timeoutTask?.cancel()
        status = .timedOut
        logger.log(.warning, "V1.3 safety timeout: \(reason).")
        await onTimeout?()
    }
}
