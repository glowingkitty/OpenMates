// DesignEmbroideryEmbedRenderer — native counterpart for design.embroidery result embeds.
// Preview: stitch preview on the fabric colour, sewn size, estimated time and thread
// length, thread swatches (converting / failed states show their text only).
// Fullscreen: Stitches/Graphic switch, numbers, downloads (all formats as one ZIP or one
// machine file, saved through the share sheet / save panel), thread list, notes.
//
// Not rendered natively: the "Change settings" form (EmbroiderySettingsForm.svelte). It only
// asks the assistant for a new conversion through the web follow-up composer, which Apple's
// result fullscreen does not host; the user asks the assistant in chat instead.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/design/DesignEmbroideryEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/design/DesignEmbroideryEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/design/EmbroideryDownloads.svelte
//          frontend/packages/ui/src/components/embeds/design/EmbroideryThreadList.svelte
//          frontend/packages/ui/src/components/embeds/design/EmbroideryThreadSwatches.svelte
// CSS:     the <style> blocks of those files (.stitch-preview, .switch, .stage, .download,
//          .threads li, .swatch, .notes, .reason)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import SwiftUI

/// Data colours (thread and fabric hex values) are content, not theme colours.
private extension Color {
    init?(embroideryHex hex: String) {
        guard EmbroideryDesignModel.isHexColour(hex) else { return nil }
        var digits = String(hex.dropFirst())
        if digits.count == 3 { digits = digits.map { "\($0)\($0)" }.joined() }
        guard digits.count >= 6, let value = UInt32(digits.prefix(6), radix: 16) else { return nil }
        self.init(.sRGB, red: Double((value >> 16) & 0xFF) / 255, green: Double((value >> 8) & 0xFF) / 255,
                  blue: Double(value & 0xFF) / 255, opacity: 1)
    }
}

struct DesignEmbroideryEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let embedID: String
    private let design: EmbroideryDesignModel

    @Environment(\.recipientMediaContext) private var recipient
    @StateObject private var actions = NativeEmbedActionController()
    @State private var showGraphic = false
    @State private var graphic: StaticSVGImageSource?

    init(data: [String: AnyCodable]?, mode: EmbedDisplayMode, embedID: String) {
        self.data = data
        self.mode = mode
        self.embedID = embedID
        design = EmbroideryDesignModel(data: data)
    }

    private var fabric: Color { Color(embroideryHex: EmbroideryDesignModel.fabricColourHex) ?? Color.grey10 }

    var body: some View {
        switch mode {
        case .preview: preview
        case .fullscreen: fullscreen
        }
    }

    // MARK: - Preview

    @ViewBuilder
    private var preview: some View {
        switch design.status {
        case .finished:
            VStack(alignment: .leading, spacing: .spacing3) {
                stitchImage(contentMode: .fit)
                    .padding(.spacing6)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(fabric)
                    .clipped()
                Text(design.skillTitle).font(.omSmall).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
                    .lineLimit(3).padding(.horizontal, .spacing6)
                VStack(alignment: .leading, spacing: .spacing3) {
                    VStack(alignment: .leading, spacing: 0) {
                        if !design.sizeLabel.isEmpty {
                            Text(design.sizeLabel).font(.omXxs).foregroundStyle(Color.fontSecondary)
                        }
                        if !effortText.isEmpty {
                            Text(effortText).font(.omXxs).foregroundStyle(Color.fontSecondary)
                        }
                    }
                    .accessibilityIdentifier("design-embroidery-numbers")
                    swatches
                }
                .padding(.horizontal, .spacing6)
                .padding(.bottom, EmbedPreviewFooterLayout.height + .spacing2)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("design-embroidery-preview")
            .accessibilityValue("finished")
        case .processing:
            previewMessage(title: design.skillTitle, text: AppStrings.embroideryConverting, state: "processing")
        case .error:
            previewMessage(title: design.skillTitle,
                           text: AppStrings.embroideryText(key: design.errorKey), state: "error")
        }
    }

    private func previewMessage(title: String, text: String, state: String) -> some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(title).font(.omSmall).fontWeight(.bold).foregroundStyle(Color.fontPrimary).lineLimit(3)
            Text(text).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(4)
        }
        .padding(.horizontal, .spacing6)
        .padding(.top, .spacing6)
        .padding(.bottom, EmbedPreviewFooterLayout.height + .spacing2)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("design-embroidery-preview")
        .accessibilityValue(state)
    }

    private var effortText: String {
        var parts: [String] = []
        if let minutes = design.estimatedMinutes { parts.append("~\(EmbroideryDesignModel.formatDuration(minutes))") }
        if let metres = design.threadLengthM {
            parts.append(AppStrings.embroideryThreadAmount(length: "~\(EmbroideryDesignModel.formatThreadLength(metres))"))
        }
        return parts.joined(separator: " · ")
    }

    /// `EmbroideryThreadSwatches.svelte`: up to eight 14pt swatches, then "+n".
    @ViewBuilder
    private var swatches: some View {
        if !design.threads.isEmpty {
            let shown = Array(design.threads.prefix(8))
            HStack(spacing: .spacing2) {
                ForEach(Array(shown.enumerated()), id: \.offset) { _, thread in
                    thread.swatch(size: 14).accessibilityIdentifier("design-embroidery-swatch")
                }
                if design.threads.count > 8 {
                    Text("+\(design.threads.count - 8)").font(.omXxs).foregroundStyle(Color.fontSecondary)
                }
            }
            .accessibilityHidden(true)
            .accessibilityIdentifier("design-embroidery-swatches")
        }
    }

    @ViewBuilder
    private func stitchImage(contentMode: ContentMode) -> some View {
        if let file = design.file("preview"), design.canDecrypt(file) {
            EncryptedImageView(
                s3Url: design.s3BaseUrl.isEmpty ? nil : design.s3BaseUrl, s3Key: file.s3Key, aesKey: design.aesKey,
                aesNonce: design.nonce(for: file), encryption: file.encryption, contentMode: contentMode)
                .accessibilityLabel(design.skillTitle)
                .accessibilityIdentifier("design-embroidery-preview-image")
        } else {
            Color.clear.accessibilityHidden(true)
        }
    }

    // MARK: - Fullscreen

    @ViewBuilder
    private var fullscreen: some View {
        switch design.status {
        case .error:
            VStack(spacing: .spacing2) {
                Text(AppStrings.embroideryFailed).font(.omP).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
                Text(AppStrings.embroideryText(key: design.errorKey)).font(.omP).foregroundStyle(Color.fontPrimary)
            }
            .multilineTextAlignment(.center)
            .padding(.spacing8)
            .frame(maxWidth: 544)
            .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius6))
            .frame(maxWidth: .infinity)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("design-embroidery-error")
        case .processing:
            Text(AppStrings.embroideryConverting).font(.omP).foregroundStyle(Color.fontSecondary)
                .frame(maxWidth: .infinity, minHeight: 200)
                .accessibilityIdentifier("design-embroidery-converting")
        case .finished:
            VStack(alignment: .leading, spacing: .spacing10) {
                VStack(spacing: .spacing5) {
                    if design.showsGraphicSwitch { viewSwitch }
                    stage
                }
                .frame(maxWidth: .infinity)
                summary
                downloads
                threadList
                notes
                if design.reworked {
                    Text(AppStrings.embroideryReworkedHint).font(.omSmall).foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("design-embroidery-reworked")
                }
            }
            .padding(.spacing6)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("design-embroidery-fullscreen")
            .task(id: showGraphic) { await loadGraphicIfNeeded() }
            .onDisappear { actions.cancel() }
        }
    }

    private var viewSwitch: some View {
        HStack(spacing: .spacing1) {
            switchButton(AppStrings.embroideryViewStitches, selected: !showGraphic, id: "design-embroidery-view-stitches") { showGraphic = false }
            switchButton(AppStrings.embroideryViewGraphic, selected: showGraphic, id: "design-embroidery-view-graphic") { showGraphic = true }
        }
        .padding(.spacing1)
        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius8))
    }

    private func switchButton(_ title: String, selected: Bool, id: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.omP)
                .foregroundStyle(selected ? Color.fontButton : Color.fontSecondary)
                .padding(.horizontal, .spacing8)
                .frame(minHeight: 44)
                .background(selected ? Color.buttonPrimary : Color.clear, in: RoundedRectangle(cornerRadius: .radius8))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityIdentifier(id)
    }

    private var stage: some View {
        Group {
            if showGraphic {
                if let graphic {
                    StaticSVGRemoteImageView(source: graphic, contentMode: .fit, onSuccess: {}, onFailure: {})
                        .allowsHitTesting(false)
                        .accessibilityLabel(design.skillTitle)
                        .accessibilityIdentifier("design-embroidery-image")
                } else {
                    ProgressView()
                }
            } else if design.file("preview") != nil {
                stitchImage(contentMode: .fit)
                    .accessibilityIdentifier("design-embroidery-image")
            } else {
                Text(AppStrings.embroideryPreviewUnavailable).font(.omP).foregroundStyle(Color.fontSecondary)
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: 320)
        .background(showGraphic ? Color.mediaLetterbox : fabric)
        .clipShape(RoundedRectangle(cornerRadius: .radius6))
    }

    private func loadGraphicIfNeeded() async {
        guard showGraphic, graphic == nil, let file = design.file("prepared_svg"), design.canDecrypt(file),
              let scope = OfflineStore.shared.activeScopeId ?? (recipient == nil ? nil : "recipient") else { return }
        do {
            let bytes = try await RecipientMediaContext.fetchAndDecrypt(
                context: recipient, s3Url: "", aesKeyHex: design.aesKey, aesNonceHex: design.nonce(for: file),
                encryption: file.encryption, s3Key: file.s3Key, cacheNamespace: scope, cachePolicy: .memoryOnly)
            graphic = StaticSVGImageSource(data: bytes)
        } catch { }
    }

    // MARK: Summary rows (ResultEmbedInfo)

    @ViewBuilder
    private var summary: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            if design.widthMm != nil {
                infoRow(AppStrings.embroiderySize, design.sizeLabel, id: "design-embroidery-size")
            }
            if let count = design.stitchCount {
                infoRow(AppStrings.embroideryStitches, EmbroideryDesignModel.formatCount(count), id: "design-embroidery-stitch-count")
            }
            if let changes = design.threadChanges {
                infoRow(AppStrings.embroideryThreadChanges, String(changes), id: "design-embroidery-thread-changes")
            }
            if let minutes = design.estimatedMinutes {
                infoRow(AppStrings.embroiderySewingTime, "~\(EmbroideryDesignModel.formatDuration(minutes))", id: "design-embroidery-time")
            }
            if let metres = design.threadLengthM {
                infoRow(AppStrings.embroideryThreadLength, "~\(EmbroideryDesignModel.formatThreadLength(metres))", id: "design-embroidery-thread-length")
            }
            if design.fitsHoop != .notChecked, !design.hoopLabel.isEmpty {
                let text = design.fitsHoop == .yes ? AppStrings.embroideryFitsHoop(design.hoopLabel) : AppStrings.embroideryTooLargeForHoop(design.hoopLabel)
                Text(text).font(.omSmall).fontWeight(.semibold)
                    .foregroundStyle(design.fitsHoop == .yes ? Color.success : Color.error)
                    .accessibilityIdentifier("design-embroidery-hoop-fit")
            }
            if let fabricName = design.fabric {
                infoRow(AppStrings.embroideryFabric, AppStrings.embroideryFabricName(fabricName), id: "design-embroidery-fabric-info")
            }
            if design.borderMm > 0 {
                infoRow(AppStrings.embroideryBorder, AppStrings.embroideryBorderMm(design.borderMm), id: "design-embroidery-border-info")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func infoRow(_ label: String, _ value: String, id: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: .spacing4) {
            Text(label).font(.omSmall).foregroundStyle(Color.fontSecondary)
            Spacer(minLength: .spacing4)
            Text(value).font(.omSmall).fontWeight(.semibold).foregroundStyle(Color.fontPrimary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(id)
    }

    // MARK: Downloads (EmbroideryDownloads.svelte)

    private var downloads: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(AppStrings.embroideryDownload).font(.omSmall).foregroundStyle(Color.fontSecondary)
            Button { downloadAll() } label: {
                HStack(spacing: .spacing4) {
                    Icon("download", size: 20)
                    Text(AppStrings.embroideryDownloadAll).font(.omP).fontWeight(.semibold)
                }
                .foregroundStyle(Color.fontButton)
                .frame(maxWidth: .infinity, minHeight: 52)
                .background(Color.buttonPrimary, in: RoundedRectangle(cornerRadius: .radius4))
            }
            .buttonStyle(.plain)
            .disabled(actions.isDownloading)
            .opacity(actions.isDownloading ? 0.6 : 1)
            .accessibilityIdentifier("design-embroidery-download-all")
            Text(AppStrings.embroideryDownloadSingle).font(.omSmall).foregroundStyle(Color.fontSecondary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 80), spacing: .spacing4)], spacing: .spacing4) {
                ForEach(EmbroideryDesignModel.formats, id: \.self) { format in
                    Button { downloadOne(format) } label: {
                        Text(format.uppercased()).font(.omP).fontWeight(.semibold)
                            .foregroundStyle(Color.fontPrimary)
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .background(Color.grey20, in: RoundedRectangle(cornerRadius: .radius4))
                    }
                    .buttonStyle(.plain)
                    .disabled(actions.isDownloading)
                    .opacity(actions.isDownloading ? 0.6 : 1)
                    .accessibilityIdentifier("design-embroidery-download-\(format)")
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("design-embroidery-downloads")
    }

    private func source(for format: String) throws -> NativeEmbedDownload.Source {
        guard let file = design.file(format), design.canDecrypt(file) else { throw URLError(.fileDoesNotExist) }
        return .encrypted(filename: "\(design.downloadBaseName).\(format)", mime: "application/octet-stream",
                          key: design.aesKey, nonce: design.nonce(for: file), marker: file.encryption, s3: file.s3Key)
    }

    private func downloadOne(_ format: String) {
        let scope = OfflineStore.shared.activeScopeId, recipient = recipient
        actions.download(load: { try await source(for: format).load(scope: scope, recipient: recipient) })
    }

    /// All machine formats in one "<name>.zip"; fails as a whole when any file is missing.
    private func downloadAll() {
        let scope = OfflineStore.shared.activeScopeId, recipient = recipient
        let name = design.downloadBaseName
        actions.download(load: {
            var entries: [(name: String, bytes: Data)] = []
            for format in EmbroideryDesignModel.formats {
                let file = try await source(for: format).load(scope: scope, recipient: recipient)
                entries.append((name: file.filename, bytes: file.bytes))
            }
            return NativeEmbedExportFile(filename: "\(name).zip", bytes: try NativeEmbedDownload.zip(entries: entries),
                                         mimeType: "application/zip")
        })
    }

    // MARK: Threads and notes

    @ViewBuilder
    private var threadList: some View {
        if !design.threads.isEmpty {
            let showMinutes = design.threads.contains { $0.estimatedMinutes != nil }
            VStack(alignment: .leading, spacing: .spacing4) {
                Text(AppStrings.embroideryThreads).font(.omSmall).foregroundStyle(Color.fontSecondary)
                VStack(spacing: .spacing2) {
                    ForEach(Array(design.threads.enumerated()), id: \.offset) { index, thread in
                        HStack(spacing: .spacing4) {
                            Text("\(index + 1)").font(.omSmall).foregroundStyle(Color.fontSecondary)
                                .frame(width: 24, alignment: .trailing)
                            thread.swatch(size: 20)
                            Text(thread.name).font(.omSmall).foregroundStyle(Color.fontPrimary).lineLimit(1)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Text(thread.threadLengthM.map { "~\(EmbroideryDesignModel.formatThreadLength($0))" }
                                 ?? "\(EmbroideryDesignModel.formatCount(thread.stitchCount)) \(AppStrings.embroideryStitchesUnit)")
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                            if showMinutes {
                                Text(thread.estimatedMinutes.map { "~\(EmbroideryDesignModel.formatDuration($0))" } ?? "")
                                    .font(.omSmall).foregroundStyle(Color.fontPrimary)
                                    .frame(width: 72, alignment: .trailing)
                            }
                        }
                        .padding(.vertical, .spacing3).padding(.horizontal, .spacing5)
                        .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius4))
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("design-embroidery-thread")
                    }
                }
                if showMinutes {
                    Text(AppStrings.embroiderySewingTimeNote).font(.omXs).foregroundStyle(Color.fontSecondary)
                        .accessibilityIdentifier("design-embroidery-time-note")
                }
            }
            .accessibilityIdentifier("design-embroidery-threads")
        }
    }

    @ViewBuilder
    private var notes: some View {
        if !design.notes.isEmpty {
            VStack(alignment: .leading, spacing: .spacing4) {
                Text(AppStrings.embroideryNotes).font(.omSmall).foregroundStyle(Color.fontSecondary)
                ForEach(Array(design.notes.enumerated()), id: \.offset) { _, note in
                    Text("• " + noteText(note)).font(.omSmall).foregroundStyle(Color.fontPrimary)
                        .accessibilityIdentifier("design-embroidery-note")
                }
            }
            .accessibilityIdentifier("design-embroidery-notes")
        }
    }

    private func noteText(_ note: EmbroideryNoteRow) -> String {
        guard let key = EmbroideryDesignModel.noteKey(note.code) else { return note.text }
        return AppStrings.embroideryText(key: key, replacements: ["count": String(note.count ?? 0), "mm": String(note.mm ?? 0)])
    }
}

private extension EmbroideryThreadRow {
    /// Thread colour dot with the thin neutral border that keeps white thread visible.
    func swatch(size: CGFloat) -> some View {
        Circle()
            .fill(Color(embroideryHex: colourHex) ?? Color.clear)
            .overlay(Circle().stroke(Color.grey40, lineWidth: 1))
            .frame(width: size, height: size)
    }
}
