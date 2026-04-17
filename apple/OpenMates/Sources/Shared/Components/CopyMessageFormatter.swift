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
        let title = embed.title ?? embed.embedType
        switch embed.embedType {
        case "image", "image_generated":
            return "[Image: \(title)]"
        case "video":
            return "[Video: \(title)]"
        case "audio":
            return "[Audio: \(title)]"
        case "link", "web_page":
            return "[Link: \(title)]"
        case "code":
            return "[Code: \(title)]"
        case "map", "place":
            return "[Map: \(title)]"
        case "file", "pdf":
            return "[File: \(title)]"
        case "search_results":
            return "[Search Results: \(title)]"
        case "travel_stay", "travel_connection":
            return "[Travel: \(title)]"
        case "event":
            return "[Event: \(title)]"
        case "product":
            return "[Product: \(title)]"
        case "recipe":
            return "[Recipe: \(title)]"
        default:
            return "[\(embed.embedType): \(title)]"
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
