//! Local-model PII span handling: overlapping word windows for the model, merging
//! window entities, and merging model entities with the regex detector's matches.
//! Ports of `webPIIWindows.ts` and `mergeWebPIIMatches` in `webPIIMatches.ts`.
//! The model itself and its network broker stay on the page; the nonce for model
//! placeholders is supplied by the page (`crypto.randomUUID`).
//! spec: specifications/features/pii-protection#pii.composer.detect-redact-exclude
use super::pii_detect::{Match, Options, detect, match_json};
use super::pii_table::{CATEGORY_KEYS, category};
use super::protocol;
use super::utf16::{Utf16Index, WS_CLASS, index_of, is_js_ws, units};
use regex::Regex;
use serde_json::{Value, json};
use std::sync::OnceLock;

const WINDOW_UNITS: usize = 16;
const WINDOW_STRIDE: usize = WINDOW_UNITS / 2;
const MAX_UNIT_CHARS: usize = 64;
const NAME_PART_MAX_GAP: i64 = 1;
const ADDRESS_PART_MAX_GAP: i64 = 8;

/// Everyday words the model mislabels as a lone GIVEN_NAME when capitalised at a
/// sentence start ("Same question. Your take?"): interjections, determiners,
/// pronouns, question words and sentence starters. A lone entity with one of
/// these texts is dropped; next to another name part it stays protected
/// ("Same Smith"). Never add words that are also given names (will, may, mark,
/// hope, grace, bill, rose, joy, april, june, art, pat, sue). Mirrored in
/// `NON_NAME_STANDALONE_WORDS` in `webPIIMatches.ts`.
const NON_NAME_STANDALONE_WORDS: &[&str] = &[
    "awesome", "great", "perfect", "okay", "ok", "nice", "cool", "thanks", "thank", "hello", "hi", "hey", "sure", "wonderful",
    "excellent", "amazing", "fine", "good", "yes", "no", "yeah", "right", "sorry", "please", "welcome", "fantastic", "brilliant",
    "lovely", "super", "sweet", "absolutely", "definitely", "exactly", "indeed", "well", "alright", "bye", "goodbye", "cheers",
    "same", "this", "that", "these", "those", "what", "which", "who", "why", "how", "when", "where", "your", "my", "our", "their", "his", "her", "its", "also", "again", "another", "other", "both", "each", "every", "any", "some", "none", "all", "many", "more", "most", "now", "then", "here", "there", "maybe",
];
const ADDRESS_ANCHORS: &[&str] = &["STREET_NAME", "BUILDING_NUMBER", "SECONDARY_ADDRESS", "ZIP_CODE"];
const MANDATORY_CATEGORIES: &[&str] = &["api_keys", "generic_secrets", "private_keys", "jwt_tokens"];
const EXTRA_PLACEHOLDER_TYPES: &[&str] =
    &["AWS_KEY", "AWS_SECRET", "GITHUB_TOKEN", "GOOGLE_KEY", "HF_TOKEN", "SECRET", "JWT_TOKEN", "CARD", "IP", "HOME_PATH", "USER_HOST", "MAC", "PLATE", "WALLET"];

/// Model label -> `PIIType`.
fn label_type(label: &str) -> Option<&'static str> {
    Some(match label {
        "GIVEN_NAME" | "SURNAME" => "PERSON_NAME",
        "STREET_NAME" | "BUILDING_NUMBER" | "SECONDARY_ADDRESS" | "CITY" | "STATE" | "ZIP_CODE" => "ADDRESS",
        "EMAIL" => "EMAIL",
        "PHONE" => "PHONE",
        "CREDIT_CARD" => "CREDIT_CARD",
        "BANK_ACCOUNT" | "ROUTING_NUMBER" => "BANK_ACCOUNT",
        "GOVERNMENT_ID" => "GOVERNMENT_ID",
        "PASSPORT" => "PASSPORT",
        "DRIVERS_LICENSE" => "DRIVERS_LICENSE",
        "TAX_ID" => "TAX_ID",
        "SSN" => "SSN",
        "IMEI" => "IMEI",
        _ => return None,
    })
}

struct Entity {
    label: String,
    original: Vec<u16>,
    start: i64,
    end: i64,
}

fn parse_entities(value: Option<&Value>) -> Result<Vec<Entity>, String> {
    value
        .and_then(Value::as_array)
        .ok_or("protocol")?
        .iter()
        .map(|e| {
            Ok::<Entity, String>(Entity {
                label: e.get("label").and_then(Value::as_str).ok_or("protocol")?.to_string(),
                original: units(e.get("original").and_then(Value::as_str).ok_or("protocol")?),
                start: e.get("start").and_then(Value::as_i64).ok_or("protocol")?,
                end: e.get("end").and_then(Value::as_i64).ok_or("protocol")?,
            })
        })
        .collect()
}

fn is_ws_unit(u: u16) -> bool {
    char::from_u32(u32::from(u)).is_some_and(is_js_ws)
}

/// `buildWebPIIWindows`: `{text}` -> `[{start,end}]` over UTF-16 units.
///
/// # Errors
/// `protocol` for a malformed payload.
pub fn windows_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let text = units(value.get("text").and_then(Value::as_str).ok_or("protocol")?);
    let mut parts: Vec<(usize, usize)> = Vec::new();
    let mut i = 0;
    while i < text.len() {
        if is_ws_unit(text[i]) {
            i += 1;
            continue;
        }
        let run_start = i;
        while i < text.len() && !is_ws_unit(text[i]) {
            i += 1;
        }
        let mut start = run_start;
        while start < i {
            let mut end = (start + MAX_UNIT_CHARS).min(i);
            // Never cut a surrogate pair in half.
            if end < i && (0xdc00..=0xdfff).contains(&text[end]) {
                end += 1;
            }
            parts.push((start, end));
            start = end;
        }
    }
    if parts.len() <= WINDOW_UNITS {
        return Ok(json!([{"start": 0, "end": text.len()}]).to_string());
    }
    let mut windows = Vec::new();
    let mut first = 0;
    loop {
        let last = (first + WINDOW_UNITS).min(parts.len()) - 1;
        windows.push(json!({"start": parts[first].0, "end": parts[last].1}));
        if last == parts.len() - 1 {
            return Ok(Value::Array(windows).to_string());
        }
        first += WINDOW_STRIDE;
    }
}

/// `mergeWebPIIWindowEntities`: indices of the kept entities in output order.
///
/// # Errors
/// `protocol` for a malformed payload.
pub fn merge_window_entities_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let entities = parse_entities(value.get("entities"))?;
    let mut order: Vec<usize> = (0..entities.len()).collect();
    order.sort_by_key(|&i| std::cmp::Reverse(entities[i].end - entities[i].start));
    let mut kept: Vec<usize> = Vec::new();
    for i in order {
        if !kept.iter().any(|&k| entities[i].start < entities[k].end && entities[i].end > entities[k].start) {
            kept.push(i);
        }
    }
    kept.sort_by_key(|&i| (entities[i].start, std::cmp::Reverse(entities[i].end)));
    Ok(json!(kept).to_string())
}

/// FNV-1a over UTF-16 units, base 36 (`modelPIIMatchId`).
fn model_match_id(kind: &str, original: &[u16]) -> String {
    let mut hash: u32 = 2_166_136_261;
    for &u in original {
        hash = (hash ^ u32::from(u)).wrapping_mul(16_777_619);
    }
    let mut digits = Vec::new();
    let mut n = hash;
    loop {
        digits.push(char::from_digit(n % 36, 36).expect("digit below 36"));
        n /= 36;
        if n == 0 {
            break;
        }
    }
    format!("pii-model-{kind}-{}", digits.iter().rev().collect::<String>())
}

fn overlaps(s: usize, e: usize, r: (usize, usize)) -> bool {
    s < r.1 && e > r.0
}

fn protected_regex() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(&format!(r"(?i-u:https?://)[^{WS_CLASS}]+|(?i-u:\b[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}\b)"))
            .expect("fixed pattern compiles")
    })
}

fn generated_regex() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        let types: Vec<&str> = CATEGORY_KEYS.iter().chain(EXTRA_PLACEHOLDER_TYPES).copied().collect();
        Regex::new(&format!(r"\[(?:{})_[1-9][0-9]*(?:_[A-Za-z0-9_-]+)?\]", types.join("|"))).expect("fixed pattern compiles")
    })
}

fn ranges_of(re: &Regex, text: &str, index: &Utf16Index) -> Vec<(usize, usize)> {
    re.find_iter(text).map(|m| (index.at(m.start()), index.at(m.end()))).collect()
}

fn is_whole_iban(value: &str) -> bool {
    let options = Options::with_disabled(&["phone_numbers"]);
    let len = super::utf16::len16(value);
    detect(value, &options).iter().any(|m| m.kind == "IBAN" && m.start == 0 && m.end == len)
}

fn is_ipv4_shape(original: &str) -> bool {
    let parts: Vec<&str> = original.split('.').collect();
    parts.len() == 4 && parts.iter().all(|p| (1..=3).contains(&p.len()) && p.bytes().all(|b| b.is_ascii_digit()) && p.parse::<u32>().is_ok_and(|n| n <= 255))
}

/// `mergeWebPIIMatches`: `{text, entities, options?, nonce}` -> matches, or the error code
/// `invalid_offsets` when the model broke the UTF-16 offset contract.
///
/// # Errors
/// `protocol` for a malformed payload, `invalid_offsets` for entities that do not slice the text.
pub fn merge_matches_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let text = value.get("text").and_then(Value::as_str).ok_or("protocol")?;
    let nonce = value.get("nonce").and_then(Value::as_str).ok_or("protocol")?;
    let entities = parse_entities(value.get("entities"))?;
    let options = Options::from_json(value.get("options"))?;
    let text16 = units(text);
    let index = Utf16Index::new(text);

    let basic = detect(text, &options);
    let excluded_ranges: Vec<(usize, usize)> = detect(text, &options.without_exclusions())
        .iter()
        .filter(|m| options.excluded_ids.contains(&m.id))
        .map(|m| (m.start, m.end))
        .collect();
    let mut reserved = excluded_ranges.clone();
    let mut known: Vec<(usize, usize)> = Vec::new();
    for token in options.replacement_tokens() {
        let token = if token.starts_with('[') { token.to_string() } else { format!("[{token}]") };
        let needle = units(&token);
        let mut from = 0;
        while let Some(at) = index_of(&text16, &needle, from) {
            known.push((at, at + needle.len()));
            from = at + needle.len();
        }
    }
    let personal = |m: &Match| m.id.starts_with("pii-PERSONAL_DATA-");
    let mut result: Vec<Match> = Vec::new();
    let mut counts: Vec<(String, usize)> = Vec::new();
    for m in basic {
        if personal(&m) && known.iter().any(|&r| overlaps(m.start, m.end, r)) {
            continue;
        }
        if reserved.iter().any(|&r| overlaps(m.start, m.end, r)) {
            continue;
        }
        reserved.push((m.start, m.end));
        if !options.excluded_ids.contains(&m.id) {
            result.push(m);
        }
    }
    let mut hard: Vec<(usize, usize)> = excluded_ranges;
    hard.extend(result.iter().filter(|m| personal(m) || category(&m.kind).is_some_and(|c| MANDATORY_CATEGORIES.contains(&c))).map(|m| (m.start, m.end)));
    hard.extend(known);
    hard.extend(ranges_of(generated_regex(), text, &index));
    hard.extend(ranges_of(protected_regex(), text, &index));
    // Model spans never cut into an embed ref (`protectedRanges` in webPIIMatches.ts).
    hard.extend(super::embed_refs::embed_reference_ranges(text, &index));

    let mut order: Vec<usize> = (0..entities.len()).collect();
    order.sort_by_key(|&i| (entities[i].start, std::cmp::Reverse(entities[i].end)));
    for &i in &order {
        let entity = &entities[i];
        let kind = match entity.label.as_str() {
            "IP_ADDRESS" => Some(if entity.original.contains(&0x3a) { "IPV6" } else { "IPV4" }),
            other => label_type(other),
        };
        let Some(kind) = kind else { continue };
        let valid_offsets = entity.start >= 0
            && entity.end > entity.start
            && entity.end as usize <= text16.len()
            && text16[entity.start as usize..entity.end as usize] == entity.original[..];
        if !valid_offsets {
            return Err("invalid_offsets".to_string());
        }
        let (s, e) = (entity.start as usize, entity.end as usize);
        let original = String::from_utf16(&entity.original).map_err(protocol)?;
        if is_standalone_non_name(&entities, i) {
            continue;
        }
        if matches!(entity.label.as_str(), "CITY" | "STATE") && !is_address_region(&entities, i) {
            continue;
        }
        if category(kind).is_some_and(|c| options.disabled_categories.contains(c)) {
            continue;
        }
        if hard.iter().any(|&r| overlaps(s, e, r)) {
            continue;
        }
        if kind == "IPV4" && !is_ipv4_shape(&original) {
            continue;
        }
        let id = model_match_id(kind, &entity.original);
        if reserved.iter().any(|&r| overlaps(s, e, r)) {
            let contained: Vec<usize> = (0..result.len()).filter(|&k| overlaps(s, e, (result[k].start, result[k].end))).collect();
            let upgrades = kind == "BANK_ACCOUNT"
                && !contained.is_empty()
                && contained.iter().all(|&k| result[k].kind == "PHONE" && !personal(&result[k]) && result[k].start >= s && result[k].end <= e)
                && is_whole_iban(&original);
            if !upgrades {
                continue;
            }
            for &k in contained.iter().rev() {
                let removed = result.remove(k);
                if let Some(at) = reserved.iter().position(|r| *r == (removed.start, removed.end)) {
                    reserved.remove(at);
                }
            }
        }
        reserved.push((s, e));
        if options.excluded_ids.contains(&id) {
            hard.push((s, e));
            continue;
        }
        let count = match counts.iter_mut().find(|(k, _)| k == kind) {
            Some((_, n)) => {
                *n += 1;
                *n
            }
            None => {
                counts.push((kind.to_string(), 1));
                1
            }
        };
        result.push(Match { kind: kind.to_string(), start: s, end: e, placeholder: format!("[{kind}_{count}_{nonce}]"), id });
    }
    result.sort_by_key(|m| m.start);
    Ok(Value::Array(result.iter().map(match_json).collect()).to_string())
}

fn near(a: &Entity, b: &Entity, gap: i64) -> bool {
    a.start - b.end <= gap && b.start - a.end <= gap
}

fn is_standalone_non_name(entities: &[Entity], i: usize) -> bool {
    let entity = &entities[i];
    let word = String::from_utf16_lossy(&entity.original);
    if entity.label != "GIVEN_NAME" || !NON_NAME_STANDALONE_WORDS.contains(&super::utf16::js_trim(&word).to_lowercase().as_str()) {
        return false;
    }
    // `other.start - entity.end <= gap && entity.start - other.end <= gap`
    !entities.iter().enumerate().any(|(k, other)| k != i && matches!(other.label.as_str(), "GIVEN_NAME" | "SURNAME") && near(entity, other, NAME_PART_MAX_GAP))
}

fn is_address_region(entities: &[Entity], i: usize) -> bool {
    entities.iter().any(|anchor| ADDRESS_ANCHORS.contains(&anchor.label.as_str()) && near(&entities[i], anchor, ADDRESS_PART_MAX_GAP))
}
