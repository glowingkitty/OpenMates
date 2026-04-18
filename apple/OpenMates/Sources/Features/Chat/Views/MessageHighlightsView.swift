// Message text highlighting and annotation — select text ranges and save highlights.
// Mirrors the web app's message-highlights feature: selection toolbar, color picker,
// optional comment, and persistent highlight storage via the backend API.

import SwiftUI

struct MessageHighlight: Identifiable, Codable {
    let id: String
    let messageId: String
    let startOffset: Int
    let endOffset: Int
    let color: String
    let comment: String?
    let createdAt: String?
}

// MARK: - Highlighted text rendering

struct HighlightedMessageText: View {
    let content: String
    let highlights: [MessageHighlight]
    let onTapHighlight: (MessageHighlight) -> Void

    var body: some View {
        if highlights.isEmpty {
            Text(content)
                .font(.omP)
                .foregroundStyle(Color.fontPrimary)
                .textSelection(.enabled)
        } else {
            highlightedText
                .font(.omP)
                .foregroundStyle(Color.fontPrimary)
                .textSelection(.enabled)
        }
    }

    private var highlightedText: Text {
        var attributed = AttributedString(content)
        let sorted = highlights.sorted { $0.startOffset < $1.startOffset }

        for highlight in sorted {
            let utf8Start = content.utf8.index(content.utf8.startIndex, offsetBy: highlight.startOffset, limitedBy: content.utf8.endIndex) ?? content.utf8.endIndex
            let utf8End = content.utf8.index(content.utf8.startIndex, offsetBy: highlight.endOffset, limitedBy: content.utf8.endIndex) ?? content.utf8.endIndex

            guard utf8Start < utf8End else { continue }

            let startIdx = String.Index(utf8Start, within: content) ?? content.startIndex
            let endIdx = String.Index(utf8End, within: content) ?? content.endIndex

            let attrStart = AttributedString.Index(startIdx, within: attributed) ?? attributed.startIndex
            let attrEnd = AttributedString.Index(endIdx, within: attributed) ?? attributed.endIndex

            guard attrStart < attrEnd else { continue }
            let highlightColor = highlightUIColor(highlight.color)
            #if os(iOS)
            attributed[attrStart..<attrEnd].backgroundColor = UIColor(highlightColor.opacity(0.3))
            #elseif os(macOS)
            attributed[attrStart..<attrEnd].backgroundColor = NSColor(highlightColor.opacity(0.3))
            #endif
        }

        return Text(attributed)
    }

    private func highlightUIColor(_ name: String) -> Color {
        switch name {
        case "yellow": return .yellow
        case "green": return .green
        case "blue": return .blue
        case "pink": return .pink
        case "orange": return .orange
        default: return .yellow
        }
    }
}

// MARK: - Highlight toolbar (shown on text selection)

struct HighlightToolbar: View {
    let onHighlight: (String, String?) -> Void
    @State private var selectedColor = "yellow"
    @State private var comment = ""
    @State private var showComment = false

    private let colors = ["yellow", "green", "blue", "pink", "orange"]

    var body: some View {
        VStack(spacing: .spacing3) {
            HStack(spacing: .spacing3) {
                ForEach(colors, id: \.self) { color in
                    Circle()
                        .fill(colorFor(color))
                        .frame(width: 28, height: 28)
                        .overlay {
                            if selectedColor == color {
                                Image(systemName: "checkmark")
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(.white)
                            }
                        }
                        .onTapGesture { selectedColor = color }
                }

                Divider().frame(height: 24)

                Button {
                    showComment.toggle()
                } label: {
                    Image(systemName: "text.bubble")
                        .foregroundStyle(showComment ? Color.buttonPrimary : Color.fontSecondary)
                }

                Button {
                    onHighlight(selectedColor, showComment ? comment : nil)
                } label: {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 24))
                        .foregroundStyle(Color.buttonPrimary)
                }
            }

            if showComment {
                TextField("Add a note...", text: $comment)
                    .font(.omSmall)
                    .textFieldStyle(.roundedBorder)
            }
        }
        .padding(.spacing4)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
    }

    private func colorFor(_ name: String) -> Color {
        switch name {
        case "yellow": return .yellow
        case "green": return .green
        case "blue": return .blue
        case "pink": return .pink
        case "orange": return .orange
        default: return .yellow
        }
    }
}

// MARK: - Highlight detail popover

struct HighlightDetailView: View {
    let highlight: MessageHighlight
    let onDelete: () -> Void
    @Environment(\.dismiss) var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            if let comment = highlight.comment, !comment.isEmpty {
                Text(comment)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontPrimary)
            }

            if let created = highlight.createdAt {
                Text(created)
                    .font(.omTiny)
                    .foregroundStyle(Color.fontTertiary)
            }

            Button(role: .destructive) {
                onDelete()
                dismiss()
            } label: {
                Label("Remove Highlight", systemImage: "trash")
                    .font(.omSmall)
            }
        }
        .padding(.spacing4)
    }
}

// MARK: - Highlights manager

@MainActor
final class HighlightsManager: ObservableObject {
    @Published var highlights: [String: [MessageHighlight]] = [:]

    func loadHighlights(chatId: String) async {
        do {
            let response: [MessageHighlight] = try await APIClient.shared.request(
                .get, path: "/v1/chats/\(chatId)/highlights"
            )
            var grouped: [String: [MessageHighlight]] = [:]
            for highlight in response {
                grouped[highlight.messageId, default: []].append(highlight)
            }
            highlights = grouped
        } catch {
            print("[Highlights] Load error: \(error)")
        }
    }

    func addHighlight(chatId: String, messageId: String, startOffset: Int, endOffset: Int, color: String, comment: String?) async {
        do {
            var body: [String: Any] = [
                "message_id": messageId,
                "start_offset": startOffset,
                "end_offset": endOffset,
                "color": color
            ]
            if let comment { body["comment"] = comment }

            let created: MessageHighlight = try await APIClient.shared.request(
                .post, path: "/v1/chats/\(chatId)/highlights", body: body
            )
            highlights[messageId, default: []].append(created)
        } catch {
            print("[Highlights] Add error: \(error)")
        }
    }

    func deleteHighlight(chatId: String, highlightId: String, messageId: String) async {
        do {
            let _: Data = try await APIClient.shared.request(
                .delete, path: "/v1/chats/\(chatId)/highlights/\(highlightId)"
            )
            highlights[messageId]?.removeAll { $0.id == highlightId }
        } catch {
            print("[Highlights] Delete error: \(error)")
        }
    }
}
