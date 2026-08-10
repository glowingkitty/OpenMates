// Native profile-image selection, square crop, resize, and safety-checked upload.
// Raw images remain on-device; only a 340x340 JPEG is sent to the upload API,
// matching SettingsProfilePicture.svelte's data handling and UI states.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/account/SettingsProfilePicture.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import ImageIO
import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

struct SettingsProfilePictureView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var selectedItem: PhotosPickerItem?
    @State private var previewData: Data?
    @State private var isUploading = false
    @State private var statusMessage: String?
    @State private var errorMessage: String?

    var body: some View {
        OMSettingsPage(title: AppStrings.profilePicture) {
            OMSettingsSection {
                VStack(spacing: .spacing6) {
                    avatar

                    PhotosPicker(selection: $selectedItem, matching: .images) {
                        HStack(spacing: .spacing2) {
                            Icon("image", size: 18)
                            Text(isUploading ? AppStrings.photoUploading : AppStrings.choosePhoto)
                        }
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(isUploading)
                    .accessibilityIdentifier("settings-profile-picture-picker")
                }
                .frame(maxWidth: .infinity)
                .padding(.spacing8)
            }

            if let statusMessage { status(statusMessage, color: Color.buttonPrimary) }
            if let errorMessage { status(errorMessage, color: Color.error) }
        }
        .onChange(of: selectedItem) { _, item in loadAndUpload(item) }
        .accessibilityIdentifier("settings-profile-picture-page")
    }

    @ViewBuilder
    private var avatar: some View {
        if let previewData, let image = platformImage(data: previewData) {
            image
                .resizable()
                .scaledToFill()
                .frame(width: 120, height: 120)
                .clipShape(Circle())
                .accessibilityHidden(true)
        } else {
            Circle()
                .fill(LinearGradient.primary)
                .frame(width: 120, height: 120)
                .overlay {
                    Icon("user", size: 48).foregroundStyle(Color.white)
                }
                .accessibilityHidden(true)
        }
    }

    private func loadAndUpload(_ item: PhotosPickerItem?) {
        guard let item else { return }
        isUploading = true
        statusMessage = nil
        errorMessage = nil
        Task {
            do {
                guard let rawData = try await item.loadTransferable(type: Data.self) else {
                    throw AccountSecurityError.missingAccountData
                }
                guard rawData.count <= 20 * 1_024 * 1_024 else {
                    throw ProfileImageError.fileTooLarge
                }
                let jpeg = try Self.squareJPEG(from: rawData)
                let response = try await AccountSecurityService.shared.uploadProfileImage(jpeg)
                switch response.status {
                case "ok":
                    previewData = jpeg
                    statusMessage = AppStrings.photoUpdated
                case "rejected":
                    throw ProfileImageError.rejected
                case "account_deleted":
                    await authManager.logout()
                    throw ProfileImageError.accountDeleted
                default:
                    throw AccountSecurityError.server(response.detail)
                }
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Profile image upload failed", category: "settings.account")
            }
            isUploading = false
            selectedItem = nil
        }
    }

    @MainActor
    private static func squareJPEG(from data: Data) throws -> Data {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil)
        else { throw ProfileImageError.wrongFormat }
        let side = min(image.width, image.height)
        let crop = CGRect(
            x: (image.width - side) / 2,
            y: (image.height - side) / 2,
            width: side,
            height: side
        )
        guard let cropped = image.cropping(to: crop),
              let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(
                data: nil,
                width: 340,
                height: 340,
                bitsPerComponent: 8,
                bytesPerRow: 0,
                space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
              )
        else { throw ProfileImageError.wrongFormat }
        context.interpolationQuality = .high
        context.draw(cropped, in: CGRect(x: 0, y: 0, width: 340, height: 340))
        guard let resized = context.makeImage() else { throw ProfileImageError.wrongFormat }

        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            output,
            UTType.jpeg.identifier as CFString,
            1,
            nil
        ) else { throw ProfileImageError.wrongFormat }
        CGImageDestinationAddImage(destination, resized, [kCGImageDestinationLossyCompressionQuality: 0.9] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw ProfileImageError.wrongFormat }
        return output as Data
    }

    private func platformImage(data: Data) -> Image? {
        #if os(iOS)
        guard let image = UIImage(data: data) else { return nil }
        return Image(uiImage: image)
        #elseif os(macOS)
        guard let image = NSImage(data: data) else { return nil }
        return Image(nsImage: image)
        #endif
    }

    private func status(_ message: String, color: Color) -> some View {
        Text(message)
            .font(.omSmall)
            .foregroundStyle(color)
            .padding(.horizontal, .spacing6)
    }
}

private struct ProfileImageError: LocalizedError {
    let errorDescription: String?

    @MainActor static var fileTooLarge: Self { .init(errorDescription: AppStrings.photoFileTooLarge) }
    @MainActor static var wrongFormat: Self { .init(errorDescription: AppStrings.photoWrongFormat) }
    @MainActor static var rejected: Self { .init(errorDescription: AppStrings.photoRejected) }
    @MainActor static var accountDeleted: Self { .init(errorDescription: AppStrings.accountDeleted) }
}
