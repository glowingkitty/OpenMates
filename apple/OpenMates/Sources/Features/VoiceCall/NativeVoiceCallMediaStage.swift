// Call media stage: the camera preview plus completed generated images and
// videos from the call's assistant answers, with paging and an AI badge.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/voicecall/VoiceCallMedia.svelte
// TS:      frontend/packages/ui/src/services/voiceCall.ts (refreshCallMedia, selectMedia, showCamera)
//          frontend/packages/ui/src/services/voiceCallMedia.ts (owned plaintext URLs)
// CSS:     VoiceCallMedia.svelte <style> — .call-media, .camera.inset, .ai-badge, .media-navigation, .round
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.video.generated-media-stage
//
// Which embeds appear and which one is shown is decided by the shared Rust
// core (voice_call_media via view_voice_call bindings). This file only fetches
// and decrypts the chosen files with the existing media client and draws them.

#if !os(watchOS)
import AVKit
import SwiftUI

@MainActor
final class NativeVoiceCallMediaModel: ObservableObject {
    enum Kind: Equatable { case image, video }
    struct Item: Identifiable, Equatable {
        let id: String
        let kind: Kind
        let image: CGImage?
        let videoURL: URL?
        static func == (lhs: Item, rhs: Item) -> Bool { lhs.id == rhs.id && lhs.kind == rhs.kind }
    }

    typealias Loader = @MainActor (NativeVoiceCallMediaPolicy.StageMedia, [String: AnyCodable]) async -> Item?

    @Published private(set) var items: [Item] = []
    @Published private(set) var displayedIndex: Int?
    /// Called when a fresh result must expand the stage (web clears the camera collapse).
    var expand: () -> Void = {}

    private var presented: [String] = []
    private var loaded: [String: Item] = [:]
    private var generation = 0
    private var refresh: Task<Void, Never>?
    private var dirty: (candidates: [String], embeds: [String: EmbedRecord])?
    private var videoFiles: [URL] = []
    private let loader: Loader?

    /// `loader` replaces the encrypted S3 fetch in the local dev preview and tests only.
    init(loader: Loader? = nil) { self.loader = loader }

    var displayed: Item? {
        guard let displayedIndex, items.indices.contains(displayedIndex) else { return nil }
        return items[displayedIndex]
    }

    /// `candidates` are the call's assistant artifact ids, newest first.
    func update(candidates: [String], embeds: [String: EmbedRecord]) {
        guard !candidates.isEmpty else { return }
        if refresh != nil { dirty = (candidates, embeds); return }
        let mine = generation
        refresh = Task { [weak self] in
            var next: (candidates: [String], embeds: [String: EmbedRecord])? = (candidates, embeds)
            while let pass = next, let self, self.generation == mine {
                self.dirty = nil
                await self.apply(candidates: pass.candidates, embeds: pass.embeds, generation: mine)
                next = self.dirty
            }
            if let self, self.generation == mine { self.refresh = nil }
        }
    }

    func select(_ index: Int) {
        guard items.indices.contains(index) else { return }
        displayedIndex = index
        expand()
    }

    func showCamera() { displayedIndex = nil }

    func reset() {
        generation += 1
        refresh?.cancel(); refresh = nil; dirty = nil
        items = []; displayedIndex = nil; presented = []; loaded = [:]
        for file in videoFiles { try? FileManager.default.removeItem(at: file) }
        videoFiles = []
    }

    private func apply(candidates: [String], embeds: [String: EmbedRecord], generation mine: Int) async {
        let stage = NativeVoiceCallMediaPolicy.stageMedia(candidates: candidates, embeds: embeds)
        var resolved: [Item] = []
        for media in stage {
            if let ready = loaded[media.embedID] { resolved.append(ready); continue }
            guard let raw = embeds[media.embedID]?.rawData else { continue }
            let fetched: Item?
            if let loader { fetched = await loader(media, raw) } else { fetched = await load(media, raw: raw) }
            guard let item = fetched, generation == mine else { continue }
            loaded[media.embedID] = item
            resolved.append(item)
        }
        guard generation == mine else { return }
        let selection = NativeVoiceCallMediaPolicy.selection(
            items: resolved.map(\.id), presented: presented, displayed: displayed?.id)
        presented.append(contentsOf: selection.newlyPresented)
        items = resolved
        if selection.fresh, let index = selection.displayedIndex {
            displayedIndex = index
            expand()
        } else if displayedIndex != nil {
            displayedIndex = selection.displayedIndex
        }
    }

    private func load(_ media: NativeVoiceCallMediaPolicy.StageMedia, raw: [String: AnyCodable]) async -> Item? {
        let url = media.preview ? EmbedMediaPayload.previewS3URL(from: raw) : EmbedMediaPayload.s3URL(from: raw)
        let key = media.preview ? EmbedMediaPayload.previewS3Key(from: raw) : EmbedMediaPayload.s3Key(from: raw)
        guard let url, let aes = EmbedMediaPayload.string(raw, keys: ["aes_key"]) else { return nil }
        let nonce = EmbedMediaPayload.string(raw, keys: ["aes_nonce"])
        guard let data = try? await S3MediaClient.shared.fetchAndDecrypt(
            s3Url: url, aesKeyHex: aes, aesNonceHex: nonce,
            encryption: EmbedMediaPayload.encryption(from: raw), s3Key: key,
            cachePolicy: .memoryOnly) else { return nil }
        switch media.kind {
        case .image:
            guard let image = NativeImageRaster.uprightImage(from: data) else { return nil }
            return Item(id: media.embedID, kind: .image, image: image, videoURL: nil)
        case .video:
            let directory = FileManager.default.temporaryDirectory
                .appendingPathComponent("openmates-call-media", isDirectory: true)
            do {
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
                let file = directory.appendingPathComponent(UUID().uuidString + ".mp4")
                #if os(iOS)
                try data.write(to: file, options: [.atomic, .completeFileProtection])
                #else
                try data.write(to: file, options: .atomic)
                #endif
                videoFiles.append(file)
                return Item(id: media.embedID, kind: .video, image: nil, videoURL: file)
            } catch {
                NativeDiagnostics.warning("call media video write failed", category: "voice_call")
                return nil
            }
        }
    }
}

/// Binding glue for the core's call-stage policy (client/voice_call_media.rs).
enum NativeVoiceCallMediaPolicy {
    struct StageMedia { let embedID: String; let kind: NativeVoiceCallMediaModel.Kind; let preview: Bool }
    struct Selection { let displayedIndex: Int?; let fresh: Bool; let newlyPresented: [String] }

    static func stageMedia(candidates: [String], embeds: [String: EmbedRecord]) -> [StageMedia] {
        let inputs = embeds.values.map { record -> VoiceCallStageEmbedInput in
            let content = record.rawData.flatMap(contentJSON)
            return VoiceCallStageEmbedInput(
                embedId: record.id, appId: record.appId, skillId: record.skillId, embedType: record.type,
                status: record.status.rawValue, decryptionFailed: false,
                decryptionPending: content == nil, contentJson: content ?? "{}")
        }
        return voiceCallStageMediaItems(candidateIdsNewestFirst: candidates, embeds: inputs).map {
            StageMedia(embedID: $0.embedId, kind: $0.kind == .video ? .video : .image, preview: $0.variant == .preview)
        }
    }

    static func selection(items: [String], presented: [String], displayed: String?) -> Selection {
        let record = voiceCallStageMediaSelection(itemEmbedIds: items, presented: presented, displayedEmbedId: displayed)
        return Selection(displayedIndex: record.displayedIndex.map(Int.init), fresh: record.fresh,
                         newlyPresented: record.newlyPresented)
    }

    /// Decrypted content as the JSON object the core reads; nil when it cannot be expressed as JSON.
    private static func contentJSON(_ raw: [String: AnyCodable]) -> String? {
        let object = raw.mapValues(\.value)
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object) else { return nil }
        return String(data: data, encoding: .utf8)
    }
}

/// Stage shown above the call bar while the camera is on or a generated result is displayed.
struct NativeVoiceCallMediaStage: View {
    @ObservedObject var camera: NativeVoiceCallCameraModel
    @ObservedObject var media: NativeVoiceCallMediaModel
    #if os(iOS)
    @Environment(\.horizontalSizeClass) private var sizeClass
    private var compact: Bool { sizeClass == .compact }
    #else
    private let compact = false
    #endif

    var body: some View {
        let displayed = media.displayed
        if camera.enabled || displayed != nil {
            ZStack {
                    if let displayed {
                        generated(displayed).id(displayed.id)
                        aiBadge.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                        if media.items.count > 1 {
                            navigation.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                        }
                    }
                    if camera.enabled {
                        cameraView(inset: displayed != nil)
                    }
                    #if os(iOS)
                    if camera.enabled {
                        round("camera", id: "voice-call-camera-flip", label: "flip_camera") { Task { await camera.flip() } }
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    }
                    #endif
                    round("up", id: "voice-call-media-expand", label: camera.expanded ? "minimize" : "expand",
                          flipped: !camera.expanded) { camera.setStageExpanded(!camera.expanded) }
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
            }
            .frame(maxWidth: .infinity)
            .frame(height: camera.expanded ? 512 : 96)
            .background(Color.grey90)
            .clipShape(RoundedRectangle(cornerRadius: .radius6))
            .animation(.easeInOut(duration: 0.18), value: camera.expanded)
            .accessibilityElement(children: .contain)
            .accessibilityLabel(AppStrings.nativeCall("generated_media"))
            .accessibilityIdentifier("voice-call-media")
        }
    }

    @ViewBuilder
    private func generated(_ item: NativeVoiceCallMediaModel.Item) -> some View {
        switch item.kind {
        case .image:
            if let image = item.image {
                Image(decorative: image, scale: 1).resizable().scaledToFit()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .accessibilityLabel(AppStrings.nativeCall("generated_media"))
                    .accessibilityIdentifier("voice-call-generated-image")
            }
        case .video:
            if let url = item.videoURL {
                NativeVoiceCallGeneratedVideo(url: url)
                    .accessibilityLabel(AppStrings.nativeCall("generated_media"))
                    .accessibilityIdentifier("voice-call-generated-video")
            }
        }
    }

    @ViewBuilder
    private func cameraView(inset: Bool) -> some View {
        if inset {
            // web .camera.inset: 6rem × 4.5rem (4.5 × 3.375 at ≤480px), 2px grey-0 border, radius-4, bottom-left.
            NativeVoiceCallCameraSurface(model: camera)
                .frame(width: compact ? 72 : 96, height: compact ? 54 : 72)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
                .overlay(RoundedRectangle(cornerRadius: .radius4).stroke(Color.grey0, lineWidth: 2))
                .shadow(color: .black.opacity(0.15), radius: 6, y: 2)
                .overlay {
                    Button { media.showCamera() } label: { Color.clear.contentShape(Rectangle()) }
                        .buttonStyle(.plain)
                        .accessibilityLabel(AppStrings.nativeCall("show_camera"))
                        .accessibilityIdentifier("voice-call-show-camera")
                }
                .padding(.spacing4)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
        } else {
            NativeVoiceCallCameraSurface(model: camera)
        }
    }

    private var aiBadge: some View {
        Icon("ai", size: 20).foregroundStyle(Color.fontPrimary)
            .padding(.vertical, .spacing2).padding(.horizontal, .spacing4)
            .background(Color.grey0).clipShape(RoundedRectangle(cornerRadius: .radius4))
            .padding(.spacing4)
            .accessibilityLabel(AppStrings.nativeCall("ai_generated"))
            .accessibilityIdentifier("voice-call-media-ai")
    }

    private var navigation: some View {
        let index = media.displayedIndex ?? 0
        return HStack(spacing: compact ? 0 : .spacing2) {
            pager("back", id: "voice-call-media-previous", label: "previous_media", disabled: index <= 0) {
                media.select(index - 1)
            }
            Text("\(index + 1) / \(media.items.count)").font(.omSmall).foregroundStyle(Color.fontPrimary)
                .lineLimit(1).fixedSize()
            pager("back", id: "voice-call-media-next", label: "next_media", disabled: index >= media.items.count - 1,
                  rotated: true) { media.select(index + 1) }
        }
        .background(Color.grey0).clipShape(Capsule())
        .padding(.bottom, .spacing4)
    }

    private func pager(_ icon: String, id: String, label: String, disabled: Bool, rotated: Bool = false,
                       action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon(icon, size: 20).rotationEffect(.degrees(rotated ? 180 : 0)).foregroundStyle(Color.fontPrimary)
                .frame(width: 40, height: 40).contentShape(Circle())
        }
        .buttonStyle(.plain).disabled(disabled).opacity(disabled ? 0.35 : 1)
        .accessibilityLabel(AppStrings.nativeCall(label)).accessibilityIdentifier(id)
    }

    private func round(_ icon: String, id: String, label: String, flipped: Bool = false,
                       action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Icon(icon, size: 20).rotationEffect(.degrees(flipped ? 180 : 0)).foregroundStyle(Color.fontPrimary)
                .frame(width: 40, height: 40).background(Color.grey0).clipShape(Circle())
        }
        .buttonStyle(.plain).padding(.spacing4)
        .accessibilityLabel(AppStrings.nativeCall(label)).accessibilityIdentifier(id)
    }
}

/// A generated clip plays once, muted, then stays available with playback controls (web: autoplay muted controls, no loop).
private struct NativeVoiceCallGeneratedVideo: View {
    let url: URL
    @State private var player: AVPlayer?
    var body: some View {
        VideoPlayer(player: player)
            .onAppear {
                let player = AVPlayer(url: url)
                player.isMuted = true
                player.actionAtItemEnd = .pause
                self.player = player
                player.play()
            }
            .onDisappear { player?.pause(); player = nil }
    }
}
#if DEBUG
/// Local dev preview (message variants voice-call-media-*): real EmbedRecords run through the
/// core stage policy; only the encrypted S3 fetch is replaced by locally drawn images.
/// Pairs with web /dev/preview voicecall/VoiceCallMedia.
struct DevVoiceCallMediaStageFixture: View {
    let variant: String
    @StateObject private var camera = NativeVoiceCallCameraModel(sendState: { _ in }, sendFrame: { _ in })
    @StateObject private var media = NativeVoiceCallMediaModel(loader: { stage, _ in
        DevVoiceCallMediaStageFixture.render(stage.embedID)
    })

    var body: some View {
        // The stage draws nothing until a result exists, so the fixture task hangs on a real container.
        VStack(spacing: 0) {
            Color.clear.frame(height: 1)
            NativeVoiceCallMediaStage(camera: camera, media: media)
        }
            .task(id: variant) {
                media.expand = { [weak camera] in camera?.setStageExpanded(true) }
                let children = variant == "voice-call-media-multiple"
                    ? ["dev-call-image-1", "dev-call-image-2"] : ["dev-call-image-1"]
                var embeds = ["dev-call-generation": Self.record("dev-call-generation", raw: [
                    "app_id": "images", "skill_id": "generate", "status": "finished", "embed_ids": children])]
                for id in children {
                    embeds[id] = Self.record(id, raw: [
                        "type": "generated_image", "app_id": "images", "skill_id": "generate", "status": "finished",
                        "s3_base_url": "https://example.org/media", "aes_key": "00", "aes_nonce": "00",
                        "files": ["original": ["s3_key": "dev/\(id).png"]]])
                }
                media.update(candidates: ["dev-call-generation"], embeds: embeds)
                guard variant == "voice-call-media-collapsed" else { return }
                for _ in 0..<40 where media.displayed == nil { try? await Task.sleep(for: .milliseconds(50)) }
                camera.setStageExpanded(false)
            }
    }

    private static func record(_ id: String, raw: [String: Any]) -> EmbedRecord {
        EmbedRecord(id: id, type: "app:images:generate", status: .finished,
                    data: .raw(raw.mapValues(AnyCodable.init)), parentEmbedId: nil,
                    appId: "images", skillId: "generate", embedIds: nil, createdAt: nil)
    }

    @MainActor static func render(_ id: String) -> NativeVoiceCallMediaModel.Item? {
        let fill = id.hasSuffix("2") ? LinearGradient.appAudio : LinearGradient.primary
        guard let image = ImageRenderer(content: Rectangle().fill(fill).frame(width: 640, height: 480)).cgImage
        else { return nil }
        return .init(id: id, kind: .image, image: image, videoURL: nil)
    }
}
#endif
#endif
