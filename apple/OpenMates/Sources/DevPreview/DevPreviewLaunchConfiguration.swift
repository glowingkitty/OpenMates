// Debug preview launch routing for native component galleries.
// Keeps simulator-only visual QA surfaces out of the regular product UI.
// Supports launch arguments and private dev URLs for Xcode MCP screenshots.
// This file is compiled in Debug builds only.
// Production builds never expose these routes.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/apps/web_app/src/routes/dev/preview/+page.svelte
//          frontend/apps/web_app/src/routes/dev/preview/embeds/[app]/+page.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

#if DEBUG
import Foundation

struct DevPreviewLaunchConfiguration: Equatable {
    enum Surface: String {
        case embeds
    }

    let surface: Surface
    let appSlug: DevEmbedPreviewApp

    static var current: DevPreviewLaunchConfiguration? {
        parse(environment: ProcessInfo.processInfo.environment)
            ?? parse(arguments: ProcessInfo.processInfo.arguments)
    }

    static func parse(environment: [String: String]) -> DevPreviewLaunchConfiguration? {
        guard environment["DEV_PREVIEW"] == Surface.embeds.rawValue else {
            return nil
        }

        let app = environment["DEV_PREVIEW_APP"]
            .flatMap(DevEmbedPreviewApp.init(rawValue:)) ?? .web

        return DevPreviewLaunchConfiguration(surface: .embeds, appSlug: app)
    }

    static func parse(arguments: [String]) -> DevPreviewLaunchConfiguration? {
        guard value(after: "--dev-preview", in: arguments) == Surface.embeds.rawValue else {
            return nil
        }

        let app = value(after: "--dev-preview-app", in: arguments)
            .flatMap(DevEmbedPreviewApp.init(rawValue:)) ?? .web

        return DevPreviewLaunchConfiguration(surface: .embeds, appSlug: app)
    }

    static func parse(url: URL) -> DevPreviewLaunchConfiguration? {
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        let queryApp = components?.queryItems?.first(where: { $0.name == "app" })?.value

        if url.scheme == "openmates", url.host == "dev" {
            let parts = url.pathComponents.filter { $0 != "/" }
            guard parts.count >= 2, parts[0] == "preview", parts[1] == Surface.embeds.rawValue else {
                return nil
            }
            let app = parts.dropFirst(2).first.flatMap(DevEmbedPreviewApp.init(rawValue:))
                ?? queryApp.flatMap(DevEmbedPreviewApp.init(rawValue:))
                ?? .web
            return DevPreviewLaunchConfiguration(surface: .embeds, appSlug: app)
        }

        if url.path.hasPrefix("/dev/preview/embeds") {
            let parts = url.pathComponents.filter { $0 != "/" }
            let app = parts.dropFirst(3).first.flatMap(DevEmbedPreviewApp.init(rawValue:))
                ?? queryApp.flatMap(DevEmbedPreviewApp.init(rawValue:))
                ?? .web
            return DevPreviewLaunchConfiguration(surface: .embeds, appSlug: app)
        }

        return nil
    }

    private static func value(after flag: String, in arguments: [String]) -> String? {
        guard let index = arguments.firstIndex(of: flag) else { return nil }
        let valueIndex = arguments.index(after: index)
        guard valueIndex < arguments.endIndex else { return nil }
        return arguments[valueIndex]
    }
}
#endif
