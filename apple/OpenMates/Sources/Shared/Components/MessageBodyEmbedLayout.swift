import Foundation

// spec: app-skills.answer.only-result-embeds-in-body
// Message-body embed placement rules. The rules themselves live in the Rust core
// (embed_read::body_policy and embed_read::carousel_runs, web bodyEmbedPolicy.ts);
// this file only maps MarkdownBlock values to the generated UniFFI API
// (view_body_embeds.rs) and back. No policy is decided in Swift.

/// One body block with its carousel placement after grouping.
struct MessageBodyPlacedBlock: Equatable {
    let sourceIndex: Int
    /// Position in the embed run; -1 for non-embed blocks.
    let carouselIndex: Int
    /// Number of embed groups in the run; 0 for non-embed blocks.
    let carouselTotal: Int
}

enum MessageBodyEmbedLayout {
    /// May an authored body reference render this embed? Skill invocations never do.
    static func mayShow(reference: String, type: String?) -> Bool {
        bodyMayShowEmbed(embedRef: reference, typeName: type)
    }

    /// Drops references to skill-use embeds from an embed group.
    static func visibleReferences(
        _ references: [MarkdownEmbedReference],
        typeFor: (String) -> String?
    ) -> [MarkdownEmbedReference] {
        references.filter { reference in
            mayShow(reference: reference.value, type: reference.type ?? typeFor(reference.value))
        }
    }

    /// Groups consecutive embed-group blocks into carousel runs and drops blank
    /// paragraphs inside a run. A group whose references are all hidden stays
    /// in place and is not counted.
    static func place(
        blocks: [MarkdownBlock],
        typeFor: (String) -> String?
    ) -> [MessageBodyPlacedBlock] {
        let nodes: [BodyNodeRecord] = blocks.map { block in
            switch block {
            case .embedGroup(let references):
                let visible = visibleReferences(references, typeFor: typeFor)
                return BodyNodeRecord(
                    kind: .embedLarge,
                    embedRef: visible.first?.value ?? references.first?.value ?? "",
                    hidden: visible.isEmpty
                )
            case .paragraph(let text):
                let blank = text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                return BodyNodeRecord(kind: blank ? .emptyParagraph : .paragraph, embedRef: "", hidden: false)
            default:
                return BodyNodeRecord(kind: .other, embedRef: "", hidden: false)
            }
        }
        return bodyAssignCarouselRuns(nodes: nodes).map {
            MessageBodyPlacedBlock(
                sourceIndex: Int($0.sourceIndex),
                carouselIndex: Int($0.carouselIndex),
                carouselTotal: Int($0.carouselTotal)
            )
        }
    }
}
