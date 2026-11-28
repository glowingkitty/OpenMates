// Edit a stored Project code file as its next version in the embed fullscreen:
// the header Edit button opens a monospaced editor; while editing the button is
// the check mark that saves and closes it. `CodeEmbedEditModel` builds the new
// stored content in the Rust core (`codeEmbedEditContent`: code, line_count,
// content_hash and version_number replaced, TOON encoded) and commits it with
// the version the edit was made on (`EmbedVersionsCoreClient.commitEdit`); a
// moved head shows `embed_user_edits.edit_conflict`, any other failure
// `embed_user_edits.edit_failed`. Nothing protocol-related is written here.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/code/CodeEmbedFullscreen.svelte
//          (toggleCodeEdit, saveEdit, canEdit)
//          frontend/packages/ui/src/services/rustCore/embeds/embedContentEdit.ts
// CSS:     CodeEmbedFullscreen.svelte <style>: .code-editor
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/embed-user-edits/specification.yml
// Assertions: embed-user-edits.edit.next-version, embed-user-edits.header.edit-save-button

import Combine
import Foundation
import SwiftUI

/// Builds the stored TOON content of an edit: current content object (JSON),
/// the new code and the new version number. The app uses the core's builder.
typealias CodeEmbedContentBuilder = (_ currentJson: String, _ code: String, _ version: Int64) throws -> String

@MainActor
final class CodeEmbedEditModel: ObservableObject {
    enum Failure: Equatable {
        case conflict
        case failed

        /// The text of the web error notification.
        @MainActor var message: String {
            switch self {
            case .conflict: return AppStrings.embedEditConflict
            case .failed: return AppStrings.embedEditFailed
            }
        }
    }

    @Published private(set) var isEditing = false
    @Published private(set) var isSaving = false
    @Published private(set) var failure: Failure?
    @Published var draft = ""

    private let client: EmbedVersionsCoreClient?
    private let buildContent: CodeEmbedContentBuilder

    init(client: EmbedVersionsCoreClient?,
         buildContent: @escaping CodeEmbedContentBuilder = { current, code, version in
             try codeEmbedEditContent(currentContent: current, code: code, versionNumber: version)
         }) {
        self.client = client
        self.buildContent = buildContent
    }

    /// Web `canEdit`: Project scope on a personal account, a finished embed,
    /// not a remote preview and no PII masking in the shown text.
    static func canEdit(availability: EmbedEditAvailability, finished: Bool, isRemotePreview: Bool, hasPII: Bool) -> Bool {
        guard case .available(let scope) = availability, case .project = scope else { return false }
        return finished && !isRemotePreview && !hasPII
    }

    func begin(code: String) {
        draft = code
        failure = nil
        isSaving = false
        isEditing = true
    }

    func cancel() {
        isEditing = false
        isSaving = false
        failure = nil
    }

    /// Saves `draft` as version `baseVersion + 1` of `embedId`. Returns the
    /// new version and closes the editor; on failure the editor stays open
    /// with `failure` set and `nil` is returned.
    func save(embedId: String, scope: EmbedScopeRecord, baseVersion: Int64, currentContent: [String: Any]) async -> Int64? {
        guard let client, isEditing, !isSaving else { return nil }
        isSaving = true
        failure = nil
        defer { isSaving = false }
        do {
            let json = try JSONSerialization.data(withJSONObject: currentContent)
            let content = try buildContent(String(decoding: json, as: UTF8.self), draft, baseVersion + 1)
            let outcome = try await client.commitEdit(embedId: embedId, scope: scope, baseVersion: baseVersion, content: content)
            isEditing = false
            return outcome.version
        } catch {
            failure = EmbedEditFailure.classify(error) == .versionConflict ? .conflict : .failed
            NativeDiagnostics.warning("code_embed_edit_failed class=\(EmbedEditFailure.classify(error).code)", category: "core_bridge")
            return nil
        }
    }
}

/// The header Edit button state (`embed-edit-button`; the check mark while editing).
struct CodeEmbedEditHeaderAction {
    let isEditing: Bool
    let isSaving: Bool
    let perform: () -> Void
}

/// The monospaced editor shown in place of the code while editing.
struct CodeEmbedEditor: View {
    @ObservedObject var model: CodeEmbedEditModel

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            TextEditor(text: $model.draft)
                .font(.omSmall.monospaced())
                .foregroundStyle(Color.fontPrimary)
                .scrollContentBackground(.hidden)
                .autocorrectionDisabledForCode()
                .padding(.spacing4)
                .frame(minHeight: 320)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
                .disabled(model.isSaving)
                .accessibilityIdentifier("code-editor-textarea")
            if let failure = model.failure {
                Text(failure.message)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
                    .accessibilityIdentifier("code-editor-error")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("code-editor")
    }
}

private extension View {
    /// Code is not prose: no autocorrection or capitalisation while typing.
    @ViewBuilder
    func autocorrectionDisabledForCode() -> some View {
        #if os(iOS)
        self.autocorrectionDisabled(true).textInputAutocapitalization(.never)
        #else
        self.autocorrectionDisabled(true)
        #endif
    }
}
