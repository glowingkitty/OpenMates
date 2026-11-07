//! Short-URL fragment/path parsing and URL building.
//!
//! spec: specifications/features/auth#auth.keys.client-wrapped
//! Mirrors `parseShortUrlFragment`, `parseShortUrlParts` and `buildShortUrl` in
//! `shortUrlEncryption.ts`; crypto for short URLs stays in `crypto::share`.

use super::{Decision, str_field};
use serde_json::{Value, json};

const MAX_SHORT_KEY_LENGTH: usize = 22;

fn is_base62(text: &str) -> bool {
    !text.is_empty() && text.bytes().all(|b| b.is_ascii_alphanumeric())
}

fn parts(token: &str, short_key: &str) -> Value {
    json!({ "token": token, "shortKey": short_key })
}

/// Legacy `token-shortKey` fragment (`parseShortUrlFragment`).
fn parse_fragment(fragment: &str) -> Value {
    let clean = fragment.strip_prefix('#').unwrap_or(fragment);
    let Some((token, short_key)) = clean.split_once('-') else {
        return Value::Null;
    };
    // Lengths are UTF-16 in JS; the base62 check below makes non-ASCII input fail either way.
    let valid = (6..=12).contains(&token.len())
        && (4..=MAX_SHORT_KEY_LENGTH).contains(&short_key.len())
        && is_base62(token)
        && is_base62(short_key);
    if valid { parts(token, short_key) } else { Value::Null }
}

/// `/s/{token}#{shortKey}` with the legacy fragment as fallback (`parseShortUrlParts`).
fn parse_parts(pathname: &str, fragment: &str) -> Value {
    let hash = fragment.strip_prefix('#').unwrap_or(fragment);
    // JS `$` without the m flag matches only at the very end: one optional trailing slash.
    let path_token = pathname
        .strip_prefix("/s/")
        .map(|rest| rest.strip_suffix('/').unwrap_or(rest))
        .filter(|token| (6..=12).contains(&token.len()) && is_base62(token));
    match path_token {
        Some(token) => {
            if (4..=MAX_SHORT_KEY_LENGTH).contains(&hash.len()) && is_base62(hash) {
                parts(token, hash)
            } else {
                Value::Null
            }
        }
        None => parse_fragment(hash),
    }
}

/// Dispatches the `shortUrl*` ops.
pub(super) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "shortUrlParseFragment" => Ok(parse_fragment(str_field(input, "fragment")?)),
        "shortUrlParseParts" => Ok(parse_parts(str_field(input, "pathname")?, str_field(input, "fragment")?)),
        "shortUrlBuild" => {
            let (token, key) = (str_field(input, "token")?, str_field(input, "short_key")?);
            let host = match input.get("short_domain") {
                Some(Value::String(domain)) if !domain.is_empty() => format!("https://{domain}"),
                _ => str_field(input, "origin")?.to_owned(),
            };
            Ok(json!(format!("{host}/s/{token}#{key}")))
        }
        _ => Err(format!("unknown_op:{op}")),
    }
}
