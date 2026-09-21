import SwiftUI

// Reachable composer detail surface, not the whole settings navigation system.
// Web AiAskModelDetails.svelte; measured phone body323, padding12, rowgap12.
struct NativeComposerModelDetails: View {
    let model: NativeModelCatalog.Model
    let onClose: () -> Void
    @ObservedObject private var runtime = NativeModelCatalogRuntime.shared
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack { Text(model.name).font(.omH3).foregroundStyle(Color.fontPrimary); Spacer()
                    Button(action: onClose) { Icon("close", size: 24) }.buttonStyle(.plain).accessibilityLabel(AppStrings.close) }
                if let description = model.description, !description.isEmpty {
                    Text(description).font(.omP).foregroundStyle(Color.fontSecondary)
                }
                if runtime.canEditPreferences {
                    toggle(model.name, enabled: !runtime.disabledPreferences.disabled_ai_models.contains(model.id), id: "model-enabled") {
                        runtime.setModel(model.id, enabled: $0)
                    }
                }
                section("common.details") {
                    HStack(spacing: 12) {
                        NativeModelCapabilityTile(level: model.capability_level ?? "medium").scaleEffect(2).frame(width: 32, height: 32)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.capability")).font(.omP)
                            Text(LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.capability_" + (model.capability_level ?? "medium"))).font(.omSmall)
                        }
                    }
                    row("settings.ai_ask.ai_ask_model_details.origin", value: runtime.catalog?.providers.first(where: { $0.id == model.provider_id })?.companyName ?? model.provider_name, icon: "openmates")
                    if let date = model.release_date { row("settings.ai_ask.ai_ask_model_details.release_date", value: formattedDate(date), icon: "time") }
                    row("settings.ai_ask.ai_ask_model_details.input_types", value: (model.input_types ?? []).map(mediaLabel).joined(separator: ", "), icon: "text")
                    row("settings.ai_ask.ai_ask_model_details.output_types", value: (model.output_types ?? []).map(mediaLabel).joined(separator: ", "), icon: "document")
                }
                if let pricing = model.pricing {
                    section("common.pricing") {
                        if let input = pricing.input_tokens_per_credit { row("settings.ai_ask.ai_ask_model_details.text_input", value: price(input), icon: "coins") }
                        if let output = pricing.output_tokens_per_credit { row("settings.ai_ask.ai_ask_model_details.text_output", value: price(output), icon: "coins") }
                    }
                }
                section("settings.app_store.skills.examples") {
                    row("settings.ai_ask.ai_ask_settings.simple_requests", value: LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.simple_requests_description"), icon: "chat")
                    row("settings.ai_ask.ai_ask_settings.complex_requests", value: LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.complex_requests_description"), icon: "chat")
                }
                section("common.provider") {
                    ForEach(model.servers, id: \.id) { server in
                        VStack(alignment: .leading, spacing: 4) {
                            if runtime.canEditPreferences {
                                toggle(server.name ?? server.id,
                                    enabled: !(runtime.disabledPreferences.disabled_ai_servers[model.id] ?? []).contains(server.id),
                                    id: "model-server-" + server.id) { runtime.setServer(server.id, model: model.id, enabled: $0) }
                            } else { Text(server.name ?? server.id).font(.omP) }
                            Text(server.region ?? "").font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                    }
                }
                if let error = runtime.error { Text(error).font(.omSmall).foregroundStyle(Color.error) }
            }.frame(maxWidth: 323).padding(12).frame(maxWidth: .infinity)
        }.background(Color.grey0).accessibilityIdentifier("composer-model-details")
    }
    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(LocalizationManager.shared.text(title)).font(.omP).fontWeight(.bold)
            content()
        }
    }
    private func row(_ title: String, value: String, icon: String) -> some View {
        HStack(spacing: 12) {
            Icon(icon, size: 24).foregroundStyle(Color(hex: 0x4867cd))
            VStack(alignment: .leading, spacing: 4) {
                Text(LocalizationManager.shared.text(title)).font(.omP)
                Text(value).font(.omSmall).foregroundStyle(Color.fontSecondary)
            }
            Spacer(minLength: 0)
        }
    }
    private func toggle(_ label: String, enabled: Bool, id: String, action: @escaping (Bool) -> Void) -> some View {
        HStack(spacing: 8) {
            Text(label).font(.omP); Spacer()
            OMToggle(isOn: Binding(get: { enabled }, set: action), accessibilityIdentifier: id)
        }
    }
    private func formattedDate(_ raw: String) -> String {
        ModelReleaseDateText.string(raw)
    }
    private func price(_ tokens: Double) -> String {
        "1 " + LocalizationManager.shared.text("common.credits") + " " + LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.per") + " " + tokens.formatted(.number.grouping(.never)) + " " + LocalizationManager.shared.text("settings.ai_ask.ai_ask_settings.tokens")
    }
    private func mediaLabel(_ type: String) -> String {
        switch type {
        case "image": return LocalizationManager.shared.text("common.images")
        case "audio": return LocalizationManager.shared.text("common.audio")
        case "video": return LocalizationManager.shared.text("settings.ai_ask.ai_ask_model_details.input_type_video")
        default: return LocalizationManager.shared.text("settings.ai_ask.ai_ask_model_details.input_type_text")
        }
    }
}

@MainActor private enum ModelReleaseDateText {
    static let parser: DateFormatter = {
        let value = DateFormatter(); value.locale = Locale(identifier: "en_US_POSIX")
        value.timeZone = TimeZone(secondsFromGMT: 0); value.dateFormat = "yyyy-MM-dd"; return value
    }()
    static var cache: [String: String] = [:]
    static func string(_ raw: String) -> String {
        let key = Locale.current.identifier + ":" + raw
        if let cached = cache[key] { return cached }
        guard let date = parser.date(from: raw) else { return raw }
        let result = date.formatted(.dateTime.year().month(.abbreviated))
        if cache.count >= 256 { cache.removeAll(keepingCapacity: true) }
        cache[key] = result; return result
    }
}
