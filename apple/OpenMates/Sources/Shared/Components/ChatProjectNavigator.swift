// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.projects.nested-readable, chat-navigation.activity.global-running, chat-navigation.projects.organize
// Web source: components/chats/ChatProjectNavigator.svelte, utils/chatProjectNavigation.ts.
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.links.openmates-only-encrypted, projects.access.explicit-context, projects.surface.semantic-parity
import SwiftUI
import CoreTransferable
import UniformTypeIdentifiers
import CryptoKit

extension UTType {
    static let openMatesChat = UTType(exportedAs: "org.openmates.chat-organization", conformingTo: .data)
}

/// Only an opaque identity crosses the drag boundary; scope is checked again on drop.
struct ChatProjectDragPayload: Codable, Transferable, Equatable {
    let chatID: String
    let accountID: String
    let scope: UUID
    let serverOrigin: String
    let teamID: String?
    static var transferRepresentation: some TransferRepresentation {
        CodableRepresentation(contentType: .openMatesChat)
    }
}
struct ChatProjectLocation: Equatable {
    let projectID: String
    let folderID: String?
}
struct ChatSidebarProject: Identifiable {
    let project: ProjectWorkspaceProject
    let contents: ProjectWorkspaceContents
    var id: String { project.id }
    static func hash(_ id: String) -> String {
        SHA256.hash(data: Data(id.utf8)).map { String(format: "%02x", $0) }.joined()
    }
    func chatIDs(in folderID: String?, recursively: Bool = false) -> Set<String> {
        guard folderID == nil || contents.folders.contains(where: { $0.id == folderID }) else { return [] }
        var hashes: Set<String?> = [folderID.map(Self.hash)]
        if recursively {
            var previous = -1
            while previous != hashes.count {
                previous = hashes.count
                for folder in contents.folders where hashes.contains(folder.parentHash) { hashes.insert(Self.hash(folder.id)) }
            }
        }
        return Set(contents.items.filter { $0.kind == "chat" && hashes.contains($0.folderHash) }.map(\.targetID))
    }
    func parentLocation(of folderID: String?) -> ChatProjectLocation? {
        let ancestors = breadcrumbs(folderID)
        guard !ancestors.isEmpty else { return nil }
        return .init(projectID: id, folderID: ancestors.count == 1 ? nil : ancestors[ancestors.count - 2].id)
    }
    func breadcrumbs(_ folderID: String?) -> [ProjectWorkspaceFolder] {
        var result: [ProjectWorkspaceFolder] = [], visited: Set<String> = []
        var folder = contents.folders.first { $0.id == folderID }
        while let current = folder, visited.insert(current.id).inserted {
            result.insert(current, at: 0)
            folder = contents.folders.first { Self.hash($0.id) == current.parentHash }
        }
        return result
    }
}
struct ChatProjectNavigationContext {
    let projects: [ChatSidebarProject]
    let location: ChatProjectLocation?
    var runningIDs: Set<String> = []
    var activeSubChatCounts: [String: Int] = [:]
    var isOrganizing = false
    var errorMessage: String? = nil
    let navigate: (ChatProjectLocation?) -> Void
    let drop: (ChatProjectDragPayload, ChatProjectLocation) -> Void
    let createFolder: (ChatProjectLocation, String) -> Void
    let openProject: (String) -> Void
}

struct ChatProjectNavigator: View {
    let context: ChatProjectNavigationContext
    @State private var showsAncestors = false
    @State private var createsFolder = false
    @State private var folderName = ""
    private var project: ChatSidebarProject? { context.projects.first { $0.id == context.location?.projectID } }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if context.isOrganizing {
                HStack(spacing: .spacing6) { ProgressView(); Text(AppStrings.localized("chats.projects.organizing")).font(.omSmall) }.padding(.spacing6)
                    .accessibilityIdentifier("chat-project-organizing")
            }
            if let error = context.errorMessage { Text(error).font(.omSmall).foregroundStyle(Color.error).padding(.spacing4).accessibilityIdentifier("chat-project-error") }
            if let project, let location = context.location {
                let ancestors = project.breadcrumbs(location.folderID)
                HStack(spacing: .spacing2) {
                    Button {
                        context.navigate(project.parentLocation(of: location.folderID))
                    } label: { Icon("back", size: 16) }.accessibilityLabel(AppStrings.localized("chats.projects.up"))
                    Button(project.project.name) { context.navigate(.init(projectID: project.id, folderID: nil)) }
                        .font(.omSmall).lineLimit(1)
                    if ancestors.count > 1 {
                        Button { showsAncestors.toggle() } label: { Icon("more", size: 16) }
                            .accessibilityLabel(AppStrings.localized("chats.projects.ancestors"))
                    }
                    if let current = ancestors.last { Text(current.name).font(.omSmall).lineLimit(1) }
                }.padding(.spacing4).accessibilityIdentifier("chat-project-breadcrumb")
                if showsAncestors {
                    ForEach(ancestors) { folder in
                        Button(folder.name) { context.navigate(.init(projectID: project.id, folderID: folder.id)); showsAncestors = false }
                            .font(.omSmall).padding(.spacing4)
                    }
                }
                HStack {
                    Button { createsFolder.toggle() } label: {
                        HStack(spacing: .spacing4) { LucideNativeIcon("plus", size: 14); Text(AppStrings.localized("chats.projects.new_folder")).font(.omSmall) }
                    }
                    Spacer()
                    Button { context.openProject(project.id) } label: { LucideNativeIcon("external-link", size: 16) }
                        .accessibilityLabel(AppStrings.localized("chats.projects.open"))
                }.padding(.spacing4)
                if createsFolder {
                    HStack(spacing: .spacing4) {
                        TextField(AppStrings.localized("chats.projects.folder_name"), text: $folderName).textFieldStyle(OMTextFieldStyle())
                        Button { context.createFolder(location, folderName); folderName = ""; createsFolder = false } label: { LucideNativeIcon("plus", size: 16) }
                            .disabled(folderName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }.padding(.spacing4).accessibilityIdentifier("chat-project-new-folder")
                }
                ForEach(project.contents.folders.filter { $0.parentHash == location.folderID.map(ChatSidebarProject.hash) }) { folder in
                    row(project: project, name: folder.name, location: .init(projectID: project.id, folderID: folder.id), identifier: "chat-project-folder-\(folder.id)")
                }
            } else {
                ForEach(context.projects) { project in
                    row(project: project, name: project.project.name, location: .init(projectID: project.id, folderID: nil), identifier: "chat-project-root-\(project.id)")
                }
            }
        }.buttonStyle(.plain).foregroundStyle(Color.fontPrimary).padding(.vertical, .spacing4)
            .accessibilityElement(children: .contain).accessibilityIdentifier("chat-project-navigation")
            .onChange(of: context.location) { _, _ in showsAncestors = false; createsFolder = false }
    }
    private func row(project: ChatSidebarProject, name: String, location: ChatProjectLocation, identifier: String) -> some View {
        Button { context.navigate(location) } label: {
            HStack(spacing: .spacing6) {
                if !project.chatIDs(in: location.folderID, recursively: true).isDisjoint(with: context.runningIDs) {
                    ChatProcessingWheel()
                } else { LucideNativeIcon("folder", size: 24) }
                Text(name).font(.omP).lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
                LucideNativeIcon("chevron-right", size: 16)
            }.frame(minHeight: 24).padding(.spacing6).frame(height: 48).contentShape(RoundedRectangle(cornerRadius: .radius3))
        }.accessibilityIdentifier(identifier)
            .dropDestination(for: ChatProjectDragPayload.self) { payloads, _ in
                guard let payload = payloads.first else { return false }
                context.drop(payload, location); return true
            }
    }
}
struct ChatProjectDragModifier: ViewModifier {
    let payload: ChatProjectDragPayload?
    let onDrop: ((ChatProjectDragPayload) -> Void)?
    @ViewBuilder func body(content: Content) -> some View {
        if let payload, let onDrop {
            content.draggable(payload).dropDestination(for: ChatProjectDragPayload.self) { values, _ in
                NativeDragDiagnostics.record("sidebar.drop.invoked;values=\(values.count)")
                guard let source = values.first, source.chatID != payload.chatID else { NativeDragDiagnostics.record("sidebar.drop.guardRejected"); return false }
                NativeDragDiagnostics.record("sidebar.drop.accepted")
                onDrop(source); return true
            } isTargeted: { targeted in NativeDragDiagnostics.record("sidebar.targeted=\(targeted)") }
        } else { content }
    }
}

@MainActor
enum ChatProjectEligibility {
    static func canOrganize(_ chat: Chat, teamID: String?) -> Bool {
        !WelcomeScreenState.isPublicChat(chat.id) && !IncognitoChatSession.isIncognitoChatId(chat.id) &&
        chat.isSharedByOthers != true && !chat.isHiddenFromNormalSurfaces && chat.teamId == teamID
    }
}


// Web: chats/ProcessingWheel.svelte border2,24pt circle,900ms rotation.
struct ChatProcessingWheel: View {
    @Environment(\.accessibilityReduceMotion) private var reducedMotion
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: reducedMotion)) { timeline in
            let angle = reducedMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 0.9) / 0.9 * 360
            Circle().stroke(Color.grey30, lineWidth: 2)
                .overlay { Circle().trim(from: 0, to: 0.25).stroke(Color.fontPrimary, lineWidth: 2).rotationEffect(.degrees(angle - 135)) }
        }.frame(width: 24, height: 24)
            .accessibilityLabel(AppStrings.localized("common.processing"))
            .accessibilityAddTraits(.isImage).accessibilityIdentifier("chat-processing-wheel")
    }
}
