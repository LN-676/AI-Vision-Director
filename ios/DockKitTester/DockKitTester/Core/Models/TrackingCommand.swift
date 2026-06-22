import Foundation

struct TrackingCommand: Codable, Equatable, Sendable {
    let type: String
    let version: String?
    let targetLocked: Bool
    let targetId: Int?
    let errorX: Double
    let errorY: Double
    let confidence: Double
    let timestampMs: Int64?

    enum CodingKeys: String, CodingKey {
        case type, version, confidence
        case targetLocked = "target_locked"
        case targetId = "target_id"
        case errorX = "error_x"
        case errorY = "error_y"
        case timestampMs = "timestamp_ms"
    }
}
