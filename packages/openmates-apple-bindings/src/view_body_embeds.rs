//! Message-body embed rules for the Apple shell (spec
//! `app-skills.answer.only-result-embeds-in-body`): whether an authored body
//! reference may render its embed, and the carousel grouping of consecutive
//! large embed previews. Marshals `openmates_sdk::embed_read::{body_policy,
//! carousel_runs}` (web `bodyEmbedPolicy.ts`); no logic lives here.
use openmates_sdk::embed_read::body_enforce::{
    self, BodyEmbedRef as CoreRef, BodyEmbedSlot as CoreSlot,
};
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

/// One block-level embed reference of a message body.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct BodyEmbedRefRecord {
    /// Authored reference.
    pub embed_ref: String,
    /// Resolved embed id, when known.
    pub embed_id: Option<String>,
    /// Resolved embed type, when known.
    pub type_name: Option<String>,
    /// App id, when known.
    pub app_id: Option<String>,
    /// Skill id, when known.
    pub skill_id: Option<String>,
    /// Result child ids; `None` while not known yet.
    pub child_ids: Option<Vec<String>>,
}

/// What the body renders in place of one block reference.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Enum)]
pub enum BodyEmbedSlotRecord {
    /// A result card.
    Card {
        /// Reference to render.
        embed_ref: String,
        /// Embed id, when known.
        embed_id: Option<String>,
    },
    /// A compact activity line marking where a skill ran.
    Activity {
        /// Invocation embed id.
        embed_id: String,
        /// App id, when known.
        app_id: Option<String>,
        /// Skill id, when known.
        skill_id: Option<String>,
        /// Children are not known yet.
        results_pending: bool,
    },
    /// Keeps the position, renders nothing.
    Hidden {
        /// Embed id kept for later resolution.
        embed_id: String,
    },
}

/// Replaces skill-invocation embeds in the body with their result cards.
/// Output keeps the group count and order.
#[uniffi::export]
pub fn body_enforce_block_embeds(
    groups: Vec<Vec<BodyEmbedRefRecord>>,
    activity_ids: Vec<String>,
) -> Vec<Vec<BodyEmbedSlotRecord>> {
    let core: Vec<Vec<CoreRef>> = groups
        .into_iter()
        .map(|g| {
            g.into_iter()
                .map(|r| CoreRef {
                    embed_ref: r.embed_ref,
                    embed_id: r.embed_id,
                    type_name: r.type_name,
                    app_id: r.app_id,
                    skill_id: r.skill_id,
                    child_ids: r.child_ids,
                })
                .collect()
        })
        .collect();
    body_enforce::enforce_block_embeds(&core, &activity_ids)
        .into_iter()
        .map(|g| {
            g.into_iter()
                .map(|s| match s {
                    CoreSlot::Card {
                        embed_ref,
                        embed_id,
                    } => BodyEmbedSlotRecord::Card {
                        embed_ref,
                        embed_id,
                    },
                    CoreSlot::Activity {
                        embed_id,
                        app_id,
                        skill_id,
                        results_pending,
                    } => BodyEmbedSlotRecord::Activity {
                        embed_id,
                        app_id,
                        skill_id,
                        results_pending,
                    },
                    CoreSlot::Hidden { embed_id } => BodyEmbedSlotRecord::Hidden { embed_id },
                })
                .collect()
        })
        .collect()
}
