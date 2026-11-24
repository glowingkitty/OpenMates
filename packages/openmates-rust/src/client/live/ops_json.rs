//! JSON wire shapes of live items for the shells: typed operations in (`LocalOp`) and view
//! models out (sheet grid, deck view). Marshalling only; the engine owns every decision.

use super::engine::{LiveItem, LocalOp};
use super::sheet::SheetOp;
use super::sheet_formula::to_a1;
use super::{LiveError, LiveItemKind, SheetFormatChange, sheet_formatting};
use crate::client::shared_items::DeckOperation;
use serde::Deserialize;
use serde_json::{Value, json};
use yrs::{Any, Array, ArrayRef, Map, MapRef, Out, ReadTxn, Transact};

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum OpWire {
    SetCell {
        row_id: String,
        col_id: String,
        value: String,
    },
    SetHeader {
        col_id: String,
        value: String,
    },
    InsertRow {
        #[serde(default)]
        after_row_id: Option<String>,
    },
    DeleteRow {
        row_id: String,
    },
    InsertCol {
        #[serde(default)]
        after_col_id: Option<String>,
    },
    DeleteCol {
        col_id: String,
    },
    SheetFormat {
        changes: Vec<SheetFormatChange>,
    },
    SheetUndoFormatting,
    Deck {
        operation: DeckOperation,
    },
    CodeReplaceLines {
        start: usize,
        end: usize,
        text: String,
    },
}

/// Parses one operation JSON into a [`LocalOp`].
///
/// # Errors
/// [`LiveError::InvalidUpdate`] for malformed JSON or an unknown operation.
pub fn parse_op(json_text: &str) -> Result<LocalOp, LiveError> {
    let wire: OpWire =
        serde_json::from_str(json_text).map_err(|e| LiveError::InvalidUpdate(e.to_string()))?;
    Ok(match wire {
        OpWire::SetCell {
            row_id,
            col_id,
            value,
        } => LocalOp::Sheet(SheetOp::SetCell {
            row_id,
            col_id,
            value,
        }),
        OpWire::SetHeader { col_id, value } => LocalOp::Sheet(SheetOp::SetHeader { col_id, value }),
        OpWire::InsertRow { after_row_id } => LocalOp::Sheet(SheetOp::InsertRow { after_row_id }),
        OpWire::DeleteRow { row_id } => LocalOp::Sheet(SheetOp::DeleteRow { row_id }),
        OpWire::InsertCol { after_col_id } => LocalOp::Sheet(SheetOp::InsertCol { after_col_id }),
        OpWire::DeleteCol { col_id } => LocalOp::Sheet(SheetOp::DeleteCol { col_id }),
        OpWire::SheetFormat { changes } => LocalOp::Sheet(SheetOp::Format(changes)),
        OpWire::SheetUndoFormatting => LocalOp::Sheet(SheetOp::UndoFormatting),
        OpWire::Deck { operation } => LocalOp::Deck(operation),
        OpWire::CodeReplaceLines { start, end, text } => {
            LocalOp::CodeReplaceLines { start, end, text }
        }
    })
}

/// Session-level operations on an assistant change: no [`LocalOp`], they act on the session.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AssistantOp {
    /// `{"op":"undo_assistant","turn_id"}`: undo the whole assistant edit of a turn.
    Undo {
        /// Assistant turn.
        turn_id: String,
    },
    /// `{"op":"dismiss_suggestion","row_id","col_id"}`: drop a sheet suggestion card.
    DismissSuggestion {
        /// Row id.
        row_id: String,
        /// Column id.
        col_id: String,
    },
}

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum AssistantOpWire {
    UndoAssistant { turn_id: String },
    DismissSuggestion { row_id: String, col_id: String },
}

/// Parses `undo_assistant` / `dismiss_suggestion`; `None` for every other operation
/// (use [`parse_op`] for those).
///
/// # Errors
/// [`LiveError::InvalidUpdate`] for malformed JSON of these two operations.
pub fn parse_assistant_op(json_text: &str) -> Result<Option<AssistantOp>, LiveError> {
    let value: Value =
        serde_json::from_str(json_text).map_err(|e| LiveError::InvalidUpdate(e.to_string()))?;
    if !matches!(
        value["op"].as_str(),
        Some("undo_assistant" | "dismiss_suggestion")
    ) {
        return Ok(None);
    }
    let wire: AssistantOpWire =
        serde_json::from_value(value).map_err(|e| LiveError::InvalidUpdate(e.to_string()))?;
    Ok(Some(match wire {
        AssistantOpWire::UndoAssistant { turn_id } => AssistantOp::Undo { turn_id },
        AssistantOpWire::DismissSuggestion { row_id, col_id } => {
            AssistantOp::DismissSuggestion { row_id, col_id }
        }
    }))
}

/// Adds `cells[key].suggestion = {assistant_value}` to a sheet view (suggestion cards).
pub fn add_suggestions(view: &mut Value, suggestions: &std::collections::HashMap<String, String>) {
    let Some(cells) = view.get_mut("cells").and_then(Value::as_object_mut) else {
        return;
    };
    for (key, assistant_value) in suggestions {
        let entry = cells
            .entry(key.clone())
            .or_insert_with(|| json!({"display": ""}));
        entry["suggestion"] = json!({"assistant_value": assistant_value});
    }
}

fn text(value: Option<Out>) -> Option<String> {
    match value {
        Some(Out::Any(Any::String(s))) => Some(s.to_string()),
        _ => None,
    }
}

fn ids<T: ReadTxn>(txn: &T, array: &ArrayRef) -> Vec<String> {
    array.iter(txn).filter_map(|v| text(Some(v))).collect()
}

fn texts<T: ReadTxn>(txn: &T, map: &MapRef) -> serde_json::Map<String, Value> {
    map.iter(txn)
        .filter_map(|(k, v)| text(Some(v)).map(|t| (k.to_string(), Value::String(t))))
        .collect()
}

/// The view model of a sheet or deck item as JSON (`None` for documents and code, which the
/// JS mirror renders itself).
///
/// Sheet: `{rows, cols, headers, aligns, cells: {"rowId:colId": {display, formula?}}}`.
/// Deck: the `DeckView` serde shape of the slides editor.
///
/// # Errors
/// [`LiveError::Empty`] when the item has no content yet.
pub fn view_json(item: &LiveItem) -> Result<Option<Value>, LiveError> {
    match item.kind() {
        LiveItemKind::Deck => {
            let deck = item.deck().ok_or(LiveError::Empty)?;
            serde_json::to_value(deck.view())
                .map(Some)
                .map_err(|e| LiveError::InvalidUpdate(e.to_string()))
        }
        LiveItemKind::Sheet => {
            let doc = item.plain_doc().ok_or(LiveError::Empty)?;
            // The roots are created before the read transaction: creating one inside it
            // would wait for a write lock held by nobody and never return.
            let (rows_ref, cols_ref) = (
                doc.get_or_insert_array("rows"),
                doc.get_or_insert_array("cols"),
            );
            let (headers_ref, aligns_ref) = (
                doc.get_or_insert_map("headers"),
                doc.get_or_insert_map("aligns"),
            );
            let cells_ref = doc.get_or_insert_map("cells");
            let format_root = sheet_formatting::root(doc);
            let txn = doc.transact();
            let rows = ids(&txn, &rows_ref);
            let cols = ids(&txn, &cols_ref);
            let headers = texts(&txn, &headers_ref);
            let aligns = texts(&txn, &aligns_ref);
            let mut cells = serde_json::Map::new();
            for (key, value) in cells_ref.iter(&txn) {
                let Out::YMap(cell) = value else { continue };
                let v = text(cell.get(&txn, "v")).unwrap_or_default();
                let entry = match text(cell.get(&txn, "f")) {
                    Some(f) => {
                        let a1 = to_a1(&f, &rows, &cols);
                        let display = if v.is_empty() { a1.clone() } else { v };
                        json!({"display": display, "formula": a1})
                    }
                    None => json!({"display": v}),
                };
                cells.insert(key.to_string(), entry);
            }
            let formatting = sheet_formatting::projected(
                &sheet_formatting::read(&txn, &format_root),
                &rows,
                &cols,
            );
            Ok(Some(json!({
                "rows": rows, "cols": cols, "headers": headers, "aligns": aligns, "cells": cells,
                "formatting": formatting, "canUndoFormatting": item.can_undo_sheet_formatting(),
            })))
        }
        LiveItemKind::Doc | LiveItemKind::Code => Ok(None),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::client::live::support::create;

    #[test]
    fn parses_every_sheet_and_code_op() {
        for (json_text, ok) in [
            (
                r#"{"op":"set_cell","row_id":"r","col_id":"c","value":"1"}"#,
                true,
            ),
            (r#"{"op":"set_header","col_id":"c","value":"H"}"#, true),
            (r#"{"op":"insert_row"}"#, true),
            (r#"{"op":"insert_row","after_row_id":"r"}"#, true),
            (r#"{"op":"delete_row","row_id":"r"}"#, true),
            (r#"{"op":"insert_col","after_col_id":"c"}"#, true),
            (r#"{"op":"delete_col","col_id":"c"}"#, true),
            (
                r#"{"op":"code_replace_lines","start":0,"end":1,"text":"x"}"#,
                true,
            ),
            (r#"{"op":"nope"}"#, false),
            (r#"{"op":"set_cell"}"#, false),
        ] {
            assert_eq!(parse_op(json_text).is_ok(), ok, "{json_text}");
        }
    }

    #[test]
    fn parses_deck_wrapper() {
        let op = r#"{"op":"deck","operation":{"op":"add_slide","index":null,"layout":null}}"#;
        assert!(matches!(parse_op(op), Ok(LocalOp::Deck(_))));
    }

    #[test]
    fn sheet_view_lists_ids_headers_and_cells() {
        let mut item = create(LiveItemKind::Sheet, "| A | B |\n| --- | --- |\n| 1 | 2 |");
        let view = view_json(&item).expect("view").expect("sheet has a view");
        let rows = view["rows"].as_array().expect("rows").clone();
        let cols = view["cols"].as_array().expect("cols").clone();
        assert_eq!((rows.len(), cols.len()), (1, 2));
        let key = format!(
            "{}:{}",
            rows[0].as_str().unwrap(),
            cols[0].as_str().unwrap()
        );
        assert_eq!(view["cells"][&key]["display"], "1");
        assert_eq!(view["headers"][cols[1].as_str().unwrap()], "B");
        let set = format!(
            r#"{{"op":"set_cell","row_id":"{}","col_id":"{}","value":"=B1"}}"#,
            rows[0].as_str().unwrap(),
            cols[0].as_str().unwrap()
        );
        item.apply_local_op(parse_op(&set).unwrap()).unwrap();
        let view = view_json(&item).unwrap().unwrap();
        assert_eq!(view["cells"][&key]["formula"], "=B1");
    }

    #[test]
    fn documents_have_no_view() {
        let item = create(LiveItemKind::Code, "x");
        assert!(view_json(&item).unwrap().is_none());
    }
}
