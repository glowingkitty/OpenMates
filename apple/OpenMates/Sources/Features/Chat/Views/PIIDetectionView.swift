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
                case .email: return "envelope"
                case .phone: return "phone"
                case .address: return "mappin"
                case .name: return "person"
                case .birthday: return "gift"
                case .custom: return "eye.slash"
                }
            }
        }
    }

    var activeCount: Int { detectedItems.filter { !$0.isExcluded }.count }

    var body: some View {
        if !detectedItems.isEmpty {
            VStack(alignment: .leading, spacing: .spacing2) {
                HStack {
                    Image(systemName: "eye.slash.fill")
                        .foregroundStyle(Color.warning)
                    Text("\(activeCount) personal data item\(activeCount == 1 ? "" : "s") detected")
                        .font(.omXs).fontWeight(.medium)
                        .foregroundStyle(Color.fontPrimary)
                    Spacer()
                    Button { onDismiss() } label: {
                        Image(systemName: "xmark").font(.caption)
                            .foregroundStyle(Color.fontTertiary)
                    }
                }

                ForEach(detectedItems) { item in
                    HStack(spacing: .spacing2) {
                        Image(systemName: item.type.icon)
                            .font(.caption).foregroundStyle(Color.fontTertiary)
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
                    }
                }

                Text("Active items will be replaced with placeholders before sending.")
                    .font(.omTiny).foregroundStyle(Color.fontTertiary)
            }
            .padding(.spacing3)
            .background(Color.warning.opacity(0.1))
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
            .padding(.horizontal, .spacing4)
        }
    }
}

struct PIIToggleButton: View {
    @Binding var showPlaceholders: Bool

    var body: some View {
        Button {
            showPlaceholders.toggle()
        } label: {
            Image(systemName: showPlaceholders ? "eye.slash.fill" : "eye.fill")
                .font(.caption)
                .foregroundStyle(showPlaceholders ? Color.buttonPrimary : Color.fontTertiary)
        }
    }
}
