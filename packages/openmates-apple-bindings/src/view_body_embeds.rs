//! Message-body embed rules for the Apple shell (spec
//! `app-skills.answer.only-result-embeds-in-body`): whether an authored body
//! reference may render its embed, and the carousel grouping of consecutive
//! large embed previews. Marshals `openmates_sdk::embed_read::{body_policy,
//! carousel_runs}` (web `bodyEmbedPolicy.ts`); no logic lives here.
use openmates_sdk::embed_read::body_policy;
use openmates_sdk::embed_read::carousel_runs::{
    self, BodyNode as CoreNode, BodyNodeKind as CoreKind,
};

/// Kind of one body node at one nesting level.
#[derive(Debug, Clone, Copy, PartialEq, Eq, uniffi::Enum)]
pub enum BodyNodeKindRecord {
    /// A paragraph without content.
    EmptyParagraph,
    /// A paragraph with content.
    Paragraph,
    /// A large embed preview block.
    EmbedLarge,
    /// Any other node.
    Other,
}

/// One body node handed to carousel grouping.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct BodyNodeRecord {
    /// Node kind.
    pub kind: BodyNodeKindRecord,
    /// Embed ref for `EmbedLarge`, else empty.
    pub embed_ref: String,
    /// Hidden placeholder: keeps position, renders nothing, never counted.
    pub hidden: bool,
}

/// Placement and carousel metadata of one kept node.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct CarouselPlacementRecord {
    /// Index of the node in the input list.
    pub source_index: u32,
    /// Position in its run; -1 for hidden and non-embed nodes.
    pub carousel_index: i32,
    /// Visible items in the run; 0 for hidden and non-embed nodes.
    pub carousel_total: u32,
    /// Ref of the run's first visible embed; empty when not applicable.
    pub run_ref: String,
}

/// May an authored body reference render this embed? A skill invocation never does.
#[uniffi::export]
pub fn body_may_show_embed(embed_ref: Option<String>, type_name: Option<String>) -> bool {
    body_policy::body_may_show_embed(embed_ref.as_deref(), type_name.as_deref())
}

/// Groups consecutive large embeds of one nesting level into carousels. Output
/// is the kept nodes in render order; dropped empty paragraphs are absent.
#[uniffi::export]
pub fn body_assign_carousel_runs(nodes: Vec<BodyNodeRecord>) -> Vec<CarouselPlacementRecord> {
    let core: Vec<CoreNode> = nodes
        .into_iter()
        .map(|n| CoreNode {
            kind: match n.kind {
                BodyNodeKindRecord::EmptyParagraph => CoreKind::EmptyParagraph,
                BodyNodeKindRecord::Paragraph => CoreKind::Paragraph,
                BodyNodeKindRecord::EmbedLarge => CoreKind::EmbedLarge,
                BodyNodeKindRecord::Other => CoreKind::Other,
            },
            embed_ref: n.embed_ref,
            hidden: n.hidden,
        })
        .collect();
    carousel_runs::assign_carousel_runs(&core)
        .into_iter()
        .map(|p| CarouselPlacementRecord {
            source_index: p.source_index as u32,
            carousel_index: p.carousel_index,
            carousel_total: p.carousel_total,
            run_ref: p.run_ref,
        })
        .collect()
}
