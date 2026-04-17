// Inline attachment previews — shows previews of attached files in the message composer
// before sending. Mirrors the web app's enter_message/in_message_previews/.
// Supports images, PDFs, and generic file attachments with remove action.

import SwiftUI

struct InlineAttachmentPreview: View {
    let attachment: PendingAttachment
    let onRemove: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            previewContent
                .frame(width: 56, height: 56)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(attachment.filename)
                    .font(.omXs).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)

                Text(attachment.formattedSize)
                    .font(.omTiny)
                    .foregroundStyle(Color.fontTertiary)
            }
            .padding(.leading, .spacing3)

            Spacer()

            Button(action: onRemove) {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(Color.fontTertiary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Remove \(attachment.filename)")
        }
        .padding(.spacing3)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .contextMenu {
            Button { onRemove() } label: {
                Label("Remove", systemImage: "trash")
            }
        }
    }

    @ViewBuilder
    private var previewContent: some View {
        switch attachment.type {
        case .image:
            if let data = attachment.data {
                #if os(iOS)
                if let uiImage = UIImage(data: data) {
                    Image(uiImage: uiImage)
                        .resizable()
                        .scaledToFill()
                }
                #elseif os(macOS)
                if let nsImage = NSImage(data: data) {
                    Image(nsImage: nsImage)
                        .resizable()
                        .scaledToFill()
                }
                #endif
            } else {
                placeholderIcon("photo")
            }

        case .pdf:
            ZStack {
                Color.red.opacity(0.1)
                Image(systemName: "doc.richtext")
                    .font(.system(size: 24))
                    .foregroundStyle(.red)
            }

        case .file:
            ZStack {
                Color.grey20
                Image(systemName: iconForExtension(attachment.fileExtension))
                    .font(.system(size: 24))
                    .foregroundStyle(Color.fontSecondary)
            }
        }
    }

    private func placeholderIcon(_ name: String) -> some View {
        ZStack {
            Color.grey20
            Image(systemName: name)
                .font(.system(size: 24))
                .foregroundStyle(Color.fontSecondary)
        }
    }

    private func iconForExtension(_ ext: String?) -> String {
        switch ext?.lowercased() {
        case "pdf": return "doc.richtext"
        case "doc", "docx": return "doc.text"
        case "xls", "xlsx", "csv": return "tablecells"
        case "zip", "tar", "gz": return "archivebox"
        case "mp3", "wav", "m4a": return "waveform"
        case "mp4", "mov", "avi": return "video"
        case "txt", "md": return "doc.plaintext"
        default: return "doc"
        }
    }
}

// MARK: - Pending attachment model

struct PendingAttachment: Identifiable {
    let id = UUID()
    let filename: String
    let data: Data?
    let type: AttachmentType
    let size: Int

    enum AttachmentType {
        case image, pdf, file
    }

    var fileExtension: String? {
        (filename as NSString).pathExtension.lowercased()
    }

    var formattedSize: String {
        ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file)
    }

    static func from(data: Data, filename: String) -> PendingAttachment {
        let ext = (filename as NSString).pathExtension.lowercased()
        let type: AttachmentType
        if ["jpg", "jpeg", "png", "gif", "heic", "webp"].contains(ext) {
            type = .image
        } else if ext == "pdf" {
            type = .pdf
        } else {
            type = .file
        }
        return PendingAttachment(filename: filename, data: data, type: type, size: data.count)
    }
}

// MARK: - Attachment list (shown above message input)

struct PendingAttachmentsList: View {
    let attachments: [PendingAttachment]
    let onRemove: (PendingAttachment) -> Void

    var body: some View {
        if !attachments.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing2) {
                    ForEach(attachments) { attachment in
                        InlineAttachmentPreview(attachment: attachment) {
                            onRemove(attachment)
                        }
                        .frame(width: 220)
                    }
                }
                .padding(.horizontal, .spacing4)
            }
            .padding(.vertical, .spacing2)
        }
    }
}
