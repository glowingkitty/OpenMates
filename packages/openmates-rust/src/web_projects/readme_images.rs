//! README image resolution: the Markdown image sources (inline and reference style) and
//! how each resolves (public URL through the proxy, connected-source path, stored root
//! item). Shared core part of `web_projects`.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `projectReadmeImages` of `projectReadmePolicy.ts`. The JS regexes are rebuilt
//! with the JS `\s` set and JS multiline anchors so every match equals the V8 match.

use super::js::{JS_SPACE_CLASS, as_str, decode_uri_component, is_js_space, prop, req_array, trim, truthy};
use super::readme::is_root_embed;
use super::{Fault, Outcome};
use regex::Regex;
use serde_json::{Value, json};
use std::sync::LazyLock;
use url::Url;

/// Connected-source images a README may read.
const MAX_REMOTE_README_IMAGES: usize = 8;

fn js_regex(pattern: &str) -> Regex {
    Regex::new(&pattern.replace("WS", JS_SPACE_CLASS)).expect("static pattern compiles")
}

/// `!\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\)` (global).
static INLINE: LazyLock<Regex> = LazyLock::new(|| {
    js_regex(r#"!\[[^\]]*\]\([WS]*(?:<([^>]+)>|([^WS)]+))(?:[WS]+(?:"[^"]*"|'[^']*'|\([^)]*\)))?[WS]*\)"#)
});
/// The `^...$`-multiline definition pattern, anchored at a line start; the trailing
/// `$` is emulated by consuming one line terminator (or the end), which accepts exactly
/// the same positions as the zero-width JS assertion.
static DEFINITION: LazyLock<Regex> = LazyLock::new(|| {
    js_regex(
        r#"\A[WS]{0,3}\[([^\]]+)\]:[WS]*(?:<([^>]+)>|([^WS]+))(?:[WS]+(?:"[^"]*"|'[^']*'|\([^)]*\)))?[WS]*(\z|[\n\r\x{2028}\x{2029}])"#,
    )
});
/// `!\[([^\]]+)\]\s*\[([^\]]*)\]` (global).
static REFERENCE: LazyLock<Regex> = LazyLock::new(|| js_regex(r"!\[([^\]]+)\][WS]*\[([^\]]*)\]"));
static IPV4: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$").expect("static pattern compiles"));

fn is_line_terminator(c: char) -> bool {
    matches!(c, '\n' | '\r' | '\u{2028}' | '\u{2029}')
}

fn add(sources: &mut Vec<String>, source: String) {
    if !source.is_empty() && !sources.contains(&source) {
        sources.push(source);
    }
}

fn normalize_label(label: &str) -> String {
    let mut out = String::new();
    let mut in_space = false;
    for c in trim(label).chars() {
        if is_js_space(c) {
            if !in_space {
                out.push(' ');
            }
            in_space = true;
        } else {
            out.push(c);
            in_space = false;
        }
    }
    out.to_lowercase()
}

/// `readmeImageSources`: distinct inline and reference-style image sources, first-seen order.
fn image_sources(markdown: &str) -> Vec<String> {
    let mut sources = Vec::new();
    for caps in INLINE.captures_iter(markdown) {
        let source = caps.get(1).or_else(|| caps.get(2)).map_or("", |m| m.as_str());
        add(&mut sources, trim(source).to_owned());
    }
    // Later definitions of a label win (`Map.set`).
    let mut definitions: Vec<(String, String)> = Vec::new();
    let mut last_index = 0;
    let line_starts = std::iter::once(0).chain(
        markdown.char_indices().filter(|(_, c)| is_line_terminator(*c)).map(|(i, c)| i + c.len_utf8()),
    );
    for start in line_starts {
        if start < last_index || start > markdown.len() {
            continue;
        }
        let Some(caps) = DEFINITION.captures(&markdown[start..]) else { continue };
        let whole = caps.get(0).map_or(0, |m| m.end());
        let terminator = caps.get(4).map_or(0, |m| m.len());
        last_index = start + whole - terminator;
        let source = trim(caps.get(2).or_else(|| caps.get(3)).map_or("", |m| m.as_str())).to_owned();
        if !source.is_empty() {
            let label = normalize_label(caps.get(1).map_or("", |m| m.as_str()));
            match definitions.iter_mut().find(|(name, _)| *name == label) {
                Some(entry) => entry.1 = source,
                None => definitions.push((label, source)),
            }
        }
        // JS resumes at `lastIndex`; a zero-length match is impossible (`[` is required).
    }
    for caps in REFERENCE.captures_iter(markdown) {
        let reference = caps.get(2).map_or("", |m| m.as_str());
        let label = normalize_label(if reference.is_empty() { caps.get(1).map_or("", |m| m.as_str()) } else { reference });
        if let Some((_, source)) = definitions.iter().find(|(name, _)| *name == label) {
            add(&mut sources, source.clone());
        }
    }
    sources
}

/// `readmePublicImageHref`: normalized href of a public http(s) URL, else `None`.
fn public_href(value: &str) -> Option<String> {
    let candidate = if value.starts_with("//") { format!("https:{value}") } else { value.to_owned() };
    let url = Url::parse(&candidate).ok()?;
    if !matches!(url.scheme(), "https" | "http")
        || !url.username().is_empty()
        || url.password().is_some_and(|p| !p.is_empty())
    {
        return None;
    }
    let host = url.host_str().unwrap_or("").to_lowercase();
    if host == "localhost" || host.ends_with(".localhost") || host.starts_with('[') || IPV4.is_match(&host) {
        return None;
    }
    Some(url.as_str().to_owned())
}

/// `relativeImagePath`: the normalized Project-relative path of a relative source.
fn relative_path(value: &str) -> Option<String> {
    if value.is_empty() || value.starts_with('/') || value.starts_with('\\') || value.starts_with('#') {
        return None;
    }
    let without_suffix = value.split(['?', '#']).next().unwrap_or("");
    let decoded = decode_uri_component(without_suffix)?;
    let decoded = decoded.strip_prefix("./").unwrap_or(&decoded);
    if decoded.is_empty() || decoded.contains('\\') {
        return None;
    }
    let mut parts: Vec<&str> = Vec::new();
    for part in decoded.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                parts.pop()?;
            }
            _ => parts.push(part),
        }
    }
    (!parts.is_empty()).then(|| parts.join("/"))
}

/// `projectItemPath`: the stored item's relative path, `None` when unsafe.
fn item_path(item: &Value) -> Result<Option<String>, Fault> {
    let metadata = prop(Some(item), "metadata")?;
    let raw = match (prop(metadata, "path")?, prop(metadata, "remote_path")?) {
        (Some(Value::String(path)), _) => Some(path.as_str()),
        (_, Some(Value::String(path))) => Some(path.as_str()),
        _ => {
            let display = prop(Some(item), "displayName")?;
            if truthy(display) {
                Some(as_str(display).ok_or_else(|| Fault::Malformed("bad_field:displayName".to_owned()))?)
            } else {
                None
            }
        }
    };
    let Some(raw) = raw.filter(|raw| !raw.is_empty()) else { return Ok(None) };
    if raw.starts_with('/') || raw.contains('\\') || raw.split('/').any(|part| matches!(part, "" | "." | "..")) {
        return Ok(None);
    }
    Ok(Some(raw.to_owned()))
}

/// `projectReadmeImages`: the resolution plan of every README image source.
pub(super) fn images(input: &Value) -> Outcome {
    let markdown = as_str(input.get("markdown")).ok_or_else(|| Fault::Malformed("bad_field:markdown".to_owned()))?;
    let remote = truthy(input.get("remote"));
    let mut images = Vec::new();
    let mut remote_images = 0;
    for source in image_sources(markdown) {
        if let Some(href) = public_href(&source) {
            images.push(json!({ "source": source, "kind": "external", "href": href }));
            continue;
        }
        let Some(path) = relative_path(&source) else { continue };
        if remote {
            if remote_images >= MAX_REMOTE_README_IMAGES {
                continue;
            }
            remote_images += 1;
            images.push(json!({ "source": source, "kind": "remote", "path": path }));
            continue;
        }
        let items = req_array(input.get("items"), "items")?;
        for (index, candidate) in items.iter().enumerate() {
            if is_root_embed(candidate)? && item_path(candidate)?.as_deref() == Some(path.as_str()) {
                images.push(json!({ "source": source, "kind": "item", "path": path, "index": index }));
                break;
            }
        }
    }
    Ok(json!({ "images": images }))
}
