// Maps one core message (`MessageViewRecord` with its `MessageMetadataRecord`)
// to the `Message` value the existing chat views render (plan
// apple-client-core-migration A4 lane 3), so `MessageBubble` and the
// transcript stay unchanged. A pure field copy: the core decrypted, ordered
// and restored the message; nothing is derived here. The render form
// (`ChatHistoryRenderDocument`) is built once per mapped value by `Message.init`,
// and `CoreChatWindow` maps a message again only when its record changed.
// Timestamps: `createdAt`/`updatedAt` are unix seconds, the server's message-row
// unit (the same unit `Message` decodes from integer rows). A message the core
// has not stored yet (a streaming reply) has no `createdAt`; it takes
// `fallbackCreatedAt`, the time of the message before it in core order, so
// Swift's time-ordered helpers keep the core's order.
// Content is the core's text after PII restoration (`ChatWindowViewRecord.piiRestoration`);
// the stored mappings are passed through for the reveal control.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.shell.allowed-responsibilities

import Foundation

@MainActor
enum CoreMessageMapper {
    private static let iso = ISO8601DateFormatter()

    /// The message as the transcript renders it.
    static func map(_ record: MessageViewRecord, chatId: String, fallbackCreatedAt: String) -> Message {
        let meta = record.metadata
        return Message(
            id: record.id,
            chatId: chatId,
            role: role(record.role),
            content: record.content,
            encryptedContent: nil,
            createdAt: seconds(meta.createdAt) ?? fallbackCreatedAt,
            updatedAt: seconds(meta.updatedAt),
            appId: meta.appId,
            isStreaming: record.status == .streaming,
            embedRefs: record.embeds.isEmpty ? nil : record.embeds.map(embedRef),
            modelName: meta.modelName,
            senderName: record.sender.isEmpty ? nil : record.sender,
            category: meta.category,
            piiMappings: meta.piiMappings.isEmpty
                ? nil
                : meta.piiMappings.map { PIIMapping(placeholder: $0.placeholder, original: $0.original, type: $0.kind) },
            thinkingContent: record.thinking.isEmpty ? nil : record.thinking,
            thinkingTokenCount: meta.thinkingTokenCount.map { Int(clamping: $0) },
            serverMessageId: meta.serverMessageId,
            userMessageId: meta.userMessageId,
            queueRevision: meta.queueRevision.map { Int(clamping: $0) },
            queueMode: meta.queueMode,
            queueDispatchStatus: meta.queueDispatchStatus,
            queueDispatchMode: meta.queueDispatchMode,
            deliveryStatus: meta.storedStatus)
    }

    /// ISO-8601 text of a unix-seconds time, the `Message` timestamp form.
    static func seconds(_ value: Int64?) -> String? {
        value.map { iso.string(from: Date(timeIntervalSince1970: TimeInterval($0))) }
    }

    private static func role(_ role: MessageRoleRecord) -> MessageRole {
        switch role {
        case .user: return .user
        case .assistant: return .assistant
        case .system: return .system
        }
    }

    /// The embed reference with its metadata object. `dataJson` is the core's
    /// JSON object text (until the embeds lane); one that does not decode as an
    /// object is logged and carried without data, never guessed.
    private static func embedRef(_ embed: EmbedRefRecord) -> EmbedRef {
        EmbedRef(
            id: embed.id,
            type: embed.kind,
            status: embed.status.isEmpty ? nil : embed.status,
            data: embedData(embed.dataJson, embedId: embed.id))
    }

    private static func embedData(_ json: String, embedId: String) -> [String: AnyCodable]? {
        guard !json.isEmpty, json != "null" else { return nil }
        do {
            return try JSONDecoder().decode([String: AnyCodable].self, from: Data(json.utf8))
        } catch {
            NativeDiagnostics.warning(
                "core_embed_ref_data_undecodable embed=\(embedId.prefix(8))", category: "core_bridge")
            return nil
        }
    }
}
