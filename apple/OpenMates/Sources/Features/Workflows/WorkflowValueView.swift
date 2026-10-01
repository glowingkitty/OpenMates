// Readable, bounded presentation of retained workflow values. The native
// workspace never exposes raw JSON, credentials, or opaque access material.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/workflows/WorkflowValueView.svelte
//          frontend/packages/ui/src/components/workflows/workflowValuePresentation.ts
// CSS:     WorkflowValueView.svelte .workflow-value, .value-fields,
//          .result-carousel, .result-navigation
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.control.typed-data, workflows.results.selective-embeds

import SwiftUI

struct WorkflowValueView: View {
    let value: Any?
    var title: String? = nil
    var appId: String = ""
    var depth: Int = 0
    var showDetails = false

    @State private var selectedIndex = 0
    @State private var detailsExpanded = false

    private static let maximumDepth = 4
    private static let maximumItems = 30
    private static let privateKeys: Set<String> = [
        "access_token", "refresh_token", "api_key", "secret", "password",
        "authorization", "cookie", "aes_key", "private_key", "id", "type",
        "hash", "source_id", "embed_id", "embed_ids", "delivery_id",
        "message_id", "run_id", "workflow_id", "node_id", "task_id",
        "app_id", "skill_id", "canonical_url", "dispatches",
        "output_schema", "input_schema", "usage", "raw", "debug",
        "metadata", "provider_metadata", "error", "errors",
        "error_summary", "query_id", "request_id"
    ]

    private var unwrapped: Any? {
        let raw = (value as? AnyCodable)?.value ?? value
        guard let text = raw as? String else { return raw }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (trimmed.hasPrefix("{") || trimmed.hasPrefix("[")),
              let data = trimmed.data(using: .utf8),
              let structured = try? JSONSerialization.jsonObject(with: data),
              structured is [String: Any] || structured is [Any]
        else { return raw }
        return structured
    }

    var body: some View {
        Group {
            if depth > Self.maximumDepth {
                Text(AppStrings.workflowBuilder(.output_type_object))
                    .foregroundStyle(Color.fontSecondary)
            } else if let dictionary = dictionaryValue {
                if let kind = resultKind(dictionary) {
                    resultBody(dictionary, kind: kind)
                } else {
                    dictionaryBody(dictionary)
                }
            } else if let items = arrayValue {
                arrayBody(items)
            } else if let url = scalarURL {
                Link(url.absoluteString, destination: url)
                    .font(.omP)
                    .foregroundStyle(Color.buttonPrimary)
            } else if let scalar = scalarText {
                Text(scalar)
                    .font(.omP)
                    .foregroundStyle(Color.fontPrimary)
                    .textSelection(.enabled)
            } else {
                Text(AppStrings.workflowBuilder(.unavailable))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }
        }
        .accessibilityIdentifier("workflow-value-view")
    }

    @ViewBuilder
    private func dictionaryBody(_ dictionary: [String: Any]) -> some View {
        let keys = dictionary.keys
            .filter { !Self.privateKeys.contains($0.lowercased())
                && !$0.hasPrefix("_")
                && !$0.hasPrefix("encrypted_")
                && !$0.hasPrefix("hashed_") }
            .sorted()
            .prefix(Self.maximumItems)
        if keys.isEmpty {
            Text(AppStrings.workflowBuilder(.output_type_object))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
        } else {
            VStack(alignment: .leading, spacing: .spacing3) {
                ForEach(Array(keys), id: \.self) { key in
                    HStack(alignment: .top, spacing: .spacing4) {
                        Text(Self.displayLabel(key))
                            .font(.omSmall.weight(.semibold))
                            .foregroundStyle(Color.fontSecondary)
                            .frame(maxWidth: 132, alignment: .leading)
                        WorkflowValueView(value: dictionary[key], title: key, appId: appId,
                                          depth: depth + 1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func arrayBody(_ items: [Any]) -> some View {
        if items.isEmpty {
            Text(AppStrings.workflowBuilder(.output_empty_list))
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
        } else if let results = resultItems(items), !results.isEmpty {
            VStack(alignment: .leading, spacing: .spacing3) {
                HStack(spacing: .spacing3) {
                    Button {
                        selectedIndex = max(0, selectedIndex - 1)
                    } label: {
                        Icon("chevron-left", size: 18)
                    }
                    .disabled(selectedIndex == 0)
                    .accessibilityLabel(AppStrings.workflowBuilder(.previous_result))

                    Text(AppStrings.workflowResultPosition(current: min(selectedIndex + 1, results.count), total: results.count))
                        .font(.omSmall.weight(.semibold))
                        .foregroundStyle(Color.fontSecondary)

                    Button {
                        selectedIndex = min(results.count - 1, selectedIndex + 1)
                    } label: {
                        Icon("chevron-right", size: 18)
                    }
                    .disabled(selectedIndex >= results.count - 1)
                    .accessibilityLabel(AppStrings.workflowBuilder(.next_result))
                }
                .frame(maxWidth: .infinity, alignment: .center)

                WorkflowValueView(value: results[min(selectedIndex, results.count - 1)], appId: appId,
                                  depth: depth + 1, showDetails: true)
                    .padding(.spacing4)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
            }
        } else {
            VStack(alignment: .leading, spacing: .spacing2) {
                ForEach(Array(items.prefix(Self.maximumItems).enumerated()), id: \.offset) { _, item in
                    WorkflowValueView(value: item, appId: appId, depth: depth + 1)
                }
            }
        }
    }

    private var dictionaryValue: [String: Any]? {
        if let dictionary = unwrapped as? [String: Any] { return dictionary }
        if let dictionary = unwrapped as? [String: AnyCodable] {
            return dictionary.mapValues(\.value)
        }
        return nil
    }

    private var arrayValue: [Any]? {
        if let items = unwrapped as? [Any] { return items }
        if let items = unwrapped as? [AnyCodable] { return items.map(\.value) }
        return nil
    }

    private func resultItems(_ items: [Any]) -> [[String: Any]]? {
        let records = items.compactMap { $0 as? [String: Any] }
        guard records.count == items.count else { return nil }
        let flattened = records.flatMap { record -> [[String: Any]] in
            if let children = record["results"] as? [[String: Any]] { return children }
            return [record]
        }
        return title == "results" || flattened.contains(where: { resultKind($0) != nil })
            ? flattened : nil
    }

    private var scalarText: String? {
        guard let value = unwrapped else { return nil }
        if value is NSNull { return nil }
        if let value = value as? Bool {
            return AppStrings.workflowBuilder(value ? .true : .false)
        }
        if let value = value as? String {
            if (title?.lowercased().contains("date") == true || title?.lowercased().contains("time") == true),
               value.count == 10, value[value.index(value.startIndex, offsetBy: 4)] == "-" {
                let parser = DateFormatter()
                parser.locale = Locale(identifier: "en_US_POSIX")
                parser.timeZone = TimeZone(secondsFromGMT: 0)
                parser.dateFormat = "yyyy-MM-dd"
                if let date = parser.date(from: value) {
                    let display = DateFormatter()
                    display.locale = .current
                    display.timeZone = TimeZone(secondsFromGMT: 0)
                    display.dateStyle = .medium
                    return display.string(from: date)
                }
            }
            return value
        }
        if let value = value as? Int { return value.formatted() }
        if let value = value as? Double { return value.formatted() }
        return nil
    }

    private var scalarURL: URL? {
        guard let raw = unwrapped as? String, !raw.contains(where: \.isWhitespace),
              let url = URL(string: raw),
              ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
              url.host != nil
        else { return nil }
        return url
    }

    private enum ResultKind {
        case fitness, event, home
    }

    private func resultKind(_ item: [String: Any]) -> ResultKind? {
        if appId == "fitness", item["name"] != nil || item["venue_name"] != nil
            || item["appointment_id"] != nil { return .fitness }
        guard item["title"] != nil else { return nil }
        if item["date_start"] != nil || item["type"] as? String == "event_result" {
            return .event
        }
        if item["price_label"] != nil || item["size_sqm"] != nil
            || item["type"] as? String == "home_listing" { return .home }
        return nil
    }

    @ViewBuilder
    private func resultBody(_ item: [String: Any], kind: ResultKind) -> some View {
        let data = item.mapValues { AnyCodable($0) }
        VStack(alignment: .leading, spacing: .spacing3) {
            Button { detailsExpanded.toggle() } label: {
                switch kind {
                case .fitness:
                    WorkflowFitnessResultCard(data: data)
                case .event:
                    EventResultCard(event: EventResultSummary(embedId: nil, data: data))
                case .home:
                    HomeListingRenderer(data: data, mode: .preview)
                }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("workflow-result-card")
            if showDetails || detailsExpanded {
                dictionaryBody(item)
                    .padding(.spacing4)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
            }
        }
    }

    static func displayLabel(_ key: String) -> String {
        key.replacingOccurrences(of: "_", with: " ")
            .replacingOccurrences(of: "-", with: " ")
            .split(separator: " ")
            .map { $0.capitalized }
            .joined(separator: " ")
    }
}

private struct WorkflowFitnessResultCard: View {
    let data: [String: AnyCodable]

    private var title: String {
        (data["name"]?.value as? String) ?? (data["title"]?.value as? String)
            ?? (data["venue_name"]?.value as? String) ?? ""
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            FitnessResultEmbedRenderer(data: data, mode: .preview)
                .padding(.spacing5)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            HStack(spacing: .spacing2) {
                AppIconView(appId: "fitness", size: 60)
                Text(title)
                    .font(.omP.weight(.bold))
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
                Spacer(minLength: .spacing3)
            }
            .frame(height: 60)
            .background(Color.grey25)
            .clipShape(Capsule())
        }
        .frame(width: 300, height: 200)
        .background(Color.grey20)
        .clipShape(RoundedRectangle(cornerRadius: 30))
        .shadow(color: .black.opacity(0.12), radius: 16, x: 0, y: 6)
    }
}
