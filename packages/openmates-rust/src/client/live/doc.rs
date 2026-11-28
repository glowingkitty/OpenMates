//! Document adapter. Yjs root: `Y.XmlFragment` `default` in the ProseMirror/TipTap shape:
//! `paragraph`, `heading` (attr `level`), `bulletList`/`orderedList` > `listItem` >
//! block nodes, `rawBlock` (attr `html`, unsupported HTML preserved verbatim; the editor
//! must register it as an atom node), and text (`Y.XmlText`) with the marks `bold`,
//! `italic`, `code` and `link` (`{href}`). The text form is the document embed's stored
//! `html` string (the subset in `doc_html`).

use super::LiveError;
use super::doc_html::{Block, Run, blocks_html, parse_blocks};
use std::collections::HashMap;
use std::sync::Arc;
use yrs::types::text::{Diff, YChange};
use yrs::types::xml::XmlIn;
use yrs::{
    Any, Doc, In, Out, ReadTxn, Text, Transact, TransactionMut, Xml, XmlElementPrelim,
    XmlElementRef, XmlFragment, XmlFragmentRef, XmlOut, XmlTextPrelim,
};

const ROOT: &str = "default";

fn marks_of(run: &Run) -> HashMap<Arc<str>, Any> {
    let empty = || Any::Map(Arc::new(HashMap::new()));
    let mut attrs = HashMap::new();
    if run.bold {
        attrs.insert(Arc::from("bold"), empty());
    }
    if run.italic {
        attrs.insert(Arc::from("italic"), empty());
    }
    if run.code {
        attrs.insert(Arc::from("code"), empty());
    }
    if let Some(href) = &run.link {
        let map = HashMap::from([("href".to_string(), Any::String(href.as_str().into()))]);
        attrs.insert(Arc::from("link"), Any::Map(Arc::new(map)));
    }
    attrs
}

fn write_runs<P: XmlFragment>(txn: &mut TransactionMut, parent: &P, runs: &[Run]) {
    if runs.is_empty() {
        return;
    }
    let text = parent.push_back(txn, XmlTextPrelim::new(""));
    let mut at = 0u32;
    for run in runs {
        text.insert_with_attributes(txn, at, &run.text, marks_of(run));
        at += run.text.encode_utf16().count() as u32;
    }
}

fn write_block<P: XmlFragment>(txn: &mut TransactionMut, parent: &P, block: &Block) {
    match block {
        Block::Paragraph(runs) => {
            let el = parent.push_back(txn, XmlElementPrelim::empty("paragraph"));
            write_runs(txn, &el, runs);
        }
        Block::Heading(level, runs) => {
            let el = parent.push_back(txn, XmlElementPrelim::empty("heading"));
            el.insert_attribute(txn, "level", In::Any(Any::from(i64::from(*level))));
            write_runs(txn, &el, runs);
        }
        Block::List { ordered, items } => {
            let tag = if *ordered {
                "orderedList"
            } else {
                "bulletList"
            };
            let el = parent.push_back(txn, XmlElementPrelim::empty(tag));
            for item in items {
                let li = el.push_back(txn, XmlElementPrelim::empty("listItem"));
                for child in item {
                    write_block(txn, &li, child);
                }
            }
        }
        Block::Raw(html) => {
            let mut prelim = XmlElementPrelim::empty("rawBlock");
            prelim.attributes.insert(Arc::from("html"), html.clone());
            parent.push_back(txn, XmlIn::from(prelim));
        }
    }
}

/// Hydrates an empty replica from the stored HTML.
pub(crate) fn from_text(doc: &Doc, html: &str) {
    let fragment = doc.get_or_insert_xml_fragment(ROOT);
    let blocks = parse_blocks(html);
    let mut txn = doc.transact_mut();
    for block in &blocks {
        write_block(&mut txn, &fragment, block);
    }
}

fn read_runs<T: ReadTxn, P: XmlFragment>(txn: &T, parent: &P) -> Vec<Run> {
    let mut runs: Vec<Run> = Vec::new();
    for child in parent.children(txn) {
        let XmlOut::Text(text) = child else { continue };
        for Diff {
            insert, attributes, ..
        } in text.diff(txn, YChange::identity)
        {
            let Out::Any(Any::String(s)) = insert else {
                continue;
            };
            let mut run = Run {
                text: s.to_string(),
                ..Run::default()
            };
            for (key, value) in attributes.iter().flat_map(|a| a.iter()) {
                match (&**key, value) {
                    (_, Any::Null) => {}
                    ("bold", _) => run.bold = true,
                    ("italic", _) => run.italic = true,
                    ("code", _) => run.code = true,
                    ("link", Any::Map(m)) => {
                        if let Some(Any::String(h)) = m.get("href") {
                            run.link = Some(h.to_string());
                        }
                    }
                    _ => {}
                }
            }
            runs.push(run);
        }
    }
    runs
}

fn read_children<T: ReadTxn, P: XmlFragment>(txn: &T, parent: &P) -> Vec<Block> {
    parent
        .children(txn)
        .filter_map(|c| read_block(txn, c))
        .collect()
}

fn read_block<T: ReadTxn>(txn: &T, node: XmlOut) -> Option<Block> {
    let XmlOut::Element(el) = node else {
        return None;
    };
    read_element(txn, &el)
}

fn read_element<T: ReadTxn>(txn: &T, el: &XmlElementRef) -> Option<Block> {
    let tag = el.try_tag()?.to_string();
    Some(match tag.as_str() {
        "heading" => {
            let level = match el.get_attribute(txn, "level") {
                Some(Out::Any(Any::Number(yrs::Number::Int(n)))) => n as u8,
                Some(Out::Any(Any::Number(yrs::Number::Float(n)))) => n as u8,
                Some(Out::Any(Any::String(s))) => s.parse().unwrap_or(1),
                _ => 1,
            };
            Block::Heading(level.clamp(1, 6), read_runs(txn, el))
        }
        "bulletList" | "orderedList" => Block::List {
            ordered: tag == "orderedList",
            items: el
                .children(txn)
                .filter_map(|c| match c {
                    XmlOut::Element(li) => Some(read_children(txn, &li)),
                    _ => None,
                })
                .collect(),
        },
        "rawBlock" => match el.get_attribute(txn, "html") {
            Some(Out::Any(Any::String(s))) => Block::Raw(s.to_string()),
            _ => return None,
        },
        // `paragraph` and any element a mirror adds that is not in the subset: its text.
        _ => Block::Paragraph(read_runs(txn, el)),
    })
}

/// The stored HTML.
pub(crate) fn to_text(doc: &Doc) -> Result<String, LiveError> {
    let fragment: XmlFragmentRef = doc.get_or_insert_xml_fragment(ROOT);
    let txn = doc.transact();
    Ok(blocks_html(&read_children(&txn, &fragment)))
}

/// The top-level blocks of the live fragment, in order.
pub(crate) fn read_blocks(doc: &Doc) -> Vec<Block> {
    let fragment: XmlFragmentRef = doc.get_or_insert_xml_fragment(ROOT);
    let txn = doc.transact();
    read_children(&txn, &fragment)
}

/// Inserts `block` as the top-level child at `index`.
fn insert_block(txn: &mut TransactionMut, parent: &XmlFragmentRef, index: u32, block: &Block) {
    match block {
        Block::Paragraph(runs) => {
            let el = parent.insert(txn, index, XmlElementPrelim::empty("paragraph"));
            write_runs(txn, &el, runs);
        }
        Block::Heading(level, runs) => {
            let el = parent.insert(txn, index, XmlElementPrelim::empty("heading"));
            el.insert_attribute(txn, "level", In::Any(Any::from(i64::from(*level))));
            write_runs(txn, &el, runs);
        }
        Block::List { ordered, items } => {
            let tag = if *ordered {
                "orderedList"
            } else {
                "bulletList"
            };
            let el = parent.insert(txn, index, XmlElementPrelim::empty(tag));
            for item in items {
                let li = el.push_back(txn, XmlElementPrelim::empty("listItem"));
                for child in item {
                    write_block(txn, &li, child);
                }
            }
        }
        Block::Raw(html) => {
            let mut prelim = XmlElementPrelim::empty("rawBlock");
            prelim.attributes.insert(Arc::from("html"), html.clone());
            parent.insert(txn, index, XmlIn::from(prelim));
        }
    }
}

/// The live fragment handle (obtain it before opening a transaction).
pub(crate) fn fragment_of(doc: &Doc) -> XmlFragmentRef {
    doc.get_or_insert_xml_fragment(ROOT)
}

/// Replaces top-level children `start..end` with `blocks`, in the caller's transaction.
pub(crate) fn replace_blocks(
    txn: &mut TransactionMut,
    fragment: &XmlFragmentRef,
    start: u32,
    end: u32,
    blocks: &[Block],
) {
    if end > start {
        fragment.remove_range(txn, start, end - start);
    }
    for (offset, block) in blocks.iter().enumerate() {
        insert_block(txn, fragment, start + offset as u32, block);
    }
}
