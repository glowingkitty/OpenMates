// Pure mapping from the app's composer types to the core's send records
// (plan apple-client-core-migration A5): composer embed nodes to
// `SendEmbedRecord`, the app's `PIIMapping` to `PiiMappingRecord` and the send
// choices (reserved ids, project, incognito, PII detection and exclusions) to
// `SendOptionsRecord`. No behaviour beyond the mapping: whether PII is
// detected, how an embed is stored and what a record may carry stay with the
// core. What a record cannot express is dropped by returning `nil` for the
// node (never approximated); callers read `unmapped` to keep it visible.
// Specification: specifications/architecture/client-core/specification.yml
// Assertions: client-core.viewmodel.capability-contract, client-core.shell.allowed-responsibilities

import Foundation

enum CoreSendMapping {
    /// The prefix of a composer embed node's `contentRef`.
    private static let embedRefPrefix = "embed:"
    /// The composer's preview family name of the recording embed; the core uses the backend type.
    private static let composerRecordingType = "recording"
    private static let backendRecordingType = "audio-recording"
    private static let statusFinished = "finished"
    private static let statusProcessing = "processing"

    /// The composer nodes of `document` that became records and the ids of the embed nodes that could not.
    struct EmbedMapping: Equatable {
        let records: [SendEmbedRecord]
        let unmapped: [String]
    }

    /// Maps embed `node` to a record; `nil` for a node that is no embed, has no
    /// durable embed id (`contentRef` `embed:<id>`) or whose status is neither
    /// `finished` nor `processing` (the record cannot express draft,
    /// uploading, transcribing, correcting, error or cancelled).
    /// `content`, `textPreview` and `childEmbedIds` come from the caller's upload or
    /// embed state; the composer node does not hold them.
    static func embedRecord(from node: ComposerNodeV1, content: String? = nil, textPreview: String? = nil,
                            childEmbedIds: [String]? = nil) -> SendEmbedRecord? {
        guard node.kind == "embed", let embedType = node.embedType, !embedType.isEmpty,
              let reference = node.contentRef, reference.hasPrefix(embedRefPrefix),
              let status = node.status, status == statusFinished || status == statusProcessing
        else { return nil }
        let embedId = String(reference.dropFirst(embedRefPrefix.count))
        guard !embedId.isEmpty else { return nil }
        return SendEmbedRecord(
            embedId: embedId,
            embedType: embedType == composerRecordingType ? backendRecordingType : embedType,
            referenceType: nil,
            status: status,
            content: content,
            textPreview: textPreview,
            childEmbedIds: childEmbedIds)
    }

    /// Maps every embed node of `document` in order.
    /// Maps a composer-pending embed with the same rules as the node mapper:
    /// only finished or processing embeds with an id and type are sent.
    static func embedRecord(from embed: ComposerPendingEmbed) -> SendEmbedRecord? {
        guard !embed.id.isEmpty, !embed.type.isEmpty,
              embed.status == statusFinished || embed.status == statusProcessing
        else { return nil }
        return SendEmbedRecord(
            embedId: embed.id,
            embedType: embed.type == composerRecordingType ? backendRecordingType : embed.type,
            referenceType: embed.referenceType.isEmpty ? nil : embed.referenceType,
            status: embed.status,
            content: embed.content,
            textPreview: embed.textPreview,
            childEmbedIds: nil)
    }

    static func embedRecords(from document: ComposerDocumentV1) -> EmbedMapping {
        var records: [SendEmbedRecord] = []
        var unmapped: [String] = []
        for node in document.nodes where node.kind == "embed" {
            if let record = embedRecord(from: node) {
                records.append(record)
            } else {
                unmapped.append(node.id)
            }
        }
        return EmbedMapping(records: records, unmapped: unmapped)
    }

    static func piiMapping(_ mapping: PIIMapping) -> PiiMappingRecord {
        PiiMappingRecord(placeholder: mapping.placeholder, original: mapping.original, kind: mapping.type)
    }

    /// The send options of a turn. Exclusions are sorted so equal choices give equal records.
    static func options(
        piiDetection: Bool = true,
        incognito: Bool = false,
        slug: String? = nil,
        reservedChatId: String? = nil,
        reservedMessageId: String? = nil,
        embeds: [SendEmbedRecord] = [],
        excludedPiiOriginals: Set<String> = [],
        excludedPiiPlaceholders: Set<String> = [],
        piiMappings: [PIIMapping] = [],
        projectId: String? = nil
    ) -> SendOptionsRecord {
        SendOptionsRecord(
            piiDetection: piiDetection,
            incognito: incognito,
            slug: slug,
            reservedChatId: reservedChatId,
            reservedMessageId: reservedMessageId,
            embeds: embeds,
            excludedPiiOriginals: excludedPiiOriginals.sorted(),
            excludedPiiPlaceholders: excludedPiiPlaceholders.sorted(),
            piiMappings: piiMappings.map(piiMapping),
            projectId: projectId)
    }
}
