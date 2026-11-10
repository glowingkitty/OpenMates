//! Applies typed deck operations to the `yrs` replica.
//! Shared client core (`live-collab.core.one-shared-model`). Each operation validates
//! against the slides whitelist first and then writes in the caller's single transaction,
//! so a refused operation changes nothing and an applied one is exactly one undo step.

use super::deck_error::DeckError;
use super::deck_inline::normalise_inline;
use super::deck_markup::{DeckModel, ElementContent, ElementModel, SlideModel, TodoItem};
use super::deck_operations::{DeckOperation, DeckOutcome, ElementSpec, TextStyle};
use super::deck_store::{
    DeckRoots, KEY_ITEMS, SlideRefs, get_array, get_map, insert_element, insert_slide, raw_ids,
    read_model, set_optional, slide_refs, write_content,
};
use super::deck_values::{
    ElementKind, GEOMETRY, MAX_ELEMENTS_PER_SLIDE, MAX_SLIDES, clamp_box, clean_attribute,
    clean_item_label, clean_label, clean_layout, clean_note_text, clean_notes,
};
use regex::Regex;
use std::collections::{BTreeMap, HashSet};
use std::sync::LazyLock;
use yrs::{Any, Array, ArrayRef, Map, MapRef, Out, ReadTxn, TransactionMut};

const TEXT_STYLE_FIELDS: [&str; 6] = ["role", "font", "size", "color", "align", "weight"];

static BLOCK_END: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)</block\s*>").expect("static pattern is valid"));

/// Applies one operation inside `txn` (validation first, then writes).
///
/// # Errors
/// Any [`DeckError`] except the update/markup variants; nothing is written then.
pub(crate) fn apply_operation(
    txn: &mut TransactionMut,
    roots: &DeckRoots,
    operation: DeckOperation,
) -> Result<DeckOutcome, DeckError> {
    let model = read_model(txn, roots);
    let ctx = Ctx {
        roots,
        model: &model,
    };
    match operation {
        DeckOperation::SetTextContent {
            slide_id,
            element_id,
            markup,
        } => {
            let element = ctx.element_of(&slide_id, &element_id, ElementKind::Text, "text")?;
            let markup = normalise_inline(&markup).map_err(|r| DeckError::invalid("markup", r))?;
            let content = ElementContent::RichText(markup);
            if element.content == content {
                return Ok(DeckOutcome::Unchanged);
            }
            let map = ctx.element_map(txn, &slide_id, &element_id)?;
            write_content(txn, &map, &content)?;
            Ok(DeckOutcome::Applied)
        }
        DeckOperation::SetTextStyle {
            slide_id,
            element_id,
            style,
        } => {
            let element = ctx.element_of(&slide_id, &element_id, ElementKind::Text, "text")?;
            let changes = text_style_changes(&style)?;
            let map = ctx.element_map(txn, &slide_id, &element_id)?;
            write_attributes(txn, &map, &element.attributes, changes)
        }
        DeckOperation::SetGeometry {
            slide_id,
            element_id,
            x,
            y,
            w,
            h,
        } => {
            let element = ctx.element(&slide_id, &element_id)?;
            let mut boxed = BTreeMap::new();
            for (name, value) in GEOMETRY.iter().zip([x, y, w, h]) {
                let clean = clean_attribute(element.kind, name, &value.to_string())
                    .ok_or_else(|| DeckError::invalid(name, "not a canvas coordinate"))?;
                boxed.insert((*name).to_string(), clean);
            }
            clamp_box(&mut boxed, model.aspect.canvas_height());
            let changes = boxed.into_iter().map(|(k, v)| (k, Some(v))).collect();
            let map = ctx.element_map(txn, &slide_id, &element_id)?;
            write_attributes(txn, &map, &element.all_attributes(), changes)
        }
        DeckOperation::SetImageSource {
            slide_id,
            element_id,
            src,
            alt,
        } => {
            let element = ctx.element_of(&slide_id, &element_id, ElementKind::Image, "image")?;
            let src = clean_attribute(ElementKind::Image, "src", &src)
                .ok_or_else(|| DeckError::invalid("src", "must be embed:<ref>"))?;
            let mut changes = vec![("src".to_string(), Some(src))];
            if let Some(alt) = alt {
                changes.push(("alt".to_string(), clean_label(&alt)));
            }
            let map = ctx.element_map(txn, &slide_id, &element_id)?;
            write_attributes(txn, &map, &element.attributes, changes)
        }
        DeckOperation::AddElement {
            slide_id,
            index,
            element,
        } => {
            let slide = ctx.slide(&slide_id)?;
            ensure_room(slide)?;
            let id = next_id(&model, "e", &HashSet::new());
            let element = element_from_spec(id.clone(), element, &model)?;
            let at = index.unwrap_or(slide.elements.len());
            ctx.insert_element_at(txn, &slide_id, at, &element)?;
            Ok(DeckOutcome::ElementCreated { element_id: id })
        }
        DeckOperation::DeleteElement {
            slide_id,
            element_id,
        } => {
            ctx.element(&slide_id, &element_id)?;
            let refs = ctx.refs(txn, &slide_id)?;
            refs.elements.remove(txn, &element_id);
            remove_id(txn, &refs.order, &element_id);
            Ok(DeckOutcome::Applied)
        }
        DeckOperation::DuplicateElement {
            slide_id,
            element_id,
        } => {
            let slide = ctx.slide(&slide_id)?;
            ensure_room(slide)?;
            let original = ctx.element(&slide_id, &element_id)?;
            let position = slide
                .elements
                .iter()
                .position(|e| e.id == element_id)
                .unwrap_or(slide.elements.len());
            let mut copy = original.clone();
            copy.id = next_id(&model, "e", &HashSet::new());
            ctx.insert_element_at(txn, &slide_id, position + 1, &copy)?;
            Ok(DeckOutcome::ElementCreated {
                element_id: copy.id,
            })
        }
        DeckOperation::AddSlide { index, layout } => {
            if model.slides.len() >= MAX_SLIDES {
                return Err(DeckError::LimitReached("200 slides per deck"));
            }
            let layout = layout
                .map(|raw| {
                    clean_layout(&raw)
                        .ok_or_else(|| DeckError::invalid("layout", "not a layout name"))
                })
                .transpose()?;
            let slide = SlideModel {
                id: next_id(&model, "s", &HashSet::new()),
                layout,
                transition: None,
                notes: String::new(),
                elements: Vec::new(),
            };
            let at = index.unwrap_or(model.slides.len());
            ctx.insert_slide_at(txn, at, &slide)?;
            Ok(DeckOutcome::SlideCreated { slide_id: slide.id })
        }
        DeckOperation::DuplicateSlide { slide_id } => {
            if model.slides.len() >= MAX_SLIDES {
                return Err(DeckError::LimitReached("200 slides per deck"));
            }
            let original = ctx.slide(&slide_id)?;
            let position = ctx.slide_position(&slide_id)?;
            let mut taken = HashSet::new();
            let mut copy = original.clone();
            copy.id = next_id(&model, "s", &taken);
            taken.insert(copy.id.clone());
            for element in &mut copy.elements {
                element.id = next_id(&model, "e", &taken);
                taken.insert(element.id.clone());
            }
            ctx.insert_slide_at(txn, position + 1, &copy)?;
            Ok(DeckOutcome::SlideCreated { slide_id: copy.id })
        }
        DeckOperation::DeleteSlide { slide_id } => {
            ctx.slide(&slide_id)?;
            if model.slides.len() <= 1 {
                return Err(DeckError::LastSlide);
            }
            roots.slides.remove(txn, &slide_id);
            remove_id(txn, &roots.order, &slide_id);
            Ok(DeckOutcome::Applied)
        }
        DeckOperation::MoveSlide { slide_id, to_index } => {
            let from = ctx.slide_position(&slide_id)?;
            let to = to_index.min(model.slides.len() - 1);
            if from == to {
                return Ok(DeckOutcome::Unchanged);
            }
            // Remove every copy of the id first (concurrent moves can leave several),
            // then insert before the slide that will follow it in the effective order.
            remove_id(txn, &roots.order, &slide_id);
            let index = raw_insert_index(txn, &roots.order, &roots.slides, to);
            roots.order.insert(txn, index, slide_id);
            Ok(DeckOutcome::Applied)
        }
        DeckOperation::SetSlideLayout { slide_id, layout } => {
            let slide = ctx.slide(&slide_id)?;
            let layout = layout
                .map(|raw| {
                    clean_layout(&raw)
                        .ok_or_else(|| DeckError::invalid("layout", "not a layout name"))
                })
                .transpose()?;
            if slide.layout == layout {
                return Ok(DeckOutcome::Unchanged);
            }
            let refs = ctx.refs(txn, &slide_id)?;
            set_optional(txn, &refs.slide, "layout", layout.as_deref());
            Ok(DeckOutcome::Applied)
        }
        DeckOperation::SetSpeakerNotes { slide_id, notes } => {
            let slide = ctx.slide(&slide_id)?;
            let notes = clean_notes(&notes);
            if slide.notes == notes {
                return Ok(DeckOutcome::Unchanged);
            }
            let refs = ctx.refs(txn, &slide_id)?;
            set_optional(
                txn,
                &refs.slide,
                "notes",
                (!notes.is_empty()).then_some(notes.as_str()),
            );
            Ok(DeckOutcome::Applied)
        }
        DeckOperation::SetNotepadText {
            slide_id,
            element_id,
            text,
        } => {
            let element =
                ctx.element_of(&slide_id, &element_id, ElementKind::Notepad, "notepad")?;
            let content = ElementContent::Plain(clean_note_text(&text));
            if element.content == content {
                return Ok(DeckOutcome::Unchanged);
            }
            let map = ctx.element_map(txn, &slide_id, &element_id)?;
            write_content(txn, &map, &content)?;
            Ok(DeckOutcome::Applied)
        }
        DeckOperation::SetTodoItems {
            slide_id,
            element_id,
            items,
        } => {
            let element = ctx.element_of(&slide_id, &element_id, ElementKind::Todo, "todo")?;
            let content = ElementContent::Items(clean_items(items));
            if element.content == content {
                return Ok(DeckOutcome::Unchanged);
            }
            let map = ctx.element_map(txn, &slide_id, &element_id)?;
            write_content(txn, &map, &content)?;
            Ok(DeckOutcome::Applied)
        }
        DeckOperation::SetTodoItemDone {
            slide_id,
            element_id,
            index,
            done,
        } => {
            let element = ctx.element_of(&slide_id, &element_id, ElementKind::Todo, "todo")?;
            let ElementContent::Items(items) = &element.content else {
                return Err(DeckError::ItemOutOfRange(index));
            };
            let item = items.get(index).ok_or(DeckError::ItemOutOfRange(index))?;
            if item.done == done {
                return Ok(DeckOutcome::Unchanged);
            }
            let map = ctx.element_map(txn, &slide_id, &element_id)?;
            let item_map = get_array(&map, txn, KEY_ITEMS)
                .and_then(
                    |items| match u32::try_from(index).ok().and_then(|i| items.get(txn, i)) {
                        Some(Out::YMap(item)) => Some(item),
                        _ => None,
                    },
                )
                .ok_or(DeckError::ItemOutOfRange(index))?;
            item_map.insert(txn, "done", Any::Bool(done));
            Ok(DeckOutcome::Applied)
        }
        DeckOperation::ClearInteractiveElement {
            slide_id,
            element_id,
        } => {
            let element = ctx.interactive(&slide_id, &element_id)?;
            if clear_element(txn, &ctx, &slide_id, element)? {
                Ok(DeckOutcome::Applied)
            } else {
                Ok(DeckOutcome::Unchanged)
            }
        }
        DeckOperation::ClearAllInteractive => {
            let mut cleared = 0;
            for slide in &model.slides {
                for element in slide.elements.iter().filter(|e| e.kind.is_interactive()) {
                    if clear_element(txn, &ctx, &slide.id, element)? {
                        cleared += 1;
                    }
                }
            }
            Ok(DeckOutcome::Cleared { elements: cleared })
        }
        DeckOperation::SetInteractiveHidden {
            slide_id,
            element_id,
            hidden,
        } => {
            let element = ctx.interactive(&slide_id, &element_id)?;
            if write_hidden(txn, &ctx, &slide_id, element, hidden)? {
                Ok(DeckOutcome::Applied)
            } else {
                Ok(DeckOutcome::Unchanged)
            }
        }
        DeckOperation::SetAllInteractiveHidden { hidden } => {
            let mut changed = false;
            for slide in &model.slides {
                for element in slide.elements.iter().filter(|e| e.kind.is_interactive()) {
                    changed |= write_hidden(txn, &ctx, &slide.id, element, hidden)?;
                }
            }
            Ok(if changed {
                DeckOutcome::Applied
            } else {
                DeckOutcome::Unchanged
            })
        }
    }
}

/// Read-side context of one operation: the model as it was when the operation started.
struct Ctx<'a> {
    roots: &'a DeckRoots,
    model: &'a DeckModel,
}

impl Ctx<'_> {
    fn slide(&self, slide_id: &str) -> Result<&SlideModel, DeckError> {
        self.model
            .slides
            .iter()
            .find(|s| s.id == slide_id)
            .ok_or_else(|| DeckError::SlideNotFound(slide_id.to_string()))
    }

    fn slide_position(&self, slide_id: &str) -> Result<usize, DeckError> {
        self.model
            .slides
            .iter()
            .position(|s| s.id == slide_id)
            .ok_or_else(|| DeckError::SlideNotFound(slide_id.to_string()))
    }

    fn element(&self, slide_id: &str, element_id: &str) -> Result<&ElementModel, DeckError> {
        self.slide(slide_id)?
            .elements
            .iter()
            .find(|e| e.id == element_id)
            .ok_or_else(|| DeckError::ElementNotFound(element_id.to_string()))
    }

    fn element_of(
        &self,
        slide_id: &str,
        element_id: &str,
        kind: ElementKind,
        expected: &'static str,
    ) -> Result<&ElementModel, DeckError> {
        let element = self.element(slide_id, element_id)?;
        if element.kind != kind {
            return Err(DeckError::WrongElementKind {
                element_id: element_id.to_string(),
                expected,
            });
        }
        Ok(element)
    }

    fn interactive(&self, slide_id: &str, element_id: &str) -> Result<&ElementModel, DeckError> {
        let element = self.element(slide_id, element_id)?;
        if !element.kind.is_interactive() {
            return Err(DeckError::WrongElementKind {
                element_id: element_id.to_string(),
                expected: "notepad or todo",
            });
        }
        Ok(element)
    }

    fn refs<T: ReadTxn>(&self, txn: &T, slide_id: &str) -> Result<SlideRefs, DeckError> {
        slide_refs(txn, self.roots, slide_id)
            .ok_or_else(|| DeckError::SlideNotFound(slide_id.to_string()))
    }

    fn element_map<T: ReadTxn>(
        &self,
        txn: &T,
        slide_id: &str,
        element_id: &str,
    ) -> Result<MapRef, DeckError> {
        let refs = self.refs(txn, slide_id)?;
        get_map(&refs.elements, txn, element_id)
            .ok_or_else(|| DeckError::ElementNotFound(element_id.to_string()))
    }

    fn insert_element_at(
        &self,
        txn: &mut TransactionMut,
        slide_id: &str,
        position: usize,
        element: &ElementModel,
    ) -> Result<(), DeckError> {
        let refs = self.refs(txn, slide_id)?;
        let index = raw_insert_index(txn, &refs.order, &refs.elements, position);
        insert_element(txn, &refs.elements, &refs.order, index, element)
    }

    fn insert_slide_at(
        &self,
        txn: &mut TransactionMut,
        position: usize,
        slide: &SlideModel,
    ) -> Result<(), DeckError> {
        let index = raw_insert_index(txn, &self.roots.order, &self.roots.slides, position);
        insert_slide(txn, self.roots, index, slide)
    }
}

/// Raw array index that puts a new id at `position` of the effective order.
fn raw_insert_index<T: ReadTxn>(
    txn: &T,
    order: &ArrayRef,
    content: &MapRef,
    position: usize,
) -> u32 {
    let mut seen = HashSet::new();
    let mut effective_positions: Vec<u32> = Vec::new();
    for (raw, id) in (0u32..).zip(raw_ids(txn, order)) {
        if matches!(content.get(txn, &id), Some(Out::YMap(_))) && seen.insert(id) {
            effective_positions.push(raw);
        }
    }
    effective_positions
        .get(position)
        .copied()
        .unwrap_or_else(|| order.len(txn))
}

/// Removes every occurrence of `id` from an order array (back to front keeps indices valid).
fn remove_id(txn: &mut TransactionMut, order: &ArrayRef, id: &str) {
    let positions: Vec<u32> = (0u32..)
        .zip(raw_ids(txn, order))
        .filter(|(_, candidate)| candidate == id)
        .map(|(index, _)| index)
        .collect();
    for index in positions.into_iter().rev() {
        order.remove(txn, index);
    }
}

/// Next free `<prefix><n>` id: one above the highest number in use, also skipping ids
/// already handed out in this operation. Slide and element ids share one namespace.
fn next_id(model: &DeckModel, prefix: &str, taken: &HashSet<String>) -> String {
    let used = model
        .slides
        .iter()
        .flat_map(|s| std::iter::once(&s.id).chain(s.elements.iter().map(|e| &e.id)))
        .chain(taken.iter());
    let highest = used
        .filter_map(|id| id.strip_prefix(prefix)?.parse::<u64>().ok())
        .max()
        .unwrap_or(0);
    format!("{prefix}{}", highest + 1)
}

fn ensure_room(slide: &SlideModel) -> Result<(), DeckError> {
    if slide.elements.len() >= MAX_ELEMENTS_PER_SLIDE {
        return Err(DeckError::LimitReached("200 elements per slide"));
    }
    Ok(())
}

fn text_style_changes(style: &TextStyle) -> Result<Vec<(String, Option<String>)>, DeckError> {
    let mut changes = Vec::new();
    let size = style.size.map(|size| size.to_string());
    for (name, value) in [
        ("font", style.font.as_ref()),
        ("size", size.as_ref()),
        ("color", style.color.as_ref()),
        ("align", style.align.as_ref()),
        ("weight", style.weight.as_ref()),
    ] {
        if let Some(raw) = value {
            let clean = clean_attribute(ElementKind::Text, name, raw)
                .ok_or_else(|| DeckError::invalid(name, "value not allowed"))?;
            changes.push((name.to_string(), Some(clean)));
        }
    }
    for name in &style.remove {
        if !TEXT_STYLE_FIELDS.contains(&name.as_str()) {
            return Err(DeckError::UnknownAttribute(name.clone()));
        }
        changes.push((name.clone(), None));
    }
    Ok(changes)
}

/// Writes only the attributes that differ from `current`.
fn write_attributes(
    txn: &mut TransactionMut,
    map: &MapRef,
    current: &BTreeMap<String, String>,
    changes: Vec<(String, Option<String>)>,
) -> Result<DeckOutcome, DeckError> {
    let mut changed = false;
    for (name, value) in changes {
        if current.get(&name) == value.as_ref() {
            continue;
        }
        changed = true;
        set_optional(txn, map, &name, value.as_deref());
    }
    Ok(if changed {
        DeckOutcome::Applied
    } else {
        DeckOutcome::Unchanged
    })
}

fn clean_items(items: Vec<TodoItem>) -> Vec<TodoItem> {
    items
        .into_iter()
        .map(|item| TodoItem {
            text: clean_item_label(&item.text),
            done: item.done,
        })
        .collect()
}

/// Sets or clears the `hidden` attribute of a notepad or to-do element; `false` when it
/// already had that state.
fn write_hidden(
    txn: &mut TransactionMut,
    ctx: &Ctx<'_>,
    slide_id: &str,
    element: &ElementModel,
    hidden: bool,
) -> Result<bool, DeckError> {
    if element.attributes.contains_key("hidden") == hidden {
        return Ok(false);
    }
    let map = ctx.element_map(txn, slide_id, &element.id)?;
    set_optional(txn, &map, "hidden", hidden.then_some("true"));
    Ok(true)
}

/// Empties a notepad or to-do element; `false` when there was nothing to clear.
fn clear_element(
    txn: &mut TransactionMut,
    ctx: &Ctx<'_>,
    slide_id: &str,
    element: &ElementModel,
) -> Result<bool, DeckError> {
    match &element.content {
        ElementContent::Items(items) if !items.is_empty() => {
            let map = ctx.element_map(txn, slide_id, &element.id)?;
            write_content(txn, &map, &ElementContent::Items(Vec::new()))?;
            Ok(true)
        }
        ElementContent::Plain(text) if !text.is_empty() => {
            let map = ctx.element_map(txn, slide_id, &element.id)?;
            write_content(txn, &map, &ElementContent::Plain(String::new()))?;
            Ok(true)
        }
        _ => Ok(false),
    }
}

/// Validates an [`ElementSpec`] with the markup whitelist and builds the element.
fn element_from_spec(
    id: String,
    spec: ElementSpec,
    model: &DeckModel,
) -> Result<ElementModel, DeckError> {
    let kind = spec.kind;
    let mut attrs = BTreeMap::new();
    let geometry = GEOMETRY.iter().zip([spec.x, spec.y, spec.w, spec.h]);
    let given = geometry
        .filter_map(|(name, value)| value.map(|v| ((*name).to_string(), v.to_string())))
        .chain(spec.attributes);
    for (name, raw) in given {
        if name == "id" || !kind.accepts(&name) {
            return Err(DeckError::UnknownAttribute(name));
        }
        let clean = clean_attribute(kind, &name, &raw)
            .ok_or_else(|| DeckError::invalid(&name, "value not allowed"))?;
        attrs.insert(name, clean);
    }
    clamp_box(&mut attrs, model.aspect.canvas_height());
    if let Some(required) = kind.required_attribute()
        && !attrs.contains_key(required)
    {
        return Err(DeckError::invalid(required, "required for this element"));
    }
    let content = match (kind, spec.content) {
        (ElementKind::Text, ElementContent::RichText(markup)) => ElementContent::RichText(
            normalise_inline(&markup).map_err(|r| DeckError::invalid("content", r))?,
        ),
        (ElementKind::Text, ElementContent::Empty) => ElementContent::RichText(String::new()),
        (ElementKind::Link, ElementContent::Label(label)) => {
            ElementContent::Label(clean_item_label(&label))
        }
        (ElementKind::Todo, ElementContent::Items(items)) => {
            ElementContent::Items(clean_items(items))
        }
        (ElementKind::Todo, ElementContent::Empty) => ElementContent::Items(Vec::new()),
        (ElementKind::Block, ElementContent::Verbatim(code)) => {
            if BLOCK_END.is_match(&code) {
                return Err(DeckError::invalid(
                    "content",
                    "block code contains </block>",
                ));
            }
            ElementContent::Verbatim(code.replace("\r\n", "\n").replace('\r', "\n"))
        }
        (ElementKind::Block, ElementContent::Empty) => ElementContent::Verbatim(String::new()),
        (ElementKind::Notepad, ElementContent::Plain(text)) => {
            ElementContent::Plain(clean_note_text(&text))
        }
        (ElementKind::Notepad, ElementContent::Empty) => ElementContent::Plain(String::new()),
        (ElementKind::Image | ElementKind::Video | ElementKind::Shape, ElementContent::Empty) => {
            ElementContent::Empty
        }
        _ => {
            return Err(DeckError::invalid(
                "content",
                "content does not match the element kind",
            ));
        }
    };
    Ok(ElementModel::from_attributes(id, kind, attrs, content))
}
