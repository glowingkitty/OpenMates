// Inline Billing usage and its three-level activity drilldown.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/settings/SettingsUsage.svelte
//         frontend/packages/ui/src/components/SettingsItem.svelte
//         frontend/packages/ui/src/components/settings/elements/SettingsTabs.svelte
// CSS:    SettingsUsage.svelte: .tab-content-panel, .usage-detail-view,
//         .entry-detail-row; SettingsItem.svelte: .credits-display
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// Reference: 78e8d99023c4a90ad06b2d1b35cd257c15cab8fc
// Rendered populated reference comparison pending; source fallback authorized.
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/billing/specification.yml
// Assertions: billing.usage.landing-complete, billing.usage.receipt-token-breakdown, billing.surface.semantic-parity

import SwiftUI
import LucideIcons
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct BillingUsageView: View {
    var context = BillingUsageContext()
    var body: some View {
        OMSettingsPage(title: AppStrings.usage, showsHeader: false) {
            BillingUsagePanel(context: context)
        }
    }
}

struct BillingUsagePanel: View {
    var context = BillingUsageContext()
    @EnvironmentObject private var authManager: AuthManager
    @ObservedObject private var team = TeamWorkspaceContext.shared
    @ObservedObject private var localization = LocalizationManager.shared
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Namespace private var tabSelectionNamespace
    @StateObject private var model = BillingUsageModel()
    @State private var tab: UsageTab = .overview
    @State private var loadedOwner = ""
    @State private var selectedContextIcon = "chat"
    @State private var selectedContextSubtitle: String?
    @State private var selectedContextIncognito = false
    @State private var selectedContextAppearance: BillingUsageChatAppearance?

    private var ownerIdentity: String {
        "\(authManager.currentUser?.id ?? "")|\(team.contextEpoch)|\(context.hiddenChatsUnlocked)|\(localization.currentLanguage.code)"
    }
    private var requestIdentity: String { ownerIdentity + "|" + tab.rawValue }
    var body: some View {
        // Normal SettingsBilling stacks these sibling blocks. The chrome=0
        // preview's generic flex-row mount must not replace the product layout.
        VStack(spacing: 0) {
            Color.clear.frame(height: 0).accessibilityIdentifier("settings-billing-usage-page")
            OMSettingsRow(title: AppStrings.billingExportUsage, icon: "download", plainIcon: true,
                showsChevron: false, accessibilityIdentifier: "usage-export-button") {
                Task { await model.export(accountID: authManager.currentUser?.id, fixture: BillingUITestFixture.enabled) }
            }
            usageTabs
            if tab != .overview, model.historyAvailabilityMissing, !model.loading {
                OMSettingsInfoBox(message: AppStrings.usageHistoryAvailabilityUnavailable,
                    identifier: "usage-history-availability-unavailable")
            }
            VStack(spacing: 0) { content }
                .padding(.vertical, .spacing2)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius5))
                .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey20, lineWidth: 1))
                .padding(.horizontal, .spacing5)
                .padding(.top, .spacing4)
        }
        .task(id: requestIdentity) {
            if loadedOwner != ownerIdentity {
                model.invalidate(); selectedContextIcon = "chat"; selectedContextSubtitle = nil
                selectedContextIncognito = false; selectedContextAppearance = nil; loadedOwner = ownerIdentity
            }
            await load()
        }
        .onChange(of: model.exportURL) { _, url in if let url { presentFile(url) } }
        .onDisappear { model.invalidate(); selectedContextSubtitle = nil; selectedContextAppearance = nil }
    }

    // SettingsTabs.svelte: four equal icon tabs; 2.8rem height and 1.15rem icons.
    // This is the same matched pill composition used by native Chat Settings.
    private var usageTabs: some View {
        HStack(spacing: 0) {
            ForEach(UsageTab.allCases, id: \.rawValue) { option in
                Button {
                    withAnimation(reduceMotion ? nil : .timingCurve(0.4, 0, 0.2, 1, duration: 0.3)) { tab = option }
                } label: {
                    Icon(tabIcon(option), size: 18.4)
                        .foregroundStyle(tab == option ? Color.fontButton : Color.grey70)
                        .frame(maxWidth: .infinity).frame(height: 44.8)
                        .background {
                            if tab == option {
                                Capsule().fill(LinearGradient.primary)
                                    .matchedGeometryEffect(id: "usage-selected-tab", in: tabSelectionNamespace)
                                    .allowsHitTesting(false)
                            }
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain).accessibilityLabel(title(option))
                .accessibilityIdentifier("settings-tab-\(option.rawValue)")
                .accessibilityAddTraits(tab == option ? .isSelected : [])
            }
        }
        .background(Color.grey0).clipShape(Capsule())
        .shadow(color: .black.opacity(0.1), radius: 4, x: 0, y: 4)
        .padding(.horizontal, .spacing5)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings-billing-usage-tabs")
    }
    private func tabIcon(_ tab: UsageTab) -> String {
        switch tab { case .overview: "event"; case .chats: "chat"; case .apps: "app"; case .api: "coding" }
    }

    @ViewBuilder private var content: some View {
        if !BillingUITestFixture.enabled && !model.canDisplay(accountID: authManager.currentUser?.id, hiddenUnlocked: context.hiddenChatsUnlocked) {
            loading
        } else if let entry = model.selectedEntry {
            entryDetail(entry)
        } else if let selectedTitle = model.selectedTitle {
            VStack(spacing: 0) {
                backButton(backIdentifier) { model.back() }
                usageDetailHeader(title: selectedTitle,
                    subtitle: selectedContextSubtitle, icon: selectedContextIcon,
                    contextChat: tab == .overview || tab == .chats, incognito: selectedContextIncognito,
                    appearance: selectedContextAppearance)
                if model.loading { loading }
                else if model.error { errorState }
                else if model.entryRows.isEmpty { empty }
                else {
                    ForEach(model.entryRows) { row in
                        if tab == .overview {
                            OMSettingsRow(title: row.title, subtitleBottom: row.subtitle,
                                icon: row.entry.appId ?? "app_store", plainIcon: true,
                                creditsDisplay: credits(row.entry.credits ?? 0), subtitleBottomWeight: .regular, showsChevron: false,
                                accessibilityIdentifier: "usage-chat-entry") {
                                Task { await model.selectEntry(row.entry, fixture: BillingUITestFixture.enabled) }
                            }
                        } else {
                            OMSettingsStaticRow(title: row.title, value: "", subtitleBottom: row.subtitle,
                                icon: row.entry.appId ?? "app_store", creditsDisplay: credits(row.entry.credits ?? 0), appearance: .information)
                                .accessibilityIdentifier("usage-detail-entry-row")
                        }
                    }
                }
            }
            .padding(.spacing5)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("usage-detail-view")
        } else if model.loading { loading }
        else if model.error { errorState }
        else if model.groups.isEmpty && !model.hasMore && !model.historyAvailabilityMissing { empty }
        else {
            if model.groups.isEmpty { empty }
            ForEach(model.groups) { group in
                OMSettingsStaticRow(title: group.title, value: "", icon: "event", creditsDisplay: credits(group.credits), appearance: .heading)
                    .accessibilityIdentifier(tab == .overview ? "usage-overview-day-heading" : "usage-month-heading")
                if group.rows.isEmpty {
                    Text(AppStrings.usageEmptyDay).font(.omXs).foregroundStyle(Color.grey50).padding(.spacing8)
                }
                ForEach(group.rows) { row in
                    if row.chatID != nil || row.summary?.identifier != nil {
                        OMSettingsRow(title: row.title, subtitleBottom: row.subtitle, icon: usageIcon(row.icon),
                            iconGradient: chatRowGradient(row.chatAppearance) ?? usageIconGradient(row.icon),
                            plainIcon: row.chatAppearance?.kind != .standard,
                            iconContent: row.chatAppearance?.lucideIcon.map { AnyView(BillingUsageLucideIcon($0, size: 20)) },
                            iconAccessibilityIdentifier: row.chatAppearance?.lucideIcon.map { "usage-chat-lucide-" + BillingUsageLucideResolver.resolve($0) },
                            creditsDisplay: credits(row.credits), subtitleBottomWeight: .regular, showsChevron: false, accessibilityIdentifier: row.identifier) {
                            selectedContextAppearance = row.chatAppearance
                            selectedContextIcon = row.icon
                            selectedContextSubtitle = tab == .apps ? row.summary?.month : tab == .api ? row.subtitle : nil
                            selectedContextIncognito = (row.chatID ?? row.summary?.chatId) == "incognito"
                            Task { await model.open(row, tab: tab, accountID: authManager.currentUser?.id, fixture: BillingUITestFixture.enabled) }
                        }
                    } else {
                        // Informational usage groups have no context navigation on the web.
                        OMSettingsStaticRow(title: row.title, value: "", subtitleBottom: row.subtitle,
                            icon: usageIcon(row.icon), creditsDisplay: credits(row.credits), appearance: .information)
                            .accessibilityIdentifier(row.identifier)
                    }
                }
            }
            if model.hasMore || model.historyAvailabilityMissing {
                Button(tab == .overview ? AppStrings.usageLoadMoreDays : AppStrings.usageShowMore) {
                    Task { await load(more: true) }
                }
                .buttonStyle(OMSettingsButtonStyle(secondary: true))
                .padding(.spacing5)
                .accessibilityIdentifier(tab == .overview ? "usage-load-more-days-button" : "usage-load-more-months-button")
            }
        }
    }

    private var loading: some View {
        HStack(spacing: .spacing6) {
            ProgressView()
            Text(AppStrings.usageLoading).font(.omSmall).foregroundStyle(Color.grey60)
        }.frame(maxWidth: .infinity).padding(.spacing20)
            .accessibilityIdentifier("usage-loading")
    }
    private var empty: some View {
        VStack(spacing: .spacing4) {
            Icon("usage", size: 48).foregroundStyle(Color.grey50)
            Text(AppStrings.usageEmpty).font(.omP.weight(.semibold))
            Text(AppStrings.usageEmptyDay).font(.omSmall).foregroundStyle(Color.grey60)
        }.frame(maxWidth: .infinity).padding(.spacing10)
            .accessibilityIdentifier("usage-empty")
    }
    private var errorState: some View {
        VStack(spacing: .spacing4) {
            Text(AppStrings.usageLoadError).font(.omSmall).foregroundStyle(Color.error)
            Button(AppStrings.retry) {
                if model.selectedTitle != nil { model.back() }
                Task { await load() }
            }
            .buttonStyle(OMSettingsButtonStyle(secondary: true))
            .accessibilityIdentifier("usage-retry-button")
        }.padding(.spacing8)
    }
    private func entryDetail(_ entry: UsageEntry) -> some View {
        VStack(spacing: 0) {
            backButton("usage-entry-detail-back-button") { model.closeEntry() }
            if let row = model.entryRows.first(where: { $0.id == entry.id }) {
                usageDetailHeader(title: row.title, subtitle: row.subtitle, icon: entry.appId ?? "app_store", entry: true)
            }
            VStack(spacing: 0) {
                if let credits = entry.credits { detail(AppStrings.usageTotalCredits, self.credits(credits), coins: true, id: "usage-entry-total-credits") }
                if let modelUsed = entry.modelUsed {
                    if let separator = modelUsed.firstIndex(of: "/") {
                        detail(AppStrings.usageProvider, String(modelUsed[..<separator]).capitalized, id: "usage-provider")
                        detail(AppStrings.usageModel, String(modelUsed[modelUsed.index(after: separator)...]), id: "usage-model")
                    } else { detail(AppStrings.usageModel, modelUsed, id: "usage-model") }
                }
                if let provider = entry.serverProvider { detail(AppStrings.usageServerProvider, provider, id: "usage-server-provider") }
                if let region = entry.serverRegion { detail(AppStrings.usageServerRegion, region, id: "usage-server-region") }
                if let credits = entry.creditsSystemPrompt { detail(AppStrings.usageCreditsSystemPrompt, self.credits(credits), id: "usage-credits-system") }
                if let credits = entry.creditsHistory { detail(AppStrings.usageCreditsHistory, self.credits(credits), id: "usage-credits-history") }
                if let credits = entry.creditsResponse { detail(AppStrings.usageCreditsResponse, self.credits(credits), id: "usage-credits-response") }
                if let count = entry.systemPromptTokens { detail(AppStrings.usageSystemPromptTokens, count.formatted(), id: "usage-system-prompt-tokens") }
                if let count = entry.userInputTokens { detail(AppStrings.usageUserInputTokens, count.formatted(), id: "usage-user-input-tokens") }
                if let count = entry.appSkillTokens {
                    detail(AppStrings.usageAppSkillTokens + " (×\(entry.toolInferenceIterations ?? 0))", count.formatted(), id: "usage-app-skill-tokens")
                }
                if let count = entry.inputTokens { detail(AppStrings.usageTotalInputTokens, count.formatted(), id: "usage-input-tokens") }
                if let count = entry.outputTokens { detail(AppStrings.usageOutputTokens, count.formatted(), id: "usage-output-tokens") }
                if let iterations = entry.toolInferenceIterations, iterations > 0 {
                    Text(AppStrings.usageAppSkillsHint).font(.omXs).foregroundStyle(Color.grey60).padding(.vertical, .spacing6)
                        .accessibilityIdentifier("usage-app-skills-hint")
                }
            }.padding(.horizontal, .spacing5)
            if let receipt = entry.llmUsageBreakdown { ChatSettingsLLMReceipt(receipt: receipt).accessibilityIdentifier("usage-llm-receipt") }
            if let target = model.selectedTarget {
                Button(target.isMessage ? AppStrings.usageOpenMessage : AppStrings.usageOpenEmbed) {
                    Task { await model.openSelectedTarget() }
                }
                .buttonStyle(OMSettingsButtonStyle(secondary: true)).padding(.spacing5)
                .accessibilityIdentifier("usage-open-target-button")
            }
        }
        .padding(.spacing5)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("usage-detail-view")
    }
    // SettingsUsage .entry-detail-row: 14px vertical padding, 14px text;
    // label weight 400 and value weight 500, separated by the grey-20 rule.
    private func detail(_ label: String, _ value: String, coins: Bool = false, id: String) -> some View {
        HStack(spacing: .spacing8) {
            Text(label).font(.omSmall).foregroundStyle(Color.grey60)
            Spacer(minLength: 0)
            HStack(spacing: .spacing2) {
                Text(value).font(.omSmall.weight(.medium)).foregroundStyle(Color.fontPrimary)
                    .multilineTextAlignment(.trailing)
                if coins { Icon("coins", size: .iconSizeXs).foregroundStyle(Color.fontPrimary) }
            }
        }
        .padding(.vertical, CGFloat.spacing6 + .spacing1)
        .frame(maxWidth: .infinity)
        .overlay(alignment: .bottom) { Color.grey20.frame(height: 1) }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(id)
    }

    // SettingsUsage .detail-header uses a 40px icon slot, never a section
    // heading with a primary underline. Category metadata is not inferred here.
    private func usageDetailHeader(title: String, subtitle: String? = nil, icon: String,
                                   contextChat: Bool = false, incognito: Bool = false, entry: Bool = false,
                                   appearance: BillingUsageChatAppearance? = nil) -> some View {
        HStack(spacing: .spacing6) {
            Group {
                if contextChat {
                    Group {
                        if let lucide = appearance?.lucideIcon {
                            BillingUsageLucideIcon(lucide, size: tab == .overview ? .iconSizeXs : .iconSizeSm)
                        } else {
                            Icon(usageIcon(incognito ? "anonym" : icon), size: tab == .overview ? .iconSizeXs : .iconSizeSm)
                        }
                    }
                        .foregroundStyle(Color.white)
                        .frame(width: tab == .overview ? CGFloat.spacing12 + .spacing2 : .spacing20,
                               height: tab == .overview ? CGFloat.spacing12 + .spacing2 : .spacing20)
                        .background {
                            if let category = appearance?.category { CategoryMapping.gradient(for: category) }
                            else { incognito ? Color.grey70 : Color.grey30 }
                        }
                        .clipShape(Circle())
                        .overlay(Circle().stroke(Color.grey0, lineWidth: 2))
                } else {
                    Icon(usageIcon(icon), size: entry ? .iconSizeLg : .iconSizeXl).foregroundStyle(LinearGradient.primary)
                }
            }
            .frame(width: .spacing20, height: .spacing20, alignment: .topLeading)
            VStack(alignment: .leading, spacing: .spacing2) {
                Text(title).font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                if let subtitle, !subtitle.isEmpty {
                    Text(subtitle).font(.omSmall).foregroundStyle(Color.grey60)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.bottom, .spacing8)
        .overlay(alignment: .bottom) { Color.grey20.frame(height: 1) }
        .padding(.bottom, .spacing12)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("usage-detail-header")
    }

    private func chatRowGradient(_ appearance: BillingUsageChatAppearance?) -> LinearGradient? {
        guard let appearance else { return nil }
        if let category = appearance.category { return CategoryMapping.gradient(for: category) }
        let color: Color
        switch appearance.kind {
        case .standard, .incognito: color = .grey50
        case .deleted: color = .grey40
        case .unsentDraft: return .primary
        }
        return LinearGradient(colors: [color, color], startPoint: .topLeading, endPoint: .bottomTrailing)
    }

    private func usageIcon(_ name: String) -> String {
        name == "help-circle" ? "lucide-help-circle" : name
    }
    private func usageIconGradient(_ name: String) -> LinearGradient? {
        let tint: Color
        switch name {
        case "anonym": tint = .grey50
        case "delete": tint = .grey40
        default: return nil
        }
        return LinearGradient(colors: [tint, tint], startPoint: .topLeading, endPoint: .bottomTrailing)
    }
    private func backButton(_ id: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: .spacing4) {
                Icon("back", size: 20)
                Text(AppStrings.back).font(.omSmall)
                Spacer()
            }.foregroundStyle(Color.grey60).padding(.vertical, .spacing4)
                .padding(.bottom, .spacing8)
        }.buttonStyle(.plain).accessibilityIdentifier(id)
    }
    private var backIdentifier: String {
        switch tab {
        case .overview: "usage-chat-detail-back-button"
        case .chats: "usage-selected-chat-back-button"
        case .apps: "usage-app-detail-back-button"
        case .api: "usage-api-detail-back-button"
        }
    }
    private func load(more: Bool = false) async {
        await model.load(tab: tab, accountID: authManager.currentUser?.id, more: more,
            fixture: BillingUITestFixture.enabled, context: context)
    }
    private func title(_ tab: UsageTab) -> String {
        switch tab {
        case .overview: AppStrings.billingUsageOverview
        case .chats: AppStrings.billingUsageChats
        case .apps: AppStrings.billingUsageApps
        case .api: AppStrings.billingUsageAPI
        }
    }
    private func credits(_ value: Double) -> String { value.rounded().formatted(.number.precision(.fractionLength(0))) }
}
private extension BillingUsageOpenTarget {
    var isMessage: Bool { if case .message = self { return true }; return false }
}

// Reuse the app's Lucide renderer, validating its name with the same native
// catalogue so unsupported names match web getLucideIcon's help-circle fallback.
@MainActor
enum BillingUsageLucideResolver {
    private static var known: [String: String] = [:]
    static func resolve(_ candidate: String) -> String {
        if let cached = known[candidate] { return cached }
        guard !candidate.isEmpty, candidate.utf8.count <= 100 else { return "help-circle" }
        let resolved: String
        #if os(iOS)
        resolved = UIImage(lucideId: candidate) != nil ? candidate : "help-circle"
        #elseif os(macOS)
        resolved = NSImage.image(lucideId: candidate) != nil ? candidate : "help-circle"
        #else
        resolved = "help-circle"
        #endif
        // This cache stores public icon-catalogue decisions only, not account
        // identities, titles, decrypted content, images or private network data.
        if resolved == candidate {
            if known.count >= 512 { known.removeAll(keepingCapacity: true) }
            known[candidate] = resolved
        }
        return resolved
    }
}

@MainActor
private struct BillingUsageLucideIcon: View {
    let resolved: String
    let size: CGFloat
    init(_ name: String, size: CGFloat) {
        resolved = BillingUsageLucideResolver.resolve(name); self.size = size
    }
    var body: some View {
        LucideNativeIcon(resolved, size: size)
            .accessibilityIdentifier("usage-chat-lucide-" + resolved)
    }
}
