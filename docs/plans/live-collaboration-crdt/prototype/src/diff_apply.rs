//! Assistant text diff → minimal CRDT change set ("fork at base, diff, merge").
//! The assistant edits the serialised text it was shown (version `base`). We rebuild a
//! private fork of the document at exactly that base state, apply the line/char
//! difference between base text and patched text to the fork as fine-grained ops, and
//! export only the new ops. Their ids anchor to base items, so merging them into the
//! live document keeps every concurrent member edit (no full replace).

use similar::{capture_diff_slices, Algorithm, DiffOp};
use yrs::updates::decoder::Decode;
use yrs::{GetString, ReadTxn, Text, Transact, Update, XmlFragment};

use crate::model::{block_text, doc_plain_lines, doc_root, insert_block, new_replica};

/// Errors of the diff-to-change-set path.
#[derive(Debug)]
pub enum DiffApplyError {
    /// The stored base state could not be decoded or applied.
    BadBase(String),
}

/// Builds the change set that turns document text `base` into `new_lines`.
///
/// `base_state` is the full Yjs v1 state of the document version the assistant read.
/// `fork_client_id` MUST be a fresh, never-used client id: the fork's clock for any
/// existing client stops at `base`, so reusing a live client id would mint duplicate
/// item ids and corrupt every replica.
///
/// # Errors
/// [`DiffApplyError::BadBase`] when `base_state` is not a valid update.
pub fn change_set_from_text(
    base_state: &[u8],
    new_lines: &[String],
    fork_client_id: u64,
) -> Result<Vec<u8>, DiffApplyError> {
    let fork = new_replica(fork_client_id);
    {
        let update =
            Update::decode_v1(base_state).map_err(|e| DiffApplyError::BadBase(e.to_string()))?;
        fork.transact_mut()
            .apply_update(update)
            .map_err(|e| DiffApplyError::BadBase(e.to_string()))?;
    }
    let base_sv = fork.transact().state_vector();
    let old_lines = doc_plain_lines(&fork.transact());

    let mut txn = fork.transact_mut();
    let root = doc_root(&mut txn);
    // Walk hunks from the end so earlier block indices stay valid while we edit.
    for (old, new) in hunks(&old_lines, new_lines).into_iter().rev() {
        let paired = old.len().min(new.len());
        // Extra old lines are deleted blocks (before inserting, which reuses the index).
        if old.len() > paired {
            root.remove_range(
                &mut txn,
                (old.start + paired) as u32,
                (old.len() - paired) as u32,
            );
        }
        // Extra new lines become new blocks after the paired ones (inserted in reverse
        // at one index, which yields the right order).
        for line in new_lines[new.start + paired..new.end].iter().rev() {
            insert_block(
                &mut txn,
                &root,
                (old.start + paired) as u32,
                "paragraph",
                line,
            );
        }
        // Paired lines: character-level edit inside the existing block, so a member
        // typing elsewhere in that same block keeps their characters.
        for p in (0..paired).rev() {
            let idx = (old.start + p) as u32;
            let Some(t) = block_text(&txn, &root, idx) else {
                continue;
            };
            let before = t.get_string(&txn);
            edit_text(&mut txn, &t, &before, &new_lines[new.start + p]);
        }
    }
    drop(txn);
    let change = fork.transact().encode_diff_v1(&base_sv);
    Ok(change)
}

/// Groups line ops into (old range, new range) hunks, merging adjacent delete/insert.
fn hunks(old: &[String], new: &[String]) -> Vec<(std::ops::Range<usize>, std::ops::Range<usize>)> {
    let mut out: Vec<(std::ops::Range<usize>, std::ops::Range<usize>)> = Vec::new();
    for op in capture_diff_slices(Algorithm::Myers, old, new) {
        let (o, n) = match op {
            DiffOp::Equal { .. } => continue,
            DiffOp::Delete {
                old_index,
                old_len,
                new_index,
            } => (old_index..old_index + old_len, new_index..new_index),
            DiffOp::Insert {
                old_index,
                new_index,
                new_len,
            } => (old_index..old_index, new_index..new_index + new_len),
            DiffOp::Replace {
                old_index,
                old_len,
                new_index,
                new_len,
            } => (
                old_index..old_index + old_len,
                new_index..new_index + new_len,
            ),
        };
        match out.last_mut() {
            Some((lo, ln)) if lo.end == o.start && ln.end == n.start => {
                lo.end = o.end;
                ln.end = n.end;
            }
            _ => out.push((o, n)),
        }
    }
    out
}

/// Applies a char-level diff `before → after` to a text node (UTF-16 offsets).
fn edit_text(txn: &mut yrs::TransactionMut, t: &yrs::XmlTextRef, before: &str, after: &str) {
    let a: Vec<char> = before.chars().collect();
    let b: Vec<char> = after.chars().collect();
    let u16_at =
        |chars: &[char], i: usize| -> u32 { chars[..i].iter().map(|c| c.len_utf16() as u32).sum() };
    for op in capture_diff_slices(Algorithm::Myers, &a, &b)
        .into_iter()
        .rev()
    {
        match op {
            DiffOp::Equal { .. } => {}
            DiffOp::Delete {
                old_index, old_len, ..
            } => {
                let s = u16_at(&a, old_index);
                t.remove_range(txn, s, u16_at(&a, old_index + old_len) - s);
            }
            DiffOp::Insert {
                old_index,
                new_index,
                new_len,
            } => {
                let s: String = b[new_index..new_index + new_len].iter().collect();
                t.insert(txn, u16_at(&a, old_index), &s);
            }
            DiffOp::Replace {
                old_index,
                old_len,
                new_index,
                new_len,
            } => {
                let s0 = u16_at(&a, old_index);
                t.remove_range(txn, s0, u16_at(&a, old_index + old_len) - s0);
                let s: String = b[new_index..new_index + new_len].iter().collect();
                t.insert(txn, s0, &s);
            }
        }
    }
}
