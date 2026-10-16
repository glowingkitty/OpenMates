// Mail draft fields shared by the native card, fullscreen header, copy and mail-client action.
// Web: embeds/mail/MailEmbedPreview.svelte, embeds/mail/MailEmbedFullscreen.svelte
import Foundation

struct MailEmbedModel {
    let receiver: String
    let subject: String
    let content: String
    let footer: String

    init(_ data: [String: AnyCodable]?) {
        func string(_ keys: [String]) -> String {
            for key in keys {
                if let value = data?[key]?.value as? String { return value }
            }
            return ""
        }
        receiver = string(["receiver", "to", "from"])
        subject = string(["subject"])
        content = string(["content", "body", "snippet"])
        footer = string(["footer"])
    }

    private init(receiver: String, subject: String, content: String, footer: String) {
        self.receiver = receiver; self.subject = subject; self.content = content; self.footer = footer
    }

    func applyingPII(mappings: [PIIMapping], revealed: Bool) -> Self {
        func render(_ text: String) -> String { EmbedPIIText.render(text, mappings: mappings, revealed: revealed) }
        return Self(receiver: render(receiver), subject: render(subject), content: render(content), footer: render(footer))
    }

    var previewBody: String {
        content.components(separatedBy: "\n").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }.joined(separator: "\n")
    }

    var mailBody: String { [content, footer].filter { !$0.isEmpty }.joined(separator: "\n\n") }
    @MainActor var copyText: String { "\(AppStrings.localized("embeds.mail.to")): \(receiver)\n\(AppStrings.localized("embeds.mail.subject")): \(subject)\n\n\(mailBody)".trimmingCharacters(in: .whitespacesAndNewlines) }

    var mailtoURL: URL? {
        // Match encodeURIComponent so reserved query delimiters cannot escape a draft field.
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()")
        func encode(_ value: String) -> String { value.addingPercentEncoding(withAllowedCharacters: allowed) ?? "" }
        return URL(string: "mailto:\(encode(receiver))?subject=\(encode(subject))&body=\(encode(mailBody))")
    }
}
