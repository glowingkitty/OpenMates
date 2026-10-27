// Usage data projection shared by Billing's inline panel and dedicated route.
// Web source: frontend/packages/ui/src/components/settings/SettingsUsage.svelte
// Reference: 78e8d99023c4a90ad06b2d1b35cd257c15cab8fc
// Specification: specifications/features/billing/specification.yml
// Assertions: billing.usage.landing-complete, billing.usage.receipt-token-breakdown, billing.surface.semantic-parity

import Combine
import Foundation
import CryptoKit

// Endpoint query values are protocol data, never translated display labels.
enum UsageTab: String, CaseIterable {
    case overview, chats, apps, api
    var backendType: String { self == .api ? "api_keys" : rawValue }
    var detailType: String { self == .api ? "api_key" : self == .chats ? "chat" : "app" }
}

struct UsageSummaryResponse: Decodable {
    let summaries: [UsageSummary]
    let count: Int? // The existing server's returned row count; never month availability.
    let hasMoreMonths: Bool?
    let nextOlderMonth: String?
}
struct UsageDetailsResponse: Decodable { let entries: [UsageEntry] }
struct DailyUsageResponse: Decodable { let days: [UsageDay]; let hasMoreDays: Bool? }

struct UsageSummary: Decodable, Identifiable {
    let chatId: String?
    let appId: String?
    let apiKeyHash: String?
    let month: String
    let totalCredits: Double
    let encryptedName: String?
    let encryptedKeyPrefix: String?
    private enum CodingKeys: String, CodingKey {
        case chatId, appId, apiKeyHash, month, yearMonth, totalCredits, encryptedName, encryptedKeyPrefix
    }
    init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        chatId = try fields.decodeIfPresent(String.self, forKey: .chatId)
        appId = try fields.decodeIfPresent(String.self, forKey: .appId)
        apiKeyHash = try fields.decodeIfPresent(String.self, forKey: .apiKeyHash)
        // Current/pinned REST returns raw year_month; older fixtures used month.
        month = try fields.decodeIfPresent(String.self, forKey: .yearMonth) ?? fields.decode(String.self, forKey: .month)
        guard BillingUsageMonth.date(month) != nil else {
            throw DecodingError.dataCorruptedError(forKey: .yearMonth, in: fields, debugDescription: "Invalid usage summary month")
        }
        totalCredits = try fields.decode(Double.self, forKey: .totalCredits)
        encryptedName = try fields.decodeIfPresent(String.self, forKey: .encryptedName)
        encryptedKeyPrefix = try fields.decodeIfPresent(String.self, forKey: .encryptedKeyPrefix)
    }
    var identifier: String? { chatId ?? appId ?? apiKeyHash }
    var id: String { "\(chatId ?? ""):\(appId ?? ""):\(apiKeyHash ?? ""):\(month)" }
}

struct UsageDay: Decodable, Identifiable {
    let date: String
    let totalCredits: Double
    let items: [UsageOverviewItem]
    var id: String { date }
}

struct UsageOverviewItem: Decodable {
    let type: String
    let chatId: String?
    let apiKeyHash: String?
    let appId: String?
    let skillId: String?
    let usageType: String?
    let startedMinutes: Int?
    let totalCredits: Double
    let entryCount: Int
    let encryptedTitle: String?
    let encryptedChatKey: String?
    let isDeleted: Bool?
}

struct UsageTimestamp: Decodable {
    let value: String
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let number = try? container.decode(Double.self) { value = String(number) }
        else { value = try container.decode(String.self) }
    }
}

struct UsageEntry: Decodable, Identifiable {
    let id: String
    let type: String
    let appId: String?
    let skillId: String?
    let chatId: String?
    let messageId: String?
    var credits: Double?
    let createdAt: UsageTimestamp?
    let modelUsed: String?
    let serverProvider: String?
    let serverRegion: String?
    let inputTokens: Int?
    let outputTokens: Int?
    let systemPromptTokens: Int?
    let userInputTokens: Int?
    let toolInferenceIterations: Int?
    let creditsSystemPrompt: Double?
    let creditsHistory: Double?
    let creditsResponse: Double?
    let llmUsageBreakdown: LLMUsageBreakdown?
    var appSkillTokens: Int? {
        guard let iterations = toolInferenceIterations, iterations > 0,
              let input = inputTokens, let system = systemPromptTokens, let user = userInputTokens,
              input > system + user else { return nil }
        return input - system - user
    }
}

// Only already-authorized local metadata becomes presentation data. No keys,
// ciphertext, or chat titles are retained in this value.
struct BillingUsageChatAppearance: Equatable {
    enum Kind: Equatable { case standard, incognito, deleted, unsentDraft }
    let kind: Kind
    var category: String? = nil
    var lucideIcon: String? = nil
    static let fallback = Self(kind: .standard, lucideIcon: "help-circle")
    var semanticIcon: String? {
        switch kind {
        case .standard: nil
        case .incognito: "anonym"
        case .deleted: "delete"
        case .unsentDraft: "recordaudio"
        }
    }
}

struct BillingUsageRow: Identifiable {
    let id: String
    let title: String
    let subtitle: String
    let icon: String
    let credits: Double
    let identifier: String
    var chatID: String? = nil
    var summary: UsageSummary? = nil
    var chatAppearance: BillingUsageChatAppearance? = nil
}
struct BillingUsageGroup: Identifiable {
    let id: String
    let title: String
    let credits: Double
    let rows: [BillingUsageRow]
}
struct BillingUsageEntryRow: Identifiable {
    let entry: UsageEntry
    let title: String
    let subtitle: String
    var id: String { entry.id }
}

enum BillingUsageOpenTarget: Equatable {
    case message(chatID: String, messageID: String)
    case embed(chatID: String, embedID: String)
}

// The parent supplies its current decrypted store and existing navigation actions.
// Defaults read only scoped encrypted-cache projections; navigation stays unavailable.
@MainActor
struct BillingUsageContext {
    var hiddenChatsUnlocked = false
    var chat: (String) -> Chat? = { OfflineStore.shared.loadChat(id: $0) }
    var messages: (String) -> [Message] = { OfflineStore.shared.loadMessages(chatId: $0) }
    var embeds: (String) -> [EmbedRecord] = { OfflineStore.shared.loadEmbeds(chatId: $0) }
    var openTarget: ((BillingUsageOpenTarget) -> Void)? = nil
}

enum BillingUsageMonth {
    static func date(_ value: String) -> Date? {
        guard value.utf8.count == 7 else { return nil }
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian); formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM"; formatter.isLenient = false
        guard let date = formatter.date(from: value), formatter.string(from: date) == value else { return nil }
        return date
    }
    static func cutoff(window: Int, now: Date) -> String {
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian); formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM"
        return formatter.string(from: now.addingTimeInterval(-Double(max(0, window - 1)) * 30 * 24 * 60 * 60))
    }
    static func windowIncluding(_ value: String, now: Date) -> Int? {
        guard let target = date(value), target.timeIntervalSince1970 >= 0, target <= now else { return nil }
        // The existing endpoint samples now - i*30 days. Extend through the
        // requested older month, rather than repeatedly loading empty gaps.
        return max(3, Int(ceil(now.timeIntervalSince(target) / (30 * 24 * 60 * 60))) + 1)
    }
}

@MainActor
final class BillingUsageModel: ObservableObject {
    typealias Transport = @MainActor (String, UserTasksAccountFence) async throws -> Data
    @Published private(set) var groups: [BillingUsageGroup] = []
    @Published private(set) var entryRows: [BillingUsageEntryRow] = []
    @Published private(set) var loading = false
    @Published private(set) var error = false
    @Published private(set) var selectedTitle: String?
    @Published private(set) var selectedEntry: UsageEntry?
    @Published private(set) var selectedTarget: BillingUsageOpenTarget?
    @Published private(set) var hasMore = false
    @Published private(set) var historyAvailabilityMissing = false
    private var nextOlderMonth: String?
    private let now: () -> Date
    @Published private(set) var exportURL: URL?
    private(set) var loadedDays = 7
    private(set) var loadedMonths = 3
    private var generation = UUID()
    private let draftAudioRegistry: BillingUsageDraftAudioRegistry
    private let transport: Transport
    private let validate: @MainActor (UserTasksAccountFence) async throws -> Void
    private var metadata: [String: AppMetadata] = [:]
    private var context = BillingUsageContext()
    private var activeFence: UserTasksAccountFence?
    private var backendChatMetadata: [String: UsageOverviewItem] = [:]
    private var legacyKeys: [LegacyKey] = []
    private var hasAttemptedLegacyKeys = false
    private struct LegacyKey: Decodable {
        let keyHash: String?
        let encryptedName: String?
        let encryptedKeyPrefix: String?
    }
    private struct LegacyKeysResponse: Decodable { let apiKeys: [LegacyKey] }
    private struct AppMetadata: Decodable {
        let nameTranslationKey: String?
        let skills: [Skill]?
        struct Skill: Decodable { let id: String; let nameTranslationKey: String? }
    }
    private struct Catalog: Decodable { let apps: [String: AppMetadata] }

    init(transport: @escaping Transport = { path, fence in
        try await APIClient.shared.request(.get, path: path, serverProfile: fence.serverProfile,
            expectedAccountID: fence.accountID, expectedScope: fence.scope,
            expectedTeamContext: fence.requestTeamContext)
    }, validate: @escaping @MainActor (UserTasksAccountFence) async throws -> Void = { try await $0.check() },
       now: @escaping () -> Date = Date.init,
       draftAudioRegistry: BillingUsageDraftAudioRegistry = .shared) {
        self.transport = transport; self.validate = validate; self.now = now; self.draftAudioRegistry = draftAudioRegistry
    }

    func canDisplay(accountID: String?, hiddenUnlocked: Bool) -> Bool {
        guard let fence = activeFence, accountID == fence.accountID,
              fence.scope == OfflineStore.shared.scopeGeneration,
              fence.serverProfile == ServerProfile.current(),
              (try? fence.checkTeamContext()) != nil,
              hiddenUnlocked == context.hiddenChatsUnlocked else { return false }
        return true
    }

    func invalidate() {
        generation = UUID(); groups = []; entryRows = []; selectedEntry = nil
        selectedTitle = nil; selectedTarget = nil; error = false; loading = false; hasMore = false
        exportURL = nil; metadata = [:]; legacyKeys = []; hasAttemptedLegacyKeys = false
        activeFence = nil; backendChatMetadata = [:]; loadedDays = 7; loadedMonths = 3
        nextOlderMonth = nil; historyAvailabilityMissing = false
    }

    func load(tab: UsageTab, accountID: String?, more: Bool = false, fixture: Bool = false, context: BillingUsageContext = .init()) async {
        let request = UUID(); generation = request; self.context = context
        selectedTarget = nil
        loading = true; error = false; selectedTitle = nil; selectedEntry = nil; entryRows = []
        defer { if generation == request { loading = false } }
        let days = more ? min(90, loadedDays + 7) : loadedDays
        let olderWindow = nextOlderMonth.flatMap { BillingUsageMonth.windowIncluding($0, now: now()) }
        let months = more ? max(loadedMonths + 3, olderWindow ?? 0) : loadedMonths
        do {
            if fixture {
                try projectFixture(tab: tab, more: more)
                return
            }
            guard let accountID else { invalidate(); return }
            let fence = UserTasksAccountFence(accountID: accountID)
            try await validate(fence)
            activeFence = fence
            if metadata.isEmpty, let data = try? await transport("/v1/apps/metadata?include_unavailable=true", fence) {
                let catalog = try? Self.decode(Catalog.self, data)
                try await validate(fence)
                guard generation == request, !Task.isCancelled else { return }
                metadata = catalog?.apps ?? [:]
            }
            let path = tab == .overview ? "/v1/settings/usage/daily-overview?days=\(days)&reconcile=true"
                : "/v1/settings/usage/summaries?type=\(tab.backendType)&months=\(months)"
            let data = try await transport(path, fence)
            try await validate(fence)
            guard generation == request, !Task.isCancelled else { return }
            let next: [BillingUsageGroup]
            let moreAvailable: Bool
            var availabilityMissing = false
            var nextMonth: String?
            if tab == .overview {
                let response = try Self.decode(DailyUsageResponse.self, data)
                next = try await projectDays(response.days, fence: fence)
                moreAvailable = response.hasMoreDays == true && days < 90
            } else {
                let response = try Self.decode(UsageSummaryResponse.self, data)
                next = try await projectSummaries(response.summaries, tab: tab, fence: fence)
                if let candidate = response.nextOlderMonth {
                    guard response.hasMoreMonths == true, BillingUsageMonth.windowIncluding(candidate, now: now()) != nil,
                          candidate < BillingUsageMonth.cutoff(window: months, now: now()) else {
                        throw APIError.invalidResponse
                    }
                    nextMonth = candidate
                }
                moreAvailable = response.hasMoreMonths == true
                availabilityMissing = response.hasMoreMonths == nil
            }
            try await validate(fence)
            guard generation == request, !Task.isCancelled else { return }
            groups = next; hasMore = moreAvailable; loadedDays = days; loadedMonths = months
            nextOlderMonth = nextMonth; historyAvailabilityMissing = availabilityMissing
        } catch {
            guard generation == request, !Task.isCancelled else { return }
            groups = []; hasMore = false; historyAvailabilityMissing = false; nextOlderMonth = nil; self.error = true
            NativeDiagnostics.warning("Usage load failed", category: "billing_usage")
        }
    }

    func open(_ row: BillingUsageRow, tab: UsageTab, accountID: String?, fixture: Bool = false) async {
        guard row.chatID != nil || row.summary?.identifier != nil else { return }
        let request = UUID(); generation = request
        selectedTitle = row.title; selectedEntry = nil; selectedTarget = nil; entryRows = []; loading = true; error = false
        defer { if generation == request { loading = false } }
        do {
            let entries: [UsageEntry]
            if fixture { entries = try Self.decode(UsageDetailsResponse.self, Data(Self.fixtureEntries.utf8)).entries }
            else {
                guard let accountID else { invalidate(); return }
                let fence = UserTasksAccountFence(accountID: accountID)
                try await validate(fence)
                let path: String
                if let chatID = row.chatID {
                    path = "/v1/settings/usage/chat-entries?chat_id=\(UserTasksPaths.escaped(chatID))"
                } else if let summary = row.summary, let identifier = summary.identifier {
                    path = "/v1/settings/usage/details?type=\(tab.detailType)&identifier=\(UserTasksPaths.escaped(identifier))&year_month=\(UserTasksPaths.escaped(summary.month))"
                } else { return }
                let data = try await transport(path, fence)
                try await validate(fence)
                entries = try Self.decode(UsageDetailsResponse.self, data).entries
            }
            guard generation == request, !Task.isCancelled else { return }
            // The web only combines assistant speech segments in monthly detail lists.
            let display = row.summary == nil ? entries : Self.groupSpeech(entries)
            entryRows = display.map { entry in
                .init(entry: entry, title: entry.llmUsageBreakdown?.entries.contains(where: { $0.purpose == "summary" }) == true
                    ? AppStrings.receiptAutomaticSummary : activity(app: entry.appId, skill: entry.skillId),
                    subtitle: [entry.createdAt.map { ChatSettingsUsageRow.formatTimestamp($0.value) }, entry.modelUsed].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
            }
        } catch {
            guard generation == request, !Task.isCancelled else { return }
            entryRows = []; self.error = true
        }
    }

    func back() {
        generation = UUID(); selectedTitle = nil; selectedEntry = nil; selectedTarget = nil; entryRows = []; loading = false; error = false
    }

    func export(accountID: String?, fixture: Bool = false) async {
        guard !fixture, let accountID else { return }
        let request = generation
        do {
            let fence = UserTasksAccountFence(accountID: accountID)
            try await validate(fence)
            let data = try await transport("/v1/settings/usage/export?months=\(loadedMonths)", fence)
            try await validate(fence)
            guard generation == request, !Task.isCancelled else { return }
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("usage-\(UUID().uuidString).csv")
            try data.write(to: url, options: .atomic)
            exportURL = url
        } catch {
            guard generation == request, !Task.isCancelled else { return }
            self.error = true
        }
    }

    private func projectDays(_ days: [UsageDay], fence: UserTasksAccountFence) async throws -> [BillingUsageGroup] {
        var result: [BillingUsageGroup] = []
        for day in days {
            var rows: [BillingUsageRow] = []
            for (index, item) in day.items.enumerated() {
                let title: String
                if item.type == "chat", let chatID = item.chatId { backendChatMetadata[chatID] = item }
                if item.type == "chat" || item.type == "incognito" {
                    title = try await chatTitle(id: item.chatId, deleted: item.isDeleted == true,
                        encryptedTitle: item.encryptedTitle, wrapper: item.encryptedChatKey, fence: fence)
                } else { title = overviewTitle(item) }
                let appearance = item.type == "chat" || item.type == "incognito"
                    ? try await chatAppearance(id: item.chatId, deleted: item.isDeleted == true,
                        unsentDraft: title == AppStrings.usageUnsentDraft, fence: fence) : nil
                rows.append(.init(id: "\(day.date):\(index)", title: title, subtitle: overviewSubtitle(item),
                    icon: title == AppStrings.usageUnsentDraft ? "recordaudio" : overviewIcon(item), credits: item.totalCredits, identifier: overviewIdentifier(item),
                    chatID: item.type == "chat" || item.type == "incognito" ? item.chatId : nil, chatAppearance: appearance))
            }
            result.append(.init(id: day.date, title: AppStrings.usageDay(day.date), credits: day.totalCredits, rows: rows))
        }
        return result
    }

    private func projectSummaries(_ summaries: [UsageSummary], tab: UsageTab, fence: UserTasksAccountFence) async throws -> [BillingUsageGroup] {
        var months: [String: [BillingUsageRow]] = [:]
        for summary in summaries.sorted(by: { $0.totalCredits > $1.totalCredits }) {
            let title: String
            var subtitle = ""
            if tab == .chats { title = try await chatTitle(id: summary.chatId, deleted: false, encryptedTitle: nil, wrapper: nil, fence: fence) }
            else if tab == .apps { title = appName(summary.appId) }
            else if let hash = summary.apiKeyHash, Self.isDevice(hash) { title = AppStrings.usageDevice(hash) }
            else {
                let master = try await CryptoManager.shared.loadMasterKey(for: fence.accountID)
                try await validate(fence)
                var name: String?
                let fallback: LegacyKey?
                if summary.encryptedName == nil && summary.encryptedKeyPrefix == nil {
                    if !hasAttemptedLegacyKeys {
                        hasAttemptedLegacyKeys = true
                        if let data = try? await transport("/v1/settings/api-keys", fence) {
                            try await validate(fence)
                            legacyKeys = (try? Self.decode(LegacyKeysResponse.self, data).apiKeys) ?? []
                        }
                    }
                    fallback = legacyKeys.first { $0.keyHash == summary.apiKeyHash }
                } else { fallback = nil }
                if let master {
                    if let encrypted = summary.encryptedName ?? fallback?.encryptedName { name = try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: master) }
                    if let encrypted = summary.encryptedKeyPrefix ?? fallback?.encryptedKeyPrefix { subtitle = (try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: master)) ?? "" }
                }
                subtitle = subtitle.trimmingCharacters(in: .whitespacesAndNewlines)
                if subtitle.count > 8 { subtitle = String(subtitle.prefix(4)) + "…" + String(subtitle.suffix(2)) }
                title = name?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty ?? AppStrings.usageAPIKeyDetails
            }
            try await validate(fence)
            let appearance = tab == .chats ? try await chatAppearance(id: summary.chatId, deleted: false,
                unsentDraft: title == AppStrings.usageUnsentDraft, fence: fence) : nil
            months[summary.month, default: []].append(.init(id: summary.id, title: title, subtitle: subtitle,
                icon: appearance?.semanticIcon ?? (tab == .chats ? "chat" : tab == .apps ? (summary.appId ?? "app_store") : "coding"),
                credits: summary.totalCredits, identifier: "usage-\(tab.rawValue)-summary-row", summary: summary, chatAppearance: appearance))
        }
        return months.keys.sorted(by: >).map { month in
            let rows = months[month] ?? []
            return .init(id: month, title: month, credits: rows.reduce(0) { $0 + $1.credits }, rows: rows)
        }
    }

    private func chatTitle(id: String?, deleted: Bool, encryptedTitle: String?, wrapper: String?, fence: UserTasksAccountFence) async throws -> String {
        if id == "incognito" { return AppStrings.usageIncognito }
        let backend = id.flatMap { backendChatMetadata[$0] }
        if deleted || backend?.isDeleted == true {
            if let id, try await hasDraftAudio(chatID: id, fence: fence) { return AppStrings.usageUnsentDraft }
            return AppStrings.usageDeletedChat
        }
        guard let id else { return AppStrings.chat }
        let chat = context.chat(id)
        guard chat == nil || (chat?.id == id && chat?.teamId == fence.teamID) else { return AppStrings.chat }
        // Hidden metadata must remain masked; a billing read never unlocks chats.
        if chat?.isHiddenFromNormalSurfaces == true && !context.hiddenChatsUnlocked { return AppStrings.chat }
        if let title = chat?.title?.nilIfEmpty { return title }
        let ciphertext = chat?.encryptedTitle ?? encryptedTitle ?? backend?.encryptedTitle
        guard let ciphertext else { return AppStrings.chat }
        let keyGeneration = ChatKeyManager.shared.cacheGeneration
        var key = ChatKeyManager.shared.key(for: id)
        if key == nil, let wrapped = chat?.encryptedChatKey ?? wrapper ?? backend?.encryptedChatKey,
           let master = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) {
            key = try? await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: wrapped, masterKey: master)
        }
        try await validate(fence)
        guard keyGeneration == ChatKeyManager.shared.cacheGeneration, let key else { return AppStrings.chat }
        let title = try? await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
        try await validate(fence)
        guard keyGeneration == ChatKeyManager.shared.cacheGeneration else { return AppStrings.chat }
        // Do not install fallback keys or write decrypted metadata to persistent storage.
        return title?.nilIfEmpty ?? AppStrings.chat
    }

    private func chatAppearance(id: String?, deleted: Bool, unsentDraft: Bool,
                                fence: UserTasksAccountFence) async throws -> BillingUsageChatAppearance {
        if id == "incognito" { return .init(kind: .incognito) }
        if deleted || id.flatMap({ backendChatMetadata[$0] })?.isDeleted == true {
            return .init(kind: unsentDraft ? .unsentDraft : .deleted)
        }
        guard let id, let chat = context.chat(id), chat.id == id, chat.teamId == fence.teamID,
              !chat.isHiddenFromNormalSurfaces || context.hiddenChatsUnlocked else { return .fallback }
        let request = generation, keyGeneration = ChatKeyManager.shared.cacheGeneration
        var category = chat.category?.nilIfEmpty, icon = chat.icon?.nilIfEmpty
        if (category == nil && chat.encryptedCategory != nil) || (icon == nil && chat.encryptedIcon != nil) {
            var key = ChatKeyManager.shared.key(for: id)
            if key == nil, let wrapped = chat.encryptedChatKey ?? backendChatMetadata[id]?.encryptedChatKey,
               let master = try await CryptoManager.shared.loadMasterKey(for: fence.accountID) {
                try await validate(fence)
                guard generation == request, keyGeneration == ChatKeyManager.shared.cacheGeneration else { throw CancellationError() }
                key = try? await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: wrapped, masterKey: master)
            }
            try await validate(fence)
            guard generation == request, keyGeneration == ChatKeyManager.shared.cacheGeneration else { throw CancellationError() }
            if let key {
                if category == nil, let encrypted = chat.encryptedCategory {
                    category = try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: key)
                    try await validate(fence)
                    guard generation == request, keyGeneration == ChatKeyManager.shared.cacheGeneration else { throw CancellationError() }
                }
                if icon == nil, let encrypted = chat.encryptedIcon {
                    icon = try? await CryptoManager.shared.decryptContent(base64String: encrypted, key: key)
                    try await validate(fence)
                    guard generation == request, keyGeneration == ChatKeyManager.shared.cacheGeneration else { throw CancellationError() }
                }
            }
        }
        try await validate(fence)
        guard generation == request, keyGeneration == ChatKeyManager.shared.cacheGeneration,
              let current = context.chat(id), current.id == id, current.teamId == fence.teamID,
              !current.isHiddenFromNormalSurfaces || context.hiddenChatsUnlocked else { return .fallback }
        // Unknown categories have no web gradient. A missing icon uses the
        // category fallback; an invalid supplied icon gets the renderer's help-circle.
        let categoryName = category?.nilIfEmpty
        let fallback = categoryName.map { CategoryMapping.lucideIconName(for: $0) } ?? "help-circle"
        return .init(kind: .standard, category: categoryName.flatMap { CategoryMapping.isKnownCategory($0) ? $0 : nil },
            lucideIcon: icon?.nilIfEmpty ?? fallback)
    }

    func selectEntry(_ entry: UsageEntry, fixture: Bool = false) async {
        selectedEntry = entry; selectedTarget = nil
        let request = generation
        guard !fixture, let fence = activeFence else { return }
        do {
            try await validate(fence)
            guard request == generation, selectedEntry?.id == entry.id, !Task.isCancelled else { return }
            selectedTarget = target(for: entry)
        } catch { invalidate() }
    }

    func closeEntry() { selectedEntry = nil; selectedTarget = nil }

    func openSelectedTarget() async {
        guard let entry = selectedEntry, let fence = activeFence, let expected = selectedTarget else { return }
        do {
            try await validate(fence)
            guard selectedEntry?.id == entry.id, target(for: entry) == expected else { selectedTarget = nil; return }
            context.openTarget?(expected)
        } catch { invalidate() }
    }

    private func target(for entry: UsageEntry) -> BillingUsageOpenTarget? {
        guard context.openTarget != nil, let chatID = entry.chatId, let messageID = entry.messageId, !messageID.isEmpty,
              let chat = context.chat(chatID), chat.teamId == activeFence?.teamID,
              !chat.isHiddenFromNormalSurfaces || context.hiddenChatsUnlocked else { return nil }
        if entry.appId == "ai", entry.skillId == "ask" {
            guard context.messages(chatID).contains(where: {
                $0.chatId == chatID && ($0.id == messageID || ($0.serverMessageId?.isEmpty == false && $0.serverMessageId == messageID))
            }) else { return nil }
            return .message(chatID: chatID, messageID: messageID)
        }
        guard let appID = entry.appId, let skillID = entry.skillId else { return nil }
        let hash = SHA256.hash(data: Data(messageID.utf8)).map { String(format: "%02x", $0) }.joined()
        guard let embed = context.embeds(chatID).first(where: {
            $0.appId == appID && $0.skillId == skillID && $0.hashedMessageId == hash
        }) else { return nil }
        return .embed(chatID: chatID, embedID: embed.id)
    }

    private func hasDraftAudio(chatID: String, fence: UserTasksAccountFence) async throws -> Bool {
        // Recording companions also exist on established chats. Only confirmed
        // new-draft allocation evidence can label a deleted usage row as unsent.
        try await draftAudioRegistry.contains(chatID: chatID, fence: fence)
    }

    private func appName(_ id: String?) -> String {
        guard let id else { return AppStrings.usageAppActivity }
        return AppStrings.usageAppName(id, translationKey: metadata[id]?.nameTranslationKey)
    }
    private func activity(app: String?, skill: String?) -> String {
        let key = metadata[app ?? ""]?.skills?.first(where: { $0.id == skill })?.nameTranslationKey
        return [appName(app), skill.map { AppStrings.usageSkillName($0, translationKey: key) }].compactMap { $0 }.joined(separator: " - ")
    }
    private func overviewTitle(_ item: UsageOverviewItem) -> String {
        switch item.type {
        case "api_key": AppStrings.usageAPIKeyDetails
        case "device": AppStrings.usageDevice(item.apiKeyHash ?? "")
        case "unattributed": AppStrings.billingUnknownUsage
        case "benchmark": item.appId == nil ? AppStrings.usageBenchmark : appName(item.appId)
        default: appName(item.appId)
        }
    }
    private func overviewSubtitle(_ item: UsageOverviewItem) -> String {
        var parts: [String] = []
        switch item.type {
        case "workflow": parts.append(AppStrings.usageWorkflowRun)
        case "workflow_test": parts.append(AppStrings.usageWorkflowTest)
        case "app": parts.append(item.usageType == "realtime_transcription_interrupted" ? AppStrings.usageInterruptedRecording : AppStrings.usageStandaloneActivity)
        case "api_key": parts.append(AppStrings.usageAPIKeyActivity)
        case "device": parts.append(AppStrings.usageDeviceActivity)
        case "benchmark": parts.append(AppStrings.usageBenchmark)
        case "unattributed": parts.append(AppStrings.usageContextUnavailable)
        default: break
        }
        if !["chat", "incognito", "api_key", "device"].contains(item.type), let skill = item.skillId {
            let key = metadata[item.appId ?? ""]?.skills?.first(where: { $0.id == skill })?.nameTranslationKey
            parts.insert(AppStrings.usageSkillName(skill, translationKey: key), at: 0)
        }
        if let minutes = item.startedMinutes, minutes > 0 { parts.append(AppStrings.usageStartedMinutes(minutes)) }
        parts.append(AppStrings.usageRequests(item.entryCount))
        return parts.joined(separator: " · ")
    }
    private func overviewIcon(_ item: UsageOverviewItem) -> String {
        switch item.type {
        case "chat": item.isDeleted == true ? "delete" : "chat"
        case "incognito": "anonym"
        case "api_key", "benchmark": "coding"
        case "device": "devices"
        case "unattributed": "help-circle"
        default: item.appId ?? "app_store"
        }
    }
    private func overviewIdentifier(_ item: UsageOverviewItem) -> String {
        switch item.type {
        case "chat", "incognito": "usage-overview-chat-row"
        case "workflow", "workflow_test": "usage-overview-workflow-row"
        case "api_key", "device": "usage-overview-api-device-row"
        case "app": "usage-overview-app-row"
        default: "usage-overview-other-row"
        }
    }
    static func isDevice(_ hash: String) -> Bool {
        ["cli:", "apple-ios:", "apple-macos:", "apple:"].contains(where: { hash.hasPrefix($0) })
    }
    static func groupSpeech(_ entries: [UsageEntry]) -> [UsageEntry] {
        var result: [UsageEntry] = []
        var positions: [String: Int] = [:]
        for entry in entries {
            guard entry.appId == "assistant_response_speech", let chat = entry.chatId, let message = entry.messageId else {
                result.append(entry); continue
            }
            let timestamp = Double(entry.createdAt?.value ?? "") ?? 0
            let date = Date(timeIntervalSince1970: timestamp)
            let month = Calendar.current.dateComponents([.year, .month], from: date)
            let key = "\(chat):\(message):\(month.year ?? 0)-\(month.month ?? 0)"
            if let index = positions[key] { result[index].credits = (result[index].credits ?? 0) + (entry.credits ?? 0) }
            else { positions[key] = result.count; result.append(entry) }
        }
        return result
    }
    static func decode<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(type, from: data)
    }
}
private extension String { var nilIfEmpty: String? { isEmpty ? nil : self } }

// Deterministic synthetic billing fixture. Never reads a signed-in account.
extension BillingUsageModel {
    static let fixtureOverview = """
    {"days":[{"date":"2026-10-19","total_credits":43,"items":[
      {"type":"chat","chat_id":"00000000-0000-0000-0000-000000000369","total_credits":5,"entry_count":2},
      {"type":"incognito","chat_id":"incognito","total_credits":3,"entry_count":1},
      {"type":"app","app_id":"audio","skill_id":"transcribe","usage_type":"realtime_transcription_interrupted","started_minutes":1,"total_credits":8,"entry_count":1},
      {"type":"api_key","api_key_hash":"fixture-key","total_credits":3,"entry_count":1},
      {"type":"device","api_key_hash":"cli:fixture-device","total_credits":4,"entry_count":1},
      {"type":"workflow","app_id":"weather","skill_id":"forecast","total_credits":7,"entry_count":1},
      {"type":"workflow_test","app_id":"web","skill_id":"search","total_credits":5,"entry_count":1},
      {"type":"benchmark","app_id":"ai","skill_id":"ask","total_credits":6,"entry_count":1},
      {"type":"unattributed","app_id":"ai","skill_id":"ask","total_credits":2,"entry_count":1}
    ]}],"has_more_days":true}
    """
    static let fixtureEntries = """
    {"entries":[{"id":"fixture-usage-receipt","type":"skill_execution","app_id":"ai","skill_id":"ask",
      "chat_id":"00000000-0000-0000-0000-000000000369","message_id":"fixture-usage-message","created_at":1792386000,"credits":12,
      "model_used":"fixture/model","server_provider":"Fixture provider","server_region":"EU",
      "input_tokens":1500,"system_prompt_tokens":1000,"user_input_tokens":100,"output_tokens":150,"tool_inference_iterations":2,
      "credits_system_prompt":6,"credits_history":2,"credits_response":4,
      "llm_usage_breakdown":{"schema_version":1,"input_tokens":1500,"uncached_input_tokens":1000,"cache_read_input_tokens":500,
        "output_tokens":150,"usage_source":"fixture","raw_credits":"11.6000","rounding_adjustment":"0.4000","credits_charged":12,
        "entries":[{"model_id":"fixture/model","input_tokens":1500,"uncached_input_tokens":1000,"cache_read_input_tokens":500,
          "output_tokens":150,"rates":{"input":"100","cache_read":"1000","output":"100"},
          "category_credits":{"input":"10","cache_read":"0.5","cache_write":"0","cache_write_1h":"0","output":"1.1"},"raw_credits":"11.6000"}]}}
    ]}
    """
    private func projectFixture(tab: UsageTab, more: Bool) throws {
        if tab == .overview {
            let response = try Self.decode(DailyUsageResponse.self, Data(Self.fixtureOverview.utf8))
            groups = response.days.map { day in
                .init(id: day.id, title: AppStrings.usageDay(day.date), credits: day.totalCredits,
                    rows: day.items.enumerated().map { index, item in
                        .init(id: "\(day.id):\(index)", title: item.type == "chat" ? AppStrings.chat : item.type == "incognito" ? AppStrings.usageIncognito : overviewTitle(item),
                            subtitle: overviewSubtitle(item), icon: overviewIcon(item), credits: item.totalCredits,
                            identifier: overviewIdentifier(item), chatID: item.chatId,
                            chatAppearance: item.type == "chat" ? .init(kind: .standard, category: "software_development", lucideIcon: "rocket")
                                : item.type == "incognito" ? .init(kind: .incognito) : nil)
                    })
            }
            if more {
                loadedDays += 7
                groups.append(.init(id: "2026-10-12", title: AppStrings.usageDay("2026-10-12"), credits: 0, rows: []))
            }
            hasMore = !more
        } else {
            let field = tab == .chats ? "chat_id" : tab == .apps ? "app_id" : "api_key_hash"
            let value = tab == .chats ? "00000000-0000-0000-0000-000000000369" : tab == .apps ? "ai" : "cli:fixture-device"
            let payload = "{\"summaries\":[{\"\(field)\":\"\(value)\",\"month\":\"2026-10\",\"total_credits\":12}]}"
            let summary = try Self.decode(UsageSummaryResponse.self, Data(payload.utf8)).summaries[0]
            let title = tab == .chats ? AppStrings.chat : tab == .apps ? appName("ai") : AppStrings.usageDevice(value)
            groups = [.init(id: "2026-10", title: "2026-10", credits: 12, rows: [
                .init(id: summary.id, title: title, subtitle: "", icon: tab == .chats ? "chat" : tab == .apps ? "ai" : "coding", credits: 12,
                    identifier: "usage-\(tab.rawValue)-summary-row", summary: summary,
                    chatAppearance: tab == .chats ? .init(kind: .standard, lucideIcon: "invalid-usage-fixture-icon") : nil)])]
            hasMore = false
        }
    }
}
