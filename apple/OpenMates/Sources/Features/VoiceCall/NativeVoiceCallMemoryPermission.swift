// SHADOW ONLY — no shipping target membership or native execution approval.
// Web source pinned at 78e8d99023: voiceCallTools.ts,
// chatSyncServiceHandlersAppSettings.ts, AppSettingsMemoriesPermissionDialog.svelte.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.privacy.first-call-warning
#if !os(watchOS)
import Combine
import Foundation
import SwiftUI

/// Plaintext choices exist only while a particular live call awaits a decision.
/// Every toggle starts off; only an explicit Include selected action releases data.
@MainActor
final class NativeVoiceCallMemoryPermission: ObservableObject {
    typealias Validation = @MainActor @Sendable () async throws -> Void
    struct Choice: Identifiable {
        let category: SettingsMemoryCategory
        let entry: SettingsMemoryEntry
        var id: String { category.id + ":" + entry.id }
    }
    struct Prompt: Identifiable {
        let id: UUID
        let scope: NativeVoiceCallScope
        let callID: String
        let request: NativeVoiceCallMemoryPolicy.Request
        let choices: [Choice]
        let categories: [SettingsMemoryCategory]
        var selectedIDs: Set<String> = []
        var deciding = false
    }
    @Published private(set) var prompt: Prompt?
    private let service: SettingsMemoryService
    private var operationID: UUID?
    private var continuation: CheckedContinuation<NativeVoiceCallArtifactDisposition, any Error>?
    private var validation: Validation?

    init(service: SettingsMemoryService? = nil) {
        self.service = service ?? SettingsMemoryService(observesSync: false, liveActivitySnapshot: { _ in })
    }

    /// Root invalidates synchronously on owner change, call termination or teardown.
    /// Cancellation never manufactures a broker answer or preserves plaintext.
    func invalidate() {
        operationID = nil; prompt = nil; validation = nil
        service.cancel()
        let waiting = continuation; continuation = nil
        waiting?.resume(throwing: CancellationError())
    }

    func request(scope: NativeVoiceCallScope, callID: String, frame: NativeVoiceCallFrame,
                 validate: @escaping Validation) async throws -> NativeVoiceCallArtifactDisposition {
        guard operationID == nil else { throw NativeVoiceCallError.invalidState }
        let request = try NativeVoiceCallMemoryPolicy.Request(scope: scope, callID: callID, frame: frame)
        let keys = request.keys
        // Native SettingsMemoryService does not load personal document memories.
        // Reject the whole unsupported request instead of approving a partial set.
        guard !request.requestsPersonalDocuments else { throw NativeVoiceCallError.unsupportedTransport }
        #if DEBUG
        guard !ProcessInfo.processInfo.arguments.contains("--ui-test-memory-fixture"),
              !ProcessInfo.processInfo.arguments.contains("--ui-test-memory-editor-fixture")
        else { throw NativeVoiceCallError.unsupportedTransport }
        #endif
        let id = UUID(); operationID = id
        defer { if operationID == id { invalidate() } }
        return try await withTaskCancellationHandler {
            try await validate(); try check(id)
            await service.load()
            try await validate(); try check(id)
            guard service.isAuthenticated else { throw NativeVoiceCallError.contextUnavailable }
            switch service.state {
            case .loaded, .empty: break
            default: throw NativeVoiceCallError.contextUnavailable
            }
            var categories: [SettingsMemoryCategory] = []
            for key in keys {
                // Match the complete catalog identity; never use broad app matches.
                guard let category = service.categories.first(where: { $0.appId + "-" + $0.categoryId == key })
                else { throw NativeVoiceCallError.unsupportedTransport }
                if !categories.contains(where: { $0.id == category.id }) { categories.append(category) }
            }
            let choices = categories.flatMap { category in
                service.entries(in: category).filter { !$0.isExample }.map { Choice(category: category, entry: $0) }
            }
            try NativeVoiceCallMemoryPolicy.validateBounds(choices.map { $0.entry.value })
            validation = validate
            return try await withCheckedThrowingContinuation { waiting in
                guard operationID == id, !Task.isCancelled else { waiting.resume(throwing: CancellationError()); return }
                continuation = waiting
                prompt = Prompt(id: id, scope: scope, callID: callID, request: request, choices: choices, categories: categories)
            }
        } onCancel: { [weak self] in
            Task { @MainActor in if self?.operationID == id { self?.invalidate() } }
        }
    }

    private func check(_ id: UUID) throws {
        try Task.checkCancellation()
        guard operationID == id else { throw CancellationError() }
    }
    func setSelected(_ selected: Bool, choiceID: String, promptID: UUID) {
        guard var current = prompt, current.id == promptID, !current.deciding,
              current.choices.contains(where: { $0.id == choiceID }) else { return }
        if selected { current.selectedIDs.insert(choiceID) } else { current.selectedIDs.remove(choiceID) }
        prompt = current
    }
    func decide(promptID: UUID, includeSelected: Bool) async {
        guard var current = prompt, current.id == promptID, !current.deciding,
              let validate = validation else { return }
        let selected = current.choices.filter { current.selectedIDs.contains($0.id) }
        guard !includeSelected || !selected.isEmpty else { return }
        current.deciding = true; prompt = current
        do {
            try await validate(); try check(promptID)
            let entries: [NativeVoiceCallJSON] = try (includeSelected ? selected : []).map { choice in
                var fields = choice.entry.fields
                // Restore the metadata stripped by SettingsMemoryService.decodePayload;
                // web shares this original decrypted object, never the hashed item key.
                fields["_original_item_key"] = .string(choice.entry.key)
                fields["settings_group"] = .string(choice.category.categoryId)
                let content = try JSONDecoder().decode(NativeVoiceCallJSON.self,
                    from: JSONEncoder().encode(SettingsMemoryValue.object(fields)))
                return .object(["app_id": .string(choice.category.appId),
                                "item_key": .string(choice.category.categoryId), "content": content])
            }
            let reply = try NativeVoiceCallMemoryPolicy.response(current.request, entries: entries)
            try check(promptID)
            let waiting = continuation; continuation = nil
            prompt = nil; validation = nil; service.cancel()
            waiting?.resume(returning: .response(reply))
        } catch {
            // Fail closed, including stale owner/call validation and encoding errors.
            invalidate()
        }
    }
}

/// Install at the persistent app root above the call controls. This is custom
/// OpenMates product UI; no platform sheet, alert, Toggle or default button style.
struct NativeVoiceCallMemoryPermissionOverlay: View {
    @ObservedObject var runtime: NativeVoiceCallMemoryPermission
    var body: some View {
        if let prompt = runtime.prompt {
            ZStack {
                Color.black.opacity(0.35).ignoresSafeArea()
                VStack(alignment: .leading, spacing: .spacing6) {
                    HStack(spacing: .spacing4) {
                        Icon("settings_memories", size: 24)
                        Text(AppStrings.localized("chat.permissions.title")).font(.omH3.weight(.semibold))
                    }
                    Text(AppStrings.localized("chat.permissions.question")).font(.omP)
                    ScrollView {
                        VStack(alignment: .leading, spacing: .spacing6) {
                            ForEach(prompt.categories) { category in
                                VStack(alignment: .leading, spacing: .spacing4) {
                                    Text(category.appName + " / " + category.categoryName).font(.omP.weight(.semibold))
                                    ForEach(prompt.choices.filter { $0.category.id == category.id }) { choice in
                                        HStack(alignment: .top, spacing: .spacing4) {
                                            OMToggle(isOn: Binding(get: { prompt.selectedIDs.contains(choice.id) },
                                                set: { runtime.setSelected($0, choiceID: choice.id, promptID: prompt.id) }),
                                                disabled: prompt.deciding,
                                                accessibilityIdentifier: "voice-memory-entry-" + choice.id)
                                                .accessibilityLabel(choice.entry.title(in: category))
                                            VStack(alignment: .leading, spacing: .spacing2) {
                                                Text(choice.entry.title(in: category)).font(.omP.weight(.semibold))
                                                Text(choice.entry.value).font(.omSmall).foregroundStyle(Color.fontSecondary)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }.frame(maxHeight: 360)
                    HStack(spacing: .spacing4) {
                        Button(AppStrings.localized("chat.permissions.include_selected")) {
                            Task { await runtime.decide(promptID: prompt.id, includeSelected: true) }
                        }.disabled(prompt.selectedIDs.isEmpty || prompt.deciding)
                            .accessibilityIdentifier("voice-memory-include-selected")
                        Button(AppStrings.localized("chat.permissions.reject_all")) {
                            Task { await runtime.decide(promptID: prompt.id, includeSelected: false) }
                        }.disabled(prompt.deciding).accessibilityIdentifier("voice-memory-reject-all")
                    }.buttonStyle(OMSettingsButtonStyle())
                }
                .padding(.spacing10).frame(maxWidth: 440)
                .background(Color.grey10).clipShape(RoundedRectangle(cornerRadius: .radius7))
                .overlay(RoundedRectangle(cornerRadius: .radius7).stroke(Color.grey25, lineWidth: 1))
                .padding(.spacing6)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("voice-memory-permission")
            }
        }
    }
}
#endif
