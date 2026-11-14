//! Progressive SVG: turn SVG source that is still streaming into a renderable
//! document (port of the web `progressiveSvg.ts` `buildProgressiveSvg`).
//!
//! While an assistant streams SVG source the last tag, attribute or entity may
//! be cut off and elements are still open. [`progressive_svg`] cuts the source
//! at the last complete token and closes every open element. Shells render the
//! result through an image view only (never a web view), so scripts and external
//! resources cannot run or load.

const RAW_TEXT_ELEMENTS: [&str; 2] = ["style", "script"];

/// A tag scanned at a `<` byte offset.
struct TagScan<'a> {
    /// Offset just after the closing `>`.
    end: usize,
    name: &'a str,
    closing: bool,
    self_closing: bool,
}

fn scan_tag(source: &str, start: usize) -> Option<TagScan<'_>> {
    let bytes = source.as_bytes();
    let mut i = start + 1;
    let closing = bytes.get(i) == Some(&b'/');
    if closing {
        i += 1;
    }
    let name_start = i;
    for ch in source[name_start..].chars() {
        if ch.is_whitespace() || ch == '/' || ch == '>' {
            break;
        }
        i += ch.len_utf8();
    }
    let name = &source[name_start..i];
    let first = name.chars().next()?;
    if !(first.is_ascii_alphabetic() || first == '_') {
        return None;
    }
    let mut quote: Option<u8> = None;
    while i < bytes.len() {
        let ch = bytes[i];
        match quote {
            Some(q) => {
                if ch == q {
                    quote = None;
                }
            }
            None if ch == b'"' || ch == b'\'' => quote = Some(ch),
            None if ch == b'>' => {
                return Some(TagScan {
                    end: i + 1,
                    name,
                    closing,
                    self_closing: !closing && bytes[i - 1] == b'/',
                });
            }
            None => {}
        }
        i += 1;
    }
    None
}

fn skip_past(source: &str, from: usize, terminator: &str) -> Option<usize> {
    source[from..]
        .find(terminator)
        .map(|found| from + found + terminator.len())
}

/// Turn a (possibly partial) SVG source into a renderable document, or `None`
/// when no complete root `<svg ...>` open tag has arrived yet. A complete
/// document is returned unchanged.
pub fn build_progressive_svg(source: &str) -> Option<String> {
    let mut stack: Vec<&str> = Vec::new();
    let mut root_seen = false;
    let mut root_closed = false;
    let mut safe_end = 0usize;
    let mut safe_stack: Vec<&str> = Vec::new();
    let mut i = 0usize;

    while i < source.len() && !root_closed {
        let Some(found) = source[i..].find('<') else {
            break;
        };
        let lt = i + found;
        let rest = &source[lt..];
        let next: Option<usize> = if rest.starts_with("<!--") {
            skip_past(source, lt + 4, "-->")
        } else if rest.starts_with("<![CDATA[") {
            skip_past(source, lt + 9, "]]>")
        } else if rest.starts_with("<?") {
            skip_past(source, lt + 2, "?>")
        } else if rest.starts_with("<!") {
            skip_past(source, lt + 2, ">")
        } else {
            let Some(tag) = scan_tag(source, lt) else {
                break;
            };
            let mut next = tag.end;
            let lower = tag.name.to_ascii_lowercase();
            if tag.closing {
                let Some(at) = stack.iter().rposition(|open| *open == tag.name) else {
                    i = next;
                    continue;
                };
                stack.truncate(at);
                if root_seen && stack.is_empty() {
                    root_closed = true;
                }
            } else if !root_seen && lower != "svg" {
                break;
            } else {
                if !tag.self_closing {
                    stack.push(tag.name);
                }
                if !root_seen {
                    root_seen = true;
                    if tag.self_closing {
                        root_closed = true;
                    }
                }
                if RAW_TEXT_ELEMENTS.contains(&lower.as_str()) && !tag.self_closing {
                    let needle = format!("</{lower}");
                    let close_at = source.to_ascii_lowercase()[next..]
                        .find(&needle)
                        .map(|f| next + f);
                    let Some(close_at) = close_at else {
                        stack.pop();
                        break;
                    };
                    let Some(close_tag) = scan_tag(source, close_at) else {
                        stack.pop();
                        break;
                    };
                    stack.pop();
                    next = close_tag.end;
                }
            }
            Some(next)
        };
        let Some(next) = next else {
            break;
        };
        i = next;
        safe_end = i;
        safe_stack = stack.clone();
    }

    if !root_seen || safe_end == 0 || (safe_stack.is_empty() && !root_closed) {
        return None;
    }
    let head = &source[..safe_end];
    if safe_stack.is_empty() {
        return Some(if source[safe_end..].trim().is_empty() {
            source.to_owned()
        } else {
            head.to_owned()
        });
    }
    let mut out = head.to_owned();
    for name in safe_stack.iter().rev() {
        out.push_str("</");
        out.push_str(name);
        out.push('>');
    }
    Some(out)
}

/// The SVG document a shell should draw for `source`. While streaming
/// (`complete == false`) the partial source is repaired by
/// [`build_progressive_svg`]; `None` means keep the last good frame. When
/// `complete` is true the source is returned as is (`None` when blank).
pub fn progressive_svg(source: &str, complete: bool) -> Option<String> {
    if complete {
        return (!source.trim().is_empty()).then(|| source.to_owned());
    }
    build_progressive_svg(source)
}

#[cfg(test)]
#[path = "progressive_svg_tests.rs"]
mod tests;
