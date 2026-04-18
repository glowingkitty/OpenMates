// AI Mates list — browse and view details of available AI mates.
// Mirrors the web app's SettingsMates.svelte: vertical list of mates
// with profile images, names, and expertise descriptions.

import SwiftUI

struct SettingsMatesView: View {
    @State private var mates: [MateInfo] = []
    @State private var isLoading = true
    @State private var selectedMate: MateInfo?

    struct MateInfo: Identifiable, Decodable {
        let id: String
        let name: String
        let description: String?
        let expertise: String?
        let profileImageUrl: String?
        let isAvailable: Bool?
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else if mates.isEmpty {
                Section {
                    VStack(spacing: .spacing4) {
                        Image(systemName: "person.2")
                            .font(.system(size: 36))
                            .foregroundStyle(Color.fontTertiary)
                        Text(LocalizationManager.shared.text("settings.mates.no_mates"))
                            .font(.omP).foregroundStyle(Color.fontSecondary)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, .spacing8)
                }
            } else {
                ForEach(mates) { mate in
                    Button {
                        selectedMate = mate
                    } label: {
                        MateRow(mate: mate)
                    }
                }
            }
        }
        .navigationTitle("Mates")
        .task { await loadMates() }
        .sheet(item: $selectedMate) { mate in
            MateDetailView(mate: mate)
        }
    }

    private func loadMates() async {
        do {
            mates = try await APIClient.shared.request(.get, path: "/v1/mates")
        } catch {
            print("[Settings] Failed to load mates: \(error)")
        }
        isLoading = false
    }
}

// MARK: - Mate row

struct MateRow: View {
    let mate: SettingsMatesView.MateInfo

    var body: some View {
        HStack(spacing: .spacing4) {
            Circle()
                .fill(LinearGradient.primary)
                .frame(width: 44, height: 44)
                .overlay {
                    Text(String(mate.name.prefix(1)).uppercased())
                        .font(.omH4).fontWeight(.bold)
                        .foregroundStyle(.white)
                }

            VStack(alignment: .leading, spacing: .spacing1) {
                Text(mate.name)
                    .font(.omSmall).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)

                if let expertise = mate.expertise {
                    Text(expertise)
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                        .lineLimit(2)
                }
            }

            Spacer()

            Image(systemName: "chevron.right")
                .font(.caption).foregroundStyle(Color.fontTertiary)
        }
        .padding(.vertical, .spacing1)
    }
}

// MARK: - Mate detail view

struct MateDetailView: View {
    let mate: SettingsMatesView.MateInfo
    @Environment(\.dismiss) var dismiss
    @State private var showChat = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: .spacing6) {
                    Circle()
                        .fill(LinearGradient.primary)
                        .frame(width: 80, height: 80)
                        .overlay {
                            Text(String(mate.name.prefix(1)).uppercased())
                                .font(.system(size: 36, weight: .bold))
                                .foregroundStyle(.white)
                        }

                    Text(mate.name)
                        .font(.omH3).fontWeight(.bold)

                    if let expertise = mate.expertise {
                        Text(expertise)
                            .font(.omP).foregroundStyle(Color.fontSecondary)
                            .multilineTextAlignment(.center)
                    }

                    if let description = mate.description {
                        Text(description)
                            .font(.omSmall).foregroundStyle(Color.fontSecondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal)
                    }

                    Button {
                        startChat()
                    } label: {
                        Label("Start Chat", systemImage: "message")
                            .font(.omSmall).fontWeight(.medium)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color.buttonPrimary)
                }
                .padding(.spacing8)
            }
            .navigationTitle(mate.name)
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

    private func startChat() {
        Task {
            let url = await APIClient.shared.webAppURL
                .appendingPathComponent("chat/new")
                .appending(queryItems: [URLQueryItem(name: "mate", value: mate.id)])
            #if os(iOS)
            await UIApplication.shared.open(url)
            #elseif os(macOS)
            NSWorkspace.shared.open(url)
            #endif
        }
    }
}
