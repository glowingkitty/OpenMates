// Specification: specifications/features/billing/specification.yml
// Assertions: billing.access.authenticated-first-party
// Native profile-image selection, square crop, resize, and safety-checked upload.
// Raw images remain on-device; only a 340x340 JPEG is sent to the upload API,
// matching SettingsProfilePicture.svelte's data handling and UI states.

// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.isolation
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/account/SettingsProfilePicture.svelte
//          frontend/packages/ui/src/components/settings/SettingsMainHeader.svelte
// Service: frontend/packages/ui/src/services/profileImageService.ts
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
        guard let item, let ownerID = authManager.currentUser?.id else { return }
        let requestFence = UserTasksAccountFence(accountID: ownerID)
        let deletionCleanup = AccountDeletionCleanup(fence: requestFence)
        isUploading = true
        statusMessage = nil
        errorMessage = nil
        Task {
            defer { isUploading = false; selectedItem = nil }
            do {
                guard let rawData = try await item.loadTransferable(type: Data.self) else {
                    throw AccountSecurityError.missingAccountData
                }
                guard rawData.count <= 20 * 1_024 * 1_024 else {
                    throw ProfileImageError.fileTooLarge
                }
                let jpeg = try Self.squareJPEG(from: rawData)
                try await requestFence.check()
                let response = try await AccountSecurityService.shared.uploadProfileImage(jpeg,
                    serverProfile: requestFence.serverProfile, expectedAccountID: requestFence.accountID,
                    expectedScope: requestFence.scope, expectedTeamContext: requestFence.requestTeamContext)
                try await requestFence.check()
                switch response.status {
                case "ok":
                    previewData = jpeg
                    statusMessage = AppStrings.photoUpdated
                case "rejected":
                    throw ProfileImageError.rejected
                case "account_deleted":
                    guard deletionCleanup.eraseConfirmed(currentAccountID: authManager.currentUser?.id) else { return }
                    await authManager.logout()
                    throw ProfileImageError.accountDeleted
                default:
                    throw AccountSecurityError.server(response.detail)
                }
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Profile image upload failed", category: "settings.account")
            }
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

// Web: services/profileImageService.ts. The authenticated API decrypts the
// private S3 image on the server; the client receives ordinary raster bytes.
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.isolation
struct SettingsProfileImageRequest: Equatable {
    enum Source: Equatable {
        case authenticated(String)
        case legacy(URL)
    }
    let ownerID: String
    let authority: AuthSessionRecoveryContext
    let scope: UUID
    let source: Source

    init?(ownerID: String, rawURL: String?, authority: AuthSessionRecoveryContext, scope: UUID) {
        guard ownerID == authority.accountID, !ownerID.isEmpty else { return nil }
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#%")
        guard let escaped = ownerID.addingPercentEncoding(withAllowedCharacters: allowed) else { return nil }
        let path = "/v1/users/\(escaped)/profile-image"
        let raw = rawURL?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let source: Source
        if raw.isEmpty || raw == path {
            source = .authenticated(path)
        } else if let url = URL(string: raw), url.scheme?.lowercased() == "https",
                  url.user == nil, url.password == nil, url.fragment == nil {
            let base = authority.profile.apiBaseURL
            if url.host?.lowercased() == base.host?.lowercased(), url.port == base.port,
               url.scheme?.lowercased() == base.scheme?.lowercased() {
                guard url.path == path, url.query == nil else { return nil }
                source = .authenticated(path)
            } else {
                // A proxy URL on another origin must never be mistaken for a
                // legacy public image, nor acquire another server's cookies.
                guard !url.path.hasPrefix("/v1/users/") else { return nil }
                source = .legacy(url)
            }
        } else { return nil }
        self.ownerID = ownerID; self.authority = authority; self.scope = scope; self.source = source
    }

    func matches(authority currentAuthority: AuthSessionRecoveryContext?, scope currentScope: UUID) -> Bool {
        authority == currentAuthority && scope == currentScope
    }

    @MainActor var isCurrent: Bool {
        matches(authority: AuthManager.captureNetworkAuthority(), scope: OfflineStore.shared.scopeGeneration)
    }
}

@MainActor
final class SettingsProfileImageLoader: ObservableObject {
    @Published private(set) var data: Data?
    @Published private(set) var image: Image?
    @Published private(set) var loadedRequest: SettingsProfileImageRequest?
    private var generation = UUID()

    // There is no global URL-only cache or negative cache. Every new mount can
    // retry a failed fetch, including after auth validation or a profile upload.
    func load(_ request: SettingsProfileImageRequest?,
              isCurrent: @escaping @MainActor () -> Bool,
              fetch: @escaping @MainActor (SettingsProfileImageRequest) async throws -> Data = SettingsProfileImageLoader.fetch) async {
        let operation = UUID(); generation = operation
        data = nil; image = nil; loadedRequest = nil
        guard let request, isCurrent() else { return }
        do {
            let bytes = try await fetch(request)
            guard generation == operation, !Task.isCancelled, isCurrent(), let decoded = Self.decodeImage(bytes) else { return }
            loadedRequest = request; image = decoded; data = bytes
        } catch {
            guard generation == operation else { return }
            data = nil; image = nil; loadedRequest = nil
            // No URL, account identifier, error body or credentials in diagnostics.
            if !Task.isCancelled && isCurrent() {
                NativeDiagnostics.info("Profile image unavailable", category: "settings.account")
            }
        }
    }

    static func fetch(_ request: SettingsProfileImageRequest) async throws -> Data {
        guard request.isCurrent else { throw CancellationError() }
        let data: Data
        switch request.source {
        case .authenticated(let path):
            data = try await APIClient.shared.request(.get, path: path, serverProfile: request.authority.profile,
                expectedAccountID: request.ownerID, expectedScope: request.scope)
        case .legacy(let url):
            // Public legacy images never use the first-party credential jar.
            let configuration = URLSessionConfiguration.ephemeral
            configuration.httpCookieStorage = nil
            configuration.urlCredentialStorage = nil
            configuration.httpShouldSetCookies = false
            let session = URLSession(configuration: configuration)
            defer { session.invalidateAndCancel() }
            var download = URLRequest(url: url); download.httpShouldHandleCookies = false
            let (bytes, response) = try await session.data(for: download)
            guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                throw APIError.invalidResponse
            }
            data = bytes
        }
        guard request.isCurrent else { throw CancellationError() }
        return data
    }

    private static func decodeImage(_ data: Data) -> Image? {
        #if os(iOS)
        return UIImage(data: data).map { Image(uiImage: $0) }
        #elseif os(macOS)
        return NSImage(data: data).map { Image(nsImage: $0) }
        #else
        return nil
        #endif
    }
}


// The view compares the loaded identity before exposing bytes, so an account or
// authority change hides the previous image immediately, before .task restarts.
struct SettingsProfileAvatar<Fallback: View>: View {
    let ownerID: String
    let rawURL: String?
    @ViewBuilder let fallback: () -> Fallback
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var loader = SettingsProfileImageLoader()

    private var request: SettingsProfileImageRequest? {
        guard let authority = authManager.networkAuthority else { return nil }
        return SettingsProfileImageRequest(ownerID: ownerID, rawURL: rawURL,
            authority: authority, scope: OfflineStore.shared.scopeGeneration)
    }

    var body: some View {
        Group {
            if let request, request.isCurrent, loader.loadedRequest == request,
               let image = loader.image {
                image.resizable().scaledToFill().accessibilityIdentifier("settings-profile-image-loaded")
            } else {
                fallback().accessibilityIdentifier("settings-profile-image-fallback")
            }
        }
        .task(id: request) {
            let captured = request
            await loader.load(captured, isCurrent: { captured?.isCurrent == true })
        }
    }


}
