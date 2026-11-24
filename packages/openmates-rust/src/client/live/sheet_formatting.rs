//! Stable-address formatting for the encrypted live sheet replica.
//! The versioned Markdown footer projects these properties to A1 addresses,
//! with the heading at row 1 (feature.rich-sheets@1).

use super::LiveError;
use super::sheet_formula::column_letters;
use serde::Deserialize;
use serde_json::{Map as JsonMap, Value, json};
use std::collections::BTreeMap;
use std::sync::Arc;
use yrs::undo::{Options as UndoOptions, UndoManager};
use yrs::{Any, Doc, Map, MapRef, Out, ReadTxn, TransactionMut};

pub(super) const ROOT: &str = "sheet_formatting";
pub(super) const LOCAL_ORIGIN: &str = "sheet-formatting-local";
const HEADER: &str = "header";
const MARKER: &str = "<!-- openmates-sheet-format-v1";
const PREFIX: &str = "<!-- openmates-sheet-format-v1: ";
const SUFFIX: &str = " -->";
const MAX_FORMATTING_BYTES: usize = 256 * 1024;

pub(super) type Properties = BTreeMap<String, Value>;
type Result<T> = std::result::Result<T, LiveError>;

fn invalid() -> LiveError {
    LiveError::InvalidText("invalid sheet formatting")
}

/// Stable live cell location. A null row denotes the heading.
#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SheetFormatCell {
    /// Data-row identifier, or the heading when null.
    pub row_id: Option<String>,
    /// Column identifier.
    pub col_id: String,
}

impl SheetFormatCell {
    fn row(&self) -> &str {
        self.row_id.as_deref().unwrap_or(HEADER)
    }
}

/// One formatting command. Missing style keys stay as they are and null values clear them.
#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "camelCase",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum SheetFormatChange {
    /// Change only the named properties of one cell.
    CellStyle {
        /// Stable target.
        cell: SheetFormatCell,
        /// Schema property names and values.
        patch: JsonMap<String, Value>,
    },
    /// Set or clear a column width in CSS pixels.
    ColumnWidth {
        /// Stable column identifier.
        col_id: String,
        /// Width, or null to clear.
        value: Option<u16>,
    },
    /// Set or clear a row height in CSS pixels.
    RowHeight {
        /// Stable row identifier, or the heading when null.
        row_id: Option<String>,
        /// Height, or null to clear.
        value: Option<u16>,
    },
    /// Set a merge starting at a stable cell or remove the merge that starts there.
    Merge {
        /// Top-left corner.
        start: SheetFormatCell,
        /// Bottom-right corner, or null to clear.
        end: Option<SheetFormatCell>,
    },
    /// Set or clear the number of frozen rows, including the heading.
    FrozenRows {
        /// Row count, or null to clear.
        value: Option<u16>,
    },
    /// Set or clear the number of frozen columns.
    FrozenColumns {
        /// Column count, or null to clear.
        value: Option<u16>,
    },
}

struct Grid<'a> {
    rows: &'a [String],
    cols: &'a [String],
}

impl Grid<'_> {
    fn row(&self, i: usize) -> Option<&str> {
        if i == 0 {
            Some(HEADER)
        } else {
            self.rows.get(i - 1).map(String::as_str)
        }
    }

    fn row_index(&self, id: &str) -> Option<usize> {
        if id == HEADER {
            Some(0)
        } else {
            self.rows.iter().position(|row| row == id).map(|i| i + 1)
        }
    }

    fn col_index(&self, id: &str) -> Option<usize> {
        self.cols.iter().position(|col| col == id)
    }

    fn indices(&self, row: &str, col: &str) -> Option<(usize, usize)> {
        Some((self.row_index(row)?, self.col_index(col)?))
    }

    fn parse_cell(&self, address: &str) -> Result<SheetFormatCell> {
        let i = address
            .find(|c: char| c.is_ascii_digit())
            .ok_or_else(invalid)?;
        let (col, row) = address.split_at(i);
        Ok(SheetFormatCell {
            row_id: self
                .row(row_index(row)?)
                .ok_or_else(invalid)
                .map(|id| (id != HEADER).then(|| id.to_owned()))?,
            col_id: self.cols.get(col_index(col)?).ok_or_else(invalid)?.clone(),
        })
    }
}

fn col_index(col: &str) -> Result<usize> {
    if !(1..=3).contains(&col.len()) || !col.bytes().all(|c| c.is_ascii_uppercase()) {
        return Err(invalid());
    }
    Ok(col
        .bytes()
        .fold(0, |n, c| n * 26 + usize::from(c - b'A' + 1))
        - 1)
}

fn row_index(row: &str) -> Result<usize> {
    if row.is_empty()
        || row.len() > 4
        || row.starts_with('0')
        || !row.bytes().all(|c| c.is_ascii_digit())
    {
        return Err(invalid());
    }
    row.parse::<usize>().map(|n| n - 1).map_err(|_| invalid())
}

fn integer(value: &Value, min: u64, max: u64) -> bool {
    value.as_u64().is_some_and(|n| (min..=max).contains(&n))
}

fn one_of(value: &Value, allowed: &[&str]) -> bool {
    value.as_str().is_some_and(|s| allowed.contains(&s))
}

fn color(value: &Value) -> bool {
    value
        .as_str()
        .and_then(|s| s.strip_prefix('#'))
        .is_some_and(|s| s.len() == 6 && s.bytes().all(|c| c.is_ascii_hexdigit()))
}

fn number_format(value: &Value) -> bool {
    let Some(format) = value.as_object() else {
        return false;
    };
    let decimals = format.get("decimals").is_none_or(|v| integer(v, 0, 10));
    match format.get("kind").and_then(Value::as_str) {
        Some("number" | "percent") => {
            decimals
                && format
                    .keys()
                    .all(|k| matches!(k.as_str(), "kind" | "decimals"))
        }
        Some("currency") => {
            decimals
                && format
                    .keys()
                    .all(|k| matches!(k.as_str(), "kind" | "decimals" | "currency"))
                && format
                    .get("currency")
                    .and_then(Value::as_str)
                    .is_some_and(|s| s.len() == 3 && s.bytes().all(|c| c.is_ascii_uppercase()))
        }
        Some("date") => {
            format.len() == 2
                && format.get("pattern").is_some_and(|v| {
                    one_of(
                        v,
                        &["yyyy-mm-dd", "mm/dd/yyyy", "dd/mm/yyyy", "mmm d, yyyy"],
                    )
                })
        }
        _ => false,
    }
}

fn style_valid(key: &str, value: &Value) -> bool {
    match key {
        "backgroundColor" | "textColor" => color(value),
        "fontFamily" => value.as_str().is_some_and(|s| {
            (1..=64).contains(&s.len())
                && s.as_bytes()[0].is_ascii_alphanumeric()
                && s.bytes()
                    .all(|c| c.is_ascii_alphanumeric() || c == b' ' || c == b'-')
        }),
        "fontSize" => integer(value, 8, 96),
        "bold" | "italic" | "underline" | "strikethrough" | "wrap" => value.is_boolean(),
        "horizontalAlign" => one_of(value, &["left", "center", "right"]),
        "verticalAlign" => one_of(value, &["top", "middle", "bottom"]),
        "numberFormat" => number_format(value),
        "borders" => value.as_object().is_some_and(|borders| {
            borders.iter().all(|(side, border)| {
                matches!(side.as_str(), "top" | "right" | "bottom" | "left")
                    && border.as_object().is_some_and(|b| {
                        b.len() == 2
                            && b.get("color").is_some_and(color)
                            && b.get("style").is_some_and(|v| {
                                one_of(
                                    v,
                                    &["thin", "medium", "thick", "dashed", "dotted", "double"],
                                )
                            })
                    })
            })
        }),
        _ => false,
    }
}

fn style_keys() -> &'static [&'static str] {
    &[
        "backgroundColor",
        "textColor",
        "fontFamily",
        "fontSize",
        "bold",
        "italic",
        "underline",
        "strikethrough",
        "horizontalAlign",
        "verticalAlign",
        "wrap",
        "numberFormat",
        "borders",
    ]
}

fn update_style(
    entries: &mut Properties,
    cell: &SheetFormatCell,
    patch: &JsonMap<String, Value>,
    allow_clear: bool,
) -> Result<()> {
    for (name, value) in patch {
        let key = format!("cell:{}:{}:{name}", cell.row(), cell.col_id);
        if allow_clear && value.is_null() && style_keys().contains(&name.as_str()) {
            entries.remove(&key);
        } else if style_valid(name, value) {
            entries.insert(key, value.clone());
        } else {
            return Err(invalid());
        }
    }
    Ok(())
}

fn sized_set(
    entries: &mut Properties,
    key: String,
    value: Option<u16>,
    min: u16,
    max: u16,
) -> Result<()> {
    match value {
        Some(n) if (min..=max).contains(&n) => {
            entries.insert(key, json!(n));
        }
        Some(_) => return Err(invalid()),
        None => {
            entries.remove(&key);
        }
    }
    Ok(())
}

type Rect = (usize, usize, usize, usize);

fn rectangle(grid: &Grid<'_>, row: &str, col: &str, end: &Value) -> Option<Rect> {
    let [r, c] = end.as_array()?.as_slice() else {
        return None;
    };
    let (top, left) = grid.indices(row, col)?;
    let (bottom, right) = grid.indices(r.as_str()?, c.as_str()?)?;
    (top <= bottom && left <= right && (top, left) != (bottom, right))
        .then_some((top, left, bottom, right))
}

fn overlaps(a: Rect, b: Rect) -> bool {
    a.0 <= b.2 && a.2 >= b.0 && a.1 <= b.3 && a.3 >= b.1
}

fn update(entries: &mut Properties, grid: &Grid<'_>, change: &SheetFormatChange) -> Result<()> {
    match change {
        SheetFormatChange::CellStyle { cell, patch } => {
            grid.indices(cell.row(), &cell.col_id).ok_or_else(invalid)?;
            update_style(entries, cell, patch, true)
        }
        SheetFormatChange::ColumnWidth { col_id, value } => {
            grid.col_index(col_id).ok_or_else(invalid)?;
            sized_set(entries, format!("width:{col_id}"), *value, 24, 1200)
        }
        SheetFormatChange::RowHeight { row_id, value } => {
            let row = row_id.as_deref().unwrap_or(HEADER);
            grid.row_index(row).ok_or_else(invalid)?;
            sized_set(entries, format!("height:{row}"), *value, 16, 600)
        }
        SheetFormatChange::Merge { start, end } => {
            let row = start.row();
            let col = &start.col_id;
            grid.indices(row, col).ok_or_else(invalid)?;
            let key = format!("merge:{row}:{col}");
            if let Some(end) = end {
                let value = json!([end.row(), end.col_id]);
                rectangle(grid, row, col, &value).ok_or_else(invalid)?;
                entries.insert(key, value);
            } else {
                entries.remove(&key);
            }
            Ok(())
        }
        SheetFormatChange::FrozenRows { value } => sized_set(
            entries,
            "frozenRows".into(),
            *value,
            0,
            grid.rows.len().saturating_add(1).min(1000) as u16,
        ),
        SheetFormatChange::FrozenColumns { value } => sized_set(
            entries,
            "frozenColumns".into(),
            *value,
            0,
            grid.cols.len().min(256) as u16,
        ),
    }
}

fn merges_valid(entries: &Properties, grid: &Grid<'_>) -> bool {
    let mut ranges = Vec::new();
    for (key, value) in entries {
        let Some((row, col)) = key
            .strip_prefix("merge:")
            .and_then(|key| key.split_once(':'))
        else {
            continue;
        };
        // A concurrently deleted endpoint leaves a merge with no visible cells.
        let Some(range) = rectangle(grid, row, col, value) else {
            continue;
        };
        if ranges.len() == 256 || ranges.iter().any(|other| overlaps(range, *other)) {
            return false;
        }
        ranges.push(range);
    }
    true
}

fn formatting_fits(entries: &Properties, grid: &Grid<'_>) -> bool {
    let value = Value::Object(projected(entries, grid.rows, grid.cols));
    [
        ("cells", 10_000),
        ("columnWidths", 256),
        ("rowHeights", 1000),
    ]
    .into_iter()
    .all(|(key, limit)| value[key].as_object().is_none_or(|map| map.len() <= limit))
        && value.to_string().len() <= MAX_FORMATTING_BYTES
}

fn target_exists(grid: &Grid<'_>, key: &str, value: &Value) -> bool {
    let parts: Vec<&str> = key.split(':').collect();
    match parts.as_slice() {
        ["cell", row, col, _] => grid.indices(row, col).is_some(),
        ["width", col] => grid.col_index(col).is_some(),
        ["height", row] => grid.row_index(row).is_some(),
        ["merge", row, col] => rectangle(grid, row, col, value).is_some(),
        ["frozenRows" | "frozenColumns"] => true,
        _ => false,
    }
}

/// Merges a validated snapshot against the pinned base, preserving human values.
pub(super) fn merge_snapshot(
    txn: &mut TransactionMut,
    root: &MapRef,
    rows: &[String],
    cols: &[String],
    base: &Properties,
    desired: &Properties,
    restore: bool,
) -> (usize, Vec<super::assistant::HunkReport>) {
    use super::assistant::HunkReport;
    let grid = Grid { rows, cols };
    let current = read(txn, root);
    let mut next = current.clone();
    let mut conflicts = Vec::new();
    let keys: std::collections::BTreeSet<_> = if restore {
        base.keys().chain(desired.keys()).collect()
    } else {
        desired.keys().collect()
    };
    let mut applied = 0;
    for key in keys {
        let was = base.get(key);
        let wanted = desired.get(key);
        let now = current.get(key);
        if was == wanted || now == wanted || wanted.is_some_and(|v| !target_exists(&grid, key, v)) {
            continue;
        }
        if now != was {
            conflicts.push(HunkReport {
                anchor: key.clone(),
                assistant_value: wanted.map_or_else(String::new, Value::to_string),
                human_value: now.map_or_else(String::new, Value::to_string),
            });
            continue;
        }
        if let Some(value) = wanted {
            next.insert(key.clone(), value.clone());
        } else {
            next.remove(key);
        }
        applied += 1;
    }
    if !merges_valid(&next, &grid) || !formatting_fits(&next, &grid) {
        conflicts.push(HunkReport {
            anchor: "sheet formatting".into(),
            assistant_value: "formatting cannot be combined with the current sheet".into(),
            human_value: "current formatting".into(),
        });
        return (0, conflicts);
    }
    write(txn, root, &current, &next);
    (applied, conflicts)
}

/// Peel the optional versioned footer off the Markdown that feeds the grid parser.
pub(super) fn split(text: &str) -> Result<(&str, Option<JsonMap<String, Value>>)> {
    let last = text.trim_end_matches('\n');
    let Some((table, footer)) = last.rsplit_once('\n') else {
        if last.starts_with(MARKER) {
            return Err(invalid());
        }
        return Ok((text, None));
    };
    if table.lines().any(|line| line.starts_with(MARKER)) {
        return Err(invalid());
    }
    if !footer.starts_with(MARKER) {
        return Ok((text, None));
    }
    let footer = footer.strip_prefix(PREFIX).ok_or_else(invalid)?;
    let json = footer.strip_suffix(SUFFIX).ok_or_else(invalid)?;
    if json.len() > MAX_FORMATTING_BYTES {
        return Err(invalid());
    }
    Ok((
        table,
        Some(serde_json::from_str(json).map_err(|_| invalid())?),
    ))
}

pub(super) fn snapshot_entries(
    formatting: Option<&JsonMap<String, Value>>,
    rows: &[String],
    cols: &[String],
) -> Result<Properties> {
    let grid = Grid { rows, cols };
    let mut entries = Properties::new();
    let Some(formatting) = formatting else {
        return Ok(entries);
    };
    for (group, value) in formatting {
        match group.as_str() {
            "cells" => {
                let cells = value
                    .as_object()
                    .filter(|m| m.len() <= 10_000)
                    .ok_or_else(invalid)?;
                for (address, style) in cells {
                    update_style(
                        &mut entries,
                        &grid.parse_cell(address)?,
                        style.as_object().ok_or_else(invalid)?,
                        false,
                    )?;
                }
            }
            "columnWidths" | "rowHeights" => {
                let widths = group == "columnWidths";
                let limit = if widths { 256 } else { 1000 };
                let sizes = value
                    .as_object()
                    .filter(|m| m.len() <= limit)
                    .ok_or_else(invalid)?;
                for (address, size) in sizes {
                    let key = if widths {
                        if !integer(size, 24, 1200) {
                            return Err(invalid());
                        }
                        format!(
                            "width:{}",
                            cols.get(col_index(address)?).ok_or_else(invalid)?
                        )
                    } else {
                        if !integer(size, 16, 600) {
                            return Err(invalid());
                        }
                        format!(
                            "height:{}",
                            grid.row(row_index(address)?).ok_or_else(invalid)?
                        )
                    };
                    entries.insert(key, size.clone());
                }
            }
            "merges" => {
                let merges = value
                    .as_array()
                    .filter(|m| m.len() <= 256)
                    .ok_or_else(invalid)?;
                for merge in merges {
                    if !merge.as_object().is_some_and(|m| m.len() == 2) {
                        return Err(invalid());
                    }
                    let start = grid.parse_cell(merge["start"].as_str().ok_or_else(invalid)?)?;
                    let end = grid.parse_cell(merge["end"].as_str().ok_or_else(invalid)?)?;
                    let key = format!("merge:{}:{}", start.row(), start.col_id);
                    if entries.contains_key(&key) {
                        return Err(invalid());
                    }
                    update(
                        &mut entries,
                        &grid,
                        &SheetFormatChange::Merge {
                            start,
                            end: Some(end),
                        },
                    )?;
                }
            }
            "frozenRows" | "frozenColumns" => {
                let max = if group == "frozenRows" {
                    (rows.len() + 1).min(1000)
                } else {
                    cols.len().min(256)
                };
                if !integer(value, 0, max as u64) {
                    return Err(invalid());
                }
                entries.insert(group.clone(), value.clone());
            }
            _ => return Err(invalid()),
        }
    }
    if !merges_valid(&entries, &grid) {
        return Err(invalid());
    }
    Ok(entries)
}

pub(super) fn root(doc: &Doc) -> MapRef {
    doc.get_or_insert_map(ROOT)
}

pub(super) fn undo_manager(doc: &Doc) -> UndoManager<()> {
    let mut undo = UndoManager::with_options(UndoOptions {
        capture_timeout_millis: 500,
        tracked_origins: Default::default(),
        capture_transaction: None,
        timestamp: Arc::new(|| 0),
        init_undo_stack: Vec::new(),
        init_redo_stack: Vec::new(),
    });
    undo.expand_scope(doc, &root(doc));
    undo.include_origin(LOCAL_ORIGIN);
    undo
}

pub(super) fn read<T: ReadTxn>(txn: &T, root: &MapRef) -> Properties {
    root.iter(txn)
        .filter_map(|(key, value)| {
            let Out::Any(Any::String(value)) = value else {
                return None;
            };
            serde_json::from_str(&value)
                .ok()
                .map(|v| (key.to_string(), v))
        })
        .collect()
}

pub(super) fn write(
    txn: &mut TransactionMut,
    root: &MapRef,
    before: &Properties,
    after: &Properties,
) {
    for key in before.keys().filter(|key| !after.contains_key(*key)) {
        root.remove(txn, key);
    }
    for (key, value) in after
        .iter()
        .filter(|(key, value)| before.get(*key) != Some(*value))
    {
        root.insert(txn, key.clone(), value.to_string());
    }
}

pub(super) fn apply(
    txn: &mut TransactionMut,
    root: &MapRef,
    rows: &[String],
    cols: &[String],
    changes: &[SheetFormatChange],
) -> Result<()> {
    let grid = Grid { rows, cols };
    if changes.len() > 10_000 {
        return Err(invalid());
    }
    let before = read(txn, root);
    let mut after = before.clone();
    for change in changes {
        update(&mut after, &grid, change)?;
    }
    if !merges_valid(&after, &grid) || !formatting_fits(&after, &grid) {
        return Err(invalid());
    }
    write(txn, root, &before, &after);
    Ok(())
}

pub(super) fn projected(
    entries: &Properties,
    rows: &[String],
    cols: &[String],
) -> JsonMap<String, Value> {
    let grid = Grid { rows, cols };
    let mut output = JsonMap::new();
    let mut cells: BTreeMap<String, JsonMap<String, Value>> = BTreeMap::new();
    let (mut widths, mut heights) = (JsonMap::new(), JsonMap::new());
    let (mut merges, mut ranges) = (Vec::new(), Vec::new());
    let address = |r: usize, c: usize| format!("{}{}", column_letters(c), r + 1);
    for (key, value) in entries {
        let parts = key.split(':').collect::<Vec<_>>();
        match parts.as_slice() {
            ["cell", row, col, property] if style_valid(property, value) => {
                if let Some((r, c)) = grid.indices(row, col) {
                    cells
                        .entry(address(r, c))
                        .or_default()
                        .insert((*property).into(), value.clone());
                }
            }
            ["width", col] if integer(value, 24, 1200) => {
                if let Some(c) = grid.col_index(col) {
                    widths.insert(column_letters(c), value.clone());
                }
            }
            ["height", row] if integer(value, 16, 600) => {
                if let Some(r) = grid.row_index(row) {
                    heights.insert((r + 1).to_string(), value.clone());
                }
            }
            ["merge", row, col] => {
                if let Some(rect @ (r1, c1, r2, c2)) = rectangle(&grid, row, col, value)
                    && ranges.len() < 256
                    && !ranges.iter().any(|other| overlaps(rect, *other))
                {
                    ranges.push(rect);
                    merges.push(json!({"start": address(r1, c1), "end": address(r2, c2)}));
                }
            }
            ["frozenRows" | "frozenColumns"] => {
                let max = if key == "frozenRows" {
                    (rows.len() + 1).min(1000)
                } else {
                    cols.len().min(256)
                };
                if let Some(n) = value.as_u64().map(|n| n.min(max as u64)).filter(|n| *n > 0) {
                    output.insert(key.clone(), json!(n));
                }
            }
            _ => {}
        }
    }
    if !cells.is_empty() {
        output.insert("cells".into(), json!(cells));
    }
    if !widths.is_empty() {
        output.insert("columnWidths".into(), Value::Object(widths));
    }
    if !heights.is_empty() {
        output.insert("rowHeights".into(), Value::Object(heights));
    }
    if !merges.is_empty() {
        output.insert("merges".into(), Value::Array(merges));
    }
    output
}

pub(super) fn append_footer(text: &mut String, formatting: JsonMap<String, Value>) {
    if !formatting.is_empty() {
        let encoded = Value::Object(formatting)
            .to_string()
            .replace('<', "\\u003c")
            .replace('>', "\\u003e");
        text.push_str(&format!("\n{PREFIX}{encoded}{SUFFIX}"));
    }
}
