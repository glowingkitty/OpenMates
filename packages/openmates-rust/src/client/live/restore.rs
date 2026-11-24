//! Merge a version restore into the open replica and record it as a new
//! client-side encrypted checkpoint (live-collab.versions.named-snapshots).

use super::assistant::{AssistantResult, apply_change, gaps, matches};
use super::assistant_session::pinned;
use super::doc_html::{Block, block_html, blocks_html, parse_blocks};
use super::session::{LiveSession, emit_change, sealed_local};
use super::session_types::{Action, CheckpointRequest, CheckpointResult, Event};
use super::{LiveError, LiveItemKind};

/// A proposed checkpoint and its update on a fork, both still private to the client.
pub(super) struct PreparedRestore {
    pub(super) checkpoint: CheckpointRequest,
    update: Option<Vec<u8>>,
}

/// When the older version removes a paragraph, preserve text appended to that paragraph
/// after the current checkpoint. Other overlapping rewrites require a new selection.
fn keep_appended_text(base: &str, selected: &str, live: &str) -> (String, String) {
    let mut base = parse_blocks(base);
    let mut selected = parse_blocks(selected);
    let live = parse_blocks(live);
    let to_units = |blocks: &[Block]| blocks.iter().map(block_html).collect::<Vec<_>>();
    let base_units = to_units(&base);
    let selected_units = to_units(&selected);
    let live_units = to_units(&live);
    let removals = gaps(
        base.len(),
        selected.len(),
        &matches(&base_units, &selected_units),
    );
    let edits = gaps(base.len(), live.len(), &matches(&base_units, &live_units));
    for (start, end, selected_start, selected_end) in removals.into_iter().rev() {
        if end != start + 1 || selected_start != selected_end {
            continue;
        }
        let Some(&(_, _, live_index, _)) = edits
            .iter()
            .find(|&&(a, b, c, d)| a == start && b == end && d == c + 1)
        else {
            continue;
        };
        let (Block::Paragraph(before), Block::Paragraph(after)) = (&base[start], &live[live_index])
        else {
            continue;
        };
        let ([before], [after]) = (before.as_slice(), after.as_slice()) else {
            continue;
        };
        let Some(suffix) = after
            .text
            .strip_prefix(&before.text)
            .filter(|s| !s.is_empty())
        else {
            continue;
        };
        let mut prefix = after.clone();
        prefix.text.clone_from(&before.text);
        if &prefix != before {
            continue;
        }
        let mut kept = after.clone();
        kept.text = suffix.to_owned();
        base[start] = live[live_index].clone();
        selected.insert(selected_start, Block::Paragraph(vec![kept]));
    }
    (blocks_html(&base), blocks_html(&selected))
}

impl LiveSession {
    /// Plans the restore on a fork so a stale checkpoint leaves the live item untouched.
    pub(super) fn prepare_version_restore(
        &self,
        item_id: &str,
        source: i64,
        head: i64,
        base_text: &str,
        restored_text: &str,
    ) -> Result<PreparedRestore, LiveError> {
        let slot = self.slots.get(item_id).ok_or(LiveError::Empty)?;
        if !self.connected || slot.can_edit != Some(true) {
            return Err(LiveError::Io("live_restore_unavailable"));
        }
        if !matches!(slot.kind, LiveItemKind::Doc | LiveItemKind::Sheet)
            || source < 1
            || source >= head
            || slot.base_version != Some(head)
            || slot.checkpoint_inflight
        {
            return Err(LiveError::Io("live_restore_stale"));
        }
        let item = slot.item.as_ref().ok_or(LiveError::Empty)?;
        let mut fork = item.fork()?;
        let before = fork.state_vector();
        let doc_restore;
        let (base_text, restored_text) = if slot.kind == LiveItemKind::Doc {
            doc_restore = keep_appended_text(base_text, restored_text, &fork.text_form()?);
            (doc_restore.0.as_str(), doc_restore.1.as_str())
        } else {
            (base_text, restored_text)
        };
        let base = pinned(&fork, Some(base_text))?;
        let operation = uuid::Uuid::new_v4().to_string();
        let AssistantResult::Applied(outcome) =
            apply_change(&mut fork, &base, restored_text, &operation, true)?
        else {
            return Err(LiveError::Io("live_restore_busy"));
        };
        if !(outcome.same_spot.is_empty() && outcome.suggestions.is_empty()) {
            return Err(LiveError::Io("live_restore_concurrent_change"));
        }
        let update = if outcome.updates.is_empty() {
            None
        } else {
            Some(fork.encode_update_since(&before)?)
        };
        let mut contributors = slot.contributors.clone();
        contributors.extend(self.user_id.iter().cloned());
        Ok(PreparedRestore {
            checkpoint: CheckpointRequest {
                item_id: item_id.to_owned(),
                base_version: Some(head),
                version_kind: "restore",
                restored_from: Some(source),
                contributors: contributors.into_iter().collect(),
                text: fork.text_form()?,
            },
            update,
        })
    }

    /// Publishes the restore to collaborators only after the encrypted checkpoint commits.
    pub(super) fn finish_version_restore(
        &mut self,
        prepared: &PreparedRestore,
        version: i64,
        now_ms: u64,
    ) -> Result<Vec<Action>, LiveError> {
        let item_id = &prepared.checkpoint.item_id;
        let slot = self.slots.get_mut(item_id).ok_or(LiveError::Empty)?;
        slot.latest_assistant = None;
        let mut actions = Vec::new();
        if let Some(bytes) = &prepared.update {
            let item = slot.item.as_mut().ok_or(LiveError::Empty)?;
            let before = item.state_vector();
            let update = item.enqueue_replica_update(bytes)?;
            sealed_local(
                item_id,
                slot,
                &update,
                now_ms,
                &self.user_id,
                self.connected,
                &mut actions,
            );
            emit_change(item_id, slot, &before, &mut actions);
        }
        actions.extend(self.checkpoint_result(item_id, CheckpointResult::Written(version), now_ms));
        actions.push(Action::Emit(Event::VersionWritten {
            item_id: item_id.clone(),
            version,
            text: prepared.checkpoint.text.clone(),
        }));
        Ok(actions)
    }
}
