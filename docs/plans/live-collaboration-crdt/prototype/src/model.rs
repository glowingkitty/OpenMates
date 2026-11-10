//! Shared-document schemas for the three editors, as Yjs shared types built with `yrs`,
//! plus serialisers back to the text formats the assistant edits.
//! Doc: XmlFragment `default` (y-prosemirror/TipTap Collaboration shape: one XmlElement per
//! block, XmlText with mark attributes). Sheet: stable row/col id arrays + LWW cell map.
//! Deck: slide-id order array + slide map of element maps (LWW properties, Y.Text body).
//! The serialisers are simplified stand-ins for docx_model / markdown table / slides markup.

use std::collections::HashSet;
use yrs::types::text::Diff;
use yrs::types::Attrs;
use yrs::{
    Any, Array, ArrayRef, Doc, GetString, Map, MapPrelim, MapRef, OffsetKind, Options, Out,
    ReadTxn, Text, TextPrelim, Transact, TransactionMut, WriteTxn, XmlElementPrelim, XmlFragment,
    XmlFragmentRef, XmlOut, XmlTextPrelim, XmlTextRef,
};

/// Root name TipTap's Collaboration extension binds to by default.
pub const DOC_ROOT: &str = "default";

/// Creates a replica. UTF-16 offsets are mandatory: Yjs (JS) counts in UTF-16 code
/// units and yrs defaults to bytes, which would corrupt positions across runtimes.
pub fn new_replica(client_id: u64) -> Doc {
    let mut o = Options::with_client_id(yrs::block::ClientID::new(client_id));
    o.offset_kind = OffsetKind::Utf16;
    Doc::with_options(o)
}

// ---------------------------------------------------------------- documents

/// Root fragment of a rich-text document.
pub fn doc_root<T: WriteTxn>(txn: &mut T) -> XmlFragmentRef {
    txn.get_or_insert_xml_fragment(DOC_ROOT)
}

/// Appends a block (`paragraph`, `heading`, ...) with plain text; returns its text node.
pub fn push_block(txn: &mut TransactionMut, tag: &str, text: &str) -> XmlTextRef {
    let root = doc_root(txn);
    let idx = root.len(txn);
    insert_block(txn, &root, idx, tag, text)
}

/// Inserts a block at `index`; returns its text node.
pub fn insert_block(
    txn: &mut TransactionMut,
    root: &XmlFragmentRef,
    index: u32,
    tag: &str,
    text: &str,
) -> XmlTextRef {
    let el = root.insert(txn, index, XmlElementPrelim::empty(tag));
    el.insert(txn, 0, XmlTextPrelim::new(text))
}

/// Text node of block `index`, if that block exists and holds text.
pub fn block_text<T: ReadTxn>(txn: &T, root: &XmlFragmentRef, index: u32) -> Option<XmlTextRef> {
    match root.get(txn, index)? {
        XmlOut::Element(el) => match el.get(txn, 0)? {
            XmlOut::Text(t) => Some(t),
            _ => None,
        },
        _ => None,
    }
}

/// Plain text of every block, one line per block (input of the assistant diff path).
pub fn doc_plain_lines<T: ReadTxn>(txn: &T) -> Vec<String> {
    let Some(root) = txn.get_xml_fragment(DOC_ROOT) else {
        return vec![];
    };
    (0..root.len(txn))
        .map(|i| {
            block_text(txn, &root, i)
                .map(|t| t.get_string(txn))
                .unwrap_or_default()
        })
        .collect()
}

/// Serialises a document as `tag: text` lines with `**bold**` runs (docx_model stand-in:
/// the real serialiser emits docx_model blocks and runs with bold/italic/underline/color).
pub fn serialise_doc(doc: &Doc) -> String {
    let txn = doc.transact();
    let Some(root) = txn.get_xml_fragment(DOC_ROOT) else {
        return String::new();
    };
    let mut out = String::new();
    for i in 0..root.len(&txn) {
        let XmlOut::Element(el) = root.get(&txn, i).expect("index < len") else {
            continue;
        };
        out.push_str(el.tag());
        out.push_str(": ");
        if let Some(t) = block_text(&txn, &root, i) {
            for Diff {
                insert, attributes, ..
            } in t.diff(&txn, |_| ())
            {
                let s = match insert {
                    Out::Any(Any::String(s)) => s.to_string(),
                    _ => continue,
                };
                let bold = attributes.as_ref().is_some_and(|a| a.contains_key("bold"));
                if bold {
                    out.push_str(&format!("**{s}**"));
                } else {
                    out.push_str(&s);
                }
            }
        }
        out.push('\n');
    }
    out
}

/// Applies the `bold` mark (ProseMirror mark → Yjs formatting attribute).
pub fn bold(txn: &mut TransactionMut, t: &XmlTextRef, index: u32, len: u32) {
    t.format(
        txn,
        index,
        len,
        Attrs::from([("bold".into(), Any::Map(Default::default()))]),
    );
}

// ---------------------------------------------------------------- sheets

/// Row ids, column ids and cells of a sheet. Cells are keyed by stable ids, not A1
/// names, so a concurrent row/column insert never re-targets another member's edit.
pub struct Sheet {
    /// Ordered row ids.
    pub rows: ArrayRef,
    /// Ordered column ids.
    pub cols: ArrayRef,
    /// `"{row}:{col}"` → raw input (`"42"`, `"=SUM(B1:B2)"`); last writer wins per key.
    pub cells: MapRef,
}

/// Opens (or creates) the sheet roots.
pub fn sheet<T: WriteTxn>(txn: &mut T) -> Sheet {
    Sheet {
        rows: txn.get_or_insert_array("rows"),
        cols: txn.get_or_insert_array("cols"),
        cells: txn.get_or_insert_map("cells"),
    }
}

/// Sets one cell's raw input.
pub fn set_cell(txn: &mut TransactionMut, s: &Sheet, row: &str, col: &str, value: &str) {
    s.cells
        .insert(txn, format!("{row}:{col}"), value.to_string());
}

fn ids<T: ReadTxn>(txn: &T, a: &ArrayRef) -> Vec<String> {
    a.iter(txn).map(|v| v.to_string(txn)).collect()
}

/// Serialises a sheet as a markdown table (header row = first row), the format the
/// assistant diffs today.
pub fn serialise_sheet(doc: &Doc) -> String {
    let mut txn = doc.transact_mut();
    let s = sheet(&mut txn);
    let (rows, cols) = (ids(&txn, &s.rows), ids(&txn, &s.cols));
    let mut out = String::new();
    for (ri, r) in rows.iter().enumerate() {
        let cells: Vec<String> = cols
            .iter()
            .map(|c| {
                s.cells
                    .get(&txn, &format!("{r}:{c}"))
                    .map(|v| v.to_string(&txn))
                    .unwrap_or_default()
            })
            .collect();
        out.push_str(&format!("| {} |\n", cells.join(" | ")));
        if ri == 0 {
            out.push_str(&format!("|{}\n", "---|".repeat(cols.len())));
        }
    }
    out
}

// ---------------------------------------------------------------- decks

/// Slide order and slide content of a deck.
pub struct Deck {
    /// Slide ids in display order. Yjs has no native move: a move is delete + insert of
    /// the id; content lives in `slides`, so a move never copies or loses content.
    pub order: ArrayRef,
    /// Slide id → slide map (`elements`: element id → element map).
    pub slides: MapRef,
}

/// Opens (or creates) the deck roots.
pub fn deck<T: WriteTxn>(txn: &mut T) -> Deck {
    Deck {
        order: txn.get_or_insert_array("slide_order"),
        slides: txn.get_or_insert_map("slides"),
    }
}

/// Adds a slide at the end; returns its element map.
pub fn add_slide(txn: &mut TransactionMut, d: &Deck, slide_id: &str) -> MapRef {
    let slide = d.slides.insert(txn, slide_id, MapPrelim::default());
    let len = d.order.len(txn);
    d.order.insert(txn, len, slide_id);
    slide.insert(txn, "elements", MapPrelim::default())
}

/// Adds a positioned text element; geometry and style are LWW map entries.
pub fn add_text_element(
    txn: &mut TransactionMut,
    elements: &MapRef,
    id: &str,
    xywh: [f64; 4],
    text: &str,
) {
    let el = elements.insert(txn, id, MapPrelim::default());
    el.insert(txn, "type", "text");
    for (k, v) in ["x", "y", "w", "h"].iter().zip(xywh) {
        el.insert(txn, *k, v);
    }
    el.insert(txn, "body", TextPrelim::new(text));
}

/// Element map by slide and element id.
pub fn element<T: ReadTxn>(txn: &T, d: &Deck, slide: &str, el: &str) -> Option<MapRef> {
    let Some(Out::YMap(s)) = d.slides.get(txn, slide) else {
        return None;
    };
    let Some(Out::YMap(els)) = s.get(txn, "elements") else {
        return None;
    };
    match els.get(txn, el) {
        Some(Out::YMap(m)) => Some(m),
        _ => None,
    }
}

/// Moves slide `from` to position `to` (indices in the current order).
pub fn move_slide(txn: &mut TransactionMut, d: &Deck, from: u32, to: u32) {
    let id = d.order.get(txn, from).expect("from < len").to_string(txn);
    d.order.remove(txn, from);
    d.order.insert(txn, to, id);
}

/// Effective slide order: first occurrence wins, ids without content are skipped.
/// Concurrent moves of one slide leave two copies of its id; concurrent delete + move
/// leaves a dangling id. Both are resolved deterministically here on every replica.
pub fn effective_order<T: ReadTxn>(txn: &T, d: &Deck) -> Vec<String> {
    let mut seen = HashSet::new();
    ids(txn, &d.order)
        .into_iter()
        .filter(|id| d.slides.get(txn, id).is_some() && seen.insert(id.clone()))
        .collect()
}

/// Serialises a deck as slides markup, one positioned element per line.
pub fn serialise_deck(doc: &Doc) -> String {
    let mut txn = doc.transact_mut();
    let d = deck(&mut txn);
    let mut out = String::new();
    for sid in effective_order(&txn, &d) {
        out.push_str(&format!("<slide id=\"{sid}\">\n"));
        let Some(Out::YMap(s)) = d.slides.get(&txn, &sid) else {
            continue;
        };
        let Some(Out::YMap(els)) = s.get(&txn, "elements") else {
            continue;
        };
        let mut keys: Vec<String> = els.keys(&txn).map(str::to_string).collect();
        keys.sort();
        for k in keys {
            let Some(Out::YMap(el)) = els.get(&txn, &k) else {
                continue;
            };
            let g = |n: &str| {
                el.get(&txn, n)
                    .map(|v| v.to_string(&txn))
                    .unwrap_or_default()
            };
            let body = match el.get(&txn, "body") {
                Some(Out::YText(t)) => t.get_string(&txn),
                _ => String::new(),
            };
            let fill = el
                .get(&txn, "fill")
                .map(|v| format!(" fill=\"{}\"", v.to_string(&txn)));
            out.push_str(&format!(
                "  <{} id=\"{k}\" x={} y={} w={} h={}{}>{body}</{}>\n",
                g("type"),
                g("x"),
                g("y"),
                g("w"),
                g("h"),
                fill.unwrap_or_default(),
                g("type")
            ));
        }
        out.push_str("</slide>\n");
    }
    out
}
