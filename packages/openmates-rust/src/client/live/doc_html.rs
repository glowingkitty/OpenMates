//! Bounded HTML subset of the document embed's stored `html` content: `p`, `h1`-`h6`,
//! `ul`/`ol`/`li` and the inline `strong`/`b`, `em`/`i`, `code`, `a[href]`. Anything else
//! (blockquote, pre, table, hr, img, spans, line breaks, comments, unknown entities) is
//! kept verbatim as a [`Block::Raw`] and written back unchanged, never dropped.

/// One inline text run with its marks.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct Run {
    pub text: String,
    pub bold: bool,
    pub italic: bool,
    pub code: bool,
    pub link: Option<String>,
}

/// One block node of the document.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Block {
    Paragraph(Vec<Run>),
    Heading(u8, Vec<Run>),
    List {
        ordered: bool,
        items: Vec<Vec<Block>>,
    },
    /// Source HTML preserved verbatim.
    Raw(String),
}

enum Token {
    Open {
        tag: String,
        attrs: Vec<(String, String)>,
        start: usize,
        end: usize,
    },
    Close {
        tag: String,
        start: usize,
        end: usize,
    },
    Text {
        start: usize,
        end: usize,
    },
}

struct Node {
    tag: String,
    attrs: Vec<(String, String)>,
    children: Vec<Child>,
    start: usize,
    end: usize,
}

enum Child {
    Text(usize, usize),
    Node(Node),
}

const VOID: [&str; 6] = ["br", "hr", "img", "input", "meta", "link"];
const BLOCK_TAGS: [&str; 15] = [
    "p",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "pre",
    "table",
    "hr",
    "div",
    "li",
];

fn tokenize(src: &str) -> Vec<Token> {
    let bytes = src.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] != b'<' {
            let end = src[i..].find('<').map_or(src.len(), |p| i + p);
            out.push(Token::Text { start: i, end });
            i = end;
            continue;
        }
        if src[i..].starts_with("<!--") {
            let end = src[i..].find("-->").map_or(src.len(), |p| i + p + 3);
            out.push(Token::Open {
                tag: "!--".into(),
                attrs: vec![],
                start: i,
                end,
            });
            i = end;
            continue;
        }
        let Some(close) = tag_end(src, i) else {
            out.push(Token::Text {
                start: i,
                end: src.len(),
            });
            break;
        };
        let inner = &src[i + 1..close - 1];
        let closing = inner.starts_with('/');
        let body = inner.trim_start_matches('/').trim_end_matches('/');
        let name_end = body.find(char::is_whitespace).unwrap_or(body.len());
        let tag = body[..name_end].to_ascii_lowercase();
        if closing {
            out.push(Token::Close {
                tag,
                start: i,
                end: close,
            });
        } else {
            let attrs = parse_attrs(&body[name_end..]);
            out.push(Token::Open {
                tag,
                attrs,
                start: i,
                end: close,
            });
        }
        i = close;
    }
    out
}

/// Index just past the `>` that closes the tag starting at `start`, honouring quotes.
fn tag_end(src: &str, start: usize) -> Option<usize> {
    let mut quote: Option<u8> = None;
    for (offset, b) in src.as_bytes()[start..].iter().enumerate() {
        match (quote, *b) {
            (Some(q), c) if c == q => quote = None,
            (None, b'"' | b'\'') => quote = Some(*b),
            (None, b'>') => return Some(start + offset + 1),
            _ => {}
        }
    }
    None
}

fn parse_attrs(rest: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    let mut s = rest.trim_start();
    while !s.is_empty() {
        let name_end = s
            .find(|c: char| c == '=' || c.is_whitespace())
            .unwrap_or(s.len());
        let name = s[..name_end].to_ascii_lowercase();
        s = s[name_end..].trim_start();
        let mut value = String::new();
        if let Some(after) = s.strip_prefix('=') {
            let after = after.trim_start();
            let (v, remaining) = match after.chars().next() {
                Some(q @ ('"' | '\'')) => {
                    let body = &after[1..];
                    let end = body.find(q).unwrap_or(body.len());
                    (&body[..end], body.get(end + 1..).unwrap_or(""))
                }
                _ => {
                    let end = after.find(char::is_whitespace).unwrap_or(after.len());
                    (&after[..end], &after[end..])
                }
            };
            value = v.to_string();
            s = remaining;
        }
        if !name.is_empty() {
            out.push((name, value));
        }
        s = s.trim_start();
    }
    out
}

fn build(src: &str) -> Vec<Child> {
    let mut stack: Vec<Node> = vec![Node {
        tag: String::new(),
        attrs: vec![],
        children: vec![],
        start: 0,
        end: src.len(),
    }];
    let finish = |stack: &mut Vec<Node>, mut node: Node, end: usize| {
        node.end = end;
        if let Some(parent) = stack.last_mut() {
            parent.children.push(Child::Node(node));
        }
    };
    for token in tokenize(src) {
        match token {
            Token::Text { start, end } => {
                if let Some(top) = stack.last_mut() {
                    top.children.push(Child::Text(start, end));
                }
            }
            Token::Open {
                tag,
                attrs,
                start,
                end,
            } => {
                let node = Node {
                    tag: tag.clone(),
                    attrs,
                    children: vec![],
                    start,
                    end,
                };
                let self_closing = VOID.contains(&tag.as_str()) || tag == "!--";
                if self_closing {
                    finish(&mut stack, node, end);
                } else {
                    stack.push(node);
                }
            }
            Token::Close { tag, end, .. } => {
                if stack.iter().skip(1).any(|n| n.tag == tag) {
                    while let Some(node) = stack.pop() {
                        let matched = node.tag == tag;
                        finish(&mut stack, node, end);
                        if matched {
                            break;
                        }
                    }
                }
            }
        }
    }
    while stack.len() > 1 {
        if let Some(node) = stack.pop() {
            let end = src.len();
            finish(&mut stack, node, end);
        }
    }
    stack.pop().map(|n| n.children).unwrap_or_default()
}

/// Decodes the five entities the serializer knows; `None` for any other `&`.
fn decode(raw: &str) -> Option<String> {
    let mut out = String::new();
    let mut rest = raw;
    while let Some(p) = rest.find('&') {
        out.push_str(&rest[..p]);
        let tail = &rest[p..];
        let (ch, len) = [
            ("&amp;", '&'),
            ("&lt;", '<'),
            ("&gt;", '>'),
            ("&quot;", '"'),
            ("&#39;", '\''),
        ]
        .iter()
        .find(|(e, _)| tail.starts_with(e))
        .map(|(e, c)| (*c, e.len()))?;
        out.push(ch);
        rest = &tail[len..];
    }
    out.push_str(rest);
    Some(out)
}

fn inline(src: &str, children: &[Child], marks: &Run, out: &mut Vec<Run>) -> Option<()> {
    for child in children {
        match child {
            Child::Text(s, e) => {
                let text = decode(&src[*s..*e])?;
                if !text.is_empty() {
                    out.push(Run {
                        text,
                        ..marks.clone()
                    });
                }
            }
            Child::Node(n) => {
                let mut next = marks.clone();
                match n.tag.as_str() {
                    "strong" | "b" => next.bold = true,
                    "em" | "i" => next.italic = true,
                    "code" => next.code = true,
                    "a" if n.attrs.iter().all(|(k, _)| k == "href") => {
                        next.link = Some(decode(&n.attrs.iter().find(|(k, _)| k == "href")?.1)?);
                    }
                    _ => return None,
                }
                inline(src, &n.children, &next, out)?;
            }
        }
    }
    Some(())
}

fn runs(src: &str, children: &[Child]) -> Option<Vec<Run>> {
    let mut out = Vec::new();
    inline(src, children, &Run::default(), &mut out)?;
    Some(out)
}

fn raw(src: &str, node: &Node) -> Block {
    Block::Raw(src[node.start..node.end].to_string())
}

fn block(src: &str, node: &Node) -> Block {
    let plain = node.attrs.is_empty();
    match node.tag.as_str() {
        "p" if plain => runs(src, &node.children).map_or_else(|| raw(src, node), Block::Paragraph),
        "h1" | "h2" | "h3" | "h4" | "h5" | "h6" if plain => {
            let level = node.tag.as_bytes()[1] - b'0';
            runs(src, &node.children).map_or_else(|| raw(src, node), |r| Block::Heading(level, r))
        }
        "ul" | "ol" if plain => list(src, node),
        _ => raw(src, node),
    }
}

fn list(src: &str, node: &Node) -> Block {
    let mut items = Vec::new();
    for child in &node.children {
        match child {
            Child::Text(s, e) if src[*s..*e].trim().is_empty() => {}
            Child::Node(li) if li.tag == "li" && li.attrs.is_empty() => items.push(item(src, li)),
            _ => return raw(src, node),
        }
    }
    Block::List {
        ordered: node.tag == "ol",
        items,
    }
}

fn item(src: &str, li: &Node) -> Vec<Block> {
    let has_block = li
        .children
        .iter()
        .any(|c| matches!(c, Child::Node(n) if BLOCK_TAGS.contains(&n.tag.as_str())));
    if !has_block {
        return match runs(src, &li.children) {
            Some(r) => vec![Block::Paragraph(r)],
            None => vec![Block::Raw(src[li.start..li.end].to_string())],
        };
    }
    let mut blocks = Vec::new();
    let mut loose_start = 0;
    let flush = |from: usize, to: usize, blocks: &mut Vec<Block>| {
        let slice = &li.children[from..to];
        let only_space = slice
            .iter()
            .all(|c| matches!(c, Child::Text(s, e) if src[*s..*e].trim().is_empty()));
        if only_space {
            return;
        }
        match runs(src, slice) {
            Some(r) => blocks.push(Block::Paragraph(r)),
            None => {
                let (first, last) = (&slice[0], &slice[slice.len() - 1]);
                let begin = match first {
                    Child::Text(s, _) => *s,
                    Child::Node(n) => n.start,
                };
                let end = match last {
                    Child::Text(_, e) => *e,
                    Child::Node(n) => n.end,
                };
                blocks.push(Block::Raw(src[begin..end].to_string()));
            }
        }
    };
    for (index, child) in li.children.iter().enumerate() {
        if let Child::Node(n) = child {
            if BLOCK_TAGS.contains(&n.tag.as_str()) {
                flush(loose_start, index, &mut blocks);
                blocks.push(block(src, n));
                loose_start = index + 1;
            }
        }
    }
    flush(loose_start, li.children.len(), &mut blocks);
    blocks
}

/// Parses the stored HTML into blocks.
pub(crate) fn parse_blocks(html: &str) -> Vec<Block> {
    let mut blocks = Vec::new();
    for child in build(html) {
        match child {
            Child::Text(s, e) => {
                let raw_text = &html[s..e];
                if raw_text.trim().is_empty() {
                    continue;
                }
                match decode(raw_text.trim()) {
                    Some(text) => blocks.push(Block::Paragraph(vec![Run {
                        text,
                        ..Run::default()
                    }])),
                    None => blocks.push(Block::Raw(raw_text.trim().to_string())),
                }
            }
            Child::Node(n) => {
                blocks.push(block(html, &n));
            }
        }
    }
    blocks
}

fn escape_text(text: &str) -> String {
    text.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

fn escape_attr(text: &str) -> String {
    escape_text(text).replace('"', "&quot;")
}

fn run_html(run: &Run) -> String {
    let mut s = escape_text(&run.text);
    if run.code {
        s = format!("<code>{s}</code>");
    }
    if run.italic {
        s = format!("<em>{s}</em>");
    }
    if run.bold {
        s = format!("<strong>{s}</strong>");
    }
    if let Some(href) = &run.link {
        s = format!("<a href=\"{}\">{s}</a>", escape_attr(href));
    }
    s
}

fn runs_html(runs: &[Run]) -> String {
    runs.iter().map(run_html).collect()
}

fn item_html(blocks: &[Block]) -> String {
    if let [Block::Raw(raw)] = blocks {
        if raw.starts_with("<li") {
            return raw.clone();
        }
    }
    let flat = matches!(blocks.first(), Some(Block::Paragraph(_)))
        && blocks[1..].iter().all(|b| matches!(b, Block::List { .. }));
    let inner = if flat {
        let Block::Paragraph(r) = &blocks[0] else {
            return String::new();
        };
        format!(
            "{}{}",
            runs_html(r),
            blocks[1..].iter().map(block_html).collect::<String>()
        )
    } else {
        blocks.iter().map(block_html).collect()
    };
    format!("<li>{inner}</li>")
}

/// Serializes one block.
pub(crate) fn block_html(block: &Block) -> String {
    match block {
        Block::Paragraph(r) => format!("<p>{}</p>", runs_html(r)),
        Block::Heading(l, r) => format!("<h{l}>{}</h{l}>", runs_html(r)),
        Block::List { ordered, items } => {
            let tag = if *ordered { "ol" } else { "ul" };
            format!(
                "<{tag}>{}</{tag}>",
                items.iter().map(|i| item_html(i)).collect::<String>()
            )
        }
        Block::Raw(raw) => raw.clone(),
    }
}

/// Serializes blocks to the stored HTML (no whitespace between blocks).
pub(crate) fn blocks_html(blocks: &[Block]) -> String {
    blocks.iter().map(block_html).collect()
}
