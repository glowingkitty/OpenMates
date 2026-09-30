// Workflow identity header and template/runs tabs.
// Web source: frontend/packages/ui/src/components/workflows/WorkflowDetailPage.svelte
// Specification: specifications/features/workflows/specification.yml
// Assertions: workflows.mvp.editor, workflows.mvp.run-history

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

// The web's workflowIcon() favors a stored Lucide name, then derives one from
// the title. Check the bundled asset before drawing so an unknown server value
// cannot leave an invisible icon in the header or home card.
@MainActor enum WorkflowIconAsset {
    static func name(title: String, icon: String?, category: String?) -> String {
        if let icon, !icon.isEmpty,
           !["help-circle", "circle-help", "workflow"].contains(icon) {
            let candidate = icon.hasPrefix("lucide-") ? icon : "lucide-\(icon)"
            if hasAsset(candidate) { return candidate }
            if hasAsset(icon) { return icon }
        }
        let title = title.lowercased()
        if title.range(of: "apartment|flat|rent|home|wohnung", options: .regularExpression) != nil {
            return "lucide-house"
        }
        if title.range(of: "weather|rain|forecast|wetter", options: .regularExpression) != nil {
            return "lucide-cloud-rain"
        }
        if title.range(of: "event|meetup", options: .regularExpression) != nil {
            return "lucide-calendar-days"
        }
        if title.range(of: "news|brief", options: .regularExpression) != nil {
            return "lucide-newspaper"
        }
        return "workflow"
    }

    static func rawLucideName(title: String, icon: String?) -> String? {
        guard let icon, !icon.isEmpty,
              !["help-circle", "circle-help", "workflow"].contains(icon),
              !hasAsset(icon.hasPrefix("lucide-") ? icon : "lucide-\(icon)"),
              !hasAsset(icon) else { return nil }
        return icon.hasPrefix("lucide-") ? String(icon.dropFirst("lucide-".count)) : icon
    }

    private static func hasAsset(_ name: String) -> Bool {
        #if os(iOS)
        UIImage(named: name) != nil
        #elseif os(macOS)
        NSImage(named: NSImage.Name(name)) != nil
        #else
        false
        #endif
    }
}

struct WorkflowIconView: View {
    let title: String
    let icon: String?
    let category: String?
    let size: CGFloat

    var body: some View {
        if let raw = WorkflowIconAsset.rawLucideName(title: title, icon: icon) {
            LucideNativeIcon(raw, size: size)
        } else {
            Icon(WorkflowIconAsset.name(title: title, icon: icon, category: category), size: size)
        }
    }
}

enum WorkflowDetailTab: String, CaseIterable {
    case template
    case runs
}

struct WorkflowDetailHeader: View {
    let title: String
    let description: String?
    let category: String
    let icon: String
    let enabled: Bool
    let canEnable: Bool
    let canRun: Bool
    let createdAt: Int?
    let nextRunAt: Int?
    let saving: Bool
    @Binding var tab: WorkflowDetailTab
    let onUpdateIdentity: (String, String) async -> Bool
    let onToggleEnabled: () -> Void
    let onRun: () -> Void
    let onDelete: () -> Void
    let onBack: () -> Void
    let onShare: () -> Void
    let onReportIssue: () -> Void

    @State private var editing = false
    @State private var draftTitle = ""
    @State private var draftDescription = ""

    private func tr(_ key: AppStrings.WorkflowBuilderCopy) -> String {
        AppStrings.workflowBuilder(key)
    }

    private var metadata: String {
        if enabled, let nextRunAt, nextRunAt > Int(Date().timeIntervalSince1970) {
            let format = Date.FormatStyle().weekday(.abbreviated).hour().minute()
                .locale(Locale(identifier: LocalizationManager.shared.currentLanguage.code))
            return "\(tr(.next_run)) \(Date(timeIntervalSince1970: TimeInterval(nextRunAt)).formatted(format))"
        }
        guard let createdAt, createdAt > 0 else { return "" }
        return "\(tr(.created)) \(Date(timeIntervalSince1970: TimeInterval(createdAt)).formatted(.relative(presentation: .named)))"
    }

    var body: some View {
        VStack(spacing: 0) {
            ZStack(alignment: .top) {
                CategoryMapping.gradient(for: CategoryMapping.isKnownCategory(category) ? category : "general_knowledge")

                VStack(spacing: 10) {
                    Spacer(minLength: 40)
                    WorkflowIconView(title: title, icon: icon, category: category, size: 38)
                        .foregroundStyle(Color.fontButton)

                    if editing {
                        VStack(spacing: 6) {
                            TextField(tr(.workflow_name), text: $draftTitle)
                                .textFieldStyle(.roundedBorder)
                                .accessibilityIdentifier("workflow-title-input")
                            TextField(tr(.description), text: $draftDescription)
                                .textFieldStyle(.roundedBorder)
                                .accessibilityIdentifier("workflow-description-input")
                            Button(tr(.save)) {
                                Task {
                                    if await onUpdateIdentity(draftTitle, draftDescription) { editing = false }
                                }
                            }
                            .disabled(saving || draftTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                        .frame(maxWidth: 400)
                    } else {
                        Button {
                            draftTitle = title
                            draftDescription = description ?? ""
                            editing = true
                        } label: {
                            Text(title)
                                .font(.omH2.weight(.semibold))
                                .multilineTextAlignment(.center)
                                .foregroundStyle(Color.fontPrimary)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("workspace-detail-title")
                    }

                    Button(action: onToggleEnabled) {
                        HStack(spacing: 6) {
                            Icon("workflow", size: 16)
                            Text(tr(enabled ? .workflow_on : .workflow_off))
                            Capsule().fill(Color.fontButton.opacity(0.35))
                                .frame(width: 32, height: 19)
                                .overlay(alignment: enabled ? .trailing : .leading) {
                                    Circle().fill(Color.fontButton)
                                        .frame(width: 15, height: 15)
                                        .padding(2)
                                }
                        }
                        .font(.omSmall.weight(.semibold))
                        .foregroundStyle(Color.fontButton)
                        .padding(.horizontal, 10)
                        .frame(height: 32)
                        .background(Color(hex: 0x4867CD))
                        .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .disabled(saving || (!enabled && !canEnable))
                    .accessibilityIdentifier("toggle-workflow")

                    if !editing {
                        Button {
                            draftTitle = title
                            draftDescription = description ?? ""
                            editing = true
                        } label: {
                            Text(description?.isEmpty == false ? description! : tr(.add_description))
                                .font(.omP)
                                .multilineTextAlignment(.center)
                                .foregroundStyle(Color.fontButton.opacity(0.95))
                        }
                        .buttonStyle(.plain)
                        .frame(maxWidth: 416)
                        .accessibilityIdentifier("workspace-detail-description")
                    }
                    Spacer(minLength: 16)
                    Text(metadata)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontButton.opacity(0.8))
                        .accessibilityIdentifier("workflow-detail-metadata")
                }
                .padding(.horizontal, 20)
                .padding(.top, 48)
                .padding(.bottom, 16)

                GeometryReader { geometry in
                    Text(tr(.workflow))
                        .font(.omSmall.weight(.semibold))
                        .foregroundStyle(Color.fontButton)
                        .frame(maxWidth: .infinity, alignment: .top)
                        .padding(.top, geometry.size.width <= 730 ? 54 : 20)

                    HStack(spacing: 8) {
                        toolbarButton("bug", label: AppStrings.reportIssue,
                                      showLabel: geometry.size.width > 730, action: onReportIssue)
                            .accessibilityIdentifier("workflow-report-issue")
                        if geometry.size.width > 730 {
                            toolbarButton("share", label: tr(.share), action: onShare)
                                .accessibilityIdentifier("workflow-share")
                        }
                        Menu {
                            Button(tr(.share), action: onShare)
                            if canRun { Button(tr(.run_now), action: onRun).disabled(saving) }
                            Button(tr(.delete_workflow), role: .destructive, action: onDelete)
                        } label: {
                            toolbarCircle("more")
                        }
                        .accessibilityLabel(tr(.action_question))
                        .accessibilityIdentifier("workflow-detail-actions")
                        Spacer()
                        toolbarButton("close", label: tr(.close), action: onBack)
                            .accessibilityIdentifier("workflow-detail-back")
                    }
                    .padding(.horizontal, 15)
                    .padding(.top, 15)
                }
            }
            .frame(minHeight: 304)
            .clipShape(UnevenRoundedRectangle(bottomLeadingRadius: 16, bottomTrailingRadius: 16))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("workspace-detail-header")

            HStack(spacing: 0) {
                tabButton(.template, icon: "workflow", label: tr(.workflow))
                tabButton(.runs, icon: "projectmanagement", label: tr(.run_history))
            }
            .background(Color.grey10, in: Capsule())
            .shadow(color: .black.opacity(0.14), radius: 4, y: 4)
            .padding(.top, 20)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("workflow-view-tabs")
        }
    }

    private func tabButton(_ value: WorkflowDetailTab, icon: String, label: String) -> some View {
        Button { tab = value } label: {
            Icon(icon, size: 20)
                .foregroundStyle(tab == value ? Color.fontButton : Color.grey70)
                .frame(width: 72, height: 44)
                .background {
                    if tab == value { Capsule().fill(LinearGradient.primary) }
                }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityIdentifier(value == .template ? "workflow-tab-template" : "workflow-tab-runs")
    }

    private func toolbarCircle(_ icon: String) -> some View {
        Icon(icon, size: 20)
            .foregroundStyle(LinearGradient.primary)
            .frame(width: 40, height: 40)
            .background(Color.grey10, in: Circle())
            .shadow(color: .black.opacity(0.16), radius: 4, y: 2)
    }

    private func toolbarButton(_ icon: String, label: String, showLabel: Bool = false,
                               action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 7) {
                Icon(icon, size: 20)
                if showLabel { Text(label).font(.omSmall.weight(.semibold)) }
            }
            .foregroundStyle(LinearGradient.primary)
            .frame(minWidth: 40, minHeight: 40)
            .padding(.horizontal, showLabel ? 10 : 0)
            .background(Color.grey10, in: Capsule())
            .shadow(color: .black.opacity(0.16), radius: 4, y: 2)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}
