// Composer model selector using the generated web model catalog.
// Web: enter_message/ComposerModelSelector.svelte, Toggle.svelte,
// settings/elements/SettingsCapabilityScale.svelte. Actual preview inspected
// at phone width: 41pt rows, 28pt provider tiles, 49x29 toggle, 4pt menu inset.
// Selection/persistence and model details belong to the production host.
import SwiftUI

struct NativeComposerModelSelector: View {
    let catalog: NativeModelCatalog
    let routing: ModelRoutingCatalog
    let selection: String
    let ready: Bool
    let viewportWidth: CGFloat
    let onSelect: (String) -> Void
    let onOpenDetails: (NativeModelCatalog.Model) -> Void
    @State private var isOpen = false
    @State private var activeProvider: String?
    @State private var showAllProviders = false
    @State private var displayError: String?
    @State private var orderedModels: [NativeModelCatalog.Model] = []
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var selectedModel: NativeModelCatalog.Model? {
        catalog.models.first { value($0) == selection && routing.usable(value($0)) }
    }
    private var providers: [NativeModelCatalog.ProviderDisplay] {
        catalog.pickerProviders.filter { provider in
            catalog.models.contains { $0.provider_id == provider.id && routing.usable(value($0)) }
        }
    }
    private var selectedLabel: String {
        ready ? selectedModel?.name ?? text("settings.ai_ask.ai_ask_settings.model_auto") : AppStrings.loading
    }
    private var menuWidth: CGFloat { min(360, max(0, viewportWidth - 32)) }
    private var rowCount: Int {
        if activeProvider != nil { return orderedModels.count + 1 }
        return showAllProviders ? max(0, providers.count - 4) + 1 : min(4, providers.count) + 1 + (providers.count > 4 ? 1 : 0)
    }
    var body: some View {
        Button(action: toggle) {
            HStack(spacing: 4) {
                if let model = selectedModel { modelIcon(model) }
                else { Icon("ai", size: 28).foregroundStyle(LinearGradient.primary) }
                if viewportWidth > 544 {
                    Text(selectedLabel).font(.omP.weight(.semibold)).lineLimit(1)
                        .frame(maxWidth: 192, alignment: .leading)
                }
            }.padding(4).foregroundStyle(Color(hex: 0x4867CD))
                .contentShape(RoundedRectangle(cornerRadius: 20))
        }.buttonStyle(.plain).disabled(!ready).opacity(ready ? 1 : 0.65)
            .accessibilityLabel(text("enter_message.model_selector.model_selection") + ": " + selectedLabel)
            .accessibilityIdentifier("composer-model-selector")
            .accessibilityValue(isOpen ? "expanded" : "collapsed")
            .overlay(alignment: .bottomLeading) {
                if isOpen {
                    ZStack(alignment: .bottomLeading) {
                        Color.black.opacity(0.001).frame(width: max(viewportWidth * 3, 1800), height: 2400)
                            .contentShape(Rectangle()).onTapGesture(perform: close)
                            .accessibilityIdentifier("composer-model-dismiss")
                        menu.offset(x: viewportWidth <= 544 ? -48 : 0, y: -48)
                    }.zIndex(30)
                }
            }
            #if os(macOS)
            .onExitCommand(perform: close)
            #endif
            .onChange(of: selection) { _, _ in if isOpen { openSelectedProvider() } }
    }
    private var menu: some View {
        ScrollView {
            VStack(spacing: 0) {
                if activeProvider != nil {
                    backRow
                    if let displayError { Text(displayError).font(.omSmall).foregroundStyle(Color.fontSecondary).padding(8) }
                    ForEach(orderedModels, id: \.id) { model in
                        HStack(spacing: 4) {
                            Button {
                                onSelect(value(model)); close(); onOpenDetails(model)
                            } label: {
                                HStack(spacing: 8) {
                                    modelIcon(model)
                                    Text(model.name).font(.omP.weight(.bold)).foregroundStyle(Color(hex: 0x4867CD)).lineLimit(1)
                                    Spacer(minLength: 0)
                                }.padding(.horizontal, 8).frame(height: 41).contentShape(RoundedRectangle(cornerRadius: 8))
                            }.buttonStyle(.plain)
                                .accessibilityLabel(text("enter_message.model_selector.model_details") + ": " + model.name)
                                .accessibilityIdentifier("composer-model-name-" + model.id)
                            modelToggle(model)
                                .padding(.trailing, 10)
                        }.accessibilityElement(children: .contain)
                            .accessibilityIdentifier("composer-model-row-" + model.id)
                    }
                } else if showAllProviders {
                    backRow
                    ForEach(Array(providers.dropFirst(4)), id: \.id, content: providerRow)
                } else {
                    Button { onSelect("auto"); close() } label: {
                        HStack(spacing: 8) {
                            Icon("ai", size: 28)
                            Text(text("settings.ai_ask.ai_ask_settings.model_auto")).font(.omP.weight(.bold))
                            Spacer(minLength: 0)
                        }.foregroundStyle(Color(hex: 0x4867CD)).padding(.horizontal, 8).frame(height: 41)
                            .contentShape(RoundedRectangle(cornerRadius: 8))
                    }.buttonStyle(.plain).accessibilityIdentifier("composer-model-auto")
                    ForEach(Array(providers.prefix(4)), id: \.id, content: providerRow)
                    if providers.count > 4 {
                        Button { showAllProviders = true } label: {
                            Text(text("common.show_more")).font(.omP).foregroundStyle(Color.fontSecondary)
                                .frame(maxWidth: .infinity).frame(height: 41)
                        }.buttonStyle(.plain).accessibilityIdentifier("composer-model-show-more")
                    }
                }
            }.padding(4)
        }.frame(width: menuWidth, height: min(352, CGFloat(rowCount) * 41 + 8))
            .background(Color.grey0, in: RoundedRectangle(cornerRadius: 20))
            .clipShape(RoundedRectangle(cornerRadius: 20))
            .shadow(color: .black.opacity(0.15), radius: 16, x: 0, y: 4)
            .accessibilityElement(children: .contain).accessibilityIdentifier("composer-model-selector-menu")
    }
    private var backRow: some View {
        Button {
            activeProvider = nil; showAllProviders = false; displayError = nil; orderedModels = []
        } label: {
            HStack(spacing: 8) {
                Icon("back", size: 25)
                Text(text("enter_message.model_selector.model_selection")).font(.omP)
                Spacer(minLength: 0)
            }.foregroundStyle(Color.fontPrimary).padding(.horizontal, 8).frame(height: 41)
                .contentShape(RoundedRectangle(cornerRadius: 8))
        }.buttonStyle(.plain).accessibilityIdentifier("composer-model-back")
    }
    private func providerRow(_ provider: NativeModelCatalog.ProviderDisplay) -> some View {
        Button { openProvider(provider.id) } label: {
            HStack(spacing: 8) {
                providerIcon(provider.logoSvg)
                VStack(alignment: .leading, spacing: 0) {
                    Text(provider.brandName).font(.omP.weight(.bold)).foregroundStyle(Color(hex: 0x4867CD))
                    if provider.brandName != provider.companyName {
                        Text(text("enter_message.mention_dropdown.from_provider_label") + " " + provider.companyName)
                            .font(.omSmall).foregroundStyle(Color.fontSecondary).lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
            }.padding(.horizontal, 8).frame(height: 41).contentShape(RoundedRectangle(cornerRadius: 8))
        }.buttonStyle(.plain).accessibilityIdentifier("composer-model-provider-" + provider.id)
    }
    private func modelToggle(_ model: NativeModelCatalog.Model) -> some View {
        let selected = selection == value(model)
        return Button {
            onSelect(selected ? "auto" : value(model)); close()
        } label: {
            ZStack(alignment: selected ? .trailing : .leading) {
                Capsule().fill(Color.grey30)
                Capsule().fill(LinearGradient.primary).opacity(selected ? 1 : 0)
                Circle().fill(Color.white).frame(width: 25, height: 25)
                    .shadow(color: .black.opacity(0.2), radius: 2, x: 0, y: 2).padding(2)
            }.frame(width: 49, height: 29)
                .animation(reduceMotion ? nil : .easeInOut(duration: 0.3), value: selected)
        }.buttonStyle(.plain).accessibilityLabel(model.name)
            .accessibilityAddTraits(.isToggle).accessibilityValue(selected ? "On" : "Off")
            .accessibilityIdentifier("composer-model-toggle-" + model.id)
    }
    private func modelIcon(_ model: NativeModelCatalog.Model) -> some View {
        providerIcon(model.logo_svg).overlay(alignment: .bottomTrailing) {
            NativeModelCapabilityTile(level: model.capability_level ?? "")
                .offset(x: 8, y: 8).accessibilityHidden(true)
        }
    }
    private func providerIcon(_ path: String) -> some View {
        let name = URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent
        return Image(name).renderingMode(.original).resizable().scaledToFit()
            .padding(4).frame(width: 28, height: 28).background(Color.white, in: RoundedRectangle(cornerRadius: 6))
    }
    private func text(_ key: String) -> String { LocalizationManager.shared.text(key) }
    private func value(_ model: NativeModelCatalog.Model) -> String { model.provider_id + "/" + model.id }
    private func close() { isOpen = false; activeProvider = nil; showAllProviders = false; displayError = nil; orderedModels = [] }
    private func toggle() { if isOpen { close() } else { isOpen = true; openSelectedProvider() } }
    private func openSelectedProvider() {
        showAllProviders = false
        if let selectedModel { openProvider(selectedModel.provider_id) }
        else { activeProvider = nil; orderedModels = [] }
    }
    private func openProvider(_ id: String) {
        activeProvider = id; showAllProviders = false
        do {
            orderedModels = try NativeModelCatalog.modelsForDisplay(catalog.models.filter {
                $0.provider_id == id && routing.usable(value($0))
            }); displayError = nil
        } catch {
            orderedModels = []; displayError = text("enter_message.model_selector.load_failed")
            NativeDiagnostics.warning("Model selector catalog display metadata invalid", category: "composer")
        }
    }
}

struct NativeModelCapabilityTile: View {
    let level: String
    private var active: Int { ["low": 1, "medium": 2, "high": 3, "max": 4][level] ?? 0 }
    private var color: Color {
        switch level { case "low": return .aiCapabilityLow; case "medium": return .aiCapabilityMedium
        case "high": return .aiCapabilityHigh; case "max": return .aiCapabilityMax; default: return .grey30 }
    }
    var body: some View {
        HStack(alignment: .bottom, spacing: 0.912) {
            ForEach(1...4, id: \.self) { bar in
                UnevenRoundedRectangle(topLeadingRadius: 2, topTrailingRadius: 2)
                    .fill(bar <= active ? color : Color.grey30)
                    .frame(width: 1.8, height: [3, 5, 7.2, 10][bar - 1])
            }
        }.padding(3).frame(width: 16, height: 16)
            .background(LinearGradient(colors: [.aiIconTileStart, .aiIconTileEnd], startPoint: .topLeading, endPoint: .bottomTrailing),
                in: RoundedRectangle(cornerRadius: 8.944))
            .shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)
    }
}
