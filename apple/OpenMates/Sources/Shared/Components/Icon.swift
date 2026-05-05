// Icon — renders a web app SVG icon from Icons.xcassets.
// Replaces Image(systemName:) everywhere in the app to match the web app's icon set.

// ─── Web source ─────────────────────────────────────────────────────
// Assets: frontend/packages/ui/src/tokens/generated/swift/Icons.xcassets
// Icons:  Lucide SVGs + custom branded SVGs, all as template imagesets
//         (template-rendering-intent = fills with current foreground color)
// Web:    getLucideIcon() / categoryUtils.ts, static/icons/*.svg
// ────────────────────────────────────────────────────────────────────

import SwiftUI

/// Renders a named SVG from Icons.xcassets at the given point size.
/// The icon fills `.foregroundStyle` (template rendering — same tinting as SF Symbols).
///
/// Usage:
///   Icon("search", size: 20)          // web: search.svg
///   Icon("close", size: 16)           // web: close.svg
///   Icon("recordaudio", size: 22)     // web: recordaudio.svg
struct Icon: View {
    let name: String
    var size: CGFloat = 20

    init(_ name: String, size: CGFloat = 20) {
        self.name = Self.resolveName(name)
        self.size = size
    }

    var body: some View {
        Image(name)
            .renderingMode(.template)
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
    }

    private static func resolveName(_ rawName: String) -> String {
        let cleanName = rawName.hasPrefix("subsetting_icon ")
            ? String(rawName.dropFirst("subsetting_icon ".count))
            : rawName

        return [
            "account": "user",
            "apps": "app",
            "app_store": "app",
            "developers": "coding",
            "gift_cards": "gift",
            "incognito": "anonym",
            "interface": "language",
            "mates": "mate",
            "messengers": "chat",
            "newsletter": "mail",
            "notifications": "announcement",
            "passkeys": "passkey",
            "pricing": "coins",
            "privacy": "lock",
            "recovery_key": "warning",
            "report_issue": "bug",
            "security": "lock",
            "settings_memories": "heart",
            "shared": "share",
            "storage": "files",
            "support": "volunteering",
            "tfa": "2fa",
            "users": "team",
            "clock": "time",
            "devices": "desktop",
            "document": "pdf",
            "email": "mail",
            "icon_gift": "gift",
            "icon_info": "question",
            "info": "question",
            "key": "security_key",
            "low_balance": "coins",
            "secrets": "lock",
            "api-keys": "coding",
            "app-ai": "ai",
            "dark_mode": "darkmode",
            "focus": "search",
            "light_mode": "darkmode",
            "link": "web",
            "notification": "announcement",
            "profile-picture": "user",
            "shield": "lock",
            "username": "user"
        ][cleanName] ?? cleanName
    }
}
