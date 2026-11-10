//! Deck schema inside the `yrs` document: how slides and elements are laid out as Yjs types.
//! Shared client core; the schema of `docs/plans/live-collaboration-crdt/spike.md` §1 (deck).
//! Roots: map `deck` (title, aspect, template), array `slide_order` (slide ids), map `slides`
//! (slide id -> map {layout, transition, notes, element_order: array, elements: map}).
//! Element map: `type`, one string per attribute, content under `body` (Y.XmlFragment for
//! text), `label` (link), `items` (array of {text, done}) or `code` (block).

use super::deck_error::DeckError;
use super::deck_inline::{INLINE_TAGS, InlineNode, normalise_nodes, parse_inline};
use super::deck_markup::{DeckModel, ElementContent, ElementModel, SlideModel, TodoItem};
use super::deck_values::{
    DEFAULT_TEMPLATE, DeckAspect, ElementKind, clamp_box, clean_attribute, clean_item_label,
    clean_layout, clean_note_text, clean_notes, clean_title, clean_transition, is_valid_template,
};
use std::collections::{BTreeMap, HashSet};
use yrs::types::xml::XmlIn;
use yrs::{
    Any, Array, ArrayPrelim, ArrayRef, GetString, In, Map, MapPrelim, MapRef, Out, ReadTxn,
    TransactionMut, WriteTxn, XmlElementPrelim, XmlFragment, XmlFragmentPrelim, XmlOut,
    XmlTextPrelim,
};

pub(crate) const ROOT_META: &str = "deck";
pub(crate) const ROOT_ORDER: &str = "slide_order";
pub(crate) const ROOT_SLIDES: &str = "slides";
pub(crate) const KEY_TYPE: &str = "type";
pub(crate) const KEY_BODY: &str = "body";
pub(crate) const KEY_LABEL: &str = "label";
pub(crate) const KEY_ITEMS: &str = "items";
pub(crate) const KEY_CODE: &str = "code";
pub(crate) const KEY_NOTE: &str = "note";
pub(crate) const KEY_ELEMENTS: &str = "elements";
pub(crate) const KEY_ELEMENT_ORDER: &str = "element_order";

/// The three root types of a deck.
pub(crate) struct DeckRoots {
    pub(crate) meta: MapRef,
    pub(crate) order: ArrayRef,
    pub(crate) slides: MapRef,
}

pub(crate) fn roots<T: WriteTxn>(txn: &mut T) -> DeckRoots {
    DeckRoots {
        meta: txn.get_or_insert_map(ROOT_META),
        order: txn.get_or_insert_array(ROOT_ORDER),
        slides: txn.get_or_insert_map(ROOT_SLIDES),
    }
}

pub(crate) fn get_string<T: ReadTxn>(map: &MapRef, txn: &T, key: &str) -> Option<String> {
    match map.get(txn, key) {
        Some(Out::Any(Any::String(value))) => Some(value.to_string()),
        _ => None,
    }
}

pub(crate) fn get_map<T: ReadTxn>(map: &MapRef, txn: &T, key: &str) -> Option<MapRef> {
    match map.get(txn, key) {
        Some(Out::YMap(value)) => Some(value),
        _ => None,
    }
}

pub(crate) fn get_array<T: ReadTxn>(map: &MapRef, txn: &T, key: &str) -> Option<ArrayRef> {
    match map.get(txn, key) {
        Some(Out::YArray(value)) => Some(value),
        _ => None,
    }
}

/// Raw ids of an order array (may hold duplicates and dangling ids).
pub(crate) fn raw_ids<T: ReadTxn>(txn: &T, array: &ArrayRef) -> Vec<String> {
    array
        .iter(txn)
        .filter_map(|value| match value {
            Out::Any(Any::String(id)) => Some(id.to_string()),
            _ => None,
        })
        .collect()
}

/// Effective order: first occurrence wins, ids without content are skipped. Yjs has no
/// move, so concurrent moves of one slide leave two copies of its id and a concurrent
/// delete + move leaves a dangling id; every replica resolves both the same way here
/// (spike rule, `prototype/src/model.rs::effective_order`).
pub(crate) fn effective_ids<T: ReadTxn>(
    txn: &T,
    array: &ArrayRef,
    content: &MapRef,
) -> Vec<String> {
    let mut seen = HashSet::new();
    raw_ids(txn, array)
        .into_iter()
        .filter(|id| matches!(content.get(txn, id), Some(Out::YMap(_))) && seen.insert(id.clone()))
        .collect()
}

/// Slide map and its element map / element order array.
pub(crate) struct SlideRefs {
    pub(crate) slide: MapRef,
    pub(crate) elements: MapRef,
    pub(crate) order: ArrayRef,
}

pub(crate) fn slide_refs<T: ReadTxn>(
    txn: &T,
    roots: &DeckRoots,
    slide_id: &str,
) -> Option<SlideRefs> {
    let slide = get_map(&roots.slides, txn, slide_id)?;
    Some(SlideRefs {
        elements: get_map(&slide, txn, KEY_ELEMENTS)?,
        order: get_array(&slide, txn, KEY_ELEMENT_ORDER)?,
        slide,
    })
}

// ------------------------------------------------------------------ writing

/// Writes a whole model into an empty document (hydration).
pub(crate) fn write_model(
    txn: &mut TransactionMut,
    roots: &DeckRoots,
    model: &DeckModel,
) -> Result<(), DeckError> {
    roots.meta.insert(txn, "title", model.title.clone());
    roots.meta.insert(txn, "aspect", model.aspect.as_str());
    roots.meta.insert(txn, "template", model.template.clone());
    for slide in &model.slides {
        let index = roots.order.len(txn);
        insert_slide(txn, roots, index, slide)?;
    }
    Ok(())
}

/// Inserts a slide with its elements at raw order position `index`.
///
/// # Errors
/// [`DeckError::InvalidValue`] when a text box holds markup outside the inline subset.
pub(crate) fn insert_slide(
    txn: &mut TransactionMut,
    roots: &DeckRoots,
    index: u32,
    slide: &SlideModel,
) -> Result<(), DeckError> {
    let map = roots
        .slides
        .insert(txn, slide.id.clone(), MapPrelim::default());
    set_optional(txn, &map, "layout", slide.layout.as_deref());
    set_optional(txn, &map, "transition", slide.transition.as_deref());
    if !slide.notes.is_empty() {
        map.insert(txn, "notes", slide.notes.clone());
    }
    let elements = map.insert(txn, KEY_ELEMENTS, MapPrelim::default());
    let order = map.insert(txn, KEY_ELEMENT_ORDER, ArrayPrelim::default());
    for element in &slide.elements {
        let at = order.len(txn);
        insert_element(txn, &elements, &order, at, element)?;
    }
    roots.order.insert(txn, index, slide.id.clone());
    Ok(())
}

/// Inserts an element map and its id at raw order position `index`.
///
/// # Errors
/// As [`write_content`].
pub(crate) fn insert_element(
    txn: &mut TransactionMut,
    elements: &MapRef,
    order: &ArrayRef,
    index: u32,
    element: &ElementModel,
) -> Result<(), DeckError> {
    let map = elements.insert(txn, element.id.clone(), MapPrelim::default());
    map.insert(txn, KEY_TYPE, element.kind.as_str());
    for (name, value) in element.all_attributes() {
        map.insert(txn, name, value);
    }
    write_content(txn, &map, &element.content)?;
    order.insert(txn, index, element.id.clone());
    Ok(())
}

/// Replaces an element's content. Each content value is one map entry, so a concurrent
/// replace of the same content resolves to one winner instead of a concatenation.
///
/// # Errors
/// [`DeckError::InvalidValue`] when rich text is not in the inline subset.
pub(crate) fn write_content(
    txn: &mut TransactionMut,
    map: &MapRef,
    content: &ElementContent,
) -> Result<(), DeckError> {
    match content {
        ElementContent::Empty => {}
        ElementContent::RichText(markup) => {
            let nodes =
                parse_inline(markup).map_err(|reason| DeckError::invalid("text", reason))?;
            map.insert(
                txn,
                KEY_BODY,
                XmlFragmentPrelim::new::<_, ()>(xml_nodes(&nodes)),
            );
        }
        ElementContent::Label(label) => {
            map.insert(txn, KEY_LABEL, label.clone());
        }
        ElementContent::Items(items) => {
            map.insert(txn, KEY_ITEMS, items_prelim(items));
        }
        ElementContent::Verbatim(code) => {
            map.insert(txn, KEY_CODE, code.clone());
        }
        ElementContent::Plain(text) => {
            if text.is_empty() {
                map.remove(txn, KEY_NOTE);
            } else {
                map.insert(txn, KEY_NOTE, text.clone());
            }
        }
    }
    Ok(())
}

pub(crate) fn item_prelim(item: &TodoItem) -> MapPrelim {
    MapPrelim::from_iter([
        ("text", In::Any(Any::from(item.text.clone()))),
        ("done", In::Any(Any::Bool(item.done))),
    ])
}

fn items_prelim(items: &[TodoItem]) -> ArrayPrelim {
    ArrayPrelim::from_iter(items.iter().map(item_prelim))
}

fn xml_nodes(nodes: &[InlineNode]) -> Vec<XmlIn> {
    nodes
        .iter()
        .map(|node| match node {
            InlineNode::Text(text) => XmlIn::from(XmlTextPrelim::new(text.as_str())),
            InlineNode::Break => XmlIn::from(XmlElementPrelim::empty("br")),
            InlineNode::Span { tag, children } => {
                XmlIn::from(XmlElementPrelim::new(*tag, xml_nodes(children)))
            }
        })
        .collect()
}

pub(crate) fn set_optional(txn: &mut TransactionMut, map: &MapRef, key: &str, value: Option<&str>) {
    match value {
        Some(value) => {
            map.insert(txn, key, value.to_string());
        }
        None => {
            map.remove(txn, key);
        }
    }
}

// ------------------------------------------------------------------ reading

/// Reads the whole deck. Every value passes the same cleaners as markup input, ids are
/// de-duplicated and boxes clamped, so the result always serialises to normalised markup
/// whatever a peer or mirror wrote.
pub(crate) fn read_model<T: ReadTxn>(txn: &T, roots: &DeckRoots) -> DeckModel {
    let aspect = get_string(&roots.meta, txn, "aspect")
        .and_then(|value| DeckAspect::parse(&value))
        .unwrap_or(DeckAspect::Wide);
    let template = get_string(&roots.meta, txn, "template")
        .filter(|value| is_valid_template(value))
        .unwrap_or_else(|| DEFAULT_TEMPLATE.to_string());
    let title = clean_title(&get_string(&roots.meta, txn, "title").unwrap_or_default());
    // Slide and element ids share one namespace in the markup; a later duplicate (only
    // possible after concurrent adds) is skipped deterministically.
    let mut seen = HashSet::new();
    let mut slides = Vec::new();
    for slide_id in effective_ids(txn, &roots.order, &roots.slides) {
        if !seen.insert(slide_id.clone()) {
            continue;
        }
        let Some(refs) = slide_refs(txn, roots, &slide_id) else {
            continue;
        };
        let mut elements = Vec::new();
        for element_id in effective_ids(txn, &refs.order, &refs.elements) {
            if !seen.insert(element_id.clone()) {
                continue;
            }
            if let Some(map) = get_map(&refs.elements, txn, &element_id)
                && let Some(element) = read_element(txn, &map, element_id, aspect)
            {
                elements.push(element);
            }
        }
        slides.push(SlideModel {
            id: slide_id,
            layout: get_string(&refs.slide, txn, "layout").and_then(|v| clean_layout(&v)),
            transition: get_string(&refs.slide, txn, "transition")
                .and_then(|v| clean_transition(&v)),
            notes: clean_notes(&get_string(&refs.slide, txn, "notes").unwrap_or_default()),
            elements,
        });
    }
    DeckModel {
        title,
        aspect,
        template,
        slides,
    }
}

fn read_element<T: ReadTxn>(
    txn: &T,
    map: &MapRef,
    id: String,
    aspect: DeckAspect,
) -> Option<ElementModel> {
    let kind = ElementKind::parse(&get_string(map, txn, KEY_TYPE)?)?;
    let mut attrs = BTreeMap::new();
    for name in kind.ordered_attributes() {
        if let Some(value) =
            get_string(map, txn, name).and_then(|raw| clean_attribute(kind, name, &raw))
        {
            attrs.insert(name.to_string(), value);
        }
    }
    clamp_box(&mut attrs, aspect.canvas_height());
    if let Some(required) = kind.required_attribute()
        && !attrs.contains_key(required)
    {
        return None;
    }
    let content = match kind {
        ElementKind::Text => ElementContent::RichText(match map.get(txn, KEY_BODY) {
            Some(Out::YXmlFragment(fragment)) => normalise_nodes(&read_inline(txn, &fragment)),
            _ => String::new(),
        }),
        ElementKind::Link => ElementContent::Label(clean_item_label(
            &get_string(map, txn, KEY_LABEL).unwrap_or_default(),
        )),
        ElementKind::Todo => ElementContent::Items(read_items(txn, map)),
        ElementKind::Block => {
            ElementContent::Verbatim(get_string(map, txn, KEY_CODE).unwrap_or_default())
        }
        ElementKind::Notepad => ElementContent::Plain(clean_note_text(
            &get_string(map, txn, KEY_NOTE).unwrap_or_default(),
        )),
        ElementKind::Image | ElementKind::Video | ElementKind::Shape => ElementContent::Empty,
    };
    Some(ElementModel::from_attributes(id, kind, attrs, content))
}

pub(crate) fn read_items<T: ReadTxn>(txn: &T, map: &MapRef) -> Vec<TodoItem> {
    let Some(items) = get_array(map, txn, KEY_ITEMS) else {
        return Vec::new();
    };
    items
        .iter(txn)
        .filter_map(|value| match value {
            Out::YMap(item) => Some(TodoItem {
                text: clean_item_label(&get_string(&item, txn, "text").unwrap_or_default()),
                done: matches!(item.get(txn, "done"), Some(Out::Any(Any::Bool(true)))),
            }),
            _ => None,
        })
        .collect()
}

/// Reads a text box fragment back into inline nodes. Elements other than the inline
/// tags (e.g. a paragraph a rich-text mirror wrapped around the text) are unwrapped,
/// like the backend normaliser unwraps unknown elements.
fn read_inline<T: ReadTxn, F: XmlFragment>(txn: &T, fragment: &F) -> Vec<InlineNode> {
    let mut nodes = Vec::new();
    for child in fragment.children(txn) {
        match child {
            XmlOut::Text(text) => {
                let value = text.get_string(txn);
                if !value.is_empty() {
                    nodes.push(InlineNode::Text(value));
                }
            }
            XmlOut::Element(element) => {
                let tag = element
                    .try_tag()
                    .map(|tag| tag.to_string())
                    .unwrap_or_default();
                if tag == "br" {
                    nodes.push(InlineNode::Break);
                } else if let Some(known) = INLINE_TAGS.iter().find(|known| **known == tag) {
                    nodes.push(InlineNode::Span {
                        tag: known,
                        children: read_inline(txn, &element),
                    });
                } else {
                    nodes.extend(read_inline(txn, &element));
                }
            }
            XmlOut::Fragment(inner) => nodes.extend(read_inline(txn, &inner)),
        }
    }
    nodes
}
