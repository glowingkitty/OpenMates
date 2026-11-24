//! Sheet adapter. Yjs roots: `rows` and `cols` (`Y.Array` of stable id strings, data rows
//! only), `cells` (`Y.Map` keyed `"{rowId}:{colId}"`, each value a map `{v, f?}`), plus
//! `headers` and `aligns` (`Y.Map` colId -> text). `v` is the displayed text; `f` is the
//! formula stored with ids (see `sheet_formula`). The text form is the sheet embed's
//! markdown table (`| h | h |`, `| --- | --- |`, data rows) with formulas in A1 notation;
//! cells starting with `=` are formulas. Cell values cannot contain `|` or line breaks.

use super::sheet_formatting::{self, SheetFormatChange};
use super::sheet_formula::{to_a1, to_stored};
use super::{LiveError, new_id};
use std::collections::BTreeMap;
use yrs::types::map::MapPrelim;
use yrs::{Any, Array, ArrayRef, Doc, In, Map, MapRef, Out, ReadTxn, Transact, TransactionMut};

/// A typed sheet operation; ids are stable across concurrent structure changes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SheetOp {
    /// Sets one cell; text starting with `=` is a formula in A1 notation.
    SetCell {
        /// Row id.
        row_id: String,
        /// Column id.
        col_id: String,
        /// New text, empty clears the cell.
        value: String,
    },
    /// Sets a column header.
    SetHeader {
        /// Column id.
        col_id: String,
        /// Header text.
        value: String,
    },
    /// Inserts an empty row after `after_row_id` (`None` = first). Returns the new id.
    InsertRow {
        /// Row to insert after.
        after_row_id: Option<String>,
    },
    /// Deletes a row and its cells.
    DeleteRow {
        /// Row id.
        row_id: String,
    },
    /// Inserts an empty column after `after_col_id` (`None` = first). Returns the new id.
    InsertCol {
        /// Column to insert after.
        after_col_id: Option<String>,
    },
    /// Deletes a column and its cells.
    DeleteCol {
        /// Column id.
        col_id: String,
    },
    /// Applies a group of formatting changes atomically on stable cells and axes.
    Format(Vec<SheetFormatChange>),
    /// Undoes the latest formatting operation authored by this replica.
    UndoFormatting,
}

fn text_of(out: Option<Out>) -> Option<String> {
    match out {
        Some(Out::Any(Any::String(s))) => Some(s.to_string()),
        _ => None,
    }
}

fn ids<T: ReadTxn>(txn: &T, array: &ArrayRef) -> Vec<String> {
    array.iter(txn).filter_map(|v| text_of(Some(v))).collect()
}

struct Roots {
    rows: ArrayRef,
    cols: ArrayRef,
    cells: MapRef,
    headers: MapRef,
    aligns: MapRef,
}

fn roots(doc: &Doc) -> Roots {
    Roots {
        rows: doc.get_or_insert_array("rows"),
        cols: doc.get_or_insert_array("cols"),
        cells: doc.get_or_insert_map("cells"),
        headers: doc.get_or_insert_map("headers"),
        aligns: doc.get_or_insert_map("aligns"),
    }
}

pub(super) fn split_row(line: &str) -> Vec<String> {
    let t = line.trim();
    let t = t.strip_prefix('|').unwrap_or(t);
    let t = t.strip_suffix('|').unwrap_or(t);
    t.split('|').map(|c| c.trim().to_string()).collect()
}

fn check_value(value: &str) -> Result<(), LiveError> {
    if value.contains('|') || value.contains('\n') {
        return Err(LiveError::InvalidCell(
            "pipes and line breaks are not allowed",
        ));
    }
    Ok(())
}

pub(super) fn is_formula(value: &str) -> bool {
    value.trim_start().starts_with('=') && value.trim().len() > 1
}

fn write_cell(
    txn: &mut TransactionMut,
    r: &Roots,
    row_id: &str,
    col_id: &str,
    value: &str,
    rows: &[String],
    cols: &[String],
) {
    let key = format!("{row_id}:{col_id}");
    let value = value.trim();
    if value.is_empty() {
        r.cells.remove(txn, &key);
        return;
    }
    let mut entries = vec![("v", In::Any(Any::from(value.to_string())))];
    if is_formula(value) {
        entries.push(("f", In::Any(Any::from(to_stored(value, rows, cols)))));
    }
    r.cells.insert(txn, key, MapPrelim::from_iter(entries));
}

/// Validates a formatted snapshot before an assistant writes a Project Sheet.
/// Legacy plain text keeps its existing behavior.
pub(crate) fn validate_formatted_snapshot(text: &str) -> Result<(), LiveError> {
    let (table, formatting) = sheet_formatting::split(text)?;
    let Some(formatting) = formatting else {
        return Ok(());
    };
    let lines: Vec<_> = table.lines().collect();
    let width = lines.first().map_or(0, |line| split_row(line).len());
    if !(2..=1001).contains(&lines.len())
        || !(1..=256).contains(&width)
        || lines.iter().any(|line| {
            !line.starts_with('|')
                || !line.ends_with('|')
                || line.bytes().filter(|b| *b == b'|').count() != width + 1
        })
        || split_row(lines[1]).iter().any(|alignment| {
            let separators = alignment.strip_prefix(':').unwrap_or(alignment);
            let separators = separators.strip_suffix(':').unwrap_or(separators);
            separators.len() < 3 || !separators.bytes().all(|b| b == b'-')
        })
    {
        return Err(LiveError::InvalidText("invalid formatted sheet table"));
    }
    let rows: Vec<_> = (1..=lines.len() - 2).map(|i| format!("r{i}")).collect();
    let cols: Vec<_> = (1..=width).map(|i| format!("c{i}")).collect();
    sheet_formatting::snapshot_entries(Some(&formatting), &rows, &cols).map(|_| ())
}

/// Hydrates an empty replica from the markdown table.
pub(crate) fn from_text(doc: &Doc, text: &str) -> Result<(), LiveError> {
    let (text, formatting) = sheet_formatting::split(text)?;
    let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    if lines.len() < 2 {
        return Err(LiveError::InvalidText(
            "a sheet needs a header and a separator row",
        ));
    }
    let headers = split_row(lines[0]);
    let aligns = split_row(lines[1]);
    let cols: Vec<String> = (1..=headers.len()).map(|i| format!("c{i}")).collect();
    let rows: Vec<String> = (1..=lines.len() - 2).map(|i| format!("r{i}")).collect();
    let formatting = sheet_formatting::snapshot_entries(formatting.as_ref(), &rows, &cols)?;
    let r = roots(doc);
    let format_root = sheet_formatting::root(doc);
    let mut txn = doc.transact_mut();
    for (i, col) in cols.iter().enumerate() {
        r.cols.push_back(&mut txn, col.clone());
        r.headers.insert(&mut txn, col.clone(), headers[i].clone());
        let align = aligns.get(i).cloned().unwrap_or_else(|| "---".into());
        r.aligns.insert(&mut txn, col.clone(), align);
    }
    for row in &rows {
        r.rows.push_back(&mut txn, row.clone());
    }
    for (ri, line) in lines[2..].iter().enumerate() {
        let cells = split_row(line);
        for (ci, col) in cols.iter().enumerate() {
            let value = cells.get(ci).map(String::as_str).unwrap_or("");
            write_cell(&mut txn, &r, &rows[ri], col, value, &rows, &cols);
        }
    }
    sheet_formatting::write(&mut txn, &format_root, &Default::default(), &formatting);
    Ok(())
}

/// Writes the markdown table; formulas render in A1 notation for the current grid.
pub(crate) fn to_text(doc: &Doc) -> Result<String, LiveError> {
    let r = roots(doc);
    let format_root = sheet_formatting::root(doc);
    let txn = doc.transact();
    let cols = ids(&txn, &r.cols);
    let rows = ids(&txn, &r.rows);
    if cols.is_empty() {
        return Err(LiveError::Empty);
    }
    let get = |map: &MapRef, key: &str| text_of(map.get(&txn, key)).unwrap_or_default();
    let line = |cells: Vec<String>| format!("| {} |", cells.join(" | "));
    let mut out = vec![
        line(cols.iter().map(|c| get(&r.headers, c)).collect()),
        line(
            cols.iter()
                .map(|c| {
                    let a = get(&r.aligns, c);
                    if a.is_empty() { "---".to_string() } else { a }
                })
                .collect(),
        ),
    ];
    for row in &rows {
        let cells = cols
            .iter()
            .map(|col| match r.cells.get(&txn, &format!("{row}:{col}")) {
                Some(Out::YMap(cell)) => match text_of(cell.get(&txn, "f")) {
                    Some(f) => to_a1(&f, &rows, &cols),
                    None => text_of(cell.get(&txn, "v")).unwrap_or_default(),
                },
                _ => String::new(),
            })
            .collect();
        out.push(line(cells));
    }
    let mut text = out.join("\n");
    let entries = sheet_formatting::read(&txn, &format_root);
    sheet_formatting::append_footer(
        &mut text,
        sheet_formatting::projected(&entries, &rows, &cols),
    );
    Ok(text)
}

/// Row ids, column ids and the live cell texts (A1 formulas), for a view model.
pub(crate) fn grid(doc: &Doc) -> (Vec<String>, Vec<String>, BTreeMap<String, String>) {
    let r = roots(doc);
    let txn = doc.transact();
    let (cols, rows) = (ids(&txn, &r.cols), ids(&txn, &r.rows));
    let mut cells = BTreeMap::new();
    for (key, value) in r.cells.iter(&txn) {
        if let Out::YMap(cell) = value {
            let text = match text_of(cell.get(&txn, "f")) {
                Some(f) => to_a1(&f, &rows, &cols),
                None => text_of(cell.get(&txn, "v")).unwrap_or_default(),
            };
            cells.insert(key.to_string(), text);
        }
    }
    (rows, cols, cells)
}

fn position(list: &[String], id: &str) -> Option<usize> {
    list.iter().position(|v| v == id)
}

/// Applies one operation in a single transaction; returns the id of an inserted row or column.
pub(crate) fn apply_op(doc: &Doc, op: &SheetOp) -> Result<Option<String>, LiveError> {
    apply_op_with_origin(doc, op, None)
}

/// [`apply_op`] under a named transaction origin (assistant edits use `assistant:{turn}`).
pub(crate) fn apply_op_with_origin(
    doc: &Doc,
    op: &SheetOp,
    origin: Option<&str>,
) -> Result<Option<String>, LiveError> {
    let r = roots(doc);
    let format_root = sheet_formatting::root(doc);
    let mut txn = match origin {
        Some(origin) => doc.transact_mut_with(origin),
        None => doc.transact_mut(),
    };
    let rows = ids(&txn, &r.rows);
    let cols = ids(&txn, &r.cols);
    let row_index = |id: &str| position(&rows, id).ok_or_else(|| LiveError::RowNotFound(id.into()));
    let col_index =
        |id: &str| position(&cols, id).ok_or_else(|| LiveError::ColumnNotFound(id.into()));
    match op {
        SheetOp::SetCell {
            row_id,
            col_id,
            value,
        } => {
            row_index(row_id)?;
            col_index(col_id)?;
            check_value(value)?;
            write_cell(&mut txn, &r, row_id, col_id, value, &rows, &cols);
            Ok(None)
        }
        SheetOp::SetHeader { col_id, value } => {
            col_index(col_id)?;
            check_value(value)?;
            r.headers
                .insert(&mut txn, col_id.clone(), value.trim().to_string());
            Ok(None)
        }
        SheetOp::InsertRow { after_row_id } => {
            let at = match after_row_id {
                Some(id) => row_index(id)? as u32 + 1,
                None => 0,
            };
            let id = new_id('r');
            r.rows.insert(&mut txn, at, id.clone());
            Ok(Some(id))
        }
        SheetOp::InsertCol { after_col_id } => {
            let at = match after_col_id {
                Some(id) => col_index(id)? as u32 + 1,
                None => 0,
            };
            let id = new_id('c');
            r.cols.insert(&mut txn, at, id.clone());
            r.headers.insert(&mut txn, id.clone(), String::new());
            r.aligns.insert(&mut txn, id.clone(), "---".to_string());
            Ok(Some(id))
        }
        SheetOp::DeleteRow { row_id } => {
            let at = row_index(row_id)?;
            r.rows.remove(&mut txn, at as u32);
            for col in &cols {
                r.cells.remove(&mut txn, &format!("{row_id}:{col}"));
            }
            Ok(None)
        }
        SheetOp::DeleteCol { col_id } => {
            let at = col_index(col_id)?;
            r.cols.remove(&mut txn, at as u32);
            r.headers.remove(&mut txn, col_id);
            r.aligns.remove(&mut txn, col_id);
            for row in &rows {
                r.cells.remove(&mut txn, &format!("{row}:{col_id}"));
            }
            Ok(None)
        }
        SheetOp::Format(changes) => {
            sheet_formatting::apply(&mut txn, &format_root, &rows, &cols, changes)?;
            Ok(None)
        }
        SheetOp::UndoFormatting => Err(LiveError::InvalidUpdate(
            "formatting undo requires the live replica".into(),
        )),
    }
}
