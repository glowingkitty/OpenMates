// Web source: frontend/packages/ui/src/components/embeds/projects/ProjectReferenceEmbedPreview.svelte
//             frontend/packages/ui/src/components/embeds/projects/ProjectReferenceEmbedFullscreen.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.rendering.assistant-document-convergence
import SwiftUI

struct ProjectReferenceEmbedRenderer: View {
    let embed: EmbedRecord
    let mode: EmbedDisplayMode
    let onOpenEmbed: (EmbedRecord) -> Void
    let model: ProjectReferenceEmbedModel
    @State private var openingID: String?
    @State private var openTask: Task<Void, Never>?
    @State private var openError: String?

    init(embed: EmbedRecord, mode: EmbedDisplayMode, onOpenEmbed: @escaping (EmbedRecord) -> Void) {
        self.embed = embed
        self.mode = mode
        self.onOpenEmbed = onOpenEmbed
        model = ProjectReferenceEmbedModel(embed: embed)
    }
    private var summary: String {
        if model.status == .processing { return AppStrings.localized("embeds.projects.references.waiting") }
        return model.references.isEmpty ? AppStrings.localized("embeds.projects.references.empty")
            : LocalizationManager.shared.text("embeds.projects.references.count", replacements: ["count": "\(model.references.count)"])
    }

    var body: some View {
        Group {
            if mode == .preview {
                SearchPreviewIdentityLayout(horizontalInset: .spacing4) {
                    Color.clear
                } inputs: {
                    Text(model.title).font(.omSmall.weight(.semibold)).lineLimit(3)
                        .accessibilityIdentifier("project-reference-input")
                } summary: {
                    Text(summary).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
                }
                .accessibilityIdentifier("project-reference-preview")
            } else {
                VStack(alignment: .leading, spacing: .spacing3) {
                    if model.references.isEmpty {
                        Text(summary).font(.omSmall).foregroundStyle(Color.fontSecondary)
                            .padding(.spacing8).frame(maxWidth: .infinity)
                            .accessibilityIdentifier("project-reference-empty")
                    } else {
                        ForEach(model.references) { reference in
                            Button { open(reference) } label: {
                                HStack(spacing: .spacing3) {
                                    Icon("files", size: 24).foregroundStyle(Color.fontSecondary)
                                    VStack(alignment: .leading, spacing: .spacing1) {
                                        Text(reference.path).font(.omSmall.weight(.semibold))
                                            .fixedSize(horizontal: false, vertical: true)
                                        Text(reference.projectName + (reference.line.map { " · L\($0)" } ?? ""))
                                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                                    }.frame(maxWidth: .infinity, alignment: .leading)
                                    if openingID == reference.id {
                                        ProgressView().accessibilityLabel(AppStrings.localized("embeds.projects.references.opening"))
                                    } else { Text("›").font(.omH3).foregroundStyle(Color.fontSecondary) }
                                }
                                .padding(.vertical, .spacing3).padding(.horizontal, .spacing4)
                                .frame(minHeight: 68, alignment: .leading)
                                .background(Color.grey10)
                                .clipShape(RoundedRectangle(cornerRadius: .radius5))
                                .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey30, lineWidth: 1))
                                .contentShape(RoundedRectangle(cornerRadius: .radius5))
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("project-reference-row")
                        }
                    }
                    if let openError {
                        Text(openError).font(.omSmall).foregroundStyle(Color.error)
                            .accessibilityIdentifier("project-reference-open-error")
                    }
                }
                .padding(.horizontal, .spacing4).padding(.top, .spacing6).padding(.bottom, 120)
                .frame(maxWidth: 816).frame(maxWidth: .infinity, alignment: .top)
                .accessibilityIdentifier("project-reference-list")
            }
        }
        .foregroundStyle(Color.fontPrimary)
        .onDisappear { cancel() }
        .onChange(of: embed.id) { _, _ in cancel() }
    }

    private func open(_ reference: ProjectFileReference) {
        cancel()
        openingID = reference.id
        openTask = Task { @MainActor in
            do {
                let child = try await ProjectReferenceLoader.open(reference)
                guard !Task.isCancelled, openingID == reference.id else { return }
                openingID = nil
                onOpenEmbed(child)
            } catch {
                guard !Task.isCancelled, openingID == reference.id else { return }
                openingID = nil
                openError = AppStrings.localized("embeds.projects.references.open_failed")
            }
        }
    }
    private func cancel() {
        openTask?.cancel(); openTask = nil; openingID = nil; openError = nil
    }
}
