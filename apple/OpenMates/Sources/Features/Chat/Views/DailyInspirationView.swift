// Daily inspiration banner — shows a rotating inspiration prompt.
// Tapping creates a new chat with the inspiration as the first message.

import SwiftUI

struct DailyInspirationBanner: View {
    let inspiration: DailyInspiration?
    let onTap: (String) -> Void

    struct DailyInspiration: Decodable {
        let text: String
        let category: String?
        let iconName: String?
    }

    var body: some View {
        if let inspiration {
            Button {
                onTap(inspiration.text)
            } label: {
                HStack(spacing: .spacing3) {
                    Image(systemName: "lightbulb.fill")
                        .foregroundStyle(Color.buttonPrimary)

                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(AppStrings.dailyInspiration)
                            .font(.omTiny).fontWeight(.bold)
                            .foregroundStyle(Color.fontTertiary)
                        Text(inspiration.text)
                            .font(.omSmall)
                            .foregroundStyle(Color.fontPrimary)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)
                    }

                    Spacer()

                    Image(systemName: "chevron.right")
                        .font(.caption)
                        .foregroundStyle(Color.fontTertiary)
                }
                .padding(.spacing4)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius4))
            }
            .buttonStyle(.plain)
            .padding(.horizontal, .spacing4)
            .padding(.top, .spacing2)
        }
    }
}
