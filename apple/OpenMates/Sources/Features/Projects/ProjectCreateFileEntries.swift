// Project create-menu entries for new empty documents, sheets, slide decks and
// code files. Choosing an entry shows an inline name field (prefilled with the
// default name, selected on web); submit creates the file through the core and
// the parent opens it. Used by the Create menu of ProjectsWorkspaceView, which
// serves both the root and the folder menus of ProjectsPage.
//
// Web source: frontend/packages/ui/src/components/projects/ProjectCreateFileEntries.svelte
// CSS: .file-entries (grid, 1px top border), button (icon 1.25rem + label, 600
//   weight, hover/active grey-10), .name-form (input + submit, spacing-6 padding).
// Tokens: Color.grey10/grey30/fontPrimary/fontSecondary, .spacing4/.spacing6, .radius3.
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.items.create-documents
import SwiftUI

/// One create entry: web `entries[]` of ProjectCreateFileEntries.svelte.
struct ProjectCreateFileEntry: Identifiable, Equatable {
    let kind: ProjectDocumentKind
    let identifier: String
    let icon: String

    var id: ProjectDocumentKind { kind }

    /// The four entries in web order, with the web testids.
    static let all: [ProjectCreateFileEntry] = [
        .init(kind: .document, identifier: "project-create-document", icon: "docs"),
        .init(kind: .sheet, identifier: "project-create-sheet", icon: "sheets"),
        .init(kind: .slides, identifier: "project-create-slides", icon: "slides"),
        .init(kind: .code, identifier: "project-create-code", icon: "coding"),
    ]

    @MainActor var label: String {
        switch kind {
        case .document: AppStrings.projectCreateDocument
        case .sheet: AppStrings.projectCreateSheet
        case .slides: AppStrings.projectCreateSlides
        case .code: AppStrings.projectCreateCodeFile
        }
    }

    @MainActor var defaultName: String {
        switch kind {
        case .document: AppStrings.projectCreateDefaultDocumentName
        case .sheet: AppStrings.projectCreateDefaultSheetName
        case .slides: AppStrings.projectCreateDefaultSlidesName
        case .code: AppStrings.projectCreateDefaultCodeName
        }
    }
}

/// The inline name form state: which entry is pending and its name.
struct ProjectCreateFileDraft: Equatable {
    private(set) var pending: ProjectDocumentKind?
    var name = ""

    /// Choosing an entry opens the name field with the entry's default name.
    mutating func choose(_ kind: ProjectDocumentKind, defaultName: String) {
        pending = kind
        name = defaultName
    }

    mutating func cancel() { pending = nil }

    /// The trimmed name to create with; nil when nothing is pending or the name is blank.
    var submission: (kind: ProjectDocumentKind, name: String)? {
        guard let pending else { return nil }
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : (pending, trimmed)
    }

    static func == (lhs: Self, rhs: Self) -> Bool { lhs.pending == rhs.pending && lhs.name == rhs.name }
}

struct ProjectCreateFileEntries: View {
    /// Stacks the entries (root menu, compact) or spreads them in four columns (folder menu).
    var stacked: Bool
    var busy: Bool
    /// Creates and opens the file; true on success (the form closes).
    var onCreate: (ProjectDocumentKind, String) async -> Bool

    @State private var draft = ProjectCreateFileDraft()
    @FocusState private var nameFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            Color.grey30.frame(height: 1)
            if stacked {
                VStack(spacing: 0) {
                    ForEach(Array(ProjectCreateFileEntry.all.enumerated()), id: \.element.id) { index, entry in
                        if index > 0 { Color.grey30.frame(height: 1) }
                        entryButton(entry, leading: true)
                    }
                }
            } else {
                HStack(spacing: 0) {
                    ForEach(Array(ProjectCreateFileEntry.all.enumerated()), id: \.element.id) { index, entry in
                        if index > 0 { Color.grey30.frame(width: 1) }
                        entryButton(entry, leading: false)
                    }
                }
            }
            if draft.pending != nil { nameForm }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-create-file-entries")
    }

    private func entryButton(_ entry: ProjectCreateFileEntry, leading: Bool) -> some View {
        let active = draft.pending == entry.kind
        return Button {
            draft.choose(entry.kind, defaultName: entry.defaultName)
            nameFocused = true
        } label: {
            HStack(spacing: leading ? .spacing6 : .spacing4) {
                Icon(entry.icon, size: 20)
                Text(entry.label).font(.omP).fontWeight(.semibold)
            }
            .padding(.spacing6)
            .frame(maxWidth: .infinity, alignment: leading ? .leading : .center)
            .background(active ? Color.grey10 : Color.clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(leading ? Color.fontPrimary : Color.fontSecondary)
        .disabled(busy)
        .accessibilityIdentifier(entry.identifier)
    }

    private var nameForm: some View {
        VStack(spacing: 0) {
            Color.grey30.frame(height: 1)
            HStack(spacing: .spacing4) {
                TextField(AppStrings.projectCreateNameLabel, text: $draft.name)
                    .textFieldStyle(OMTextFieldStyle())
                    .focused($nameFocused)
                    .disabled(busy)
                    .onSubmit { submit() }
                    .accessibilityLabel(AppStrings.projectCreateNameLabel)
                    .accessibilityIdentifier("project-create-name-input")
                Button(AppStrings.projectCreateNameSubmit) { submit() }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(busy || draft.submission == nil)
                    .accessibilityIdentifier("project-create-name-submit")
            }
            .padding(.spacing6)
        }
    }

    private func submit() {
        guard !busy, let submission = draft.submission else { return }
        Task {
            if await onCreate(submission.kind, submission.name) { draft.cancel() }
        }
    }
}
