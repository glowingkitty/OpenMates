// Web source: frontend/packages/ui/src/components/chats/chatUsageRows.ts.
// Reads established owner-only usage endpoints with captured account fences.
import Combine
import Foundation
import Yams
import ZIPFoundation

struct ChatSettingsUsageRow: Decodable, Identifiable {
    let id: String
    let label: String
    let provider: String
    let appID: String?
    let credits: Double?
    let timestamp: String
    let timestampLabel: String
    let inputTokens: Int?
    let outputTokens: Int?
    init(id: String, label: String, provider: String, credits: Double?, timestamp: String, inputTokens: Int? = nil, outputTokens: Int? = nil, appID: String? = nil) {
        self.appID = appID; self.id = id; self.label = label; self.provider = provider; self.credits = credits; self.timestamp = timestamp; self.inputTokens = inputTokens; self.outputTokens = outputTokens; self.timestampLabel = Self.formatTimestamp(timestamp)
    }
    private enum CodingKeys: String, CodingKey { case id, messageId, appId, skillId, type, serverProvider, serverRegion, modelUsed, credits, createdAt, inputTokens, outputTokens }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(String.self, forKey: .id) ?? c.decodeIfPresent(String.self, forKey: .messageId) ?? UUID().uuidString
        let app = try c.decodeIfPresent(String.self, forKey: .appId)
        appID = app
        let skill = try c.decodeIfPresent(String.self, forKey: .skillId)
        let activity = [app, skill].compactMap { $0 }.joined(separator: " | ")
        label = activity.isEmpty ? (try c.decodeIfPresent(String.self, forKey: .type) ?? "Unknown activity") : activity
        let providerParts = [try c.decodeIfPresent(String.self, forKey: .serverProvider), try c.decodeIfPresent(String.self, forKey: .serverRegion)].compactMap { $0 }
        provider = providerParts.isEmpty ? (try c.decodeIfPresent(String.self, forKey: .modelUsed) ?? "—") : providerParts.joined(separator: " / ")
        credits = try c.decodeIfPresent(Double.self, forKey: .credits)
        timestamp = (try? c.decode(String.self, forKey: .createdAt)) ?? (try? c.decode(Double.self, forKey: .createdAt)).map { String($0) } ?? ""
        timestampLabel = Self.formatTimestamp(timestamp)
        inputTokens = try c.decodeIfPresent(Int.self, forKey: .inputTokens)
        outputTokens = try c.decodeIfPresent(Int.self, forKey: .outputTokens)
    }
    var iconName: String {
        guard let appID, ["web", "ai", "news", "videos", "maps", "code", "audio"].contains(appID) else { return "chat" }
        return appID
    }
    var subtitle: String { provider + (timestampLabel.isEmpty ? "" : " - " + timestampLabel) }
    static func formatTimestamp(_ value: String, locale: Locale = .current, timeZone: TimeZone = .current) -> String {
        let date: Date?
        if let number = Double(value), number.isFinite, number > 0 {
            date = Date(timeIntervalSince1970: number > 10_000_000_000 ? number / 1000 : number)
        } else {
            let iso = ISO8601DateFormatter()
            date = iso.date(from: value) ?? { iso.formatOptions.insert(.withFractionalSeconds); return iso.date(from: value) }()
        }
        guard let date else { return "" }
        let formatter = DateFormatter(); formatter.locale = locale; formatter.timeZone = timeZone
        formatter.dateStyle = .medium; formatter.timeStyle = .short
        return formatter.string(from: date)
    }
}

@MainActor
final class ChatSettingsUsageModel: ObservableObject {
    @Published var rows: [ChatSettingsUsageRow] = []
    @Published var total: Double?
    @Published var error: String?
    private var generation = UUID()
    private struct Response: Decodable { let entries: [ChatSettingsUsageRow] }
    private struct Total: Decodable { let totalCredits: Double }
    var hasKnownCredits: Bool { rows.contains { $0.credits != nil } }
    var knownCredits: Double { rows.reduce(0) { $0 + ($1.credits ?? 0) } }
    func loadStatic(rows: [ChatSettingsUsageRow]) {
        generation = UUID(); self.rows = rows; total = nil; error = nil
    }
    func load(chatID: String, accountID: String?, shared: Bool, messages: [Message]) async {
        guard !Task.isCancelled else { return }
        let request = UUID(); generation = request; error = nil
        let local = messages.filter { $0.role == .assistant }.map { ChatSettingsUsageRow(id: $0.id, label: "AI | Ask", provider: $0.modelName ?? "—", credits: nil, timestamp: $0.createdAt) }
        rows = local; total = nil
        guard !shared, let accountID else { return }
        do {
            let fence = UserTasksAccountFence(accountID: accountID)
            try await fence.check()
            let query = "?chat_id=\(UserTasksPaths.escaped(chatID))"
            async let response: Response = APIClient.shared.request(.get, path: "/v1/settings/usage/chat-entries\(query)&limit=500", serverProfile: fence.serverProfile, expectedAccountID: fence.accountID, expectedScope: fence.scope)
            async let sum: Total = APIClient.shared.request(.get, path: "/v1/settings/usage/chat-total\(query)", serverProfile: fence.serverProfile, expectedAccountID: fence.accountID, expectedScope: fence.scope)
            let (nextRows, nextTotal) = try await (response, sum)
            try await fence.check()
            guard request == generation, !Task.isCancelled else { return }
            rows = nextRows.entries; total = nextTotal.totalCredits
        } catch {
            guard request == generation, !Task.isCancelled else { return }
            rows = local; total = nil; self.error = AppStrings.error
        }
    }
    func export() throws -> Data {
        let values: [[String: Any]] = rows.map { row in ["id": row.id, "activity": row.label, "provider": row.provider, "created_at": row.timestamp, "credits": row.credits as Any? ?? NSNull(), "input_tokens": row.inputTokens as Any? ?? NSNull(), "output_tokens": row.outputTokens as Any? ?? NSNull()] }
        func escaped(_ string: String) -> String { "\"" + string.replacingOccurrences(of: "\"", with: "\"\"") + "\"" }
        let csv = "id,activity,provider,created_at,credits,input_tokens,output_tokens\n" + rows.map {
            [$0.id, $0.label, $0.provider, $0.timestamp, $0.credits.map { String($0) } ?? "", $0.inputTokens.map(String.init) ?? "", $0.outputTokens.map(String.init) ?? ""].map(escaped).joined(separator: ",")
        }.joined(separator: "\n")
        let archive = try Archive(data: Data(), accessMode: .create)
        for (name, data) in [("chat-usage.csv", Data(csv.utf8)), ("chat-usage.yml", Data(try Yams.dump(object: values).utf8))] {
            try archive.addEntry(with: name, type: .file, uncompressedSize: Int64(data.count)) { offset, size in data.subdata(in: Int(offset)..<min(Int(offset) + size, data.count)) }
        }
        guard let data = archive.data else { throw CocoaError(.fileWriteUnknown) }
        return data
    }
}
