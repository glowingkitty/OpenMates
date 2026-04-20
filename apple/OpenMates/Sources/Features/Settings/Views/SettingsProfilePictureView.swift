// Profile picture management — upload, preview, and remove profile avatar.
// Mirrors the web app's account/SettingsProfilePicture.svelte.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/account/SettingsProfilePicture.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import PhotosUI

struct SettingsProfilePictureView: View {
    @EnvironmentObject var authManager: AuthManager
    @State private var selectedItem: PhotosPickerItem?
    @State private var imageData: Data?
    @State private var previewImage: Image?
    @State private var isUploading = false
    @State private var error: String?

    var body: some View {
        Form {
            Section {
                VStack(spacing: .spacing6) {
                    if let previewImage {
                        previewImage
                            .resizable()
                            .scaledToFill()
                            .frame(width: 120, height: 120)
                            .clipShape(Circle())
                    } else {
                        Circle()
                            .fill(LinearGradient.primary)
                            .frame(width: 120, height: 120)
                            .overlay {
                                Text(String(authManager.currentUser?.username.prefix(1) ?? "?").uppercased())
                                    .font(.system(size: 48, weight: .bold))
                                    .foregroundStyle(.white)
                            }
                    }

                    PhotosPicker(selection: $selectedItem, matching: .images) {
                        Text(LocalizationManager.shared.text("settings.profile_picture.choose_photo"))
                            .font(.omSmall).fontWeight(.medium)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color.buttonPrimary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, .spacing6)
            }

            if previewImage != nil || authManager.currentUser?.profileImageUrl != nil {
                Section {
                    Button(role: .destructive) {
                        removePhoto()
                    } label: {
                        Label("Remove Photo", systemImage: "trash")
                    }
                }
            }

            if let error {
                Section {
                    Text(error)
                        .font(.omSmall).foregroundStyle(Color.error)
                }
            }
        }
        .navigationTitle("Profile Picture")
        .onChange(of: selectedItem) { _, newItem in
            loadAndUpload(newItem)
        }
    }

    private func loadAndUpload(_ item: PhotosPickerItem?) {
        guard let item else { return }
        Task {
            guard let data = try? await item.loadTransferable(type: Data.self) else { return }
            imageData = data
            #if os(iOS)
            if let uiImage = UIImage(data: data) {
                previewImage = Image(uiImage: uiImage)
            }
            #elseif os(macOS)
            if let nsImage = NSImage(data: data) {
                previewImage = Image(nsImage: nsImage)
            }
            #endif

            await uploadPhoto(data)
        }
    }

    private func uploadPhoto(_ data: Data) async {
        isUploading = true
        error = nil
        do {
            let _: Data = try await APIClient.shared.request(
                .post, path: "/v1/settings/user/profile-picture",
                body: ["image_base64": data.base64EncodedString()]
            )
            ToastManager.shared.show("Photo updated", type: .success)
        } catch {
            self.error = error.localizedDescription
        }
        isUploading = false
    }

    private func removePhoto() {
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .delete, path: "/v1/settings/user/profile-picture"
                )
                previewImage = nil
                imageData = nil
                ToastManager.shared.show("Photo removed", type: .success)
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}
