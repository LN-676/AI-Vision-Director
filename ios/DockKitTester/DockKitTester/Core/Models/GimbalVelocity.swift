import Foundation

struct GimbalVelocity: Equatable, Sendable {
    var yaw: Double
    var pitch: Double
    var roll: Double

    static let zero = GimbalVelocity(yaw: 0, pitch: 0, roll: 0)
}

struct GimbalControlConfiguration: Equatable, Sendable {
    var manualSpeed = 0.2
    var maxYawSpeed = 0.8
    var maxPitchSpeed = 0.4
    var deadZone = 0.03
    var smoothingOldWeight = 0.7
    var kpYaw = 1.0
    var kpPitch = 1.0
}

struct GimbalVelocityCalculator: Sendable {
    var configuration: GimbalControlConfiguration
    private(set) var previous = GimbalVelocity.zero

    init(configuration: GimbalControlConfiguration = .init()) {
        self.configuration = configuration
    }

    mutating func velocity(for command: GimbalCommand) -> GimbalVelocity {
        let speed = configuration.manualSpeed
        let output: GimbalVelocity
        switch command {
        case .panLeft:
            output = .init(yaw: -speed, pitch: 0, roll: 0)
        case .panRight:
            output = .init(yaw: speed, pitch: 0, roll: 0)
        case .tiltUp:
            output = .init(yaw: 0, pitch: -speed, roll: 0)
        case .tiltDown:
            output = .init(yaw: 0, pitch: speed, roll: 0)
        case .stop, .recenter:
            output = .zero
        }
        previous = output
        return output
    }

    mutating func velocity(for tracking: TrackingCommand) -> GimbalVelocity {
        guard tracking.isTrackable() else {
            reset()
            return .zero
        }

        let errorX = abs(tracking.errorX) < configuration.deadZone ? 0 : tracking.errorX
        let errorY = abs(tracking.errorY) < configuration.deadZone ? 0 : tracking.errorY
        let requestedYaw = clamp(
            errorX * configuration.kpYaw,
            min: -configuration.maxYawSpeed,
            max: configuration.maxYawSpeed
        )
        let requestedPitch = clamp(
            -errorY * configuration.kpPitch,
            min: -configuration.maxPitchSpeed,
            max: configuration.maxPitchSpeed
        )
        let newWeight = 1 - configuration.smoothingOldWeight
        let output = GimbalVelocity(
            yaw: previous.yaw * configuration.smoothingOldWeight + requestedYaw * newWeight,
            pitch: previous.pitch * configuration.smoothingOldWeight + requestedPitch * newWeight,
            roll: 0
        )
        previous = output
        return output
    }

    mutating func reset() {
        previous = .zero
    }
}
