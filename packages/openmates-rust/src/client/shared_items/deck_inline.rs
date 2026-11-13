//! Rich text of slide text boxes: the inline subset `b i u s br ul ol li` plus escaped text.
//! Shared client core. Parses and writes the normalised form produced by `_rich_text` +
//! `_tidy_inline` in `backend/shared/python_utils/slides_markup.py`; the tree is what the
//! deck replica stores as a nested `Y.XmlFragment` (see `deck_store`).

use super::deck_values::{collapse_whitespace, escape_text, unescape};
use regex::Regex;
use std::sync::LazyLock;

/// Inline formatting tags; `br` is a separate void node.
pub(crate) const INLINE_TAGS: [&str; 7] = ["b", "i", "u", "s", "ul", "ol", "li"];

/// One node of a text box's content.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum InlineNode {
    /// Plain (unescaped) text.
    Text(String),
    /// `<br/>`.
    Break,
    /// A formatting element with children; `tag` is one of [`INLINE_TAGS`].
    Span {
        tag: &'static str,
        children: Vec<InlineNode>,
    },
}

/// Parses inline markup. `<br>` and `<br/>` are accepted; any other tag, an unclosed or
/// mismatched tag or an unknown character reference is refused with a short reason.
pub(crate) fn parse_inline(source: &str) -> Result<Vec<InlineNode>, &'static str> {
    let mut stack: Vec<(&'static str, Vec<InlineNode>)> = vec![("", Vec::new())];
    let mut rest = source;
    while !rest.is_empty() {
        let Some(index) = rest.find('<') else {
            push_text(&mut stack, rest)?;
            break;
        };
        push_text(&mut stack, &rest[..index])?;
        rest = &rest[index..];
        let end = rest.find('>').ok_or("unterminated tag")?;
        let tag = &rest[1..end];
        rest = &rest[end + 1..];
        if tag == "br" || tag == "br/" {
            current(&mut stack).push(InlineNode::Break);
        } else if let Some(name) = tag.strip_prefix('/') {
            let (open, children) = stack.pop().ok_or("unexpected closing tag")?;
            if open.is_empty() || open != name {
                return Err("mismatched closing tag");
            }
            current(&mut stack).push(InlineNode::Span {
                tag: open,
                children,
            });
        } else {
            let known = INLINE_TAGS
                .iter()
                .find(|known| **known == tag)
                .ok_or("tag not allowed in text")?;
            stack.push((known, Vec::new()));
        }
    }
    if stack.len() != 1 {
        return Err("unclosed tag");
    }
    Ok(stack.pop().map(|(_, nodes)| nodes).unwrap_or_default())
}

fn current<'a>(stack: &'a mut [(&'static str, Vec<InlineNode>)]) -> &'a mut Vec<InlineNode> {
    // The root frame is pushed first and only popped after the loop.
    &mut stack.last_mut().expect("root frame is always present").1
}

fn push_text(stack: &mut [(&'static str, Vec<InlineNode>)], raw: &str) -> Result<(), &'static str> {
    if raw.is_empty() {
        return Ok(());
    }
    let text = unescape(raw).ok_or("unknown character reference")?;
    current(stack).push(InlineNode::Text(text));
    Ok(())
}

/// Writes nodes as markup (`<br/>` for breaks, escaped text), without tidying.
pub(crate) fn serialise_inline(nodes: &[InlineNode]) -> String {
    let mut out = String::new();
    write_nodes(nodes, &mut out);
    out
}

fn write_nodes(nodes: &[InlineNode], out: &mut String) {
    for node in nodes {
        match node {
            InlineNode::Text(text) => out.push_str(&escape_text(text)),
            InlineNode::Break => out.push_str("<br/>"),
            InlineNode::Span { tag, children } => {
                out.push('<');
                out.push_str(tag);
                out.push('>');
                write_nodes(children, out);
                out.push_str("</");
                out.push_str(tag);
                out.push('>');
            }
        }
    }
}

static LIST_OPEN_SPACE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(<(?:ul|ol)>)\s+").expect("static pattern is valid"));
static LIST_CLOSE_SPACE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\s+(</(?:ul|ol)>)").expect("static pattern is valid"));
static ITEM_GAP_SPACE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(</li>)\s+(<li>)").expect("static pattern is valid"));

/// Normalised markup of a node tree: whitespace runs inside text become one space,
/// whitespace next to list tags and between items is removed, the result is trimmed
/// (`_rich_text` + `_tidy_inline`). Used for operation input and on every read so that
/// what a rich-text mirror typed is saved in normalised form.
pub(crate) fn normalise_nodes(nodes: &[InlineNode]) -> String {
    let collapsed = collapse_nodes(nodes);
    let markup = serialise_inline(&collapsed);
    let markup = LIST_OPEN_SPACE.replace_all(&markup, "$1");
    let markup = LIST_CLOSE_SPACE.replace_all(&markup, "$1");
    let markup = ITEM_GAP_SPACE.replace_all(&markup, "$1$2");
    markup.trim().to_string()
}

fn collapse_nodes(nodes: &[InlineNode]) -> Vec<InlineNode> {
    nodes
        .iter()
        .map(|node| match node {
            InlineNode::Text(text) => InlineNode::Text(collapse_whitespace(text)),
            InlineNode::Break => InlineNode::Break,
            InlineNode::Span { tag, children } => InlineNode::Span {
                tag,
                children: collapse_nodes(children),
            },
        })
        .collect()
}

/// Validates and normalises rich-text input of an operation.
pub(crate) fn normalise_inline(source: &str) -> Result<String, &'static str> {
    parse_inline(source).map(|nodes| normalise_nodes(&nodes))
}

/// One styled stretch of text of a flattened text box (see [`inline_runs`]).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InlineRun {
    /// Plain text; `"\n"` for a line break; list items carry their marker (`• `, `1. `).
    pub text: String,
    /// Bold.
    pub bold: bool,
    /// Italic.
    pub italic: bool,
    /// Underlined.
    pub underline: bool,
    /// Struck through.
    pub strike: bool,
}

/// Flattens normalised inline markup into styled runs for shells that draw attributed
/// text (lists become marker-prefixed lines). Markup the parser refuses yields a single
/// plain run of the unparsed source so nothing is silently lost.
pub fn inline_runs(source: &str) -> Vec<InlineRun> {
    let Ok(nodes) = parse_inline(source) else {
        return vec![InlineRun {
            text: source.to_string(),
            bold: false,
            italic: false,
            underline: false,
            strike: false,
        }];
    };
    let mut runs = Vec::new();
    flatten(&nodes, (false, false, false, false), None, &mut runs);
    runs
}

fn flatten(
    nodes: &[InlineNode],
    style: (bool, bool, bool, bool),
    list: Option<bool>,
    runs: &mut Vec<InlineRun>,
) {
    let mut item_index = 0usize;
    let push = |runs: &mut Vec<InlineRun>, text: String| {
        runs.push(InlineRun {
            text,
            bold: style.0,
            italic: style.1,
            underline: style.2,
            strike: style.3,
        });
    };
    for node in nodes {
        match node {
            InlineNode::Text(text) => push(runs, text.clone()),
            InlineNode::Break => push(runs, "\n".to_string()),
            InlineNode::Span { tag, children } => match *tag {
                "b" => flatten(children, (true, style.1, style.2, style.3), list, runs),
                "i" => flatten(children, (style.0, true, style.2, style.3), list, runs),
                "u" => flatten(children, (style.0, style.1, true, style.3), list, runs),
                "s" => flatten(children, (style.0, style.1, style.2, true), list, runs),
                "ul" => flatten(children, style, Some(false), runs),
                "ol" => flatten(children, style, Some(true), runs),
                _ => {
                    item_index += 1;
                    if !runs.is_empty() && runs.last().is_some_and(|run| run.text != "\n") {
                        push(runs, "\n".to_string());
                    }
                    let marker = if list == Some(true) {
                        format!("{item_index}. ")
                    } else {
                        "\u{2022} ".to_string()
                    };
                    push(runs, marker);
                    flatten(children, style, None, runs);
                }
            },
        }
    }
}
