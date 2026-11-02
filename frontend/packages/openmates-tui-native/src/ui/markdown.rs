//! Markdown is parsed and laid out in Rust. Input ANSI/control bytes are never interpreted.
use super::{ACCENT, MUTED, TEXT};
use pulldown_cmark::{CodeBlockKind, Event, Options, Parser, Tag, TagEnd};
use ratatui::style::{Color, Modifier, Style};
use serde_json::Value;
use unicode_segmentation::UnicodeSegmentation;
use unicode_width::UnicodeWidthStr;

#[derive(Clone, PartialEq)]
pub(super) enum Link {
    Url(String),
    Embed(String),
    Wiki(String),
    Question(Value),
    Node(usize),
    Skill {
        app: String,
        skill: String,
    },
    Run(Value),
    ProjectFile {
        project: String,
        embed: String,
        name: String,
    },
    Carousel {
        message: String,
        delta: i32,
    },
}
#[derive(Clone)]
pub(super) struct Part {
    pub text: String,
    pub style: Style,
    pub link: Option<Link>,
}
pub(super) type Row = Vec<Part>;
pub(super) fn clean(text: &str) -> String {
    text.chars()
        .filter(|c| !c.is_control() || *c == '\n' || *c == '\t')
        .collect()
}
pub(super) fn plain(text: impl Into<String>) -> Row {
    vec![Part {
        text: clean(&text.into()),
        style: Style::default().fg(TEXT),
        link: None,
    }]
}
pub(super) fn styled(text: impl Into<String>, style: Style) -> Row {
    vec![Part {
        text: clean(&text.into()),
        style,
        link: None,
    }]
}
fn flush(out: &mut Vec<Row>, row: &mut Row) {
    if !row.is_empty() {
        out.push(std::mem::take(row));
    }
}
fn push(row: &mut Row, text: &str, style: Style, link: Option<Link>) {
    if !text.is_empty() {
        row.push(Part {
            text: clean(text),
            style,
            link,
        });
    }
}
pub(super) fn render(source: &str, width: usize) -> Vec<Row> {
    let source = clean(source);
    let mut out = vec![];
    let mut row = vec![];
    let mut bold = 0;
    let mut italic = 0;
    let mut strike = 0;
    let mut heading = false;
    let mut link: Option<Link> = None;
    let mut code = false;
    let mut language = String::new();
    let mut body = String::new();
    let mut lists: Vec<Option<u64>> = vec![];
    let mut quote = 0usize;
    for event in Parser::new_ext(
        &source,
        Options::ENABLE_TABLES | Options::ENABLE_STRIKETHROUGH | Options::ENABLE_TASKLISTS,
    ) {
        let mut style = Style::default().fg(TEXT);
        if bold > 0 || heading {
            style = style.add_modifier(Modifier::BOLD);
        }
        if heading {
            style = style.fg(ACCENT);
        }
        if italic > 0 {
            style = style.add_modifier(Modifier::ITALIC);
        }
        if strike > 0 {
            style = style.add_modifier(Modifier::CROSSED_OUT);
        }
        if link.is_some() {
            style = style
                .fg(Color::Rgb(128, 202, 255))
                .add_modifier(Modifier::UNDERLINED);
        }
        match event {
            Event::Start(Tag::Strong) => bold += 1,
            Event::End(TagEnd::Strong) => bold -= 1,
            Event::Start(Tag::Emphasis) => italic += 1,
            Event::End(TagEnd::Emphasis) => italic -= 1,
            Event::Start(Tag::Strikethrough) => strike += 1,
            Event::End(TagEnd::Strikethrough) => strike -= 1,
            Event::Start(Tag::Heading { .. }) => {
                flush(&mut out, &mut row);
                heading = true;
            }
            Event::End(TagEnd::Heading(_)) => {
                flush(&mut out, &mut row);
                heading = false;
                out.push(vec![]);
            }
            Event::Start(Tag::Paragraph) => {
                if quote > 0 {
                    push(
                        &mut row,
                        &format!("{}│ ", "  ".repeat(quote - 1)),
                        Style::default().fg(MUTED),
                        None,
                    );
                }
            }
            Event::End(TagEnd::Paragraph) => {
                flush(&mut out, &mut row);
                out.push(vec![]);
            }
            Event::Start(Tag::BlockQuote(_)) => {
                quote += 1;
            }
            Event::End(TagEnd::BlockQuote(_)) => {
                flush(&mut out, &mut row);
                quote = quote.saturating_sub(1);
            }
            Event::Start(Tag::List(start)) => {
                flush(&mut out, &mut row);
                lists.push(start);
            }
            Event::End(TagEnd::List(_)) => {
                flush(&mut out, &mut row);
                lists.pop();
            }
            Event::Start(Tag::Item) => {
                flush(&mut out, &mut row);
                let prefix = match lists.last_mut() {
                    Some(Some(n)) => {
                        let value = format!("{n}. ");
                        *n += 1;
                        value
                    }
                    _ => "• ".into(),
                };
                push(
                    &mut row,
                    &format!("{}{prefix}", "  ".repeat(lists.len().saturating_sub(1))),
                    style,
                    None,
                );
            }
            Event::End(TagEnd::Item) => flush(&mut out, &mut row),
            Event::Start(Tag::CodeBlock(kind)) => {
                flush(&mut out, &mut row);
                code = true;
                body.clear();
                language = match kind {
                    CodeBlockKind::Fenced(l) => l.to_string(),
                    _ => String::new(),
                };
            }
            Event::End(TagEnd::CodeBlock) => {
                if language == "interactive_question" {
                    if let Ok(question) = serde_json::from_str::<Value>(&body) {
                        let title = question
                            .get("question")
                            .or_else(|| question.get("title"))
                            .and_then(Value::as_str)
                            .unwrap_or("Interactive question");
                        out.push(vec![Part {
                            text: format!("? {title}  [Answer]"),
                            style: Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
                            link: Some(Link::Question(question)),
                        }]);
                    } else {
                        out.push(plain("Question unavailable: invalid question data"));
                    }
                } else if language == "results-view" {
                    out.push(styled(
                        "Results · text view",
                        Style::default().fg(ACCENT).bold(),
                    ));
                    for l in body.lines() {
                        out.push(plain(l));
                    }
                } else {
                    out.push(styled(
                        format!(
                            "╭─ {}",
                            if language.is_empty() {
                                "Code"
                            } else {
                                &language
                            }
                        ),
                        Style::default().fg(MUTED),
                    ));
                    for l in body.lines() {
                        out.push(styled(
                            format!("│ {l}"),
                            Style::default().fg(Color::Rgb(192, 192, 192)),
                        ));
                    }
                    out.push(styled("╰─", Style::default().fg(MUTED)));
                }
                code = false;
                body.clear();
            }
            Event::Text(text) if code => body.push_str(&text),
            Event::Text(text) => push(&mut row, &text, style, link.clone()),
            Event::Code(text) => push(
                &mut row,
                &text,
                style
                    .fg(Color::Rgb(192, 192, 192))
                    .bg(Color::Rgb(37, 37, 37)),
                link.clone(),
            ),
            // The existing terminal client preserves source line breaks.
            // Joining them changes both the displayed text and scroll distance.
            Event::SoftBreak => flush(&mut out, &mut row),
            Event::HardBreak => flush(&mut out, &mut row),
            Event::Rule => {
                flush(&mut out, &mut row);
                out.push(styled(
                    "─".repeat(width.min(64)),
                    Style::default().fg(MUTED),
                ));
            }
            Event::Start(Tag::Link { dest_url, .. })
            | Event::Start(Tag::Image { dest_url, .. }) => {
                link = if let Some(id) = dest_url.strip_prefix("embed:") {
                    Some(Link::Embed(id.into()))
                } else if let Some(id) = dest_url.strip_prefix("wiki:") {
                    Some(Link::Wiki(id.into()))
                } else if dest_url.starts_with("https://") || dest_url.starts_with("http://") {
                    Some(Link::Url(dest_url.into_string()))
                } else {
                    None
                };
            }
            Event::End(TagEnd::Link) | Event::End(TagEnd::Image) => {
                if let Some(target) = &link {
                    let command = match target {
                        Link::Embed(id) => format!(" (/embed {id})"),
                        Link::Wiki(id) => format!(" (/wiki {id})"),
                        _ => String::new(),
                    };
                    push(&mut row, &command, Style::default().fg(MUTED), link.clone());
                }
                link = None;
            }
            Event::Start(Tag::Table(_)) => {
                flush(&mut out, &mut row);
            }
            Event::Start(Tag::TableHead) => {
                bold += 1;
            }
            Event::End(TagEnd::TableHead) => {
                flush(&mut out, &mut row);
                bold -= 1;
                out.push(styled(
                    "─".repeat(width.min(64)),
                    Style::default().fg(MUTED),
                ));
            }
            Event::End(TagEnd::TableRow) => flush(&mut out, &mut row),
            Event::End(TagEnd::TableCell) => {
                push(&mut row, " │ ", Style::default().fg(MUTED), None)
            }
            Event::TaskListMarker(done) => {
                push(&mut row, if done { "☑ " } else { "☐ " }, style, None)
            }
            Event::Html(text) | Event::InlineHtml(text) => {
                push(&mut row, &text, Style::default().fg(MUTED), None)
            }
            Event::FootnoteReference(text) => push(&mut row, &format!("[{text}]"), style, None),
            _ => {}
        }
    }
    flush(&mut out, &mut row);
    while out.last().is_some_and(Vec::is_empty) {
        out.pop();
    }
    out.into_iter().flat_map(|row| wrap(row, width)).collect()
}
pub(super) fn wrap(row: Row, width: usize) -> Vec<Row> {
    let width = width.max(1);
    let mut out = vec![];
    let mut current: Row = vec![];
    let mut col = 0;
    for part in row {
        // Printable ASCII has one byte, one grapheme and one cell per character.
        // Copy whole row-sized spans; retain Unicode/tab/newline behavior below.
        if part.text.bytes().all(|byte| (b' '..=b'~').contains(&byte)) {
            let mut start = 0;
            while start < part.text.len() {
                if col == width {
                    out.push(std::mem::take(&mut current));
                    col = 0;
                }
                let end = (start + width - col).min(part.text.len());
                let text = &part.text[start..end];
                if let Some(last) = current
                    .last_mut()
                    .filter(|p| p.style == part.style && p.link == part.link)
                {
                    last.text.push_str(text);
                } else {
                    current.push(Part {
                        text: text.into(),
                        style: part.style,
                        link: part.link.clone(),
                    });
                }
                col += end - start;
                start = end;
            }
            continue;
        }
        // Measure each original grapheme independently, then emit contiguous
        // slices once per line. Whole-string widths can differ for contextual
        // Unicode sequences, so only emission (never width calculation) batches.
        let emit = |current: &mut Row, text: &str| {
            if text.is_empty() {
                return;
            }
            if let Some(last) = current
                .last_mut()
                .filter(|p| p.style == part.style && p.link == part.link)
            {
                last.text.push_str(text);
            } else {
                current.push(Part {
                    text: text.into(),
                    style: part.style,
                    link: part.link.clone(),
                });
            }
        };
        let mut start = 0;
        let mut offset = 0;
        for g in part.text.graphemes(true) {
            let value = if g == "\t" { "    " } else { g };
            let cells = value.width();
            if g == "\n" || (col > 0 && col + cells > width) {
                emit(&mut current, &part.text[start..offset]);
                start = offset;
                out.push(std::mem::take(&mut current));
                col = 0;
            }
            offset += g.len();
            if g == "\n" {
                start = offset;
                continue;
            }
            if g == "\t" || cells > width {
                emit(&mut current, &part.text[start..offset - g.len()]);
                let value = if cells > width { "�" } else { value };
                emit(&mut current, value);
                start = offset;
                col += if cells > width { 1 } else { cells };
            } else {
                col += cells;
            }
        }
        emit(&mut current, &part.text[start..]);
    }
    if !current.is_empty() || out.is_empty() {
        out.push(current);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    fn legacy_wrap(row: Row, width: usize) -> Vec<Row> {
        let width = width.max(1);
        let mut out = vec![];
        let mut current: Row = vec![];
        let mut col = 0;
        for part in row {
            for g in part.text.graphemes(true) {
                let value = if g == "\t" { "    " } else { g };
                let cells = value.width();
                if g == "\n" || (col > 0 && col + cells > width) {
                    out.push(std::mem::take(&mut current));
                    col = 0;
                }
                if g == "\n" {
                    continue;
                }
                let value = if cells > width { "�" } else { value };
                if let Some(last) = current
                    .last_mut()
                    .filter(|p| p.style == part.style && p.link == part.link)
                {
                    last.text.push_str(value);
                } else {
                    current.push(Part {
                        text: value.into(),
                        style: part.style,
                        link: part.link.clone(),
                    });
                }
                col += value.width();
            }
        }
        if !current.is_empty() || out.is_empty() {
            out.push(current);
        }
        out
    }

    // contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned,terminal-pointer.viewport-coherent,cli.migration.complete-compatible
    #[test]
    fn unicode_span_layout_matches_per_grapheme_reference() {
        let texts = [
            "", "界界a界", "👩‍💻👨‍👩‍👧‍👦🇩🇪👍🏽", "a\u{301}b\u{301}",
            "\u{301}\u{200b}\u{200d}", "لا العربية", "क्‍ष हिन्दी", "\r\n\n\t界\t",
            "a\u{1b}[31m界\u{7}b", "界\n\n👩‍💻", "abc界def", "\u{fe0f}a\u{2060}",
            "☀︎☀️🏴‍☠️", "각㍿", "\t\t\t", "尾", 
        ];
        let links = [None, Some(Link::Url("https://example.test".into())), Some(Link::Embed("result".into()))];
        for width in [0, 1, 2, 3, 4, 7, 9, 80] {
            for first in texts {
                for second in texts {
                    for (index, link) in links.iter().enumerate() {
                        let row = vec![
                            Part { text: first.into(), style: Style::default().fg(TEXT), link: link.clone() },
                            Part { text: second.into(), style: Style::default().fg(TEXT), link: links[(index + 1) % links.len()].clone() },
                            Part { text: first.into(), style: Style::default().fg(MUTED).add_modifier(Modifier::BOLD), link: link.clone() },
                            Part { text: second.into(), style: Style::default().fg(MUTED).add_modifier(Modifier::BOLD), link: link.clone() },
                        ];
                        let expected = legacy_wrap(row.clone(), width);
                        let actual = wrap(row, width);
                        assert_eq!(actual.len(), expected.len(), "rows: width={width}, first={first:?}, second={second:?}, link={index}");
                        for (actual, expected) in actual.iter().zip(&expected) {
                            assert_eq!(actual.len(), expected.len(), "parts: width={width}, first={first:?}, second={second:?}, link={index}");
                            for (actual, expected) in actual.iter().zip(expected) {
                                assert_eq!(actual.text, expected.text);
                                assert_eq!(actual.style, expected.style);
                                assert!(actual.link == expected.link);
                            }
                        }
                    }
                }
            }
        }
    }

    // contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned,terminal-pointer.viewport-coherent,cli.migration.complete-compatible
    #[test]
    fn ascii_span_layout_preserves_legacy_rows_styles_and_actions() {
        let texts = ["", "ascii words repeated across rows", "a\tb\nc", "界a", "a\u{301}b", "👩‍💻 hello", "\r\n", "\u{1b}text", "tail"];
        for width in [0, 1, 2, 4, 9, 80] {
            for first in texts {
                for second in texts {
                    let row = vec![
                        Part { text: first.into(), style: Style::default().fg(TEXT), link: Some(Link::Url("https://example.test".into())) },
                        Part { text: second.into(), style: Style::default().fg(TEXT), link: Some(Link::Url("https://example.test".into())) },
                        Part { text: " styled suffix".into(), style: Style::default().fg(MUTED).add_modifier(Modifier::BOLD), link: Some(Link::Embed("result".into())) },
                    ];
                    let expected = legacy_wrap(row.clone(), width);
                    let actual = wrap(row, width);
                    assert_eq!(actual.len(), expected.len(), "row count: width={width}, first={first:?}, second={second:?}");
                    for (actual, expected) in actual.iter().zip(&expected) {
                        assert_eq!(actual.len(), expected.len(), "part count: width={width}");
                        for (actual, expected) in actual.iter().zip(expected) {
                            assert_eq!(actual.text, expected.text);
                            assert_eq!(actual.style, expected.style);
                            assert!(actual.link == expected.link);
                        }
                    }
                }
            }
        }
    }

    // contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned,cli.migration.complete-compatible
    #[test]
    fn source_line_breaks_preserve_rows_styles_and_link_actions() {
        let rows = render("alpha\n**beta** [link](https://openmates.org)", 80);
        let lines: Vec<String> = rows
            .iter()
            .map(|row| row.iter().map(|part| part.text.as_str()).collect())
            .collect();
        assert_eq!(lines, ["alpha", "beta link"]);
        assert!(rows[1].iter().any(|part| {
            part.text == "beta" && part.style.add_modifier.contains(Modifier::BOLD)
        }));
        assert!(rows[1].iter().any(|part| {
            part.text == "link"
                && matches!(&part.link, Some(Link::Url(url)) if url == "https://openmates.org")
        }));
    }
    // contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned,terminal-pointer.viewport-coherent,cli.migration.complete-compatible
    #[test]
    fn multiline_chat_keeps_each_source_line_for_scrolling() {
        let source = (1..=80)
            .map(|index| format!("Synthetic line {index:03}"))
            .collect::<Vec<_>>()
            .join("\n");
        let rows = render(&source, 80);
        assert_eq!(rows.len(), 80);
        for (index, row) in rows.iter().enumerate() {
            let line: String = row.iter().map(|part| part.text.as_str()).collect();
            assert_eq!(line, format!("Synthetic line {:03}", index + 1));
        }
    }
    #[test]
    fn markdown_styles_not_literal_markup_and_links_remain_actions() {
        let rows = render(
            "# Title\n\n**bold** and *italic* [result](embed:abc)\n\n| A | B |\n|---|---|\n| c | d |\n",
            80,
        );
        let text: String = rows.iter().flatten().map(|p| p.text.as_str()).collect();
        assert!(text.contains("Title"));
        assert!(!text.contains("**"));
        assert!(text.contains("/embed abc"));
        assert!(
            rows.iter()
                .flatten()
                .any(|p| p.text == "bold" && p.style.add_modifier.contains(Modifier::BOLD))
        );
        assert!(
            rows.iter()
                .flatten()
                .any(|p| matches!(p.link, Some(Link::Embed(_))))
        );
    }
    #[test]
    fn control_bytes_are_removed_and_wide_wrapping_is_bounded() {
        let rows = render("\u{1b}hello 界界 👩‍💻", 4);
        for row in rows {
            let text: String = row.iter().map(|p| p.text.as_str()).collect();
            assert!(!text.contains('\u{1b}'));
            assert!(text.width() <= 4);
        }
    }
}
