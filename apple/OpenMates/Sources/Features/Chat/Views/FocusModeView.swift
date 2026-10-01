// Active focus indicator and canonical mention presentation shared by transcript and composer.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS: frontend/packages/ui/src/components/enter_message/MessageInput.styles.css
// Classes: .focus-pill, .generic-mention, .mate-mention, .best-model-mention
// ────────────────────────────────────────────────────────────────────
import SwiftUI

struct NativeMentionPresentation: Equatable {
    let syntax: String
    let kind: String
    let target: String
    let appId: String?

    static func parse(_ syntax: String) -> Self? {
        let parts = syntax.split(separator: ":", omittingEmptySubsequences: false).map(String.init)
        guard parts.count >= 2, !parts[1].isEmpty else { return nil }
        let kind = String(parts[0].dropFirst())
        guard parts[0].hasPrefix("@") else { return nil }
        switch kind {
        case "mate", "best-model":
            guard parts.count == 2 else { return nil }
            return .init(syntax: syntax, kind: kind, target: parts[1], appId: nil)
        case "ai-model":
            guard parts.count == 3, !parts[2].isEmpty else { return nil }
            return .init(syntax: syntax, kind: kind, target: parts[1], appId: "ai")
        case "skill", "focus", "memory", "memory-entry":
            guard (kind == "skill" || kind == "focus" ? parts.count == 3 : parts.count >= 3), !parts[2].isEmpty else { return nil }
            return .init(syntax: syntax, kind: kind, target: parts[2], appId: parts[1])
        default: return nil
        }
    }

    @MainActor var label: String {
        switch kind {
        case "mate":
            // Web mentionSearchService uses the mate's first name in lowercase.
            let name = CanonicalSettingsMateCatalog.mate(id: target)?.name ?? Self.titleCase(target)
            return "@" + (name.split(separator: " ").first.map(String.init) ?? name).lowercased()
        case "best-model":
            return "@" + Self.titleCase(target)
        case "ai-model":
            return "@" + (NativeModelCatalogRuntime.shared.catalog?.models.first { $0.id == target }?.name.replacingOccurrences(of: " ", with: "-") ?? target)
        case "skill", "focus":
            let app = appId ?? ""
            // Web mentionSearchService uses stable title-cased IDs for these labels.
            return "@" + Self.titleCase(app) + "-" + Self.titleCase(target)
        default:
            return "@" + Self.titleCase(target)
        }
    }

    @MainActor var gradient: LinearGradient {
        if kind == "best-model" {
            // Web .best-model-mention has these dedicated colors; no generated alias token exists.
            return LinearGradient(colors: [Color(hex: 0xF6D365), Color(hex: 0xFDA085)], startPoint: .topLeading, endPoint: .bottomTrailing)
        }
        return AppIconView.gradient(forAppId: kind == "mate" ? target : (appId ?? "ai"))
    }

    @MainActor static func localized(_ key: String, fallback: String) -> String {
        let value = AppStrings.localized(key)
        return value == key ? fallback : value
    }
    static func titleCase(_ id: String) -> String {
        id.replacingOccurrences(of: "_", with: "-").split(separator: "-").map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined(separator: "-")
    }
}

struct NativeMentionLabel: View {
    let mention: NativeMentionPresentation
    var displayLabel: String? = nil
    var highlightRanges: [NSRange] = []
    var body: some View {
        Text(SearchTextHighlighter.highlighted(displayLabel.map { $0.hasPrefix("@") ? $0 : "@" + $0 } ?? mention.label, ranges: highlightRanges))
            .font(.omP).fontWeight(mention.kind == "best-model" ? .semibold : .medium)
            .foregroundStyle(mention.gradient)
            .fixedSize()
            .accessibilityIdentifier("mention-\(mention.kind)")
    }
}

// Canonical focus icon metadata from backend/apps/*/app.yml (same web app metadata).
enum NativeFocusCatalog {
    static let icons: [String: String] = [
        "books-book_recommendations": "book",
        "books-book_discussion": "book",
        "code-project_planner": "coding",
        "code-test_git_repo": "coding",
        "code-analyze_logs": "coding",
        "code-research_solutions": "coding",
        "code-code_walkthrough": "coding",
        "code-setup_infrastructure": "coding",
        "code-learn_by_building": "coding",
        "code-refactor_code": "coding",
        "code-check_security": "coding",
        "health-prepare_doctor_report": "heart",
        "health-health_insights": "heart",
        "health-prepare_doctor_appointment": "heart",
        "jobs-career_insights": "insight",
        "life_coaching-crisis_support": "lifecoaching",
        "news-understand_the_news": "news",
        "openmates-plan": "planning",
        "plants-plant_care_guide": "plants",
        "politics-prepare_discussion": "politics",
        "social_media-content_calendar_strategist": "socialmedia",
        "study-what_to_study": "study",
        "study-learn_topic": "study",
        "study-test_knowledge": "study",
        "study-socratic_questioning": "study",
        "tasks-daily_meeting_and_orchestration": "task",
        "videos-analyze_video": "videos",
        "web-check_reputation": "web",
        "web-analyze_privacy": "web",
        "web-research": "web",
        "workflows-clarify_workflows": "workflow",
    ]
}

@MainActor
final class FocusModeManager: ObservableObject {
    @Published var activeFocusMode: FocusModeInfo?
    struct FocusModeInfo: Equatable {
        let id: String
        let appId: String
        let name: String
        var modeId: String { String(id.dropFirst(appId.count + 1)) }
        @MainActor var iconName: String { NativeFocusCatalog.icons[id] ?? AppIconView.iconName(forAppId: appId) }
        @MainActor static func resolve(_ id: String) -> Self? {
            guard let split = id.firstIndex(of: "-") else { return nil }
            let app = String(id[..<split]), mode = String(id[id.index(after: split)...])
            guard !app.isEmpty, !mode.isEmpty else { return nil }
            return .init(id: id, appId: app, name: NativeMentionPresentation.localized("app_focus_modes.\(app).\(mode)", fallback: AppStrings.focusModeActiveBanner))
        }
    }
    func activate(_ focusMode: FocusModeInfo) { activeFocusMode = focusMode }
    func deactivate() { activeFocusMode = nil }
}

struct FocusModePill: View {
    @ObservedObject var focusModeManager: FocusModeManager
    var onDeactivate: ((FocusModeManager.FocusModeInfo) -> Void)? = nil
    var onOpen: ((FocusModeManager.FocusModeInfo) -> Void)? = nil
    @State private var pendingDeactivation: Task<Void, Never>?
    @State private var isOn = true

    var body: some View {
        if let focus = focusModeManager.activeFocusMode {
            HStack(spacing: 0) {
                Button {
                    if let onOpen { onOpen(focus) }
                    else if let url = URL(string: "openmates://settings/apps/\(focus.appId)/focus/\(focus.modeId)") {
                        NotificationCenter.default.post(name: .deepLinkReceived, object: nil, userInfo: ["url": url])
                    }
                } label: {
                    HStack(spacing: 6) {
                        Icon(focus.iconName, size: 16).accessibilityHidden(true)
                        Text(focus.name).fontWeight(.semibold).lineLimit(1).frame(maxWidth: 160)
                            .accessibilityIdentifier("focus-pill-label")
                        Text(AppStrings.focusModeFocusOn).fontWeight(.regular).opacity(0.8).fixedSize()
                    }
                    .font(.custom("Lexend Deca", size: 13)).foregroundStyle(.white)
                    .padding(.leading, 12).padding(.trailing, 10)
                    .frame(height: 36)
                }.buttonStyle(.plain)
                    // Keep the real button boundary and its separately identified
                    // visible label; the outer pill must not propagate its ID here.
                    .accessibilityElement(children: .contain)
                    .accessibilityAddTraits(.isButton)
                    .accessibilityLabel(AppStrings.focusModeActiveBanner)
                    .accessibilityIdentifier("focus-pill-body")
                Rectangle().fill(.white.opacity(0.25)).frame(width: 1, height: 36)
                OMToggle(isOn: Binding(get: { isOn }, set: { value in
                    isOn = value
                    pendingDeactivation?.cancel()
                    if !value {
                        pendingDeactivation = Task { @MainActor in
                            do { try await Task.sleep(for: .seconds(1)) } catch { return }
                            guard focusModeManager.activeFocusMode?.id == focus.id else { return }
                            focusModeManager.deactivate()
                            onDeactivate?(focus)
                        }
                    }
                }), accessibilityIdentifier: "focus-pill-toggle")
                    .padding(.horizontal, 8)
            }
            .fixedSize(horizontal: true, vertical: false)
            .frame(height: 36).background(AppIconView.gradient(forAppId: focus.appId))
            .clipShape(RoundedRectangle(cornerRadius: 20))
            .shadow(color: .black.opacity(0.18), radius: 4, x: 0, y: 2)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("focus-pill")
            .onChange(of: focus.id) { _, _ in pendingDeactivation?.cancel(); isOn = true }
            .onDisappear { pendingDeactivation?.cancel(); isOn = true }
        }
    }
}

struct FocusModeBadge: View {
    let appId: String
    var body: some View {
        Icon("select", size: 8).foregroundStyle(.white).padding(3)
            .background(Circle().fill(Color.buttonPrimary)).accessibilityHidden(true)
    }
}
