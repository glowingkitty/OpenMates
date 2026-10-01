// Native owner and recipient panels for portable, client-encrypted Workflow templates.
// Web source: frontend/packages/ui/src/components/workflows/WorkflowTemplateShare.svelte

import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

extension AppStrings {
    enum WorkflowTemplateCopy: String {
        case title, create_link, `import`, complete_bindings, revoked
        case owner_description, preparing, copy_short, copy_offline, revoke, restore
        case link_created, link_copied, access_restored, preview_label
        case import_disabled, importing, complete_before_enable, binding_explanation
        case binding_schedule, binding_app_skill, binding_notifications, binding_other
        case mark_complete, completed, enabling, enable, import_done, binding_done
    }

    static func workflowTemplate(_ key: WorkflowTemplateCopy) -> String {
        localized("workflows.template_share.\(key.rawValue)")
    }

    static func workflowTemplatePreviewSummary(stepCount: Int) -> String {
        LocalizationManager.shared.text("workflows.template_share.preview_step_summary",
                                        replacements: ["count": String(stepCount)])
    }
}

struct WorkflowTemplateOwnerPanel: View {
    let workflow: WorkflowDetail
    let accountId: String
    var onChanged: (() async -> Void)? = nil

    @State private var service = WorkflowTemplateShareService()
    @State private var share: WorkflowTemplateShareResult?
    @State private var projectionExists = false
    @State private var revoked = false
    @State private var busy = false
    @State private var error: String?
    @State private var message: String?
    @State private var generation = 0

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing5) {
            Text(AppStrings.workflowTemplate(.title))
                .font(.omH3)
                .foregroundStyle(Color.fontPrimary)
            Text(AppStrings.workflowTemplate(.owner_description))
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)

            ViewThatFits(in: .horizontal) {
                actionButtons
                VStack(alignment: .leading, spacing: .spacing4) { actionButtons }
            }

            if let message {
                Text(message).font(.omSmall).foregroundStyle(Color.fontSecondary)
            }
            if let error {
                Text(error).font(.omSmall).foregroundStyle(Color.error)
            }
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius8))
        .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey30, lineWidth: 1))
        .accessibilityIdentifier("workflow-template-share")
        .task(id: "\(accountId)|\(workflow.id)") { await loadStatus() }
        .onDisappear { generation &+= 1 }
    }

    private var actionButtons: some View {
        HStack(spacing: .spacing4) {
            Button {
                Task { await createShare() }
            } label: {
                Text(AppStrings.workflowTemplate(busy ? .preparing : .create_link))
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(busy || accountId.isEmpty)
            .accessibilityIdentifier("workflow-template-create-share")

            if let share {
                Button(AppStrings.workflowTemplate(.copy_short)) { copy(share.shortURL) }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("workflow-template-copy-short-link")
                Button(AppStrings.workflowTemplate(.copy_offline)) { copy(share.longURL) }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("workflow-template-copy-long-link")
            }

            if projectionExists {
                Button(AppStrings.workflowTemplate(revoked ? .restore : .revoke)) {
                    Task { await toggleRevocation() }
                }
                .buttonStyle(OMSecondaryButtonStyle())
                .disabled(busy)
                .accessibilityIdentifier("workflow-template-toggle-revocation")
            }
        }
    }

    private func loadStatus() async {
        generation &+= 1
        let stamp = generation
        share = nil
        projectionExists = false
        revoked = false
        guard !accountId.isEmpty else { return }
        do {
            let status = try await service.ownerStatus(workflowId: workflow.id, accountId: accountId)
            guard generation == stamp else { return }
            projectionExists = status.exists
            revoked = status.isRevoked
        } catch {
            guard generation == stamp else { return }
            self.error = error.localizedDescription
        }
    }

    private func createShare() async {
        guard !busy, !accountId.isEmpty else { return }
        let stamp = generation
        busy = true
        error = nil
        defer { if generation == stamp { busy = false } }
        do {
            let result = try await service.createShare(workflow: workflow, accountId: accountId)
            guard generation == stamp else { return }
            share = result
            projectionExists = true
            revoked = false
            message = AppStrings.workflowTemplate(.link_created)
            await onChanged?()
        } catch {
            guard generation == stamp else { return }
            self.error = error.localizedDescription
        }
    }

    private func toggleRevocation() async {
        guard !busy, projectionExists else { return }
        let stamp = generation
        busy = true
        error = nil
        defer { if generation == stamp { busy = false } }
        do {
            if revoked {
                try await service.unrevoke(workflowId: workflow.id, accountId: accountId)
                guard generation == stamp else { return }
                message = AppStrings.workflowTemplate(.access_restored)
            } else {
                try await service.revoke(workflowId: workflow.id, accountId: accountId,
                                         shortToken: share?.shortToken)
                guard generation == stamp else { return }
                share = nil
                message = AppStrings.workflowTemplate(.revoked)
            }
            revoked.toggle()
            await onChanged?()
        } catch {
            guard generation == stamp else { return }
            self.error = error.localizedDescription
        }
    }

    private func copy(_ url: URL) {
        #if canImport(UIKit)
        UIPasteboard.general.string = url.absoluteString
        #elseif canImport(AppKit)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(url.absoluteString, forType: .string)
        #endif
        message = AppStrings.workflowTemplate(.link_copied)
    }
}

struct WorkflowTemplateImportPanel: View {
    let templateId: String
    let fragmentKey: String
    let accountId: String
    var onImported: ((WorkflowDetail) async -> Void)? = nil
    var onEnabled: ((WorkflowDetail) async -> Void)? = nil
    // The debug preview host injects a locally decrypted synthetic projection.
    // Production keeps loading the recipient projection through the service.
    #if DEBUG
    var previewPayload: WorkflowTemplatePayload? = nil
    #else
    private var previewPayload: WorkflowTemplatePayload? { nil }
    #endif

    @State private var service = WorkflowTemplateShareService()
    @State private var payload: WorkflowTemplatePayload?
    @State private var imported: WorkflowTemplateImported?
    @State private var previewImported = false
    @State private var completedBindingIds = Set<String>()
    @State private var busy = false
    @State private var error: String?
    @State private var message: String?
    @State private var generation = 0

    private var bindingsComplete: Bool {
        let requirements = imported?.bindingRequirements ?? (previewImported ? previewPayload?.bindingRequirements : nil)
        guard let requirements else { return false }
        return requirements.allSatisfy { completedBindingIds.contains(bindingId($0)) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing5) {
            if let payload {
                Text(AppStrings.workflowTemplate(.preview_label))
                    .font(.omSmall.weight(.heavy))
                    .textCase(.uppercase)
                Text(payload.title)
                    .font(.omH3)
                    .accessibilityIdentifier("workflow-template-title")
                if let description = payload.description {
                    Text(description).foregroundStyle(Color.fontSecondary)
                }
                Text(AppStrings.workflowTemplatePreviewSummary(stepCount: payload.nodeTemplates.count + 1))
                    .font(.omP)
                    .foregroundStyle(Color.fontSecondary)

                if let imported {
                    bindings(imported.bindingRequirements)
                } else if previewImported {
                    bindings(payload.bindingRequirements)
                } else {
                    Button(AppStrings.workflowTemplate(busy ? .importing : .import)) {
                        Task { await importTemplate(payload) }
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(busy || accountId.isEmpty)
                    .accessibilityIdentifier("workflow-template-import")
                }
            } else if busy {
                ProgressView()
            }
            if let message { Text(message).font(.omSmall).foregroundStyle(Color.fontSecondary) }
            if let error { Text(error).font(.omSmall).foregroundStyle(Color.error) }
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius8))
        .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey30, lineWidth: 1))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-template-preview")
        .task(id: "\(accountId)|\(templateId)") { await load() }
        .onDisappear { generation &+= 1 }
    }

    private func bindings(_ requirements: [WorkflowTemplateBindingRequirement]) -> some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(AppStrings.workflowTemplate(.complete_before_enable))
                .font(.omP.weight(.semibold))
            Text(AppStrings.workflowTemplate(.binding_explanation))
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)
            ForEach(requirements, id: \.nodeId) { requirement in
                HStack(spacing: .spacing3) {
                    Text(bindingLabel(requirement))
                    Spacer()
                    if completedBindingIds.contains(bindingId(requirement)) {
                        Text(AppStrings.workflowTemplate(.completed))
                            .font(.omSmall.weight(.semibold))
                            .foregroundStyle(Color(hex: 0x067647))
                    } else {
                        Button(AppStrings.workflowTemplate(.mark_complete)) {
                            Task { await complete(requirement) }
                        }
                        .buttonStyle(OMSecondaryButtonStyle())
                        .disabled(busy)
                        .accessibilityIdentifier("workflow-template-complete-binding")
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("workflow-template-binding-\(bindingId(requirement))")
            }
            Button(AppStrings.workflowTemplate(busy ? .enabling : .enable)) {
                if let imported { Task { await enable(imported) } }
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(busy || !bindingsComplete || previewPayload != nil)
            .accessibilityIdentifier("workflow-template-enable")
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-template-bindings")
    }

    private func load() async {
        generation &+= 1
        let stamp = generation
        payload = nil
        imported = nil
        previewImported = false
        completedBindingIds = []
        guard !accountId.isEmpty else { return }
        if let previewPayload {
            payload = previewPayload
            return
        }
        busy = true
        defer { if generation == stamp { busy = false } }
        do {
            let opened = try await service.loadShared(
                templateId: templateId, fragmentKey: fragmentKey, accountId: accountId
            )
            guard generation == stamp else { return }
            payload = opened
        } catch {
            guard generation == stamp else { return }
            self.error = error.localizedDescription
        }
    }

    private func importTemplate(_ payload: WorkflowTemplatePayload) async {
        guard !busy, !accountId.isEmpty else { return }
        if previewPayload != nil {
            previewImported = true
            message = AppStrings.workflowTemplate(.import_done)
            return
        }
        let stamp = generation
        busy = true
        error = nil
        defer { if generation == stamp { busy = false } }
        do {
            let result = try await service.importTemplate(payload, accountId: accountId)
            guard generation == stamp else { return }
            imported = result
            message = AppStrings.workflowTemplate(.import_done)
            await onImported?(result.workflow)
        } catch {
            guard generation == stamp else { return }
            self.error = error.localizedDescription
        }
    }

    private func complete(_ requirement: WorkflowTemplateBindingRequirement) async {
        guard !busy, imported != nil || previewImported else { return }
        if previewImported {
            completedBindingIds.insert(bindingId(requirement))
            return
        }
        guard let imported else { return }
        let stamp = generation
        busy = true
        error = nil
        defer { if generation == stamp { busy = false } }
        do {
            try await service.completeBinding(
                workflowId: imported.workflow.id, requirement: requirement, accountId: accountId
            )
            guard generation == stamp else { return }
            completedBindingIds.insert(bindingId(requirement))
            message = AppStrings.workflowTemplate(.binding_done)
        } catch {
            guard generation == stamp else { return }
            self.error = error.localizedDescription
        }
    }

    private func enable(_ imported: WorkflowTemplateImported) async {
        guard !busy, bindingsComplete else { return }
        let stamp = generation
        busy = true
        error = nil
        defer { if generation == stamp { busy = false } }
        do {
            let workflow = try await service.enableImported(
                workflowId: imported.workflow.id, accountId: accountId
            )
            guard generation == stamp else { return }
            await onEnabled?(workflow)
        } catch {
            guard generation == stamp else { return }
            self.error = error.localizedDescription
        }
    }

    private func bindingId(_ requirement: WorkflowTemplateBindingRequirement) -> String {
        "\(requirement.type)-\(requirement.nodeId)"
    }

    private func bindingLabel(_ requirement: WorkflowTemplateBindingRequirement) -> String {
        switch requirement.type {
        case "schedule": AppStrings.workflowTemplate(.binding_schedule)
        case "app_skill": "\(AppStrings.workflowTemplate(.binding_app_skill)) \(requirement.appId ?? "") \(requirement.skillId ?? "")"
        case "notification_preferences": AppStrings.workflowTemplate(.binding_notifications)
        default: AppStrings.workflowTemplate(.binding_other)
        }
    }
}
