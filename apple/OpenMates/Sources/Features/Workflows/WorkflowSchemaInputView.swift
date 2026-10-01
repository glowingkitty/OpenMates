// Capability-schema controls for workflow app-skill inputs.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/workflows/WorkflowSchemaFields.svelte
//          frontend/packages/ui/src/components/workflows/WorkflowDateRangeField.svelte
//          frontend/packages/ui/src/components/workflows/WorkflowLocationField.svelte
// CSS:     WorkflowSchemaFields.svelte .schema-field, .field-grid
//          WorkflowDateRangeField.svelte .date-range, .range-modes
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.actions.skill-contract, workflows.control.typed-data

import SwiftUI

struct WorkflowSchemaInputView: View {
    let schema: [String: Any]
    let value: [String: Any]
    let appId: String
    let onChange: ([String: Any]) -> Void
    var path = "input"
    var timezone = TimeZone.current.identifier

    @State private var showAdvanced = false
    @State private var selectedLocationKey: String?
    @State private var mapFullscreen = false

    private var properties: [String: [String: Any]] {
        guard let raw = schema["properties"] as? [String: Any] else { return [:] }
        return raw.compactMapValues { $0 as? [String: Any] }
    }

    private var ui: [String: Any] { schema["x-ui"] as? [String: Any] ?? [:] }
    private var required: Set<String> { Set(schema["required"] as? [String] ?? []) }

    private var dateRangeKeys: (String, String)? {
        let start = ui["start_field"] as? String ?? "start_date"
        let end = ui["end_field"] as? String ?? "end_date"
        guard ui["control"] as? String == "date-range" ||
              appId == "weather" && properties[start] != nil && properties[end] != nil,
              properties[start] != nil, properties[end] != nil else { return nil }
        return (start, end)
    }

    private var fieldKeys: [String] {
        properties.keys.filter { key in
            let metadata = properties[key]?["x-ui"] as? [String: Any] ?? [:]
            guard metadata["hidden"] as? Bool != true else { return false }
            if let (start, end) = dateRangeKeys, key == start || key == end { return false }
            return !isCoordinateField(key)
        }.sorted { lhs, rhs in
            let left = properties[lhs]?["x-ui"] as? [String: Any] ?? [:]
            let right = properties[rhs]?["x-ui"] as? [String: Any] ?? [:]
            let leftRank = left["basic"] as? Bool == true ? 0 : required.contains(lhs) ? 1 : 2
            let rightRank = right["basic"] as? Bool == true ? 0 : required.contains(rhs) ? 1 : 2
            return leftRank == rightRank ? lhs < rhs : leftRank < rightRank
        }
    }

    private var basicKeys: [String] {
        fieldKeys.filter { key in
            let metadata = properties[key]?["x-ui"] as? [String: Any] ?? [:]
            if let basic = metadata["basic"] as? Bool { return basic }
            return required.contains(key) || fieldKeys.firstIndex(of: key).map { $0 < 3 } == true
        }
    }

    private var advancedKeys: [String] { fieldKeys.filter { !basicKeys.contains($0) } }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            ForEach(basicKeys, id: \.self) { key in field(key) }
            if let (start, end) = dateRangeKeys {
                WorkflowDateRangeInput(
                    start: value[start], end: value[end],
                    timezone: timezone,
                    minOffsetDays: ui["min_offset_days"] as? Int ?? 0,
                    maxOffsetDays: ui["max_offset_days"] as? Int ?? 13,
                    onChange: { startValue, endValue in
                        var next = value
                        next[start] = startValue
                        next[end] = endValue
                        onChange(next)
                    }
                )
            }
            if !advancedKeys.isEmpty {
                Button {
                    showAdvanced.toggle()
                } label: {
                    Text(AppStrings.workflowBuilder(showAdvanced ? .show_basic_fields : .show_all_fields))
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("workflow-show-all-fields")
                if showAdvanced {
                    ForEach(advancedKeys, id: \.self) { key in field(key) }
                }
            }
        }
        .sheet(isPresented: Binding(
            get: { selectedLocationKey != nil },
            set: { if !$0 { selectedLocationKey = nil } }
        )) {
            if let key = selectedLocationKey {
                ComposerLocationOverlay(isFullscreen: $mapFullscreen, onShare: { selection in
                    applyLocation(selection, key: key)
                    selectedLocationKey = nil
                }, onCancel: { selectedLocationKey = nil })
                .frame(minHeight: 520)
            }
        }
    }

    @ViewBuilder
    private func field(_ key: String) -> some View {
        if let spec = properties[key] {
            let kind = spec["type"] as? String ?? "string"
            let label = spec["title"] as? String ?? WorkflowValueView.displayLabel(key)
            let metadata = spec["x-ui"] as? [String: Any] ?? [:]
            VStack(alignment: .leading, spacing: .spacing2) {
                if kind != "boolean" {
                    Text(label + (required.contains(key) ? " *" : ""))
                        .font(.omP.weight(.semibold))
                        .foregroundStyle(Color.fontPrimary)
                }
                if locationConfig(for: key, metadata: metadata) != nil {
                    Button {
                        selectedLocationKey = key
                    } label: {
                        HStack(spacing: .spacing2) {
                            Icon("maps", size: 18)
                            Text(value[key] as? String ?? label)
                                .lineLimit(1)
                        }
                        .font(.omP)
                        .foregroundStyle(Color.fontPrimary)
                        .padding(.horizontal, .spacing3)
                        .frame(minHeight: 40)
                        .background(Color.grey10)
                        .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("workflow-location-\(path)-\(key)")
                } else if let choices = spec["enum"] as? [String], !choices.isEmpty {
                    Picker(label, selection: Binding(
                        get: { value[key] as? String ?? choices[0] },
                        set: { change(key, to: $0) }
                    )) {
                        ForEach(choices, id: \.self) { choice in Text(choice).tag(choice) }
                    }
                    .pickerStyle(.menu)
                    .accessibilityIdentifier("workflow-input-\(path)-\(key)")
                } else if kind == "boolean" {
                    Toggle(label, isOn: Binding(
                        get: { value[key] as? Bool ?? false },
                        set: { change(key, to: $0) }
                    ))
                    .accessibilityIdentifier("workflow-input-\(path)-\(key)")
                } else if kind == "object" {
                    WorkflowSchemaInputView(
                        schema: spec, value: value[key] as? [String: Any] ?? [:],
                        appId: appId, onChange: { change(key, to: $0) },
                        path: "\(path)-\(key)", timezone: timezone
                    )
                } else if kind == "array", let items = spec["items"] as? [String: Any],
                          items["type"] as? String == "object" {
                    objectArray(key: key, itemSchema: items)
                } else {
                    TextField(label, text: Binding(
                        get: { value[key].map { String(describing: $0) } ?? "" },
                        set: { raw in
                            if kind == "integer" { change(key, to: Int(raw)) }
                            else if kind == "number" { change(key, to: Double(raw)) }
                            else { change(key, to: raw) }
                        }
                    ))
                    .textFieldStyle(OMTextFieldStyle())
                    .accessibilityIdentifier("workflow-input-\(path)-\(key)")
                }
            }
        }
    }

    @ViewBuilder
    private func objectArray(key: String, itemSchema: [String: Any]) -> some View {
        let rows = value[key] as? [[String: Any]] ?? [[:]]
        ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
            VStack(alignment: .leading, spacing: .spacing3) {
                Text("\(WorkflowValueView.displayLabel(key)) \(index + 1)")
                    .font(.omP.weight(.semibold))
                WorkflowSchemaInputView(
                    schema: itemSchema, value: row, appId: appId,
                    onChange: { changed in
                        var nextRows = rows
                        nextRows[index] = changed
                        change(key, to: nextRows)
                    }, path: "\(path)-\(key)-\(index)", timezone: timezone
                )
            }
            .padding(.spacing3)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius5))
        }
    }

    private func change(_ key: String, to updated: Any?) {
        var next = value
        next[key] = updated
        onChange(next)
    }

    private func isCoordinateField(_ key: String) -> Bool {
        for (fieldKey, spec) in properties where fieldKey != key {
            let metadata = spec["x-ui"] as? [String: Any] ?? [:]
            if metadata["control"] as? String == "location",
               [metadata["latitude_field"] as? String, metadata["longitude_field"] as? String]
                .contains(key) { return true }
        }
        if appId == "weather", properties["location"] != nil { return key == "latitude" || key == "longitude" }
        if appId == "events", properties["location"] != nil { return key == "lat" || key == "lon" }
        return false
    }

    private func locationConfig(for key: String, metadata: [String: Any]) -> (String?, String?, String?)? {
        if metadata["control"] as? String == "location" {
            return (metadata["latitude_field"] as? String,
                    metadata["longitude_field"] as? String,
                    metadata["city_field"] as? String)
        }
        if appId == "weather", key == "location", properties["latitude"] != nil {
            return ("latitude", "longitude", nil)
        }
        if appId == "events", key == "location", properties["lat"] != nil {
            return ("lat", "lon", nil)
        }
        if appId == "home", key == "query" { return (nil, nil, nil) }
        return nil
    }

    private func applyLocation(_ selection: ComposerLocationSelection, key: String) {
        let metadata = properties[key]?["x-ui"] as? [String: Any] ?? [:]
        guard let config = locationConfig(for: key, metadata: metadata) else { return }
        var next = value
        next[key] = selection.name
        if let latitude = config.0 { next[latitude] = selection.latitude }
        if let longitude = config.1 { next[longitude] = selection.longitude }
        if let city = config.2 { next[city] = selection.name }
        for field in metadata["clear_fields"] as? [String] ?? [] { next.removeValue(forKey: field) }
        onChange(next)
    }
}

private struct WorkflowDateRangeInput: View {
    let start: Any?
    let end: Any?
    let timezone: String
    let minOffsetDays: Int
    let maxOffsetDays: Int
    let onChange: (Any, Any) -> Void

    @State private var showingSpecific = false
    @State private var selectedStart = Date()
    @State private var selectedEnd = Date()

    private var calendar: Calendar {
        var result = Calendar(identifier: .gregorian)
        result.timeZone = TimeZone(identifier: timezone) ?? .current
        return result
    }

    private var today: Date { calendar.startOfDay(for: Date()) }
    private var bounds: ClosedRange<Date> {
        let minimum = calendar.date(byAdding: .day, value: minOffsetDays, to: today) ?? today
        let maximum = calendar.date(byAdding: .day, value: maxOffsetDays, to: today) ?? today
        return minimum...max(minimum, maximum)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(AppStrings.workflowBuilder(.date_range))
                .font(.omP.weight(.semibold))
            HStack(spacing: .spacing2) {
                if minOffsetDays == 0 && maxOffsetDays >= 13 {
                    presetButton(.today, active: relativeToken(start) == "today") {
                        onChange(["$date": "today", "format": "date"],
                                 ["$date": "today", "format": "date"])
                        showingSpecific = false
                    }
                    presetButton(.next_seven_days,
                                 active: relativeToken(start) == "next_seven_days_start") {
                        onChange(["$date": "next_seven_days_start", "format": "date"],
                                 ["$date": "next_seven_days_end", "format": "date"])
                        showingSpecific = false
                    }
                }
                presetButton(.specific_dates, active: showingSpecific) {
                    showingSpecific = true
                    let startDate = min(max(selectedStart, bounds.lowerBound), bounds.upperBound)
                    let endDate = min(max(selectedEnd, startDate), bounds.upperBound)
                    onChange(isoDate(startDate), isoDate(endDate))
                }
            }
            if showingSpecific {
                DatePicker(AppStrings.workflowBuilder(.date_range),
                           selection: $selectedStart, in: bounds, displayedComponents: .date)
                    .labelsHidden()
                    .onChange(of: selectedStart) { _, _ in
                        onChange(isoDate(selectedStart), isoDate(max(selectedStart, selectedEnd)))
                    }
                DatePicker(AppStrings.workflowBuilder(.date_range),
                           selection: $selectedEnd, in: bounds, displayedComponents: .date)
                    .labelsHidden()
                    .onChange(of: selectedEnd) { _, _ in
                        onChange(isoDate(min(selectedStart, selectedEnd)), isoDate(selectedEnd))
                    }
            }
        }
        .accessibilityIdentifier("workflow-date-range-field")
        .onAppear {
            if let parsedStart = parsedDate(start), let parsedEnd = parsedDate(end) {
                selectedStart = min(max(parsedStart, bounds.lowerBound), bounds.upperBound)
                selectedEnd = min(max(parsedEnd, selectedStart), bounds.upperBound)
                showingSpecific = true
            }
        }
    }

    private func presetButton(_ key: AppStrings.WorkflowBuilderCopy, active: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) { Text(AppStrings.workflowBuilder(key)).font(.omP) }
            .buttonStyle(.plain)
            .foregroundStyle(active ? Color.fontButton : Color.fontSecondary)
            .padding(.horizontal, .spacing3)
            .frame(minHeight: 40)
            .background(active ? AnyShapeStyle(LinearGradient.primary) : AnyShapeStyle(Color.grey10))
            .clipShape(Capsule())
    }

    private func relativeToken(_ value: Any?) -> String? {
        (value as? [String: Any])?["$date"] as? String
    }

    private func isoDate(_ value: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: value)
    }

    private func parsedDate(_ value: Any?) -> Date? {
        guard let raw = value as? String, raw.count >= 10 else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.date(from: String(raw.prefix(10)))
    }
}
