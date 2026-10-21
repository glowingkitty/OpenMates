// Web source: frontend/packages/ui/src/services/voiceCall.ts, voiceCallMessages.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.transcripts,
// video-call.chat.typed-input, video-call.audio.startup-buffer, video-call.provider.boundary, video-call.chat.skill-integration

import Foundation

/// Immutable personal-chat identity. A local new chat may construct this scope;
/// environment.prepare must confirm its encrypted canonical ownership before the
/// provider socket opens. Consent precedes all capture. No team/public calls.
struct NativeVoiceCallScope: Codable, Equatable, Hashable, Sendable {
    let accountID: String
    let profileID: String
    let workspaceGeneration: UUID
    let chatID: String
    let mateCategory: String
}

enum NativeVoiceCallError: String, Error, Equatable, Sendable {
    case invalidState, invalidResponse, scopeChanged, consentRequired, consentUnavailable
    case audioUnavailable, audioQueueFull, startupTimedOut, connectionLost
    case contextUnavailable, contextTooLarge, persistenceFailed, textRejected
    case callUnavailable, unsupportedTransport
}

/// JSON values are bounded at the frame/context boundaries. No Any or unchecked
/// Sendable payloads cross the controller/transport isolation boundaries.
indirect enum NativeVoiceCallJSON: Codable, Equatable, Sendable {
    case string(String), number(Double), bool(Bool), object([String: NativeVoiceCallJSON])
    case array([NativeVoiceCallJSON]), null

    init(from decoder: any Decoder) throws {
        let box = try decoder.singleValueContainer()
        if box.decodeNil() { self = .null }
        else if let value = try? box.decode(Bool.self) { self = .bool(value) }
        else if let value = try? box.decode(String.self) { self = .string(value) }
        else if let value = try? box.decode(Double.self), value.isFinite { self = .number(value) }
        else if let value = try? box.decode([String: Self].self) { self = .object(value) }
        else { self = .array(try box.decode([Self].self)) }
    }

    func encode(to encoder: any Encoder) throws {
        var box = encoder.singleValueContainer()
        switch self {
        case .string(let value): try box.encode(value)
        case .number(let value): try box.encode(value)
        case .bool(let value): try box.encode(value)
        case .object(let value): try box.encode(value)
        case .array(let value): try box.encode(value)
        case .null: try box.encodeNil()
        }
    }

    var string: String? { if case .string(let value) = self { value } else { nil } }
    var number: Double? { if case .number(let value) = self { value } else { nil } }
    var bool: Bool? { if case .bool(let value) = self { value } else { nil } }
    var object: [String: Self]? { if case .object(let value) = self { value } else { nil } }
}

typealias NativeVoiceCallFrame = [String: NativeVoiceCallJSON]

enum NativeVoiceCallWire {
    static let inputSampleRate = 16_000
    static let outputSampleRate = 24_000
    static let startupByteLimit = 16_000 * 2 * 10
    static let maximumAudioChunkBytes = 32_000 // <= 1 second PCM16 mono input
    static let maximumFrameBytes = 512 * 1_024

    static func encode(_ frame: NativeVoiceCallFrame) throws -> String {
        let data = try JSONEncoder().encode(frame)
        guard data.count <= maximumFrameBytes, let text = String(data: data, encoding: .utf8)
        else { throw NativeVoiceCallError.invalidResponse }
        return text
    }

    static func decode(_ text: String) throws -> NativeVoiceCallFrame {
        guard text.utf8.count <= maximumFrameBytes,
              let data = text.data(using: .utf8) else { throw NativeVoiceCallError.invalidResponse }
        do {
            let frame = try JSONDecoder().decode(NativeVoiceCallFrame.self, from: data)
            guard frame["type"]?.string != nil else { throw NativeVoiceCallError.invalidResponse }
            return frame
        } catch { throw NativeVoiceCallError.invalidResponse }
    }

    static func audio(_ data: Data) throws -> NativeVoiceCallFrame {
        guard !data.isEmpty, data.count % 2 == 0, data.count <= maximumAudioChunkBytes
        else { throw NativeVoiceCallError.invalidResponse }
        return ["type": .string("mic_audio"), "data": .string(data.base64EncodedString())]
    }
}

/// The same bounded JSON reference consumed by web and native Markdown parsers.
/// Validation is structural only. The controller's issued-event ledger plus the
/// caller's confirmed shared embed persistence establish commit authority.
struct NativeVoiceCallArtifactReference: Codable, Equatable, Sendable {
    let fields: NativeVoiceCallFrame
    var embedID: String { fields["embed_id"]?.string ?? "" }
    var type: String { fields["type"]?.string ?? "" }
    init(validating fields: NativeVoiceCallFrame, expectedID: String? = nil) throws {
        guard let id = fields["embed_id"]?.string,
              id.range(of: #"\A[A-Za-z0-9_-]{1,240}\z"#, options: .regularExpression) != nil,
              expectedID == nil || id == expectedID,
              let type = fields["type"]?.string, type != "unknown",
              type.range(of: #"\A[A-Za-z0-9_-]{1,96}\z"#, options: .regularExpression) != nil,
              fields["parent_embed_id"] == nil || fields["parent_embed_id"] == .null,
              try JSONEncoder().encode(fields).count <= 16_000 else { throw NativeVoiceCallError.invalidResponse }
        self.fields = fields
    }
    static func fromPayload(_ payload: NativeVoiceCallFrame) throws -> Self? {
        // Child payloads already belong to their parent's card.
        if let parent = payload["parent_embed_id"], parent != .null { return nil }
        guard let id = payload["embed_id"]?.string else { throw NativeVoiceCallError.invalidResponse }
        if let json = payload["embed_reference"]?.string {
            guard json.utf8.count <= 16_000, let bytes = json.data(using: .utf8) else { throw NativeVoiceCallError.invalidResponse }
            return try Self(validating: JSONDecoder().decode(NativeVoiceCallFrame.self, from: bytes), expectedID: id)
        }
        var fields: NativeVoiceCallFrame = ["embed_id": .string(id)]
        fields["type"] = payload["type"]
        for key in ["app_id", "skill_id", "focus_id", "focus_mode_name", "query", "provider", "title", "filename", "language", "file_path", "status"] {
            if let text = payload[key]?.string { fields[key] = .string(text) }
        }
        return try Self(validating: fields, expectedID: id)
    }
    var markdown: String {
        get throws {
            let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
            guard let json = String(data: try encoder.encode(fields), encoding: .utf8) else { throw NativeVoiceCallError.invalidResponse }
            return "```json\n" + json + "\n```"
        }
    }
}

struct NativeVoiceCallArtifactAssociation: Sendable {
    let callID: String
    let assistantMessageID: String
    let userMessageID: String
    let reference: NativeVoiceCallArtifactReference
    let createdAt: Int
    let modelName: String?
    let mateCategory: String?
    let mateName: String?
}

/// Optional capability keeps existing persistence adapters and fixtures honest:
/// unsupported adapters refuse association rather than inventing a durable row.
protocol NativeVoiceCallArtifactPersistence: Sendable {
    func associateArtifact(scope: NativeVoiceCallScope, value: NativeVoiceCallArtifactAssociation) async throws -> NativeVoiceCallTranscript
    func publishedTranscript(scope: NativeVoiceCallScope, callID: String, messageID: String) async throws -> NativeVoiceCallTranscript
}

struct NativeVoiceCallTranscript: Equatable, Sendable {
    enum Role: String, Codable, Sendable { case user, assistant }
    let callID: String
    let messageID: String
    let role: Role
    let text: String
    let final: Bool
    let interrupted: Bool
    let userMessageID: String?
    let createdAt: Int
    let modelName: String?
    let mateCategory: String?
    let mateName: String?
    var embedReferences: [NativeVoiceCallArtifactReference] = []
}

struct NativeVoiceCallSnapshot: Equatable, Sendable {
    enum Status: String, Sendable { case idle, connecting, live, ended, failed }
    var status: Status = .idle
    var scope: NativeVoiceCallScope?
    var callID: String?
    var muted = false
    var inputIdle = false
    var contextPaused = false
    var inputListening = false
    var processing = false
    var activeSeconds: TimeInterval = 0
    var error: NativeVoiceCallError?
}

enum NativeVoiceCallEvent: Sendable {
    case state(NativeVoiceCallSnapshot)
    /// Only emitted after ciphertext is durably stored. Canonical chat adapters
    /// publish this row without invoking their ordinary text-inference sender.
    case transcript(NativeVoiceCallTranscript)
    case typedRejected(messageID: String)
    case tool(NativeVoiceCallFrame)
    case usage(NativeVoiceCallFrame)
}

/// UUIDv7 layout uses milliseconds in the first 48 bits, RFC variant and version.
/// Cryptographically random trailing bytes are supplied by Foundation's UUID.
/// Calls retain this identity across transport retries and final transcript echo.
enum NativeVoiceCallMessageID {
    static func make(now: Date = Date(), random: UUID = UUID()) -> String {
        var tuple = random.uuid
        var bytes = withUnsafeBytes(of: &tuple) { Array($0) }
        let raw = now.timeIntervalSince1970 * 1_000
        let milliseconds = raw.isFinite ? UInt64(min(281_474_976_710_655, max(0, raw))) : 0
        for offset in 0..<6 { bytes[offset] = UInt8(truncatingIfNeeded: milliseconds >> ((5 - offset) * 8)) }
        bytes[6] = (bytes[6] & 0x0f) | 0x70
        bytes[8] = (bytes[8] & 0x3f) | 0x80
        let hex = bytes.map { String(format: "%02x", $0) }
        return hex[0..<4].joined() + "-" + hex[4..<6].joined() + "-" + hex[6..<8].joined()
            + "-" + hex[8..<10].joined() + "-" + hex[10..<16].joined()
    }
}
