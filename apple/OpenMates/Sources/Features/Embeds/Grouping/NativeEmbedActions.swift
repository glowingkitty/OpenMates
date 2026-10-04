// Fullscreen OS-owned calendar and file actions. No calendar writes occur here.
// Web: utils/calendarDownload.ts, embeds/UnifiedEmbedFullscreen.svelte.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.persistence.client-encrypted
import Foundation
import Combine
import SwiftUI
import UniformTypeIdentifiers
#if os(iOS)
import UIKit
import EventKit
import EventKitUI
#elseif os(macOS)
import AppKit
#endif

@MainActor
struct EmbedReportIssueAction {
    let open: (ReportIssuePrefill) -> Void
}
private struct EmbedReportIssueActionKey: EnvironmentKey {
    static let defaultValue: EmbedReportIssueAction? = nil
}
extension EnvironmentValues {
    var embedReportIssueAction: EmbedReportIssueAction? {
        get { self[EmbedReportIssueActionKey.self] }
        set { self[EmbedReportIssueActionKey.self] = newValue }
    }
}

enum NativeEmbedActionURL {
    static func external(_ value: String) -> URL? {
        guard let parts = URLComponents(string: value), ["https", "http"].contains(parts.scheme?.lowercased() ?? ""),
              parts.host?.isEmpty == false, parts.user == nil, parts.password == nil else { return nil }
        return parts.url
    }
}

struct NativeEmbedExportFile: Equatable {
    let filename: String
    let bytes: Data
    let mimeType: String

    init(filename: String, bytes: Data, mimeType: String) {
        self.filename = ChatSettingsExport.safeFilename(filename, fallback: "download.bin")
        self.bytes = bytes; self.mimeType = mimeType
    }
}

struct NativeEmbedActionFence: Equatable {
    let accountGeneration: UUID
    let selectionGeneration: UUID
    let teamEpoch: UInt64
    let teamID: String?
    init(accountGeneration: UUID, selectionGeneration: UUID, teamEpoch: UInt64 = 0, teamID: String? = nil) {
        self.accountGeneration = accountGeneration; self.selectionGeneration = selectionGeneration
        self.teamEpoch = teamEpoch; self.teamID = teamID
    }
    func permits(account: UUID, selection: UUID, teamEpoch: UInt64 = 0, teamID: String? = nil) -> Bool {
        accountGeneration == account && selectionGeneration == selection && self.teamEpoch == teamEpoch && self.teamID == teamID
    }
}

/// Completion belongs to one OS presentation and its own temporary directory.
/// An old dismissal must never release another presentation's export bytes.
struct NativeEmbedPresentationLease {
    let controller: ObjectIdentifier
    let directory: URL?
    init(controller: AnyObject, directory: URL?) {
        self.controller = ObjectIdentifier(controller); self.directory = directory
    }
    func permits(controller: AnyObject?, directory: URL?) -> Bool {
        guard let controller else { return false }
        return self.controller == ObjectIdentifier(controller) && self.directory == directory
    }
}

@MainActor
final class NativeEmbedActionController: NSObject, ObservableObject {
    @Published private(set) var isDownloading = false
    private var selectionGeneration = UUID()
    private var task: Task<Void, Never>?
    private var directory: URL?
    private var teamObserver: AnyCancellable?
    private var actionTeamEpoch: UInt64?
    #if os(iOS)
    private var platformController: UIViewController?
    #elseif os(macOS)
    private var savePanel: NSSavePanel?
    #endif

    override init() {
        super.init()
        teamObserver = TeamWorkspaceContext.shared.$contextEpoch.dropFirst().sink { [weak self] _ in
            Task { @MainActor in
                // Read the latest epoch after @Published completes its mutation.
                // A queued older notification cannot cancel a new team's export.
                guard let self, let activeEpoch = self.actionTeamEpoch,
                      activeEpoch != TeamWorkspaceContext.shared.contextEpoch else { return }
                self.cancel()
            }
        }
    }

    private func currentFence() -> NativeEmbedActionFence {
        .init(accountGeneration: OfflineStore.shared.scopeGeneration, selectionGeneration: selectionGeneration,
              teamEpoch: TeamWorkspaceContext.shared.contextEpoch, teamID: TeamWorkspaceContext.shared.teamID)
    }
    private func check(_ fence: NativeEmbedActionFence) throws {
        guard fence.permits(account: OfflineStore.shared.scopeGeneration, selection: selectionGeneration,
                            teamEpoch: TeamWorkspaceContext.shared.contextEpoch, teamID: TeamWorkspaceContext.shared.teamID) else { throw CancellationError() }
    }

    func cancel() {
        selectionGeneration = UUID(); task?.cancel(); task = nil; isDownloading = false; actionTeamEpoch = nil
        #if os(iOS)
        platformController?.dismiss(animated: false); platformController = nil
        #elseif os(macOS)
        savePanel?.cancel(nil); savePanel = nil
        #endif
        cleanup()
    }

    func download(load: @escaping () async throws -> NativeEmbedExportFile,
                  validate: @escaping () throws -> Void = {}) {
        guard !isDownloading else { return }
        let fence = currentFence(); actionTeamEpoch = fence.teamEpoch
        isDownloading = true
        task = Task { [weak self] in
            guard let self else { return }
            do {
                try validate()
                let file = try await load()
                try Task.checkCancellation(); try validate()
                try self.check(fence)
                self.export(file, validate: {
                    try validate()
                    try self.check(fence)
                })
            } catch is CancellationError { }
            catch { if !Task.isCancelled { ToastManager.shared.show(AppStrings.error, type: .error) } }
            guard self.selectionGeneration == fence.selectionGeneration else { return }
            self.isDownloading = false; self.task = nil
        }
    }

    func export(_ file: NativeEmbedExportFile, validate: @escaping () throws -> Void = {}) {
        #if os(iOS)
        guard platformController == nil else { return }
        #elseif os(macOS)
        guard savePanel == nil else { return }
        #endif
        let fence = currentFence(); actionTeamEpoch = fence.teamEpoch
        let validateExport = {
            try validate()
            try self.check(fence)
        }
        do {
            try validateExport()
            #if os(iOS)
            guard let presenter = Self.presenter() else { throw URLError(.cannotOpenFile) }
            let url = try writeTemporary(file)
            let activity = UIActivityViewController(activityItems: [url], applicationActivities: nil)
            activity.view.accessibilityIdentifier = "native-embed-file-export"
            let lease = NativeEmbedPresentationLease(controller: activity, directory: directory)
            activity.completionWithItemsHandler = { [weak self] _, _, _, _ in
                Task { @MainActor in
                    guard let self, lease.permits(controller: self.platformController, directory: self.directory) else { return }
                    self.platformController = nil; self.cleanup()
                }
            }
            if let popover = activity.popoverPresentationController {
                popover.sourceView = presenter.view
                popover.sourceRect = CGRect(x: presenter.view.bounds.midX, y: presenter.view.bounds.maxY, width: 1, height: 1)
            }
            platformController = activity
            presenter.present(activity, animated: true)
            #elseif os(macOS)
            let panel = NSSavePanel(); savePanel = panel
            panel.nameFieldStringValue = file.filename; panel.canCreateDirectories = true
            panel.allowedContentTypes = [UTType(mimeType: file.mimeType) ?? UTType(filenameExtension: URL(fileURLWithPath: file.filename).pathExtension) ?? .data]
            let lease = NativeEmbedPresentationLease(controller: panel, directory: directory)
            panel.begin { [weak self, weak panel] response in
                guard let self, let panel, lease.permits(controller: self.savePanel, directory: self.directory) else { return }
                defer { self.savePanel = nil }
                guard response == .OK, let url = panel.url else { return }
                do { try validateExport(); try file.bytes.write(to: url, options: .atomic) }
                catch is CancellationError { }
                catch { ToastManager.shared.show(AppStrings.error, type: .error) }
            }
            #endif
        } catch is CancellationError { cleanup() }
        catch { cleanup(); ToastManager.shared.show(AppStrings.error, type: .error) }
    }

    func calendar(_ file: EmbedCalendarFile) {
        #if os(iOS)
        guard platformController == nil else { return }
        #elseif os(macOS)
        guard savePanel == nil else { return }
        #endif
        let fence = currentFence(); actionTeamEpoch = fence.teamEpoch
        do {
            try check(fence)
            #if os(iOS)
            guard let presenter = Self.presenter(), let input = file.event else { throw URLError(.cannotOpenFile) }
            let store = EKEventStore()
            let event = Self.makeEvent(input, store: store)
            let editor = EKEventEditViewController()
            editor.eventStore = store; editor.event = event; editor.editViewDelegate = self
            editor.view.accessibilityIdentifier = "native-embed-calendar-editor"
            platformController = editor
            presenter.present(editor, animated: true)
            #elseif os(macOS)
            let url = try writeTemporary(.init(filename: file.filename, bytes: Data(file.content.utf8), mimeType: "text/calendar"))
            // Opening ICS invokes Calendar's import confirmation, not a save-to-file panel.
            guard NSWorkspace.shared.open(url) else { throw URLError(.cannotOpenFile) }
            #endif
        } catch { cleanup(); ToastManager.shared.show(AppStrings.error, type: .error) }
    }

    #if os(iOS)
    static func makeEvent(_ input: EmbedCalendarEvent, store: EKEventStore) -> EKEvent {
        let event = EKEvent(eventStore: store)
        event.title = input.title; event.isAllDay = input.allDay
        event.startDate = input.allDay ? localCivilDate(input.start, timeZone: input.timeZone) : input.start
        event.endDate = input.allDay ? localCivilDate(input.end, timeZone: input.timeZone) : input.end
        event.timeZone = input.timeZone; event.location = input.location; event.notes = input.notes; event.url = input.sourceURL
        return event
    }
    private static func localCivilDate(_ date: Date, timeZone: TimeZone) -> Date {
        var utc = Calendar(identifier: .gregorian); utc.timeZone = TimeZone(secondsFromGMT: 0)!
        var local = Calendar(identifier: .gregorian); local.timeZone = timeZone
        return local.date(from: utc.dateComponents([.year, .month, .day], from: date)) ?? date
    }
    private static func presenter() -> UIViewController? {
        guard let scene = UIApplication.shared.connectedScenes.first(where: { $0.activationState == .foregroundActive }) as? UIWindowScene,
              var presenter = scene.windows.first(where: \.isKeyWindow)?.rootViewController else { return nil }
        while let presented = presenter.presentedViewController { presenter = presented }
        return presenter.isBeingDismissed ? nil : presenter
    }
    #endif

    private func writeTemporary(_ file: NativeEmbedExportFile) throws -> URL {
        cleanup()
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("openmates-embed-export", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        directory = root
        var url = root.appendingPathComponent(file.filename)
        #if os(iOS)
        try file.bytes.write(to: url, options: [.atomic, .completeFileProtection])
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete, .posixPermissions: 0o600], ofItemAtPath: url.path)
        #else
        try file.bytes.write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        #endif
        var values = URLResourceValues(); values.isExcludedFromBackup = true; try url.setResourceValues(values)
        return url
    }
    private func cleanup() { if let directory { try? FileManager.default.removeItem(at: directory) }; directory = nil }
}

#if os(iOS)
extension NativeEmbedActionController: @MainActor EKEventEditViewDelegate {
    func eventEditViewController(_ controller: EKEventEditViewController, didCompleteWith action: EKEventEditViewAction) {
        guard platformController === controller else { return }
        controller.dismiss(animated: true); platformController = nil
    }
}
#endif
