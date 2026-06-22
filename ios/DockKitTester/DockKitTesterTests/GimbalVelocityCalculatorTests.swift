import XCTest
@testable import DockKitTesterCore

final class GimbalVelocityCalculatorTests: XCTestCase {
    func testManualDirectionsMatchAppleAxisMapping() {
        var calculator = GimbalVelocityCalculator()

        XCTAssertEqual(calculator.velocity(for: .panLeft), .init(yaw: -0.2, pitch: 0, roll: 0))
        XCTAssertEqual(calculator.velocity(for: .panRight), .init(yaw: 0.2, pitch: 0, roll: 0))
        XCTAssertEqual(calculator.velocity(for: .tiltUp), .init(yaw: 0, pitch: -0.2, roll: 0))
        XCTAssertEqual(calculator.velocity(for: .tiltDown), .init(yaw: 0, pitch: 0.2, roll: 0))
    }

    func testTrackingAppliesClampAndSmoothing() {
        var calculator = GimbalVelocityCalculator()
        let command = makeCommand(errorX: 4, errorY: 4)

        let velocity = calculator.velocity(for: command)

        XCTAssertEqual(velocity.yaw, 0.24, accuracy: 0.000_001)
        XCTAssertEqual(velocity.pitch, -0.12, accuracy: 0.000_001)
        XCTAssertEqual(velocity.roll, 0)
    }

    func testDeadZoneProducesZero() {
        var calculator = GimbalVelocityCalculator()

        let velocity = calculator.velocity(for: makeCommand(errorX: 0.02, errorY: -0.02))

        XCTAssertEqual(velocity, .zero)
    }

    func testLostTargetStopsAndClearsSmoothingHistory() {
        var calculator = GimbalVelocityCalculator()
        _ = calculator.velocity(for: makeCommand(errorX: 0.5, errorY: 0.2))

        let stopped = calculator.velocity(for: makeCommand(targetLocked: false, errorX: 0.5, errorY: 0.2))

        XCTAssertEqual(stopped, .zero)
        XCTAssertEqual(calculator.previous, .zero)
    }

    private func makeCommand(
        targetLocked: Bool = true,
        errorX: Double,
        errorY: Double
    ) -> TrackingCommand {
        TrackingCommand(
            type: "tracking",
            version: "1.3",
            targetLocked: targetLocked,
            targetId: 7,
            errorX: errorX,
            errorY: errorY,
            confidence: 0.91,
            timestampMs: 1_781_770_000_000
        )
    }
}
