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
        timestampMs: Int64? = nil
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
    }

    enum CodingKeys: String, CodingKey {
        case type, version, sequence, confidence
        case sourceVersion = "source_version"
        case targetLocked = "target_locked"
        case targetId = "target_id"
        case errorX = "error_x"
        case errorY = "error_y"
        case timestampMs = "timestamp_ms"
    }
}
