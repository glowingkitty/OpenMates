//! Assistant changes inside a [`LiveSession`]: `embed_assistant_change` is merged into the open
//! item (`assistant.rs`), sent through the session outbox, reported to the server as an
//! outcome and locked until acknowledged; `embed_assistant_editing` becomes a "mate is
//! editing here" presence peer.
//!
//! Choices:
//! - The frame carries `base_text_form` or only `base_version`. For a version the session
//!   emits [`Action::AssistantNeedBase`]; the host reads that version through the embed
//!   version read path and answers `provide_assistant_base`. Sheet row and column ids are
//!   reconstructed by matching the base table to the live one (`assistant_sheet.rs`).
//! - The outcome is posted as soon as the change is applied locally; the item's assistant
//!   lock is released when the server acknowledges every update of the turn.
//! - An item that is not open yields [`Action::AssistantChangeNotOpen`]; the server also
//!   parks changes for offline requesters, so nothing is lost.
//! - Sheet suggestions live in the session slot (`Slot::suggestions`), not in the shared doc.

use super::assistant::{
    AssistantOutcome, AssistantResult, HunkReport, PinnedBase, apply_assistant_change,
    finish_assistant_change, undo_assistant,
};
use super::assistant_sheet::reconstruct_base;
use super::engine::LiveItem;
use super::ops_json::AssistantOp;
use super::presence::{MatePresence, Presence, color_for};
use super::session::{LiveSession, Slot, emit_change, emit_full, presence_event, sealed_local};
use super::session_types::Action;
use super::{LiveError, LiveItemKind};
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet, VecDeque};

/// The assistant peer disappears this long after `embed_assistant_editing`.
pub const EDITING_TTL_MS: u64 = 60_000;
const PEER_KEY: &str = "assistant";
/// Presence entries expire 30 s after `seen`; `seen` is set this far ahead so the entry
/// outlives the regular TTL and [`EDITING_TTL_MS`] is the real limit.
const SEEN_AHEAD_MS: u64 = EDITING_TTL_MS - super::session::PRESENCE_TTL_MS;

struct Turn {
    turn_id: String,
    new_text: String,
    base_text: Option<String>,
    base_version: Option<i64>,
}

#[derive(Default)]
enum Phase {
    #[default]
    Idle,
    /// Waiting for the host to read the base version.
    Fetching(Turn),
    /// Applied; waiting for the acknowledgement of these client message ids.
    Waiting {
        turn_id: String,
        pending: HashSet<String>,
    },
}

#[derive(Default)]
struct EmbedState {
    queue: VecDeque<Turn>,
    phase: Phase,
    editing_since: Option<u64>,
}

/// Per-embed assistant queues of one [`LiveSession`].
#[derive(Default)]
pub struct AssistantSession {
    embeds: HashMap<String, EmbedState>,
}

fn outcome_body(turn_id: &str, outcome: &AssistantOutcome, current: &str) -> Value {
    let hunks = |list: &[HunkReport]| {
        list.iter()
            .map(|h| {
                json!({"anchor": h.anchor, "assistant_value": h.assistant_value,
                    "human_value": h.human_value})
            })
            .collect::<Vec<_>>()
    };
    let name = if !outcome.target_deleted.is_empty()
        && outcome.applied_hunks == 0
        && outcome.same_spot.is_empty()
        && outcome.suggestions.is_empty()
    {
        "target_deleted"
    } else if !outcome.same_spot.is_empty() && outcome.applied_hunks == 0 {
        "same_spot"
    } else if outcome.needs_recheck {
        "needs_recheck"
    } else {
        "applied"
    };
    json!({"turn_id": turn_id, "outcome": name, "details": {
        "current_text_form": current,
        "same_spot": hunks(&outcome.same_spot),
        "target_deleted": outcome.target_deleted,
        "suggestions": hunks(&outcome.suggestions),
    }})
}

pub(super) fn pinned(item: &LiveItem, base_text: Option<&str>) -> Result<PinnedBase, LiveError> {
    let live = item.text_form()?;
    match base_text {
        None => PinnedBase::pin(item),
        Some(text) if item.kind() == LiveItemKind::Sheet => {
            if text == live {
                PinnedBase::pin(item)
            } else {
                reconstruct_base(item, text)
            }
        }
        Some(text) => Ok(PinnedBase {
            text: text.to_string(),
            rows: Vec::new(),
            cols: Vec::new(),
        }),
    }
}

fn clear_peer(item_id: &str, slot: &mut Slot, state: &mut EmbedState, out: &mut Vec<Action>) {
    state.editing_since = None;
    if slot.presence.remove(PEER_KEY).is_some() {
        out.push(presence_event(item_id, slot));
    }
}

/// Runs queued turns while the embed is idle.
fn pump(
    item_id: &str,
    slot: &mut Slot,
    state: &mut EmbedState,
    user: &Option<String>,
    connected: bool,
    now_ms: u64,
    out: &mut Vec<Action>,
) -> Result<(), LiveError> {
    while matches!(state.phase, Phase::Idle) {
        let Some(turn) = state.queue.pop_front() else {
            return Ok(());
        };
        if slot.item.is_none() {
            state.queue.push_front(turn);
            return Ok(());
        }
        if turn.base_text.is_none()
            && let Some(version) = turn.base_version
        {
            out.push(Action::AssistantNeedBase {
                embed_id: item_id.to_string(),
                turn_id: turn.turn_id.clone(),
                base_version: version,
            });
            state.phase = Phase::Fetching(turn);
            return Ok(());
        }
        if !run_reported(item_id, slot, state, turn, user, connected, now_ms, out) {
            return Ok(());
        }
    }
    Ok(())
}

/// [`run`], but a turn that cannot be applied (text the kind rejects, no content) is
/// reported as `needs_recheck` with the error code instead of being dropped silently.
fn run_reported(
    item_id: &str,
    slot: &mut Slot,
    state: &mut EmbedState,
    turn: Turn,
    user: &Option<String>,
    connected: bool,
    now_ms: u64,
    out: &mut Vec<Action>,
) -> bool {
    let turn_id = turn.turn_id.clone();
    match run(item_id, slot, state, turn, user, connected, now_ms, out) {
        Ok(ran) => ran,
        Err(error) => {
            out.push(Action::PostAssistantOutcome {
                embed_id: item_id.to_string(),
                body: json!({"turn_id": turn_id, "outcome": "needs_recheck",
                    "details": {"reason": error.code()}}),
            });
            clear_peer(item_id, slot, state, out);
            true
        }
    }
}

/// Applies one turn. `false` when the item is busy (the turn goes back to the queue head).
fn run(
    item_id: &str,
    slot: &mut Slot,
    state: &mut EmbedState,
    turn: Turn,
    user: &Option<String>,
    connected: bool,
    now_ms: u64,
    out: &mut Vec<Action>,
) -> Result<bool, LiveError> {
    let item = slot.item.as_mut().ok_or(LiveError::Empty)?;
    let base = pinned(item, turn.base_text.as_deref())?;
    let before = item.state_vector();
    let outcome = match apply_assistant_change(item, &base, &turn.new_text, &turn.turn_id)? {
        AssistantResult::Busy => {
            state.queue.push_front(turn);
            return Ok(false);
        }
        AssistantResult::Applied(outcome) => outcome,
    };
    let current = item.text_form()?;
    let pending: HashSet<String> = outcome
        .updates
        .iter()
        .map(|u| u.client_msg_id.clone())
        .collect();
    for update in &outcome.updates {
        sealed_local(item_id, slot, update, now_ms, user, connected, out);
    }
    for hunk in &outcome.suggestions {
        slot.suggestions
            .insert(hunk.anchor.clone(), hunk.assistant_value.clone());
    }
    if !outcome.updates.is_empty() {
        slot.latest_assistant = Some(turn.turn_id.clone());
    }
    if !outcome.updates.is_empty() || !outcome.suggestions.is_empty() {
        emit_change(item_id, slot, &before, out);
    }
    out.push(Action::PostAssistantOutcome {
        embed_id: item_id.to_string(),
        body: outcome_body(&turn.turn_id, &outcome, &current),
    });
    clear_peer(item_id, slot, state, out);
    if pending.is_empty() {
        if let Some(item) = slot.item.as_mut() {
            finish_assistant_change(item, &turn.turn_id);
        }
    } else {
        state.phase = Phase::Waiting {
            turn_id: turn.turn_id,
            pending,
        };
    }
    Ok(true)
}

impl LiveSession {
    /// Whether this replica has an authorized editor that has not adopted the revision.
    pub(super) fn accepts_project_commit(&self, item_id: &str, revision: i64) -> bool {
        self.connected
            && self.slots.get(item_id).is_some_and(|slot| {
                slot.can_edit == Some(true)
                    && slot.item.is_some()
                    && slot.base_version.is_some_and(|head| head < revision)
            })
    }

    /// Translate the authorized Project writer's stored version into an encrypted
    /// update for the open replicas. A different human edit stays in the live state.
    pub(super) fn adopt_project_commit(
        &mut self,
        item_id: &str,
        turn_id: &str,
        revision: i64,
        base_text: &str,
        committed_text: &str,
        now_ms: u64,
    ) -> Result<Vec<Action>, LiveError> {
        if !self.accepts_project_commit(item_id, revision) {
            return Ok(Vec::new());
        }
        let slot = self.slots.get_mut(item_id).ok_or(LiveError::Empty)?;
        let item = slot.item.as_mut().ok_or(LiveError::Empty)?;
        let before = item.state_vector();
        let base = pinned(item, Some(base_text))?;
        let AssistantResult::Applied(outcome) =
            apply_assistant_change(item, &base, committed_text, turn_id)?
        else {
            return Err(LiveError::Io("live_assistant_busy"));
        };
        finish_assistant_change(item, turn_id);
        let has_uncheckpointed_changes = item.text_form()? != committed_text;
        let mut out = Vec::new();
        for update in &outcome.updates {
            sealed_local(
                item_id,
                slot,
                update,
                now_ms,
                &self.user_id,
                self.connected,
                &mut out,
            );
        }
        if !outcome.updates.is_empty() {
            slot.latest_assistant = Some(turn_id.to_owned());
        }
        for suggestion in outcome.suggestions {
            slot.suggestions
                .insert(suggestion.anchor, suggestion.assistant_value);
        }
        slot.base_version = Some(revision);
        if !has_uncheckpointed_changes {
            slot.dirty_since = None;
            slot.contributors.clear();
        }
        emit_change(item_id, slot, &before, &mut out);
        if let Some(state) = self.assistant.embeds.get_mut(item_id) {
            clear_peer(item_id, slot, state, &mut out);
        }
        Ok(out)
    }

    /// Takes the latest assistant transaction if no local edit has followed it.
    pub(super) fn take_assistant_undo(&mut self, item_id: &str) -> Option<String> {
        self.slots
            .get_mut(item_id)
            .filter(|slot| slot.can_edit == Some(true))?
            .latest_assistant
            .take()
    }

    /// `embed_assistant_change` and `embed_assistant_editing` frames (called from `on_frame`).
    ///
    /// # Errors
    /// Content errors of the change (invalid text for the kind).
    pub(super) fn on_assistant_frame(
        &mut self,
        message_type: &str,
        payload: &Value,
        now_ms: u64,
    ) -> Result<Vec<Action>, LiveError> {
        let Some(embed_id) = payload["embed_id"].as_str().map(str::to_string) else {
            return Ok(Vec::new());
        };
        let mut out = Vec::new();
        let (connected, user) = (self.connected, self.user_id.clone());
        let Some(slot) = self.slots.get_mut(&embed_id) else {
            if message_type == "embed_assistant_change" {
                out.push(Action::AssistantChangeNotOpen {
                    embed_id,
                    frame: payload.clone(),
                });
            }
            return Ok(out);
        };
        let state = self.assistant.embeds.entry(embed_id.clone()).or_default();
        if message_type == "embed_assistant_editing" {
            let scope: Vec<&str> = payload["scope"]
                .as_array()
                .map(|l| l.iter().filter_map(Value::as_str).collect())
                .unwrap_or_default();
            let mate_name = payload["mate_name"].as_str().unwrap_or("Assistant");
            let peer = Presence {
                user_id: PEER_KEY.to_string(),
                display_name: mate_name.to_string(),
                color: color_for(mate_name),
                cursor: None,
                mate: Some(MatePresence {
                    mate_name: mate_name.to_string(),
                    editing_scope: scope.join(", "),
                }),
            };
            let mut value =
                serde_json::to_value(&peer).map_err(|e| LiveError::InvalidUpdate(e.to_string()))?;
            // Shells use the display name directly, while the nested presence retains the scope.
            value["mate_name"] = Value::String(mate_name.to_string());
            slot.presence
                .insert(PEER_KEY.to_string(), (value, now_ms + SEEN_AHEAD_MS));
            state.editing_since = Some(now_ms);
            out.push(presence_event(&embed_id, slot));
            return Ok(out);
        }
        let Some(new_text) = payload["new_text_form"].as_str() else {
            return Ok(out);
        };
        state.queue.push_back(Turn {
            turn_id: payload["turn_id"].as_str().unwrap_or_default().to_string(),
            new_text: new_text.to_string(),
            base_text: payload["base_text_form"].as_str().map(str::to_string),
            base_version: payload["base_version"].as_i64(),
        });
        pump(&embed_id, slot, state, &user, connected, now_ms, &mut out)?;
        Ok(out)
    }

    /// The host read the text form of the version named in [`Action::AssistantNeedBase`].
    ///
    /// # Errors
    /// Content errors of the change.
    pub fn provide_assistant_base(
        &mut self,
        embed_id: &str,
        turn_id: &str,
        base_text: &str,
        now_ms: u64,
    ) -> Result<Vec<Action>, LiveError> {
        let (connected, user) = (self.connected, self.user_id.clone());
        let (Some(slot), Some(state)) = (
            self.slots.get_mut(embed_id),
            self.assistant.embeds.get_mut(embed_id),
        ) else {
            return Ok(Vec::new());
        };
        let mut out = Vec::new();
        match std::mem::take(&mut state.phase) {
            Phase::Fetching(mut turn) if turn.turn_id == turn_id => {
                turn.base_text = Some(base_text.to_string());
                if !run_reported(
                    embed_id, slot, state, turn, &user, connected, now_ms, &mut out,
                ) {
                    return Ok(out);
                }
            }
            other => state.phase = other,
        }
        pump(embed_id, slot, state, &user, connected, now_ms, &mut out)?;
        Ok(out)
    }

    /// The base version could not be read: report `needs_recheck` and move on.
    pub fn fail_assistant_base(
        &mut self,
        embed_id: &str,
        turn_id: &str,
        now_ms: u64,
    ) -> Vec<Action> {
        let (connected, user) = (self.connected, self.user_id.clone());
        let (Some(slot), Some(state)) = (
            self.slots.get_mut(embed_id),
            self.assistant.embeds.get_mut(embed_id),
        ) else {
            return Vec::new();
        };
        let mut out = Vec::new();
        if matches!(&state.phase, Phase::Fetching(t) if t.turn_id == turn_id) {
            state.phase = Phase::Idle;
            out.push(Action::PostAssistantOutcome {
                embed_id: embed_id.to_string(),
                body: json!({"turn_id": turn_id, "outcome": "needs_recheck",
                    "details": {"reason": "base_version_unavailable"}}),
            });
            clear_peer(embed_id, slot, state, &mut out);
        }
        // pump reports turn errors as outcomes and never fails.
        let _ = pump(embed_id, slot, state, &user, connected, now_ms, &mut out);
        out
    }

    /// After a `live_item_update_ack`: releases the lock when the turn is fully acknowledged
    /// and starts the next queued turn.
    pub(super) fn assistant_acked(
        &mut self,
        item_id: &str,
        payload: &Value,
        now_ms: u64,
    ) -> Result<Vec<Action>, LiveError> {
        let (connected, user) = (self.connected, self.user_id.clone());
        let (Some(slot), Some(state)) = (
            self.slots.get_mut(item_id),
            self.assistant.embeds.get_mut(item_id),
        ) else {
            return Ok(Vec::new());
        };
        let acked = payload["client_msg_id"].as_str().unwrap_or_default();
        if let Phase::Waiting { turn_id, pending } = &mut state.phase {
            pending.remove(acked);
            if pending.is_empty() {
                if let Some(item) = slot.item.as_mut() {
                    finish_assistant_change(item, turn_id);
                }
                state.phase = Phase::Idle;
            }
        }
        let mut out = Vec::new();
        pump(item_id, slot, state, &user, connected, now_ms, &mut out)?;
        Ok(out)
    }

    /// Clock tick: clears assistant presence after [`EDITING_TTL_MS`] and retries queued
    /// turns that found the item busy.
    pub fn assistant_tick(&mut self, now_ms: u64) -> Vec<Action> {
        let (connected, user) = (self.connected, self.user_id.clone());
        let mut out = Vec::new();
        for (id, state) in &mut self.assistant.embeds {
            let Some(slot) = self.slots.get_mut(id) else {
                continue;
            };
            if state
                .editing_since
                .is_some_and(|since| now_ms.saturating_sub(since) >= EDITING_TTL_MS)
            {
                clear_peer(id, slot, state, &mut out);
            }
            // pump reports turn errors as outcomes and never fails.
            let _ = pump(id, slot, state, &user, connected, now_ms, &mut out);
        }
        out
    }

    /// Runs `undo_assistant` / `dismiss_suggestion` (see `ops_json::parse_assistant_op`).
    ///
    /// # Errors
    /// The item is not open, not ready or read-only.
    pub fn apply_assistant_op(
        &mut self,
        item_id: &str,
        op: AssistantOp,
        now_ms: u64,
    ) -> Result<Vec<Action>, LiveError> {
        let (connected, user) = (self.connected, self.user_id.clone());
        let slot = self
            .slots
            .get_mut(item_id)
            .ok_or_else(|| LiveError::InvalidUpdate(format!("item not open: {item_id}")))?;
        let mut out = Vec::new();
        match op {
            AssistantOp::DismissSuggestion { row_id, col_id } => {
                if slot
                    .suggestions
                    .remove(&format!("{row_id}:{col_id}"))
                    .is_some()
                {
                    emit_full(item_id, slot, &mut out);
                }
            }
            AssistantOp::Undo { turn_id } => {
                if slot.can_edit == Some(false) {
                    return Err(LiveError::InvalidUpdate("read_only".to_string()));
                }
                let item = slot.item.as_mut().ok_or(LiveError::Empty)?;
                let before = item.state_vector();
                if let Some(update) = undo_assistant(item, &turn_id)? {
                    sealed_local(item_id, slot, &update, now_ms, &user, connected, &mut out);
                    emit_change(item_id, slot, &before, &mut out);
                } else if slot.kind == LiveItemKind::Deck {
                    emit_full(item_id, slot, &mut out);
                }
            }
        }
        Ok(out)
    }
}
