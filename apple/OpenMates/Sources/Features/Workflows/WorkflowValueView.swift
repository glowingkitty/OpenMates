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
    @State private var measuredWidth: CGFloat = 0

    private static let maximumDepth = 4
    private static let maximumItems = 30
    nonisolated static let privateKeys: Set<String> = [
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
                } else if depth == 0 {
                    dictionaryBody(dictionary)
                } else {
                    DisclosureGroup(AppStrings.localized("workflows.builder.details")) {
                        dictionaryBody(dictionary)
                    }
                    .font(.omP)
                    .accessibilityIdentifier("workflow-value-details")
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
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { measuredWidth = $0 }
        .accessibilityElement(children: .contain)
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
                    let layout = measuredWidth > 550
                        ? AnyLayout(HStackLayout(alignment: .top, spacing: 13))
                        : AnyLayout(VStackLayout(alignment: .leading, spacing: 3))
                    layout {
                        Text(Self.displayLabel(key))
                            .font(.omSmall.weight(.semibold))
                            .foregroundStyle(Color.fontSecondary)
                            .frame(maxWidth: measuredWidth > 550 ? 132 : .infinity, alignment: .leading)
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
            let index = min(max(0, selectedIndex), results.count - 1)
            VStack(alignment: .leading, spacing: .spacing3) {
                HStack(spacing: .spacing3) {
                    Button {
                        selectedIndex = max(0, index - 1)
                    } label: {
                        Icon("back", size: .iconSizeMd)
                            .foregroundStyle(Color.fontPrimary)
                            .frame(width: 42, height: 42)
                            .background(Color.grey30, in: Circle())
                            .contentShape(Circle())
                    }
                    .disabled(index == 0)
                    .opacity(index == 0 ? 0.5 : 1)
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("workflow-result-previous")
                    .accessibilityLabel(AppStrings.workflowBuilder(.previous_result))

                    Text(AppStrings.workflowResultPosition(current: index + 1, total: results.count))
                        .font(.omSmall.weight(.semibold))
                        .foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("workflow-result-position")

                    Button {
                        selectedIndex = min(results.count - 1, index + 1)
                    } label: {
                        Icon("back", size: .iconSizeMd)
                            .rotationEffect(.degrees(180))
                            .foregroundStyle(Color.fontPrimary)
                            .frame(width: 42, height: 42)
                            .background(Color.grey30, in: Circle())
                            .contentShape(Circle())
                    }
                    .disabled(index == results.count - 1)
                    .opacity(index == results.count - 1 ? 0.5 : 1)
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("workflow-result-next")
                    .accessibilityLabel(AppStrings.workflowBuilder(.next_result))
                }
                .frame(maxWidth: .infinity, alignment: .center)

                WorkflowValueView(value: results[index], appId: appId,
                                  depth: depth + 1, showDetails: true)
                    // Web gives each selected result its own path/preview identity.
                    .id(index)
                    .padding(.spacing4)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
            }
        } else {
            DisclosureGroup(AppStrings.localized("workflows.builder.output_item_count")
                .replacingOccurrences(of: "{count}", with: String(items.count))) {
                ScrollView {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        ForEach(Array(items.prefix(Self.maximumItems).enumerated()), id: \.offset) { _, item in
                            WorkflowValueView(value: item, appId: appId, depth: depth + 1)
                                .padding(.spacing4)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(Color.grey0, in: RoundedRectangle(cornerRadius: 10))
                        }
                    }
                }
                .frame(maxHeight: 448)
            }
            .font(.omP)
            .accessibilityIdentifier("workflow-value-list")
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
        case fitness, event, home, news
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
        if item["url"] != nil, appId == "news" || ["news_result", "news_article"].contains(item["type"] as? String ?? "") { return .news }
        return nil
    }

    @ViewBuilder
    private func resultBody(_ item: [String: Any], kind: ResultKind) -> some View {
        let data = item.mapValues { AnyCodable($0) }
        VStack(alignment: .leading, spacing: .spacing3) {
            if kind == .news {
                // Ephemeral in-memory preview only: never inserted into embed storage.
                EmbedPreviewCard(embed: EmbedRecord(id: "workflow-value-preview", type: "web-website", status: .finished,
                    data: .raw(data), parentEmbedId: nil, appId: "news", skillId: "article", embedIds: nil, createdAt: nil),
                    onTap: { detailsExpanded.toggle() })
                    .accessibilityIdentifier("workflow-result-card")
            } else {
            Button { detailsExpanded.toggle() } label: {
                switch kind {
                case .fitness:
                    WorkflowFitnessResultCard(data: data)
                case .event:
                    EventResultCard(event: EventResultSummary(embedId: nil, data: data))
                case .home:
                    HomeListingRenderer(data: data, mode: .preview)
                case .news:
                    EmptyView()
                }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("workflow-result-card")
            }
            if showDetails || detailsExpanded {
                dictionaryBody(item)
                    .padding(.spacing4)
                    .background(Color.grey10)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("workflow-result-fields")
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

// WorkflowOutputFields.svelte / WorkflowOutputField.svelte: declared examples
// have type badges and progressive fields; a completed Test uses readable values.
enum WorkflowOutputPresentation {
    static func fields(_ properties: [String: Any]) -> (basic: [String], advanced: [String]) {
        let diagnostics: Set<String> = ["summary", "warning", "warnings", "partial", "is_partial", "status"]
        let aliases: Set<String> = ["articles", "events", "listings"]
        let eligible = properties.keys.sorted().filter { key in
            let ui = (properties[key] as? [String: Any])?["x-ui"] as? [String: Any] ?? [:]
            return ui["hidden"] as? Bool != true && !WorkflowValueView.privateKeys.contains(key)
                && !diagnostics.contains(key) && !key.hasPrefix("_") && !key.hasPrefix("encrypted_")
                && !key.hasPrefix("hashed_") && !key.hasSuffix("_id") && !key.hasSuffix("_ids")
                && !(properties["results"] != nil && aliases.contains(key))
        }
        func ui(_ key: String) -> [String: Any] { (properties[key] as? [String: Any])?["x-ui"] as? [String: Any] ?? [:] }
        let explicit = eligible.filter { ui($0)["basic"] as? Bool == true }
        let hasSelection = eligible.contains { ui($0)["basic"] is Bool }
        let preferred: Set<String> = ["result", "results", "answer", "text", "content", "result_count", "count", "title", "name", "date_start", "start_time", "start_date", "start", "location", "address", "url", "link", "value", "matched", "forecast", "forecast_day", "forecast_days", "temperature", "rain_probability", "rain_expected", "rain_periods", "rain_summary", "max_temperature_c", "min_temperature_c", "condition"]
        let prioritized = explicit + eligible.filter { ui($0)["basic"] == nil && preferred.contains($0) }
        let basic = hasSelection ? explicit : Array((prioritized.isEmpty ? eligible : prioritized).prefix(4))
        return (basic, eligible.filter { !basic.contains($0) })
    }

    static func example(_ schema: [String: Any], depth: Int = 0) -> Any? {
        if let value = schema["example"] { return value }
        if let values = schema["examples"] as? [Any], let value = values.first { return value }
        if let value = schema["default"] { return value }
        guard depth < 8 else { return nil }
        if schema["type"] as? String == "object", let properties = schema["properties"] as? [String: Any] {
            let values = properties.compactMapValues { field in
                (field as? [String: Any]).flatMap { example($0, depth: depth + 1) }
            }
            return values.isEmpty ? nil : values
        }
        if schema["type"] as? String == "array", let item = schema["items"] as? [String: Any],
           let value = example(item, depth: depth + 1) { return [value] }
        return nil
    }

    static func type(_ schema: [String: Any]) -> String {
        if (schema["format"] as? String)?.contains("date") == true { return "date" }
        switch schema["type"] as? String {
        case "array": return "list"
        case "integer", "number": return "number"
        case "boolean": return "boolean"
        case "object": return "object"
        default: return "text"
        }
    }
}

struct WorkflowOutputFieldsView: View {
    let properties: [String: Any]
    var appId = ""
    @State private var showAll = false

    var body: some View {
        let fields = WorkflowOutputPresentation.fields(properties)
        VStack(alignment: .leading, spacing: 16) {
            ForEach(showAll ? fields.basic + fields.advanced : fields.basic, id: \.self) { key in
                WorkflowOutputFieldView(name: key, schema: properties[key] as? [String: Any] ?? [:], appId: appId)
            }
            if !fields.advanced.isEmpty {
                Button(AppStrings.workflowBuilder(showAll ? .show_basic_fields : .show_all_fields)) { showAll.toggle() }
                    .buttonStyle(.plain)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity)
                    .accessibilityIdentifier("workflow-output-show-all")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-output-fields")
    }
}

private struct WorkflowOutputFieldView: View {
    let name: String
    let schema: [String: Any]
    let appId: String
    @State private var expanded = false
    @State private var measuredWidth: CGFloat = 0

    private var type: String { WorkflowOutputPresentation.type(schema) }
    private var color: Color { type == "number" ? .error : type == "date" ? .warning : Color(hex: 0x4867CD) }
    private var icon: String {
        if type == "date" { return "lucide-calendar-days" }
        if ["location", "address"].contains(name) { return "lucide-map-pin" }
        if name.contains("count") || type == "number" { return "lucide-hash" }
        if name.contains("url") || name.contains("link") { return "lucide-link" }
        switch type {
        case "list": return "lucide-list"
        case "object": return "lucide-braces"
        case "boolean": return "lucide-toggle-left"
        default: return "lucide-type"
        }
    }

    private var typeBadge: some View {
        Text(AppStrings.localized("workflows.builder.output_type_\(type)"))
            .font(.omSmall)
            .padding(.horizontal, 5).padding(.vertical, 2)
            .foregroundStyle(Color.fontButton)
            .background(color, in: RoundedRectangle(cornerRadius: 3))
            .accessibilityIdentifier("workflow-output-type")
    }

    private var fieldName: some View {
        HStack(alignment: .top, spacing: 4) {
            Icon(icon, size: 18).foregroundStyle(Color.fontSecondary)
            Text(schema["title"] as? String ?? WorkflowValueView.displayLabel(name))
                .font(.omP.weight(.semibold))
        }
    }

    @ViewBuilder private var exampleValue: some View {
        let value = WorkflowOutputPresentation.example(schema)
        if let items = value as? [Any], !items.isEmpty {
            Button { expanded.toggle() } label: {
                Icon(expanded ? "chevron-up" : "dropdown", size: 22)
                    .frame(width: 32, height: 32)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.localized("workflows.builder.details"))
            .accessibilityIdentifier("workflow-output-list-disclosure")
        } else {
            WorkflowValueView(value: value, title: name, appId: appId)
        }
    }

    var body: some View {
        let items = WorkflowOutputPresentation.example(schema) as? [Any]
        VStack(alignment: .leading, spacing: 8) {
            if measuredWidth > 730 {
                HStack(alignment: .top, spacing: 10) {
                    typeBadge.frame(width: 88, alignment: .leading)
                    fieldName.frame(maxWidth: .infinity, alignment: .leading)
                    exampleValue.frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                HStack(alignment: .center, spacing: 8) {
                    VStack(alignment: .leading, spacing: 4) {
                        typeBadge
                        fieldName
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    exampleValue.frame(width: 108, alignment: .leading)
                }
            }
            if expanded, let first = items?.first {
                // The web example disclosure inspects the first declared item.
                WorkflowValueView(value: first, appId: appId)
                    .padding(13)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.grey10, in: RoundedRectangle(cornerRadius: 5))
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("workflow-output-list-details")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-output-field")
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { measuredWidth = $0 }
    }
}
