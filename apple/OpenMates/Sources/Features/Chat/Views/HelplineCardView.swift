// HelplineCardView — the calm card a chat shows when the wellbeing layer places a
// `helplines` embed before the answer: an encouraging title, one row per helpline
// (name, hours, call / text / chat buttons), the local emergency number and a link
// to a helpline directory. With no lines only the emergency number and the directory
// link are shown. Presentational only; EmbedContentView decodes the payload.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/wellbeing/HelplineCard.svelte
//          frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/HelplinesRenderer.ts
// CSS:     HelplineCard.svelte <style>: .helpline-card, .title, .line, .line-name, .line-hours,
//          .action, .emergency, .directory
// Tokens:  ColorTokens.generated.swift (grey0, grey10, grey20, fontPrimary, fontSecondary, fontButton, buttonPrimary),
//          SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Payload contract: docs/plans/safety-decisions-build/wellbeing-contract.md

import SwiftUI

/// One helpline of the `helplines` embed payload.
struct HelplineLine: Identifiable, Equatable, Sendable {
    let id: Int
    let name: String
    let phone: String?
    let sms: String?
    let chatURL: URL?
    let hours: String?
}

/// Decoded `helplines` embed content (country/language are informational only).
struct HelplineCardContent: Equatable, Sendable {
    let lines: [HelplineLine]
    let emergencyNumber: String
    let directoryURL: URL?

    /// Mirrors HelplinesRenderer.ts: the emergency number and directory URL are
    /// required; lines without a name are dropped; only https links become links.
    init?(data: [String: AnyCodable]?) {
        guard let emergency = (data?["emergency_number"]?.value as? String), !emergency.isEmpty,
              let directory = (data?["directory_url"]?.value as? String), !directory.isEmpty else { return nil }
        let raw = data?["lines"]?.value as? [Any] ?? []
        var parsed: [HelplineLine] = []
        for (index, entry) in raw.enumerated() {
            guard let record = entry as? [String: Any],
                  let name = record["name"] as? String, !name.isEmpty else { continue }
            func text(_ key: String) -> String? {
                (record[key] as? String).flatMap { $0.isEmpty ? nil : $0 }
            }
            parsed.append(HelplineLine(id: index, name: name, phone: text("phone"), sms: text("sms"),
                                       chatURL: Self.httpsURL(text("chat_url")), hours: text("hours")))
        }
        lines = parsed
        emergencyNumber = emergency
        directoryURL = Self.httpsURL(directory)
    }

    init(lines: [HelplineLine], emergencyNumber: String, directoryURL: URL?) {
        self.lines = lines
        self.emergencyNumber = emergencyNumber
        self.directoryURL = directoryURL
    }

    private static func httpsURL(_ value: String?) -> URL? {
        guard let value, let url = URL(string: value), url.scheme == "https" else { return nil }
        return url
    }

    /// `tel:` / `sms:` URL with only dialable characters (HelplineCard.svelte `dialable`).
    static func dialURL(scheme: String, number: String) -> URL? {
        let digits = number.filter { $0 == "+" || $0.isNumber }
        return digits.isEmpty ? nil : URL(string: "\(scheme):\(digits)")
    }
}

struct HelplineCardView: View {
    private enum Layout {
        /// `.helpline-card` max-width: 28rem.
        static let maxWidth: CGFloat = 448
        /// `.action` min-height: 2.5rem.
        static let actionHeight: CGFloat = 40
    }

    let content: HelplineCardContent

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(AppStrings.helplinesTitle)
                .font(.omP.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)
                .accessibilityAddTraits(.isHeader)
            ForEach(content.lines) { line in
                lineRow(line)
            }
            emergency
            if let directory = content.directoryURL {
                Link(AppStrings.helplinesFindMore, destination: directory)
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.buttonPrimary)
                    .accessibilityIdentifier("helpline-directory-link")
            }
        }
        .padding(.spacing6)
        .frame(maxWidth: Layout.maxWidth, alignment: .leading)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius6))
        .overlay(RoundedRectangle(cornerRadius: .radius6).stroke(Color.grey20, lineWidth: 1))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(AppStrings.helplinesTitle)
        .accessibilityIdentifier("helpline-card")
    }

    private func lineRow(_ line: HelplineLine) -> some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            VStack(alignment: .leading, spacing: .spacing1) {
                Text(line.name).font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                if let hours = line.hours {
                    Text(hours).font(.omSmall).foregroundStyle(Color.fontSecondary)
                }
            }
            HStack(spacing: .spacing3) {
                if let phone = line.phone, let url = HelplineCardContent.dialURL(scheme: "tel", number: phone) {
                    action(AppStrings.helplinesCall, url: url, identifier: "helpline-call")
                }
                if let sms = line.sms, let url = HelplineCardContent.dialURL(scheme: "sms", number: sms) {
                    action(AppStrings.helplinesText, url: url, identifier: "helpline-sms")
                }
                if let chat = line.chatURL {
                    action(AppStrings.helplinesChat, url: chat, identifier: "helpline-chat")
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.spacing4)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .overlay(RoundedRectangle(cornerRadius: .radius4).stroke(Color.grey20, lineWidth: 1))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("helpline-entry")
    }

    private func action(_ title: String, url: URL, identifier: String) -> some View {
        Link(destination: url) {
            Text(title)
                .font(.omSmall.weight(.semibold))
                .foregroundStyle(Color.fontButton)
                .padding(.horizontal, .spacing6)
                .frame(minHeight: Layout.actionHeight)
                .background(Capsule().fill(Color.buttonPrimary))
        }
        .accessibilityIdentifier(identifier)
    }

    @ViewBuilder private var emergency: some View {
        let sentence = AppStrings.helplinesEmergency(number: content.emergencyNumber)
        Group {
            if let url = HelplineCardContent.dialURL(scheme: "tel", number: content.emergencyNumber) {
                Link(sentence, destination: url).foregroundStyle(Color.fontPrimary).font(.omSmall.weight(.semibold))
            } else {
                Text(sentence).foregroundStyle(Color.fontSecondary).font(.omSmall)
            }
        }
        .accessibilityIdentifier("helpline-emergency")
    }
}
