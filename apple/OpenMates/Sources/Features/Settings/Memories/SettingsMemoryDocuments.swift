// Settings > Memories view state over the Rust core's Memory documents.
// The core (`ViewModelCore` via `CoreSession`) decrypts, parses, validates,
// stamps save times, re-encrypts and deletes; this file only keeps page state:
// the rows in storage order, the web list sort/search (view state, web
// `utils/memoryListEntries.ts`), the editable draft and the mapping of the
// core's refusal codes to the web's messages (`MemoriesEditor.svelte`
// `displayError`). No protocol, crypto or document parsing here.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/MemoriesEditor.svelte
//          frontend/packages/ui/src/components/settings/MemoryList.svelte
//          frontend/packages/ui/src/components/settings/MemoryEntryPage.svelte
// TS:      frontend/packages/ui/src/utils/memoryListEntries.ts
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-memories/specification.yml
// Assertions: app-memories.lifecycle.encrypted-crud, app-memories.expiry.client-enforced, app-memories.load-modes, app-memories.compatibility.legacy-documents, app-memories.surface.semantic-parity

import Combine
import Foundation

/// The core calls the Memories pages use. `CoreSession` in the app; unit
/// tests inject a fake.
@MainActor
protocol SettingsMemoryDocumentStore: AnyObject {
    func listMemoryDocuments() async throws -> [MemoryDocumentRecord]
    func createMemoryDocument(fields: MemoryFieldsRecord) async throws -> MemoryDocumentRecord
    func updateMemoryDocument(id: String, fields: MemoryFieldsRecord) async throws -> MemoryDocumentRecord
    func deleteMemoryDocument(id: String) async throws
    func deleteExpiredMemoryDocuments() async throws -> UInt32
}

extension CoreSession: SettingsMemoryDocumentStore {}

/// Page of Settings > Memories (web `MemoryEditorView`): the list, the create
/// page or one Memory's page. Routes: `settings_memories`,
/// `settings_memories/create`, `settings_memories/<id>` and `memories/<id>`.
enum SettingsMemoryPage: Equatable {
    case list
    case create
    case entry(String)

    /// `nil` for a path that is not a Memories route.
    init?(path: String) {
        let parts = path.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard let first = parts.first else { return nil }
        if first == "settings_memories", parts.count == 1 { self = .list; return }
        guard parts.count == 2, ["settings_memories", "memories"].contains(first), !parts[1].isEmpty else { return nil }
        let id = parts[1].removingPercentEncoding ?? parts[1]
        if id == "create" {
            guard first == "settings_memories" else { return nil }
            self = .create
        } else {
            self = .entry(id)
        }
    }
}

/// Web list sorts (`MemorySort`); `modified` is the default.
enum SettingsMemorySort: String, CaseIterable {
    case modified, added, title
}

/// One stored Memory as a list row; `index` is its storage position (later
/// stored = larger), the tie-breaker of every sort.
struct SettingsMemoryRow: Identifiable, Equatable {
    let record: MemoryDocumentRecord
    let index: Int

    var id: String { record.id }
    /// `false` when this client cannot parse the document; it is listed and
    /// deletable, its page shows the stored text read-only.
    var isReadable: Bool { record.fields != nil }
    var title: String {
        if let title = record.fields?.title, !title.isEmpty { return title }
        let firstLine = record.document.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }.first { !$0.isEmpty }
        return firstLine.map { String($0.prefix(180)) } ?? record.id
    }
    /// Last change in unix seconds; a Memory saved once has only `createdAt`.
    var modifiedAt: UInt64? { record.updatedAt ?? record.createdAt }
}

/// The editable fields of the create/entry page (web `RuleDocumentFields`).
/// Fields this page does not edit (`description`, `references`) are kept as read.
struct SettingsMemoryDraft: Equatable {
    var title = ""
    var body = ""
    var whenToUse = ""
    var appId: String?
    var loadMode: MemoryLoadModeRecord = .autoInclude
    /// `YYYY-MM-DD`, `nil` for none.
    var validFrom: String?
    var validUntil: String?
    var description: String?
    var references: [String] = []

    init() {}

    init(_ fields: MemoryFieldsRecord) {
        title = fields.title; body = fields.body; whenToUse = fields.whenToUse
        appId = fields.appId; loadMode = fields.loadMode ?? .autoInclude
        validFrom = fields.validFrom.map { String($0.prefix(10)) }
        validUntil = fields.validUntil.map { String($0.prefix(10)) }
        description = fields.description; references = fields.references
    }

    /// The record the core validates and stores; dates use the web's
    /// start-of-day / end-of-day times.
    var fields: MemoryFieldsRecord {
        MemoryFieldsRecord(
            title: title, description: description, whenToUse: whenToUse, body: body,
            loadMode: loadMode,
            validFrom: validFrom.map { "\($0)T00:00:00.000Z" },
            validUntil: validUntil.map { "\($0)T23:59:59.000Z" },
            references: references, appId: appId)
    }
}

@MainActor
final class SettingsMemoryDocumentsModel: ObservableObject {
    enum LoadState: Equatable { case idle, loading, loaded, failed }

    /// Rows in storage order (as the core returns them).
    @Published private(set) var rows: [SettingsMemoryRow] = [] { didSet { updateVisibleRows() } }
    /// Rows after search and sort, as the list shows them.
    @Published private(set) var visibleRows: [SettingsMemoryRow] = []
    @Published private(set) var state: LoadState = .idle
    @Published private(set) var saving = false
    /// Web `memory-error-text`; `nil` for none.
    @Published private(set) var errorMessage: String?
    /// Web `rule-saved-notice` after the last save; cleared when a page opens.
    @Published private(set) var savedNotice: String?
    @Published var sort: SettingsMemorySort = .modified { didSet { updateVisibleRows() } }
    @Published var query = "" { didSet { updateVisibleRows() } }

    private let store: SettingsMemoryDocumentStore?
    private let locale: @MainActor () -> Locale
    private let now: @MainActor () -> Date
    private var generation = 0

    /// `store` is `nil` when the app's core could not be created
    /// (`CoreSession.launchError`); every load then fails visibly.
    init(store: SettingsMemoryDocumentStore?,
         locale: @escaping @MainActor () -> Locale = { Locale(identifier: LocalizationManager.shared.currentLanguage.code) },
         now: @escaping @MainActor () -> Date = { Date() }) {
        self.store = store; self.locale = locale; self.now = now
    }

    /// The row of `id` (or `personal:<id>`, like the web deep link).
    func row(for id: String) -> SettingsMemoryRow? {
        rows.first { $0.id == id || $0.id == "personal:\(id)" }
    }

    /// Screen opened: the web expiry sweep, then a fresh list. A failed sweep
    /// is shown and the list still loads (deleted Memories stay deleted).
    func open() async {
        let token = begin()
        guard let store else { fail(token: token, message: AppStrings.memoriesSaveFailed, log: "no_core"); return }
        state = .loading
        do {
            let removed = try await store.deleteExpiredMemoryDocuments()
            guard token == generation else { return }
            if removed > 0 { NativeDiagnostics.info("memory_expired_sweep removed=\(removed)", category: "settings_memories") }
        } catch {
            guard token == generation else { return }
            report(error, operation: "sweep")
        }
        await load(token: token, store: store)
    }

    /// Reload the list (Retry).
    func reload() async {
        let token = begin()
        guard let store else { fail(token: token, message: AppStrings.memoriesSaveFailed, log: "no_core"); return }
        state = .loading
        await load(token: token, store: store)
    }

    /// Stop publishing results of running calls (page left, account changed).
    func cancel() {
        generation += 1
        saving = false
    }

    /// A page opened: hide the last notice and error (web `open`).
    func clearMessages() {
        savedNotice = nil
        errorMessage = nil
    }

    /// Create (`existingID == nil`) or update one Memory; `true` once stored
    /// and the list was read again.
    func save(_ draft: SettingsMemoryDraft, existingID: String?) async -> Bool {
        guard let store, !saving else { return false }
        let token = generation
        saving = true; errorMessage = nil
        defer { if token == generation { saving = false } }
        do {
            if let existingID {
                _ = try await store.updateMemoryDocument(id: existingID, fields: draft.fields)
            } else {
                _ = try await store.createMemoryDocument(fields: draft.fields)
            }
            guard token == generation else { return false }
            let documents = try await store.listMemoryDocuments()
            guard token == generation else { return false }
            apply(documents)
            savedNotice = AppStrings.memoriesSaved
            return true
        } catch {
            guard token == generation else { return false }
            report(error, operation: existingID == nil ? "create" : "update")
            return false
        }
    }

    /// Delete one Memory (readable or not); `true` once deleted and listed again.
    func delete(id: String) async -> Bool {
        guard let store, !saving else { return false }
        let token = generation
        saving = true; errorMessage = nil
        defer { if token == generation { saving = false } }
        do {
            try await store.deleteMemoryDocument(id: id)
            guard token == generation else { return false }
            let documents = try await store.listMemoryDocuments()
            guard token == generation else { return false }
            apply(documents)
            return true
        } catch {
            guard token == generation else { return false }
            report(error, operation: "delete")
            return false
        }
    }

    /// Web Renew: keep the Memory for 30 more days from today.
    func renew(_ row: SettingsMemoryRow) async {
        guard let fields = row.record.fields else { return }
        var draft = SettingsMemoryDraft(fields)
        let until = now().addingTimeInterval(30 * 86_400)
        draft.validUntil = Self.dayString(until)
        _ = await save(draft, existingID: row.id)
    }

    /// Web row second line: `Private · Modified <date> · Expired`.
    func subtitle(for row: SettingsMemoryRow) -> String {
        let date = row.modifiedAt.map { modifiedFormatter().string(from: Date(timeIntervalSince1970: TimeInterval($0))) }
        return [AppStrings.memoriesVisibilityPrivate,
                date.map(AppStrings.memoriesModifiedOn) ?? "",
                row.record.expired ? AppStrings.memoriesExpired : ""]
            .filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private var cachedFormatter: (locale: Locale, formatter: DateFormatter)?

    /// Medium date in the UI locale (web `formatMemoryDate`), built once per locale.
    private func modifiedFormatter() -> DateFormatter {
        let current = locale()
        if let cachedFormatter, cachedFormatter.locale == current { return cachedFormatter.formatter }
        let formatter = DateFormatter()
        formatter.locale = current
        formatter.dateStyle = .medium
        formatter.timeStyle = .none
        cachedFormatter = (current, formatter)
        return formatter
    }

    // MARK: - Pure helpers (unit-tested)

    /// Web `sortMemoryEntries`: newest first by the chosen time, untimed
    /// Memories last, ties and untimed ones newest stored first; title A-Z.
    static func sorted(_ rows: [SettingsMemoryRow], by sort: SettingsMemorySort, locale: Locale) -> [SettingsMemoryRow] {
        switch sort {
        case .title:
            return rows.sorted { a, b in
                let order = a.title.compare(b.title, options: [.caseInsensitive, .diacriticInsensitive, .numeric],
                                            range: nil, locale: locale)
                return order == .orderedSame ? a.index > b.index : order == .orderedAscending
            }
        case .modified, .added:
            let pick: (SettingsMemoryRow) -> UInt64? = sort == .added ? { $0.record.createdAt } : { $0.modifiedAt }
            return rows.sorted { a, b in
                switch (pick(a), pick(b)) {
                case let (left?, right?) where left != right: return left > right
                case (nil, _?): return false
                case (_?, nil): return true
                default: return a.index > b.index
                }
            }
        }
    }

    /// Web `filterMemoryEntries`: case-insensitive title / when-to-use match.
    static func filtered(_ rows: [SettingsMemoryRow], query: String) -> [SettingsMemoryRow] {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !needle.isEmpty else { return rows }
        return rows.filter { "\($0.title)\n\($0.record.fields?.whenToUse ?? "")".lowercased().contains(needle) }
    }

    /// The web message for a failed Memory call; `nil` for a cancellation.
    static func message(for error: Error) -> String? {
        guard let coreError = error as? CoreError else {
            return error is CancellationError ? nil : AppStrings.memoriesSaveFailed
        }
        switch coreError {
        case .Cancelled: return nil
        case .Authentication, .Expired: return AppStrings.memoryAuthenticationRequired
        case .Memory(let code):
            switch code {
            case "invalid_rule_document": return AppStrings.memoriesInvalidDocument
            case "rule_changed": return AppStrings.memoriesDraftConflict
            case "rule_not_found": return AppStrings.memoriesNotFound
            default: return AppStrings.memoriesSaveFailed
            }
        default: return AppStrings.memoriesSaveFailed
        }
    }

    /// `YYYY-MM-DD` of `date` in the device calendar (web `<input type=date>` value).
    static func dayString(_ date: Date) -> String {
        dayFormatter.string(from: date)
    }

    /// Date of a `YYYY-MM-DD` value, `nil` when malformed.
    static func day(_ value: String) -> Date? {
        dayFormatter.date(from: value)
    }

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    // MARK: - Private

    private func begin() -> Int {
        generation += 1
        errorMessage = nil
        return generation
    }

    private func load(token: Int, store: SettingsMemoryDocumentStore) async {
        do {
            let documents = try await store.listMemoryDocuments()
            guard token == generation else { return }
            apply(documents)
            state = .loaded
        } catch {
            guard token == generation else { return }
            report(error, operation: "list")
            state = .failed
        }
    }

    private func apply(_ documents: [MemoryDocumentRecord]) {
        rows = documents.enumerated().map { SettingsMemoryRow(record: $0.element, index: $0.offset) }
    }

    private func fail(token: Int, message: String, log: String) {
        guard token == generation else { return }
        errorMessage = message
        state = .failed
        NativeDiagnostics.warning("memory_documents_unavailable reason=\(log)", category: "settings_memories")
    }

    private func report(_ error: Error, operation: String) {
        guard let message = Self.message(for: error) else { return }
        errorMessage = message
        NativeDiagnostics.warning(
            "memory_documents_failed op=\(operation) error=\(CoreSession.errorClass(error))", category: "settings_memories")
    }

    private func updateVisibleRows() {
        visibleRows = Self.sorted(Self.filtered(rows, query: query), by: sort, locale: locale())
    }
}

// Web keys: memories.* in frontend/packages/ui/src/i18n/locales/en.json.
extension AppStrings {
    static var memoriesSourcesHelp: String { localized("memories.sources_help") }
    static var memoriesPrivate: String { localized("memories.private_memories") }
    static var memoriesVisibilityPrivate: String { localized("memories.visibility_private") }
    static var memoriesCreate: String { localized("memories.create") }
    static var memoriesCreateTitle: String { localized("memories.create_title") }
    static var memoriesEmpty: String { localized("memories.empty") }
    static var memoriesSaved: String { localized("memories.saved") }
    static var memoriesSaveFailed: String { localized("memories.save_failed") }
    static var memoriesInvalidDocument: String { localized("memories.invalid_document") }
    static var memoriesDraftConflict: String { localized("memories.draft_conflict") }
    static var memoriesNotFound: String { localized("memories.suggestion_not_found") }
    static var memoriesExpired: String { localized("memories.expired") }
    static var memoriesRenew: String { localized("memories.renew") }
    static var memoriesSortLabel: String { localized("memories.sort_label") }
    static var memoriesSortModified: String { localized("memories.sort_recently_modified") }
    static var memoriesSortAdded: String { localized("memories.sort_recently_added") }
    static var memoriesSortTitle: String { localized("memories.sort_title") }
    static var memoriesFieldTitle: String { localized("memories.title") }
    static var memoriesFieldBody: String { localized("memories.practices") }
    static var memoriesBodyPlaceholder: String { localized("memories.body_placeholder") }
    static var memoriesWhenToUse: String { localized("memories.when_to_use") }
    static var memoriesWhenToUseOptional: String { localized("memories.when_to_use_optional") }
    static var memoriesWhenToUseHint: String { localized("memories.when_to_use_hint") }
    static var memoriesApp: String { localized("memories.app") }
    static var memoriesAppNone: String { localized("memories.app_none") }
    static var memoriesLoadMode: String { localized("memories.load_mode") }
    static var memoriesLoadModeAutoInclude: String { localized("memories.load_mode_auto_include") }
    static var memoriesLoadModeAskFirst: String { localized("memories.load_mode_ask_first") }
    static var memoriesLoadModeMentionOnly: String { localized("memories.load_mode_mention_only") }
    static var memoriesValidFrom: String { localized("memories.valid_from") }
    static var memoriesValidUntil: String { localized("memories.valid_until") }
    static var memoriesDiscoverApps: String { localized("settings.app_store.settings_memories.discover_link") }
    static var commonDate: String { localized("common.date") }
    static func memoriesModifiedOn(_ date: String) -> String {
        LocalizationManager.shared.text("memories.modified_on", replacements: ["date": date])
    }
}
