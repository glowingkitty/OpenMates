// Fullscreen embed overlay — slides up from bottom, shows full embed content.
// Mirrors UnifiedEmbedFullscreen.svelte with gradient header, scrollable content,
// child embed carousel for composite types, and action bar.

import SwiftUI

struct EmbedFullscreenView: View {
    let embed: EmbedRecord
    let childEmbeds: [EmbedRecord]
    @Environment(\.dismiss) var dismiss

    @State private var selectedChildId: String?
    @State private var showChildFullscreen = false

    private var embedType: EmbedType? {
        EmbedType(rawValue: embed.type)
    }

    var body: some View {
        ZStack(alignment: .top) {
            ScrollView {
                VStack(spacing: 0) {
                    headerBanner
                    contentArea
                    if !childEmbeds.isEmpty {
                        childEmbedsSection
                    }
                }
            }
            .background(Color.grey0)

            HStack(spacing: .spacing3) {
                OMIconButton(icon: "close", label: "Close", size: 38, iconSize: 18) {
                    dismiss()
                }

                Spacer()

                OMIconButton(icon: "copy", label: "Copy", size: 38, iconSize: 18) {
                    copyContent()
                }

                OMIconButton(icon: "share", label: "Share", size: 38, iconSize: 18, isProminent: true) {
                    shareEmbed()
                }
            }
            .padding(.horizontal, .spacing5)
            .padding(.top, .spacing5)

            if showChildFullscreen,
               let childId = selectedChildId,
               let child = childEmbeds.first(where: { $0.id == childId }) {
                ZStack(alignment: .topTrailing) {
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
    }

    // MARK: - Header banner with gradient

    private var headerBanner: some View {
        ZStack(alignment: .bottomLeading) {
            if let appId = embedType?.appId {
                AppGradientBackground(appId: appId)
                    .frame(height: 120)
                    .accessibilityHidden(true)
            } else {
                LinearGradient.primary
                    .frame(height: 120)
                    .accessibilityHidden(true)
            }

            VStack(alignment: .leading, spacing: .spacing2) {
                Text(embedType?.displayName ?? embed.type)
                    .font(.omH3)
                    .fontWeight(.bold)
                    .foregroundStyle(.white)

                if let subtitle = headerSubtitle {
                    Text(subtitle)
                        .font(.omSmall)
                        .foregroundStyle(.white.opacity(0.8))
                        .lineLimit(2)
                }
            }
            .padding(.horizontal, .spacing6)
            .padding(.bottom, .spacing4)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(embedType?.displayName ?? embed.type)\(headerSubtitle.map { ": \($0)" } ?? "")")
    }

    private var headerSubtitle: String? {
        guard let data = embed.data, case .raw(let dict) = data else { return nil }
        if let query = dict["query"]?.value as? String { return query }
        if let title = dict["title"]?.value as? String { return title }
        if let url = dict["url"]?.value as? String { return url }
        return nil
    }

    // MARK: - Content area

    private var contentArea: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            EmbedContentView(embed: embed, mode: .fullscreen)
        }
        .padding(.spacing6)
    }

    // MARK: - Child embeds (for composite types)

    private var childEmbedsSection: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text("\(LocalizationManager.shared.text("embed.results")) (\(childEmbeds.count))")
                .font(.omP)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)
                .padding(.horizontal, .spacing6)

            ScrollView(.horizontal, showsIndicators: false) {
                LazyHStack(spacing: .spacing4) {
                    ForEach(childEmbeds) { child in
                        EmbedPreviewCard(embed: child) {
                            selectedChildId = child.id
                            showChildFullscreen = true
                        }
                        .frame(width: 260, height: 180)
                    }
                }
                .padding(.horizontal, .spacing6)
            }
            .accessibilityLabel("Related embeds, \(childEmbeds.count) items. Scroll horizontally to browse")
        }
        .padding(.vertical, .spacing4)
    }

    // MARK: - Actions

    private func shareEmbed() {
        Task {
            let webAppURL = await APIClient.shared.webAppURL
            let shareURL = webAppURL.appendingPathComponent("embed/\(embed.id)")
            #if os(iOS)
            let activityVC = UIActivityViewController(activityItems: [shareURL], applicationActivities: nil)
            if let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
               let rootVC = windowScene.windows.first?.rootViewController {
                rootVC.present(activityVC, animated: true)
            }
            #elseif os(macOS)
            let sharingPicker = NSSharingServicePicker(items: [shareURL])
            if let window = NSApplication.shared.windows.first {
                sharingPicker.show(relativeTo: .zero, of: window.contentView!, preferredEdge: .minY)
            }
            #endif
        }
    }

    private func copyContent() {
        #if os(iOS)
        if let data = embed.data, case .raw(let dict) = data {
            let text = dict.map { "\($0.key): \($0.value.value)" }.joined(separator: "\n")
            UIPasteboard.general.string = text
        }
        #elseif os(macOS)
        if let data = embed.data, case .raw(let dict) = data {
            let text = dict.map { "\($0.key): \($0.value.value)" }.joined(separator: "\n")
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
        }
        #endif
    }
}

// MARK: - Gradient background helper

struct AppGradientBackground: View {
    let appId: String

    var body: some View {
        Rectangle()
            .fill(gradient)
            .overlay(
                LinearGradient(
                    colors: [.clear, .black.opacity(0.3)],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )
    }

    private var gradient: AnyShapeStyle {
        switch appId {
        case "web": return AnyShapeStyle(LinearGradient.appWeb)
        case "videos": return AnyShapeStyle(LinearGradient.appVideos)
        case "code": return AnyShapeStyle(LinearGradient.appCode)
        case "maps": return AnyShapeStyle(LinearGradient.appMaps)
        case "travel": return AnyShapeStyle(LinearGradient.appTravel)
        case "news": return AnyShapeStyle(LinearGradient.appNews)
        case "shopping": return AnyShapeStyle(LinearGradient.appShopping)
        case "health": return AnyShapeStyle(LinearGradient.appHealth)
        case "nutrition": return AnyShapeStyle(LinearGradient.appNutrition)
        case "events": return AnyShapeStyle(LinearGradient.appEvents)
        case "photos", "images": return AnyShapeStyle(LinearGradient.appPhotos)
        case "music": return AnyShapeStyle(LinearGradient.appMusic)
        case "mail": return AnyShapeStyle(LinearGradient.appMail)
        case "docs": return AnyShapeStyle(LinearGradient.appDocs)
        case "pdf": return AnyShapeStyle(LinearGradient.appPdf)
        case "home": return AnyShapeStyle(LinearGradient.appHome)
        case "finance": return AnyShapeStyle(LinearGradient.appFinance)
        case "math": return AnyShapeStyle(LinearGradient.appMath)
        case "audio": return AnyShapeStyle(LinearGradient.appAudio)
        default: return AnyShapeStyle(LinearGradient.primary)
        }
    }
}
