// Fullscreen embed container with navigation between embeds in a group.
// Supports prev/next navigation arrows, child embed loading for composite types,
// and the full slide-up presentation matching the web app.

import SwiftUI

struct EmbedFullscreenContainer: View {
    let embeds: [EmbedRecord]
    let initialEmbedId: String
    let allEmbedRecords: [String: EmbedRecord]
    @Environment(\.dismiss) var dismiss

    @State private var currentIndex: Int = 0
    @State private var selectedChildEmbed: EmbedRecord?
    @State private var showChildFullscreen = false

    private var currentEmbed: EmbedRecord? {
        guard currentIndex >= 0 && currentIndex < embeds.count else { return nil }
        return embeds[currentIndex]
    }

    private var childEmbeds: [EmbedRecord] {
        guard let embed = currentEmbed else { return [] }
        return embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
    }

    var body: some View {
        ZStack(alignment: .top) {
            if let embed = currentEmbed {
                ZStack {
                    ScrollView {
                        VStack(spacing: 0) {
                            EmbedFullscreenHeader(embed: embed)
                            EmbedContentView(embed: embed, mode: .fullscreen)
                                .padding(.spacing6)

                            if !childEmbeds.isEmpty {
                                childEmbedSection
                            }
                        }
                    }
                    .background(Color.grey0)

                    if embeds.count > 1 {
                        navigationArrows
                    }
                }

                fullscreenControls(embed: embed)
            }

            if showChildFullscreen, let child = selectedChildEmbed {
                ZStack {
                    Color.black.opacity(0.38)
                        .ignoresSafeArea()
                        .onTapGesture {
                            showChildFullscreen = false
                        }

                    EmbedFullscreenView(embed: child, childEmbeds: [])
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                        .padding(.spacing8)
                }
            }
        }
        .onAppear {
            currentIndex = embeds.firstIndex(where: { $0.id == initialEmbedId }) ?? 0
        }
    }

    // MARK: - Navigation arrows

    private var navigationArrows: some View {
        HStack {
            if currentIndex > 0 {
                Button { withAnimation { currentIndex -= 1 } } label: {
                    Icon("back", size: 36)
                        .foregroundStyle(.white)
                        .shadow(radius: 4)
                }
            }
            Spacer()
            if currentIndex < embeds.count - 1 {
                Button { withAnimation { currentIndex += 1 } } label: {
                    Icon("back", size: 36)
                        .scaleEffect(x: -1, y: 1)
                        .foregroundStyle(.white)
                        .shadow(radius: 4)
                }
            }
        }
        .padding(.horizontal, .spacing4)
    }

    // MARK: - Child embeds

    private var childEmbedSection: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Divider().padding(.horizontal, .spacing6)

            Text("\(LocalizationManager.shared.text("embed.results")) (\(childEmbeds.count))")
                .font(.omP).fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)
                .padding(.horizontal, .spacing6)

            let groups = EmbedGrouper.group(childEmbeds)
            ForEach(groups) { group in
                GroupedEmbedView(group: group) { embed in
                    selectedChildEmbed = embed
                    showChildFullscreen = true
                }
                .padding(.horizontal, .spacing6)
            }
        }
        .padding(.bottom, .spacing8)
    }

    // MARK: - Fullscreen controls

    private func fullscreenControls(embed: EmbedRecord) -> some View {
        HStack(spacing: .spacing3) {
            OMIconButton(icon: "close", label: "Close", size: 38, iconSize: 18) {
                dismiss()
            }

            Spacer()

            if embeds.count > 1 {
                Text("\(currentIndex + 1) / \(embeds.count)")
                    .font(.omXs)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .padding(.horizontal, .spacing4)
                    .padding(.vertical, .spacing3)
                    .background(Color.grey0.opacity(0.92))
                    .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
            }

            Spacer()

            OMIconButton(icon: "copy", label: "Copy", size: 38, iconSize: 18) {
                copyEmbedContent(embed)
            }

            OMIconButton(icon: "share", label: "Share", size: 38, iconSize: 18, isProminent: true) {
                shareEmbed(embed)
            }
        }
        .padding(.horizontal, .spacing5)
        .padding(.top, .spacing5)
    }

    private func shareEmbed(_ embed: EmbedRecord) {
        Task {
            let url = await APIClient.shared.webAppURL.appendingPathComponent("embed/\(embed.id)")
            #if os(iOS)
            let activityVC = UIActivityViewController(activityItems: [url], applicationActivities: nil)
            if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
               let rootVC = scene.windows.first?.rootViewController {
                rootVC.present(activityVC, animated: true)
            }
            #endif
        }
    }

    private func copyEmbedContent(_ embed: EmbedRecord) {
        guard let data = embed.data, case .raw(let dict) = data else { return }
        let text = dict.compactMap { key, val -> String? in
            guard let str = val.value as? String else { return nil }
            return "\(key): \(str)"
        }.joined(separator: "\n")
        #if os(iOS)
        UIPasteboard.general.string = text
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #endif
    }
}

// MARK: - Fullscreen header

struct EmbedFullscreenHeader: View {
    let embed: EmbedRecord

    private var embedType: EmbedType? { EmbedType(rawValue: embed.type) }

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            if let appId = embedType?.appId {
                AppGradientBackground(appId: appId)
            } else {
                LinearGradient.primary
            }

            VStack(alignment: .leading, spacing: .spacing2) {
                Text(embedType?.displayName ?? embed.type)
                    .font(.omH3).fontWeight(.bold).foregroundStyle(.white)

                if let subtitle = headerSubtitle {
                    Text(subtitle)
                        .font(.omSmall).foregroundStyle(.white.opacity(0.8))
                        .lineLimit(2)
                }
            }
            .padding(.horizontal, .spacing6)
            .padding(.bottom, .spacing4)
        }
        .frame(height: 120)
    }

    private var headerSubtitle: String? {
        guard let data = embed.data, case .raw(let dict) = data else { return nil }
        return (dict["query"]?.value as? String)
            ?? (dict["title"]?.value as? String)
            ?? (dict["url"]?.value as? String)
    }
}
