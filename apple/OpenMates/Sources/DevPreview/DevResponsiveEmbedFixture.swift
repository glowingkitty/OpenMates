// Fixed footer regression: real production cards, synthetic content variants.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//         frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
//         frontend/packages/ui/src/components/embeds/health/HealthAppointmentEmbedPreview.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.layout.responsive-history

#if DEBUG
import SwiftUI

struct DevResponsiveEmbedFixture: View {
    let large: Bool
    @State private var index = 0
    @State private var bounds: [String: CGRect] = [:]
    private let states = ["short", "long", "processing", "error", "cancelled", "full-width"]

    private var record: EmbedRecord {
        var data: [String: AnyCodable] = ["name": AnyCodable(index == 0 ? "Dr. Example" : "Dr. Example With A Deliberately Long Name That Wraps Across Several Lines"),
            "slot_datetime": AnyCodable("2026-10-04T10:30:00"),
            "provider": AnyCodable("Jameda"), "provider_platform": AnyCodable("Jameda")]
        if index != 0 {
            data["speciality"] = AnyCodable("General practitioner and preventive medicine")
            data["address"] = AnyCodable("Example Street 123, Berlin")
            data["insurance"] = AnyCodable("public")
            data["telehealth"] = AnyCodable(true)
            data["rating"] = AnyCodable(4.8)
            data["rating_count"] = AnyCodable(123)
            data["price"] = AnyCodable(120)
        }
        let status: EmbedStatus = index == 2 ? .processing : index == 3 ? .error : index == 4 ? .cancelled : .finished
        if index == 5 {
            data = ["title": AnyCodable("Responsive document"), "filename": AnyCodable("responsive.docx"),
                "html_content": AnyCodable("<h1>Responsive document</h1><p>" + String(repeating: "A synthetic paragraph. ", count: 80) + "</p>")]
        }
        return EmbedRecord(id: "responsive-footer-fixture", type: index == 5 ? "docs-doc" : "health-appointment",
            status: status, data: .raw(data), parentEmbedId: nil,
            appId: index == 5 ? "docs" : "health", skillId: nil, embedIds: nil, createdAt: nil)
    }

    var body: some View {
        GeometryReader { viewport in
            VStack(spacing: .spacing10) {
                Button("Next fixture content") { index = (index + 1) % states.count }
                    .buttonStyle(.plain).accessibilityIdentifier("responsive-preview-next-content")
                Text(states[index]).font(.omTiny)
                    .accessibilityIdentifier("responsive-preview-content-state")
                EmbedPreviewCard(embed: record, variant: large ? .large : .compact) {}
                    .frame(width: large ? max(300, viewport.size.width - 40) : 300)
                    .coordinateSpace(name: "responsive-preview-fixture")
                    .onPreferenceChange(EmbedPreviewGeometryKey.self) { bounds = $0 }
                Spacer(minLength: 0)
            }
            .padding(.spacing10)
            .frame(width: viewport.size.width, height: viewport.size.height, alignment: .top)
            .overlay(alignment: .bottomLeading) {
                VStack(spacing: 0) {
                    ForEach(["card", "footer", "circle"], id: \.self) { key in
                        let rect = bounds[key] ?? .zero
                        Text(" ").font(.omTiny).foregroundStyle(Color.clear)
                            .frame(width: 1, height: 1).allowsHitTesting(false)
                            .accessibilityLabel("\(rect.minX),\(rect.minY),\(rect.width),\(rect.height)")
                            .accessibilityIdentifier("responsive-preview-\(key)-bounds")
                    }
                }
            }
        }
    }
}
#endif
