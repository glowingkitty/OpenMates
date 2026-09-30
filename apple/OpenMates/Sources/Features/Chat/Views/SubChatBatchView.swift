// Inline sub-chat carousel for assistant batch markers.
// Child titles and summaries come only from decrypted account-scoped ChatStore data.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/sub_chats/SubChatBatchPreview.svelte
// TypeScript: frontend/packages/ui/src/services/subChatPreviewService.ts
// CSS:     SubChatBatchPreview.svelte <style> — .sub-chats-carousel,
//          .sub-chat-card, .sub-chat-status-pill, .sub-chat-large-content
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.rendering.assistant-document-convergence, chats.surface.semantic-parity

import Foundation
import SwiftUI
import Combine

struct SubChatBatchDescriptor: Codable, Equatable, Sendable {
    let batchID: String
    let parentChatID: String?
    let status: String
    let subChatIDs: [String]
    let executionMode: String?

    func accepts(parentID: String) -> Bool {
        !parentID.isEmpty && (parentChatID == nil || parentChatID == parentID)
    }

    func orderedChildren(in chats: [Chat], parentID: String, messageCreatedAt: String? = nil) -> [Chat] {
        guard accepts(parentID: parentID) else { return [] }
        let validChildren = chats.filter { $0.parentId == parentID }
        guard !subChatIDs.isEmpty else {
            guard !parentID.hasPrefix("example-"), let messageCreatedAt,
                  let messageDate = Self.parseDate(messageCreatedAt) else { return validChildren }
            return validChildren.filter {
                guard let createdDate = $0.createdDate else { return false }
                return abs(createdDate.timeIntervalSince(messageDate)) < 60
            }
        }
        let byID = Dictionary(uniqueKeysWithValues: validChildren.map { ($0.id, $0) })
        return subChatIDs.compactMap { byID[$0] }
    }

    private static func parseDate(_ value: String) -> Date? {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    }

    static func isProtocolMarker(_ code: String, language: String?) -> Bool {
        if let language, !language.isEmpty, language.lowercased() != "json" { return false }
        if let object = jsonObject(code) {
            return object["type"] as? String == "sub_chat_batch"
        }
        // A damaged protocol fence must not become a visible code sample.
        // Match only the explicit type field so ordinary JSON examples survive.
        return code.range(of: #""type"\s*:\s*"sub_chat_batch""#, options: .regularExpression) != nil
    }

    static func parse(_ code: String) -> Self? {
        guard let object = jsonObject(code),
              object["type"] as? String == "sub_chat_batch",
              let rawBatchID = object["batch_id"] as? String else { return nil }
        let batchID = rawBatchID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !batchID.isEmpty else { return nil }
        let rawStatus = object["status"] as? String ?? "processing"
        let status = ["processing", "finished", "error", "cancelled"].contains(rawStatus)
            ? rawStatus : "processing"
        let parentID = object["chat_id"] as? String ?? object["parent_chat_id"] as? String
        var seen = Set<String>()
        let ids = (object["sub_chat_ids"] as? [String] ?? [])
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && seen.insert($0).inserted }
        return Self(batchID: batchID, parentChatID: parentID,
                    status: status, subChatIDs: ids,
                    executionMode: object["execution_mode"] as? String)
    }

    private static func jsonObject(_ code: String) -> [String: Any]? {
        guard let data = code.trimmingCharacters(in: .whitespacesAndNewlines).data(using: .utf8) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
}

enum SubChatBatchPreviewText {
    private static let protocolFence = try! NSRegularExpression(
        pattern: #"```(?:json)?\s*[\r\n]+[\s\S]*?"type"\s*:\s*"(?:app[-_]skill[-_]use|sub[-_]chat[-_]batch)"[\s\S]*?```"#,
        options: [.caseInsensitive]
    )
    private static let whitespace = try! NSRegularExpression(pattern: #"\s+"#)

    static func summary(for chat: Chat, messages: [Message]) -> String? {
        if let summary = sanitize(chat.chatSummary) { return summary }
        for message in messages.reversed() where message.role == .assistant && message.isStreaming != true {
            if let summary = sanitize(message.content) {
                guard summary.count > 180 else { return summary }
                return String(summary.prefix(180)).trimmingCharacters(in: .whitespacesAndNewlines) + "..."
            }
        }
        return nil
    }

    static func sanitize(_ value: String?) -> String? {
        guard let value else { return nil }
        let full = NSRange(value.startIndex..., in: value)
        let withoutProtocol = protocolFence.stringByReplacingMatches(in: value, range: full, withTemplate: " ")
        let compact = whitespace.stringByReplacingMatches(
            in: withoutProtocol, range: NSRange(withoutProtocol.startIndex..., in: withoutProtocol),
            withTemplate: " "
        ).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !compact.isEmpty,
              compact.range(of: #""type"\s*:\s*"(?:app[-_]skill[-_]use|sub[-_]chat[-_]batch)""#,
                            options: [.regularExpression, .caseInsensitive]) == nil,
              !compact.contains("```json") else { return nil }
        return compact
    }
}

struct SubChatResolvedPreview {
    let title: String?
    let summary: String?
    let category: String?
    let icon: String?
}

@MainActor
enum SubChatPreviewLoader {
    static func resolve(chat: Chat, parentID: String, messages: [Message]) async -> SubChatResolvedPreview? {
        let scope = OfflineStore.shared.scopeGeneration
        let keyGeneration = ChatKeyManager.shared.cacheGeneration
        let key = ChatKeyManager.shared.key(for: chat.id) ?? ChatKeyManager.shared.key(for: parentID)

        func decrypt(_ ciphertext: String?) async -> String? {
            guard let ciphertext, let key else { return nil }
            return try? await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
        }

        var title = SubChatBatchPreviewText.sanitize(chat.title)
        if title == nil { title = SubChatBatchPreviewText.sanitize(await decrypt(chat.encryptedTitle)) }
        var category = chat.category
        if category == nil { category = await decrypt(chat.encryptedCategory) }
        var icon = chat.icon
        if icon == nil { icon = await decrypt(chat.encryptedIcon) }
        var summary = SubChatBatchPreviewText.sanitize(await decrypt(chat.encryptedChatSummary))
        if summary == nil { summary = SubChatBatchPreviewText.sanitize(chat.chatSummary) }
        if summary == nil {
            for message in messages.reversed() where message.role == .assistant && message.isStreaming != true {
                var text = message.content
                if text == nil { text = await decrypt(message.encryptedContent) }
                if let value = SubChatBatchPreviewText.sanitize(text) {
                    summary = value.count > 180
                        ? String(value.prefix(180)).trimmingCharacters(in: .whitespacesAndNewlines) + "..."
                        : value
                    break
                }
            }
        }
        guard scope == OfflineStore.shared.scopeGeneration,
              keyGeneration == ChatKeyManager.shared.cacheGeneration else { return nil }
        return SubChatResolvedPreview(title: title, summary: summary, category: category, icon: icon)
    }
}

struct SubChatBatchView: View {
    let descriptor: SubChatBatchDescriptor
    let parentChatID: String
    let messageCreatedAt: String?
    let viewportWidth: CGFloat?
    let store: ChatStore?
    let progress: SubChatProgress?
    let completedSubChatIDs: Set<String>
    let onOpenChat: ((String) -> Void)?

    var body: some View {
        Group {
            if descriptor.accepts(parentID: parentChatID), let store {
                SubChatBatchCardsView(descriptor: descriptor, parentChatID: parentChatID,
                                      messageCreatedAt: messageCreatedAt, viewportWidth: viewportWidth,
                                      store: store, progress: progress,
                                      completedSubChatIDs: completedSubChatIDs, onOpenChat: onOpenChat)
            }
        }
    }
}

private struct SubChatBatchCardsView: View {
    let descriptor: SubChatBatchDescriptor
    let parentChatID: String
    let messageCreatedAt: String?
    let viewportWidth: CGFloat?
    @ObservedObject var store: ChatStore
    let progress: SubChatProgress?
    let completedSubChatIDs: Set<String>
    let onOpenChat: ((String) -> Void)?
    @State private var resolvedPreviews: [String: SubChatResolvedPreview] = [:]
    @State private var resolvedScope: UUID?
    @State private var keyRefresh = 0

    private var children: [Chat] {
        descriptor.orderedChildren(in: store.chats, parentID: parentChatID,
                                   messageCreatedAt: messageCreatedAt)
    }

    private var previewRevision: String {
        let childVersions = children.map { child in
            let messages = store.messages(for: child.id)
            let latest = messages.last
            return "\(child.id):\(child.updatedAt ?? ""):\(latest?.id ?? ""):\(latest?.updatedAt ?? ""):\(latest?.isStreaming == true):\(messages.count)"
        }.joined(separator: "|")
        return "\(keyRefresh):\(childVersions)"
    }

    private func scopedPreview(for childID: String) -> SubChatResolvedPreview? {
        guard resolvedScope == OfflineStore.shared.scopeGeneration else { return nil }
        return resolvedPreviews[childID]
    }

    var body: some View {
        let compact = (viewportWidth ?? 390) <= 680
        if children.isEmpty {
            Text(AppStrings.subChatBatchLoading)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .padding(.spacing6)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius7))
                .accessibilityIdentifier("sub-chats-carousel")
        } else {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing8) {
                    ForEach(children) { child in
                        Button {
                            onOpenChat?(child.id)
                        } label: {
                            SubChatBatchCard(chat: child, status: cardStatus(for: child),
                                             compact: compact,
                                             resolvedPreview: scopedPreview(for: child.id),
                                             previewSummary: scopedPreview(for: child.id)?.summary
                                                ?? SubChatBatchPreviewText.summary(
                                                    for: child, messages: store.messages(for: child.id)))
                        }
                        .buttonStyle(.plain)
                        .disabled(onOpenChat == nil)
                        .accessibilityIdentifier("sub-chat-card")
                        .accessibilityValue(compact ? "260x188" : "300x200")
                    }
                }
                .padding(.horizontal, .spacing2)
                .padding(.top, .spacing6)
                .padding(.bottom, .spacing8)
            }
            .accessibilityIdentifier("sub-chats-carousel")
            .task(id: previewRevision) {
                let scope = OfflineStore.shared.scopeGeneration
                let keyGeneration = ChatKeyManager.shared.cacheGeneration
                var loaded: [String: SubChatResolvedPreview] = [:]
                for child in children {
                    if let preview = await SubChatPreviewLoader.resolve(
                        chat: child, parentID: parentChatID,
                        messages: store.messages(for: child.id)
                    ) { loaded[child.id] = preview }
                }
                guard scope == OfflineStore.shared.scopeGeneration,
                      keyGeneration == ChatKeyManager.shared.cacheGeneration else { return }
                resolvedPreviews = loaded
                resolvedScope = scope
            }
            .onReceive(NotificationCenter.default.publisher(for: .chatKeyMaterialAvailable)) { notification in
                guard notification.userInfo?["accountScope"] as? UUID == OfflineStore.shared.scopeGeneration else { return }
                keyRefresh += 1
            }
        }
    }

    private func cardStatus(for child: Chat) -> SubChatBatchCard.Status {
        let status = progress?.status ?? ""
        if scopedPreview(for: child.id)?.summary != nil
            || SubChatBatchPreviewText.summary(for: child, messages: store.messages(for: child.id)) != nil
            || completedSubChatIDs.contains(child.id)
            || descriptor.status == "finished" || status == "completed" {
            return .completed
        }
        if descriptor.status == "error" || status == "error" || status == "failed" { return .attention }
        if descriptor.status == "cancelled" || status == "cancelled" || status == "stopped" { return .stopped }
        if progress?.activeSubChatId == child.id { return .thinking }
        if (progress?.executionMode ?? descriptor.executionMode) == "sequential" && status != "completed" { return .waiting }
        if descriptor.status == "processing" || status == "running" || status == "stopping" { return .thinking }
        return .queued
    }
}

private struct SubChatBatchCard: View {
    enum Status {
        case completed, attention, stopped, thinking, waiting, queued

        var testID: String {
            switch self {
            case .completed: "sub-chat-status-completed"
            case .attention: "sub-chat-status-attention"
            case .stopped: "sub-chat-status-stopped"
            case .thinking: "sub-chat-status-thinking"
            case .waiting: "sub-chat-status-waiting"
            case .queued: "sub-chat-status-queued"
            }
        }

        @MainActor
        func label(title: String) -> String {
            switch self {
            case .completed: AppStrings.subChatCompleted
            case .attention: AppStrings.subChatNeedsAttention
            case .stopped: AppStrings.subChatStopped
            case .thinking: AppStrings.subChatThinking(title)
            case .waiting: AppStrings.subChatWaiting
            case .queued: AppStrings.subChatQueued
            }
        }
    }

    let chat: Chat
    let status: Status
    let compact: Bool
    let resolvedPreview: SubChatResolvedPreview?
    let previewSummary: String?

    private var category: String { resolvedPreview?.category ?? chat.category ?? "general_knowledge" }
    private var iconName: String {
        LucideCategoryIconAsset.name(for: resolvedPreview?.icon ?? chat.icon,
                                     fallback: CategoryMapping.lucideIconName(for: category))
    }
    private var title: String {
        let raw = (resolvedPreview?.title ?? chat.title)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return raw.isEmpty ? AppStrings.subChatAutonomousTask : raw
    }
    private var summary: String? { previewSummary }

    private func cardIcon(size: CGFloat) -> some View {
        Icon(iconName, size: size)
    }

    var body: some View {
        let width: CGFloat = compact ? 260 : 300
        let height: CGFloat = compact ? 188 : 200
        VStack(spacing: 7) {
            cardIcon(size: 32).accessibilityHidden(true)
            Text(title)
                .font(.omP.weight(.bold))
                .lineLimit(3)
                .accessibilityIdentifier("sub-chat-title")
            if let summary {
                Text(summary)
                    .font(.omXxs.weight(.medium))
                    .lineLimit(4)
                    .foregroundStyle(Color.white.opacity(0.85))
                    .accessibilityIdentifier("sub-chat-summary")
            } else {
                Text(AppStrings.subChatTapToOpen)
                    .font(.omXxs.weight(.semibold))
                    .foregroundStyle(Color.white.opacity(0.85))
                    .accessibilityIdentifier("sub-chat-open-cta")
            }
        }
        .multilineTextAlignment(.center)
        .foregroundStyle(Color.fontButton)
        .frame(width: width - 32, height: height - 16, alignment: .top)
        .padding(.top, 16)
        .frame(width: width, height: height, alignment: .top)
        .background {
            CategoryMapping.gradient(for: category)
                .overlay(alignment: .bottomLeading) {
                    cardIcon(size: 80)
                        .rotationEffect(.degrees(-15))
                        .foregroundStyle(Color.white.opacity(0.22))
                        .offset(x: -12, y: 22)
                        .accessibilityHidden(true)
                }
                .overlay(alignment: .bottomTrailing) {
                    cardIcon(size: 80)
                        .rotationEffect(.degrees(15))
                        .foregroundStyle(Color.white.opacity(0.22))
                        .offset(x: 12, y: 22)
                        .accessibilityHidden(true)
                }
        }
        .overlay(alignment: .topLeading) {
            Text(status.label(title: String(title.prefix(22))))
                .font(.omXxs.weight(.heavy))
                .lineLimit(1)
                .padding(.horizontal, 9)
                .padding(.vertical, 4)
                .background(Color.black.opacity(0.28))
                .clipShape(Capsule())
                .overlay(Capsule().strokeBorder(Color.white.opacity(0.22), lineWidth: 1))
                .foregroundStyle(Color.white.opacity(0.92))
                .padding(.spacing8)
                .accessibilityIdentifier(status.testID)
        }
        .clipShape(RoundedRectangle(cornerRadius: 30))
        .shadow(color: .black.opacity(0.16), radius: 12, x: 0, y: 8)
        .shadow(color: .black.opacity(0.1), radius: 3, x: 0, y: 2)
        .accessibilityLabel(title)
    }
}
