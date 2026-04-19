// PII detection UI — warns user about personal data in messages.
// Shows detected PII count with option to exclude individual entries.
// Replaces PII with placeholders like [EMAIL_1], [PHONE_1] on send.

import SwiftUI

struct PIIWarningBanner: View {
    let detectedItems: [PIIItem]
    let onExclude: (PIIItem) -> Void
    let onDismiss: () -> Void

    struct PIIItem: Identifiable {
        let id = UUID()
        let type: PIIType
        let value: String
        var isExcluded: Bool = false

        enum PIIType: String {
            case email, phone, address, name, birthday, custom
            var icon: String {
                switch self {
                case .email: return "mail"
                case .phone: return "phone"
                case .address: return "maps"
                case .name: return "user"
                case .birthday: return "gift"
                case .custom: return "hidden"
                }
            }
        }
    }

    var activeCount: Int { detectedItems.filter { !$0.isExcluded }.count }

    var body: some View {
        if !detectedItems.isEmpty {
            VStack(alignment: .leading, spacing: .spacing2) {
                HStack {
                    Icon("hidden", size: 16)
                        .foregroundStyle(Color.warning)
                        .accessibilityHidden(true)
                    Text("\(activeCount) personal data item\(activeCount == 1 ? "" : "s") detected")
                        .font(.omXs).fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)
                    Spacer()
                    Button { onDismiss() } label: {
                        Icon("close", size: 12)
                            .foregroundStyle(Color.fontTertiary)
                    }
                    .accessibleButton("Dismiss privacy warning", hint: "Closes this personal data warning banner")
                }

                ForEach(detectedItems) { item in
                    HStack(spacing: .spacing2) {
                        Icon(item.type.icon, size: 12)
                            .foregroundStyle(Color.fontTertiary)
                            .accessibilityHidden(true)
                        Text(item.value)
                            .font(.omXs).foregroundStyle(Color.fontSecondary)
                            .lineLimit(1)
                        Spacer()
                        Button {
                            onExclude(item)
                        } label: {
                            Text(item.isExcluded ? "Include" : "Exclude")
                                .font(.omTiny).fontWeight(.medium)
                                .foregroundStyle(item.isExcluded ? Color.buttonPrimary : Color.fontTertiary)
                        }
                        .accessibleButton(
                            item.isExcluded ? "Include \(item.value)" : "Exclude \(item.value)",
                            hint: item.isExcluded
                                ? "Includes this item in the message — it will be sent as-is"
                                : "Replaces this item with a placeholder before sending"
                        )
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("\(item.type.rawValue): \(item.value), \(item.isExcluded ? "included" : "will be masked")")
                }

                Text(LocalizationManager.shared.text("enter_message.pii.banner_description"))
                    .font(.omTiny).foregroundStyle(Color.fontTertiary)
            }
            .padding(.spacing3)
            .background(Color.warning.opacity(0.1))
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
            .padding(.horizontal, .spacing4)
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Privacy warning: \(activeCount) personal data item\(activeCount == 1 ? "" : "s") detected in your message")
        }
    }
}

struct PIIToggleButton: View {
    @Binding var showPlaceholders: Bool

    var body: some View {
        Button {
            showPlaceholders.toggle()
            AccessibilityAnnouncement.announce(showPlaceholders ? "Showing placeholders" : "Showing original values")
        } label: {
            Icon(showPlaceholders ? "hidden" : "visible", size: 16)
                .foregroundStyle(showPlaceholders ? Color.buttonPrimary : Color.fontTertiary)
        }
        .accessibleButton(
            showPlaceholders ? "Show original values" : "Show placeholders",
            hint: "Toggles between masked placeholders and original personal data values"
        )
    }
}
