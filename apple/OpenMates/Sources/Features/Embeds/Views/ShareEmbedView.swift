// Share embed — generate a shareable link for an individual embed from fullscreen view.
// Mirrors the web app's share-embed-flow: link generation, copy, and native share sheet.

import SwiftUI

struct ShareEmbedView: View {
    let embedId: String
    let chatId: String
    @Environment(\.dismiss) var dismiss

    @State private var shareLink: String?
    @State private var isGenerating = false
    @State private var error: String?
    @State private var copied = false

    var body: some View {
        NavigationStack {
            Form {
                if let shareLink {
                    Section("Share Link") {
                        HStack {
                            Text(shareLink)
                                .font(.omSmall)
                                .lineLimit(2)
                                .textSelection(.enabled)
                                .accessibilityLabel("Share link: \(shareLink)")
                            Spacer()
                            Button {
                                copyToClipboard(shareLink)
                                copied = true
                                AccessibilityAnnouncement.announce("Link copied to clipboard")
                                Task {
                                    try? await Task.sleep(for: .seconds(2))
                                    copied = false
                                }
                            } label: {
                                Icon(copied ? "check" : "copy", size: 18)
                                    .foregroundStyle(copied ? .green : Color.buttonPrimary)
                            }
                            .accessibleButton(
                                copied ? "Copied" : "Copy link",
                                hint: copied ? nil : "Copies the share link to the clipboard"
                            )
                        }
                    }

                    Section {
                        ShareLink("Share via...", item: URL(string: shareLink)!)
                            .accessibilityLabel("Share embed via another app")
                            .accessibilityHint("Opens the system share sheet")
                    }
                } else {
                    Section {
                        if isGenerating {
                            HStack {
                                ProgressView()
                                    .accessibilityHidden(true)
                                Text(LocalizationManager.shared.text("embed.generating_link"))
                                    .font(.omSmall)
                                    .foregroundStyle(Color.fontSecondary)
                            }
                            .accessibilityElement(children: .combine)
                            .accessibilityLabel("Generating share link")
                        } else {
                            Button("Generate Share Link") {
                                generateLink()
                            }
                            .accessibleButton("Generate share link", hint: "Creates a shareable public link for this embed")
                        }
                    }
                }

                if let error {
                    Section {
                        Text(error)
                            .font(.omSmall)
                            .foregroundStyle(Color.error)
                    }
                }
            }
            .navigationTitle("Share Embed")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func generateLink() {
        isGenerating = true
        error = nil

        Task {
            do {
                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/chats/\(chatId)/embeds/\(embedId)/share",
                    body: [:] as [String: String]
                )
                shareLink = response["share_url"]?.value as? String
            } catch {
                self.error = error.localizedDescription
            }
            isGenerating = false
        }
    }

    private func copyToClipboard(_ text: String) {
        #if os(iOS)
        UIPasteboard.general.string = text
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #endif
    }
}
