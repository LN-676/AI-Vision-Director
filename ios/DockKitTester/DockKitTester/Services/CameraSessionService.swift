@preconcurrency import AVFoundation
import Combine
import Foundation

@MainActor
final class CameraSessionService: ObservableObject {
    var session: AVCaptureSession { capture.session }

    @Published private(set) var isRunning = false
    @Published private(set) var authorizationStatus = AVCaptureDevice.authorizationStatus(for: .video)
    @Published private(set) var lastError: String?

    private let logger: AppLogger
    private let sessionQueue = DispatchQueue(label: "com.linen.DockKitTester.camera-session")
    private let capture = CaptureSessionBox()

    init(logger: AppLogger) {
        self.logger = logger
    }

    func start() async {
        authorizationStatus = AVCaptureDevice.authorizationStatus(for: .video)

        if authorizationStatus == .notDetermined {
            let granted = await AVCaptureDevice.requestAccess(for: .video)
            authorizationStatus = AVCaptureDevice.authorizationStatus(for: .video)
            guard granted else {
                recordError("Camera permission was denied; DockKit camera session cannot start.")
                return
            }
        }

        guard authorizationStatus == .authorized else {
            recordError("Camera permission is not authorized. Enable it in Settings > Privacy & Security > Camera.")
            return
        }

        do {
            try await configureAndStart()
            isRunning = true
            lastError = nil
            logger.log(.success, "Rear camera capture session started; DockKit discovery is active.")
        } catch {
            recordError("Camera capture session failed: \(error.localizedDescription) [\(String(reflecting: error))]")
        }
    }

    func stop() async {
        guard isRunning else { return }
        let capture = capture
        await withCheckedContinuation { continuation in
            sessionQueue.async {
                if capture.session.isRunning {
                    capture.session.stopRunning()
                }
                continuation.resume()
            }
        }
        isRunning = false
        logger.log(.info, "Camera capture session stopped.")
    }

    private func configureAndStart() async throws {
        let capture = capture
        try await withCheckedThrowingContinuation { continuation in
            sessionQueue.async {
                do {
                    if !capture.isConfigured {
                        capture.session.beginConfiguration()
                        capture.session.sessionPreset = .high

                        guard let camera = AVCaptureDevice.default(
                            .builtInWideAngleCamera,
                            for: .video,
                            position: .back
                        ) else {
                            capture.session.commitConfiguration()
                            throw CameraSessionError.rearCameraUnavailable
                        }

                        let input = try AVCaptureDeviceInput(device: camera)
                        guard capture.session.canAddInput(input) else {
                            capture.session.commitConfiguration()
                            throw CameraSessionError.cannotAddInput
                        }
                        capture.session.addInput(input)

                        let output = AVCaptureVideoDataOutput()
                        output.alwaysDiscardsLateVideoFrames = true
                        guard capture.session.canAddOutput(output) else {
                            capture.session.commitConfiguration()
                            throw CameraSessionError.cannotAddOutput
                        }
                        capture.session.addOutput(output)
                        capture.session.commitConfiguration()
                        capture.isConfigured = true
                    }

                    if !capture.session.isRunning {
                        capture.session.startRunning()
                    }
                    continuation.resume()
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private func recordError(_ message: String) {
        lastError = message
        isRunning = false
        logger.log(.error, message)
    }
}

private final class CaptureSessionBox: @unchecked Sendable {
    let session = AVCaptureSession()
    var isConfigured = false
}

private enum CameraSessionError: LocalizedError {
    case rearCameraUnavailable
    case cannotAddInput
    case cannotAddOutput

    var errorDescription: String? {
        switch self {
        case .rearCameraUnavailable: "Rear camera is unavailable."
        case .cannotAddInput: "AVCaptureSession rejected the rear camera input."
        case .cannotAddOutput: "AVCaptureSession rejected the video output."
        }
    }
}
