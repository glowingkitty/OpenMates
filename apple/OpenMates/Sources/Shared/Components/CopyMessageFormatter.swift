// Smart message copy — converts message content with embedded references to readable text.
// Mirrors the web app's copy-message-flow: strips markdown artifacts, converts embed refs
// to human-readable summaries (e.g. "[Image: sunset.jpg]"), and copies to system clipboard.

import Foundation
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

enum CopyMessageFormatter {

    static func formatForCopy(content: String, embeds: [EmbedRecord]) -> String {
        var result = content

        for embed in embeds {
            let placeholder = embedPlaceholder(embed)
            if let refPattern = embed.id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) {
                result = result.replacingOccurrences(
                    of: "\\[embed:\\s*\(NSRegularExpression.escapedPattern(for: refPattern))\\]",
                    with: placeholder,
                    options: .regularExpression
                )
                result = result.replacingOccurrences(
                    of: "[embed:\(embed.id)]",
                    with: placeholder
                )
            }
        }

        result = cleanMarkdownForPlaintext(result)
        return result.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func copyToClipboard(_ text: String) {
        #if os(iOS)
        UIPasteboard.general.string = text
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #endif
    }

    // MARK: - Embed type to readable placeholder

    private static func embedPlaceholder(_ embed: EmbedRecord) -> String {
        let displayName = EmbedType(rawValue: embed.type)?.displayName ?? embed.type
        switch embed.type {
        case "image", "image_generated":
            return "[Image: \(displayName)]"
        case "video":
            return "[Video: \(displayName)]"
        case "audio":
            return "[Audio: \(displayName)]"
        case "link", "web_page":
            return "[Link: \(displayName)]"
        case "code":
            return "[Code: \(displayName)]"
        case "map", "place":
            return "[Map: \(displayName)]"
        case "file", "pdf":
            return "[File: \(displayName)]"
        case "search_results":
            return "[Search Results: \(displayName)]"
        case "travel_stay", "travel_connection":
            return "[Travel: \(displayName)]"
        case "event":
            return "[Event: \(displayName)]"
        case "product":
            return "[Product: \(displayName)]"
        case "recipe":
            return "[Recipe: \(displayName)]"
        default:
            return "[\(embed.type): \(displayName)]"
        }
    }

    // MARK: - Markdown cleanup for plain text

    private static func cleanMarkdownForPlaintext(_ text: String) -> String {
        var result = text

        // Bold/italic markers
        result = result.replacingOccurrences(of: "\\*{1,3}(.+?)\\*{1,3}", with: "$1", options: .regularExpression)
        result = result.replacingOccurrences(of: "_{1,3}(.+?)_{1,3}", with: "$1", options: .regularExpression)

        // Inline code
        result = result.replacingOccurrences(of: "`(.+?)`", with: "$1", options: .regularExpression)

        // Headers (keep text, remove # prefix)
        result = result.replacingOccurrences(of: "(?m)^#{1,6}\\s+", with: "", options: .regularExpression)

        // Links [text](url) → text (url)
        result = result.replacingOccurrences(of: "\\[(.+?)\\]\\((.+?)\\)", with: "$1 ($2)", options: .regularExpression)

        return result
    }
}
