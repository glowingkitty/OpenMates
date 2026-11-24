//! Assistant change sets: a mate's edit of a live item is merged with what humans did since
//! the assistant read it (the pinned base). Hunks whose target is unchanged are applied in
//! ONE Yjs transaction with origin `assistant:{turn_id}` (one undo step, one timeline
//! entry); a hunk a human touched becomes a same-spot conflict or (sheets) a suggestion;
//! a hunk whose target a human deleted is dropped. A per-item lock holds a second change
//! set until the first one is released with [`finish_assistant_change`].
//!
//! Hunks are computed per unit: code lines, document top-level blocks, sheet cells (by
//! stable ids), deck text elements. Positions are resolved against the live content inside
//! the same synchronous transaction, which makes them equivalent to relative positions.

use super::assistant_sheet;
use super::doc::{fragment_of, read_blocks, replace_blocks};
use super::doc_html::{Block, block_html, parse_blocks};
use super::engine::{LiveItem, LocalOp, SealedUpdate};
use super::{LiveError, LiveItemKind};
use crate::client::shared_items::DeckOperation;
use crate::client::shared_items::deck_markup::{ElementContent, parse_deck_markup};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use yrs::undo::{Options as UndoOptions, UndoManager};
use yrs::updates::decoder::Decode;
use yrs::{Doc, Text, Transact, Update};

/// Share of the text form a human may change elsewhere before `needs_recheck` is set.
const RECHECK_PERCENT: usize = 20;

/// Per-item assistant lock and the undo managers of applied change sets.
#[derive(Default)]
pub(super) struct AssistantState {
    pending: Option<String>,
    undo: HashMap<String, UndoManager<()>>,
}

impl AssistantState {
    /// Starts tracking `origin` for undo; call before the transaction that uses it.
    pub(super) fn track(&mut self, doc: &Doc, kind: LiveItemKind, turn_id: &str) {
        let options = UndoOptions {
            capture_timeout_millis: 1000,
            tracked_origins: HashSet::new(),
            capture_transaction: None,
            timestamp: Arc::new(|| 0),
            init_undo_stack: Vec::new(),
            init_redo_stack: Vec::new(),
        };
        let mut undo = UndoManager::with_options(options);
        match kind {
            LiveItemKind::Code => undo.expand_scope(doc, &doc.get_or_insert_text("content")),
            LiveItemKind::Doc => undo.expand_scope(doc, &doc.get_or_insert_xml_fragment("default")),
            LiveItemKind::Deck => {
                use crate::client::shared_items::ROOT_SLIDES;
                undo.expand_scope(doc, &doc.get_or_insert_map(ROOT_SLIDES));
            }
            LiveItemKind::Sheet => {
                undo.expand_scope(doc, &doc.get_or_insert_array("rows"));
                undo.expand_scope(doc, &doc.get_or_insert_array("cols"));
                for name in ["cells", "headers", "aligns", super::sheet_formatting::ROOT] {
                    undo.expand_scope(doc, &doc.get_or_insert_map(name));
                }
            }
        }
        undo.include_origin(origin_of(turn_id));
        self.undo.insert(turn_id.to_string(), undo);
    }
}

/// Transaction origin of one assistant turn.
pub fn origin_of(turn_id: &str) -> String {
    format!("assistant:{turn_id}")
}

/// The content the assistant read, frozen: its text form and, for sheets, the row and
/// column ids that text was rendered from.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PinnedBase {
    /// Text form when the assistant read the item.
    pub text: String,
    /// Sheet row ids at that moment (empty for other kinds).
    pub rows: Vec<String>,
    /// Sheet column ids at that moment (empty for other kinds).
    pub cols: Vec<String>,
}

impl PinnedBase {
    /// Freezes the current content of `item`.
    ///
    /// # Errors
    /// [`LiveError::Empty`] when the item has no content yet.
    pub fn pin(item: &LiveItem) -> Result<Self, LiveError> {
        let (rows, cols) = item.sheet_ids().unwrap_or_default();
        Ok(Self {
            text: item.text_form()?,
            rows,
            cols,
        })
    }
}

/// A hunk a human touched (or a sheet cell that becomes a suggestion card).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HunkReport {
    /// Where: `line N`, `block N`, `{rowId}:{colId}`, `{slideId}/{elementId}`.
    pub anchor: String,
    /// What the assistant wanted there.
    pub assistant_value: String,
    /// What a human has there now.
    pub human_value: String,
}

/// Structured result of one change set.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AssistantOutcome {
    /// Hunks applied.
    pub applied_hunks: usize,
    /// Code, document and deck hunks a human changed (`Conflict::SameSpot`).
    pub same_spot: Vec<HunkReport>,
    /// Anchors of hunks whose target was deleted (`Conflict::TargetDeleted`); dropped.
    pub target_deleted: Vec<String>,
    /// Sheet cells a human changed: suggestion cards, the other cells were applied.
    pub suggestions: Vec<HunkReport>,
    /// More than about 20% of the text form changed elsewhere since the base.
    pub needs_recheck: bool,
    /// Sealed updates to send (one for code, documents and sheets).
    pub updates: Vec<SealedUpdate>,
}

/// Whether the change set ran.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AssistantResult {
    /// Another change set is pending on this item; the caller queues this one.
    Busy,
    /// The change set ran.
    Applied(AssistantOutcome),
}

/// Applies the assistant's `new_text` (computed from `base`) to the live `item`.
///
/// # Errors
/// [`LiveError::InvalidText`] for text the kind rejects, [`LiveError::Empty`].
pub fn apply_assistant_change(
    item: &mut LiveItem,
    base: &PinnedBase,
    new_text: &str,
    turn_id: &str,
) -> Result<AssistantResult, LiveError> {
    apply_change(item, base, new_text, turn_id, false)
}

pub(super) fn apply_change(
    item: &mut LiveItem,
    base: &PinnedBase,
    new_text: &str,
    turn_id: &str,
    restore: bool,
) -> Result<AssistantResult, LiveError> {
    if item.assistant_state().pending.is_some() {
        return Ok(AssistantResult::Busy);
    }
    let kind = item.kind();
    let mut outcome = if kind == LiveItemKind::Deck {
        apply_deck(item, base, new_text, turn_id)?
    } else {
        let origin = origin_of(turn_id);
        let (mut outcome, sealed) = item.assistant_edit(|doc, state| match kind {
            LiveItemKind::Code => apply_units(doc, state, kind, base, new_text, turn_id, &origin),
            LiveItemKind::Doc => apply_units(doc, state, kind, base, new_text, turn_id, &origin),
            _ => assistant_sheet::apply(doc, state, base, new_text, turn_id, &origin, restore),
        })?;
        outcome.updates.extend(sealed);
        outcome
    };
    if outcome.updates.is_empty() {
        item.assistant_state().undo.remove(turn_id);
    } else {
        item.assistant_state().pending = Some(turn_id.to_string());
    }
    outcome.updates.shrink_to_fit();
    Ok(AssistantResult::Applied(outcome))
}

/// Releases the item's assistant lock once the change set is acknowledged.
pub fn finish_assistant_change(item: &mut LiveItem, turn_id: &str) {
    let state = item.assistant_state();
    if state.pending.as_deref() == Some(turn_id) {
        state.pending = None;
    }
}

/// Undoes the whole assistant edit of `turn_id` in one step, keeping human changes.
/// Returns the sealed update to send, `None` when there was nothing to undo.
///
/// # Errors
/// Fails if the inverse update cannot be sealed.
pub fn undo_assistant(
    item: &mut LiveItem,
    turn_id: &str,
) -> Result<Option<SealedUpdate>, LiveError> {
    let (_, sealed) = item.assistant_edit(|_, state| {
        if let Some(undo) = state.undo.get_mut(turn_id) {
            undo.undo_blocking();
        }
        Ok(())
    })?;
    Ok(sealed)
}

/// One merge edit: live units `start..end` become `new[new_range]`.
struct Edit {
    start: usize,
    end: usize,
    new_range: (usize, usize),
}

#[derive(Default)]
struct UnitPlan {
    edits: Vec<Edit>,
    same_spot: Vec<(usize, HunkReport)>,
    deleted: Vec<usize>,
    recheck: bool,
}

/// Index pairs `(a, b)` of an LCS of `a` and `b`.
pub(super) fn matches(a: &[String], b: &[String]) -> Vec<(usize, usize)> {
    let pre = a.iter().zip(b).take_while(|(x, y)| x == y).count();
    let max_suf = a.len().min(b.len()) - pre;
    let suf = a
        .iter()
        .rev()
        .zip(b.iter().rev())
        .take(max_suf)
        .take_while(|(x, y)| x == y)
        .count();
    let mut out: Vec<(usize, usize)> = (0..pre).map(|i| (i, i)).collect();
    let (am, bm) = (&a[pre..a.len() - suf], &b[pre..b.len() - suf]);
    let (n, m) = (am.len(), bm.len());
    if n > 0 && m > 0 && n * m <= 4_000_000 {
        let mut dp = vec![0u32; (n + 1) * (m + 1)];
        let at = |i: usize, j: usize| i * (m + 1) + j;
        for i in (0..n).rev() {
            for j in (0..m).rev() {
                dp[at(i, j)] = if am[i] == bm[j] {
                    dp[at(i + 1, j + 1)] + 1
                } else {
                    dp[at(i + 1, j)].max(dp[at(i, j + 1)])
                };
            }
        }
        let (mut i, mut j) = (0, 0);
        while i < n && j < m {
            if am[i] == bm[j] {
                out.push((pre + i, pre + j));
                i += 1;
                j += 1;
            } else if dp[at(i + 1, j)] >= dp[at(i, j + 1)] {
                i += 1;
            } else {
                j += 1;
            }
        }
    }
    out.extend((0..suf).map(|k| (a.len() - suf + k, b.len() - suf + k)));
    out
}

/// Non-empty gaps `(a0, a1, b0, b1)` between consecutive matches.
pub(super) fn gaps(
    a_len: usize,
    b_len: usize,
    found: &[(usize, usize)],
) -> Vec<(usize, usize, usize, usize)> {
    let mut out = Vec::new();
    let (mut ai, mut bi) = (0, 0);
    for &(a, b) in found.iter().chain(std::iter::once(&(a_len, b_len))) {
        if a > ai || b > bi {
            out.push((ai, a, bi, b));
        }
        ai = a + 1;
        bi = b + 1;
    }
    out
}

fn plan_units(base: &[String], new: &[String], live: &[String], name: &str) -> UnitPlan {
    let mut map: Vec<Option<usize>> = vec![None; base.len()];
    let to_live = matches(base, live);
    for &(i, j) in &to_live {
        map[i] = Some(j);
    }
    let mut human_deleted = vec![false; base.len()];
    let mut human_changed = 0;
    for (a0, a1, l0, l1) in gaps(base.len(), live.len(), &to_live) {
        human_changed += (a1 - a0).max(l1 - l0);
        human_deleted[a0..a1].iter_mut().for_each(|d| *d = l0 == l1);
    }
    let mut plan = UnitPlan {
        recheck: human_changed * 100 > base.len().max(1) * RECHECK_PERCENT,
        ..UnitPlan::default()
    };
    for (a0, a1, b0, b1) in gaps(base.len(), new.len(), &matches(base, new)) {
        let conflict = |plan: &mut UnitPlan| {
            let lo = (0..a0).rev().find_map(|i| map[i]).map_or(0, |v| v + 1);
            let hi = (a1..base.len()).find_map(|i| map[i]).unwrap_or(live.len());
            plan.same_spot.push((
                a0,
                HunkReport {
                    anchor: format!("{name} {}", a0 + 1),
                    assistant_value: new[b0..b1].concat(),
                    human_value: live[lo..hi.max(lo)].concat(),
                },
            ));
        };
        let range = if a0 < a1 {
            let mapped = &map[a0..a1];
            if mapped.iter().all(Option::is_none) && human_deleted[a0..a1].iter().all(|d| *d) {
                plan.deleted.push(a0);
                continue;
            }
            let contiguous = mapped
                .iter()
                .enumerate()
                .all(|(k, v)| v.is_some() && *v == mapped[0].map(|s| s + k));
            contiguous.then(|| (mapped[0].unwrap_or(0), mapped[0].unwrap_or(0) + (a1 - a0)))
        } else {
            let at = if base.is_empty() {
                Some(0)
            } else if a0 > 0 && map[a0 - 1].is_some() {
                map[a0 - 1].map(|v| v + 1)
            } else if a0 < base.len() {
                map[a0]
            } else {
                None
            };
            at.map(|p| (p, p))
        };
        match range {
            Some((start, end)) => plan.edits.push(Edit {
                start,
                end,
                new_range: (b0, b1),
            }),
            None => conflict(&mut plan),
        }
    }
    plan.edits
        .sort_by(|x, y| (y.start, y.end).cmp(&(x.start, x.end)));
    plan
}

fn units_outcome(plan: &UnitPlan, name: &str) -> AssistantOutcome {
    AssistantOutcome {
        applied_hunks: plan.edits.len(),
        same_spot: plan.same_spot.iter().map(|(_, r)| r.clone()).collect(),
        target_deleted: plan
            .deleted
            .iter()
            .map(|i| format!("{name} {}", i + 1))
            .collect(),
        needs_recheck: plan.recheck,
        ..AssistantOutcome::default()
    }
}

fn utf16_offsets(units: &[String]) -> Vec<u32> {
    let mut at = 0;
    let mut out = vec![0];
    for unit in units {
        at += unit.encode_utf16().count() as u32;
        out.push(at);
    }
    out
}

fn apply_units(
    doc: &Doc,
    state: &mut AssistantState,
    kind: LiveItemKind,
    base: &PinnedBase,
    new_text: &str,
    turn_id: &str,
    origin: &str,
) -> Result<AssistantOutcome, LiveError> {
    if kind == LiveItemKind::Code {
        let lines = |t: &str| {
            t.split_inclusive('\n')
                .map(str::to_string)
                .collect::<Vec<_>>()
        };
        let live_text = super::code::to_text(doc);
        let (b, n, l) = (lines(&base.text), lines(new_text), lines(&live_text));
        let plan = plan_units(&b, &n, &l, "line");
        if !plan.edits.is_empty() {
            state.track(doc, kind, turn_id);
            let offsets = utf16_offsets(&l);
            let content = doc.get_or_insert_text("content");
            let mut txn = doc.transact_mut_with(origin);
            for edit in &plan.edits {
                let (from, to) = (offsets[edit.start], offsets[edit.end]);
                if to > from {
                    content.remove_range(&mut txn, from, to - from);
                }
                let insert = n[edit.new_range.0..edit.new_range.1].concat();
                if !insert.is_empty() {
                    content.insert(&mut txn, from, &insert);
                }
            }
        }
        return Ok(units_outcome(&plan, "line"));
    }
    let to_units = |blocks: &[Block]| blocks.iter().map(block_html).collect::<Vec<_>>();
    let base_blocks = parse_blocks(&base.text);
    let new_blocks = parse_blocks(new_text);
    let live_blocks = read_blocks(doc);
    let plan = plan_units(
        &to_units(&base_blocks),
        &to_units(&new_blocks),
        &to_units(&live_blocks),
        "block",
    );
    if !plan.edits.is_empty() {
        state.track(doc, kind, turn_id);
        let fragment = fragment_of(doc);
        let mut txn = doc.transact_mut_with(origin);
        for edit in &plan.edits {
            replace_blocks(
                &mut txn,
                &fragment,
                edit.start as u32,
                edit.end as u32,
                &new_blocks[edit.new_range.0..edit.new_range.1],
            );
        }
    }
    Ok(units_outcome(&plan, "block"))
}

/// Deck: text elements (by slide and element id) whose content the assistant changed.
fn apply_deck(
    item: &mut LiveItem,
    base: &PinnedBase,
    new_text: &str,
    turn_id: &str,
) -> Result<AssistantOutcome, LiveError> {
    let parse = |text: &str| parse_deck_markup(text).map_err(|e| LiveError::Deck(e.to_string()));
    let (base_deck, new_deck, live_deck) = (
        parse(&base.text)?,
        parse(new_text)?,
        parse(&item.text_form()?)?,
    );
    let content_of =
        |deck: &crate::client::shared_items::deck_markup::DeckModel, slide: &str, element: &str| {
            deck.slides
                .iter()
                .find(|s| s.id == slide)
                .and_then(|s| s.elements.iter().find(|e| e.id == element))
                .map(|e| e.content.clone())
        };
    let mut outcome = AssistantOutcome::default();
    let mut edits = Vec::new();
    let (mut total, mut human_changed) = (0usize, 0usize);
    for slide in &base_deck.slides {
        for element in &slide.elements {
            total += 1;
            let live = content_of(&live_deck, &slide.id, &element.id);
            if live.as_ref() != Some(&element.content) {
                human_changed += 1;
            }
            let anchor = format!("{}/{}", slide.id, element.id);
            let Some(wanted) = content_of(&new_deck, &slide.id, &element.id) else {
                continue;
            };
            let (ElementContent::RichText(markup), true) = (&wanted, wanted != element.content)
            else {
                continue;
            };
            match live {
                None => outcome.target_deleted.push(anchor),
                Some(now) if now == element.content => {
                    edits.push(DeckOperation::SetTextContent {
                        slide_id: slide.id.clone(),
                        element_id: element.id.clone(),
                        markup: markup.clone(),
                    });
                }
                Some(now) if now == wanted => {}
                Some(now) => outcome.same_spot.push(HunkReport {
                    anchor,
                    assistant_value: markup.clone(),
                    human_value: match now {
                        ElementContent::RichText(v)
                        | ElementContent::Plain(v)
                        | ElementContent::Label(v) => v,
                        _ => String::new(),
                    },
                }),
            }
        }
    }
    outcome.needs_recheck = human_changed * 100 > total.max(1) * RECHECK_PERCENT;
    if edits.is_empty() {
        return Ok(outcome);
    }

    // Validate every typed operation on a private replica before publishing the batch.
    // Applying its delta under one origin gives the requesting editor one undo step.
    let mut staged = item.fork()?;
    let before = staged.state_vector();
    outcome.applied_hunks = edits.len();
    for edit in edits {
        staged.apply_local_op(LocalOp::Deck(edit))?;
    }
    let delta = Update::decode_v1(&staged.encode_update_since(&before)?)
        .map_err(|e| LiveError::InvalidUpdate(e.to_string()))?;
    let (_, update) = item.assistant_edit(|doc, state| {
        state.track(doc, LiveItemKind::Deck, turn_id);
        doc.transact_mut_with(origin_of(turn_id))
            .apply_update(delta)
            .map_err(|e| LiveError::InvalidUpdate(e.to_string()))
    })?;
    outcome.updates.extend(update);
    Ok(outcome)
}
