// Watch chat runtime and offline cache.
// Provides the portable data layer for the standalone watchOS chat shell while
// staying small enough to unit test from the existing Apple unit-test target.
// The runtime fetches recent chats/messages directly from the backend, unwraps
// per-chat keys from the Watch-local master key, and keeps a local JSON snapshot
// for offline startup. This layer never logs plaintext.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.browse-search-open, apple-watch.chats.new-text-reply, apple-watch.chats.audio-reply, apple-watch.offline.recent-cohort
// Specification: specifications/features/apple-recent-offline-chats/specification.yml
// Assertions: apple-offline.recent-cohort, apple-offline.interruption-isolation
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.action.routing-coherent, apple-notifications.delivery.idempotent-visible

import CryptoKit
import Foundation
import SwiftUI

enum WatchUIContract {
    static let pairLoginIdentifiers = [
        "watch-pair-login",
        "watch-pair-confirm-iphone-title",
        "watch-pair-manual-fallback",
        "watch-pair-login-without-iphone-button",
        "watch-pair-token",
        "watch-pair-url",
        "watch-pair-waiting-label",
        "watch-pair-pin-input",
        "watch-pair-refresh-button",
        "watch-pair-self-host-button",
        "watch-pair-self-host-input",
        "watch-pair-self-host-connect-button",
        "watch-pair-self-host-cancel-button",
        "watch-pair-self-host-error",
        "watch-pair-use-production-button",
    ]

    static let chatFlowIdentifiers = [
        "watch-chat-shell",
        "watch-chat-list",
        "watch-chat-search-button",
        "watch-chat-search-input",
        "watch-chat-settings-button",
        "watch-chat-row-<id>",
        "watch-chat-thread",
        "watch-message-input",
        "watch-message-send",
        "watch-new-chat-button",
        "watch-audio-record-button",
        "watch-audio-send-button",
        "watch-pending-audio-embed",
    ]

    static let audioComposerIdentifiers = [
        "watch-audio-record-button",
        "watch-audio-recording-screen",
        "watch-audio-recording-duration",
        "watch-audio-cancel-button",
        "watch-audio-send-button",
        "watch-audio-error",
        "watch-audio-retry-button",
        "watch-audio-back-button",
        "watch-pending-audio-embed",
    ]

    static let embedPreviewIdentifiers = [
        "watch-embed-preview",
        "watch-embed-continuation",
        "watch-embed-open-device",
        "watch-embed-qr-payload",
        "watch-embed-notification-request",
    ]

    static let forbiddenProductChrome = [
        "List",
        "Form",
        "NavigationStack",
        "TabView",
        "navigationTitle",
        "toolbar",
    ]

    static let designEvidence = [
        "Dark Watch shell uses Color.grey100, Color.grey90, Color.grey0, Color.buttonPrimary, and generated spacing/typography tokens.",
        "Chat and embed surfaces use ScrollView/LazyVStack/custom buttons instead of List, Form, default navigation chrome, or stock product controls.",
        "Embed previews preserve OpenMates app/embed semantics through WatchEmbedPreviewModel and route detail actions to continuation metadata instead of rich fullscreen Watch consumption.",
        "Audio recording uploads and transcribes on the server, then sends one encrypted audio-recording embed turn.",
    ]
}

struct WatchChatSummary: Codable, Equatable, Identifiable, Sendable {
    let id: String
    var title: String?
    var lastMessageAt: String?
    var preview: String?
    var isPinned: Bool
    var encryptedTitle: String?
    var encryptedPreview: String?
    var encryptedChatKey: String?
    var messagesV: Int = 0
    var titleV: Int = 0
    var metadataV: Int = 0
    var lastEditedOverallTimestamp: String? = nil
    var parentID: String? = nil
    var isSubChat: Bool = false
    var offlineWrappedChatKey: String? = nil
    var category: String? = nil
    var icon: String? = nil
    var encryptedCategory: String? = nil
    var encryptedIcon: String? = nil
    var isSupportChat: Bool = false
    var isSharedRecipient: Bool = false

    init(id: String, title: String?, lastMessageAt: String?, preview: String?, isPinned: Bool,
         encryptedTitle: String?, encryptedPreview: String?, encryptedChatKey: String?,
         messagesV: Int = 0, titleV: Int = 0, metadataV: Int = 0) {
        self.id = id; self.title = title; self.lastMessageAt = lastMessageAt
        self.preview = preview; self.isPinned = isPinned; self.encryptedTitle = encryptedTitle
        self.encryptedPreview = encryptedPreview; self.encryptedChatKey = encryptedChatKey
        self.messagesV = messagesV; self.titleV = titleV; self.metadataV = metadataV
    }

    private enum CodingKeys: String, CodingKey {
        case id, title, lastMessageAt, preview, isPinned, encryptedTitle, encryptedPreview,
             encryptedChatKey, messagesV, titleV, metadataV, lastEditedOverallTimestamp, parentID, isSubChat, offlineWrappedChatKey, category, icon, encryptedCategory, encryptedIcon, isSupportChat, isSharedRecipient
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(id: try c.decode(String.self, forKey: .id),
                  title: try c.decodeIfPresent(String.self, forKey: .title),
                  lastMessageAt: try c.decodeIfPresent(String.self, forKey: .lastMessageAt),
                  preview: try c.decodeIfPresent(String.self, forKey: .preview),
                  isPinned: try c.decode(Bool.self, forKey: .isPinned),
                  encryptedTitle: try c.decodeIfPresent(String.self, forKey: .encryptedTitle),
                  encryptedPreview: try c.decodeIfPresent(String.self, forKey: .encryptedPreview),
                  encryptedChatKey: try c.decodeIfPresent(String.self, forKey: .encryptedChatKey),
                  messagesV: try c.decodeIfPresent(Int.self, forKey: .messagesV) ?? 0,
                  titleV: try c.decodeIfPresent(Int.self, forKey: .titleV) ?? 0,
                  metadataV: try c.decodeIfPresent(Int.self, forKey: .metadataV) ?? 0)
        lastEditedOverallTimestamp = try c.decodeIfPresent(String.self, forKey: .lastEditedOverallTimestamp)
        parentID = try c.decodeIfPresent(String.self, forKey: .parentID)
        isSubChat = try c.decodeIfPresent(Bool.self, forKey: .isSubChat) ?? false
        offlineWrappedChatKey = try c.decodeIfPresent(String.self, forKey: .offlineWrappedChatKey)
        category = try c.decodeIfPresent(String.self, forKey: .category)
        icon = try c.decodeIfPresent(String.self, forKey: .icon)
        encryptedCategory = try c.decodeIfPresent(String.self, forKey: .encryptedCategory)
        encryptedIcon = try c.decodeIfPresent(String.self, forKey: .encryptedIcon)
        isSupportChat = try c.decodeIfPresent(Bool.self, forKey: .isSupportChat) ?? false
        isSharedRecipient = try c.decodeIfPresent(Bool.self, forKey: .isSharedRecipient) ?? false
    }
}

struct WatchChatMessage: Codable, Equatable, Identifiable, Sendable {
    enum Role: String, Codable, Sendable {
        case user
        case assistant
        case system
    }

    let id: String
    let chatId: String
    let role: Role
    var content: String?
    var encryptedContent: String?
    var embedRefs: [WatchEmbedRef]? = nil
    let createdAt: String
    var isPending: Bool
}

struct WatchEmbedRef: Codable, Equatable, Identifiable, @unchecked Sendable {
    let id: String
    let type: String
    let status: String?
    let data: [String: AnyCodable]?
}

struct WatchPendingTextSend: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let chatId: String
    let messageId: String
    let encryptedContent: String
    let encryptedChatKey: String
    let createdAt: String
    var preflightJSON: Data = Data()
    var inferenceJSON: Data = Data()
    var encryptedPreparedTurn: String?

    init(id: String, chatId: String, messageId: String, encryptedContent: String,
         encryptedChatKey: String, createdAt: String, preflightJSON: Data = Data(),
         inferenceJSON: Data = Data(), encryptedPreparedTurn: String? = nil) {
        self.id = id; self.chatId = chatId; self.messageId = messageId
        self.encryptedContent = encryptedContent; self.encryptedChatKey = encryptedChatKey
        self.createdAt = createdAt; self.preflightJSON = preflightJSON
        self.inferenceJSON = inferenceJSON
        self.encryptedPreparedTurn = encryptedPreparedTurn
    }

    private enum CodingKeys: String, CodingKey {
        case id, chatId, messageId, encryptedContent, encryptedChatKey,
             createdAt, preflightJSON, inferenceJSON, encryptedPreparedTurn
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(id: try c.decode(String.self, forKey: .id),
                  chatId: try c.decode(String.self, forKey: .chatId),
                  messageId: try c.decode(String.self, forKey: .messageId),
                  encryptedContent: try c.decode(String.self, forKey: .encryptedContent),
                  encryptedChatKey: try c.decode(String.self, forKey: .encryptedChatKey),
                  createdAt: try c.decode(String.self, forKey: .createdAt),
                  preflightJSON: try c.decodeIfPresent(Data.self, forKey: .preflightJSON) ?? Data(),
                  inferenceJSON: try c.decodeIfPresent(Data.self, forKey: .inferenceJSON) ?? Data(),
                  encryptedPreparedTurn: try c.decodeIfPresent(String.self, forKey: .encryptedPreparedTurn))
    }
}

struct WatchUploadedFileVariant: Codable, Equatable, Sendable {
    let s3Key: String
    let sizeBytes: Int?
    let width: Int?
    let height: Int?
    let format: String?
}

struct WatchUploadedAudio: Codable, Equatable, Sendable {
    let embedId: String
    let filename: String
    let contentType: String
    let contentHash: String?
    let files: [String: WatchUploadedFileVariant]
    let s3BaseUrl: String
    let aesKey: String
    let aesNonce: String
    let vaultWrappedAesKey: String
}

struct WatchTranscriptionWaveform: Decodable, Equatable, Sendable {
    let version: Int
    let kind: String
    let samples: [Int]
    let durationSeconds: TimeInterval?

    var contentObject: [String: Any] {
        var value: [String: Any] = ["version": version, "kind": kind, "samples": samples]
        if let durationSeconds { value["duration_seconds"] = durationSeconds }
        return value
    }
}

struct WatchTranscriptionMetadata: Decodable, Equatable, Sendable {
    let title: String?
    let transcript: String?
    let transcriptOriginal: String?
    let transcriptCorrected: String?
    let useCorrected: Bool?
    let model: String?
    let correctionModel: String?
    let waveform: WatchTranscriptionWaveform?

    var displayTranscript: String? {
        if useCorrected == true, let transcriptCorrected, !transcriptCorrected.isEmpty {
            return transcriptCorrected
        }
        return transcript
    }
}

struct WatchPendingAudioEmbed: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let filename: String
    let transcript: String?
    let duration: TimeInterval
    let content: String

    var markdownReference: String {
        "```json\n{\"type\": \"audio-recording\", \"embed_id\": \"\(id)\"}\n```"
    }

    static func from(upload: WatchUploadedAudio, transcription: WatchTranscriptionMetadata?, duration: TimeInterval) -> WatchPendingAudioEmbed {
        let contentObject = audioContentObject(upload: upload, transcription: transcription, duration: duration)
        return WatchPendingAudioEmbed(
            id: upload.embedId,
            filename: upload.filename,
            transcript: transcription?.displayTranscript,
            duration: duration,
            content: jsonString(contentObject)
        )
    }

    private static func audioContentObject(
        upload: WatchUploadedAudio,
        transcription: WatchTranscriptionMetadata?,
        duration: TimeInterval
    ) -> [String: Any] {
        var object: [String: Any] = [
            "app_id": "audio",
            "type": "audio-recording",
            "status": "finished",
            "filename": upload.filename,
            "s3_base_url": upload.s3BaseUrl,
            "files": upload.files.mapValues { variant in
                var item: [String: Any] = ["s3_key": variant.s3Key]
                if let sizeBytes = variant.sizeBytes { item["size_bytes"] = sizeBytes }
                if let width = variant.width { item["width"] = width }
                if let height = variant.height { item["height"] = height }
                if let format = variant.format { item["format"] = format }
                return item
            },
            "aes_key": upload.aesKey,
            "aes_nonce": upload.aesNonce,
            "vault_wrapped_aes_key": upload.vaultWrappedAesKey,
            "skill_id": "transcribe",
            "duration": duration,
        ]
        if let contentHash = upload.contentHash { object["content_hash"] = contentHash }
        if let transcription {
            if let title = transcription.title { object["title"] = title }
            if let transcript = transcription.transcript { object["transcript"] = transcript }
            if let display = transcription.displayTranscript { object["transcription"] = display }
            if let original = transcription.transcriptOriginal { object["transcript_original"] = original }
            if let corrected = transcription.transcriptCorrected { object["transcript_corrected"] = corrected }
            if let useCorrected = transcription.useCorrected { object["use_corrected"] = useCorrected }
            if let model = transcription.model { object["model"] = model }
            if let correctionModel = transcription.correctionModel { object["correction_model"] = correctionModel }
            if let waveform = transcription.waveform { object["waveform"] = waveform.contentObject }
        }
        return object
    }

    private static func jsonString(_ object: [String: Any]) -> String {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
              let string = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return string
    }
}

// Draft bodies use the account master key (Format D), never durable plaintext.
struct WatchEncryptedDraft: Codable, Equatable, Sendable {
    var encryptedMarkdown: String?
    var encryptedPreview: String?
    var serverVersion: Int = 0
    var localRevision: UInt64 = 0
    var needsSync: Bool = true
    var clearedVersion: Int? = nil
}

struct WatchChatSnapshot: Codable, Equatable, Sendable {
    var chats: [WatchChatSummary]
    var messagesByChatId: [String: [WatchChatMessage]]
    var pendingTextSends: [WatchPendingTextSend]
    var pendingAudioEmbeds: [WatchPendingAudioEmbed]
    var savedAt: Date
    var accountID: String?
    var serverScope: String?
    var encryptedDrafts: [String: WatchEncryptedDraft]
    var pendingRecoveryJobs: [WatchRecoveryJob]
    var pendingCompletions: [WatchPendingCompletion]

    static let empty = WatchChatSnapshot(
        chats: [],
        messagesByChatId: [:],
        pendingTextSends: [],
        pendingAudioEmbeds: [],
        savedAt: .distantPast
    )

    init(
        chats: [WatchChatSummary],
        messagesByChatId: [String: [WatchChatMessage]],
        pendingTextSends: [WatchPendingTextSend] = [],
        pendingAudioEmbeds: [WatchPendingAudioEmbed] = [],
        savedAt: Date,
        accountID: String? = nil,
        serverScope: String? = nil,
        encryptedDrafts: [String: WatchEncryptedDraft] = [:],
        pendingRecoveryJobs: [WatchRecoveryJob] = [],
        pendingCompletions: [WatchPendingCompletion] = []
    ) {
        self.chats = chats
        self.messagesByChatId = messagesByChatId
        self.pendingTextSends = pendingTextSends
        self.pendingAudioEmbeds = pendingAudioEmbeds
        self.savedAt = savedAt
        self.accountID = accountID
        self.serverScope = serverScope
        self.encryptedDrafts = encryptedDrafts
        self.pendingRecoveryJobs = pendingRecoveryJobs
        self.pendingCompletions = pendingCompletions
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        chats = try container.decode([WatchChatSummary].self, forKey: .chats)
        messagesByChatId = try container.decode([String: [WatchChatMessage]].self, forKey: .messagesByChatId)
        pendingTextSends = try container.decodeIfPresent([WatchPendingTextSend].self, forKey: .pendingTextSends) ?? []
        pendingAudioEmbeds = try container.decodeIfPresent([WatchPendingAudioEmbed].self, forKey: .pendingAudioEmbeds) ?? []
        savedAt = try container.decode(Date.self, forKey: .savedAt)
        accountID = try container.decodeIfPresent(String.self, forKey: .accountID)
        serverScope = try container.decodeIfPresent(String.self, forKey: .serverScope)
        encryptedDrafts = try container.decodeIfPresent([String: WatchEncryptedDraft].self, forKey: .encryptedDrafts) ?? [:]
        pendingRecoveryJobs = try container.decodeIfPresent([WatchRecoveryJob].self, forKey: .pendingRecoveryJobs) ?? []
        pendingCompletions = try container.decodeIfPresent([WatchPendingCompletion].self, forKey: .pendingCompletions) ?? []
    }
}

struct WatchSyncSession: Equatable, Sendable {
    let sessionId: String
    let token: String?
}

struct WatchSyncClientState: Equatable, Sendable {
    let clientChatVersions: [String: [String: Int]]
    let clientChatIds: [String]
    let clientSuggestionsCount: Int
    let clientEmbedIds: [String]

    var phasedSyncPayload: [String: Any] {
        [
            "phase": "all",
            // Personal scope still requires an explicit context epoch on the server.
            "context_epoch": 0,
            "client_chat_versions": clientChatVersions,
            "client_chat_ids": clientChatIds,
            "client_suggestions_count": clientSuggestionsCount,
            "client_embed_ids": clientEmbedIds,
        ]
    }
}

// Mirrors ChatKeyWrapperRecord selection for the Watch target, which does not
// compile ChatKeyManager.swift.
struct WatchChatKeyWrapperRecord: Decodable, Sendable {
    let id: String?
    let hashedChatId: String
    let keyType: String
    let encryptedChatKey: String
    let wrapperVersion: Int?
    let createdAt: String?

    private enum CodingKeys: String, CodingKey {
        case id, hashedChatId, keyType, encryptedChatKey, wrapperVersion, createdAt
    }

    init(id: String?, hashedChatId: String, keyType: String,
         encryptedChatKey: String, wrapperVersion: Int?, createdAt: String?) {
        self.id = id
        self.hashedChatId = hashedChatId
        self.keyType = keyType
        self.encryptedChatKey = encryptedChatKey
        self.wrapperVersion = wrapperVersion
        self.createdAt = createdAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id)
        hashedChatId = try container.decode(String.self, forKey: .hashedChatId)
        keyType = try container.decode(String.self, forKey: .keyType)
        encryptedChatKey = try container.decode(String.self, forKey: .encryptedChatKey)
        wrapperVersion = try container.decodeIfPresent(Int.self, forKey: .wrapperVersion)
        if !container.contains(.createdAt) {
            createdAt = nil
        } else if try container.decodeNil(forKey: .createdAt) {
            createdAt = nil
        } else if let timestamp = try? container.decode(String.self, forKey: .createdAt) {
            createdAt = timestamp
        } else {
            createdAt = String(try container.decode(Int.self, forKey: .createdAt))
        }
    }

    static func orderedMasterWrappers(_ wrappers: [Self], for chatId: String) -> [Self] {
        let hash = hashedChatId(for: chatId)
        return wrappers
            .filter { $0.keyType == "master" && $0.hashedChatId == hash && !$0.encryptedChatKey.isEmpty }
            .sorted {
                ($0.wrapperVersion ?? 0, $0.createdAt ?? "", $0.id ?? "") >
                    ($1.wrapperVersion ?? 0, $1.createdAt ?? "", $1.id ?? "")
            }
    }

    static func hashedChatId(for chatId: String) -> String {
        SHA256.hash(data: Data(chatId.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

struct WatchRemoteChat: Sendable {
    let id: String
    let title: String?
    let lastMessageAt: String?
    let updatedAt: String?
    let chatSummary: String?
    let isPinned: Bool
    let encryptedTitle: String?
    let encryptedChatSummary: String?
    let encryptedChatKey: String?
    var chatKeyWrappers: [WatchChatKeyWrapperRecord] = []
    var messagesV: Int = 0
    var titleV: Int = 0
    var metadataV: Int = 0
    var lastEditedOverallTimestamp: String? = nil
    var parentID: String? = nil
    var isSubChat: Bool = false
    var encryptedDraftMD: String? = nil
    var encryptedDraftPreview: String? = nil
    var draftV: Int? = nil
    var clearedDraftV: Int? = nil
    var encryptedCategory: String? = nil
    var encryptedIcon: String? = nil
    var isSupportChat: Bool = false
    var isSharedRecipient: Bool = false
}

struct WatchRemoteMessage: Equatable, Sendable {
    let id: String
    let chatId: String
    let role: WatchChatMessage.Role
    let content: String?
    let encryptedContent: String?
    let embedRefs: [WatchEmbedRef]?
    let createdAt: String

    init(
        id: String,
        chatId: String,
        role: WatchChatMessage.Role,
        content: String?,
        encryptedContent: String?,
        embedRefs: [WatchEmbedRef]? = nil,
        createdAt: String
    ) {
        self.id = id
        self.chatId = chatId
        self.role = role
        self.content = content
        self.encryptedContent = encryptedContent
        self.embedRefs = embedRefs
        self.createdAt = createdAt
    }
}

// Published v1 foreground viewing windows. Full encrypted offline sync remains separate.
struct WatchMessageWindowCursor: Codable, Equatable, Sendable {
    let createdAt: Int
    let messageId: String
}

struct WatchMessageWindowQuery: Equatable, Sendable {
    enum Direction: String, Sendable { case latest, before, after, around }
    var direction: Direction = .latest
    var limit: Int = 50
    var before: WatchMessageWindowCursor? = nil
    var after: WatchMessageWindowCursor? = nil
    var anchorMessageId: String? = nil
    var respectCompressionBoundary = true

    func path(chatID: String) throws -> String {
        guard (1...100).contains(limit), !chatID.isEmpty, !chatID.contains("/"),
              direction != .before || before != nil,
              direction != .after || after != nil,
              direction != .around || anchorMessageId?.isEmpty == false,
              before.map({ !$0.messageId.isEmpty && $0.createdAt >= 0 }) ?? true,
              after.map({ !$0.messageId.isEmpty && $0.createdAt >= 0 }) ?? true else { throw WatchChatRuntimeError.historyUnavailable }
        var components = URLComponents()
        components.path = "/v1/chats/\(chatID)/messages/window"
        var items = [URLQueryItem(name: "direction", value: direction.rawValue),
                     URLQueryItem(name: "limit", value: String(limit)),
                     URLQueryItem(name: "respect_compression_boundary", value: respectCompressionBoundary ? "true" : "false")]
        if let before {
            items += [URLQueryItem(name: "before_timestamp", value: String(before.createdAt)), URLQueryItem(name: "before_message_id", value: before.messageId)]
        }
        if let after {
            items += [URLQueryItem(name: "after_timestamp", value: String(after.createdAt)), URLQueryItem(name: "after_message_id", value: after.messageId)]
        }
        if let anchorMessageId { items.append(URLQueryItem(name: "anchor_message_id", value: anchorMessageId)) }
        components.queryItems = items
        guard let path = components.url?.relativeString else { throw WatchChatRuntimeError.historyUnavailable }
        return path
    }
}

struct WatchMessageWindow: Sendable {
    let chatId: String
    var messages: [WatchRemoteMessage]
    var hasMoreBefore = false
    var hasMoreAfter = false
    var startCursor: WatchMessageWindowCursor? = nil
    var endCursor: WatchMessageWindowCursor? = nil
    var anchorFound = true
    var messagesV: Int? = nil
    var serverMessageCount: Int? = nil
    var compressionBoundaryTimestamp: Int? = nil
    var compressionCheckpoints: [WatchMessageCompressionCheckpoint] = []
    var respectCompressionBoundary = true
}

struct WatchMessageCompressionCheckpoint: Decodable, Sendable {
    let id: String
    let chatId: String
    let encryptedSummary: String?
    let compressedUpToTimestamp: Int?
    let compressedMessageCount: Int?
    let summaryTokenEstimate: Int?
    let keyVersion: Int?
}

struct WatchMessageWindowEnvelope: Decodable {
    let chatId: String
    fileprivate let messages: [WatchChatMessageDTO]
    let hasMoreBefore: Bool
    let hasMoreAfter: Bool
    let startCursor: WatchMessageWindowCursor?
    let endCursor: WatchMessageWindowCursor?
    let anchorFound: Bool
    let messagesV: Int?
    let serverMessageCount: Int?
    let compressionBoundaryTimestamp: Int?
    let compressionCheckpoints: [WatchMessageCompressionCheckpoint]
    let respectCompressionBoundary: Bool
    var window: WatchMessageWindow {
        WatchMessageWindow(chatId: chatId, messages: messages.map(WatchRemoteMessage.init(dto:)),
            hasMoreBefore: hasMoreBefore, hasMoreAfter: hasMoreAfter, startCursor: startCursor, endCursor: endCursor,
            anchorFound: anchorFound, messagesV: messagesV, serverMessageCount: serverMessageCount,
            compressionBoundaryTimestamp: compressionBoundaryTimestamp, compressionCheckpoints: compressionCheckpoints,
            respectCompressionBoundary: respectCompressionBoundary)
    }
}

/// Captured by the originating MainActor service/runtime before the API actor
/// hop. Rotation cannot replace this account's pair deadline or lifecycle scope.
struct WatchChatRequestContext: Sendable {
    let accountID: String?
    let profile: ServerProfile
    let accountGeneration: UInt64
    private let pairDeadline: Int?
    private let deadline: @MainActor @Sendable (String) -> Int?
    private let now: @MainActor @Sendable () -> Int
    private let validate: @MainActor @Sendable () throws -> Void

    @MainActor init(accountID: String?, profile: ServerProfile, accountGeneration: UInt64,
        deadline: @escaping @MainActor @Sendable (String) -> Int? = { PairSessionDeadlineStore.deadline(userID: $0) },
        now: @escaping @MainActor @Sendable () -> Int = { Int(Date().timeIntervalSince1970) },
        validate: @escaping @MainActor @Sendable () throws -> Void = {}) {
        self.accountID = accountID
        self.profile = profile
        self.accountGeneration = accountGeneration
        self.pairDeadline = accountID.flatMap { deadline($0) }
        self.deadline = deadline
        self.now = now
        self.validate = validate
    }

    @MainActor func check() throws {
        try Task.checkCancellation()
        guard accountGeneration == WatchChatAccountLifecycle.generation,
              profile == ServerProfile.current() else { throw CancellationError() }
        if let accountID {
            guard deadline(accountID) == pairDeadline,
                  pairDeadline.map({ now() < $0 }) ?? true else { throw CancellationError() }
        }
        try validate()
    }
}

@MainActor enum WatchSessionTransport {
    static func loadSession(api: APIClient = .shared, body: SessionRequest,
                            context: WatchChatRequestContext) async throws -> SessionResponse {
        guard let accountID = context.accountID else { throw CancellationError() }
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let rawBody = JSONRawBody(data: try encoder.encode(body))
        let data = try await api.requestForVerifiedWatchSession(.post, path: "/v1/auth/session",
            serverProfile: context.profile, body: rawBody, verifyResponse: { response, data in
                guard (200...299).contains(response.statusCode) else { return }
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                let result = try decoder.decode(SessionResponse.self, from: data)
                if let user = result.user, user.id != accountID { throw CancellationError() }
            }, validate: { try context.check() })
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(SessionResponse.self, from: data)
    }
}

protocol WatchChatAPI: Sendable {
    func fetchRecentChats(limit: Int, offset: Int, context: WatchChatRequestContext) async throws -> [WatchRemoteChat]
    func fetchMessages(chatId: String, context: WatchChatRequestContext) async throws -> [WatchRemoteMessage]
    func fetchMessageWindow(chatId: String, query: WatchMessageWindowQuery, context: WatchChatRequestContext) async throws -> WatchMessageWindow
    func fetchMessagesVersion(chatId: String, context: WatchChatRequestContext) async throws -> Int?
    func uploadAudioRecording(data: Data, filename: String, chatId: String, context: WatchChatRequestContext) async throws -> WatchUploadedAudio
    func transcribeAudioRecording(_ upload: WatchUploadedAudio, chatId: String, context: WatchChatRequestContext) async throws -> WatchTranscriptionMetadata?
}

extension WatchChatAPI {
    func fetchMessageWindow(chatId: String, query: WatchMessageWindowQuery, context: WatchChatRequestContext) async throws -> WatchMessageWindow {
        throw WatchChatRuntimeError.historyUnavailable
    }
}

@MainActor
protocol WatchChatSyncSocket: AnyObject {
    func connect(session: WatchSyncSession, syncState: WatchSyncClientState)
    func disconnect()
    func sendTurn(_ pending: WatchPendingTextSend) async throws
    func sendTurn(_ pending: WatchPendingTextSend, encryptMetadata: @escaping @MainActor (String) async throws -> String) async throws
    func setChangeHandler(_ handler: (@MainActor () -> Void)?)
    var generation: Int { get }
    func sendEvent(type: String, payload: [String: Any]) async throws
    func setEventHandler(_ handler: (@MainActor (String, [String: Any]) -> Void)?)
    func setReadyHandler(_ handler: (@MainActor () -> Void)?)
    var isConnected: Bool { get }
    func requestEvent(type: String, payload: [String: Any], responseTypes: Set<String>,
                      matching: @escaping @MainActor ([String: Any]) -> Bool) async throws -> [String: Any]
    func requestEvent(type: String, payload: [String: Any], responseTypes: Set<String>,
                      matching: @escaping @MainActor ([String: Any]) -> Bool,
                      beforeSend: @escaping @MainActor () throws -> Void) async throws -> [String: Any]
}

extension WatchChatSyncSocket {
    var generation: Int { 0 }
    func sendTurn(_ pending: WatchPendingTextSend, encryptMetadata: @escaping @MainActor (String) async throws -> String) async throws {
        try await sendTurn(pending)
    }
    func sendEvent(type: String, payload: [String: Any]) async throws { throw WatchChatRuntimeError.socketUnavailable }
    func setEventHandler(_ handler: (@MainActor (String, [String: Any]) -> Void)?) {}
    func setReadyHandler(_ handler: (@MainActor () -> Void)?) {}
    var isConnected: Bool { false }
    func requestEvent(type: String, payload: [String: Any], responseTypes: Set<String>,
                      matching: @escaping @MainActor ([String: Any]) -> Bool) async throws -> [String: Any] {
        throw WatchChatRuntimeError.socketUnavailable
    }
    func requestEvent(type: String, payload: [String: Any], responseTypes: Set<String>,
                      matching: @escaping @MainActor ([String: Any]) -> Bool,
                      beforeSend: @escaping @MainActor () throws -> Void) async throws -> [String: Any] {
        try beforeSend()
        return try await requestEvent(type: type, payload: payload,
                                      responseTypes: responseTypes, matching: matching)
    }
}

@MainActor
protocol WatchChatCrypto: AnyObject {
    func offlineWrappedChatKey(for chat: WatchChatSummary) -> String?
    func decryptChat(_ chat: WatchRemoteChat) async -> WatchChatSummary?
    func decryptMessage(_ message: WatchRemoteMessage) async -> WatchChatMessage
    func encryptText(_ text: String, for chat: WatchChatSummary) async throws -> String
    func createChat() async throws -> WatchChatSummary
    func createChat(withID id: String) async throws -> WatchChatSummary
    func encryptDraft(_ text: String) async throws -> String
    func decryptDraft(_ ciphertext: String) async throws -> String
    func hydrateEmbed(payload: [String: Any], chat: WatchChatSummary) async throws -> WatchEmbedRef
    func prepareEmbedStorage(payload: [String: Any], chat: WatchChatSummary, messageID: String) async throws -> (keys: [String: Any], embed: [String: Any])
    func recoveryPublicKey(for chat: WatchChatSummary) async throws -> String
    func decryptText(_ ciphertext: String, for chat: WatchChatSummary) async throws -> String
    func openCompletion(_ sealed: String, job: WatchRecoveryJob, ownerID: String, chat: WatchChatSummary) async throws -> WatchRecoveredCompletion
    func encryptedAudioEmbed(_ embed: WatchPendingAudioEmbed, chat: WatchChatSummary, messageId: String) async throws -> [[String: Any]]
}

extension WatchChatCrypto {
    func offlineWrappedChatKey(for chat: WatchChatSummary) -> String? { chat.offlineWrappedChatKey ?? chat.encryptedChatKey }
    func createChat(withID id: String) async throws -> WatchChatSummary { throw WatchChatRuntimeError.missingChatKey }
    func prepareEmbedStorage(payload: [String: Any], chat: WatchChatSummary, messageID: String) async throws -> (keys: [String: Any], embed: [String: Any]) { throw WatchChatRuntimeError.missingChatKey }
    func hydrateEmbed(payload: [String: Any], chat: WatchChatSummary) async throws -> WatchEmbedRef { throw WatchChatRuntimeError.missingChatKey }
    func decryptText(_ ciphertext: String, for chat: WatchChatSummary) async throws -> String { throw WatchChatRuntimeError.missingChatKey }
    func openCompletion(_ sealed: String, job: WatchRecoveryJob, ownerID: String, chat: WatchChatSummary) async throws -> WatchRecoveredCompletion {
        throw WatchChatRuntimeError.missingChatKey
    }
}

extension WatchChatCrypto {
    func encryptDraft(_ text: String) async throws -> String { throw WatchChatRuntimeError.missingChatKey }
    func decryptDraft(_ ciphertext: String) async throws -> String { throw WatchChatRuntimeError.missingChatKey }
}

@MainActor
enum WatchChatAccountLifecycle {
    private(set) static var generation: UInt64 = 0
    static func invalidate() { generation &+= 1 }
}

actor WatchChatOfflineCache {
    static let shared = WatchChatOfflineCache()
    static let maximumConversationBytes = 32_000_000
    static let maximumConversationCacheBytes = 256_000_000
    private let fileURL: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    private let conversationDirectory: URL
    private var eraseEpoch: UInt64 = 0

    init(directory: URL? = nil) {
        self.fileURL = (directory ?? WatchChatOfflineCache.defaultDirectory())
            .appendingPathComponent("watch-chat-snapshot.json")
        // Complete offline receipts are user data, not evictable system caches.
        self.conversationDirectory = (directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OpenMatesWatch", isDirectory: true))
            .appendingPathComponent("recent-conversations", isDirectory: true)
        self.encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
    }

    func loadSnapshot() -> WatchChatSnapshot {
        guard let data = try? Data(contentsOf: fileURL),
              let snapshot = try? decoder.decode(WatchChatSnapshot.self, from: data) else {
            return .empty
        }
        return snapshot
    }

    func saveSnapshot(_ snapshot: WatchChatSnapshot, accountGeneration: UInt64? = nil, serverScope: String? = nil) async throws {
        let observedEraseEpoch = eraseEpoch
        if let accountGeneration {
            let valid = await MainActor.run {
                accountGeneration == WatchChatAccountLifecycle.generation &&
                (serverScope == nil || serverScope == WatchChatRuntime.currentServerScope)
            }
            guard valid, observedEraseEpoch == eraseEpoch else { throw CancellationError() }
        }
        try Task.checkCancellation()
        guard observedEraseEpoch == eraseEpoch else { throw CancellationError() }
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let data = try encoder.encode(snapshot)
        try data.write(to: fileURL, options: [.atomic, .completeFileProtection])
    }

    func removeSnapshot() throws {
        eraseEpoch &+= 1
        if FileManager.default.fileExists(atPath: fileURL.path) { try FileManager.default.removeItem(at: fileURL) }
        if FileManager.default.fileExists(atPath: conversationDirectory.path) { try FileManager.default.removeItem(at: conversationDirectory) }
    }

    private func conversationURL(chatID: String) -> URL {
        conversationDirectory.appendingPathComponent(WatchChatKeyWrapperRecord.hashedChatId(for: chatID) + ".json")
    }

    func loadConversation(chatID: String, accountID: String?, serverScope: String) -> WatchOfflineConversation? {
        guard let data = try? Data(contentsOf: conversationURL(chatID: chatID)),
              let value = try? decoder.decode(WatchOfflineConversation.self, from: data),
              value.chat.id == chatID, value.accountID == accountID, value.serverScope == serverScope else { return nil }
        return value
    }

    func conversationMetadata(accountID: String?, serverScope: String) -> [WatchChatSummary] {
        var result: [WatchChatSummary] = []
        for url in (try? FileManager.default.contentsOfDirectory(at: conversationDirectory, includingPropertiesForKeys: nil)) ?? [] {
            guard let data = try? Data(contentsOf: url),
                  let value = try? decoder.decode(WatchOfflineConversation.self, from: data),
                  value.accountID == accountID, value.serverScope == serverScope else { continue }
            var chat = value.chat
            chat.offlineWrappedChatKey = value.wrappedRecoveryChatKey ?? chat.offlineWrappedChatKey
            result.append(chat)
        }
        return result
    }

    func saveConversation(_ value: WatchOfflineConversation, accountGeneration: UInt64) async throws {
        let observedEraseEpoch = eraseEpoch
        let data = try encoder.encode(value)
        guard data.count <= Self.maximumConversationBytes else { throw WatchChatRuntimeError.historyUnavailable }
        let valid = await MainActor.run {
            accountGeneration == WatchChatAccountLifecycle.generation && value.serverScope == WatchChatRuntime.currentServerScope
        }
        guard valid, observedEraseEpoch == eraseEpoch else { throw CancellationError() }
        try Task.checkCancellation()
        try FileManager.default.createDirectory(at: conversationDirectory, withIntermediateDirectories: true)
        var directory = conversationDirectory
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try directory.setResourceValues(values)
        let target = conversationURL(chatID: value.chat.id)
        let entries = try FileManager.default.contentsOfDirectory(at: conversationDirectory, includingPropertiesForKeys: [.fileSizeKey])
        let retainedBytes = try entries.filter { $0 != target }.reduce(0) { try $0 + ($1.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0) }
        guard retainedBytes + data.count <= Self.maximumConversationCacheBytes else { throw WatchChatRuntimeError.historyUnavailable }
        try data.write(to: target, options: [.atomic, .completeFileProtection])
    }

    func pruneConversations(retaining ids: Set<String>) throws {
        let names = Set(ids.map { WatchChatKeyWrapperRecord.hashedChatId(for: $0) + ".json" })
        for url in (try? FileManager.default.contentsOfDirectory(at: conversationDirectory, includingPropertiesForKeys: nil)) ?? [] {
            try Task.checkCancellation()
            if !names.contains(url.lastPathComponent) { try FileManager.default.removeItem(at: url) }
        }
    }

    /// Parse and paginate ciphertext off the foreground actor. No transcript is
    /// decrypted or published by cohort maintenance, and a receipt requires the
    /// server's full-count/version agreement rather than a viewing window.
    func prepareConversation(_ data: Data, chatID: String) throws -> WatchOfflinePreparedConversation {
        try Task.checkCancellation()
        guard data.count <= Self.maximumConversationBytes,
              let fields = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              fields["partial_error"] as? Bool != true,
              let rows = (fields["messages_by_chat_id"] as? [String: Any])?[chatID] as? [Any],
              let versions = (fields["versions_by_chat_id"] as? [String: [String: Int]])?[chatID],
              let count = versions["server_message_count"], count == rows.count,
              let version = versions["messages_v"], version >= count else { throw WatchChatRuntimeError.historyUnavailable }
        var messages: [[String: Any]] = []
        var seen = Set<String>()
        for row in rows {
            try Task.checkCancellation()
            let object: [String: Any]?
            if let string = row as? String { object = try JSONSerialization.jsonObject(with: Data(string.utf8)) as? [String: Any] }
            else { object = row as? [String: Any] }
            guard var record = object, record["chat_id"] as? String == chatID,
                  let id = (record["client_message_id"] ?? record["message_id"] ?? record["id"]) as? String,
                  seen.insert(id).inserted else { throw WatchChatRuntimeError.historyUnavailable }
            record["id"] = id
            if let timestamp = record["created_at"], !(timestamp is String) { record["created_at"] = String(describing: timestamp) }
            messages.append(record)
        }
        messages.sort { left, right in
            let l = WatchRecentOfflinePolicy.timestamp(left["created_at"] as? String)
            let r = WatchRecentOfflinePolicy.timestamp(right["created_at"] as? String)
            return l == r ? (left["id"] as? String ?? "") < (right["id"] as? String ?? "") : l < r
        }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let wrappers = try decoder.decode([WatchChatKeyWrapperRecord].self,
            from: JSONSerialization.data(withJSONObject: fields["chat_key_wrappers"] ?? []))
        let embeds = fields["embeds"] as? [[String: Any]] ?? []
        let keys = fields["embed_keys"] as? [[String: Any]] ?? []
        let hash = WatchChatKeyWrapperRecord.hashedChatId(for: chatID)
        var payloads: [[String: Any]] = []
        for embed in embeds {
            guard let id = (embed["embed_id"] ?? embed["id"]) as? String,
                  embed["chat_id"] as? String == chatID || embed["hashed_chat_id"] as? String == hash else { throw WatchChatRuntimeError.historyUnavailable }
            var payload = embed
            payload["embed_id"] = id
            payload["chat_id"] = chatID
            payload["type"] = embed["encrypted_type"] ?? embed["type"] ?? "app_skill_use"
            payload["content"] = embed["encrypted_content"] ?? embed["content"] ?? ""
            if embed["encrypted_content"] as? String != nil {
                let matching = keys.filter { $0["hashed_embed_id"] as? String == WatchChatKeyWrapperRecord.hashedChatId(for: id) }
                guard !matching.isEmpty else { throw WatchChatRuntimeError.missingChatKey }
                payload["embed_keys"] = matching
                payload["already_encrypted"] = true
                payload["encryption_mode"] = "client"
            }
            payloads.append(payload)
        }
        func pages(_ rows: [[String: Any]]) throws -> [Data] {
            try stride(from: 0, to: rows.count, by: 50).map {
                try JSONSerialization.data(withJSONObject: Array(rows[$0..<min($0 + 50, rows.count)]))
            }
        }
        let supplemental = fields.filter { ["compression_checkpoints_by_chat_id", "code_run_outputs", "notebook_run_outputs", "embed_keys", "chat_key_wrappers"].contains($0.key) }
        return WatchOfflinePreparedConversation(messagePages: try pages(messages), embedPages: try pages(payloads),
            supplemental: try JSONSerialization.data(withJSONObject: supplemental), wrappers: wrappers,
            messagesVersion: version, messageCount: count)
    }

    func decodeMessagePage(_ data: Data) throws -> [WatchRemoteMessage] {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode([WatchChatMessageDTO].self, from: data).map(WatchRemoteMessage.init(dto:))
    }

    func decodeEmbedPage(_ data: Data) throws -> [[String: AnyCodable]] {
        try JSONDecoder().decode([[String: AnyCodable]].self, from: data)
    }

    static func defaultDirectory() -> URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OpenMatesWatch", isDirectory: true)
    }
}

struct WatchOfflinePreparedConversation: Sendable {
    let messagePages: [Data]
    let embedPages: [Data]
    let supplemental: Data
    let wrappers: [WatchChatKeyWrapperRecord]
    let messagesVersion: Int
    let messageCount: Int
}

/// Each page and supplemental payload is sealed with the validated chat key.
/// Only a complete atomic receipt is eligible for offline opening.
struct WatchOfflineConversation: Codable, Sendable {
    let chat: WatchChatSummary
    let accountID: String?
    let serverScope: String
    let revision: String
    let messagesVersion: Int
    let messageCount: Int
    let messagePages: [String]
    let embedPages: [String]
    let supplemental: String
    var wrappedRecoveryChatKey: String? = nil
}

enum WatchRecentOfflinePolicy {
    static let capacity = 20
    static func timestamp(_ value: String?) -> Double {
        guard let value else { return 0 }
        if let number = Double(value) { return number }
        let parser = ISO8601DateFormatter()
        if let date = parser.date(from: value) { return date.timeIntervalSince1970 }
        parser.formatOptions.insert(.withFractionalSeconds)
        return parser.date(from: value)?.timeIntervalSince1970 ?? 0
    }
    static func activity(_ chat: WatchChatSummary) -> Double {
        timestamp(chat.lastEditedOverallTimestamp ?? chat.lastMessageAt)
    }
    static func revision(_ chat: WatchChatSummary) -> String {
        "\(chat.messagesV)|\(activity(chat))"
    }
    static func cohort(_ chats: [WatchChatSummary]) -> [WatchChatSummary] {
        Array(chats.filter { chat in
            chat.parentID == nil && !chat.isSubChat && !["incognito-", "demo-", "example-", "announcements-"].contains(where: chat.id.hasPrefix)
        }.sorted {
            activity($0) == activity($1) ? $0.id < $1.id : activity($0) > activity($1)
        }.prefix(capacity))
    }
}

@MainActor
final class WatchChatRuntime: ObservableObject {
    @Published private(set) var chats: [WatchChatSummary] = []
    @Published private(set) var messagesByChatId: [String: [WatchChatMessage]] = [:]
    @Published var selectedChatId: String?
    @Published private(set) var isSyncing = false
    @Published private(set) var isOffline = false
    @Published private(set) var chatLoadFailed = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var pendingAudioEmbeds: [WatchPendingAudioEmbed] = []
    @Published private(set) var unavailableChatCount = 0
    @Published private(set) var hydratedEmbedPreviews: [String: WatchEmbedRef] = [:]
    private var requestedEmbedPreviews: Set<String> = []
    private var embedSocketGeneration: Int?

    static var currentServerScope: String {
        let profile = ServerProfile.current()
        return profile.apiBaseURL.absoluteString + "|" + profile.webBaseURL.absoluteString
    }
    private let serverScope = WatchChatRuntime.currentServerScope
    private let requestServerProfile = ServerProfile.current()
    private let accountID: String?
    var lifecycleGeneration: UInt64 = 0
    private var stopped = false
    private let accountLifecycleGeneration = WatchChatAccountLifecycle.generation
    var isStopped: Bool {
        get { stopped || accountLifecycleGeneration != WatchChatAccountLifecycle.generation || serverScope != Self.currentServerScope }
        set { stopped = newValue }
    }
    private var transientChat: WatchChatSummary?
    private var encryptedDrafts: [String: WatchEncryptedDraft] = [:]
    @Published private(set) var composerDrafts: [String: String] = [:]
    private var draftRevision: UInt64 = 0
    private var draftLocalRevisions: [String: UInt64] = [:]
    private var draftSaveTask: Task<Void, Never>?
    private var inFlightDrafts: [String: WatchEncryptedDraft] = [:]
    private var draftSocketGeneration: Int?
    private var draftReconciledSocketGeneration: Int?
    private(set) var isPreviewFixture = false
    private(set) var isOfflineCohortFixture = false
    private let api: any WatchChatAPI
    private let cache: WatchChatOfflineCache
    private let crypto: any WatchChatCrypto
    private let syncSocket: (any WatchChatSyncSocket)?
    private var syncSession: WatchSyncSession?
    private var isForeground = false
    @Published private(set) var visibleChatID: String?
    private var receiptChatID: String?
    private var visibleReceiptIDs: Set<String> = []
    private var acknowledgedReceiptIDs: Set<String> = []
    private var inFlightReceiptIDs: Set<String> = []
    private var receiptAttemptID = UUID()
    private var isSending = false
    private var refreshTask: Task<Void, Never>?
    private var recentOfflineTask: Task<Void, Never>?
    private var recentOfflineRunID: UUID?
    private var recentOfflineNeedsRefresh = false
    private var foregroundNavigationBusy = false
    private var offlineConversation: WatchOfflineConversation?
    @Published private(set) var offlinePageIndex: Int?
    @Published private(set) var offlinePageCount = 0
    @Published private(set) var isLoadingOfflinePage = false
    @Published private(set) var hasMoreRemoteMessages = false
    @Published private(set) var isLoadingRemoteMessages = false
    private var remoteStartCursor: WatchMessageWindowCursor?
    private var windowRequestID = UUID()
    private var partialWindowChats: Set<String> = []

    private var backgroundOfflineMaintenance = false
    private var chatListAuthoritative = false
    private var pendingTextSends: [WatchPendingTextSend] = []
    private var pendingRecoveryJobs: [WatchRecoveryJob] = []
    private var pendingCompletions: [WatchPendingCompletion] = []
    private var completionTask: Task<Void, Never>?
    private var completionWorkInProgress = false
    private var completionRetryAttempt = 0
    private static let incognitoChatIdPrefix = "incognito-"
    // Show the first page promptly, then fetch older chats for local search.
    // Some deployed servers ignore offset, so stop when a page repeats.
    private static let firstChatFetchLimit = 20
    private static let chatFetchLimit = 100
    private static let fetchRetryAttempts = 4
    private static let fetchRetryDelayNanoseconds: UInt64 = 750_000_000

    init(
        currentUserId: String? = nil,
        api: any WatchChatAPI = APIClient.shared,
        cache: WatchChatOfflineCache = .shared,
        crypto: (any WatchChatCrypto)? = nil,
        syncSocket: (any WatchChatSyncSocket)? = WatchRealtimeSyncSocket(),
        syncSession: WatchSyncSession? = nil
    ) {
        self.accountID = currentUserId
        self.api = api
        self.cache = cache
        self.crypto = crypto ?? WatchChatCryptoService(currentUserId: currentUserId)
        self.syncSocket = syncSocket
        self.syncSession = syncSession
    }

#if DEBUG
    static func offlineCohortFixture(directory: URL? = nil) -> WatchChatRuntime {
        let crypto = WatchOfflineFixtureCrypto()
        let transport = WatchOfflineFixtureTransport(crypto: crypto)
        let runtime = WatchChatRuntime(currentUserId: WatchOfflineFixtureTransport.accountID,
            api: transport, cache: WatchChatOfflineCache(directory: directory ?? FileManager.default.temporaryDirectory.appendingPathComponent("watch-offline-fixture-" + UUID().uuidString)),
            crypto: crypto, syncSocket: transport, syncSession: WatchSyncSession(sessionId: "fixture", token: nil))
        runtime.isOfflineCohortFixture = true
        return runtime
    }

    static func messageWindowFixture() -> WatchChatRuntime {
        let runtime = WatchChatRuntime(api: WatchMessageWindowFixtureTransport(),
            cache: WatchChatOfflineCache(directory: FileManager.default.temporaryDirectory.appendingPathComponent("watch-window-fixture-" + UUID().uuidString)),
            crypto: WatchPreviewDraftCrypto(), syncSocket: nil)
        runtime.isPreviewFixture = true
        runtime.chats = [WatchChatSummary(id: "watch-window-fixture", title: "Synthetic paged history", lastMessageAt: nil,
            preview: nil, isPinned: false, encryptedTitle: nil, encryptedPreview: nil, encryptedChatKey: nil)]
        runtime.selectedChatId = "watch-window-fixture"
        return runtime
    }

    func prepareMessageWindowFixture() async {
        guard isPreviewFixture, api is WatchMessageWindowFixtureTransport, let chat = chats.first else { return }
        await openChat(chat)
    }

    func prepareOfflineCohortFixture() async {
        guard isOfflineCohortFixture, let transport = api as? WatchOfflineFixtureTransport else { return }
        await setForeground(true)
        await refresh()
        await waitForRecentOfflineSync()
        transport.offline = true
        await setForeground(false)
        isOffline = true
        // Reopen from ciphertext to prove unopened cohort data is durable.
        messagesByChatId.removeAll()
        hydratedEmbedPreviews.removeAll()
    }

    init(uiTestSnapshot snapshot: WatchChatSnapshot, selectedChatId: String?, initialDraft: String? = nil) {
        self.accountID = nil
        self.isPreviewFixture = true
        self.api = APIClient.shared
        self.cache = WatchChatOfflineCache()
        self.crypto = WatchPreviewDraftCrypto()
        self.syncSocket = nil
        self.syncSession = nil
        self.chats = snapshot.chats
        self.messagesByChatId = snapshot.messagesByChatId
        self.pendingTextSends = snapshot.pendingTextSends
        self.pendingAudioEmbeds = snapshot.pendingAudioEmbeds
        self.selectedChatId = selectedChatId
        if let selectedChatId, let initialDraft { composerDrafts[selectedChatId] = initialDraft }
        if let selectedChatId, let chat = chats.first(where: { $0.id == selectedChatId }),
           chat.title == "New chat", (messagesByChatId[selectedChatId] ?? []).isEmpty {
            transientChat = chat
            chats.removeAll { $0.id == selectedChatId }
        }
    }
#endif

    private func requestContext() -> WatchChatRequestContext {
        let generation = lifecycleGeneration
        return WatchChatRequestContext(accountID: accountID, profile: requestServerProfile,
            accountGeneration: accountLifecycleGeneration, validate: { [weak self] in
                guard let self, !self.isStopped, self.lifecycleGeneration == generation else { throw CancellationError() }
            })
    }

    func selectedChatShareContext() -> WatchChatRequestContext? {
        guard !isStopped, !isOffline, let selectedChat, chats.contains(where: { $0.id == selectedChat.id }) else { return nil }
        return requestContext()
    }

    var selectedChat: WatchChatSummary? {
        guard let selectedChatId else { return nil }
        return chats.first { $0.id == selectedChatId } ?? (transientChat?.id == selectedChatId ? transientChat : nil)
    }

#if DEBUG
    func seedRemoteDraftPreview() async {
        guard isPreviewFixture else { return }
        guard let ciphertext = try? await crypto.encryptDraft("Berlin remote draft") else { return }
        handleDraftSyncEvent(type: "phase_2_last_20_chats_ready", payload: ["context_epoch": 0,
            "chats": [["chat_details": ["id": "watch-remote-draft", "draft_v": 2, "messages_v": 0,
                "encrypted_draft_md": ciphertext, "encrypted_draft_preview": ciphertext]]]])
    }
#endif

    var selectedMessages: [WatchChatMessage] {
        guard let selectedChatId else { return [] }
        return messagesByChatId[selectedChatId] ?? []
    }

    func loadCachedSnapshot() async {
        guard !isStopped else { return }
        let generation = lifecycleGeneration
        let profile = ServerProfile.current()
        var snapshot = await cache.loadSnapshot()
        if snapshot.accountID != accountID || !(snapshot.serverScope == serverScope || (accountID == nil && snapshot.serverScope == nil)) {
            snapshot = .empty; snapshot.accountID = accountID; snapshot.serverScope = serverScope
        }
        let recent = await cache.conversationMetadata(accountID: accountID, serverScope: serverScope)
        let present = Set(snapshot.chats.map(\.id))
        snapshot.chats += recent.filter { !present.contains($0.id) }
        guard generation == lifecycleGeneration, !isStopped, profile == ServerProfile.current() else { return }
        apply(snapshot)
        for cached in snapshot.chats {
            var remote = WatchRemoteChat(id: cached.id, title: cached.title, lastMessageAt: cached.lastMessageAt,
                updatedAt: nil, chatSummary: cached.preview, isPinned: cached.isPinned,
                encryptedTitle: cached.encryptedTitle, encryptedChatSummary: cached.encryptedPreview,
                encryptedChatKey: cached.encryptedChatKey, messagesV: cached.messagesV,
                titleV: cached.titleV, metadataV: cached.metadataV)
            remote.encryptedCategory = cached.encryptedCategory; remote.encryptedIcon = cached.encryptedIcon
            remote.isSupportChat = cached.isSupportChat; remote.isSharedRecipient = cached.isSharedRecipient
            if let wrapped = cached.offlineWrappedChatKey {
                remote.chatKeyWrappers = [WatchChatKeyWrapperRecord(id: nil, hashedChatId: WatchChatKeyWrapperRecord.hashedChatId(for: cached.id),
                    keyType: "master", encryptedChatKey: wrapped, wrapperVersion: nil, createdAt: nil)]
            }
            if var decrypted = await crypto.decryptChat(remote), let index = chats.firstIndex(where: { $0.id == cached.id }) {
                guard generation == lifecycleGeneration, !isStopped, profile == ServerProfile.current() else { return }
                decrypted.lastEditedOverallTimestamp = cached.lastEditedOverallTimestamp
                decrypted.parentID = cached.parentID; decrypted.isSubChat = cached.isSubChat
                chats[index] = decrypted
            }
            for message in (snapshot.messagesByChatId[cached.id] ?? []).filter(\.isPending) {
                var decrypted = await crypto.decryptMessage(.init(id: message.id, chatId: message.chatId, role: message.role,
                    content: message.content, encryptedContent: message.encryptedContent, embedRefs: message.embedRefs, createdAt: message.createdAt))
                guard generation == lifecycleGeneration, !isStopped, profile == ServerProfile.current() else { return }
                decrypted.isPending = message.isPending
                upsertCompletionMessage(decrypted)
            }
        }
        for (chatID, draft) in encryptedDrafts {
            guard let ciphertext = draft.encryptedMarkdown else { continue }
            let text = try? await crypto.decryptDraft(ciphertext)
            guard generation == lifecycleGeneration, !isStopped, profile == ServerProfile.current() else { return }
            if let text { composerDrafts[chatID] = text }
        }
    }

    func refresh() async {
        guard !isStopped else { return }
        if let refreshTask { await refreshTask.value; return }
        let task = Task { @MainActor in await self.performRefresh() }
        refreshTask = task
        await task.value
        refreshTask = nil
    }

    private func performRefresh() async {
        guard !isSyncing, !isStopped else { return }
        chatListAuthoritative = false
        let generation = lifecycleGeneration
        let profile = ServerProfile.current()
        func current() -> Bool { !Task.isCancelled && !isStopped && generation == lifecycleGeneration && profile == ServerProfile.current() }
        isSyncing = true
        defer { if current() { isSyncing = false } }
        errorMessage = nil
        if chats.isEmpty {
            await loadCachedSnapshot()
        }
        guard current() else { return }
        var remote: [WatchChatSummary] = []
        var seenChatIds = Set<String>()
        var fetchedCount = 0
        var offset = 0
        var limit = Self.firstChatFetchLimit
        var fetchedFirstPage = false
        var fetchError: Error?
        var reachedEnd = false
        while true {
            let page: [WatchRemoteChat]
            do {
                page = try await fetchWithRetry {
                    try await api.fetchRecentChats(limit: limit, offset: offset, context: requestContext())
                }
            } catch {
                guard current() else { return }
                if fetchedFirstPage && limit == Self.chatFetchLimit {
                    NativeDiagnostics.failure("large_page_failed", category: "watch_chat", level: .warning, error: error)
                    limit = Self.firstChatFetchLimit
                    continue
                }
                fetchError = error
                break
            }
            guard current() else { return }
            fetchedFirstPage = true
            let unseen = page.filter { seenChatIds.insert($0.id).inserted }
            if !page.isEmpty && unseen.isEmpty {
                NativeDiagnostics.event("repeated_page", category: "watch_chat", level: .warning,
                                        counts: ["offset": offset, "limit": limit])
                break
            }
            fetchedCount += unseen.count
            let decryptedPage = await decryptChats(unseen)
            guard current() else { return }
            remote.append(contentsOf: decryptedPage)
            unavailableChatCount = fetchedCount - remote.count
            let remoteIds = Set(remote.map(\.id))
            let pendingChatIds = Set(pendingTextSends.map(\.chatId))
            let hasMore = page.count == limit
            let localRetained = chats.filter { chat in
                !remoteIds.contains(chat.id) && (
                    hasMore || pendingChatIds.contains(chat.id)
                    || (chat.messagesV == 0 && messagesByChatId[chat.id] != nil)
                )
            }
            chats = Self.sortedChats(remote + localRetained)
            isOffline = false
            chatLoadFailed = false
            NativeDiagnostics.event("refresh_page", category: "watch_chat", counts: [
                "offset": offset, "fetched": unseen.count, "decrypted": remote.count,
                "unavailable_key": unavailableChatCount,
            ])
            guard hasMore else { reachedEnd = true; break }
            offset += page.count
            limit = Self.chatFetchLimit
        }
        if let fetchError {
            NativeDiagnostics.failure("fetch_failed", category: "watch_chat", level: .warning, error: fetchError)
            errorMessage = fetchError.localizedDescription
            chatLoadFailed = true
            if !fetchedFirstPage {
                isOffline = Self.isConnectivityError(fetchError)
                if chats.isEmpty { await loadCachedSnapshot() }
            }
        }
        guard current() else { return }
        chatListAuthoritative = reachedEnd && fetchError == nil
        if fetchedFirstPage {
            NativeDiagnostics.event("refresh", category: "watch_chat", counts: [
                "fetched": fetchedCount, "decrypted": remote.count,
                "unavailable_key": unavailableChatCount,
            ])
            await replayPendingTextSends()
            do {
                try await persistSnapshot()
            } catch {
                NativeDiagnostics.failure("persist_failed", category: "watch_chat", level: .warning, error: error)
            }
        }
        scheduleRecentOfflineSync()
    }

    private var canMaintainRecentOfflineChats: Bool {
        !isStopped && !isPreviewFixture
            && ((isForeground && !foregroundNavigationBusy && selectedChatId == nil) || (backgroundOfflineMaintenance && !isForeground))
            && chatListAuthoritative && !isOffline && syncSocket?.isConnected == true
    }

    /// An opportunistic watchOS grant has an external cancellation deadline.
    /// It may persist a subset of complete receipts, never a truncated receipt.
    func performBackgroundOfflineSync() async {
        guard !isStopped, !isForeground, accountID != nil else { return }
        backgroundOfflineMaintenance = true
        defer {
            backgroundOfflineMaintenance = false
            cancelRecentOfflineSync()
            if !isForeground { syncSocket?.disconnect() }
        }
        if let syncSocket, let syncSession, !syncSocket.isConnected {
            syncSocket.connect(session: syncSession, syncState: makeSyncClientState())
        }
        if let syncSocket {
            let ready = await WatchSocketReadiness.wait(maxAttempts: 80, interval: .milliseconds(100)) {
                if Task.isCancelled || self.isForeground || self.isStopped { return .closed }
                return syncSocket.isConnected ? .open : .retry
            }
            guard ready else { return }
        }
        await refresh()
        guard !Task.isCancelled, !isForeground else { return }
        scheduleRecentOfflineSync()
        await withTaskCancellationHandler(operation: { await waitForRecentOfflineSync() }, onCancel: {
            Task { @MainActor [weak self] in self?.cancelRecentOfflineSync() }
        })
    }

    private func cancelRecentOfflineSync() {
        recentOfflineRunID = nil
        recentOfflineTask?.cancel()
        recentOfflineTask = nil
    }

    func setForegroundNavigationBusy(_ busy: Bool) {
        foregroundNavigationBusy = busy
        if busy { cancelRecentOfflineSync() }
        else { scheduleRecentOfflineSync() }
    }

    private func scheduleRecentOfflineSync() {
        guard canMaintainRecentOfflineChats else { return }
        recentOfflineNeedsRefresh = true
        guard recentOfflineTask == nil else { return }
        let id = UUID()
        recentOfflineRunID = id
        recentOfflineTask = Task(priority: .utility) { @MainActor [weak self] in
            guard let self else { return }
            while self.recentOfflineNeedsRefresh, self.recentOfflineRunID == id, self.canMaintainRecentOfflineChats {
                self.recentOfflineNeedsRefresh = false
                await self.maintainRecentOfflineChats(runID: id)
            }
            if self.recentOfflineRunID == id {
                self.recentOfflineTask = nil
                self.recentOfflineRunID = nil
            }
        }
    }

    /// Deterministic completion hook; production starts maintenance from list
    /// refresh, socket readiness, and hub foreground entry.
    func waitForRecentOfflineSync() async {
        while let task = recentOfflineTask { await task.value }
    }

    private func maintainRecentOfflineChats(runID: UUID) async {
        guard let socket = syncSocket else { return }
        let socketGeneration = socket.generation
        let generation = lifecycleGeneration
        func check() throws {
            try Task.checkCancellation()
            guard canMaintainRecentOfflineChats, recentOfflineRunID == runID,
                  lifecycleGeneration == generation, socket.generation == socketGeneration else { throw CancellationError() }
        }
        let cohort = WatchRecentOfflinePolicy.cohort(chats)
        for chat in cohort {
            do {
                try check()
                let revision = WatchRecentOfflinePolicy.revision(chat)
                if let existing = await cache.loadConversation(chatID: chat.id, accountID: accountID, serverScope: serverScope),
                   existing.revision == revision { continue }
                try check()
                let fields = try await socket.requestEvent(type: "request_chat_content_batch", payload: ["chat_ids": [chat.id]],
                    responseTypes: ["chat_content_batch_response"], matching: {
                        ($0["messages_by_chat_id"] as? [String: Any])?[chat.id] != nil
                    }, beforeSend: { try check() })
                try check()
                let prepared = try await cache.prepareConversation(JSONSerialization.data(withJSONObject: fields), chatID: chat.id)
                try check()
                guard let current = chats.first(where: { $0.id == chat.id }), WatchRecentOfflinePolicy.revision(current) == revision,
                      prepared.messagesVersion >= chat.messagesV else { continue }
                var remote = WatchRemoteChat(id: chat.id, title: nil, lastMessageAt: chat.lastMessageAt, updatedAt: nil,
                    chatSummary: nil, isPinned: chat.isPinned, encryptedTitle: chat.encryptedTitle,
                    encryptedChatSummary: chat.encryptedPreview, encryptedChatKey: chat.encryptedChatKey)
                remote.chatKeyWrappers = prepared.wrappers
                remote.messagesV = prepared.messagesVersion
                guard let keyedChat = await crypto.decryptChat(remote), let recoveryWrapper = crypto.offlineWrappedChatKey(for: keyedChat) else { throw WatchChatRuntimeError.missingChatKey }
                try check()
                func seal(_ pages: [Data]) async throws -> [String] {
                    var result: [String] = []
                    for page in pages {
                        try check()
                        result.append(try await crypto.encryptText(String(decoding: page, as: UTF8.self), for: keyedChat))
                        await Task.yield()
                    }
                    return result
                }
                let messagePages = try await seal(prepared.messagePages)
                let embedPages = try await seal(prepared.embedPages)
                let supplemental = try await crypto.encryptText(String(decoding: prepared.supplemental, as: UTF8.self), for: keyedChat)
                try check()
                var storedChat = chat
                storedChat.title = nil; storedChat.preview = nil; storedChat.category = nil; storedChat.icon = nil
                storedChat.offlineWrappedChatKey = recoveryWrapper
                var value = WatchOfflineConversation(chat: storedChat, accountID: accountID, serverScope: serverScope,
                    revision: revision, messagesVersion: prepared.messagesVersion, messageCount: prepared.messageCount,
                    messagePages: messagePages, embedPages: embedPages, supplemental: supplemental)
                value.wrappedRecoveryChatKey = recoveryWrapper
                guard let latest = chats.first(where: { $0.id == chat.id }), WatchRecentOfflinePolicy.revision(latest) == revision else { continue }
                try await cache.saveConversation(value, accountGeneration: accountLifecycleGeneration)
                await Task.yield()
            } catch is CancellationError { return }
            catch {
                guard (try? check()) != nil else { return }
                NativeDiagnostics.event("recent_offline_chat_incomplete", category: "watch_chat", level: .warning)
            }
        }
        do {
            try check()
            try await cache.pruneConversations(retaining: Set(WatchRecentOfflinePolicy.cohort(chats).map(\.id)))
        } catch { }
    }

    private static func isConnectivityError(_ error: Error) -> Bool {
        guard let urlError = error as? URLError else { return false }
        return [.notConnectedToInternet, .networkConnectionLost, .cannotConnectToHost,
                .cannotFindHost, .timedOut].contains(urlError.code)
    }

    func startRealtimeSync() async {
        guard !isStopped, let syncSocket, let syncSession else { return }
        let generation = lifecycleGeneration
        completionRetryAttempt = 0
        syncSocket.setChangeHandler { [weak self] in
            guard let self, !self.isStopped, self.lifecycleGeneration == generation else { return }
            Task {
                await self.refreshSelectedChat()
                if self.selectedChatId == nil, !self.foregroundNavigationBusy { await self.refresh() }
            }
        }
        syncSocket.setEventHandler { [weak self] type, payload in
            guard let self, !self.isStopped, self.lifecycleGeneration == generation else { return }
            self.handleDraftSyncEvent(type: type, payload: payload)
            Task { @MainActor in
                guard self.lifecycleGeneration == generation, !self.isStopped else { return }
                await self.handleCompletionEvent(type: type, payload: payload)
                guard self.lifecycleGeneration == generation, !self.isStopped else { return }
                await self.handleEmbedEvent(type: type, payload: payload)
            }
        }
        syncSocket.setReadyHandler { [weak self] in
            guard let self, !self.isStopped, self.lifecycleGeneration == generation else { return }
            self.receiptAttemptID = UUID()
            self.inFlightReceiptIDs = []
            Task { @MainActor in
                await self.foregroundHeartbeat()
                self.scheduleRecentOfflineSync()
            }
        }
        syncSocket.connect(session: syncSession, syncState: makeSyncClientState())
        await replayPendingDrafts()
        await replayPendingTextSends()
        await flushPendingCompletions()
        await requestSelectedEmbedPreviews()
        // Cohort maintenance must not require opening the Chats section first.
        await refresh()
    }

    /// Resolve only the requested authorized/decryptable chat. A missing target
    /// leaves the list in an error state and never substitutes another chat.
    func openNotificationChat(chatID: String) async -> WatchNotificationResolution {
        guard !isStopped, !chatID.isEmpty else { return .stale }
        selectedChatId = nil
#if DEBUG
        if isPreviewFixture {
            guard chats.contains(where: { $0.id == chatID }) else { chatLoadFailed = true; return .unavailable }
            selectedChatId = chatID
            return .opened
        }
#endif
        if !chats.contains(where: { $0.id == chatID }) { await refresh() }
        guard !isStopped else { return .stale }
        guard let chat = chats.first(where: { $0.id == chatID }) else {
            if chatListAuthoritative { chatLoadFailed = true; return .unavailable }
            return .retry
        }
        await openChat(chat)
        guard !isStopped else { return .stale }
        return selectedChatId == chatID && errorMessage == nil ? .opened : .retry
    }

    func openChat(_ chat: WatchChatSummary) async {
        guard !isStopped else { return }
        cancelRecentOfflineSync()
        let generation = lifecycleGeneration
        let profile = ServerProfile.current()
        selectedChatId = chat.id
        let requestID = UUID(); windowRequestID = requestID
        hasMoreRemoteMessages = false; remoteStartCursor = nil
        isLoadingRemoteMessages = false
        offlineConversation = nil
        offlinePageIndex = nil; offlinePageCount = 0
        if let conversation = await cache.loadConversation(chatID: chat.id, accountID: accountID, serverScope: serverScope) {
            guard !isStopped, generation == lifecycleGeneration, selectedChatId == chat.id else { return }
            offlineConversation = conversation
            if conversation.messagePages.isEmpty { messagesByChatId[chat.id] = [] }
            await loadOfflinePage(max(0, conversation.messagePages.count - 1))
        }
        if messagesByChatId[chat.id] == nil {
            let snapshot = await cache.loadSnapshot()
            guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(), selectedChatId == chat.id, windowRequestID == requestID else { return }
            if snapshot.accountID == accountID,
               snapshot.serverScope == serverScope || (accountID == nil && snapshot.serverScope == nil) {
                var cachedMessages: [WatchChatMessage] = []
                for message in (snapshot.messagesByChatId[chat.id] ?? []).suffix(50) {
                    var decrypted = await crypto.decryptMessage(.init(id: message.id, chatId: message.chatId, role: message.role,
                        content: message.content, encryptedContent: message.encryptedContent, embedRefs: message.embedRefs, createdAt: message.createdAt))
                    guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(), selectedChatId == chat.id, windowRequestID == requestID else { return }
                    decrypted.isPending = message.isPending
                    cachedMessages.append(decrypted)
                }
                messagesByChatId[chat.id] = Self.sortedMessages(cachedMessages)
            }
        }
        // An omitted REST message version also decodes as zero. Only a known
        // unsent draft can skip fetching; an empty cache is not authoritative.
        let isDraftOnly = chat.messagesV == 0 && chat.titleV == 0 && chat.metadataV == 0
            && (transientChat?.id == chat.id || encryptedDrafts[chat.id]?.encryptedMarkdown != nil)
        if isDraftOnly, messagesByChatId[chat.id] == [] { return }
        if isOffline, offlinePageIndex != nil { return }

        do {
            let window = try await fetchWithRetry {
                try await api.fetchMessageWindow(chatId: chat.id, query: WatchMessageWindowQuery(), context: requestContext())
            }
            guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(),
                  selectedChatId == chat.id, windowRequestID == requestID else { return }
            try validateWindow(window, chatID: chat.id, limit: 50)
            let decrypted = await decryptMessages(window.messages)
            guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(),
                  selectedChatId == chat.id, windowRequestID == requestID else { return }
            mergeForegroundWindow(decrypted, chatID: chat.id)
            remoteStartCursor = window.startCursor
            hasMoreRemoteMessages = window.hasMoreBefore && window.startCursor != nil
            offlinePageIndex = nil; offlinePageCount = 0
            // A viewing page cannot advance content-sync versions or certify a
            // complete offline snapshot. Maintenance keeps its full-history path.
            isOffline = false
            errorMessage = nil
            do {
                try await persistSnapshot()
            } catch {
                NativeDiagnostics.failure("persist_failed", category: "watch_chat", level: .warning, error: error)
            }
        } catch {
            guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(), selectedChatId == chat.id, windowRequestID == requestID else { return }
            NativeDiagnostics.failure("messages_fetch_failed", category: "watch_chat", level: .warning, error: error)
            isOffline = Self.isConnectivityError(error)
            errorMessage = error.localizedDescription
        }
        guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(), selectedChatId == chat.id, windowRequestID == requestID else { return }
        await requestSelectedEmbedPreviews()
    }

    func loadOfflinePage(_ index: Int) async {
        guard !isLoadingOfflinePage, !isStopped, let value = offlineConversation,
              selectedChatId == value.chat.id, index >= 0, index < value.messagePages.count else { return }
        isLoadingOfflinePage = true
        defer { isLoadingOfflinePage = false }
        let generation = lifecycleGeneration
        let selection = selectedChatId
        do {
            let chat = value.chat
            var remote = WatchRemoteChat(id: chat.id, title: nil, lastMessageAt: chat.lastMessageAt, updatedAt: nil,
                chatSummary: nil, isPinned: chat.isPinned, encryptedTitle: chat.encryptedTitle,
                encryptedChatSummary: chat.encryptedPreview, encryptedChatKey: chat.encryptedChatKey)
            if let wrapped = value.wrappedRecoveryChatKey ?? chat.offlineWrappedChatKey {
                remote.chatKeyWrappers = [WatchChatKeyWrapperRecord(id: nil, hashedChatId: WatchChatKeyWrapperRecord.hashedChatId(for: chat.id),
                    keyType: "master", encryptedChatKey: wrapped, wrapperVersion: nil, createdAt: nil)]
            }
            guard let keyed = await crypto.decryptChat(remote) else { throw WatchChatRuntimeError.missingChatKey }
            let plaintext = try await crypto.decryptText(value.messagePages[index], for: keyed)
            let page = try await cache.decodeMessagePage(Data(plaintext.utf8))
            let messages = Self.sortedMessages(await decryptMessages(page))
            guard !isStopped, generation == lifecycleGeneration, selectedChatId == selection else { return }
            let pending = (messagesByChatId[chat.id] ?? []).filter(\.isPending)
            messagesByChatId[chat.id] = Self.sortedMessages(messages + pending.filter { item in !messages.contains(where: { $0.id == item.id }) })
            hydratedEmbedPreviews.removeAll()
            var needed = Set(messages.flatMap { WatchMessageContentSanitizer.mergedEmbedRefs(content: $0.content, provided: $0.embedRefs).map(\.id) })
            // Two passes allow parents to reveal child IDs without decrypting
            // unrelated payloads or retaining other conversations in RAM.
            for _ in 0..<2 {
                for sealed in value.embedPages {
                    let text = try await crypto.decryptText(sealed, for: keyed)
                    let rows = try await cache.decodeEmbedPage(Data(text.utf8))
                    for row in rows {
                        var payload = row.mapValues(\.value)
                        guard let id = payload["embed_id"] as? String, needed.contains(id), hydratedEmbedPreviews[id] == nil else { continue }
                        payload["user_id"] = accountID
                        if let ref = try? await crypto.hydrateEmbed(payload: payload, chat: keyed) {
                            guard !isStopped, generation == lifecycleGeneration, selectedChatId == selection else { return }
                            hydratedEmbedPreviews[id] = ref
                            needed.formUnion(WatchEmbedPreviewMapper.embedRecord(from: ref).childEmbedIds)
                        }
                    }
                    guard !isStopped, generation == lifecycleGeneration, selectedChatId == selection else { return }
                    await Task.yield()
                }
            }
            offlinePageIndex = index; offlinePageCount = value.messagePages.count
        } catch {
            if !isStopped, generation == lifecycleGeneration, selectedChatId == selection {
                NativeDiagnostics.event("offline_page_unavailable", category: "watch_chat", level: .warning)
            }
        }
    }

    func messageWithHydratedEmbeds(_ message: WatchChatMessage) -> WatchChatMessage {
        var result = message
        result.embedRefs = WatchMessageContentSanitizer.mergedEmbedRefs(content: message.content, provided: message.embedRefs)
            .map { hydratedEmbedPreviews[$0.id] ?? $0 }
        return result
    }

    /// Parent previews may summarize their hydrated children. Keep those
    /// child payloads in lookup memory without rendering duplicate cards.
    func hydratedChildRecords(for message: WatchChatMessage) -> [EmbedRecord] {
        let roots = messageWithHydratedEmbeds(message).watchEmbedRecords
        let ids = roots.flatMap(\.childEmbedIds)
        var seen = Set(roots.map(\.id))
        return ids.prefix(30).compactMap { id in
            guard seen.insert(id).inserted, let ref = hydratedEmbedPreviews[id] else { return nil }
            return WatchEmbedPreviewMapper.embedRecord(from: ref)
        }
    }

    func requestSelectedEmbedPreviews() async {
        guard !isStopped, let syncSocket, let chat = selectedChat else { return }
        let generation = lifecycleGeneration
        let socketGeneration = syncSocket.generation
        let profile = ServerProfile.current()
        if embedSocketGeneration != socketGeneration {
            requestedEmbedPreviews.removeAll()
            embedSocketGeneration = socketGeneration
        }
        let refs = selectedMessages.flatMap { WatchMessageContentSanitizer.mergedEmbedRefs(content: $0.content, provided: $0.embedRefs) }
        var ids = Set(refs.map(\.id))
        for ref in refs {
            let hydrated = hydratedEmbedPreviews[ref.id] ?? ref
            ids.formUnion(WatchEmbedPreviewMapper.embedRecord(from: hydrated).childEmbedIds)
        }
        for embedID in ids {
            guard generation == lifecycleGeneration, socketGeneration == syncSocket.generation, profile == ServerProfile.current(),
                  !isStopped, selectedChatId == chat.id else { return }
            guard hydratedEmbedPreviews[embedID] == nil, requestedEmbedPreviews.insert(embedID).inserted else { continue }
            do { try await syncSocket.sendEvent(type: "request_embed", payload: ["embed_id": embedID]) }
            catch { requestedEmbedPreviews.remove(embedID) }
        }
    }

    func handleEmbedEvent(type: String, payload: [String: Any]) async {
        guard type == "send_embed_data", !isStopped,
              let embedID = payload["embed_id"] as? String else { return }
        let generation = lifecycleGeneration
        let socketGeneration = syncSocket?.generation
        let profile = ServerProfile.current()
        // Attach only to an embed referenced by a chat already opened/decrypted here.
        guard let owner = embedOwner(embedID: embedID) else { return }
        let chat = owner.chat
        do {
            let ref = try await crypto.hydrateEmbed(payload: payload, chat: chat)
            guard generation == lifecycleGeneration, socketGeneration == syncSocket?.generation, profile == ServerProfile.current(),
                  !isStopped else { return }
            hydratedEmbedPreviews[embedID] = ref
            requestedEmbedPreviews.remove(embedID)
            if payload["already_encrypted"] as? Bool != true, payload["encryption_mode"] as? String != "client" {
                let prepared = try await crypto.prepareEmbedStorage(payload: payload, chat: chat, messageID: owner.message.id)
                guard generation == lifecycleGeneration, socketGeneration == syncSocket?.generation,
                      profile == ServerProfile.current(), !isStopped else { return }
                for (event, wire) in [("store_embed_keys", prepared.keys), ("store_embed", prepared.embed)] {
                    guard let requestID = wire["request_id"] as? String else { throw WatchChatRuntimeError.invalidPendingTurn }
                    pendingCompletions.append(WatchPendingCompletion(id: requestID, chatId: chat.id, eventType: event,
                        encryptedPayload: try JSONSerialization.data(withJSONObject: wire)))
                }
                try await persistSnapshot() // Only ciphertext/wrappers/metadata cross the durable boundary.
                await flushPendingCompletions()
            }
            await requestSelectedEmbedPreviews()
        } catch {
            if generation == lifecycleGeneration { requestedEmbedPreviews.remove(embedID) }
        }
    }

    private func embedOwner(embedID: String) -> (chat: WatchChatSummary, message: WatchChatMessage)? {
        for chat in chats {
            for message in messagesByChatId[chat.id] ?? [] {
                if WatchMessageContentSanitizer.mergedEmbedRefs(content: message.content, provided: message.embedRefs).contains(where: { ref in
                    if ref.id == embedID { return true }
                    let hydrated = hydratedEmbedPreviews[ref.id] ?? ref
                    return WatchEmbedPreviewMapper.embedRecord(from: hydrated).childEmbedIds.contains(embedID)
                }) { return (chat, message) }
            }
        }
        return nil
    }

    func createNewChat() async {
        let generation = lifecycleGeneration
        do {
            let chat = try await crypto.createChat()
            guard generation == lifecycleGeneration, !isStopped else { return }
            // Navigation creates only an in-memory identity. First content promotes it.
            transientChat = chat
            selectedChatId = chat.id
            errorMessage = nil
        } catch { if generation == lifecycleGeneration { errorMessage = error.localizedDescription } }
    }

    func updateComposerDraft(_ text: String, chatId: String) {
        guard !isStopped else { return }
        composerDrafts[chatId] = text
        draftRevision &+= 1
        let revision = draftRevision
        draftLocalRevisions[chatId] = revision
        let generation = lifecycleGeneration
        draftSaveTask?.cancel()
        draftSaveTask = Task { [weak self] in
            do { try await Task.sleep(for: .milliseconds(450)) } catch { return }
            await self?.saveComposerDraft(text, chatId: chatId, revision: revision, generation: generation)
        }
    }

    func leaveChat() async {
        guard let chatId = selectedChatId else { return }
        draftSaveTask?.cancel()
        await saveComposerDraft(composerDrafts[chatId] ?? "", chatId: chatId,
                                revision: currentDraftRevision(for: chatId), generation: lifecycleGeneration)
        selectedChatId = nil
        windowRequestID = UUID(); hasMoreRemoteMessages = false; isLoadingRemoteMessages = false; remoteStartCursor = nil
        offlineConversation = nil
        offlinePageIndex = nil; offlinePageCount = 0
        messagesByChatId = messagesByChatId.mapValues { $0.filter(\.isPending) }.filter { !$0.value.isEmpty }
        hydratedEmbedPreviews.removeAll()
        if transientChat?.id == chatId { transientChat = nil }
        scheduleRecentOfflineSync()
    }

    private func currentDraftRevision(for chatId: String) -> UInt64 {
        draftLocalRevisions[chatId] ?? encryptedDrafts[chatId]?.localRevision ?? 0
    }

    private func saveComposerDraft(_ text: String, chatId: String, revision: UInt64, generation: UInt64) async {
        guard generation == lifecycleGeneration, !isStopped, revision == currentDraftRevision(for: chatId) else { return }
        if encryptedDrafts[chatId]?.localRevision == revision {
            // Back and backgrounding flush edits, not an already saved revision.
            // Keep an acknowledged or superseded write retired; dirty retries
            // reuse the exact existing ciphertext through the queue.
            await replayPendingDrafts()
            return
        }
        do {
            let hasContent = !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            let encrypted = hasContent ? try await crypto.encryptDraft(text) : nil
            let preview = hasContent ? try await crypto.encryptDraft(String(text.prefix(160))) : nil
            guard generation == lifecycleGeneration, !isStopped, revision == currentDraftRevision(for: chatId) else { return }
            if hasContent, let chat = transientChat, chat.id == chatId { promoteDraftChatForSending(chat) }
            if !hasContent, (messagesByChatId[chatId] ?? []).isEmpty,
               (chats.first { $0.id == chatId }?.messagesV ?? 0) == 0,
               encryptedDrafts[chatId] != nil || transientChat?.id == chatId {
                chats.removeAll { $0.id == chatId }
                messagesByChatId.removeValue(forKey: chatId)
            }
            // A tombstone remains until receipt so a delayed remote echo cannot resurrect content.
            let old = encryptedDrafts[chatId]
            if hasContent || old != nil {
                encryptedDrafts[chatId] = WatchEncryptedDraft(encryptedMarkdown: encrypted,
                    encryptedPreview: preview, serverVersion: old?.serverVersion ?? 0,
                    localRevision: revision, needsSync: true, clearedVersion: old?.clearedVersion)
                try await persistSnapshot()
                await replayPendingDrafts()
            }
        } catch { if generation == lifecycleGeneration { errorMessage = error.localizedDescription } }
    }

    func promoteDraftChatForSending(_ chat: WatchChatSummary) {
        if !chats.contains(where: { $0.id == chat.id }) { chats.insert(chat, at: 0) }
        if messagesByChatId[chat.id] == nil { messagesByChatId[chat.id] = [] }
    }

    func clearDraftAfterSending(chatId: String) async {
        draftSaveTask?.cancel()
        draftRevision &+= 1
        draftLocalRevisions[chatId] = draftRevision
        composerDrafts[chatId] = ""
        if encryptedDrafts[chatId] != nil {
            encryptedDrafts[chatId]?.encryptedMarkdown = nil
            encryptedDrafts[chatId]?.encryptedPreview = nil
            encryptedDrafts[chatId]?.localRevision = draftRevision
            encryptedDrafts[chatId]?.needsSync = true
            try? await persistSnapshot()
            await replayPendingDrafts()
        }
        if transientChat?.id == chatId { transientChat = nil }
    }

    func replayPendingDrafts() async {
        guard let syncSocket, !isStopped else { return }
        if draftSocketGeneration != syncSocket.generation {
            inFlightDrafts.removeAll()
            draftSocketGeneration = syncSocket.generation
        }
        let generation = lifecycleGeneration
        for (chatId, draft) in encryptedDrafts where draft.needsSync && inFlightDrafts[chatId] == nil
            && (draftLocalRevisions[chatId] ?? 0) <= draft.localRevision {
            guard generation == lifecycleGeneration, !isStopped else { return }
            var payload: [String: Any] = ["chat_id": chatId]
            if let markdown = draft.encryptedMarkdown {
                payload["encrypted_draft_md"] = markdown
                payload["encrypted_draft_preview"] = draft.encryptedPreview
            }
            inFlightDrafts[chatId] = draft
            do { try await syncSocket.sendEvent(type: draft.encryptedMarkdown == nil ? "delete_draft" : "update_draft", payload: payload) }
            catch { inFlightDrafts.removeValue(forKey: chatId); return } // Keep ciphertext and retry when the connection returns.
        }
    }

    func requestDraftVersions() async {
        guard !isStopped, let syncSocket, draftReconciledSocketGeneration != syncSocket.generation else { return }
        draftReconciledSocketGeneration = syncSocket.generation
        let ids = Set(chats.map(\.id)).union(encryptedDrafts.keys).sorted()
        guard !ids.isEmpty else { return }
        let generation = lifecycleGeneration
        for offset in stride(from: 0, to: ids.count, by: 100) {
            guard generation == lifecycleGeneration, !isStopped else { return }
            let slice = ids[offset..<min(offset + 100, ids.count)]
            let entries: [[String: Any]] = slice.map { ["chat_id": $0, "client_draft_v": encryptedDrafts[$0]?.serverVersion ?? 0] }
            do { try await syncSocket.sendEvent(type: "get_draft_versions", payload: ["chats": entries]) }
            catch { draftReconciledSocketGeneration = nil; return }
        }
    }

    private func reconcileDraftVersions(_ payload: [String: Any]) async {
        guard !isStopped, let syncSocket, let versions = payload["versions"] as? [String: Int] else { return }
        let unavailable = Set(payload["unavailable_chat_ids"] as? [String] ?? [])
        let tombstones = payload["tombstone_versions"] as? [String: Int] ?? [:]
        var refreshIDs: [String] = []
        for (id, version) in versions where !unavailable.contains(id) {
            let local = encryptedDrafts[id]
            if version == 0 {
                // A missing Redis/Directus row is not an authoritative deletion.
                if let tombstone = tombstones[id], tombstone > 0 {
                    handleDraftSyncEvent(type: "draft_deleted", payload: ["chat_id": id, "draft_v": tombstone])
                }
            } else if version > (local?.serverVersion ?? 0), local?.needsSync != true,
                      (draftLocalRevisions[id] ?? 0) <= (local?.localRevision ?? 0) { refreshIDs.append(id) }
        }
        guard !refreshIDs.isEmpty else { return }
        // The backend phase2 refresh path supports explicit IDs outside the recent page.
        // get_chat_details is not implemented on this backend.
        let generation = lifecycleGeneration
        let socketGeneration = syncSocket.generation
        for offset in stride(from: 0, to: refreshIDs.count, by: 50) {
            guard generation == lifecycleGeneration, socketGeneration == syncSocket.generation, !isStopped else { return }
            var request = makeSyncClientState().phasedSyncPayload
            request["phase"] = "phase2"
            request["refresh_chat_ids"] = Array(refreshIDs[offset..<min(offset + 50, refreshIDs.count)])
            try? await syncSocket.sendEvent(type: "phased_sync_request", payload: request)
        }
    }

    private func applyDraftDetails(_ details: [String: Any]) {
        guard let id = (details["id"] as? String) ?? (details["chat_id"] as? String),
              let draftVersion = details["draft_v"] as? Int else { return }
        let hasMarkdownField = details.keys.contains("encrypted_draft_md")
        let incoming = details["encrypted_draft_md"] as? String
        let cleared = details["cleared_draft_v"] as? Int ?? 0
        if hasMarkdownField, incoming == nil {
            handleDraftSyncEvent(type: "draft_deleted", payload: ["chat_id": id, "draft_v": max(draftVersion, cleared)])
        } else if let incoming {
            var payload = details
            payload["chat_id"] = id
            payload["draft_v"] = draftVersion
            payload["encrypted_draft_md"] = incoming
            handleDraftSyncEvent(type: "chat_draft_updated", payload: payload)
        }
    }

    func handleDraftSyncEvent(type: String, payload: [String: Any]) {
        guard !isStopped else { return }
        if let teamID = payload["team_id"], !(teamID is NSNull) { return }
        if let epoch = payload["context_epoch"] as? Int, epoch != 0 { return }
        if type == "draft_versions_response" {
            Task { [weak self] in await self?.reconcileDraftVersions(payload) }; return
        }
        if type == "phased_sync_complete" {
            Task { [weak self] in await self?.requestDraftVersions() }; return
        }
        if type == "chat_details" {
            applyDraftDetails(payload["chat_details"] as? [String: Any] ?? payload); return
        }
        if ["phase_1_last_chat_ready", "phase_2_last_20_chats_ready", "load_more_chats_response", "sync_metadata_chats_response"].contains(type) {
            if let details = payload["chat_details"] as? [String: Any] { applyDraftDetails(details) }
            for details in payload["recent_chat_metadata"] as? [[String: Any]] ?? [] { applyDraftDetails(details) }
            for wrapper in payload["chats"] as? [[String: Any]] ?? [] {
                applyDraftDetails(wrapper["chat_details"] as? [String: Any] ?? wrapper)
            }
            return
        }
        guard let chatId = payload["chat_id"] as? String else { return }
        guard ["draft_update_receipt", "draft_delete_receipt", "chat_draft_updated", "chat_draft_deleted", "draft_deleted"].contains(type) else { return }
        if type.hasSuffix("_receipt"), payload["success"] as? Bool == false {
            inFlightDrafts.removeValue(forKey: chatId)
            return
        }
        let versions = payload["versions"] as? [String: Any]
        guard let version = (payload["draft_v"] as? Int) ?? (versions?["draft_v"] as? Int) else { return }
        let previous = encryptedDrafts[chatId]
        guard version >= (previous?.serverVersion ?? 0) else { return }
        let receipt = type.hasSuffix("_receipt")
        let data = payload["data"] as? [String: Any] ?? payload
        var incoming = data["encrypted_draft_md"] as? String
        var incomingPreview = data["encrypted_draft_preview"] as? String
        if receipt {
            guard let sent = inFlightDrafts.removeValue(forKey: chatId), payload["success"] as? Bool == true else { return }
            // Socket serializes one outstanding write per chat: old receipts update
            // only the version while a newer edit remains dirty and is sent next.
            if sent.localRevision != previous?.localRevision || (draftLocalRevisions[chatId] ?? 0) > sent.localRevision {
                encryptedDrafts[chatId]?.serverVersion = version
                Task { [weak self] in await self?.replayPendingDrafts() }
                return
            }
            if payload["superseded"] as? Bool == true {
                // The attempted write lost to another device. Retire only this
                // revision; its allocated version does not acknowledge its ciphertext.
                encryptedDrafts[chatId]?.needsSync = false
                let generation = lifecycleGeneration
                let socketGeneration = syncSocket?.generation
                Task { [weak self] in
                    // Persist the retired queue even if the transport reconnects;
                    // snapshot writes still validate account, profile and lifecycle.
                    guard let self, generation == self.lifecycleGeneration, !self.isStopped else { return }
                    try? await self.persistSnapshot()
                    guard generation == self.lifecycleGeneration, !self.isStopped,
                          socketGeneration == self.syncSocket?.generation, let socket = self.syncSocket else { return }
                    // Force the supported detail path even if version discovery
                    // already ran on this socket or the winning broadcast was missed.
                    var request = self.makeSyncClientState().phasedSyncPayload
                    request["phase"] = "phase2"
                    request["refresh_chat_ids"] = [chatId]
                    try? await socket.sendEvent(type: "phased_sync_request", payload: request)
                }
                return
            }
            incoming = sent.encryptedMarkdown
            incomingPreview = sent.encryptedPreview
        } else if previous?.needsSync == true || (draftLocalRevisions[chatId] ?? 0) > (previous?.localRevision ?? 0) {
            // Unsent local content and deletion tombstones win until acknowledged.
            return
        }
        let explicitNull = data.keys.contains("encrypted_draft_md") && incoming == nil
        let isDeletion = type == "chat_draft_deleted" || type == "draft_deleted" || type == "draft_delete_receipt" || explicitNull
        guard isDeletion || incoming != nil else { return } // Positive metadata omission preserves content.
        if !isDeletion, version <= (previous?.clearedVersion ?? 0) { return }
        if !receipt, !isDeletion, version == previous?.serverVersion,
           previous?.encryptedMarkdown != nil, incoming != previous?.encryptedMarkdown { return }
        encryptedDrafts[chatId] = WatchEncryptedDraft(encryptedMarkdown: isDeletion ? nil : incoming,
            encryptedPreview: incomingPreview, serverVersion: version,
            localRevision: previous?.localRevision ?? 0, needsSync: false,
            clearedVersion: isDeletion ? max(version, previous?.clearedVersion ?? 0) : previous?.clearedVersion)
        let generation = lifecycleGeneration
        let socketGeneration = syncSocket?.generation
        let revision = encryptedDrafts[chatId]?.localRevision
        Task { [weak self] in
            guard let self else { return }
            let decoded = isDeletion ? "" : (try? await self.crypto.decryptDraft(incoming!))
            guard generation == self.lifecycleGeneration, socketGeneration == self.syncSocket?.generation, !self.isStopped,
                  self.encryptedDrafts[chatId]?.serverVersion == version,
                  self.encryptedDrafts[chatId]?.localRevision == revision,
                  (self.draftLocalRevisions[chatId] ?? 0) <= (revision ?? 0),
                  self.encryptedDrafts[chatId]?.needsSync == false else { return }
            guard let decoded else { return }
            self.composerDrafts[chatId] = decoded
            if !decoded.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
               !self.chats.contains(where: { $0.id == chatId }) {
                self.chats.insert(WatchChatSummary(id: chatId, title: nil,
                    lastMessageAt: nil, preview: nil, isPinned: false,
                    encryptedTitle: payload["encrypted_title"] as? String, encryptedPreview: nil,
                    encryptedChatKey: payload["encrypted_chat_key"] as? String,
                    messagesV: payload["messages_v"] as? Int ?? 0, titleV: payload["title_v"] as? Int ?? 0,
                    metadataV: payload["metadata_v"] as? Int ?? 0), at: 0)
                self.messagesByChatId[chatId] = []
            } else if isDeletion, let chat = self.chats.first(where: { $0.id == chatId }),
                      chat.messagesV == 0, (self.messagesByChatId[chatId] ?? []).isEmpty {
                self.chats.removeAll { $0.id == chatId }
                self.messagesByChatId.removeValue(forKey: chatId)
                if self.selectedChatId == chatId { self.selectedChatId = nil }
            }
            try? await self.persistSnapshot()
        }
    }

    func stopRealtimeSync() {
        cancelRecentOfflineSync()
        lifecycleGeneration &+= 1
        isStopped = true
        draftSaveTask?.cancel()
        completionTask?.cancel()
        inFlightDrafts.removeAll()
        receiptAttemptID = UUID()
        inFlightReceiptIDs = []
        visibleReceiptIDs = []
        visibleChatID = nil
        receiptChatID = nil
        acknowledgedReceiptIDs = []
        isForeground = false
        syncSocket?.disconnect()
    }

    func updateWebSocketToken(_ token: String?) {
        guard !isStopped, let syncSession else { return }
        self.syncSession = WatchSyncSession(sessionId: syncSession.sessionId, token: token)
    }

    func setForeground(_ foreground: Bool) async {
        guard !isStopped else { return }
        isForeground = foreground
        receiptAttemptID = UUID()
        inFlightReceiptIDs = []
        if foreground {
            if backgroundOfflineMaintenance { backgroundOfflineMaintenance = false; cancelRecentOfflineSync() }
            await foregroundHeartbeat()
            scheduleRecentOfflineSync()
        } else if let syncSocket, syncSocket.isConnected {
            cancelRecentOfflineSync()
            do {
                try await syncSocket.sendEvent(type: "native_client_lifecycle",
                    payload: ["is_foreground": false, "client_type": "apple"])
            } catch {
                NativeDiagnostics.failure("background_presence_failed", category: "watch_chat_socket",
                                          level: .warning, error: error)
            }
        }
        if !foreground { cancelRecentOfflineSync() }
    }

    func foregroundHeartbeat() async {
        guard !isStopped, isForeground, accountID != nil,
              let syncSocket, let syncSession else { return }
        if !syncSocket.isConnected {
            syncSocket.connect(session: syncSession, syncState: makeSyncClientState())
            return
        }
        do {
            try await syncSocket.sendEvent(type: "native_client_lifecycle",
                payload: ["is_foreground": true, "client_type": "apple"])
            try await syncSocket.sendEvent(type: "set_active_chat",
                payload: ["chat_id": visibleChatID.map { $0 as Any } ?? NSNull()])
        } catch {
            NativeDiagnostics.failure("foreground_presence_failed", category: "watch_chat_socket",
                                      level: .warning, error: error)
        }
        retryVisibleReceipts()
    }

    func setVisibleChatID(_ chatID: String?) {
        guard !isStopped else { return }
        if let chatID, receiptChatID != chatID {
            receiptChatID = chatID
            acknowledgedReceiptIDs = []
        }
        if visibleChatID != chatID {
            visibleChatID = chatID
            visibleReceiptIDs = []
            inFlightReceiptIDs = []
            receiptAttemptID = UUID()
        }
        guard isForeground, syncSocket?.isConnected == true else { return }
        Task { @MainActor in
            guard !isStopped, isForeground, visibleChatID == chatID else { return }
            try? await syncSocket?.sendEvent(type: "set_active_chat",
                payload: ["chat_id": chatID.map { $0 as Any } ?? NSNull()])
        }
    }

    func updateVisibleMessages(_ ids: Set<String>, chatID: String?) {
        guard !isStopped, let chatID, visibleChatID == chatID, selectedChatId == chatID else { return }
        let committed = Set((messagesByChatId[chatID] ?? []).filter {
            ids.contains($0.id) && !$0.isPending && ($0.role == .assistant || $0.role == .user)
        }.map(\.id))
        visibleReceiptIDs = committed
        retryVisibleReceipts()
    }

    private func retryVisibleReceipts() {
        guard !isStopped, isForeground, let accountID, let chatID = visibleChatID,
              selectedChatId == chatID, let syncSocket, syncSocket.isConnected else { return }
        let scope = serverScope
        let accountGeneration = accountLifecycleGeneration
        let socketGeneration = syncSocket.generation
        let attemptID = receiptAttemptID
        for messageID in visibleReceiptIDs.subtracting(acknowledgedReceiptIDs).subtracting(inFlightReceiptIDs) {
            inFlightReceiptIDs.insert(messageID)
            Task { @MainActor in
                let requestID = UUID().uuidString
                var viewed = false
                do {
                    let response = try await syncSocket.requestEvent(
                        type: "chat_message_viewed",
                        payload: ["request_id": requestID, "chat_id": chatID, "message_id": messageID],
                        responseTypes: ["notification_message_viewed_ack"],
                        matching: { ($0["request_id"] as? String) == requestID },
                        beforeSend: {
                            guard !self.isStopped, self.isForeground, self.accountID == accountID,
                                  self.accountLifecycleGeneration == accountGeneration,
                                  self.serverScope == scope, Self.currentServerScope == scope,
                                  syncSocket.generation == socketGeneration,
                                  self.visibleChatID == chatID, self.selectedChatId == chatID,
                                  self.visibleReceiptIDs.contains(messageID),
                                  self.receiptAttemptID == attemptID else { throw CancellationError() }
                        }
                    )
                    viewed = response["chat_id"] as? String == chatID
                        && response["message_id"] as? String == messageID
                        && response["viewed"] as? Bool == true
                } catch {
                    NativeDiagnostics.failure("visible_receipt_failed", category: "watch_chat_socket",
                                              level: .warning, error: error)
                }
                guard !isStopped, isForeground, self.accountID == accountID,
                      accountLifecycleGeneration == accountGeneration,
                      serverScope == scope, Self.currentServerScope == scope,
                      syncSocket.generation == socketGeneration,
                      visibleChatID == chatID, selectedChatId == chatID,
                      receiptAttemptID == attemptID else { return }
                inFlightReceiptIDs.remove(messageID)
                if viewed { acknowledgedReceiptIDs.insert(messageID) }
            }
        }
    }

    func flushDraftAndStop() async {
        draftSaveTask?.cancel()
        if let chatId = selectedChatId {
            await saveComposerDraft(composerDrafts[chatId] ?? "", chatId: chatId,
                                    revision: currentDraftRevision(for: chatId), generation: lifecycleGeneration)
        }
        stopRealtimeSync()
    }

    @discardableResult
    func sendText(_ content: String) async -> Bool {
        guard var chat = selectedChat else {
            errorMessage = WatchChatRuntimeError.noSelectedChat.localizedDescription
            return false
        }
        do { chat = try await prepareDraftChatForSending(chat) }
        catch { if !isStopped { errorMessage = error.localizedDescription }; return false }
        return await send(content: content, chat: chat, embed: nil)
    }

    @discardableResult
    func sendAudioRecording(data: Data, filename: String, duration: TimeInterval) async -> Bool {
        guard var chat = selectedChat else {
            errorMessage = WatchChatRuntimeError.noSelectedChat.localizedDescription
            return false
        }
        guard !data.isEmpty, duration > 0 else {
            errorMessage = WatchChatRuntimeError.invalidRecording.localizedDescription
            return false
        }
        let generation = lifecycleGeneration
        let profile = ServerProfile.current()
        do {
            chat = try await prepareDraftChatForSending(chat)
            let upload = try await api.uploadAudioRecording(data: data, filename: filename, chatId: chat.id, context: requestContext())
            guard generation == lifecycleGeneration, !isStopped, profile == ServerProfile.current() else { return false }
            let transcription = try await api.transcribeAudioRecording(upload, chatId: chat.id, context: requestContext())
            guard generation == lifecycleGeneration, !isStopped, profile == ServerProfile.current() else { return false }
            let embed = WatchPendingAudioEmbed.from(upload: upload, transcription: transcription, duration: duration)
            return await send(content: embed.markdownReference, chat: chat, embed: embed)
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    private func prepareDraftChatForSending(_ original: WatchChatSummary) async throws -> WatchChatSummary {
        guard original.encryptedChatKey == nil, original.encryptedTitle == nil,
              original.messagesV == 0, original.titleV == 0, original.metadataV == 0,
              encryptedDrafts[original.id]?.encryptedMarkdown != nil,
              (messagesByChatId[original.id] ?? []).isEmpty else { return original }
        let generation = lifecycleGeneration
        let prepared = try await crypto.createChat(withID: original.id)
        guard generation == lifecycleGeneration, !isStopped, prepared.id == original.id else { throw CancellationError() }
        if let index = chats.firstIndex(where: { $0.id == original.id }) { chats[index] = prepared }
        return prepared
    }

    private func send(content: String, chat: WatchChatSummary, embed: WatchPendingAudioEmbed?) async -> Bool {
        guard !isStopped else { return false }
        let generation = lifecycleGeneration
        let profile = ServerProfile.current()
        func validate() throws {
            guard !Task.isCancelled, generation == lifecycleGeneration, !isStopped,
                  profile == ServerProfile.current() else { throw WatchChatRuntimeError.socketUnavailable }
        }
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            errorMessage = WatchChatRuntimeError.noSelectedChat.localizedDescription
            return false
        }
        guard let encryptedChatKey = chat.encryptedChatKey else {
            errorMessage = WatchChatRuntimeError.missingChatKey.localizedDescription
            return false
        }
        guard !isSending else {
            errorMessage = WatchChatRuntimeError.sendInProgress.localizedDescription
            return false
        }
        if !pendingTextSends.isEmpty {
            await replayPendingTextSends()
            guard pendingTextSends.isEmpty else {
                if errorMessage == nil {
                    errorMessage = WatchChatRuntimeError.socketUnavailable.localizedDescription
                }
                return false
            }
        }
        isSending = true
        defer { isSending = false }
        var queued = false
        do {
            guard let syncSocket, syncSession != nil else { throw WatchChatRuntimeError.socketUnavailable }
            let now = Date()
            let createdAt = ISO8601DateFormatter().string(from: now)
            let createdAtUnix = Int(now.timeIntervalSince1970)
            let messageId = UUID().uuidString.lowercased()
            let turnId = UUID().uuidString.lowercased()
            let encryptedContent = try await crypto.encryptText(trimmed, for: chat)
            let recoveryPublicKey = try await crypto.recoveryPublicKey(for: chat)
            try validate()
            let existing = messagesByChatId[chat.id] ?? []
            let expectedVersion = max(chat.messagesV, existing.filter { !$0.isPending }.count)
            let titleVersion = max(chat.titleV, chat.title?.isEmpty == false ? 1 : 0)
            let metadataVersion = max(chat.metadataV, titleVersion)
            var message: [String: Any] = [
                "message_id": messageId, "role": "user", "content": trimmed,
                "created_at": createdAtUnix, "sender_name": "user",
                "chat_has_title": titleVersion > 0, "current_chat_title_v": titleVersion,
                "current_chat_metadata_v": metadataVersion
            ]
            if titleVersion > 0, let title = chat.title { message["current_chat_title"] = title }
            var inference: [String: Any] = [
                "chat_id": chat.id, "message": message,
                "encrypted_chat_key": encryptedChatKey, "broadcast": false,
                "turn_id": turnId, "recovery_public_key": recoveryPublicKey,
                "chat_key_version": 1
            ]
            let history = try Self.historyPayload(existing + [WatchChatMessage(
                id: messageId, chatId: chat.id, role: .user, content: trimmed,
                encryptedContent: encryptedContent, embedRefs: nil,
                createdAt: createdAt, isPending: true
            )])
            if !existing.isEmpty { inference["message_history"] = history }
            if let embed {
                inference["embeds"] = [[
                    "embed_id": embed.id, "type": "audio-recording", "status": "finished",
                    "content": embed.content, "createdAt": createdAtUnix, "updatedAt": createdAtUnix,
                    "text_preview": embed.transcript ?? embed.filename
                ]]
                inference["encrypted_embeds"] = try await crypto.encryptedAudioEmbed(embed, chat: chat, messageId: messageId)
            }
            let encryptedUserMessage: [String: Any] = [
                "client_message_id": messageId, "chat_id": chat.id,
                "encrypted_content": encryptedContent, "role": "user",
                "created_at": createdAtUnix, "updated_at": createdAtUnix
            ]
            var preflight: [String: Any] = [
                "protocol_version": 1, "chat_id": chat.id, "turn_id": turnId,
                "message_id": messageId, "chat_key_version": 1,
                "encrypted_chat_key": encryptedChatKey,
                "recovery_public_key": recoveryPublicKey,
                "expected_messages_v": expectedVersion,
                "encrypted_user_message": encryptedUserMessage,
                "inference_request": inference
            ]
            if expectedVersion == 0 && titleVersion == 0 {
                let encryptedTitle: String
                if let existingTitle = chat.encryptedTitle { encryptedTitle = existingTitle }
                else { encryptedTitle = try await crypto.encryptText("", for: chat) }
                preflight["encrypted_chat_metadata"] = [
                    "encrypted_title": encryptedTitle,
                    "encrypted_chat_key": encryptedChatKey,
                    "created_at": createdAtUnix, "updated_at": createdAtUnix
                ]
            }
            let prepared = try JSONSerialization.data(withJSONObject: ["preflight": preflight, "inference": inference])
            guard let preparedText = String(data: prepared, encoding: .utf8) else { throw WatchChatRuntimeError.invalidPendingTurn }
            let encryptedPrepared = try await crypto.encryptText(preparedText, for: chat)
            try validate()
            let pending = WatchPendingTextSend(
                id: turnId, chatId: chat.id, messageId: messageId,
                encryptedContent: encryptedContent, encryptedChatKey: encryptedChatKey,
                createdAt: createdAt, encryptedPreparedTurn: encryptedPrepared
            )
            promoteDraftChatForSending(chat)
            var local = messagesByChatId[chat.id] ?? []
            local.append(WatchChatMessage(
                id: messageId, chatId: chat.id, role: .user, content: trimmed,
                encryptedContent: encryptedContent,
                embedRefs: embed.map { [WatchEmbedRef(id: $0.id, type: "audio-recording", status: "finished", data: nil)] },
                createdAt: createdAt, isPending: true
            ))
            messagesByChatId[chat.id] = Self.sortedMessages(local)
            pendingTextSends.append(pending)
            queued = true
            try await persistSnapshot()
            try validate()
            await clearDraftAfterSending(chatId: chat.id)
            try validate()
            syncSocket.connect(session: syncSession!, syncState: makeSyncClientState())
            let socketGeneration = syncSocket.generation
            try await syncSocket.sendTurn(try await preparedTurn(pending, chat: chat), encryptMetadata: { text in
                try validate()
                return try await self.crypto.encryptText(text, for: chat)
            })
            try validate()
            guard socketGeneration == syncSocket.generation else { throw WatchChatRuntimeError.socketUnavailable }
            pendingTextSends.removeAll { $0.id == turnId }
            markPendingMessageSent(messageId: messageId, chatId: chat.id)
            errorMessage = nil
            try await persistSnapshot()
            await flushPendingCompletions()
            await refreshSelectedChat()
            Task { [weak self] in
                try? await Task.sleep(for: .seconds(3))
                await self?.refreshSelectedChat()
            }
            return true
        } catch {
            guard generation == lifecycleGeneration, !isStopped, profile == ServerProfile.current() else { return queued }
            NativeDiagnostics.failure("send_failed", category: "watch_chat_socket", level: .warning, error: error)
            errorMessage = error.localizedDescription
            try? await persistSnapshot()
            return queued
        }
    }

    private static func historyPayload(_ messages: [WatchChatMessage]) throws -> [[String: Any]] {
        var history: [[String: Any]] = []
        var seen = Set<String>()
        for message in messages.sorted(by: { $0.createdAt < $1.createdAt }) {
            guard message.role != .system, seen.insert(message.id).inserted else { continue }
            guard let content = message.content, !content.isEmpty else {
                throw WatchChatRuntimeError.historyUnavailable
            }
            history.append([
                "message_id": message.id, "chat_id": message.chatId,
                "role": message.role.rawValue, "content": content,
                "sender_name": message.role == .user ? "User" : "Assistant",
                "created_at": Int(Double(message.createdAt) ?? (ISO8601DateFormatter().date(from: message.createdAt) ?? Date()).timeIntervalSince1970)
            ])
        }
        return history
    }

    func refreshSelectedChat() async {
        guard !isStopped, let chat = selectedChat else { return }
        let generation = lifecycleGeneration
        let profile = ServerProfile.current()
        let requestID = UUID(); windowRequestID = requestID
        isLoadingRemoteMessages = false
        do {
            let window = try await api.fetchMessageWindow(chatId: chat.id, query: WatchMessageWindowQuery(), context: requestContext())
            guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(),
                  selectedChatId == chat.id, windowRequestID == requestID else { return }
            try validateWindow(window, chatID: chat.id, limit: 50)
            let decrypted = await decryptMessages(window.messages)
            guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(),
                  selectedChatId == chat.id, windowRequestID == requestID else { return }
            mergeForegroundWindow(decrypted, chatID: chat.id)
            if remoteStartCursor == nil { remoteStartCursor = window.startCursor; hasMoreRemoteMessages = window.hasMoreBefore && window.startCursor != nil }
            try await persistSnapshot()
        } catch { /* A new local chat may not exist before its first committed turn. */ }
        guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(),
              selectedChatId == chat.id, windowRequestID == requestID else { return }
        await requestSelectedEmbedPreviews()
    }

    func loadOlderMessages() async {
        guard !isStopped, !isOffline, !isLoadingRemoteMessages, hasMoreRemoteMessages,
              let chat = selectedChat, let cursor = remoteStartCursor else { return }
        let generation = lifecycleGeneration
        let profile = ServerProfile.current()
        let requestID = UUID(); windowRequestID = requestID
        isLoadingRemoteMessages = true
        defer { if windowRequestID == requestID { isLoadingRemoteMessages = false } }
        do {
            let query = WatchMessageWindowQuery(direction: .before, before: cursor)
            let window = try await api.fetchMessageWindow(chatId: chat.id, query: query, context: requestContext())
            guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(),
                  selectedChatId == chat.id, windowRequestID == requestID else { return }
            try validateWindow(window, chatID: chat.id, limit: query.limit)
            let decrypted = await decryptMessages(window.messages)
            guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(),
                  selectedChatId == chat.id, windowRequestID == requestID else { return }
            mergeForegroundWindow(decrypted, chatID: chat.id)
            remoteStartCursor = window.startCursor
            hasMoreRemoteMessages = window.hasMoreBefore && window.startCursor != nil && window.startCursor != cursor
            errorMessage = nil
            try await persistSnapshot()
            await requestSelectedEmbedPreviews()
        } catch {
            guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current(),
                  selectedChatId == chat.id, windowRequestID == requestID else { return }
            errorMessage = WatchChatRuntimeError.historyUnavailable.localizedDescription
        }
    }

    private func validateWindow(_ window: WatchMessageWindow, chatID: String, limit: Int) throws {
        guard window.chatId == chatID, window.messages.count <= limit,
              window.messages.allSatisfy({ $0.chatId == chatID }) else { throw WatchChatRuntimeError.historyUnavailable }
    }

    private func mergeForegroundWindow(_ messages: [WatchChatMessage], chatID: String) {
        partialWindowChats.insert(chatID)
        var byID = Dictionary((messagesByChatId[chatID] ?? []).map { ($0.id, $0) }, uniquingKeysWith: { _, new in new })
        for message in messages { byID[message.id] = message }
        messagesByChatId[chatID] = Self.sortedMessages(Array(byID.values))
    }

    private func apply(_ snapshot: WatchChatSnapshot) {
        encryptedDrafts = snapshot.encryptedDrafts
        draftRevision = encryptedDrafts.values.map(\.localRevision).max() ?? 0
        chats = Self.sortedChats(snapshot.chats)
        messagesByChatId = snapshot.messagesByChatId.mapValues { Self.sortedMessages($0.filter(\.isPending)) }.filter { !$0.value.isEmpty }
        pendingTextSends = snapshot.pendingTextSends
        pendingRecoveryJobs = snapshot.pendingRecoveryJobs
        pendingCompletions = snapshot.pendingCompletions
        pendingAudioEmbeds = []
    }

    private func persistSnapshot() async throws {
        guard !isStopped, !isPreviewFixture else { return }
        let generation = lifecycleGeneration
        let profile = ServerProfile.current()
        func validate() throws {
            guard !isStopped, generation == lifecycleGeneration, profile == ServerProfile.current() else { throw CancellationError() }
        }
        var encryptedChats: [WatchChatSummary] = []
        var encryptedMessages: [String: [WatchChatMessage]] = [:]
        let previous = await cache.loadSnapshot()
        try validate()
        if previous.accountID == accountID, previous.serverScope == serverScope || (accountID == nil && previous.serverScope == nil) {
            let retained = Set(chats.map(\.id))
            encryptedMessages = previous.messagesByChatId.filter { retained.contains($0.key) && (messagesByChatId[$0.key] == nil || partialWindowChats.contains($0.key)) }
        }
        for chat in chats {
            var storedChat = chat
            if let title = chat.title, storedChat.encryptedTitle == nil { storedChat.encryptedTitle = try await crypto.encryptText(title, for: chat) }
            if let preview = chat.preview, storedChat.encryptedPreview == nil { storedChat.encryptedPreview = try await crypto.encryptText(preview, for: chat) }
            if let category = chat.category, storedChat.encryptedCategory == nil { storedChat.encryptedCategory = try await crypto.encryptText(category, for: chat) }
            if let icon = chat.icon, storedChat.encryptedIcon == nil { storedChat.encryptedIcon = try await crypto.encryptText(icon, for: chat) }
            storedChat.category = nil; storedChat.icon = nil
            storedChat.title = nil
            storedChat.preview = nil
            encryptedChats.append(storedChat)
            for message in messagesByChatId[chat.id] ?? [] {
                var storedMessage = message
                if storedMessage.encryptedContent == nil, let content = storedMessage.content {
                    storedMessage.encryptedContent = try await crypto.encryptText(content, for: chat)
                }
                storedMessage.content = nil
                storedMessage.embedRefs = nil
                encryptedMessages[chat.id, default: []].removeAll { $0.id == storedMessage.id }
                encryptedMessages[chat.id, default: []].append(storedMessage)
            }
            if let stored = encryptedMessages[chat.id] { encryptedMessages[chat.id] = Self.sortedMessages(stored) }
            try validate()
        }
        // Migrate legacy prepared JSON on the next save; queued inference and
        // history remain encrypted on disk even when an offline retry is pending.
        for pending in pendingTextSends where pending.encryptedPreparedTurn == nil {
            guard let chat = chats.first(where: { $0.id == pending.chatId }), !pending.preflightJSON.isEmpty else { continue }
            let data = try JSONSerialization.data(withJSONObject: ["preflight": WatchCanonicalStorage.object(pending.preflightJSON),
                                                                   "inference": WatchCanonicalStorage.object(pending.inferenceJSON)])
            let encrypted = try await crypto.encryptText(String(decoding: data, as: UTF8.self), for: chat)
            try validate()
            guard let index = pendingTextSends.firstIndex(where: { $0.id == pending.id && $0.encryptedPreparedTurn == nil }) else { continue }
            pendingTextSends[index].encryptedPreparedTurn = encrypted
            pendingTextSends[index].preflightJSON = Data()
            pendingTextSends[index].inferenceJSON = Data()
        }
        try validate()
        try await cache.saveSnapshot(
            WatchChatSnapshot(
                chats: encryptedChats,
                messagesByChatId: encryptedMessages,
                pendingTextSends: pendingTextSends,
                pendingAudioEmbeds: [],
                savedAt: Date(), accountID: accountID, serverScope: serverScope, encryptedDrafts: encryptedDrafts,
                pendingRecoveryJobs: pendingRecoveryJobs, pendingCompletions: pendingCompletions
            ), accountGeneration: accountLifecycleGeneration, serverScope: serverScope
        )
    }

    private func fetchWithRetry<T>(_ operation: () async throws -> T) async throws -> T {
        var lastError: Error?
        for attempt in 1...Self.fetchRetryAttempts {
            do {
                return try await operation()
            } catch {
                lastError = error
                guard attempt < Self.fetchRetryAttempts,
                      Self.shouldRetryFetchError(error),
                      !Task.isCancelled else {
                    throw error
                }
                try await Task.sleep(nanoseconds: Self.fetchRetryDelayNanoseconds)
            }
        }
        throw lastError ?? URLError(.unknown)
    }

    private static func shouldRetryFetchError(_ error: Error) -> Bool {
        guard let urlError = error as? URLError else { return false }
        switch urlError.code {
        case .networkConnectionLost, .timedOut, .cannotConnectToHost, .notConnectedToInternet:
            return true
        default:
            return false
        }
    }

    private func decryptChats(_ remoteChats: [WatchRemoteChat]) async -> [WatchChatSummary] {
        var result: [WatchChatSummary] = []
        result.reserveCapacity(remoteChats.count)
        for chat in remoteChats {
            if let version = chat.draftV {
                var details: [String: Any] = ["id": chat.id, "draft_v": version, "messages_v": chat.messagesV]
                if let ciphertext = chat.encryptedDraftMD { details["encrypted_draft_md"] = ciphertext }
                else if chat.clearedDraftV != nil { details["encrypted_draft_md"] = NSNull() }
                if let preview = chat.encryptedDraftPreview { details["encrypted_draft_preview"] = preview }
                if let cleared = chat.clearedDraftV { details["cleared_draft_v"] = cleared }
                applyDraftDetails(details)
            }
            if var decrypted = await crypto.decryptChat(chat) {
                decrypted.lastEditedOverallTimestamp = chat.lastEditedOverallTimestamp
                decrypted.parentID = chat.parentID; decrypted.isSubChat = chat.isSubChat
                result.append(decrypted)
            }
        }
        return result
    }

    private func decryptMessages(_ remoteMessages: [WatchRemoteMessage]) async -> [WatchChatMessage] {
        var result: [WatchChatMessage] = []
        result.reserveCapacity(remoteMessages.count)
        for message in remoteMessages {
            result.append(await crypto.decryptMessage(message))
        }
        return result
    }

    private func replayPendingTextSends() async {
        guard !isStopped, let syncSocket, let syncSession, !pendingTextSends.isEmpty, !isSending else { return }
        let generation = lifecycleGeneration
        let profile = ServerProfile.current()
        isSending = true
        defer { isSending = false }
        syncSocket.connect(session: syncSession, syncState: makeSyncClientState())
        for pending in pendingTextSends {
            do {
                guard let chat = chats.first(where: { $0.id == pending.chatId }) else { throw WatchChatRuntimeError.noSelectedChat }
                let socketGeneration = syncSocket.generation
                let prepared = try await preparedTurn(pending, chat: chat)
                guard generation == lifecycleGeneration, !isStopped, profile == ServerProfile.current(),
                      socketGeneration == syncSocket.generation else { return }
                try await syncSocket.sendTurn(prepared, encryptMetadata: { text in
                    guard !self.isStopped, self.lifecycleGeneration == generation, ServerProfile.current() == profile else { throw CancellationError() }
                    return try await self.crypto.encryptText(text, for: chat)
                })
                guard generation == lifecycleGeneration, !isStopped, profile == ServerProfile.current(),
                      socketGeneration == syncSocket.generation else { return }
                pendingTextSends.removeAll { $0.id == pending.id }
                markPendingMessageSent(messageId: pending.messageId, chatId: pending.chatId)
            } catch {
                NativeDiagnostics.failure("pending_replay_failed", category: "watch_chat", level: .warning, error: error)
                errorMessage = error.localizedDescription
                break
            }
        }
        try? await persistSnapshot()
    }

    private func preparedTurn(_ pending: WatchPendingTextSend, chat: WatchChatSummary) async throws -> WatchPendingTextSend {
        guard let ciphertext = pending.encryptedPreparedTurn else { return pending }
        let plaintext = try await crypto.decryptText(ciphertext, for: chat)
        let value = try WatchCanonicalStorage.object(Data(plaintext.utf8))
        guard let preflight = value["preflight"] as? [String: Any], let inference = value["inference"] as? [String: Any] else { throw WatchChatRuntimeError.invalidPendingTurn }
        var transient = pending
        transient.preflightJSON = try JSONSerialization.data(withJSONObject: preflight)
        transient.inferenceJSON = try JSONSerialization.data(withJSONObject: inference)
        return transient
    }

    private func handleCompletionEvent(type: String, payload: [String: Any]) async {
        guard !isStopped else { return }
        let generation = lifecycleGeneration
        let profile = ServerProfile.current()
        func current() -> Bool { generation == lifecycleGeneration && !isStopped && profile == ServerProfile.current() }
        if type == "recovery_jobs_available", let jobs = payload["jobs"] as? [[String: Any]] {
            for job in jobs {
                guard let id = job["job_id"] as? String, let chat = job["chat_id"] as? String,
                      let message = job["assistant_message_id"] as? String, !chat.hasPrefix(Self.incognitoChatIdPrefix) else { continue }
                let version = job["chat_key_version"] as? Int ?? 1
                guard version > 0, version <= Int(UInt32.max) else { continue }
                if !pendingRecoveryJobs.contains(where: { $0.id == id }) {
                    pendingRecoveryJobs.append(.init(id: id, chatId: chat, messageId: message,
                        turnId: job["turn_id"] as? String, keyVersion: UInt32(version)))
                }
            }
        } else if ["ai_message_update", "ai_background_response_completed", "pending_ai_response"].contains(type) {
            if type == "ai_message_update", payload["is_final_chunk"] as? Bool != true { return }
            let body = payload["message"] as? [String: Any] ?? payload
            guard let chatID = (payload["chat_id"] ?? body["chat_id"]) as? String,
                  !chatID.hasPrefix(Self.incognitoChatIdPrefix),
                  let messageID = (payload["message_id"] ?? body["message_id"]) as? String,
                  let chat = chats.first(where: { $0.id == chatID }) else { return }
            if let jobID = payload["recovery_job_id"] as? String, !jobID.isEmpty {
                if !pendingRecoveryJobs.contains(where: { $0.id == jobID }) {
                    pendingRecoveryJobs.append(.init(id: jobID, chatId: chatID, messageId: messageID,
                        turnId: payload["turn_id"] as? String, keyVersion: 1))
                }
            } else if (payload["recovery_protocol_version"] as? Int ?? 0) < 1 {
                guard let content = (payload["full_content_so_far"] ?? payload["full_content"] ?? body["content"]) as? String else { return }
                let ciphertext = try? await crypto.encryptText(content, for: chat)
                guard current(), let ciphertext else { return }
                let now = Int(Date().timeIntervalSince1970)
                var message: [String: Any] = ["message_id": messageID, "chat_id": chatID, "role": "assistant",
                    "encrypted_content": ciphertext, "created_at": now, "status": "synced"]
                if let userID = payload["user_message_id"] as? String { message["user_message_id"] = userID }
                for (source, target) in [("category", "encrypted_category"), ("model_name", "encrypted_model_name")] {
                    if let text = payload[source] as? String, let encrypted = try? await crypto.encryptText(text, for: chat) { message[target] = encrypted }
                }
                guard current() else { return }
                let wire: [String: Any] = ["chat_id": chatID, "message": message,
                    "versions": ["messages_v": chat.messagesV + 1, "last_edited_overall_timestamp": now]]
                if let data = try? JSONSerialization.data(withJSONObject: wire), !pendingCompletions.contains(where: { $0.id == messageID }) {
                    pendingCompletions.append(.init(id: messageID, chatId: chatID, eventType: "ai_response_completed", encryptedPayload: data))
                    upsertCompletionMessage(.init(id: messageID, chatId: chatID, role: .assistant, content: content,
                        encryptedContent: ciphertext, createdAt: ISO8601DateFormatter().string(from: Date()), isPending: true))
                }
            }
        } else if ["ai_task_initiated", "ai_typing_started", "post_processing_completed"].contains(type) {
            guard let chatID = payload["chat_id"] as? String, let chat = chats.first(where: { $0.id == chatID }) else { return }
            let metadata = payload["chat_metadata"] as? [String: Any] ?? payload
            guard let wrappedKey = chat.encryptedChatKey else { return }
            var wire: [String: Any] = ["chat_id": chatID, "encrypted_chat_key": wrappedKey]
            let mappings = type == "post_processing_completed"
                ? [("updated_chat_title", "encrypted_title"), ("chat_summary", "encrypted_chat_summary")]
                : [("title", "encrypted_title"), ("category", "encrypted_chat_category")]
            for (source, target) in mappings {
                guard let text = metadata[source] as? String, !text.isEmpty else { continue }
                if target == "encrypted_title" {
                    if type == "post_processing_completed", let version = metadata["source_title_v"] as? Int,
                       chat.titleV > version { continue }
                    if type != "post_processing_completed", chat.title?.isEmpty == false { continue }
                }
                if target == "encrypted_chat_summary", let version = metadata["source_metadata_v"] as? Int,
                   chat.metadataV > version, chat.encryptedPreview != nil { continue }
                if let encrypted = try? await crypto.encryptText(text, for: chat) { wire[target] = encrypted }
            }
            if type != "post_processing_completed", wire["encrypted_title"] != nil {
                let category = metadata["category"] as? String ?? "ai"
                let icon = (metadata["icon_names"] as? [String])?.first ?? WatchCanonicalStorage.iconFallback(category)
                if let encryptedIcon = try? await crypto.encryptText(icon, for: chat),
                   let encryptedCategory = try? await crypto.encryptText(category, for: chat) {
                    wire["encrypted_icon"] = encryptedIcon
                    wire["encrypted_chat_category"] = encryptedCategory
                } else { return }
            }
            if type == "post_processing_completed" {
                for (source, target) in [("follow_up_request_suggestions", "encrypted_follow_up_suggestions"), ("chat_tags", "encrypted_chat_tags")] {
                    if let values = metadata[source] as? [String], let json = try? JSONSerialization.data(withJSONObject: values),
                       let text = String(data: json, encoding: .utf8), let encrypted = try? await crypto.encryptText(text, for: chat) { wire[target] = encrypted }
                }
                wire["versions"] = ["messages_v": chat.messagesV,
                    "title_v": wire["encrypted_title"] == nil ? chat.titleV : max(chat.titleV, metadata["source_title_v"] as? Int ?? 0) + 1,
                    "metadata_v": max(chat.metadataV, chat.titleV)]
            }
            guard current(), wire.keys.contains(where: { $0 != "chat_id" && $0 != "encrypted_chat_key" }),
                  let data = try? JSONSerialization.data(withJSONObject: wire) else { return }
            let id = "metadata-\(chatID)-\(type)-\(payload["task_id"] as? String ?? "")"
            pendingCompletions.removeAll { $0.id == id }
            pendingCompletions.append(.init(id: id, chatId: chatID,
                eventType: type == "post_processing_completed" ? "update_post_processing_metadata" : "encrypted_chat_metadata", encryptedPayload: data))
        } else if ["encrypted_metadata_stored", "post_processing_metadata_stored"].contains(type) {
            applyAcceptedVersions(payload)
        } else if type == "phased_sync_complete" {
            completionRetryAttempt = 0
            await replayPendingDrafts()
        } else { return }
        guard current() else { return }
        try? await persistSnapshot()
        await flushPendingCompletions()
    }

    private func flushPendingCompletions() async {
        guard !isStopped, !completionWorkInProgress, let syncSocket else { return }
        completionWorkInProgress = true
        defer { completionWorkInProgress = false }
        let generation = lifecycleGeneration
        let socketGeneration = syncSocket.generation
        let profile = ServerProfile.current()
        func validate() throws {
            guard !isStopped, !Task.isCancelled, generation == lifecycleGeneration,
                  socketGeneration == syncSocket.generation, profile == ServerProfile.current() else { throw WatchChatRuntimeError.socketUnavailable }
        }
        var failed = false
        for entry in pendingCompletions {
            do {
                try validate()
                let payload = try WatchCanonicalStorage.object(entry.encryptedPayload)
                let acknowledgementType: String
                switch entry.eventType {
                case "store_embed_keys": acknowledgementType = "store_embed_keys_confirmed"
                case "store_embed": acknowledgementType = "store_embed_confirmed"
                case "ai_response_completed": acknowledgementType = "ai_response_storage_confirmed"
                case "update_post_processing_metadata": acknowledgementType = "post_processing_metadata_stored"
                default: acknowledgementType = "encrypted_metadata_stored"
                }
                let embedStorage = entry.eventType == "store_embed" || entry.eventType == "store_embed_keys"
                let types: Set<String> = [acknowledgementType, "incomplete_chat_metadata", "chat_key_mismatch"]
                let acknowledgement = try await syncSocket.requestEvent(type: entry.eventType, payload: payload, responseTypes: types, matching: {
                    if embedStorage { return $0["request_id"] as? String == entry.id }
                    guard $0["chat_id"] as? String == entry.chatId else { return false }
                    return entry.eventType == "ai_response_completed" ? $0["message_id"] as? String == entry.id : ($0["message_id"] as? String) == nil
                })
                try validate()
                guard acknowledgement["code"] == nil else { throw WatchChatRuntimeError.preflightRejected }
                if embedStorage {
                    try WatchCanonicalStorage.validateEmbedStorageAcknowledgement(type: entry.eventType, payload: payload,
                        acknowledgement: acknowledgement, requestID: entry.id)
                    pendingCompletions.removeAll { $0.id == entry.id }
                    try await persistSnapshot()
                    continue
                }
                applyAcceptedVersions(acknowledgement)
                if let index = chats.firstIndex(where: { $0.id == entry.chatId }),
                   let versions = acknowledgement["versions"] as? [String: Any] {
                    if let ciphertext = payload["encrypted_title"] as? String,
                       let version = versions["title_v"] as? Int, version >= chats[index].titleV {
                        let title = try await crypto.decryptText(ciphertext, for: chats[index])
                        try validate()
                        if let currentIndex = chats.firstIndex(where: { $0.id == entry.chatId }), chats[currentIndex].titleV <= version {
                            chats[currentIndex].encryptedTitle = ciphertext
                            chats[currentIndex].title = title
                        }
                    }
                    if let ciphertext = payload["encrypted_chat_summary"] as? String,
                       let version = versions["metadata_v"] as? Int,
                       let summaryChat = chats.first(where: { $0.id == entry.chatId }), version >= summaryChat.metadataV {
                        let summary = try await crypto.decryptText(ciphertext, for: summaryChat)
                        try validate()
                        if let currentIndex = chats.firstIndex(where: { $0.id == entry.chatId }), chats[currentIndex].metadataV <= version {
                            chats[currentIndex].encryptedPreview = ciphertext
                            chats[currentIndex].preview = summary
                        }
                    }
                }
                if let chat = chats.first(where: { $0.id == entry.chatId }) {
                    let encryptedCategory = payload["encrypted_chat_category"] as? String ?? payload["encrypted_category"] as? String
                    if let encryptedCategory {
                        let category = try await crypto.decryptText(encryptedCategory, for: chat)
                        try validate()
                        if let index = chats.firstIndex(where: { $0.id == entry.chatId }) {
                            chats[index].category = category; chats[index].encryptedCategory = encryptedCategory
                        }
                    }
                    if let encryptedIcon = payload["encrypted_icon"] as? String {
                        let icon = try await crypto.decryptText(encryptedIcon, for: chat)
                        try validate()
                        if let index = chats.firstIndex(where: { $0.id == entry.chatId }) {
                            chats[index].icon = icon; chats[index].encryptedIcon = encryptedIcon
                        }
                    }
                }
                if entry.eventType == "ai_response_completed" { markPendingMessageSent(messageId: entry.id, chatId: entry.chatId) }
                pendingCompletions.removeAll { $0.id == entry.id }
                try await persistSnapshot()
            } catch { failed = true; break }
        }
        if let owner = accountID {
            for job in pendingRecoveryJobs {
                do {
                    try validate()
                    guard var chat = chats.first(where: { $0.id == job.chatId }) else { throw WatchChatRuntimeError.noSelectedChat }
                    if let authoritative = try await api.fetchMessagesVersion(chatId: chat.id, context: requestContext()) { chat.messagesV = authoritative }
                    try validate()
                    let result = try await WatchCanonicalStorage.recover(job, chat: chat, ownerID: owner,
                        request: { type, payload, responses, matching in
                            try validate()
                            return try await syncSocket.requestEvent(type: type, payload: payload, responseTypes: responses, matching: matching)
                        }, open: { sealed, boundJob, owner in
                            try await self.crypto.openCompletion(sealed, job: boundJob, ownerID: owner, chat: chat)
                        }, encrypt: { try await self.crypto.encryptText($0, for: chat) }, validate: validate)
                    try validate()
                    if result.requiresHydration {
                        let remote = try await api.fetchMessages(chatId: chat.id, context: requestContext())
                        let hydrated = await decryptMessages(remote)
                        let version = try await api.fetchMessagesVersion(chatId: chat.id, context: requestContext())
                        try validate()
                        guard (version ?? -1) >= result.version,
                              hydrated.contains(where: { $0.id == job.messageId && $0.encryptedContent?.isEmpty == false }) else { throw WatchChatRuntimeError.historyUnavailable }
                        for message in hydrated { upsertCompletionMessage(message) }
                    } else if let message = result.message { upsertCompletionMessage(message) }
                    if let index = chats.firstIndex(where: { $0.id == chat.id }) { chats[index].messagesV = max(chats[index].messagesV, result.version) }
                    pendingRecoveryJobs.removeAll { $0.id == job.id }
                    try await persistSnapshot()
                } catch { failed = true }
            }
        }
        let retryDelays: [Duration] = [.seconds(1), .seconds(3), .seconds(10), .seconds(20), .seconds(30), .seconds(65)]
        if failed, !isStopped, generation == lifecycleGeneration, completionRetryAttempt < retryDelays.count {
            let delay = retryDelays[completionRetryAttempt]
            completionRetryAttempt += 1
            completionTask?.cancel()
            completionTask = Task { @MainActor [weak self] in
                do { try await Task.sleep(for: delay) } catch { return }
                guard let self, !self.isStopped, self.lifecycleGeneration == generation else { return }
                await self.flushPendingCompletions()
            }
        }
    }

    private func upsertCompletionMessage(_ message: WatchChatMessage) {
        var messages = messagesByChatId[message.chatId] ?? []
        if let index = messages.firstIndex(where: { $0.id == message.id }) { messages[index] = message }
        else { messages.append(message) }
        messagesByChatId[message.chatId] = Self.sortedMessages(messages)
    }

    private func applyAcceptedVersions(_ payload: [String: Any]) {
        guard let chatID = payload["chat_id"] as? String, let versions = payload["versions"] as? [String: Any],
              let index = chats.firstIndex(where: { $0.id == chatID }) else { return }
        if let version = versions["messages_v"] as? Int { chats[index].messagesV = max(chats[index].messagesV, version) }
        if let version = versions["title_v"] as? Int { chats[index].titleV = max(chats[index].titleV, version) }
        if let version = versions["metadata_v"] as? Int { chats[index].metadataV = max(chats[index].metadataV, version) }
    }

    private func makeSyncClientState() -> WatchSyncClientState {
        let syncableChats = chats.filter { !$0.id.hasPrefix(Self.incognitoChatIdPrefix) }
        return WatchSyncClientState(
            clientChatVersions: Dictionary(uniqueKeysWithValues: syncableChats.map { chat in
                (chat.id, ["messages_v": chat.messagesV, "title_v": chat.titleV,
                    "metadata_v": chat.metadataV, "draft_v": encryptedDrafts[chat.id]?.serverVersion ?? 0])
            }),
            clientChatIds: syncableChats.map(\.id),
            clientSuggestionsCount: 0,
            clientEmbedIds: []
        )
    }

    private func markPendingMessageSent(messageId: String, chatId: String) {
        guard var messages = messagesByChatId[chatId],
              let index = messages.firstIndex(where: { $0.id == messageId }) else { return }
        messages[index].isPending = false
        messagesByChatId[chatId] = messages
    }

    private static func sortedChats(_ chats: [WatchChatSummary]) -> [WatchChatSummary] {
        chats.sorted { lhs, rhs in
            if lhs.isPinned != rhs.isPinned { return lhs.isPinned && !rhs.isPinned }
            return (lhs.lastMessageAt ?? "") > (rhs.lastMessageAt ?? "")
        }
    }

    private static func sortedMessages(_ messages: [WatchChatMessage]) -> [WatchChatMessage] {
        let formatter = ISO8601DateFormatter()
        let dated: [(message: WatchChatMessage, timestamp: TimeInterval)] = messages.map { message in
            let civilTimestamp = formatter.date(from: message.createdAt)?.timeIntervalSince1970 ?? 0
            let timestamp: TimeInterval = Double(message.createdAt) ?? civilTimestamp
            return (message: message, timestamp: timestamp)
        }
        let ordered = dated.sorted { lhs, rhs in
            if lhs.timestamp == rhs.timestamp { return lhs.message.id < rhs.message.id }
            return lhs.timestamp < rhs.timestamp
        }
        return ordered.map { $0.message }
    }
}

extension APIClient: WatchChatAPI {
    private func verifiedWatchData(_ method: HTTPMethod, path: String, context: WatchChatRequestContext,
                                   body: (any Encodable & Sendable)? = nil) async throws -> Data {
        guard context.accountID != nil else { throw CancellationError() }
        return try await requestForVerifiedWatchSession(method, path: path, serverProfile: context.profile,
            body: body, validate: { try context.check() })
    }

    private func decodeWatchResponse<T: Decodable>(_ type: T.Type, data: Data) throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(type, from: data)
    }

    func fetchRecentChats(limit: Int, offset: Int, context: WatchChatRequestContext) async throws -> [WatchRemoteChat] {
        let data = try await verifiedWatchData(.get, path: "/v1/chats?limit=\(limit)&offset=\(offset)", context: context)
        return try decodeWatchResponse(WatchChatListEnvelope.self, data: data).chats.map(WatchRemoteChat.init(dto:))
    }

    func fetchMessages(chatId: String, context: WatchChatRequestContext) async throws -> [WatchRemoteMessage] {
        let data = try await verifiedWatchData(.get, path: "/v1/chats/\(chatId)/messages", context: context)
        return try decodeWatchResponse([WatchChatMessageDTO].self, data: data).map(WatchRemoteMessage.init(dto:))
    }

    func fetchMessageWindow(chatId: String, query: WatchMessageWindowQuery, context: WatchChatRequestContext) async throws -> WatchMessageWindow {
        let data = try await verifiedWatchData(.get, path: query.path(chatID: chatId), context: context)
        return try decodeWatchResponse(WatchMessageWindowEnvelope.self, data: data).window
    }

    func fetchMessagesVersion(chatId: String, context: WatchChatRequestContext) async throws -> Int? {
        let data = try await verifiedWatchData(.get, path: "/v1/chats/\(chatId)/messages/window?limit=1", context: context)
        let response = try decodeWatchResponse(WatchChatVersionEnvelope.self, data: data)
        return response.messagesV ?? response.serverMessageCount
    }

    func uploadAudioRecording(data: Data, filename: String, chatId: String, context: WatchChatRequestContext) async throws -> WatchUploadedAudio {
        guard context.accountID != nil else { throw CancellationError() }
        let response = try await uploadFileForVerifiedWatchSession(data: data, filename: filename,
            contentType: "audio/mp4", chatId: chatId, serverProfile: context.profile, validate: { try context.check() })
        return try decodeWatchResponse(WatchUploadedAudio.self, data: response)
    }

    func transcribeAudioRecording(_ upload: WatchUploadedAudio, chatId: String, context: WatchChatRequestContext) async throws -> WatchTranscriptionMetadata? {
        let s3Key = upload.files["original"]?.s3Key ?? upload.files.values.first?.s3Key
        guard let s3Key else { throw WatchChatRuntimeError.audioUploadFailed }
        let embedId = UUID().uuidString
        let body: [String: Any] = ["requests": [[
            "id": embedId, "embed_id": upload.embedId, "s3_key": s3Key,
            "s3_base_url": upload.s3BaseUrl, "aes_key": upload.aesKey, "aes_nonce": upload.aesNonce,
            "vault_wrapped_aes_key": upload.vaultWrappedAesKey, "filename": upload.filename,
            "mime_type": upload.contentType, "chat_id": chatId,
        ]]]
        let raw = JSONRawBody(data: try JSONSerialization.data(withJSONObject: body))
        let data = try await verifiedWatchData(.post, path: "/v1/apps/audio/skills/transcribe", context: context, body: raw)
        return try decodeWatchResponse(WatchTranscribeSkillResponse.self, data: data).data.results.first?.results.first
    }
}

#if !os(watchOS)
extension WebSocketManager: WatchChatSyncSocket {
    func sendTurn(_ pending: WatchPendingTextSend) async throws {
        throw WatchChatRuntimeError.socketUnavailable
    }

    func setChangeHandler(_ handler: (@MainActor () -> Void)?) {}

    func connect(session: WatchSyncSession, syncState: WatchSyncClientState) {
        connect(
            sessionId: session.sessionId,
            token: session.token,
            syncState: SyncClientState(
                clientChatVersions: syncState.clientChatVersions,
                clientChatIds: syncState.clientChatIds,
                clientSuggestionsCount: syncState.clientSuggestionsCount,
                clientEmbedIds: syncState.clientEmbedIds
            )
        )
    }
}
#endif

@MainActor
enum WatchSocketReadiness {
    enum ProbeResult {
        case open, retry, closed
    }

    static func wait(
        maxAttempts: Int = 60,
        interval: Duration = .milliseconds(250),
        probe: () async -> ProbeResult
    ) async -> Bool {
        for _ in 0..<maxAttempts {
            switch await probe() {
            case .open: return true
            case .closed: return false
            case .retry: try? await Task.sleep(for: interval)
            }
        }
        return false
    }
}

@MainActor
private final class WatchRealtimeSyncSocket: WatchChatSyncSocket {
    private var webSocketTask: URLSessionWebSocketTask?
    private var isConnecting = false
    private var isReady = false
    private var changeHandler: (@MainActor () -> Void)?
    private var inbox: [(type: String, payload: [String: Any])] = []
    private var receiveTask: Task<Void, Never>?
    private var connectionTask: Task<Void, Never>?
    private var connectionGeneration = 0
    var generation: Int { connectionGeneration }
    private var eventHandler: (@MainActor (String, [String: Any]) -> Void)?
    private var readyHandler: (@MainActor () -> Void)?
    var isConnected: Bool { webSocketTask != nil && isReady }
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.default
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        config.httpCookieStorage = OpenMatesSharedEnvironment.cookieStorage
        return URLSession(configuration: config)
    }()

    func setChangeHandler(_ handler: (@MainActor () -> Void)?) { changeHandler = handler }
    func setEventHandler(_ handler: (@MainActor (String, [String: Any]) -> Void)?) { eventHandler = handler }
    func setReadyHandler(_ handler: (@MainActor () -> Void)?) {
        readyHandler = handler
        if isConnected { readyHandler?() }
    }

    func connect(session syncSession: WatchSyncSession, syncState: WatchSyncClientState) {
        guard webSocketTask == nil, !isConnecting else { return }
        isConnecting = true
        isReady = false
        connectionGeneration += 1
        let expectedGeneration = connectionGeneration
        let profile = ServerProfile.current()
        connectionTask = Task {
            defer { if self.connectionGeneration == expectedGeneration { self.isConnecting = false } }
            let baseURL = profile.apiBaseURL
            let origin = profile.webBaseURL.absoluteString
            guard !Task.isCancelled, self.connectionGeneration == expectedGeneration,
                  ServerProfile.current() == profile else { return }
            let hasRefreshCookie = OpenMatesSharedEnvironment.cookieStorage.cookies(for: baseURL)?.contains {
                $0.name == "auth_refresh_token"
            } == true
            NativeDiagnostics.event(
                "connect_attempt", category: "watch_chat_socket",
                flags: [
                    "ws_token_present": syncSession.token?.isEmpty == false,
                    "refresh_cookie_present": hasRefreshCookie,
                ]
            )
            guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { return }
            components.scheme = components.scheme == "https" ? "wss" : "ws"
            components.path = "/v1/ws"
            var queryItems = [URLQueryItem(name: "sessionId", value: syncSession.sessionId)]
            if let token = syncSession.token, !token.isEmpty {
                queryItems.append(URLQueryItem(name: "token", value: token))
            }
            components.queryItems = queryItems
            guard let url = components.url else { return }
            var request = URLRequest(url: url)
            request.timeoutInterval = 30
            request.setValue(origin, forHTTPHeaderField: "Origin")
            APIClient.nativeClientHeaders.forEach { request.setValue($1, forHTTPHeaderField: $0) }
            let task = self.session.webSocketTask(with: request)
            self.webSocketTask = task
            task.resume()
            self.receiveTask = Task { await self.receiveLoop(task) }
            guard await self.waitForOpenSocket(task) else {
                guard self.webSocketTask === task, self.connectionGeneration == expectedGeneration else { return }
                NativeDiagnostics.event(
                    "open_failed", category: "watch_chat_socket", level: .warning,
                    counts: ["close_code": task.closeCode.rawValue]
                )
                self.disconnect()
                return
            }
            NativeDiagnostics.event("connected", category: "watch_chat_socket")
            guard self.webSocketTask === task, self.connectionGeneration == expectedGeneration,
                  !Task.isCancelled, ServerProfile.current() == profile else { return }
            let sync = WatchWSOutboundMessage(type: "phased_sync_request", payload: syncState.phasedSyncPayload)
            do {
                try await self.send(sync, on: task)
                guard self.webSocketTask === task, self.connectionGeneration == expectedGeneration else { return }
                self.isReady = true
                self.readyHandler?()
            } catch {
                guard self.webSocketTask === task, self.connectionGeneration == expectedGeneration else { return }
                NativeDiagnostics.failure(
                    "initial_sync_failed", category: "watch_chat_socket", level: .warning, error: error
                )
                self.disconnect()
            }
        }
    }

    private func waitForOpenSocket(_ task: URLSessionWebSocketTask) async -> Bool {
        await WatchSocketReadiness.wait {
            guard self.webSocketTask === task else { return .closed }
            let pingSucceeded = await withCheckedContinuation { continuation in
                task.sendPing { error in continuation.resume(returning: error == nil) }
            }
            guard self.webSocketTask === task else { return .closed }
            return pingSucceeded ? .open : .retry
        }
    }

    func disconnect() {
        connectionGeneration += 1
        connectionTask?.cancel()
        connectionTask = nil
        isConnecting = false
        receiveTask?.cancel()
        receiveTask = nil
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        isReady = false
        inbox.removeAll()
    }

    func sendTurn(_ pending: WatchPendingTextSend) async throws {
        try await sendTurn(pending, encryptMetadata: { _ in throw WatchChatRuntimeError.missingChatKey })
    }

    func sendTurn(_ pending: WatchPendingTextSend, encryptMetadata: @escaping @MainActor (String) async throws -> String) async throws {
        let expected = connectionGeneration
        let profile = ServerProfile.current()
        try await WatchCanonicalStorage.sendTurn(pending, request: { type, payload, responses, matching in
            try await self.requestEvent(type: type, payload: payload, responseTypes: responses, matching: matching)
        }, encryptMetadata: encryptMetadata, validate: {
            guard !Task.isCancelled, self.connectionGeneration == expected,
                  ServerProfile.current() == profile else { throw WatchChatRuntimeError.socketUnavailable }
        })
    }

    func sendEvent(type: String, payload: [String: Any]) async throws {
        let expected = connectionGeneration
        let task = try await connectedTask()
        guard expected == connectionGeneration, !Task.isCancelled else { throw WatchChatRuntimeError.socketUnavailable }
        if !type.isEmpty { try await send(WatchWSOutboundMessage(type: type, payload: payload), on: task) }
    }

    func requestEvent(type: String, payload: [String: Any], responseTypes: Set<String>,
                      matching: @escaping @MainActor ([String: Any]) -> Bool) async throws -> [String: Any] {
        try await requestEvent(type: type, payload: payload, responseTypes: responseTypes,
                               matching: matching, beforeSend: {})
    }

    func requestEvent(type: String, payload: [String: Any], responseTypes: Set<String>,
                      matching: @escaping @MainActor ([String: Any]) -> Bool,
                      beforeSend: @escaping @MainActor () throws -> Void) async throws -> [String: Any] {
        let expected = connectionGeneration
        let task = try await connectedTask()
        try beforeSend()
        guard expected == connectionGeneration, !Task.isCancelled else { throw WatchChatRuntimeError.socketUnavailable }
        if !type.isEmpty { try await send(WatchWSOutboundMessage(type: type, payload: payload), on: task) }
        for _ in 0..<200 {
            guard expected == connectionGeneration, webSocketTask === task, !Task.isCancelled else { throw WatchChatRuntimeError.socketUnavailable }
            if let response = try WatchSocketResponses.takeMatchingResponse(from: &inbox,
                requestType: type, responseTypes: responseTypes, matching: matching) { return response }
            try await Task.sleep(for: .milliseconds(100))
        }
        throw WatchChatRuntimeError.socketUnavailable
    }

    private func connectedTask() async throws -> URLSessionWebSocketTask {
        for _ in 0..<300 {
            if let webSocketTask, isReady { return webSocketTask }
            if webSocketTask == nil && !isConnecting { break }
            try await Task.sleep(for: .milliseconds(100))
        }
        NativeDiagnostics.event("ready_timeout", category: "watch_chat_socket", level: .warning)
        throw WatchChatRuntimeError.socketUnavailable
    }

    private func send(_ message: WatchWSOutboundMessage, on task: URLSessionWebSocketTask) async throws {
        guard webSocketTask === task, !Task.isCancelled else { throw WatchChatRuntimeError.socketUnavailable }
        let data = try JSONEncoder().encode(message)
        guard let json = String(data: data, encoding: .utf8) else { throw WatchChatRuntimeError.socketUnavailable }
        try await task.send(.string(json))
    }

    private func receiveLoop(_ task: URLSessionWebSocketTask) async {
        while !Task.isCancelled {
            do {
                let value = try await task.receive()
                guard webSocketTask === task, !Task.isCancelled else { return }
                let data: Data
                switch value {
                case .string(let text): data = Data(text.utf8)
                case .data(let bytes): data = bytes
                @unknown default: continue
                }
                guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let type = (object["type"] ?? object["event"]) as? String else { continue }
                // Draft broadcasts put chat identity and versions beside data.
                let payload = object["payload"] as? [String: Any] ?? object
                inbox.append((type, payload))
                if inbox.count > 100 { inbox.removeFirst(inbox.count - 100) }
                eventHandler?(type, payload)
                if ["new_chat_message", "chat_message_added", "chat_message_confirmed", "ai_response_storage_confirmed", "phased_sync_complete"].contains(type) {
                    changeHandler?()
                }
            } catch {
                NativeDiagnostics.failure(
                    "receive_failed", category: "watch_chat_socket", level: .warning, error: error
                )
                if webSocketTask === task {
                    webSocketTask = nil
                    isReady = false
                }
                return
            }
        }
    }

    private func waitForEvent(type: String, turnId: String, messageId: String? = nil) async throws -> [String: Any] {
        for _ in 0..<200 {
            if let index = inbox.firstIndex(where: { event in
                guard event.type == type || event.type == "error" else { return false }
                if event.payload["turn_id"] as? String == turnId { return true }
                if let messageId,
                   (event.payload["user_message_id"] ?? event.payload["message_id"]) as? String == messageId { return true }
                return false
            }) {
                let event = inbox.remove(at: index)
                if event.type == "error" {
                    throw WatchTurnAdmissionDiagnostic.serverRejection(
                        stage: type == "chat_turn_preflight_ack" ? .preflight : .commit,
                        code: event.payload["code"])
                }
                return event.payload
            }
            try await Task.sleep(for: .milliseconds(100))
        }
        NativeDiagnostics.event(
            type == "chat_turn_preflight_ack" ? "preflight_ack_timeout" : "inference_ack_timeout",
            category: "watch_chat_socket", level: .warning
        )
        throw WatchChatRuntimeError.socketUnavailable
    }
}

private struct WatchWSOutboundMessage: Encodable {
    let type: String
    let payload: [String: AnyCodable]

    init(type: String, payload: [String: Any]) {
        self.type = type
        self.payload = payload.mapValues { AnyCodable($0) }
    }
}

@MainActor
private final class WatchChatCryptoService: WatchChatCrypto {
    private let currentUserId: String?
    private var chatKeys: [String: SymmetricKey] = [:]
    private var offlineWrappers: [String: String] = [:]
    func offlineWrappedChatKey(for chat: WatchChatSummary) -> String? { offlineWrappers[chat.id] ?? chat.offlineWrappedChatKey ?? chat.encryptedChatKey }

    init(currentUserId: String?) {
        self.currentUserId = currentUserId
    }

    func decryptChat(_ chat: WatchRemoteChat) async -> WatchChatSummary? {
        guard let resolved = await loadChatKey(chatId: chat.id, wrappers: chat.chatKeyWrappers,
                                               encryptedChatKey: chat.encryptedChatKey) else {
            guard chat.messagesV == 0, let ciphertext = chat.encryptedDraftMD,
                  let text = try? await decryptDraft(ciphertext), !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return WatchChatSummary(id: chat.id, title: nil, lastMessageAt: chat.lastMessageAt ?? chat.updatedAt,
                preview: nil, isPinned: chat.isPinned, encryptedTitle: nil, encryptedPreview: nil, encryptedChatKey: nil)
        }
        let key = resolved.key
        let title = await decrypt(chat.encryptedTitle, key: key) ?? chat.title
        let preview = await decrypt(chat.encryptedChatSummary, key: key) ?? chat.chatSummary
        var summary = WatchChatSummary(
            id: chat.id, title: title,
            lastMessageAt: chat.lastMessageAt ?? chat.updatedAt,
            preview: preview, isPinned: chat.isPinned,
            encryptedTitle: chat.encryptedTitle,
            encryptedPreview: chat.encryptedChatSummary,
            encryptedChatKey: resolved.outboundWrapped,
            messagesV: chat.messagesV, titleV: chat.titleV, metadataV: chat.metadataV
        )
        summary.lastEditedOverallTimestamp = chat.lastEditedOverallTimestamp
        summary.parentID = chat.parentID
        summary.isSubChat = chat.isSubChat
        summary.category = await decrypt(chat.encryptedCategory, key: key)
        summary.icon = await decrypt(chat.encryptedIcon, key: key)
        summary.encryptedCategory = chat.encryptedCategory; summary.encryptedIcon = chat.encryptedIcon
        summary.isSupportChat = chat.isSupportChat; summary.isSharedRecipient = chat.isSharedRecipient
        summary.offlineWrappedChatKey = resolved.wrapped
        return summary
    }

    func decryptMessage(_ message: WatchRemoteMessage) async -> WatchChatMessage {
        let key = chatKeys[message.chatId]
        let content = await decrypt(message.encryptedContent, key: key) ?? message.content
        let embedRefs = WatchMessageContentSanitizer.mergedEmbedRefs(content: content, provided: message.embedRefs)
        return WatchChatMessage(
            id: message.id,
            chatId: message.chatId,
            role: message.role,
            content: content,
            encryptedContent: message.encryptedContent,
            embedRefs: embedRefs.isEmpty ? nil : embedRefs,
            createdAt: message.createdAt,
            isPending: false
        )
    }

    func encryptText(_ text: String, for chat: WatchChatSummary) async throws -> String {
        guard let key = await chatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey) else {
            throw WatchChatRuntimeError.missingChatKey
        }
        return try await CryptoManager.shared.encryptContent(text, key: key)
    }

    func hydrateEmbed(payload: [String: Any], chat: WatchChatSummary) async throws -> WatchEmbedRef {
        guard let currentUserId,
              let masterKey = try await CryptoManager.shared.loadMasterKey(for: currentUserId),
              let embedID = payload["embed_id"] as? String else { throw WatchChatRuntimeError.missingChatKey }
        let key = await chatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey)
        return try WatchEmbedHydration.open(payload: payload, embedID: embedID, chatID: chat.id,
            accountID: currentUserId, masterKey: masterKey, chatKey: key)
    }

    func prepareEmbedStorage(payload: [String: Any], chat: WatchChatSummary, messageID: String) async throws -> (keys: [String: Any], embed: [String: Any]) {
        guard let currentUserId,
              let masterKey = try await CryptoManager.shared.loadMasterKey(for: currentUserId),
              let key = await chatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey),
              let embedID = payload["embed_id"] as? String else { throw WatchChatRuntimeError.missingChatKey }
        return try WatchEmbedHydration.prepareStorage(payload: payload, embedID: embedID, chatID: chat.id,
            messageID: messageID, accountID: currentUserId, masterKey: masterKey, chatKey: key)
    }

    func encryptDraft(_ text: String) async throws -> String {
        guard let currentUserId, let masterKey = try await CryptoManager.shared.loadMasterKey(for: currentUserId) else {
            throw WatchChatRuntimeError.missingChatKey
        }
        return try await CryptoManager.shared.encryptWithMasterKey(text, masterKey: masterKey)
    }

    func decryptDraft(_ ciphertext: String) async throws -> String {
        guard let currentUserId, let masterKey = try await CryptoManager.shared.loadMasterKey(for: currentUserId) else {
            throw WatchChatRuntimeError.missingChatKey
        }
        return try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: masterKey)
    }

    func createChat() async throws -> WatchChatSummary {
        try await createChat(withID: UUID().uuidString.lowercased())
    }

    func createChat(withID id: String) async throws -> WatchChatSummary {
        guard let currentUserId,
              let masterKey = try await CryptoManager.shared.loadMasterKey(for: currentUserId) else {
            throw WatchChatRuntimeError.missingChatKey
        }
        let key = await CryptoManager.shared.generateChatKey()
        let wrapped = try await CryptoManager.shared.wrapChatKey(key, masterKey: masterKey)
        let encryptedTitle = try await CryptoManager.shared.encryptContent("", key: key)
        chatKeys[id] = key
        return WatchChatSummary(id: id, title: nil, lastMessageAt: nil, preview: nil,
                                isPinned: false, encryptedTitle: encryptedTitle,
                                encryptedPreview: nil, encryptedChatKey: wrapped)
    }

    func recoveryPublicKey(for chat: WatchChatSummary) async throws -> String {
        guard let key = await chatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey) else {
            throw WatchChatRuntimeError.missingChatKey
        }
        return try await CryptoManager.shared.deriveRecoveryKeyPair(
            chatKey: key, chatId: chat.id, keyVersion: 1
        ).publicKey
    }

    func decryptText(_ ciphertext: String, for chat: WatchChatSummary) async throws -> String {
        guard let key = await chatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey) else { throw WatchChatRuntimeError.missingChatKey }
        return try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
    }

    func openCompletion(_ sealed: String, job: WatchRecoveryJob, ownerID: String, chat: WatchChatSummary) async throws -> WatchRecoveredCompletion {
        guard currentUserId == ownerID,
              let key = await chatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey) else { throw WatchChatRuntimeError.missingChatKey }
        return try await WatchCanonicalStorage.openRecovery(sealed, job: job, ownerID: ownerID, key: key)
    }

    func encryptedAudioEmbed(_ embed: WatchPendingAudioEmbed, chat: WatchChatSummary, messageId: String) async throws -> [[String: Any]] {
        guard let currentUserId,
              let masterKey = try await CryptoManager.shared.loadMasterKey(for: currentUserId),
              let chatKey = await chatKey(chatId: chat.id, encryptedChatKey: chat.encryptedChatKey) else {
            throw WatchChatRuntimeError.missingChatKey
        }
        let embedKey = ComposerEmbedCrypto.deriveKey(chatKey: chatKey, embedId: embed.id)
        let hashedChatId = Self.hash(chat.id)
        let hashedUserId = Self.hash(currentUserId)
        let hashedEmbedId = Self.hash(embed.id)
        let now = Int(Date().timeIntervalSince1970)
        return [[
            "embed_id": embed.id,
            "encrypted_type": try ComposerEmbedCrypto.encryptContent("audio-recording", using: embedKey),
            "encrypted_content": try ComposerEmbedCrypto.encryptContent(embed.content, using: embedKey),
            "encrypted_text_preview": try ComposerEmbedCrypto.encryptContent(embed.transcript ?? embed.filename, using: embedKey),
            "status": "finished", "hashed_chat_id": hashedChatId,
            "hashed_message_id": Self.hash(messageId), "hashed_user_id": hashedUserId,
            "created_at": now, "updated_at": now,
            "embed_keys": [
                ["hashed_embed_id": hashedEmbedId, "key_type": "master", "hashed_chat_id": NSNull(),
                 "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(embedKey, using: masterKey),
                 "hashed_user_id": hashedUserId, "created_at": now] as [String: Any],
                ["hashed_embed_id": hashedEmbedId, "key_type": "chat", "hashed_chat_id": hashedChatId,
                 "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(embedKey, using: chatKey),
                 "hashed_user_id": hashedUserId, "created_at": now] as [String: Any]
            ]
        ]]
    }

    private static func hash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func chatKey(chatId: String, encryptedChatKey: String?) async -> SymmetricKey? {
        if let key = chatKeys[chatId] { return key }
        guard let currentUserId,
              let encryptedChatKey,
              let masterKey = try? await CryptoManager.shared.loadMasterKey(for: currentUserId),
              let chatKey = try? await CryptoManager.shared.unwrapChatKey(
                encryptedChatKeyBase64: encryptedChatKey,
                masterKey: masterKey
              ) else { return nil }
        chatKeys[chatId] = chatKey
        return chatKey
    }

    private func loadChatKey(chatId: String, wrappers: [WatchChatKeyWrapperRecord],
                             encryptedChatKey: String?) async -> WatchChatKeyResolver.Resolved? {
        guard let currentUserId,
              let masterKey = try? await CryptoManager.shared.loadMasterKey(for: currentUserId) else { return nil }
        guard let resolved = await WatchChatKeyResolver.resolve(
            chatId: chatId, wrappers: wrappers, encryptedChatKey: encryptedChatKey,
            masterKey: masterKey
        ) else { return nil }
        chatKeys[chatId] = resolved.key
        offlineWrappers[chatId] = resolved.wrapped
        return resolved
    }

    private func decrypt(_ encrypted: String?, key: SymmetricKey?) async -> String? {
        guard let encrypted, let key else { return nil }
        return try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: key)
    }
}

enum WatchChatKeyResolver {
    struct Resolved {
        let key: SymmetricKey
        let wrapped: String
        let outboundWrapped: String?
    }

    static func resolve(chatId: String, wrappers: [WatchChatKeyWrapperRecord],
                        encryptedChatKey: String?, masterKey: SymmetricKey) async -> Resolved? {
        let candidates = WatchChatKeyWrapperRecord.orderedMasterWrappers(wrappers, for: chatId)
            .map(\.encryptedChatKey) + (encryptedChatKey.map { [$0] } ?? [])
        for wrapped in candidates {
            if let key = try? await CryptoManager.shared.unwrapChatKey(
                encryptedChatKeyBase64: wrapped, masterKey: masterKey
            ) {
                // Existing-chat writes must send the exact immutable row value.
                // A different wrapper can decrypt content, but cannot replace it.
                var outboundWrapped: String?
                if let encryptedChatKey,
                   let rowKey = try? await CryptoManager.shared.unwrapChatKey(
                    encryptedChatKeyBase64: encryptedChatKey, masterKey: masterKey
                   ), rowKey.withUnsafeBytes({ Data($0) }) == key.withUnsafeBytes({ Data($0) }) {
                    outboundWrapped = encryptedChatKey
                }
                return Resolved(key: key, wrapped: wrapped, outboundWrapped: outboundWrapped)
            }
        }
        return nil
    }
}

enum WatchTurnAdmissionStage: String, Equatable, Sendable {
    case preflight, commit, legacyStorage = "legacy_storage"

    init?(requestType: String) {
        switch requestType {
        case "chat_turn_preflight": self = .preflight
        case "chat_message_added": self = .commit
        case "encrypted_chat_metadata": self = .legacyStorage
        default: return nil
        }
    }
}

enum WatchTurnAcknowledgementIssue: String, Equatable, Sendable {
    case missingState = "missing_state"
    case missingPreflightID = "missing_preflight_id"
    case unexpectedState = "unexpected_state"
    case missingTaskID = "missing_task_id"
    case missingStoredVersion = "missing_stored_version"
}

// All strings admitted here are static protocol codes from the preflight/
// message handlers and Directus chat-recovery-transaction prepare/enqueue paths.
// An unknown code, message, ID or other server value never enters diagnostics.
struct WatchTurnAdmissionDiagnostic: Equatable, Sendable {
    let stage: WatchTurnAdmissionStage
    let reason: String
    let invalidAcknowledgement: Bool

    private static let knownServerCodes: Set<String> = [
        "durable_preflight_failed", "transaction_failed", "team_permission_denied",
        "client_update_required", "inference_temporarily_unavailable", "active_task_in_progress",
        "inference_temporarily_paused", "cutover_state_corrupt", "invalid_request",
        "invalid_owner", "invalid_team", "invalid_chat_id", "invalid_turn_id", "invalid_message_id",
        "invalid_device", "invalid_key_version", "invalid_wrapped_chat_key", "invalid_recovery_public_key",
        "invalid_inference_commitment", "invalid_commitment_version", "invalid_message_version",
        "invalid_encrypted_message", "invalid_message_timestamp", "invalid_encrypted_chat_metadata",
        "invalid_chat_timestamp", "message_identity_mismatch", "message_identity_conflict",
        "chat_not_found", "preflight_mismatch", "existing_chat_metadata_forbidden", "version_conflict",
        "new_chat_metadata_required", "immutable_chat_key_mismatch", "recovery_key_mismatch",
        "invalid_preflight_id", "invalid_task_id", "invalid_billing_identity", "invalid_outbox_id",
        "preflight_not_found", "preflight_invalidated", "enqueue_identity_mismatch",
        "invalid_preflight_state", "preflight_expired"
    ]

    private init(stage: WatchTurnAdmissionStage, reason: String, invalidAcknowledgement: Bool) {
        self.stage = stage
        self.reason = reason
        self.invalidAcknowledgement = invalidAcknowledgement
    }

    static func serverRejection(stage: WatchTurnAdmissionStage, code: Any?) -> WatchChatRuntimeError {
        let reason = (code as? String).flatMap { knownServerCodes.contains($0) ? $0 : nil } ?? "unrecognized_server_code"
        return failure(stage: stage, reason: reason, invalidAcknowledgement: false)
    }

    static func invalidAcknowledgement(stage: WatchTurnAdmissionStage, issue: WatchTurnAcknowledgementIssue) -> WatchChatRuntimeError {
        failure(stage: stage, reason: issue.rawValue, invalidAcknowledgement: true)
    }

    private static func failure(stage: WatchTurnAdmissionStage, reason: String, invalidAcknowledgement: Bool) -> WatchChatRuntimeError {
        let diagnostic = Self(stage: stage, reason: reason, invalidAcknowledgement: invalidAcknowledgement)
        NativeDiagnostics.event("turn_admission_failed", category: "watch_chat_socket", level: .warning,
            flags: ["stage_\(stage.rawValue)": true, "reason_\(reason)": true,
                    "invalid_acknowledgement": invalidAcknowledgement])
        return .turnAdmissionFailure(diagnostic)
    }
}

// Shared by the real socket and account-free tests. Correlation is unchanged:
// errors for another turn remain queued and cannot reject/authorize this turn.
@MainActor
enum WatchSocketResponses {
    static func takeMatchingResponse(from inbox: inout [(type: String, payload: [String: Any])],
        requestType: String, responseTypes: Set<String>, matching: ([String: Any]) -> Bool) throws -> [String: Any]? {
        guard let index = inbox.firstIndex(where: {
            (responseTypes.contains($0.type) || $0.type == "error") && matching($0.payload)
        }) else { return nil }
        let event = inbox.remove(at: index)
        if event.type == "error" {
            guard let stage = WatchTurnAdmissionStage(requestType: requestType) else { throw WatchChatRuntimeError.preflightRejected }
            throw WatchTurnAdmissionDiagnostic.serverRejection(stage: stage, code: event.payload["code"])
        }
        return event.payload
    }
}

enum WatchChatRuntimeError: LocalizedError {
    case missingChatKey
    case audioUploadFailed
    case noSelectedChat
    case invalidRecording
    case sendInProgress
    case socketUnavailable
    case invalidPendingTurn
    case preflightRejected
    case inferenceRejected
    case historyUnavailable
    case turnAdmissionFailure(WatchTurnAdmissionDiagnostic)

    var errorDescription: String? {
        switch self {
        case .missingChatKey:
            return "Missing local chat key"
        case .audioUploadFailed: return "Audio upload failed"
        case .noSelectedChat: return "Open or create a chat first"
        case .invalidRecording: return "Recording is empty"
        case .sendInProgress: return "A message is already sending"
        case .socketUnavailable: return "Chat connection is unavailable"
        case .invalidPendingTurn: return "Pending message cannot be sent"
        case .preflightRejected: return "Message could not be saved"
        case .inferenceRejected: return "Message could not start a reply"
        case .historyUnavailable: return "Chat history could not be read"
        case .turnAdmissionFailure(let diagnostic):
            return diagnostic.stage == .commit ? "Message could not start a reply" : "Message could not be saved"
        }
    }
}

private struct WatchTranscribeSkillResponse: Decodable {
    struct ResponseData: Decodable {
        struct ResultGroup: Decodable {
            let results: [WatchTranscriptionMetadata]
        }

        let results: [ResultGroup]
    }

    let data: ResponseData
}

private struct WatchChatVersionEnvelope: Decodable {
    let messagesV: Int?
    let serverMessageCount: Int?
}

struct WatchChatListEnvelope: Decodable {
    let chats: [WatchChatDTO]
}

struct WatchChatDTO: Decodable {
    let id: String
    let title: String?
    let lastMessageAt: String?
    let updatedAt: String?
    let chatSummary: String?
    let isPinned: Bool?
    let encryptedTitle: String?
    let encryptedChatSummary: String?
    let encryptedChatKey: String?
    let chatKeyWrappers: [WatchChatKeyWrapperRecord]
    let messagesV: Int
    let titleV: Int
    let metadataV: Int
    let encryptedDraftMD: String?
    let encryptedDraftPreview: String?
    let draftV: Int?
    let clearedDraftV: Int?
    let lastEditedOverallTimestamp: String?
    let parentID: String?
    let isSubChat: Bool
    let encryptedCategory: String?
    let encryptedIcon: String?
    let isSupportChat: Bool
    let isSharedRecipient: Bool

    private enum CodingKeys: String, CodingKey {
        case encryptedCategory, encryptedCategorySnake = "encrypted_category", encryptedChatCategory, encryptedChatCategorySnake = "encrypted_chat_category"
        case encryptedIcon, encryptedIconSnake = "encrypted_icon"
        case isSupportChat, isSupportChatSnake = "is_support_chat"
        case isSharedRecipient, isSharedRecipientSnake = "is_shared_recipient"
        case id
        case lastEditedOverallTimestamp, lastEditedOverallTimestampSnake = "last_edited_overall_timestamp"
        case parentID = "parentId", parentIDSnake = "parent_id"
        case isSubChat, isSubChatSnake = "is_sub_chat"
        case chatId = "chat_id"
        case title
        case lastMessageAt
        case lastMessageAtSnake = "last_message_at"
        case updatedAt
        case updatedAtSnake = "updated_at"
        case chatSummary
        case chatSummarySnake = "chat_summary"
        case isPinned
        case isPinnedSnake = "is_pinned"
        case pinned
        case encryptedTitle
        case encryptedTitleSnake = "encrypted_title"
        case encryptedChatSummary
        case encryptedChatSummarySnake = "encrypted_chat_summary"
        case encryptedChatKey
        case encryptedChatKeySnake = "encrypted_chat_key"
        case chatKeyWrappers
        case chatKeyWrappersSnake = "chat_key_wrappers"
        case messagesV, titleV, metadataV
        case messagesVSnake = "messages_v"
        case titleVSnake = "title_v"
        case metadataVSnake = "metadata_v"
        case encryptedDraftMD = "encryptedDraftMd"
        case encryptedDraftMDSnake = "encrypted_draft_md"
        case encryptedDraftPreview
        case encryptedDraftPreviewSnake = "encrypted_draft_preview"
        case draftV
        case draftVSnake = "draft_v"
        case clearedDraftV
        case clearedDraftVSnake = "cleared_draft_v"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        encryptedCategory = try container.decodeIfPresent(String.self, forKey: .encryptedCategory) ?? container.decodeIfPresent(String.self, forKey: .encryptedCategorySnake) ?? container.decodeIfPresent(String.self, forKey: .encryptedChatCategory) ?? container.decodeIfPresent(String.self, forKey: .encryptedChatCategorySnake)
        encryptedIcon = try container.decodeIfPresent(String.self, forKey: .encryptedIcon) ?? container.decodeIfPresent(String.self, forKey: .encryptedIconSnake)
        isSupportChat = try container.decodeIfPresent(Bool.self, forKey: .isSupportChat) ?? container.decodeIfPresent(Bool.self, forKey: .isSupportChatSnake) ?? false
        isSharedRecipient = try container.decodeIfPresent(Bool.self, forKey: .isSharedRecipient) ?? container.decodeIfPresent(Bool.self, forKey: .isSharedRecipientSnake) ?? false
        lastEditedOverallTimestamp = try container.decodeIfPresent(String.self, forKey: .lastEditedOverallTimestamp) ?? container.decodeIfPresent(String.self, forKey: .lastEditedOverallTimestampSnake)
        parentID = try container.decodeIfPresent(String.self, forKey: .parentID) ?? container.decodeIfPresent(String.self, forKey: .parentIDSnake)
        isSubChat = try container.decodeIfPresent(Bool.self, forKey: .isSubChat) ?? container.decodeIfPresent(Bool.self, forKey: .isSubChatSnake) ?? false
        encryptedDraftMD = try container.decodeIfPresent(String.self, forKey: .encryptedDraftMD) ?? container.decodeIfPresent(String.self, forKey: .encryptedDraftMDSnake)
        encryptedDraftPreview = try container.decodeIfPresent(String.self, forKey: .encryptedDraftPreview) ?? container.decodeIfPresent(String.self, forKey: .encryptedDraftPreviewSnake)
        draftV = try container.decodeIfPresent(Int.self, forKey: .draftV) ?? container.decodeIfPresent(Int.self, forKey: .draftVSnake)
        clearedDraftV = try container.decodeIfPresent(Int.self, forKey: .clearedDraftV) ?? container.decodeIfPresent(Int.self, forKey: .clearedDraftVSnake)
        id = try container.decodeIfPresent(String.self, forKey: .id)
            ?? container.decode(String.self, forKey: .chatId)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        lastMessageAt = try container.decodeIfPresent(String.self, forKey: .lastMessageAt)
            ?? container.decodeIfPresent(String.self, forKey: .lastMessageAtSnake)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
            ?? container.decodeIfPresent(String.self, forKey: .updatedAtSnake)
        chatSummary = try container.decodeIfPresent(String.self, forKey: .chatSummary)
            ?? container.decodeIfPresent(String.self, forKey: .chatSummarySnake)
        isPinned = try container.decodeIfPresent(Bool.self, forKey: .isPinned)
            ?? container.decodeIfPresent(Bool.self, forKey: .isPinnedSnake)
            ?? container.decodeIfPresent(Bool.self, forKey: .pinned)
        encryptedTitle = try container.decodeIfPresent(String.self, forKey: .encryptedTitle)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedTitleSnake)
        encryptedChatSummary = try container.decodeIfPresent(String.self, forKey: .encryptedChatSummary)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedChatSummarySnake)
        encryptedChatKey = try container.decodeIfPresent(String.self, forKey: .encryptedChatKey)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedChatKeySnake)
        chatKeyWrappers = try container.decodeIfPresent([WatchChatKeyWrapperRecord].self, forKey: .chatKeyWrappers)
            ?? container.decodeIfPresent([WatchChatKeyWrapperRecord].self, forKey: .chatKeyWrappersSnake) ?? []
        messagesV = try container.decodeIfPresent(Int.self, forKey: .messagesV)
            ?? container.decodeIfPresent(Int.self, forKey: .messagesVSnake) ?? 0
        titleV = try container.decodeIfPresent(Int.self, forKey: .titleV)
            ?? container.decodeIfPresent(Int.self, forKey: .titleVSnake) ?? 0
        metadataV = try container.decodeIfPresent(Int.self, forKey: .metadataV)
            ?? container.decodeIfPresent(Int.self, forKey: .metadataVSnake) ?? titleV
    }
}

fileprivate struct WatchChatMessageDTO: Decodable {
    let id: String
    let chatId: String
    let role: WatchChatMessage.Role
    let content: String?
    let encryptedContent: String?
    let embedRefs: [WatchEmbedRef]?
    let createdAt: String

    private enum CodingKeys: String, CodingKey {
        case id
        case messageId, messageIdSnake = "message_id"
        case chatId
        case chatIdSnake = "chat_id"
        case role
        case content
        case encryptedContent
        case encryptedContentSnake = "encrypted_content"
        case embedRefs
        case embedRefsSnake = "embed_refs"
        case createdAt
        case createdAtSnake = "created_at"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .messageId)
            ?? container.decodeIfPresent(String.self, forKey: .messageIdSnake)
            ?? container.decode(String.self, forKey: .id)
        chatId = try container.decodeIfPresent(String.self, forKey: .chatId)
            ?? container.decode(String.self, forKey: .chatIdSnake)
        role = try container.decode(WatchChatMessage.Role.self, forKey: .role)
        content = try container.decodeIfPresent(String.self, forKey: .content)
        encryptedContent = try container.decodeIfPresent(String.self, forKey: .encryptedContent)
            ?? container.decodeIfPresent(String.self, forKey: .encryptedContentSnake)
        embedRefs = try container.decodeIfPresent([WatchEmbedRef].self, forKey: .embedRefs)
            ?? container.decodeIfPresent([WatchEmbedRef].self, forKey: .embedRefsSnake)
        if let timestamp = try? container.decode(String.self, forKey: .createdAt) { createdAt = timestamp }
        else if let timestamp = try? container.decode(String.self, forKey: .createdAtSnake) { createdAt = timestamp }
        else if let timestamp = try? container.decode(Int.self, forKey: .createdAt) { createdAt = String(timestamp) }
        else if let timestamp = try? container.decode(Int.self, forKey: .createdAtSnake) { createdAt = String(timestamp) }
        else { createdAt = "" }
    }
}

extension WatchRemoteChat {
    init(dto: WatchChatDTO) {
        self.init(
            id: dto.id,
            title: dto.title,
            lastMessageAt: dto.lastMessageAt ?? dto.updatedAt,
            updatedAt: dto.updatedAt,
            chatSummary: dto.chatSummary,
            isPinned: dto.isPinned == true,
            encryptedTitle: dto.encryptedTitle,
            encryptedChatSummary: dto.encryptedChatSummary,
            encryptedChatKey: dto.encryptedChatKey,
            chatKeyWrappers: dto.chatKeyWrappers,
            messagesV: dto.messagesV, titleV: dto.titleV, metadataV: dto.metadataV,
            lastEditedOverallTimestamp: dto.lastEditedOverallTimestamp, parentID: dto.parentID, isSubChat: dto.isSubChat,
            encryptedDraftMD: dto.encryptedDraftMD, encryptedDraftPreview: dto.encryptedDraftPreview,
            draftV: dto.draftV, clearedDraftV: dto.clearedDraftV,
            encryptedCategory: dto.encryptedCategory, encryptedIcon: dto.encryptedIcon,
            isSupportChat: dto.isSupportChat, isSharedRecipient: dto.isSharedRecipient
        )
    }
}

private extension WatchRemoteMessage {
    init(dto: WatchChatMessageDTO) {
        self.init(
            id: dto.id,
            chatId: dto.chatId,
            role: dto.role,
            content: dto.content,
            encryptedContent: dto.encryptedContent,
            embedRefs: dto.embedRefs,
            createdAt: dto.createdAt,
        )
    }
}

#if DEBUG
@MainActor
private final class WatchPreviewDraftCrypto: WatchChatCrypto {
    private let masterKey = SymmetricKey(size: .bits256)
    func decryptChat(_ chat: WatchRemoteChat) async -> WatchChatSummary? { nil }
    func decryptMessage(_ message: WatchRemoteMessage) async -> WatchChatMessage {
        WatchChatMessage(id: message.id, chatId: message.chatId, role: message.role,
            content: message.content, encryptedContent: message.encryptedContent,
            createdAt: message.createdAt, isPending: false)
    }
    func encryptText(_ text: String, for chat: WatchChatSummary) async throws -> String {
        try await CryptoManager.shared.encryptContent(text, key: masterKey)
    }
    func encryptDraft(_ text: String) async throws -> String {
        try await CryptoManager.shared.encryptWithMasterKey(text, masterKey: masterKey)
    }
    func decryptDraft(_ ciphertext: String) async throws -> String {
        try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: masterKey)
    }
    func createChat() async throws -> WatchChatSummary {
        WatchChatSummary(id: UUID().uuidString.lowercased(), title: nil, lastMessageAt: nil,
            preview: nil, isPinned: false, encryptedTitle: nil, encryptedPreview: nil,
            encryptedChatKey: try await CryptoManager.shared.wrapChatKey(masterKey, masterKey: masterKey))
    }
    func recoveryPublicKey(for chat: WatchChatSummary) async throws -> String {
        try await CryptoManager.shared.deriveRecoveryKeyPair(chatKey: masterKey, chatId: chat.id, keyVersion: 1).publicKey
    }
    func encryptedAudioEmbed(_ embed: WatchPendingAudioEmbed, chat: WatchChatSummary, messageId: String) async throws -> [[String: Any]] {
        throw WatchChatRuntimeError.socketUnavailable
    }
}

@MainActor
final class WatchOfflineFixtureCrypto: WatchChatCrypto {
    let key = SymmetricKey(size: .bits256)
    private(set) var decryptedMessageCount = 0
    func seal(_ text: String) throws -> String { try ComposerEmbedCrypto.encryptContent(text, using: key) }
    func decryptChat(_ chat: WatchRemoteChat) async -> WatchChatSummary? {
        var value = WatchChatSummary(id: chat.id, title: chat.encryptedTitle.flatMap { try? ComposerEmbedCrypto.decryptContent($0, using: key) } ?? chat.title,
            lastMessageAt: chat.lastMessageAt, preview: nil, isPinned: chat.isPinned,
            encryptedTitle: chat.encryptedTitle, encryptedPreview: nil, encryptedChatKey: chat.encryptedChatKey,
            messagesV: chat.messagesV, titleV: chat.titleV, metadataV: chat.metadataV)
        value.lastEditedOverallTimestamp = chat.lastEditedOverallTimestamp
        return value
    }
    func decryptMessage(_ message: WatchRemoteMessage) async -> WatchChatMessage {
        decryptedMessageCount += 1
        let text = message.encryptedContent.flatMap { try? ComposerEmbedCrypto.decryptContent($0, using: key) } ?? message.content
        return WatchChatMessage(id: message.id, chatId: message.chatId, role: message.role, content: text,
            encryptedContent: message.encryptedContent, embedRefs: WatchMessageContentSanitizer.inlineEmbedRefs(content: text),
            createdAt: message.createdAt, isPending: false)
    }
    func encryptText(_ text: String, for chat: WatchChatSummary) async throws -> String { try seal(text) }
    func decryptText(_ ciphertext: String, for chat: WatchChatSummary) async throws -> String { try ComposerEmbedCrypto.decryptContent(ciphertext, using: key) }
    func encryptDraft(_ text: String) async throws -> String { try seal(text) }
    func decryptDraft(_ ciphertext: String) async throws -> String { try ComposerEmbedCrypto.decryptContent(ciphertext, using: key) }
    func hydrateEmbed(payload: [String: Any], chat: WatchChatSummary) async throws -> WatchEmbedRef {
        guard let id = payload["embed_id"] as? String else { throw WatchChatRuntimeError.historyUnavailable }
        return try WatchEmbedHydration.open(payload: payload, embedID: id, chatID: chat.id,
            accountID: WatchOfflineFixtureTransport.accountID, masterKey: key, chatKey: key)
    }
    func createChat() async throws -> WatchChatSummary { throw WatchChatRuntimeError.socketUnavailable }
    func recoveryPublicKey(for chat: WatchChatSummary) async throws -> String { throw WatchChatRuntimeError.socketUnavailable }
    func encryptedAudioEmbed(_ embed: WatchPendingAudioEmbed, chat: WatchChatSummary, messageId: String) async throws -> [[String: Any]] { throw WatchChatRuntimeError.socketUnavailable }
}

/// Disposable DEBUG transport exercises the production disk/cohort path, then
/// becomes offline; no release network or credential path can select this type.
@MainActor
final class WatchOfflineFixtureTransport: WatchChatAPI, WatchChatSyncSocket {
    static let accountID = "watch-offline-fixture"
    let crypto: WatchOfflineFixtureCrypto
    var offline = false
    var holdBatch = false
    var partialBatch = false
    var wrongCount = false
    private(set) var requestedIDs: [String] = []
    private(set) var windowReadCount = 0
    private(set) var fullMessageReadCount = 0
    var generation: Int { 1 }
    var isConnected: Bool { !offline }
    init(crypto: WatchOfflineFixtureCrypto) { self.crypto = crypto }
    func chats() throws -> [WatchRemoteChat] {
        try (0...20).map { index in
            var chat = WatchRemoteChat(id: "watch-offline-\(index)", title: nil, lastMessageAt: String(1_800_000_000 + index), updatedAt: nil,
                chatSummary: nil, isPinned: index == 0, encryptedTitle: try crypto.seal("Offline chat \(index)"),
                encryptedChatSummary: nil, encryptedChatKey: "fixture-wrapped-key")
            chat.lastEditedOverallTimestamp = String(1_800_000_000 + index)
            return chat
        }.sorted { $0.isPinned != $1.isPinned ? $0.isPinned : ($0.lastMessageAt ?? "") > ($1.lastMessageAt ?? "") }
    }
    func fetchRecentChats(limit: Int, offset: Int, context: WatchChatRequestContext) async throws -> [WatchRemoteChat] {
        if offline { throw URLError(.notConnectedToInternet) }
        return Array(try chats().dropFirst(offset).prefix(limit))
    }
    func fetchMessages(chatId: String, context: WatchChatRequestContext) async throws -> [WatchRemoteMessage] {
        fullMessageReadCount += 1
        if offline { throw URLError(.notConnectedToInternet) }
        return []
    }
    func fetchMessageWindow(chatId: String, query: WatchMessageWindowQuery, context: WatchChatRequestContext) async throws -> WatchMessageWindow {
        windowReadCount += 1
        if offline { throw URLError(.notConnectedToInternet) }
        // Complete fixture history still comes exclusively from the encrypted
        // cohort batch; foreground REST is empty while this transport is online.
        return WatchMessageWindow(chatId: chatId, messages: [])
    }
    func fetchMessagesVersion(chatId: String, context: WatchChatRequestContext) async throws -> Int? { nil }
    func uploadAudioRecording(data: Data, filename: String, chatId: String, context: WatchChatRequestContext) async throws -> WatchUploadedAudio { throw WatchChatRuntimeError.socketUnavailable }
    func transcribeAudioRecording(_ upload: WatchUploadedAudio, chatId: String, context: WatchChatRequestContext) async throws -> WatchTranscriptionMetadata? { throw WatchChatRuntimeError.socketUnavailable }
    func connect(session: WatchSyncSession, syncState: WatchSyncClientState) { }
    func disconnect() { offline = true }
    func setChangeHandler(_ handler: (@MainActor () -> Void)?) { }
    func sendTurn(_ pending: WatchPendingTextSend) async throws { throw WatchChatRuntimeError.socketUnavailable }
    func sendEvent(type: String, payload: [String: Any]) async throws { if offline { throw WatchChatRuntimeError.socketUnavailable } }
    func requestEvent(type: String, payload: [String: Any], responseTypes: Set<String>, matching: @escaping @MainActor ([String: Any]) -> Bool) async throws -> [String: Any] {
        try Task.checkCancellation()
        guard !offline, type == "request_chat_content_batch", let id = (payload["chat_ids"] as? [String])?.first else { throw WatchChatRuntimeError.socketUnavailable }
        requestedIDs.append(id)
        while holdBatch { try await Task.sleep(for: .milliseconds(1)) }
        try Task.checkCancellation()
        let count = id == "watch-offline-20" ? 101 : 1
        let messages = try (0..<count).map { index -> [String: Any] in
            let text = index == 100 ? "Last offline response\n[!](embed:offline-sheet)" : "Offline message \(index)"
            return ["id": "offline-message-\(index)", "chat_id": id, "role": "assistant", "encrypted_content": try crypto.seal(text), "created_at": String(1_800_000_000 + index)]
        }
        var embeds: [[String: Any]] = []
        var keys: [[String: Any]] = []
        if id == "watch-offline-20" {
            let embedKey = SymmetricKey(size: .bits256)
            embeds = [["embed_id": "offline-sheet", "hashed_chat_id": WatchChatKeyWrapperRecord.hashedChatId(for: id),
                "encrypted_type": try ComposerEmbedCrypto.encryptContent("sheet", using: embedKey),
                "encrypted_content": try ComposerEmbedCrypto.encryptContent("{\"title\":\"offline.xls\",\"table\":\"|Name|Value|\\n|---|---|\\n|Offline|42|\",\"cell_count\":2}", using: embedKey), "status": "finished"]]
            keys = [["hashed_embed_id": WatchChatKeyWrapperRecord.hashedChatId(for: "offline-sheet"), "key_type": "master",
                "hashed_user_id": WatchChatKeyWrapperRecord.hashedChatId(for: Self.accountID),
                "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(embedKey, using: crypto.key)]]
        }
        return ["messages_by_chat_id": [id: messages], "versions_by_chat_id": [id: ["messages_v": count, "server_message_count": count + (wrongCount ? 1 : 0)]],
            "embeds": embeds, "embed_keys": keys, "chat_key_wrappers": [], "partial_error": partialBatch]
    }
}
#endif

#if DEBUG
private struct WatchMessageWindowFixtureTransport: WatchChatAPI {
    func fetchRecentChats(limit: Int, offset: Int, context: WatchChatRequestContext) async throws -> [WatchRemoteChat] { [] }
    func fetchMessages(chatId: String, context: WatchChatRequestContext) async throws -> [WatchRemoteMessage] { throw WatchChatRuntimeError.historyUnavailable }
    func fetchMessagesVersion(chatId: String, context: WatchChatRequestContext) async throws -> Int? { nil }
    func fetchMessageWindow(chatId: String, query: WatchMessageWindowQuery, context: WatchChatRequestContext) async throws -> WatchMessageWindow {
        let upper = query.before.flatMap { Int($0.messageId.replacingOccurrences(of: "window-message-", with: "")) } ?? 60
        let lower = max(0, upper - query.limit)
        let messages = (lower..<upper).map { index in
            WatchRemoteMessage(id: "window-message-\(index)", chatId: chatId, role: .assistant,
                content: "Remote message \(index)", encryptedContent: nil, createdAt: String(1_800_000_000 + index))
        }
        return WatchMessageWindow(chatId: chatId, messages: messages, hasMoreBefore: lower > 0,
            hasMoreAfter: upper < 60, startCursor: messages.first.map { WatchMessageWindowCursor(createdAt: Int($0.createdAt)!, messageId: $0.id) },
            endCursor: messages.last.map { WatchMessageWindowCursor(createdAt: Int($0.createdAt)!, messageId: $0.id) },
            messagesV: 60, serverMessageCount: 60)
    }
    func uploadAudioRecording(data: Data, filename: String, chatId: String, context: WatchChatRequestContext) async throws -> WatchUploadedAudio { throw WatchChatRuntimeError.audioUploadFailed }
    func transcribeAudioRecording(_ upload: WatchUploadedAudio, chatId: String, context: WatchChatRequestContext) async throws -> WatchTranscriptionMetadata? { throw WatchChatRuntimeError.audioUploadFailed }
}
#endif
