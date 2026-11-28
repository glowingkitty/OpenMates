//! Sheet change sets: per-cell diff by stable row and column ids. A cell a human changed
//! since the base becomes a suggestion, the other cells are applied.

use super::assistant::{AssistantOutcome, AssistantState, HunkReport, PinnedBase, gaps, matches};
use super::engine::LiveItem;
use super::sheet::{self, SheetOp, is_formula, split_row};
use super::sheet_formatting;
use super::{LiveError, LiveItemKind};
use serde_json::{Map, Value};
use std::collections::HashMap;
use yrs::{Doc, Transact};

struct Table {
    headers: Vec<String>,
    rows: Vec<Vec<String>>,
    formatting: Option<Map<String, Value>>,
}

fn parse_table(text: &str) -> Result<Table, LiveError> {
    let (text, formatting) = sheet_formatting::split(text)?;
    let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    if lines.len() < 2 {
        return Err(LiveError::InvalidText(
            "a sheet needs a header and a separator row",
        ));
    }
    Ok(Table {
        headers: split_row(lines[0]),
        rows: lines[2..].iter().map(|l| split_row(l)).collect(),
        formatting,
    })
}

fn cell(table: &Table, r: usize, c: usize) -> String {
    table
        .rows
        .get(r)
        .and_then(|row| row.get(c))
        .cloned()
        .unwrap_or_default()
}

pub(super) fn apply(
    doc: &Doc,
    state: &mut AssistantState,
    base: &PinnedBase,
    new_text: &str,
    turn_id: &str,
    origin: &str,
    restore: bool,
) -> Result<AssistantOutcome, LiveError> {
    let (live_rows, live_cols, live_cells) = sheet::grid(doc);
    let live_table = parse_table(&sheet::to_text(doc)?)?;
    let live_header: HashMap<&str, &str> = live_cols
        .iter()
        .zip(&live_table.headers)
        .map(|(id, h)| (id.as_str(), h.as_str()))
        .collect();
    let (base_t, new_t) = (parse_table(&base.text)?, parse_table(new_text)?);
    let base_format =
        sheet_formatting::snapshot_entries(base_t.formatting.as_ref(), &base.rows, &base.cols)?;
    // Validate coordinates and ranges before changing any content. Appended
    // positions will receive their real stable identities below.
    let provisional_ids = |base: &[String], len: usize, kind: &str| {
        (0..len)
            .map(|i| {
                base.get(i)
                    .cloned()
                    .unwrap_or_else(|| format!("format-{kind}-{i}"))
            })
            .collect::<Vec<_>>()
    };
    let target_rows = provisional_ids(&base.rows, new_t.rows.len(), "row");
    let target_cols = provisional_ids(&base.cols, new_t.headers.len(), "column");
    let provisional_format =
        sheet_formatting::snapshot_entries(new_t.formatting.as_ref(), &target_rows, &target_cols)?;
    let structure_changed = live_rows != base.rows || live_cols != base.cols;
    let mut out = AssistantOutcome::default();
    let mut ops: Vec<SheetOp> = Vec::new();
    let live_value = |r: &str, c: &str| {
        live_cells
            .get(&format!("{r}:{c}"))
            .cloned()
            .unwrap_or_default()
    };

    let (mut total, mut human_changed) = (0usize, 0usize);
    for (r, row_id) in base.rows.iter().enumerate() {
        for (c, col_id) in base.cols.iter().enumerate() {
            total += 1;
            let present = live_rows.contains(row_id) && live_cols.contains(col_id);
            if !present || live_value(row_id, col_id) != cell(&base_t, r, c) {
                human_changed += 1;
            }
        }
    }
    out.needs_recheck = human_changed * 100 > total.max(1) * 20;

    // Header and cell hunks on positions that exist in both base and new.
    let keep_rows = base.rows.len().min(new_t.rows.len());
    let keep_cols = base.cols.len().min(new_t.headers.len());
    for (c, col_id) in base.cols.iter().enumerate().take(keep_cols) {
        let (was, wanted) = (
            base_t.headers.get(c).cloned().unwrap_or_default(),
            new_t.headers[c].clone(),
        );
        if was == wanted {
            continue;
        }
        let anchor = format!("header:{col_id}");
        match live_header.get(col_id.as_str()) {
            None => out.target_deleted.push(anchor),
            Some(now) if *now == was => ops.push(SheetOp::SetHeader {
                col_id: col_id.clone(),
                value: wanted,
            }),
            Some(now) if *now == wanted => {}
            Some(now) => out.suggestions.push(HunkReport {
                anchor,
                assistant_value: wanted,
                human_value: (*now).to_string(),
            }),
        }
    }
    for (r, row_id) in base.rows.iter().enumerate().take(keep_rows) {
        for (c, col_id) in base.cols.iter().enumerate().take(keep_cols) {
            let (was, wanted) = (cell(&base_t, r, c), cell(&new_t, r, c));
            if was == wanted {
                continue;
            }
            let anchor = format!("{row_id}:{col_id}");
            if !live_rows.contains(row_id) || !live_cols.contains(col_id) {
                out.target_deleted.push(anchor);
                continue;
            }
            let now = live_value(row_id, col_id);
            if now == wanted {
                continue;
            }
            if now == was && !(is_formula(&wanted) && structure_changed) {
                ops.push(SheetOp::SetCell {
                    row_id: row_id.clone(),
                    col_id: col_id.clone(),
                    value: wanted,
                });
            } else {
                out.suggestions.push(HunkReport {
                    anchor,
                    assistant_value: wanted,
                    human_value: now,
                });
            }
        }
    }

    // Deleted rows and columns: only when no human touched them.
    let mut deletes: Vec<SheetOp> = Vec::new();
    for (r, row_id) in base.rows.iter().enumerate().skip(new_t.rows.len()) {
        if !live_rows.contains(row_id) {
            continue;
        }
        let untouched = base.cols.iter().enumerate().all(|(c, col_id)| {
            !live_cols.contains(col_id) || live_value(row_id, col_id) == cell(&base_t, r, c)
        });
        if untouched {
            deletes.push(SheetOp::DeleteRow {
                row_id: row_id.clone(),
            });
        } else {
            out.suggestions.push(HunkReport {
                anchor: format!("row:{row_id}"),
                assistant_value: String::new(),
                human_value: base
                    .cols
                    .iter()
                    .map(|c| live_value(row_id, c))
                    .collect::<Vec<_>>()
                    .join(" | "),
            });
        }
    }
    for (c, col_id) in base.cols.iter().enumerate().skip(new_t.headers.len()) {
        if !live_cols.contains(col_id) {
            continue;
        }
        let untouched = base.rows.iter().enumerate().all(|(r, row_id)| {
            !live_rows.contains(row_id) || live_value(row_id, col_id) == cell(&base_t, r, c)
        });
        if untouched {
            deletes.push(SheetOp::DeleteCol {
                col_id: col_id.clone(),
            });
        } else {
            out.suggestions.push(HunkReport {
                anchor: format!("col:{col_id}"),
                assistant_value: String::new(),
                human_value: base
                    .rows
                    .iter()
                    .map(|r| live_value(r, col_id))
                    .collect::<Vec<_>>()
                    .join(" | "),
            });
        }
    }

    let appended_cols = new_t.headers.len().saturating_sub(base.cols.len());
    let appended_rows = new_t.rows.len().saturating_sub(base.rows.len());
    out.applied_hunks = ops.len() + deletes.len() + appended_cols + appended_rows;
    let format_changed =
        provisional_format != base_format && (restore || new_t.formatting.is_some());
    if out.applied_hunks == 0 && !format_changed {
        return Ok(out);
    }

    state.track(doc, LiveItemKind::Sheet, turn_id);
    let run = |op: &SheetOp| sheet::apply_op_with_origin(doc, op, Some(origin));
    // Appended structure first, so formulas in the new text resolve against the final grid.
    let mut col_ids: Vec<Option<String>> = base
        .cols
        .iter()
        .map(|id| live_cols.contains(id).then(|| id.clone()))
        .collect();
    let mut last_col = live_cols.last().cloned();
    for c in base.cols.len()..new_t.headers.len() {
        let id = run(&SheetOp::InsertCol {
            after_col_id: last_col.clone(),
        })?;
        if let Some(id) = &id {
            run(&SheetOp::SetHeader {
                col_id: id.clone(),
                value: new_t.headers[c].clone(),
            })?;
        }
        last_col = id.clone();
        col_ids.push(id);
    }
    let mut row_ids: Vec<Option<String>> = base
        .rows
        .iter()
        .map(|id| live_rows.contains(id).then(|| id.clone()))
        .collect();
    let mut last_row = live_rows.last().cloned();
    for _ in base.rows.len()..new_t.rows.len() {
        let id = run(&SheetOp::InsertRow {
            after_row_id: last_row.clone(),
        })?;
        last_row = id.clone();
        row_ids.push(id);
    }
    for op in &ops {
        run(op)?;
    }
    // Cells in appended rows or columns.
    for (r, row_id) in row_ids.iter().enumerate().take(new_t.rows.len()) {
        for (c, col_id) in col_ids.iter().enumerate().take(new_t.headers.len()) {
            let appended = r >= base.rows.len() || c >= base.cols.len();
            let (Some(row_id), Some(col_id)) = (row_id, col_id) else {
                continue;
            };
            let value = cell(&new_t, r, c);
            if appended && !value.is_empty() {
                run(&SheetOp::SetCell {
                    row_id: row_id.clone(),
                    col_id: col_id.clone(),
                    value,
                })?;
            }
        }
    }
    for op in &deletes {
        run(op)?;
    }
    if format_changed {
        let actual_ids = |provisional: Vec<String>, actual: Vec<Option<String>>| {
            provisional
                .into_iter()
                .zip(actual)
                .map(|(old, new)| new.unwrap_or(old))
                .collect::<Vec<_>>()
        };
        let desired = sheet_formatting::snapshot_entries(
            new_t.formatting.as_ref(),
            &actual_ids(target_rows, row_ids),
            &actual_ids(target_cols, col_ids),
        )?;
        let (rows, cols, _) = sheet::grid(doc);
        let root = sheet_formatting::root(doc);
        let mut txn = doc.transact_mut_with(origin);
        let (applied, conflicts) = sheet_formatting::merge_snapshot(
            &mut txn,
            &root,
            &rows,
            &cols,
            &base_format,
            &desired,
            restore,
        );
        out.applied_hunks += applied;
        out.same_spot.extend(conflicts);
    }
    Ok(out)
}

/// Maps each base index to the live index it matches: exact LCS first, then gaps of equal
/// size pair up by position (a human edited a cell of that row or column).
fn align(base: &[String], live: &[String]) -> Vec<Option<usize>> {
    let found = matches(base, live);
    let mut map = vec![None; base.len()];
    for &(b, l) in &found {
        map[b] = Some(l);
    }
    for (b0, b1, l0, l1) in gaps(base.len(), live.len(), &found) {
        if b1 - b0 == l1 - l0 {
            for k in 0..(b1 - b0) {
                map[b0 + k] = Some(l0 + k);
            }
        }
    }
    map
}

/// Row and column ids of the item as they were when the assistant read `base_text`.
///
/// Only the text of the base version is known, so ids are reconstructed by matching the
/// base table to the live one: identical rows (columns by header) match exactly, equal-size
/// gaps pair by position, anything else gets a synthetic id that does not exist live (a
/// human deleted it, so its cells count as changed and the assistant's edit there drops).
///
/// # Errors
/// [`LiveError::InvalidText`] for a base that is not a table, [`LiveError::WrongKind`].
pub(super) fn reconstruct_base(item: &LiveItem, base_text: &str) -> Result<PinnedBase, LiveError> {
    let (live_rows, live_cols) = item.sheet_ids()?;
    let live = parse_table(&item.text_form()?)?;
    let base = parse_table(base_text)?;
    let col_map = align(&base.headers, &live.headers);
    let join = |rows: &[Vec<String>]| rows.iter().map(|r| r.join("\u{1f}")).collect::<Vec<_>>();
    let row_map = align(&join(&base.rows), &join(&live.rows));
    let pick = |map: &[Option<usize>], ids: &[String], tag: &str| {
        map.iter()
            .enumerate()
            .map(|(i, m)| {
                m.and_then(|l| ids.get(l).cloned())
                    .unwrap_or_else(|| format!("base-{tag}-{i}"))
            })
            .collect()
    };
    Ok(PinnedBase {
        text: base_text.to_string(),
        rows: pick(&row_map, &live_rows, "row"),
        cols: pick(&col_map, &live_cols, "col"),
    })
}
