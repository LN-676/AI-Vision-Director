import Foundation
import Combine
import AVFoundation
#if canImport(DockKit)
import DockKit
import Spatial
#endif

@MainActor
protocol DockKitMotorControlling: AnyObject {
    func setAngularVelocity(yaw: Double, pitch: Double, roll: Double) async
    func track(_ command: TrackingCommand) async
    func stop() async
    func recenter() async
    func setHome() async
    func returnHome() async
}

@MainActor
final class DockKitManager: ObservableObject, DockKitMotorControlling {
    @Published private(set) var accessoryStatus: AccessoryStatus = .notFound
    @Published private(set) var accessoryName: String?
    @Published private(set) var isSystemTrackingEnabled: Bool?
    @Published private(set) var trackingButtonEnabled: Bool?
    @Published private(set) var isManualModeTransitioning = false
    @Published private(set) var isCapabilityTestRunning = false
    @Published private(set) var lastError: String?
    @Published private(set) var hasHomePosition = false

    private let logger: AppLogger
    private var listeningTask: Task<Void, Never>?
    private var retryTask: Task<Void, Never>?
    private var discoveryWatchdogTask: Task<Void, Never>?
    private var discoveryFailureCount = 0

#if !targetEnvironment(simulator)
    private var accessory: DockAccessory?
    private var motionStateTask: Task<Void, Never>?
    private var accessoryPreparationTask: Task<Void, Never>?
    private var accessorySessionPrepared = false
    private var motorControlMode: MotorControlMode = .unknown
    private var activeOrientationProgress: Progress?
    private var orientationCommandInFlight = false
    private var currentOffset = Vector3D()
    private var homeOffset: Vector3D?
    private var lastVelocityUpdateAt: Date?
    private var customTrackingTask: Task<Void, Never>?
    private var latestTrackingCommand: TrackingCommand?
    private var latestTrackingCommandAt: Date?
    private var customTrackingGeneration = 0
    private var cameraCalibration: DockKitCameraCalibration?
    private var lastCustomTrackingLogAt = Date.distantPast
#endif

    init(logger: AppLogger) {
        self.logger = logger
    }

    deinit {
        listeningTask?.cancel()
        retryTask?.cancel()
        discoveryWatchdogTask?.cancel()
#if !targetEnvironment(simulator)
        customTrackingTask?.cancel()
        motionStateTask?.cancel()
        accessoryPreparationTask?.cancel()
#endif
    }

    var isDocked: Bool {
        accessoryStatus == .docked
    }

    var isManualControlReady: Bool {
        isDocked && isSystemTrackingEnabled == false && !isManualModeTransitioning
    }

    func startListening() async {
        guard listeningTask == nil else { return }

#if targetEnvironment(simulator)
        accessoryStatus = .notFound
        logger.log(.warning, "DockKit requires an iPhone and is unavailable in Simulator.")
#else
        accessoryStatus = .connecting
        retryTask?.cancel()
        retryTask = nil
        logger.log(.info, "Starting DockAccessoryManager.accessoryStateChanges listener.")
        armDiscoveryWatchdog()
        listeningTask = Task { @MainActor [weak self] in
            do {
                for await stateChange in try DockAccessoryManager.shared.accessoryStateChanges {
                    guard !Task.isCancelled else { return }
                    self?.discoveryFailureCount = 0
                    self?.handle(stateChange)
                }
            } catch is CancellationError {
                return
            } catch {
                self?.accessoryStatus = .error
                self?.recordError(api: "accessoryStateChanges", error: error)
                self?.listeningTask = nil
                self?.scheduleDiscoveryRetry()
            }
            self?.listeningTask = nil
        }
#endif
    }

    func restartListening() async {
#if targetEnvironment(simulator)
        await startListening()
#else
        let previousTask = listeningTask
        previousTask?.cancel()
        if let previousTask {
            await previousTask.value
        }
        listeningTask = nil
        motionStateTask?.cancel()
        motionStateTask = nil
        accessoryPreparationTask?.cancel()
        accessoryPreparationTask = nil
        accessorySessionPrepared = false
        accessory = nil
        discoveryWatchdogTask?.cancel()
        discoveryWatchdogTask = nil
        accessoryStatus = .connecting
        accessoryName = nil
        isSystemTrackingEnabled = nil
        trackingButtonEnabled = nil
        lastError = nil
        logger.log(.info, "Restarting DockKit accessory discovery.")
        await startListening()
#endif
    }

#if !targetEnvironment(simulator)
    private func scheduleDiscoveryRetry() {
        guard retryTask == nil else { return }
        discoveryFailureCount = min(discoveryFailureCount + 1, 5)
        let delayMilliseconds = min(4_000, 250 * (1 << (discoveryFailureCount - 1)))
        logger.log(
            .warning,
            "DockKit discovery will retry in \(delayMilliseconds) ms without resetting pairing."
        )
        retryTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(delayMilliseconds))
            guard !Task.isCancelled, let self else { return }
            self.retryTask = nil
            await self.startListening()
        }
    }

    private func armDiscoveryWatchdog() {
        discoveryWatchdogTask?.cancel()
        discoveryWatchdogTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(5))
            guard !Task.isCancelled, let self, self.accessory == nil else { return }
            self.accessoryStatus = .notFound
            let message = "No DockKit dock event. Power on and fully unfold Flow 2 Pro, enable Bluetooth, then remove and remount iPhone. If it has never paired, unlock iPhone on the Home Screen and tap the Flow NFC mark."
            self.lastError = message
            self.logger.log(.warning, message)
        }
    }
#endif

    func enableSystemTracking() async {
#if targetEnvironment(simulator)
        logSimulatorFailure(api: "setSystemTrackingEnabled(true)")
#else
        guard accessory != nil else {
            logMissingAccessory(api: "setSystemTrackingEnabled(true)")
            return
        }
        guard !isManualModeTransitioning else {
            logger.log(.warning, "System Tracking change ignored while another mode transition is running.")
            return
        }

        isManualModeTransitioning = true
        defer { isManualModeTransitioning = false }

        do {
            if isSystemTrackingEnabled == false, let accessory {
                try await accessory.setAngularVelocity(Vector3D())
                logger.log(.info, "Manual motor output stopped before restoring System Tracking.")
            }
            try await DockAccessoryManager.shared.setSystemTrackingEnabled(true)
            guard await waitForSystemTracking(expected: true) else {
                throw ManualModeError.trackingStateDidNotChange(expected: true)
            }
            lastError = nil
            logger.log(.success, "setSystemTrackingEnabled(true) succeeded.")
        } catch {
            recordError(api: "setSystemTrackingEnabled(true)", error: error)
        }
#endif
    }

    func disableSystemTracking() async {
        _ = await enterManualMode()
    }

    @discardableResult
    func enterManualMode() async -> Bool {
#if targetEnvironment(simulator)
        logSimulatorFailure(api: "setSystemTrackingEnabled(false)")
        return false
#else
        guard accessory != nil else {
            logMissingAccessory(api: "setSystemTrackingEnabled(false)")
            return false
        }
        if isSystemTrackingEnabled == false {
            logger.log(.info, "Manual Mode is already active; System Tracking is OFF.")
            return true
        }
        guard !isManualModeTransitioning else {
            logger.log(.warning, "Manual Mode request ignored while another mode transition is running.")
            return false
        }

        isManualModeTransitioning = true
        defer { isManualModeTransitioning = false }

        do {
            logger.log(.info, "Entering Manual Mode: requesting System Tracking OFF.")
            try await DockAccessoryManager.shared.setSystemTrackingEnabled(false)
            guard await waitForSystemTracking(expected: false) else {
                throw ManualModeError.trackingStateDidNotChange(expected: false)
            }
            lastError = nil
            logger.log(.success, "Manual Mode ready: System Tracking is confirmed OFF.")
            return true
        } catch {
            recordError(api: "setSystemTrackingEnabled(false)", error: error)
            return false
        }
#endif
    }

    func setAngularVelocity(yaw: Double, pitch: Double, roll: Double) async {
#if targetEnvironment(simulator)
        logSimulatorFailure(api: "setAngularVelocity")
#else
        guard let accessory else {
            logMissingAccessory(api: "setAngularVelocity")
            return
        }
        guard isManualControlReady else {
            let message = "setAngularVelocity blocked: enter Manual Mode and confirm Tracking OFF first."
            lastError = message
            logger.log(.error, message)
            return
        }

        if motorControlMode == .relativeOrientation {
            await applyRelativeOrientationFallback(
                accessory: accessory,
                yaw: yaw,
                pitch: pitch,
                roll: roll
            )
            return
        }

        let velocity = Vector3D(x: pitch, y: yaw, z: roll)
        integrateAngularVelocity(yaw: yaw, pitch: pitch, roll: roll)
        do {
            try await accessory.setAngularVelocity(velocity)
            motorControlMode = .angularVelocity
            lastError = nil
            logger.log(
                .success,
                String(format: "setAngularVelocity(pitch: %.3f, yaw: %.3f, roll: %.3f) succeeded.", pitch, yaw, roll)
            )
        } catch DockKitError.notSupportedByDevice {
            if motorControlMode != .relativeOrientation {
                logger.log(.warning, "Angular velocity is unsupported; switching to relative orientation fallback.")
            }
            motorControlMode = .relativeOrientation
            await applyRelativeOrientationFallback(
                accessory: accessory,
                yaw: yaw,
                pitch: pitch,
                roll: roll
            )
        } catch {
            recordError(
                api: String(format: "setAngularVelocity(pitch: %.3f, yaw: %.3f, roll: %.3f)", pitch, yaw, roll),
                error: error
            )
        }
#endif
    }

    func track(_ command: TrackingCommand) async {
#if targetEnvironment(simulator)
        logSimulatorFailure(api: "track observations")
#else
        guard let accessory else {
            logMissingAccessory(api: "track observations")
            return
        }
        guard isManualControlReady else {
            let message = "Custom tracking blocked: disable System Tracking first."
            lastError = message
            logger.log(.error, message)
            return
        }
        guard command.targetLocked,
              command.targetId != nil,
              let targetX = command.targetX,
              let targetY = command.targetY,
              let bboxWidth = command.bboxWidth,
              let bboxHeight = command.bboxHeight,
              targetX.isFinite,
              targetY.isFinite,
              bboxWidth.isFinite,
              bboxHeight.isFinite,
              bboxWidth > 0,
              bboxHeight > 0 else {
            cancelCustomTrackingCadence()
            await stopCustomTracking(accessory: accessory)
            return
        }

        latestTrackingCommand = command
        latestTrackingCommandAt = Date()
        startCustomTrackingCadence(accessory: accessory)
#endif
    }

    func updateCameraCalibration(_ calibration: DockKitCameraCalibration) {
        cameraCalibration = calibration
        logger.log(
            .success,
            String(
                format: "DockKit camera calibration ready: %@ %.0fx%.0f.",
                calibration.captureDevice.rawValue,
                calibration.referenceDimensions.width,
                calibration.referenceDimensions.height
            )
        )
    }

#if !targetEnvironment(simulator)
    private func startCustomTrackingCadence(accessory: DockAccessory) {
        guard customTrackingTask == nil else { return }
        customTrackingGeneration += 1
        let generation = customTrackingGeneration
        logger.log(.info, "Starting custom DockKit tracking cadence at 15 Hz.")
        customTrackingTask = Task { @MainActor [weak self, weak accessory] in
            guard let self, let accessory else { return }
            do {
                try await accessory.setFramingMode(.center)
                try await accessory.setRegionOfInterest(
                    CGRect(x: 0, y: 0, width: 1, height: 1)
                )
                self.logger.log(
                    .success,
                    "Custom DockKit framing prepared: center mode, full-frame ROI."
                )
            } catch {
                self.recordError(api: "custom tracking framing setup", error: error)
            }
            while !Task.isCancelled {
                guard let command = self.latestTrackingCommand,
                      let receivedAt = self.latestTrackingCommandAt,
                      Date().timeIntervalSince(receivedAt) <= 0.30 else {
                    await self.stopCustomTracking(accessory: accessory)
                    break
                }
                await self.publishCustomTracking(command, accessory: accessory)
                try? await Task.sleep(for: .milliseconds(67))
            }
            if self.customTrackingGeneration == generation {
                self.customTrackingTask = nil
            }
        }
    }

    private func publishCustomTracking(_ command: TrackingCommand, accessory: DockAccessory) async {
        guard command.targetLocked,
              let targetId = command.targetId,
              let targetX = command.targetX,
              let targetY = command.targetY,
              let bboxWidth = command.bboxWidth,
              let bboxHeight = command.bboxHeight else {
            return
        }
        let width = min(1.0, max(0.001, bboxWidth))
        let height = min(1.0, max(0.001, bboxHeight))
        let originX = min(1.0 - width, max(0.0, targetX - width / 2))
        // Desktop detection uses a top-left image origin. DockKit's `.corrected`
        // observation coordinates use a bottom-left origin, matching Vision.
        let originY = min(1.0 - height, max(0.0, 1.0 - targetY - height / 2))
        let observation = DockAccessory.Observation(
            identifier: targetId,
            type: .object,
            rect: CGRect(x: originX, y: originY, width: width, height: height)
        )
        let calibration = cameraCalibration
        let cameraInformation = DockAccessory.CameraInformation(
            captureDevice: calibration?.captureDevice ?? Self.preferredRearCameraDeviceType(),
            cameraPosition: .back,
            orientation: .corrected,
            cameraIntrinsics: calibration?.intrinsics,
            referenceDimensions: calibration?.referenceDimensions
        )
        do {
            try await accessory.track(
                [observation],
                cameraInformation: cameraInformation
            )
            motorControlMode = .customTracking
            lastError = nil
            let now = Date()
            if now.timeIntervalSince(lastCustomTrackingLogAt) >= 1.0 {
                lastCustomTrackingLogAt = now
                logger.log(
                    .success,
                    String(
                        format: "Custom DockKit tracking: target=%d rect=(%.3f, %.3f, %.3f, %.3f).",
                        targetId,
                        originX,
                        originY,
                        width,
                        height
                    )
                )
            }
        } catch {
            recordError(api: "custom DockKit track observations", error: error)
        }
    }

    private func cancelCustomTrackingCadence() {
        customTrackingGeneration += 1
        customTrackingTask?.cancel()
        customTrackingTask = nil
        latestTrackingCommand = nil
        latestTrackingCommandAt = nil
    }

    private static func preferredRearCameraDeviceType() -> AVCaptureDevice.DeviceType {
        let priority: [AVCaptureDevice.DeviceType] = [
            .builtInTripleCamera,
            .builtInDualWideCamera,
            .builtInDualCamera,
            .builtInWideAngleCamera,
        ]
        let discovery = AVCaptureDevice.DiscoverySession(
            deviceTypes: priority,
            mediaType: .video,
            position: .back
        )
        return priority.first { type in
            discovery.devices.contains(where: { $0.deviceType == type })
        } ?? .builtInWideAngleCamera
    }
#endif

    func stop() async {
#if targetEnvironment(simulator)
        logSimulatorFailure(api: "stop / setAngularVelocity(0, 0, 0)")
#else
        cancelCustomTrackingCadence()
        guard let accessory else {
            logger.log(.warning, "Stop requested with no DockKit accessory connected.")
            return
        }
        guard isSystemTrackingEnabled == false else {
            logger.log(.info, "STOP skipped: System Tracking owns the motors and no manual velocity is active.")
            return
        }
        if motorControlMode == .customTracking {
            await stopCustomTracking(accessory: accessory)
            return
        }
        if motorControlMode == .relativeOrientation {
            activeOrientationProgress?.cancel()
            activeOrientationProgress = nil
            orientationCommandInFlight = false
            lastVelocityUpdateAt = nil
            lastError = nil
            logger.log(.success, "STOP succeeded: relative orientation command cancelled.")
            return
        }
        integrateAngularVelocity(yaw: 0, pitch: 0, roll: 0)
        lastVelocityUpdateAt = nil
        do {
            try await accessory.setAngularVelocity(Vector3D())
            lastError = nil
            logger.log(.success, "STOP succeeded: all angular velocities are zero.")
        } catch DockKitError.notSupportedByDevice {
            motorControlMode = .unknown
            recordError(api: "stop / setAngularVelocity(0, 0, 0)", error: DockKitError.notSupportedByDevice)
        } catch {
            recordError(api: "stop / setAngularVelocity(0, 0, 0)", error: error)
        }
#endif
    }

    func recenter() async {
#if targetEnvironment(simulator)
        logSimulatorFailure(api: "setOrientation(origin)")
#else
        guard let accessory else {
            logMissingAccessory(api: "setOrientation(origin)")
            return
        }
        guard isSystemTrackingEnabled == false else {
            let message = "Recenter blocked: disable system tracking first."
            lastError = message
            logger.log(.error, message)
            return
        }
        do {
            _ = try await accessory.setOrientation(Vector3D(), duration: .seconds(1), relative: false)
            lastError = nil
            logger.log(.success, "setOrientation(origin, 1s, absolute) started.")
        } catch {
            recordError(api: "setOrientation(origin, 1s, absolute)", error: error)
            logger.log(.warning, "Recenter failed; applying STOP fallback.")
            await stop()
        }
#endif
    }

    func setHome() async {
#if targetEnvironment(simulator)
        hasHomePosition = true
        logger.log(.success, "Home position overwritten at simulated current offset.")
#else
        activeOrientationProgress?.cancel()
        activeOrientationProgress = nil
        orientationCommandInFlight = false
        lastVelocityUpdateAt = nil
        homeOffset = currentOffset
        hasHomePosition = true
        logger.log(
            .success,
            String(
                format: "Home overwritten at current relative offset pitch=%.3f yaw=%.3f roll=%.3f.",
                currentOffset.x,
                currentOffset.y,
                currentOffset.z
            )
        )
#endif
    }

    func returnHome() async {
        if !hasHomePosition {
            await setHome()
        }
#if targetEnvironment(simulator)
        logger.log(.info, "Returning gimbal to simulated Home.")
#else
        guard let accessory else {
            logMissingAccessory(api: "return Home")
            return
        }
        guard isSystemTrackingEnabled == false else {
            let message = "Return Home blocked: disable system tracking first."
            lastError = message
            logger.log(.error, message)
            return
        }
        let home = homeOffset ?? Vector3D()
        let delta = Vector3D(
            x: home.x - currentOffset.x,
            y: home.y - currentOffset.y,
            z: home.z - currentOffset.z
        )
        logger.log(
            .info,
            String(format: "Returning to Home via relative delta pitch=%.3f yaw=%.3f roll=%.3f.", delta.x, delta.y, delta.z)
        )
        do {
            activeOrientationProgress?.cancel()
            activeOrientationProgress = try await accessory.setOrientation(delta, duration: .seconds(1), relative: true)
            await waitForProgress(activeOrientationProgress!, timeout: .seconds(2))
            currentOffset = home
            lastVelocityUpdateAt = nil
            lastError = nil
            logger.log(.success, "Return Home completed.")
        } catch {
            recordError(api: "return Home relative orientation", error: error)
            await stop()
        }
#endif
    }

    func runCapabilityDiagnostics() async {
#if targetEnvironment(simulator)
        logSimulatorFailure(api: "DockKit capability diagnostics")
#else
        guard let accessory else {
            logMissingAccessory(api: "DockKit capability diagnostics")
            return
        }
        guard await enterManualMode() else { return }
        guard !isCapabilityTestRunning else {
            logger.log(.warning, "Capability diagnostics are already running.")
            return
        }

        isCapabilityTestRunning = true
        defer { isCapabilityTestRunning = false }
        logger.log(.info, "Capability diagnostics started; keep the gimbal area clear.")

        do {
            let limits = try accessory.limits
            logger.log(.success, "Capability limits succeeded: \(String(reflecting: limits)).")
        } catch {
            recordError(api: "capability limits", error: error)
        }

        do {
            let progress = try await accessory.animate(motion: .yes)
            await waitForProgress(progress, timeout: .seconds(3))
            logger.log(.success, "Capability animate(.yes) succeeded.")
        } catch {
            recordError(api: "capability animate(.yes)", error: error)
        }

        do {
            let progress = try await accessory.setOrientation(
                Vector3D(x: 0, y: 0.08, z: 0),
                duration: .milliseconds(300),
                relative: true
            )
            await waitForProgress(progress, timeout: .seconds(2))
            logger.log(.success, "Capability relative orientation succeeded.")
        } catch {
            recordError(api: "capability relative orientation", error: error)
        }

        do {
            try await accessory.setAngularVelocity(Vector3D(x: 0, y: 0.10, z: 0))
            try await Task.sleep(for: .milliseconds(200))
            try await accessory.setAngularVelocity(Vector3D())
            logger.log(.success, "Capability angular velocity succeeded.")
        } catch {
            recordError(api: "capability angular velocity", error: error)
            try? await accessory.setAngularVelocity(Vector3D())
        }

        logger.log(.info, "Capability diagnostics finished; Manual Mode remains active.")
#endif
    }

#if !targetEnvironment(simulator)
    private func handle(_ stateChange: DockAccessory.StateChange) {
        discoveryWatchdogTask?.cancel()
        discoveryWatchdogTask = nil
        trackingButtonEnabled = stateChange.trackingButtonEnabled
        let currentTracking = DockAccessoryManager.shared.isSystemTrackingEnabled
        logger.log(
            .info,
            "DockKit state change: state=\(String(describing: stateChange.state)), accessoryPresent=\(stateChange.accessory != nil), trackingButton=\(stateChange.trackingButtonEnabled), systemTracking=\(currentTracking)."
        )
        if stateChange.state == .docked, let newAccessory = stateChange.accessory {
            if let currentAccessory = accessory, currentAccessory == newAccessory {
                // Tracking-mode and button changes also emit docked state
                // events. Keep the existing session instead of resetting the
                // accessory and its motor-control state on every event.
                accessoryStatus = .docked
                isSystemTrackingEnabled = currentTracking
                if currentTracking,
                   accessorySessionPrepared,
                   !isManualModeTransitioning {
                    logger.log(.warning, "Physical tracking button restored System Tracking; turning it OFF again.")
                    Task { @MainActor [weak self] in
                        _ = await self?.enterManualMode()
                    }
                }
                return
            }

            accessory = newAccessory
            startMotionStateMonitoring(for: newAccessory)
            accessoryPreparationTask?.cancel()
            accessoryPreparationTask = nil
            accessorySessionPrepared = false
            motorControlMode = .unknown
            activeOrientationProgress = nil
            orientationCommandInFlight = false
            currentOffset = Vector3D()
            homeOffset = nil
            lastVelocityUpdateAt = nil
            hasHomePosition = false
            accessoryStatus = .docked
            let model = newAccessory.hardwareModel ?? "DockKit Accessory"
            accessoryName = "\(model) • \(String(describing: newAccessory.identifier))"
            isSystemTrackingEnabled = currentTracking
            lastError = nil
            logger.log(
                .success,
                "Accessory docked: \(accessoryName ?? model); firmware: \(newAccessory.firmwareVersion ?? "unknown")."
            )
            accessoryPreparationTask = Task { @MainActor [weak self, weak newAccessory] in
                guard let self, let newAccessory else { return }
                await self.prepareAccessorySession(newAccessory)
            }
        } else {
            accessoryPreparationTask?.cancel()
            accessoryPreparationTask = nil
            accessorySessionPrepared = false
            motionStateTask?.cancel()
            motionStateTask = nil
            cancelCustomTrackingCadence()
            accessory = nil
            motorControlMode = .unknown
            activeOrientationProgress = nil
            orientationCommandInFlight = false
            currentOffset = Vector3D()
            homeOffset = nil
            lastVelocityUpdateAt = nil
            hasHomePosition = false
            accessoryStatus = .notFound
            accessoryName = nil
            isSystemTrackingEnabled = nil
            trackingButtonEnabled = nil
            logger.log(.warning, "DockKit accessory undocked or unavailable; motor commands are disabled.")
        }
    }

    private func prepareAccessorySession(_ expectedAccessory: DockAccessory) async {
        guard accessory == expectedAccessory, !isManualModeTransitioning else { return }
        isManualModeTransitioning = true
        defer {
            isManualModeTransitioning = false
            accessoryPreparationTask = nil
        }

        do {
            // Match Apple's current sample lifecycle: explicitly initialize
            // the newly docked accessory in System Tracking before changing
            // it to custom/manual motor control.
            logger.log(.info, "Initializing DockKit session with System Tracking ON.")
            try await DockAccessoryManager.shared.setSystemTrackingEnabled(true)
            guard await waitForSystemTracking(expected: true) else {
                throw ManualModeError.trackingStateDidNotChange(expected: true)
            }
            try await Task.sleep(for: .milliseconds(250))
            guard accessory == expectedAccessory, !Task.isCancelled else { return }

            logger.log(.info, "DockKit session initialized; switching to Manual Mode.")
            try await DockAccessoryManager.shared.setSystemTrackingEnabled(false)
            guard await waitForSystemTracking(expected: false) else {
                throw ManualModeError.trackingStateDidNotChange(expected: false)
            }
            accessorySessionPrepared = true
            motorControlMode = .unknown
            lastError = nil
            logger.log(.success, "DockKit session prepared once; Manual Mode is ready.")
        } catch is CancellationError {
            return
        } catch {
            accessorySessionPrepared = false
            recordError(api: "DockKit accessory session preparation", error: error)
        }
    }

    private func startMotionStateMonitoring(for accessory: DockAccessory) {
        motionStateTask?.cancel()
        do {
            let states = try accessory.motionStates
            motionStateTask = Task { @MainActor [weak self] in
                var lastLogAt = Date.distantPast
                for await state in states {
                    guard !Task.isCancelled else { return }
                    let now = Date()
                    guard now.timeIntervalSince(lastLogAt) >= 0.5 else { continue }
                    lastLogAt = now
                    if let error = state.error {
                        self?.logger.log(.error, "DockKit motion state error: \(error.localizedDescription)")
                    } else {
                        self?.logger.log(
                            .info,
                            String(
                                format: "DockKit actual motion: position=(pitch %.4f, yaw %.4f, roll %.4f) velocity=(pitch %.4f, yaw %.4f, roll %.4f).",
                                state.angularPositions.x,
                                state.angularPositions.y,
                                state.angularPositions.z,
                                state.angularVelocities.x,
                                state.angularVelocities.y,
                                state.angularVelocities.z
                            )
                        )
                    }
                }
            }
        } catch {
            recordError(api: "motionStates subscription", error: error)
        }
    }

    private func waitForSystemTracking(expected: Bool) async -> Bool {
        for _ in 0..<12 {
            let current = DockAccessoryManager.shared.isSystemTrackingEnabled
            isSystemTrackingEnabled = current
            if current == expected {
                return true
            }
            try? await Task.sleep(for: .milliseconds(50))
        }
        isSystemTrackingEnabled = DockAccessoryManager.shared.isSystemTrackingEnabled
        return isSystemTrackingEnabled == expected
    }

    private func waitForProgress(_ progress: Progress, timeout: Duration) async {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while !progress.isFinished && !progress.isCancelled && clock.now < deadline {
            try? await Task.sleep(for: .milliseconds(50))
        }
    }

    private func applyRelativeOrientationFallback(
        accessory: DockAccessory,
        yaw: Double,
        pitch: Double,
        roll: Double
    ) async {
        guard !orientationCommandInFlight else { return }
        orientationCommandInFlight = true
        defer { orientationCommandInFlight = false }

        let yawStep = max(-0.04, min(0.04, yaw * 0.18))
        let pitchStep = max(-0.03, min(0.03, pitch * 0.18))
        let rollStep = max(-0.02, min(0.02, roll * 0.18))
        do {
            let progress = try await accessory.setOrientation(
                Vector3D(x: pitchStep, y: yawStep, z: rollStep),
                duration: .milliseconds(80),
                relative: true
            )
            activeOrientationProgress = progress
            currentOffset = Vector3D(
                x: currentOffset.x + pitchStep,
                y: currentOffset.y + yawStep,
                z: currentOffset.z + rollStep
            )
            lastVelocityUpdateAt = nil
            lastError = nil
            logger.log(
                .success,
                String(format: "Relative fallback(pitch: %.3f, yaw: %.3f, roll: %.3f) started.", pitchStep, yawStep, rollStep)
            )
            await waitForProgress(progress, timeout: .milliseconds(250))
            if activeOrientationProgress === progress {
                activeOrientationProgress = nil
            }
        } catch {
            recordError(api: "relative orientation fallback", error: error)
        }
    }

    private func stopCustomTracking(accessory: DockAccessory) async {
        let cameraInformation = DockAccessory.CameraInformation(
            captureDevice: .builtInWideAngleCamera,
            cameraPosition: .back,
            orientation: .corrected,
            cameraIntrinsics: nil,
            referenceDimensions: nil
        )
        do {
            let observations: [DockAccessory.Observation] = []
            try await accessory.track(
                observations,
                cameraInformation: cameraInformation
            )
            motorControlMode = .customTracking
            lastVelocityUpdateAt = nil
            lastError = nil
            logger.log(.success, "STOP succeeded: custom DockKit observations cleared.")
        } catch {
            recordError(api: "stop custom DockKit tracking", error: error)
        }
    }

    private func integrateAngularVelocity(yaw: Double, pitch: Double, roll: Double) {
        let now = Date()
        defer { lastVelocityUpdateAt = now }
        guard let previous = lastVelocityUpdateAt else { return }
        let dt = max(0.0, min(0.25, now.timeIntervalSince(previous)))
        currentOffset = Vector3D(
            x: currentOffset.x + pitch * dt,
            y: currentOffset.y + yaw * dt,
            z: currentOffset.z + roll * dt
        )
    }
#endif

    private func recordError(api: String, error: Error) {
        let detail = "\(api) failed: \(error.localizedDescription) [\(String(reflecting: error))]"
        lastError = detail
        logger.log(.error, detail)
    }

    private func logMissingAccessory(api: String) {
        let detail = "\(api) failed: no docked accessory."
        lastError = detail
        logger.log(.error, detail)
    }

    private func logSimulatorFailure(api: String) {
        let detail = "\(api) unavailable in Simulator; run on a physical iPhone."
        lastError = detail
        logger.log(.error, detail)
    }
}

private enum MotorControlMode {
    case unknown
    case angularVelocity
    case relativeOrientation
    case customTracking
}

private enum ManualModeError: LocalizedError {
    case trackingStateDidNotChange(expected: Bool)

    var errorDescription: String? {
        switch self {
        case .trackingStateDidNotChange(let expected):
            "System Tracking did not become \(expected ? "ON" : "OFF") before the verification timeout."
        }
    }
}
