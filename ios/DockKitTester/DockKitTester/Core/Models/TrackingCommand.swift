import Foundation

struct TrackingCommand: Codable, Equatable, Sendable {
    let type: String
    let version: String?
    let sourceVersion: String?
    let sequence: Int64?
    let targetLocked: Bool
    let targetId: Int?
    let errorX: Double
    let errorY: Double
    let confidence: Double
    let timestampMs: Int64?
    let frameWidth: Int?
    let frameHeight: Int?
    let targetX: Double?
    let targetY: Double?
    let bboxWidth: Double?
    let bboxHeight: Double?

    init(
        type: String,
        version: String? = nil,
        sourceVersion: String? = nil,
        sequence: Int64? = nil,
        targetLocked: Bool,
        targetId: Int? = nil,
        errorX: Double,
        errorY: Double,
        confidence: Double,
        timestampMs: Int64? = nil,
        frameWidth: Int? = nil,
        frameHeight: Int? = nil,
        targetX: Double? = nil,
        targetY: Double? = nil,
        bboxWidth: Double? = nil,
        bboxHeight: Double? = nil
    ) {
        self.type = type
        self.version = version
        self.sourceVersion = sourceVersion
        self.sequence = sequence
        self.targetLocked = targetLocked
        self.targetId = targetId
        self.errorX = errorX
        self.errorY = errorY
        self.confidence = confidence
        self.timestampMs = timestampMs
        self.frameWidth = frameWidth
        self.frameHeight = frameHeight
        self.targetX = targetX
        self.targetY = targetY
        self.bboxWidth = bboxWidth
        self.bboxHeight = bboxHeight
    }

    enum CodingKeys: String, CodingKey {
        case type, version, sequence, confidence
        case sourceVersion = "source_version"
        case targetLocked = "target_locked"
        case targetId = "target_id"
        case errorX = "error_x"
        case errorY = "error_y"
        case timestampMs = "timestamp_ms"
        case frameWidth = "frame_width"
        case frameHeight = "frame_height"
        case targetX = "target_x"
        case targetY = "target_y"
        case bboxWidth = "bbox_width"
        case bboxHeight = "bbox_height"
    }

    func isTrackable(minimumConfidence: Double = 0.20) -> Bool {
        targetLocked
            && confidence >= minimumConfidence
            && confidence.isFinite
            && errorX.isFinite
            && errorY.isFinite
    }
}

struct MotorStatusMessage: Codable, Equatable, Sendable {
    let type = "motor_status"
    let docked: Bool
    let manualReady: Bool
    let systemTrackingEnabled: Bool?
    let lastError: String?
    let timestampMs: Int64

    enum CodingKeys: String, CodingKey {
        case type, docked
        case manualReady = "manual_ready"
        case systemTrackingEnabled = "system_tracking_enabled"
        case lastError = "last_error"
        case timestampMs = "timestamp_ms"
    }
}

struct ControlMessage: Codable, Equatable, Sendable {
    let type = "control"
    let action: String
    let source: String?
    let gid: Int?
    let timestampMs: Int64

    init(action: String, source: String? = nil, gid: Int? = nil) {
        self.action = action
        self.source = source
        self.gid = gid
        self.timestampMs = Int64(Date().timeIntervalSince1970 * 1_000)
    }

    enum CodingKeys: String, CodingKey {
        case type, action, source, gid
        case timestampMs = "timestamp_ms"
    }
}

struct TrackingCommandSequenceValidator: Sendable {
    private(set) var lastSequence: Int64?

    mutating func accept(_ command: TrackingCommand) -> Bool {
        guard let sequence = command.sequence else { return true }
        guard lastSequence.map({ sequence > $0 }) ?? true else { return false }
        lastSequence = sequence
        return true
    }

    mutating func reset() {
        lastSequence = nil
    }
}
