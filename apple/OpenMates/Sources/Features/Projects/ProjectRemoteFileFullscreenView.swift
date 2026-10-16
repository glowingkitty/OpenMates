// Web source: projects/ProjectsPage.svelte, embeds/UnifiedEmbedFullscreen.svelte,
// embeds/images/ImageEmbedFullscreen.svelte. Project transport remains source-owned.
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.files.connected-embed-previews, projects.surface.semantic-parity, projects.access.explicit-context
import SwiftUI
import ImageIO

/// Immutable decoded pixels cross the decode task boundary; no private byte cache is persisted.
struct ProjectRemoteFileImage: @unchecked Sendable {
    let pixels: CGImage
    static let maximumBytes = 64 * 1024 * 1024

    static func decode(url: URL) throws -> Self {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard let size = attributes[.size] as? NSNumber, size.intValue > 0,
              size.intValue <= maximumBytes,
              let source = CGImageSourceCreateWithURL(url as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary),
              let pixels = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceThumbnailMaxPixelSize: 1920,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceShouldCacheImmediately: true,
              ] as CFDictionary) else { throw ProjectsWorkspaceError.invalidResponse }
        return Self(pixels: pixels)
    }
}

/// Immutable preview data uses the shared inert SVG validator and renderer.
enum ProjectRemoteFilePreview: @unchecked Sendable {
    case raster(ProjectRemoteFileImage)
    case svg(StaticSVGImageSource)

    static func maximumBytes(path: String) -> Int {
        (path as NSString).pathExtension.lowercased() == "svg" ? 2_000_000 : ProjectRemoteFileImage.maximumBytes
    }

    static func decode(url: URL, path: String) throws -> Self {
        if (path as NSString).pathExtension.lowercased() == "svg" {
            let size = try FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber
            guard let size, size.intValue > 0, size.intValue <= maximumBytes(path: path),
                  let source = StaticSVGImageSource(data: try Data(contentsOf: url)) else {
                throw ProjectsWorkspaceError.invalidResponse
            }
            return .svg(source)
        }
        return .raster(try ProjectRemoteFileImage.decode(url: url))
    }
}

enum ProjectRemoteFilePresentation {
    static func isImage(_ path: String) -> Bool { ProjectRemotePreviewPolicy.appID(path) == "images" }

    /// Metadata is already decrypted in the browser listing: opening never waits for remote bytes.
    static func metadataEmbed(sourceID: String, entry: ProjectRemoteEntry) -> EmbedRecord {
        let appID = ProjectRemotePreviewPolicy.appID(entry.path)
        let type = appID == "images" ? "image" : "project-remote-file"
        return EmbedRecord(id: "remote:\(sourceID):\(entry.path)", type: type, status: .finished,
            data: .raw(["filename": AnyCodable(entry.name), "path": AnyCodable(entry.path),
                "language": AnyCodable(ProjectRemotePreviewPolicy.language(entry.path)),
                "size_bytes": AnyCodable(entry.sizeBytes ?? 0)]), parentEmbedId: nil,
            appId: appID, skillId: appID == "code" ? "code" : nil, embedIds: nil, createdAt: nil)
    }

    static func header(_ entry: ProjectRemoteEntry) -> EmbedFullscreenHeaderPresentation {
        let appID = ProjectRemotePreviewPolicy.appID(entry.path)
        return .init(title: entry.name, subtitle: entry.sizeBytes.map {
            ByteCountFormatter.string(fromByteCount: Int64($0), countStyle: .file)
        }, icon: appID == "images" ? "image" : appID == "code" ? "code" : appID == "docs" ? "docs" : appID == "pdf" ? "pdf" : "files")
    }
}

/// Projects supply scoped transport state inside the same fullscreen chrome as chat embeds.
struct ProjectRemoteFileFullscreenView: View {
    @ObservedObject var store: ProjectsWorkspaceStore
    let entry: ProjectRemoteEntry
    let originalFileActions: EmbedOriginalFileActions
    let onClose: () -> Void

    private var embed: EmbedRecord {
        let metadata = ProjectRemoteFilePresentation.metadataEmbed(sourceID: store.activeRemoteSourceID ?? "", entry: entry)
        return store.remoteEmbed ?? metadata
    }
    private var isImage: Bool { ProjectRemoteFilePresentation.isImage(entry.path) }
    private var usesCustomContent: Bool { isImage || store.remoteEmbed == nil }

    var body: some View {
        EmbedFullscreenContainer(embeds: [embed], initialEmbedId: embed.id,
            allEmbedRecords: [embed.id: embed], chatId: nil, onClose: onClose,
            originalFileActions: isImage ? nil : originalFileActions,
            headerPresentation: ProjectRemoteFilePresentation.header(entry),
            contentOverride: usesCustomContent ? AnyView(fileContent) : nil)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-remote-file-detail")
    }

    @ViewBuilder private var fileContent: some View {
        if let image = store.remoteImage, isImage {
            Image(decorative: image.pixels, scale: 1).resizable().scaledToFit()
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(entry.name)
                .accessibilityIdentifier("project-remote-image-rendered")
                .accessibilityValue("\(image.pixels.width)x\(image.pixels.height)")
        } else if let source = store.remoteSVG, isImage {
            StaticSVGRemoteImageView(source: source, contentMode: .fit,
                onSuccess: {}, onFailure: { store.reportRemoteSVGFailure(source) })
                .allowsHitTesting(false)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(entry.name)
                .accessibilityIdentifier("project-remote-image-rendered")
        } else if let error = store.remoteError {
            VStack(spacing: .spacing4) {
                Text(error).font(.omSmall).foregroundStyle(Color.error)
                    .accessibilityIdentifier("project-remote-file-error")
                Button(AppStrings.retry) { Task {
                    if isImage || ProjectRemotePreviewPolicy.canReadText(entry.path) { await store.openRemoteFile(entry) }
                    else { await store.downloadRemoteFile(entry.path) }
                } }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("project-remote-file-retry")
            }.frame(maxWidth: .infinity)
        } else if isImage || ProjectRemotePreviewPolicy.canReadText(entry.path) {
            ProgressView(AppStrings.projectRemoteOpening)
                .frame(maxWidth: .infinity, minHeight: 160)
                .accessibilityIdentifier("project-remote-file-opening")
        } else {
            VStack(spacing: .spacing4) {
                Text(entry.path).font(.omSmall).textSelection(.enabled)
                Text(AppStrings.projectRemoteOnDemand).font(.omSmall).foregroundStyle(Color.fontSecondary)
            }.frame(maxWidth: .infinity, minHeight: 160)
        }
    }
}
