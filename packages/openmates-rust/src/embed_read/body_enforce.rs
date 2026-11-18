//! spec: app-skills.answer.only-result-embeds-in-body
//! Block-level answer-body rule: a skill-invocation embed in the answer text is
//! replaced by its result cards (web `enforceBodyEmbedPolicy`, block part of
//! `bodyEmbedPolicy.ts`). Pure: the caller supplies the block references in
//! document order and renders the returned slots.
use std::collections::HashSet;

use super::body_policy::body_may_show_embed;

/// One block-level `[!](embed:ref)` reference of a message body.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BodyEmbedRef {
    /// Authored reference (with or without the `embed:` prefix).
    pub embed_ref: String,
    /// Resolved embed id, when known.
    pub embed_id: Option<String>,
    /// Resolved embed type, when known.
    pub type_name: Option<String>,
    /// App id of the embed, when known.
    pub app_id: Option<String>,
    /// Skill id of the embed, when known.
    pub skill_id: Option<String>,
    /// Result child ids; `None` while the children are not known yet.
    pub child_ids: Option<Vec<String>>,
}

/// What the body renders in place of one block reference.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BodyEmbedSlot {
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

fn strip_prefix(reference: &str) -> &str {
    reference.strip_prefix("embed:").unwrap_or(reference)
}

/// Applies the answer-body rule to groups of adjacent block embeds. Output
/// keeps the group count and order; a group may become empty. `activity_ids`
/// are invocation ids that already have an activity node.
pub fn enforce_block_embeds(
    groups: &[Vec<BodyEmbedRef>],
    activity_ids: &[String],
) -> Vec<Vec<BodyEmbedSlot>> {
    let mut shown: HashSet<String> = HashSet::new();
    for r in groups.iter().flatten() {
        if body_may_show_embed(Some(&r.embed_ref), r.type_name.as_deref()) {
            shown.insert(r.embed_ref.clone());
            if let Some(id) = &r.embed_id {
                shown.insert(id.clone());
            }
        }
    }
    let mut activity: HashSet<String> = activity_ids.iter().cloned().collect();
    groups
        .iter()
        .map(|group| {
            let mut out = Vec::new();
            for r in group {
                enforce_one(r, &mut shown, &mut activity, &mut out);
            }
            out
        })
        .collect()
}

fn enforce_one(
    r: &BodyEmbedRef,
    shown: &mut HashSet<String>,
    activity: &mut HashSet<String>,
    out: &mut Vec<BodyEmbedSlot>,
) {
    if body_may_show_embed(Some(&r.embed_ref), r.type_name.as_deref()) {
        out.push(BodyEmbedSlot::Card {
            embed_ref: r.embed_ref.clone(),
            embed_id: r.embed_id.clone(),
        });
        return;
    }
    let parent = r
        .embed_id
        .clone()
        .unwrap_or_else(|| strip_prefix(&r.embed_ref).to_owned());
    let type_known = r.type_name.as_deref().is_some_and(|t| !t.is_empty());
    let mut emitted_activity = false;
    if type_known && !activity.contains(&parent) {
        activity.insert(parent.clone());
        emitted_activity = true;
        out.push(BodyEmbedSlot::Activity {
            embed_id: parent.clone(),
            app_id: r.app_id.clone(),
            skill_id: r.skill_id.clone(),
            results_pending: r.child_ids.is_none(),
        });
    }
    match &r.child_ids {
        None => {
            if !emitted_activity {
                out.push(BodyEmbedSlot::Hidden { embed_id: parent });
            }
        }
        Some(children) => {
            for child in children {
                if shown.insert(child.clone()) {
                    out.push(BodyEmbedSlot::Card {
                        embed_ref: child.clone(),
                        embed_id: Some(child.clone()),
                    });
                }
            }
        }
    }
}
