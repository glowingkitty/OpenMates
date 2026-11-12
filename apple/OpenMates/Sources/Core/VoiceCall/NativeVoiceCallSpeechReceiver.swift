// Web source: frontend/packages/ui/src/services/assistantSpeechController.ts
// (handleAudio, handleTurnStatus, handleLiveSeal, flushEarlyAudio, setCallOwner),
// assistantSpeechStream.ts (isAssistantSpeechAudioEvent, AssistantSpeechStream.accept)
// and assistantSpeechQueue.ts (turn track, spokenWordProgress, turnPlaybackBoundary).
// Server contract: backend/shared/python_utils/assistant_speech_audio.py,
// backend/apps/audio/assistant_speech/realtime_turn.py and live_stream.py.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.audio.spoken-rich-response, video-call.audio.single-owner,
// video-call.audio.localized-waiting
//
// Thin mirror of the web shell's live-call speech receiver. Transient MP3 bytes
// from `assistant_speech_audio` frames are only handed to a playback sink; nothing
// is cached, persisted, synced or encrypted here. Live calls are server-push only:
// missing bytes fail the stream visibly and never request a stored generation.

import Foundation

/// One validated `assistant_speech_audio` payload (web `isAssistantSpeechAudioEvent`).
struct NativeVoiceCallSpeechAudioFrame: Equatable, Sendable {
    enum Kind: String, Sendable { case clause = "voice_prose_clause", waiting = "waiting_confirmation", turn = "voice_prose_turn" }
    enum Phase: String, Sendable { case start, chunk, end, error, alignment, words }
    struct ClauseTiming: Equatable, Sendable { let segmentID: String; let sequence: Int; let startMilliseconds: Int; let endMilliseconds: Int }

    let chatID: String
    let messageID: String
    let callID: String
    let segmentID: String
    let sequence: Int
    let kind: Kind
    let sourceVersion: Int
    let executionVersion: Int
    let attemptID: String
    let phase: Phase
    let chunkIndex: Int
    /// Decoded MP3 bytes of a `chunk` frame.
    let audio: Data?
    /// Display-only `[word_index, start_ms]` estimates on the turn timeline.
    let wordStarts: [[Int]]?
    let clauseTimings: [ClauseTiming]?

    static let maximumChunkBytes = 128 * 1_024
    static let maximumLifetimeMilliseconds = 600_000
    private static let maximumSafeInteger = 9_007_199_254_740_991

    init?(_ fields: [String: Any]) {
        func identity(_ key: String) -> String? {
            guard let value = fields[key] as? String, !value.isEmpty, value.count <= 128 else { return nil }
            return value
        }
        guard let chatID = identity("chat_id"), let messageID = identity("message_id"),
              let callID = identity("voice_call_id"), let segmentID = identity("segment_id"),
              let kind = (fields["kind"] as? String).flatMap(Kind.init(rawValue:)),
              fields["mime_type"] as? String == "audio/mpeg",
              let attemptID = fields["attempt_id"] as? String, Self.isUUID(attemptID),
              let sequence = Self.integer(fields["sequence"]),
              let sourceVersion = Self.integer(fields["source_version"]), sourceVersion >= 1,
              let executionVersion = Self.integer(fields["execution_version"]), executionVersion >= 1,
              let chunkIndex = Self.integer(fields["chunk_index"]), chunkIndex >= 0,
              let phase = (fields["phase"] as? String).flatMap(Phase.init(rawValue:)),
              chunkIndex <= (phase == .chunk ? 4_095 : 4_096) else { return nil }
        switch kind {
        case .waiting: guard sequence == -1 else { return nil }
        case .turn: guard sequence == 0 else { return nil }
        case .clause: guard (0...65_535).contains(sequence) else { return nil }
        }
        var wordStarts: [[Int]]?
        if phase == .words {
            guard kind == .turn, let rows = Self.wordStarts(fields["word_starts"]) else { return nil }
            wordStarts = rows
        } else if fields["word_starts"] != nil { return nil }
        var timings: [ClauseTiming]?
        if phase == .alignment {
            guard kind == .turn, let rows = Self.clauseTimings(fields["clause_timings"]) else { return nil }
            timings = rows
        } else if fields["clause_timings"] != nil { return nil }
        var audio: Data?
        if phase == .chunk {
            guard let encoded = fields["audio_data"] as? String, !encoded.isEmpty,
                  encoded.count <= (Self.maximumChunkBytes + 2) / 3 * 4,
                  let bytes = Data(base64Encoded: encoded), !bytes.isEmpty,
                  bytes.count <= Self.maximumChunkBytes,
                  bytes.base64EncodedString() == encoded else { return nil }
            audio = bytes
        } else if fields["audio_data"] != nil { return nil }
        self.chatID = chatID; self.messageID = messageID; self.callID = callID; self.segmentID = segmentID
        self.sequence = sequence; self.kind = kind; self.sourceVersion = sourceVersion
        self.executionVersion = executionVersion; self.attemptID = attemptID; self.phase = phase
        self.chunkIndex = chunkIndex; self.audio = audio; self.wordStarts = wordStarts; self.clauseTimings = timings
    }

    /// JSON integers only; booleans never pass as numbers (server `_integer`).
    static func integer(_ value: Any?) -> Int? {
        guard let value, ObjectIdentifier(type(of: value)) != ObjectIdentifier(Bool.self),
              let number = value as? Int, number >= -maximumSafeInteger, number <= maximumSafeInteger else { return nil }
        return number
    }
    static func isUUID(_ value: String) -> Bool {
        value.count == 36 && UUID(uuidString: value) != nil
    }
    /// 64 hex characters or a canonical UUID (web segment identity regex).
    static func isSegmentIdentity(_ value: String) -> Bool {
        if value.count == 64 { return value.allSatisfy { $0.isHexDigit && $0.isASCII } }
        return isUUID(value)
    }
    static func wordStarts(_ value: Any?) -> [[Int]]? {
        guard let rows = value as? [Any], (1...512).contains(rows.count) else { return nil }
        var previousIndex = -1, previousStart = 0, result: [[Int]] = []
        for row in rows {
            guard let pair = row as? [Any], pair.count == 2,
                  let index = integer(pair[0]), let start = integer(pair[1]),
                  index > previousIndex, index <= 65_535, start >= previousStart,
                  start <= maximumLifetimeMilliseconds else { return nil }
            previousIndex = index; previousStart = start; result.append([index, start])
        }
        return result
    }
    static func clauseTimings(_ value: Any?) -> [ClauseTiming]? {
        guard let rows = value as? [Any], rows.count <= 1_024 else { return nil }
        var previousSequence = -1, previousEnd = 0, ids = Set<String>(), result: [ClauseTiming] = []
        for row in rows {
            guard let object = row as? [String: Any],
                  Set(object.keys) == ["segment_id", "sequence", "start_ms", "end_ms"],
                  let id = object["segment_id"] as? String, isSegmentIdentity(id), !ids.contains(id),
                  let sequence = integer(object["sequence"]), sequence > previousSequence, sequence <= 65_535,
                  let start = integer(object["start_ms"]), let end = integer(object["end_ms"]),
                  start >= previousEnd, end > start, end <= maximumLifetimeMilliseconds else { return nil }
            previousSequence = sequence; previousEnd = end; ids.insert(id)
            result.append(.init(segmentID: id, sequence: sequence, startMilliseconds: start, endMilliseconds: end))
        }
        return result
    }
}

/// Owner-scoped `assistant_speech_status` fields used by live calls.
struct NativeVoiceCallSpeechStatus {
    let chatID: String?
    let messageID: String?
    let callID: String?
    let segmentID: String?
    let status: String?
    let sequence: Int?
    let kind: String?
    let sourceVersion: Int?
    let executionVersion: Int?
    let turnTrackID: String?
    let error: String?
    /// Raw `segments` rows; validated only by the sealed-membership rules.
    let segmentRows: [[String: Any]]?

    init(_ fields: [String: Any]) {
        chatID = fields["chat_id"] as? String; messageID = fields["message_id"] as? String
        callID = fields["voice_call_id"] as? String; segmentID = fields["segment_id"] as? String
        status = fields["status"] as? String; kind = fields["kind"] as? String
        sequence = NativeVoiceCallSpeechAudioFrame.integer(fields["sequence"])
        sourceVersion = NativeVoiceCallSpeechAudioFrame.integer(fields["source_version"])
        executionVersion = NativeVoiceCallSpeechAudioFrame.integer(fields["execution_version"])
        turnTrackID = fields["turn_track_id"] as? String; error = fields["error"] as? String
        if let rows = fields["segments"] as? [Any] {
            let objects = rows.compactMap { $0 as? [String: Any] }
            segmentRows = objects.count == rows.count ? objects : nil
        } else { segmentRows = nil }
    }
    var cancelled: Bool { ["cancelled", "deleted", "invalidated"].contains(status ?? "") }
}

enum NativeVoiceCallSpeechSinkEvent: Sendable, Equatable { case started, drained, failed }

/// Playback target for one stream at a time. `open` discards any previous stream;
/// `finish` means every byte was delivered and `.drained` follows once played out.
@MainActor
protocol NativeVoiceCallSpeechSink: AnyObject {
    func open(_ events: @escaping @MainActor (NativeVoiceCallSpeechSinkEvent) -> Void) throws
    func append(_ mp3: Data) throws
    func finish() throws
    func stop()
    /// Played position on the source-audio timeline (before the 1.25x tempo).
    var sourcePositionMilliseconds: Int { get }
}

@MainActor
final class NativeVoiceCallSpeechReceiver {
    struct SpokenWordProgress: Equatable, Sendable { let responseID: String; let words: Int; let began: Bool; let settled: Bool }

    static let liveSealError = "Speech is temporarily unavailable."
    private static let maximumEarlyBytes = 512 * 1_024
    private static let maximumEarlySegments = 8
    private static let maximumPendingBytes = 512 * 1_024
    private static let maximumClipBytes = 4 * 1_024 * 1_024
    private static let maximumTurnBytes = 16 * 1_024 * 1_024
    private static let maximumStoppedMessages = 50
    private static let maximumRejected = 256
    static let idleNanoseconds: UInt64 = 15_000_000_000
    static let turnLifetimeNanoseconds: UInt64 = 600_000_000_000

    private struct Stream {
        let segmentID: String
        let kind: NativeVoiceCallSpeechAudioFrame.Kind
        let attemptID: String
        let sourceVersion: Int
        let executionVersion: Int
        var nextIndex = 0
        var providerEnded = false
        var pending: [Data] = []
        var pendingBytes = 0
        var totalBytes = 0
        var timer: Task<Void, Never>?
    }
    private struct Turn {
        let id: String
        let messageID: String
        let sourceVersion: Int
        let executionVersion: Int
        var began = false, ended = false, failed = false, sealed = false
        var members: [String: Int] = [:]
        var timings: [String: NativeVoiceCallSpeechAudioFrame.ClauseTiming] = [:]
        var offsetMilliseconds = 0
        var wordStarts: [[Int]] = []
        var lifetime: Task<Void, Never>?
    }
    private struct Waiting { let id: String; let messageID: String; var done = false }
    private struct Seal { let messageID: String; let callID: String; let sourceVersion: Int; let members: [String: Int]; let trackID: String?; let failed: Bool }
    private struct Early { var frames: [NativeVoiceCallSpeechAudioFrame] = []; var bytes = 0; var timer: Task<Void, Never>? }

    weak var sink: NativeVoiceCallSpeechSink?
    /// Called on every observable change: speaking state, settlement, word progress.
    var onChange: (@MainActor () -> Void)?
    /// Late status for a stopped response: web sends `assistant_speech` cancel.
    var cancelResponse: (@MainActor (_ chatID: String, _ messageID: String) -> Void)?
    private let sleep: @MainActor @Sendable (UInt64) async throws -> Void

    private(set) var callOwner: String?
    private(set) var activeCallID: String?
    private(set) var messageID: String?
    private(set) var speaking = false
    private var turn: Turn?
    private var waiting: Waiting?
    private var seal: Seal?
    private var streams: [String: Stream] = [:]
    private var attached: String?
    private var attachGeneration = UUID()
    private var cancelledSegments = Set<String>()
    private var rejected = Set<String>()
    private var early: [String: Early] = [:]
    private var earlyBytes = 0
    private var stopped: [String] = []

    init(sleep: @escaping @MainActor @Sendable (UInt64) async throws -> Void = { try await Task.sleep(nanoseconds: $0) }) {
        self.sleep = sleep
    }

    // MARK: Call ownership (web setCallOwner)

    func setCallOwner(chatID: String?, callID: String?) {
        if activeCallID != nil, chatID == nil || chatID != callOwner || callID != activeCallID { dispose() }
        if chatID == nil || chatID != callOwner { activeCallID = nil }
        activeCallID = callID
        callOwner = chatID
        if chatID == nil { stopped.removeAll(); messageID = nil }
        publish()
    }

    /// Barge-in, cancel, turn discard or a new user turn: silence now and never
    /// let the same response resume.
    func stop() {
        if let messageID { remember(messageID) }
        dispose()
        messageID = nil
        publish()
    }

    /// True once this response's speech can no longer start or continue.
    func isSettled(messageID id: String) -> Bool {
        if stopped.contains(id) { return true }
        guard id == messageID else { return false }
        if let turn, turn.messageID == id { return turn.ended || turn.failed }
        return seal?.messageID == id
    }

    // MARK: Status (web handleStatus subset reachable in a live call)

    func receiveStatus(_ fields: [String: Any]) {
        let status = NativeVoiceCallSpeechStatus(fields)
        if let callID = status.callID, callOwner == nil || callID != activeCallID { return }
        if callOwner != nil, status.chatID != callOwner { return }
        if let id = status.messageID, stopped.contains(id) {
            if let chat = status.chatID, ["accepted", "queued"].contains(status.status ?? "") { cancelResponse?(chat, id) }
            return
        }
        if status.status == "sealed" { handleSeal(status); return }
        if status.kind == NativeVoiceCallSpeechAudioFrame.Kind.turn.rawValue, status.callID != nil { handleTurnStatus(status); return }
        if let turn, turn.messageID == status.messageID, status.kind == NativeVoiceCallSpeechAudioFrame.Kind.clause.rawValue {
            if let id = status.segmentID, let sequence = status.sequence, sequence >= 0, status.sourceVersion == turn.sourceVersion {
                registerTurnClause(id, sequence)
                if status.status == "error" || status.cancelled { failTurn() }
            }
            publish(); return
        }
        guard matchesSeal(messageID: status.messageID, segmentID: status.segmentID, sequence: status.sequence,
                          kind: status.kind, chatID: status.chatID, callID: status.callID, sourceVersion: status.sourceVersion) else { return }
        if status.kind == NativeVoiceCallSpeechAudioFrame.Kind.waiting.rawValue, status.sequence == -1 { handleWaitingStatus(status) }
    }

    private func handleWaitingStatus(_ status: NativeVoiceCallSpeechStatus) {
        guard let id = status.segmentID, let message = status.messageID, activeCallID != nil,
              status.callID == activeCallID, status.chatID == callOwner else { return }
        if status.cancelled || status.status == "error" {
            cancelledSegments.insert(id); dropEarly(id)
            if waiting?.id == id { finishWaiting() }
            return
        }
        // A waiting confirmation after the answer began is late; it never plays.
        if let turn, turn.messageID == message, turn.began || streams[turn.id] != nil { return }
        if messageID != message { supersede(with: message) }
        if waiting == nil { waiting = Waiting(id: id, messageID: message) }
        guard waiting?.id == id else { return }
        flushEarly(id)
    }

    private func handleTurnStatus(_ status: NativeVoiceCallSpeechStatus) {
        guard let id = status.segmentID, NativeVoiceCallSpeechAudioFrame.isSegmentIdentity(id),
              let activeCallID, status.callID == activeCallID, status.chatID == callOwner,
              let message = status.messageID, status.sequence == 0,
              let sourceVersion = status.sourceVersion, sourceVersion >= 1,
              let executionVersion = status.executionVersion, executionVersion >= 1 else { return }
        if let turn, turn.messageID == message,
           turn.id != id || turn.sourceVersion != sourceVersion || turn.executionVersion != executionVersion { return }
        if cancelledSegments.contains(id) { return }
        if turn?.messageID != message {
            supersede(with: message)
            var created = Turn(id: id, messageID: message, sourceVersion: sourceVersion, executionVersion: executionVersion)
            created.lifetime = timer(Self.turnLifetimeNanoseconds) { receiver in
                if receiver.turn?.id == id, receiver.turn?.messageID == message { receiver.failStream(id) }
            }
            turn = created
        }
        if status.status == "error" || status.cancelled {
            if status.cancelled { cancelledSegments.insert(id) }
            failTurn(); return
        }
        flushEarly(id)
        publish()
    }

    private func handleSeal(_ status: NativeVoiceCallSpeechStatus) {
        guard callOwner != nil, let activeCallID, status.callID == activeCallID, status.chatID == callOwner,
              let message = status.messageID, message.count <= 128,
              let sourceVersion = status.sourceVersion, sourceVersion >= 1,
              status.error == nil || status.error == Self.liveSealError,
              let rows = status.segmentRows, rows.count <= 1_024 else { return }
        let failed = status.error == Self.liveSealError
        var members: [String: Int] = [:], previous = -1
        for row in rows {
            guard Set(row.keys) == ["segment_id", "sequence", "kind", "source_version"],
                  let id = row["segment_id"] as? String, NativeVoiceCallSpeechAudioFrame.isSegmentIdentity(id),
                  row["kind"] as? String == NativeVoiceCallSpeechAudioFrame.Kind.clause.rawValue,
                  NativeVoiceCallSpeechAudioFrame.integer(row["source_version"]) == sourceVersion,
                  let sequence = NativeVoiceCallSpeechAudioFrame.integer(row["sequence"]),
                  sequence > previous, sequence <= 65_535, members[id] == nil,
                  failed || !cancelledSegments.contains(id) else { return }
            if let turn, turn.messageID == message, let known = turn.members[id], known != sequence { return }
            members[id] = sequence; previous = sequence
        }
        if let turn, turn.messageID == message, status.turnTrackID != turn.id { failTurn(); return }
        if let existing = seal, existing.messageID == message,
           existing.callID != activeCallID || existing.sourceVersion != sourceVersion || existing.members != members
            || existing.failed != failed || existing.trackID != status.turnTrackID { return }
        if messageID != message { supersede(with: message) }
        seal = Seal(messageID: message, callID: activeCallID, sourceVersion: sourceVersion, members: members,
                    trackID: status.turnTrackID, failed: failed)
        if let track = status.turnTrackID {
            guard var current = turn, current.id == track, current.messageID == message else { failTurn(); publish(); return }
            if failed { failTurn(); return }
            if current.timings.values.contains(where: { members[$0.segmentID] != $0.sequence }) { failTurn(); return }
            current.members = members; current.sealed = true; turn = current
        }
        publish()
    }

    private func registerTurnClause(_ id: String, _ sequence: Int) {
        guard var current = turn, !current.sealed, !current.failed else { return }
        if (current.members[id] == nil && current.members.count >= 1_024)
            || current.members.contains(where: { $0.key != id && $0.value == sequence })
            || (current.members[id].map { $0 != sequence } ?? false) { failTurn(); return }
        current.members[id] = sequence; turn = current
    }

    private func matchesSeal(messageID: String?, segmentID: String?, sequence: Int?, kind: String?,
                             chatID: String?, callID: String?, sourceVersion: Int?) -> Bool {
        guard let seal, messageID == seal.messageID else { return true }
        if seal.failed { return false }
        guard let segmentID, sequence != -1 else { return true }
        if kind == NativeVoiceCallSpeechAudioFrame.Kind.turn.rawValue {
            return segmentID == seal.trackID && chatID == callOwner && callID == seal.callID && sourceVersion == seal.sourceVersion
        }
        return chatID == callOwner && callID == seal.callID && kind == NativeVoiceCallSpeechAudioFrame.Kind.clause.rawValue
            && sourceVersion == seal.sourceVersion && seal.members[segmentID] == sequence
    }

    // MARK: Audio (web handleAudio + AssistantSpeechStream.accept)

    func receiveAudio(_ fields: [String: Any]) {
        guard let frame = NativeVoiceCallSpeechAudioFrame(fields) else { return }
        receive(frame)
    }

    func receive(_ frame: NativeVoiceCallSpeechAudioFrame) {
        guard let activeCallID, frame.callID == activeCallID, frame.chatID == callOwner,
              !stopped.contains(frame.messageID) else { return }
        // Prose arrives only on the turn track in mp3_turn_stream_v2.
        if frame.kind == .clause { return }
        if let turn, turn.messageID == frame.messageID, frame.kind == .turn,
           frame.segmentID != turn.id || frame.sourceVersion != turn.sourceVersion
            || frame.executionVersion != turn.executionVersion { return }
        guard matchesSeal(messageID: frame.messageID, segmentID: frame.segmentID, sequence: frame.sequence,
                          kind: frame.kind.rawValue, chatID: frame.chatID, callID: frame.callID,
                          sourceVersion: frame.sourceVersion),
              !rejected.contains(frame.segmentID), !cancelledSegments.contains(frame.segmentID) else { return }
        guard bound(frame.segmentID) else { buffer(frame); return }
        guard frame.messageID == messageID else { return }
        if let current = streams[frame.segmentID] {
            if frame.sourceVersion < current.sourceVersion
                || (frame.sourceVersion == current.sourceVersion && frame.executionVersion < current.executionVersion)
                || (frame.sourceVersion == current.sourceVersion && frame.executionVersion == current.executionVersion
                    && frame.attemptID != current.attemptID) { return }
            if frame.attemptID == current.attemptID {
                if frame.phase != .start { accept(frame) }
                return
            }
        }
        // A new provider attempt must begin at chunk zero; anything else is a gap.
        guard frame.phase == .start, frame.chunkIndex == 0 else { reject(frame.segmentID); return }
        retire(frame.segmentID)
        var stream = Stream(segmentID: frame.segmentID, kind: frame.kind, attemptID: frame.attemptID,
                            sourceVersion: frame.sourceVersion, executionVersion: frame.executionVersion)
        stream.timer = idleTimer(frame.segmentID, attempt: frame.attemptID)
        streams[frame.segmentID] = stream
    }

    private func bound(_ id: String) -> Bool {
        if let turn, turn.id == id, turn.messageID == messageID { return true }
        if let waiting, waiting.id == id, waiting.messageID == messageID, !waiting.done { return true }
        return false
    }

    private func accept(_ frame: NativeVoiceCallSpeechAudioFrame) {
        guard var stream = streams[frame.segmentID] else { return }
        if stream.providerEnded || frame.phase == .error { failStream(frame.segmentID); return }
        guard frame.chunkIndex == stream.nextIndex else { failStream(frame.segmentID); return }
        switch frame.phase {
        case .start, .error: return
        case .words:
            if let rows = frame.wordStarts { addWordStarts(frame.segmentID, rows) }
            publish(); return
        case .alignment:
            if let rows = frame.clauseTimings { updateTimings(rows) }
            return
        case .end:
            stream.providerEnded = true
            stream.timer?.cancel(); stream.timer = nil
            streams[frame.segmentID] = stream
            if stream.nextIndex == 0 { failStream(frame.segmentID); return }
            if attached == frame.segmentID {
                do { try sink?.finish() } catch { failStream(frame.segmentID) }
            } else { advance() }
        case .chunk:
            guard let bytes = frame.audio else { failStream(frame.segmentID); return }
            let limit = stream.kind == .turn ? Self.maximumTurnBytes : Self.maximumClipBytes
            guard stream.totalBytes + bytes.count <= limit,
                  stream.pendingBytes + bytes.count <= Self.maximumPendingBytes else { failStream(frame.segmentID); return }
            stream.totalBytes += bytes.count; stream.nextIndex += 1
            stream.timer?.cancel(); stream.timer = idleTimer(frame.segmentID, attempt: stream.attemptID)
            if attached == frame.segmentID {
                streams[frame.segmentID] = stream
                do { try sink?.append(bytes) } catch { failStream(frame.segmentID) }
            } else {
                stream.pending.append(bytes); stream.pendingBytes += bytes.count
                streams[frame.segmentID] = stream
                advance()
            }
        }
    }

    // MARK: Playback ownership

    /// The answer's turn track preempts a waiting confirmation as soon as it has
    /// bytes (the server stops the waiting clip at the turn's first audio).
    private func advance() {
        let candidate: String?
        if let turn, turn.messageID == messageID, !turn.failed, !turn.ended,
           let stream = streams[turn.id], stream.nextIndex > 0 { candidate = turn.id }
        else if let waiting, waiting.messageID == messageID, !waiting.done,
                let stream = streams[waiting.id], stream.nextIndex > 0 { candidate = waiting.id }
        else { candidate = nil }
        guard let candidate, candidate != attached else { return }
        if let previous = attached { detach(previous) }
        guard let sink, var stream = streams[candidate] else { return }
        let generation = UUID(); attachGeneration = generation
        do {
            try sink.open { [weak self] event in self?.sinkEvent(event, segmentID: candidate, generation: generation) }
            attached = candidate
            let pending = stream.pending
            stream.pending = []; stream.pendingBytes = 0; streams[candidate] = stream
            for bytes in pending { try sink.append(bytes) }
            if stream.providerEnded { try sink.finish() }
        } catch { failStream(candidate) }
    }

    private func detach(_ id: String) {
        attachGeneration = UUID(); attached = nil
        sink?.stop()
        if speaking { speaking = false; publish() }
        if waiting?.id == id { finishWaiting(silently: true) }
    }

    private func sinkEvent(_ event: NativeVoiceCallSpeechSinkEvent, segmentID: String, generation: UUID) {
        guard attachGeneration == generation, attached == segmentID else { return }
        switch event {
        case .started:
            if turn?.id == segmentID { turn?.began = true }
            speaking = true; publish()
        case .drained:
            attached = nil; attachGeneration = UUID(); speaking = false
            streams[segmentID]?.timer?.cancel(); streams.removeValue(forKey: segmentID)
            if turn?.id == segmentID {
                turn?.offsetMilliseconds = sink?.sourcePositionMilliseconds ?? 0
                turn?.ended = true; turn?.lifetime?.cancel()
            }
            if waiting?.id == segmentID { waiting?.done = true }
            publish(); advance()
        case .failed:
            failStream(segmentID)
        }
    }

    private func failStream(_ id: String) {
        if turn?.id == id { failTurn(); return }
        streams[id]?.timer?.cancel(); streams.removeValue(forKey: id)
        if attached == id { detach(id) }
        if waiting?.id == id { finishWaiting() }
        publish()
    }

    private func failTurn() {
        guard var current = turn else { return }
        let wasAttached = attached == current.id
        if wasAttached && current.began { current.offsetMilliseconds = sink?.sourcePositionMilliseconds ?? current.offsetMilliseconds }
        current.failed = true; current.lifetime?.cancel(); turn = current
        streams[current.id]?.timer?.cancel(); streams.removeValue(forKey: current.id)
        if wasAttached { detach(current.id) }
        if rejected.count < Self.maximumRejected { rejected.insert(current.id) }
        publish()
    }

    private func finishWaiting(silently: Bool = false) {
        guard let current = waiting else { return }
        waiting?.done = true
        streams[current.id]?.timer?.cancel(); streams.removeValue(forKey: current.id)
        dropEarly(current.id)
        if !silently { advance() }
    }

    private func retire(_ id: String) {
        streams[id]?.timer?.cancel(); streams.removeValue(forKey: id)
        if attached == id { detach(id) }
    }

    private func reject(_ id: String) {
        dropEarly(id)
        if rejected.count < Self.maximumRejected { rejected.insert(id) }
        if turn?.id == id { failTurn(); return }
        failStream(id)
    }

    // MARK: Early audio (web earlyAudio)

    private func buffer(_ frame: NativeVoiceCallSpeechAudioFrame) {
        let size = frame.audio?.count ?? 0
        let existing = early[frame.segmentID]
        if (existing == nil && early.count >= Self.maximumEarlySegments)
            || earlyBytes + size > Self.maximumEarlyBytes || (existing?.frames.count ?? 0) >= 256 {
            reject(frame.segmentID); return
        }
        var entry = existing ?? Early()
        if existing == nil {
            let id = frame.segmentID
            entry.timer = timer(Self.idleNanoseconds) { receiver in
                if receiver.early[id] != nil { receiver.reject(id) }
            }
        }
        entry.frames.append(frame); entry.bytes += size; earlyBytes += size
        early[frame.segmentID] = entry
    }

    private func flushEarly(_ id: String) {
        guard let frames = early[id]?.frames else { return }
        dropEarly(id)
        for frame in frames { receive(frame) }
    }

    private func dropEarly(_ id: String) {
        guard let entry = early.removeValue(forKey: id) else { return }
        entry.timer?.cancel(); earlyBytes -= entry.bytes
    }

    // MARK: Turn timeline (web AssistantSpeechQueue turn track)

    private func addWordStarts(_ id: String, _ rows: [[Int]]) {
        guard var current = turn, current.id == id, !current.failed, let first = rows.first else { return }
        if let last = current.wordStarts.last, first[0] <= last[0] || first[1] < last[1] { return }
        guard current.wordStarts.count + rows.count <= 65_536 else { return }
        current.wordStarts.append(contentsOf: rows); turn = current
    }

    private func updateTimings(_ rows: [NativeVoiceCallSpeechAudioFrame.ClauseTiming]) {
        guard var current = turn, !current.failed else { return }
        var merged = current.timings
        for row in rows {
            if current.members[row.segmentID] != row.sequence { failTurn(); return }
            if let prior = merged[row.segmentID], prior != row { failTurn(); return }
            merged[row.segmentID] = row
        }
        var previousEnd = 0
        for row in merged.values.sorted(by: { $0.sequence < $1.sequence }) {
            if row.startMilliseconds < previousEnd { failTurn(); return }
            previousEnd = row.endMilliseconds
        }
        current.timings = merged; turn = current
    }

    private var turnTimeMilliseconds: Int {
        guard let turn else { return 0 }
        return attached == turn.id ? max(0, sink?.sourcePositionMilliseconds ?? 0) : turn.offsetMilliseconds
    }

    /// Display-only words of the live turn already reached by playback time.
    var spokenWordProgress: SpokenWordProgress? {
        guard let turn, let messageID, turn.messageID == messageID else { return nil }
        let settled = turn.ended || turn.failed
        guard turn.began else { return .init(responseID: messageID, words: 0, began: false, settled: settled) }
        let time = turnTimeMilliseconds
        var low = 0, high = turn.wordStarts.count
        while low < high {
            let middle = (low + high) / 2
            if turn.wordStarts[middle][1] <= time { low = middle + 1 } else { high = middle }
        }
        return .init(responseID: messageID, words: low > 0 ? turn.wordStarts[low - 1][0] + 1 : 0, began: true, settled: settled)
    }

    /// Actual playback coverage of the turn (web turnPlaybackBoundary). Word
    /// estimates never grant heard coverage.
    func heardBoundary(messageID id: String?) -> NativeVoiceCallHeardBoundary? {
        guard let turn, let id, turn.messageID == id, turn.began else { return nil }
        let time = turnTimeMilliseconds
        let completeAll = turn.ended && turn.sealed && !turn.failed
        let timings = Array(turn.timings.values)
        let completed = completeAll ? Array(turn.members.values)
            : timings.filter { $0.endMilliseconds <= time }.map(\.sequence)
        let active = completeAll ? nil : timings.first { $0.startMilliseconds <= time && time < $0.endMilliseconds }
        return .init(assistantMessageID: id, completedSequences: Set(completed), activeSequence: active?.sequence,
                     activeOffsetMilliseconds: active.map { min(3_600_000, time - $0.startMilliseconds) } ?? 0)
    }

    // MARK: Lifecycle

    private func supersede(with next: String) {
        guard let current = messageID, current != next else { messageID = next; return }
        remember(current)
        let keep = early.filter { $0.value.frames.first?.messageID == next }
        for id in early.keys where keep[id] == nil { dropEarly(id) }
        disposePlayback()
        seal = seal?.messageID == next ? seal : nil
        messageID = next
    }

    private func disposePlayback() {
        if attached != nil { attachGeneration = UUID(); attached = nil; sink?.stop() }
        for stream in streams.values { stream.timer?.cancel() }
        streams.removeAll()
        turn?.lifetime?.cancel(); turn = nil; waiting = nil
        speaking = false
    }

    private func dispose() {
        disposePlayback()
        for id in Array(early.keys) { dropEarly(id) }
        seal = nil; rejected.removeAll(); cancelledSegments.removeAll()
    }

    private func remember(_ id: String) {
        stopped.removeAll { $0 == id }; stopped.append(id)
        if stopped.count > Self.maximumStoppedMessages { stopped.removeFirst() }
    }

    private func idleTimer(_ id: String, attempt: String) -> Task<Void, Never> {
        timer(Self.idleNanoseconds) { receiver in
            if let stream = receiver.streams[id], stream.attemptID == attempt, !stream.providerEnded { receiver.failStream(id) }
        }
    }

    private func timer(_ nanoseconds: UInt64,
                       _ fire: @escaping @MainActor @Sendable (NativeVoiceCallSpeechReceiver) -> Void) -> Task<Void, Never> {
        let sleep = sleep
        return Task { @MainActor [weak self] in
            do { try await sleep(nanoseconds) } catch { return }
            guard !Task.isCancelled, let self else { return }
            fire(self)
        }
    }

    private func publish() { onChange?() }
}
