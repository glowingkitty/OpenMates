// Legal document viewer — privacy policy, terms of use, imprint.
// Fetches legal content from backend and renders as scrollable text.

import SwiftUI

struct LegalChatView: View {
    let documentType: LegalDocumentType

    @State private var content: String?
    @State private var isLoading = true
    @State private var error: String?

    enum LegalDocumentType: String, CaseIterable {
        case privacy = "privacy-policy"
        case terms = "terms-of-use"
        case imprint = "imprint"

        var title: String {
            switch self {
            case .privacy: return "Privacy Policy"
            case .terms: return "Terms of Use"
            case .imprint: return "Imprint"
            }
        }

        var icon: String {
            switch self {
            case .privacy: return "safety"
            case .terms: return "text"
            case .imprint: return "business"
            }
        }
    }

    var body: some View {
        ScrollView {
            if isLoading {
                ProgressView()
                    .padding(.top, .spacing16)
            } else if let error {
                VStack(spacing: .spacing4) {
                    Icon("warning", size: 36)
                        .foregroundStyle(Color.error)
                    Text(error)
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                    Button("Retry") { Task { await loadContent() } }
                        .buttonStyle(OMSecondaryButtonStyle())
                }
                .padding(.top, .spacing16)
            } else if let content {
                Text(attributedContent(content))
                    .font(.omP)
                    .foregroundStyle(Color.fontPrimary)
                    .textSelection(.enabled)
                    .padding(.spacing6)
            }
        }
        .navigationTitle(documentType.title)
        #if os(iOS)
        .navigationBarTitleDisplayMode(.large)
        #endif
        .task { await loadContent() }
    }

    private func loadContent() async {
        isLoading = true
        error = nil
        do {
            let response: LegalContentResponse = try await APIClient.shared.request(
                .get, path: "/v1/public/legal/\(documentType.rawValue)"
            )
            content = response.content
        } catch {
            self.error = "Failed to load \(documentType.title)"
        }
        isLoading = false
    }

    private func attributedContent(_ text: String) -> AttributedString {
        (try? AttributedString(markdown: text, options: .init(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        ))) ?? AttributedString(text)
    }
}

struct LegalContentResponse: Decodable {
    let content: String
    let lastUpdated: String?
}
