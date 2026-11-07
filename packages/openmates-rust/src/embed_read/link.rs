//! spec: sdk.client.thin-platform-boundary
//! `embed:` link targets and direct embed refs (port of `embedFragmentUtils.ts`).
//! Line numbers beyond `u64` are refused (the TS float path never occurs in real links).
use super::EmbedReadError;

/// Parsed `embed:ref#fragment` target.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmbedLinkFocus {
    /// Reference without fragment: the only value used for lookup.
    pub clean_ref: String,
    /// First focused line (`#L10-L20`).
    pub line_start: Option<u64>,
    /// Last focused line.
    pub line_end: Option<u64>,
    /// Quote to highlight (`#text=` / `#quote=`).
    pub highlight_quote_text: Option<String>,
    /// Upper-cased sheet range (`#range=` / `#cell=`).
    pub sheet_range: Option<String>,
}

fn hex(b: u8) -> Option<u8> {
    (b as char).to_digit(16).map(|d| d as u8)
}

/// `URLSearchParams` decoding: `+` is a space, invalid escapes stay literal, bytes decode lossily.
fn form_decode(input: &str) -> String {
    let b = input.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'+' => out.push(b' '),
            b'%' if i + 2 < b.len() && hex(b[i + 1]).is_some() && hex(b[i + 2]).is_some() => {
                out.push(hex(b[i + 1]).unwrap_or(0) * 16 + hex(b[i + 2]).unwrap_or(0));
                i += 2;
            }
            c => out.push(c),
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// JS `decodeURIComponent` after `+` -> space; malformed input is returned unchanged.
fn decode_fragment_value(value: &str) -> String {
    let spaced = value.replace('+', " ");
    let b = spaced.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' {
            if i + 2 >= b.len() {
                return value.to_string();
            }
            match (hex(b[i + 1]), hex(b[i + 2])) {
                (Some(h), Some(l)) => out.push(h * 16 + l),
                _ => return value.to_string(),
            }
            i += 3;
        } else {
            out.push(b[i]);
            i += 1;
        }
    }
    match String::from_utf8(out) {
        Ok(s) => s,
        Err(_) => value.to_string(),
    }
}

/// First value of `key` in a query string, as `URLSearchParams.get`.
fn query_get(query: &str, key: &str) -> Option<String> {
    // `new URLSearchParams("?a=b")` drops one leading question mark.
    let query = query.strip_prefix('?').unwrap_or(query);
    for pair in query.split('&') {
        if pair.is_empty() {
            continue;
        }
        let (name, value) = pair.split_once('=').unwrap_or((pair, ""));
        if form_decode(name) == key {
            return Some(form_decode(value));
        }
    }
    None
}

fn parse_line_fragment(fragment: &str) -> Option<(&str, Option<&str>)> {
    let rest = fragment.strip_prefix('L')?;
    let digits = |s: &str| !s.is_empty() && s.bytes().all(|c| c.is_ascii_digit());
    match rest.split_once('-') {
        None => digits(rest).then_some((rest, None)),
        Some((a, b)) => {
            let b = b.strip_prefix('L').unwrap_or(b);
            (digits(a) && digits(b)).then_some((a, Some(b)))
        }
    }
}

/// Splits `raw` into its clean ref and focus fragment.
pub fn parse_embed_link_target(raw: &str) -> Result<EmbedLinkFocus, EmbedReadError> {
    let (clean_ref, fragment) = raw.split_once('#').unwrap_or((raw, ""));
    let clean_ref = clean_ref.to_string();
    if let Some((start, end)) = parse_line_fragment(fragment) {
        let num = |s: &str| {
            s.parse::<u64>()
                .map_err(|_| EmbedReadError::new("line_out_of_range"))
        };
        let start = num(start)?;
        let end = match end {
            Some(e) => num(e)?,
            None => start,
        };
        return Ok(EmbedLinkFocus {
            clean_ref,
            line_start: Some(start.min(end)),
            line_end: Some(start.max(end)),
            highlight_quote_text: None,
            sheet_range: None,
        });
    }
    let nonempty = |v: Option<String>| v.filter(|s| !s.is_empty());
    let text =
        nonempty(query_get(fragment, "text")).or_else(|| nonempty(query_get(fragment, "quote")));
    let range =
        nonempty(query_get(fragment, "range")).or_else(|| nonempty(query_get(fragment, "cell")));
    Ok(EmbedLinkFocus {
        clean_ref,
        line_start: None,
        line_end: None,
        highlight_quote_text: text.map(|t| decode_fragment_value(&t)),
        sheet_range: range.map(|r| decode_fragment_value(&r).to_uppercase()),
    })
}

/// Deterministic direct embed ref from metadata (`generateDirectEmbedRef`).
pub fn generate_direct_embed_ref(
    embed_type: &str,
    embed_id: &str,
    filename: Option<&str>,
    title: Option<&str>,
    subject: Option<&str>,
) -> String {
    let pick = [filename, title, subject]
        .into_iter()
        .flatten()
        .find(|s| !s.is_empty());
    let fallback_owned = embed_type.replace('_', "-");
    let fallback = if fallback_owned.is_empty() {
        "embed"
    } else {
        fallback_owned.as_str()
    };
    let candidate = pick
        .or(if embed_type.is_empty() {
            None
        } else {
            Some(embed_type)
        })
        .unwrap_or(fallback);
    let lowered = candidate.trim().to_lowercase();
    let mut base = String::new();
    for ch in lowered.chars() {
        let ok = ch.is_ascii_lowercase() || ch.is_ascii_digit() || matches!(ch, '.' | '_' | '-');
        let ch = if ok { ch } else { '-' };
        if ch == '-' && base.ends_with('-') {
            continue;
        }
        base.push(ch);
    }
    let strip = |s: &str| s.trim_matches(|c| matches!(c, '-' | '.' | '_')).to_string();
    let mut base = strip(&base);
    base.truncate(48);
    let base = base.trim_end_matches(['-', '.', '_']).to_string();
    let base = if base.is_empty() {
        fallback.to_string()
    } else {
        base
    };
    let suffix: String = embed_id.chars().take(6).collect();
    if !suffix.is_empty() && !base.ends_with(&format!("-{suffix}")) {
        format!("{base}-{suffix}")
    } else {
        base
    }
}
