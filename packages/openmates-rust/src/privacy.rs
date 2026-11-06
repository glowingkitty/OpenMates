//! Deterministic client-side privacy boundary, ported from piiDetectionService and
//! ProjectFilePrivacy. Mappings stay in client RAM and are persisted only encrypted.
use crate::error::{Error, Result};
use regex::Regex;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    sync::{Mutex, OnceLock},
};

mod placeholder;

/// Caller policy; no state directory or installed CLI preferences are consulted.
#[derive(Clone, Default)]
pub struct PrivacyOptions {
    pub enhanced: bool,
}
impl PrivacyOptions {
    pub fn verify(&self) -> Result<()> {
        if self.enhanced {
            return Err(Error::Invalid(
                "Enhanced personal data anonymization is enabled but unavailable in this Rust SDK.",
            ));
        }
        Ok(())
    }
}
pub struct PreparedPrivacy {
    pub text: String,
    pub mappings: Vec<Value>,
}
#[derive(Clone)]
struct Range {
    start: usize,
    end: usize,
    kind: String,
}
struct Pattern {
    kind: &'static str,
    regex: Regex,
}
fn patterns() -> &'static [Pattern] {
    static PATTERNS: OnceLock<Vec<Pattern>> = OnceLock::new();
    PATTERNS.get_or_init(|| {
        let table = [
        ("AWS_ACCESS_KEY", r#"(?-u:\b)AKIA[0-9A-Z]{16}(?-u:\b)"#),
        ("OPENAI_KEY", r#"(?-u:\b)sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,200}(?-u:\b)"#),
        ("ANTHROPIC_KEY", r#"(?-u:\b)sk-ant-api03-[A-Za-z0-9_-]{90,110}(?-u:\b)"#),
        ("GITHUB_PAT", r#"(?-u:\b)(?:ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}|gho_[a-zA-Z0-9]{36})(?-u:\b)"#),
        ("STRIPE_KEY", r#"(?-u:\b)[sr]k_(?:live|test)_[0-9a-zA-Z]{24,99}(?-u:\b)"#),
        ("GOOGLE_API_KEY", r#"(?-u:\b)AIza[0-9A-Za-z\-_]{35}(?-u:\b)"#),
        ("SLACK_TOKEN", r#"(?-u:\b)xox[bpras]-[0-9a-zA-Z-]{10,250}(?-u:\b)"#),
        ("AWS_SECRET_KEY", r#"(?i)(?:aws_secret|secret_key|secretkey|secret_access_key)['":\s=]+([0-9a-zA-Z/+=]{40})(?-u:\b)"#),
        ("TWILIO_KEY", r#"(?-u:\b)(?:AC[a-f0-9]{32}|SK[a-f0-9]{32})(?-u:\b)"#),
        ("SENDGRID_KEY", r#"(?-u:\b)SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}(?-u:\b)"#),
        ("AZURE_KEY", r#"(?i)(?:azure|subscription|ocp-apim)[_-]?(?:key|secret|token)['":\s=]+([0-9a-f]{32})(?-u:\b)"#),
        ("HUGGINGFACE_KEY", r#"(?-u:\b)hf_[a-zA-Z0-9]{34,}(?-u:\b)"#),
        ("DATABRICKS_TOKEN", r#"(?-u:\b)dapi[a-f0-9]{32,40}(?-u:\b)"#),
        ("FIREBASE_KEY", r#"(?-u:\b)AAAA[A-Za-z0-9_-]{100,200}(?-u:\b)"#),
        ("GENERIC_SECRET", r#"(?i)(?:api[_-]?key|api[_-]?secret|secret[_-]?key|auth[_-]?token|access[_-]?token|bearer[_-]?token|private[_-]?key|password|passwd|credential|client[_-]?secret|app[_-]?secret|signing[_-]?key|encryption[_-]?key)['":\s=]+['"]?([A-Za-z0-9_\-/.+=]{8,200})['"]?"#),
        ("PRIVATE_KEY", r#"-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"#),
        ("JWT", r#"(?-u:\b)eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+"#),
        ("EMAIL", r#"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"#),
        ("CREDIT_CARD", r#"(?-u:\b)(?:4[0-9]{3}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}|5[1-5][0-9]{2}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}|3[47][0-9]{2}[-\s]?[0-9]{6}[-\s]?[0-9]{5}|6(?:011|5[0-9]{2})[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4})(?-u:\b)"#),
        ("SSN", r#"(?-u:\b)[0-9]{3}[-\s]?[0-9]{2}[-\s]?[0-9]{4}(?-u:\b)"#),
        ("PHONE", r#"(?:(?:\+|00)[1-9][0-9]{0,2}[-.\s/]?(?:\(?[0-9]{1,5}\)?[-.\s/]?){1,4}[0-9]{2,4})|(?:\+?1[-.\s]?)?\(?[2-9][0-9]{2}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}|(?:0[0-9][-.\s/]?(?:\(?[0-9]{1,5}\)?[-.\s/]?){1,4}[0-9]{2,4})"#),
        ("IPV4", r#"(?-u:\b)(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?-u:\b)"#),
        ("IPV6", r#"(?-u:\b)(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}(?-u:\b)"#),
        ("IBAN", r#"(?-u:\b)[A-Z]{2}[0-9]{2}[\s]?[[0-9]A-Z]{4}[\s]?(?:[[0-9]A-Z]{4}[\s]?){1,7}[[0-9]A-Z]{1,4}(?-u:\b)"#),
        ("HOME_FOLDER", r#"(?:\/home\/|\/Users\/|[A-Z]:\\Users\\)[a-zA-Z0-9_.-]{1,64}|PS [A-Z]:\\Users\\[a-zA-Z0-9_.-]{1,64}|PS \/(?:home|Users)\/[a-zA-Z0-9_.-]{1,64}"#),
        ("USER_AT_HOSTNAME", r#"(?-u:\b)[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,31}@[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}"#),
        ("MAC_ADDRESS", r#"(?-u:\b)(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?-u:\b)"#),
        ("PASSPORT", r#"(?i)(?:passport|reisepass|passeport|pass(?:port)?[\s._-]?(?:no|nr|num(?:ber)?|#))[:\s#=]*([A-Z0-9]{6,9})(?-u:\b)"#),
        ("TAX_ID", r#"(?i)(?-u:\b)(?:AT ?U[0-9]{8}|BE ?0?[0-9]{9,10}|BG ?[0-9]{9,10}|HR ?[0-9]{11}|CY ?[0-9]{8}[A-Z]|CZ ?[0-9]{8,10}|DK ?[0-9]{8}|EE ?[0-9]{9}|FI ?[0-9]{8}|FR ?[0-9A-Z]{2}[0-9]{9}|DE ?[0-9]{9}|EL ?[0-9]{9}|HU ?[0-9]{8}|IE ?[0-9]{7}[A-Z]{1,2}|IT ?[0-9]{11}|LV ?[0-9]{11}|LT ?[0-9]{9,12}|LU ?[0-9]{8}|MT ?[0-9]{8}|NL ?[0-9]{9}B[0-9]{2}|PL ?[0-9]{10}|PT ?[0-9]{9}|RO ?[0-9]{2,10}|SK ?[0-9]{10}|SI ?[0-9]{8}|ES ?[A-Z0-9][0-9]{7}[A-Z0-9]|SE ?[0-9]{12}|GB ?[0-9]{9}(?:[0-9]{3})?)(?-u:\b)|(?:tax[\s_-]?(?:id|number|no|nr)|steuer(?:nummer|identifikationsnummer|nr|ident(?:nummer)?)|tin[\s_-]?(?:number|no|nr)|vat[\s_-]?(?:id|number|no|nr)|tax[\s_-]?identification(?:[\s_-]?number)?)[:\s#=]+([A-Z0-9\s/-]{5,20})"#),
        ("VEHICLE_PLATE", r#"(?i)(?:license[\s_-]?plate|plate[\s_-]?(?:number|no|nr)|kennzeichen|nummernschild|kfz[\s_-]?kennzeichen|immatriculation|registration[\s_-]?(?:number|no|nr|plate)|vrm|numberplate)[:\s#=]*([A-Z0-9]{1,4}[\s-]?[A-Z0-9]{1,4}[\s-]?[A-Z0-9]{1,6})(?-u:\b)"#),
        ("CRYPTO_WALLET", r#"(?-u:\b)(?:bc1[a-z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|0x[0-9a-fA-F]{40})(?-u:\b)"#),
        ];
        table.into_iter().map(|(kind, pattern)| Pattern { kind, regex: Regex::new(pattern).expect("fixed canonical PII pattern") }).collect()
    })
}

fn regex(pattern: &'static str) -> Regex {
    static CACHE: OnceLock<Mutex<HashMap<&'static str, Regex>>> = OnceLock::new();
    let mut cache = CACHE
        .get_or_init(|| Mutex::new(HashMap::new()))
        .lock()
        .unwrap_or_else(|error| error.into_inner());
    cache
        .entry(pattern)
        .or_insert_with(|| Regex::new(pattern).expect("fixed privacy pattern"))
        .clone()
}
fn category(kind: &str) -> &str {
    match kind {
        "EMAIL" => "email_addresses",
        "ADDRESS" => "addresses",
        "PHONE" => "phone_numbers",
        "CREDIT_CARD" => "credit_card_numbers",
        "SSN" => "social_security_numbers",
        "IBAN" => "iban_bank_account",
        "TAX_ID" => "tax_id_vat",
        "PASSPORT" => "passport_numbers",
        "CRYPTO_WALLET" => "crypto_wallets",
        "VEHICLE_PLATE" => "vehicle_plate",
        "GENERIC_SECRET" => "generic_secrets",
        "PRIVATE_KEY" => "private_keys",
        "JWT" => "jwt_tokens",
        "IPV4" | "IPV6" => "ip_addresses",
        "HOME_FOLDER" => "home_folder",
        "USER_AT_HOSTNAME" => "user_at_hostname",
        "MAC_ADDRESS" => "mac_addresses",
        _ => "api_keys",
    }
}
fn digits(value: &str) -> Vec<u8> {
    value
        .bytes()
        .filter(u8::is_ascii_digit)
        .map(|c| c - b'0')
        .collect()
}
fn valid(kind: &str, value: &str, next: Option<char>) -> bool {
    match kind {
        "CREDIT_CARD" => {
            let digits = digits(value);
            (13..=19).contains(&digits.len())
                && digits
                    .iter()
                    .rev()
                    .enumerate()
                    .map(|(i, d)| {
                        let n = if i % 2 == 1 { *d * 2 } else { *d };
                        u32::from(if n > 9 { n - 9 } else { n })
                    })
                    .sum::<u32>()
                    % 10
                    == 0
        }
        "SSN" => {
            let d = digits(value);
            d.len() == 9 && {
                let area = u32::from(d[0]) * 100 + u32::from(d[1]) * 10 + u32::from(d[2]);
                area != 0
                    && area != 666
                    && area < 900
                    && d[3..5].iter().any(|v| *v != 0)
                    && d[5..].iter().any(|v| *v != 0)
            }
        }
        "IBAN" => {
            let cleaned: Vec<u8> = value
                .bytes()
                .filter(|c| !c.is_ascii_whitespace())
                .map(|c| c.to_ascii_uppercase())
                .collect();
            if !(15..=34).contains(&cleaned.len()) {
                return false;
            }
            let mut remainder = 0u32;
            for c in cleaned[4..].iter().chain(&cleaned[..4]) {
                if c.is_ascii_digit() {
                    remainder = (remainder * 10 + u32::from(*c - b'0')) % 97;
                } else if c.is_ascii_uppercase() {
                    remainder = (remainder * 100 + u32::from(*c - b'A') + 10) % 97;
                } else {
                    return false;
                }
            }
            remainder == 1
        }
        "PHONE" => {
            let count = digits(value).len();
            let value = value.trim();
            if !(7..=15).contains(&count) {
                return false;
            }
            !regex(r"^(?:[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}|[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4}|(?:19|20)[0-9]{6}|0[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{1,2})$").is_match(value)
        }
        "IPV4" => {
            value != "127.0.0.1"
                && value != "0.0.0.0"
                && !["192.168.", "10.", "172."]
                    .iter()
                    .any(|prefix| value.starts_with(prefix))
        }
        "HOME_FOLDER" => {
            if next.is_some_and(|c| c.is_ascii_alphanumeric() || c == '_') {
                return false;
            }
            let user = value
                .trim_start_matches("PS ")
                .replace('\\', "/")
                .rsplit('/')
                .next()
                .unwrap_or("")
                .to_lowercase();
            ![
                "root", "admin", "shared", "public", "default", "guest", "nobody", "daemon",
                "www-data", "ubuntu",
            ]
            .contains(&user.as_str())
        }
        "USER_AT_HOSTNAME" => {
            if !next.is_some_and(|c| c.is_whitespace() || c == ':' || c == '~') {
                return false;
            }
            let (user, host) = value.split_once('@').unwrap_or(("", ""));
            ![
                "github.com",
                "gitlab.com",
                "bitbucket.org",
                "ssh.dev.azure.com",
            ]
            .contains(&host.to_lowercase().as_str())
                && ![
                    "root", "admin", "guest", "nobody", "daemon", "www-data", "noreply",
                    "no-reply", "git", "svn", "user", "test", "ubuntu",
                ]
                .contains(&user.to_lowercase().as_str())
        }
        "MAC_ADDRESS" => {
            let v = value.replace([':', '-'], "").to_uppercase();
            v != "000000000000" && v != "FFFFFFFFFFFF"
        }
        _ => true,
    }
}

/// Union of nonempty byte intervals. Kind/selection order remains in `Range`;
/// this index only answers shielding queries in logarithmic time.
#[derive(Clone, Default)]
struct RangeIndex(BTreeMap<usize, usize>);
impl RangeIndex {
    // Regex find_iter supplies ordered disjoint intervals. Preserve their
    // boundaries for exact URL containment queries as well as overlap checks.
    fn from_ranges(ranges: &[Range]) -> Self {
        Self(
            ranges
                .iter()
                .map(|range| (range.start, range.end))
                .collect(),
        )
    }
    fn contains(&self, start: usize, end: usize) -> bool {
        self.0
            .range(..=start)
            .next_back()
            .is_some_and(|(_, previous_end)| end <= *previous_end)
    }
    fn overlaps(&self, start: usize, end: usize) -> bool {
        self.0
            .range(..end)
            .next_back()
            .is_some_and(|(_, previous_end)| start < *previous_end)
    }
    fn insert(&mut self, mut start: usize, mut end: usize) {
        if start >= end {
            return;
        }
        if let Some((&previous_start, &previous_end)) = self.0.range(..=start).next_back()
            && previous_end >= start
        {
            start = previous_start;
            end = end.max(previous_end);
            self.0.remove(&previous_start);
        }
        while let Some((&next_start, &next_end)) = self.0.range(start..=end).next() {
            end = end.max(next_end);
            self.0.remove(&next_start);
        }
        self.0.insert(start, end);
    }
    fn uncovered(&self, range: Range) -> Vec<Range> {
        let mut cursor = range.start;
        if let Some((_, &previous_end)) = self.0.range(..=cursor).next_back() {
            cursor = cursor.max(previous_end.min(range.end));
        }
        let mut parts = Vec::new();
        for (&start, &end) in self.0.range(range.start..range.end) {
            if cursor < start {
                parts.push(Range {
                    start: cursor,
                    end: start,
                    ..range.clone()
                });
            }
            cursor = cursor.max(end.min(range.end));
        }
        if cursor < range.end {
            parts.push(Range {
                start: cursor,
                ..range
            });
        }
        parts
    }
}
fn ranges_for(pattern: &Regex, text: &str) -> Vec<Range> {
    pattern
        .find_iter(text)
        .map(|m| Range {
            start: m.start(),
            end: m.end(),
            kind: String::new(),
        })
        .collect()
}
// Hand scanners, not regex: restore runs on every rendered message (see placeholder.rs).
fn valid_token(token: &str) -> bool {
    placeholder::is_token(token)
}
fn generated_token(token: &str) -> bool {
    placeholder::is_generated(token)
}
fn legacy_token(token: &str) -> bool {
    let re = regex(r"^\[([A-Z_]+)_[0-9]+_[A-Za-z0-9]{1,3}\]$");
    re.captures(token).is_some_and(|c| {
        c.get(1).is_some_and(|m| {
            patterns().iter().any(|p| p.kind == m.as_str()) || m.as_str() == "ADDRESS"
        })
    })
}

fn append_privacy(output: &mut String, value: &str, limit: Option<usize>) -> Result<()> {
    let length = output.len().checked_add(value.len()).ok_or(Error::Invalid(
        "Local privacy output exceeds the supported limit.",
    ))?;
    if limit.is_some_and(|maximum| length > maximum) {
        return Err(Error::Invalid(
            "Local privacy output exceeds the supported limit.",
        ));
    }
    output.push_str(value);
    Ok(())
}

/// Restore in one pass: originals containing token spellings are never expanded again.
pub fn restore(text: &str, mappings: &[Value]) -> Result<String> {
    restore_internal(text, mappings, None, false)
}
/// Viewing a bounded page cannot know mappings defined on omitted messages.
/// This never changes strict full-history/send/local-privacy restoration.
pub(crate) fn restore_page(text: &str, mappings: &[Value]) -> Result<String> {
    restore_internal(text, mappings, Some(LOCAL_PRIVACY_MAX_TEXT_BYTES), true)
}
pub(crate) fn restore_page_refs(text: &str, mappings: &[&Value]) -> Result<String> {
    restore_borrowed(
        text,
        mappings.iter().copied(),
        Some(LOCAL_PRIVACY_MAX_TEXT_BYTES),
        true,
    )
}
fn restore_internal(
    text: &str,
    mappings: &[Value],
    output_limit: Option<usize>,
    unknown_literal: bool,
) -> Result<String> {
    restore_borrowed(text, mappings.iter(), output_limit, unknown_literal)
}
fn restore_borrowed<'a>(
    text: &str,
    mappings: impl IntoIterator<Item = &'a Value>,
    output_limit: Option<usize>,
    unknown_literal: bool,
) -> Result<String> {
    let mut count = 0usize;
    let mut originals: HashMap<&str, &str> = HashMap::new();
    let mut ambiguous = HashSet::new();
    for mapping in mappings {
        count += 1;
        if count > 10_000 {
            return Err(Error::Invalid("Privacy mapping limit exceeded."));
        }
        let Some(token) = mapping
            .get("placeholder")
            .and_then(Value::as_str)
            .filter(|s| valid_token(s))
        else {
            continue;
        };
        let Some(original) = mapping
            .get("original")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
        else {
            continue;
        };
        if originals
            .insert(token, original)
            .is_some_and(|previous| previous != original)
        {
            ambiguous.insert(token);
        }
    }
    let mut result = String::with_capacity(text.len());
    let mut cursor = 0;
    for (start, end) in placeholder::find(text) {
        append_privacy(&mut result, &text[cursor..start], output_limit)?;
        let token = &text[start..end];
        if ambiguous.contains(token) {
            return Err(Error::Invalid(
                "A privacy placeholder has conflicting mappings.",
            ));
        }
        if let Some(original) = originals.get(token) {
            append_privacy(&mut result, original, output_limit)?;
        } else if !unknown_literal && (generated_token(token) || legacy_token(token)) {
            return Err(Error::Invalid(
                "A privacy placeholder mapping is unavailable.",
            ));
        } else {
            append_privacy(&mut result, token, output_limit)?;
        }
        cursor = end;
    }
    append_privacy(&mut result, &text[cursor..], output_limit)?;
    Ok(result)
}

pub fn prepare(text: &str, memories: &[Value], existing: &[Value]) -> Result<PreparedPrivacy> {
    prepare_internal(text, memories, existing, None, None)
}
fn prepare_internal(
    text: &str,
    memories: &[Value],
    existing: &[Value],
    output_limit: Option<usize>,
    mapping_limit: Option<usize>,
) -> Result<PreparedPrivacy> {
    if text.len() > 16 * 1024 * 1024 || existing.len() > 10_000 {
        return Err(Error::Invalid("Privacy input exceeds the supported limit."));
    }
    let mut mappings: Vec<Value> = Vec::new();
    let mut by_token: HashMap<String, usize> = HashMap::new();
    let mut ambiguous = HashSet::new();
    for value in existing {
        let Some(original) = value
            .get("original")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
        else {
            continue;
        };
        let Some(token) = value
            .get("placeholder")
            .and_then(Value::as_str)
            .filter(|s| valid_token(s))
        else {
            continue;
        };
        if let Some(index) = by_token.get(token) {
            if mappings[*index]["original"] != original {
                ambiguous.insert(token.to_owned());
                mappings.push(value.clone());
            }
        } else {
            by_token.insert(token.to_owned(), mappings.len());
            mappings.push(value.clone());
        }
    }
    let settings = memories
        .iter()
        .find(|m| m["app_id"] == "privacy" && m["item_type"] == "pii_detection_settings")
        .and_then(|m| m.get("data"));
    let enabled = settings
        .and_then(|s| s.get("masterEnabled"))
        .and_then(Value::as_bool)
        != Some(false);
    let disabled: HashSet<&str> = settings
        .and_then(|s| s.get("categories"))
        .and_then(Value::as_object)
        .map(|m| {
            m.iter()
                .filter(|(_, v)| v.as_bool() == Some(false))
                .map(|(k, _)| k.as_str())
                .collect()
        })
        .unwrap_or_default();
    let tokens = ranges_for(&regex(r"\[[A-Za-z][A-Za-z0-9_]*\]"), text);
    let token_index = RangeIndex::from_ranges(&tokens);
    let mut accepted = RangeIndex::default();
    let mut ranges = Vec::new();
    for r in &tokens {
        let token = &text[r.start..r.end];
        if by_token.contains_key(token) {
            if ambiguous.contains(token) {
                return Err(Error::Invalid(
                    "A privacy placeholder has conflicting mappings.",
                ));
            }
        } else if generated_token(token) || legacy_token(token) {
            accepted.insert(r.start, r.end);
            ranges.push(r.clone());
        }
    }
    let mut known: Vec<&Value> = mappings.iter().collect();
    known.sort_by_key(|m| {
        std::cmp::Reverse(m["original"].as_str().unwrap_or("").encode_utf16().count())
    });
    for mapping in known {
        let original = mapping["original"].as_str().unwrap_or("");
        for (start, _) in text.match_indices(original) {
            let end = start + original.len();
            if !token_index.overlaps(start, end) && !accepted.overlaps(start, end) {
                accepted.insert(start, end);
                ranges.push(Range {
                    start,
                    end,
                    kind: mapping["type"].as_str().unwrap_or("OTHER").into(),
                });
            }
        }
    }
    if enabled {
        let urls = ranges_for(&regex(r"https?://[^\s]+"), text);
        let url_index = RangeIndex::from_ranges(&urls);
        let identifiers = ranges_for(
            &regex(
                r"(?i)(?-u:\b)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?-u:\b)|(?-u:\b)[0-9a-f]{40,64}(?-u:\b)|\[[A-Z][A-Z0-9_]*\]",
            ),
            text,
        );
        let identifier_index = RangeIndex::from_ranges(&identifiers);
        if text.encode_utf16().count() >= 6 {
            for pattern in patterns() {
                if disabled.contains(category(pattern.kind)) {
                    continue;
                }
                for matched in pattern.regex.find_iter(text) {
                    let (start, end) = (matched.start(), matched.end());
                    if url_index.contains(start, end)
                        || token_index.overlaps(start, end)
                        || accepted.overlaps(start, end)
                        || pattern.kind == "PHONE" && identifier_index.overlaps(start, end)
                        || !valid(pattern.kind, matched.as_str(), text[end..].chars().next())
                    {
                        continue;
                    }
                    accepted.insert(start, end);
                    ranges.push(Range {
                        start,
                        end,
                        kind: pattern.kind.into(),
                    });
                }
            }
        }
        let mut personal = Vec::new();
        let mut personal_index = RangeIndex::default();
        for memory in memories
            .iter()
            .filter(|m| m["app_id"] == "privacy" && m["item_type"] == "personal_data_entry")
        {
            let data = &memory["data"];
            if data["enabled"] != true
                || data["textToHide"].as_str().is_none_or(str::is_empty)
                || data["replaceWith"].as_str().is_none_or(str::is_empty)
            {
                continue;
            }
            let mut values = vec![data["textToHide"].as_str().unwrap()];
            if let Some(lines) = data["addressLines"].as_object() {
                values.extend(lines.values().filter_map(Value::as_str));
            }
            for value in values.into_iter().filter(|v| !v.trim().is_empty()) {
                let search = Regex::new(&format!("(?i){}", regex::escape(value)))
                    .map_err(|_| Error::Invalid("Personal privacy data could not be processed."))?;
                for m in search.find_iter(text) {
                    if !personal_index.overlaps(m.start(), m.end()) {
                        personal_index.insert(m.start(), m.end());
                        personal.push(Range {
                            start: m.start(),
                            end: m.end(),
                            kind: "EMAIL".into(),
                        });
                    }
                }
            }
        }
        // Preserve the same uncovered personal-data suffixes, querying only
        // intersecting shield intervals instead of scanning every prior range.
        if !personal.is_empty() {
            let mut protected = token_index.clone();
            for range in &ranges {
                protected.insert(range.start, range.end);
            }
            for range in personal {
                let fragments = protected.uncovered(range);
                for fragment in &fragments {
                    protected.insert(fragment.start, fragment.end);
                }
                ranges.extend(fragments);
            }
        }
    }
    ranges.sort_by_key(|r| r.start);
    let mut output = String::with_capacity(text.len());
    let mut cursor = 0;
    for range in ranges {
        append_privacy(&mut output, &text[cursor..range.start], output_limit)?;
        for part in text[range.start..range.end].split_inclusive('\n') {
            let (part, newline) = if let Some(part) = part.strip_suffix("\r\n") {
                (part, "\r\n")
            } else if let Some(part) = part.strip_suffix('\n') {
                (part, "\n")
            } else {
                (part, "")
            };
            if !part.is_empty() {
                if let Some(token) = mappings
                    .iter()
                    .find(|m| {
                        m["original"] == part
                            && m["placeholder"]
                                .as_str()
                                .is_some_and(|p| !ambiguous.contains(p))
                    })
                    .and_then(|m| m["placeholder"].as_str())
                {
                    // The caller token may be very long. Check its borrowed
                    // length before copying any replacement bytes.
                    append_privacy(&mut output, token, output_limit)?;
                } else {
                    if mapping_limit.is_some_and(|maximum| mappings.len() >= maximum) {
                        return Err(Error::Invalid(
                            "Local privacy output exceeds the supported limit.",
                        ));
                    }
                    let token = format!(
                        "[OM_PII_{}]",
                        uuid::Uuid::new_v4().simple().to_string().to_uppercase()
                    );
                    append_privacy(&mut output, &token, output_limit)?;
                    mappings.push(json!({"original":part,"placeholder":token,"type":if range.kind.is_empty(){"OTHER"}else{&range.kind}}));
                }
            }
            append_privacy(&mut output, newline, output_limit)?;
        }
        cursor = range.end;
    }
    if mappings.len() > 10_000 {
        return Err(Error::Invalid("Privacy mapping limit exceeded."));
    }
    append_privacy(&mut output, &text[cursor..], output_limit)?;
    for mapping in &mut mappings {
        if mapping.get("type").is_none() {
            mapping["type"] = json!("OTHER");
        }
    }
    Ok(PreparedPrivacy {
        text: output,
        mappings,
    })
}

/// Maximum UTF-8 text bytes accepted by the synchronized local privacy facade.
pub const LOCAL_PRIVACY_MAX_TEXT_BYTES: usize = 1024 * 1024;
/// Maximum canonical JSON operation bytes, including caller mappings.
pub const LOCAL_PRIVACY_MAX_INPUT_BYTES: usize = 4 * 1024 * 1024;
/// Maximum combined memory and existing-mapping entries for local preparation.
pub const LOCAL_PRIVACY_MAX_ENTRIES: usize = 1024;

fn local_json_valid(value: &Value, depth: usize) -> bool {
    if depth > 64 {
        return false;
    }
    match value {
        Value::Array(values) => values.iter().all(|v| local_json_valid(v, depth + 1)),
        Value::Object(values) => values.values().all(|v| local_json_valid(v, depth + 1)),
        Value::Number(n) => n.as_f64().is_some_and(|n| {
            n.is_finite() && (n.fract() != 0.0 || n.abs() <= 9_007_199_254_740_991.0)
        }),
        _ => true,
    }
}

// Counting uses a single Rust JSON representation: all numbers serialize as
// finite f64, and both signs of zero serialize as 0.0. Foreign wire formatting
// never defines the canonical budget. No input values are cloned here.
struct CanonicalValue<'a>(&'a Value);
impl serde::Serialize for CanonicalValue<'_> {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        use serde::ser::{SerializeMap, SerializeSeq};
        match self.0 {
            Value::Null => serializer.serialize_unit(),
            Value::Bool(v) => serializer.serialize_bool(*v),
            Value::String(v) => serializer.serialize_str(v),
            Value::Number(v) => {
                let number = v.as_f64().ok_or_else(|| {
                    <S::Error as serde::ser::Error>::custom("Invalid typed privacy input.")
                })?;
                serializer.serialize_f64(if number == 0.0 { 0.0 } else { number })
            }
            Value::Array(values) => {
                let mut seq = serializer.serialize_seq(Some(values.len()))?;
                for value in values {
                    seq.serialize_element(&CanonicalValue(value))?;
                }
                seq.end()
            }
            Value::Object(values) => {
                let mut map = serializer.serialize_map(Some(values.len()))?;
                for (key, value) in values {
                    map.serialize_entry(key, &CanonicalValue(value))?;
                }
                map.end()
            }
        }
    }
}
struct CanonicalSlice<'a>(&'a [Value]);
impl serde::Serialize for CanonicalSlice<'_> {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        use serde::ser::SerializeSeq;
        let mut seq = serializer.serialize_seq(Some(self.0.len()))?;
        for value in self.0 {
            seq.serialize_element(&CanonicalValue(value))?;
        }
        seq.end()
    }
}
#[derive(serde::Serialize)]
#[serde(tag = "operation", rename_all = "snake_case")]
enum LocalInput<'a> {
    Prepare {
        text: &'a str,
        memories: CanonicalSlice<'a>,
        existing_mappings: CanonicalSlice<'a>,
        enhanced: bool,
    },
    Restore {
        text: &'a str,
        mappings: CanonicalSlice<'a>,
    },
}
struct BudgetWriter {
    written: usize,
}
impl std::io::Write for BudgetWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > LOCAL_PRIVACY_MAX_INPUT_BYTES.saturating_sub(self.written) {
            return Err(std::io::Error::other(
                "Local privacy input exceeds the supported limit.",
            ));
        }
        self.written += bytes.len();
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
fn borrowed_bounds(text: &str, first: &[Value], second: &[Value]) -> Result<()> {
    if text.len() > LOCAL_PRIVACY_MAX_TEXT_BYTES
        || first.len().saturating_add(second.len()) > LOCAL_PRIVACY_MAX_ENTRIES
    {
        return Err(Error::Invalid(
            "Local privacy input exceeds the supported limit.",
        ));
    }
    // Envelope root=0, arrays=1, each caller entry=2. Validation precedes any
    // serialization and borrows values, including direct Rust caller trees.
    if !first.iter().chain(second).all(|v| local_json_valid(v, 2)) {
        return Err(Error::Invalid("Invalid typed privacy input."));
    }
    Ok(())
}
fn canonical_size(input: LocalInput<'_>) -> Result<()> {
    serde_json::to_writer(BudgetWriter { written: 0 }, &input)
        .map_err(|_| Error::Invalid("Local privacy input exceeds the supported limit."))
}
fn restore_bounds(text: &str, mappings: &[Value]) -> Result<()> {
    borrowed_bounds(text, mappings, &[])?;
    canonical_size(LocalInput::Restore {
        text,
        mappings: CanonicalSlice(mappings),
    })
}

/// Bounded public SDK preparation shared by Rust, npm and Python.
/// Limits are 1 MiB UTF-8 text, 4 MiB canonical JSON operation and 1024 combined
/// memory/mapping entries. Canonical counting streams borrowed input through
/// Rust's f64 JSON number representation, normalizing either zero sign to 0.0.
/// Values allow at most 64 nesting levels and integer-valued numbers only in
/// the JavaScript safe-integer range. A separate 16 MiB foreign transport cap
/// bounds decoding; foreign JSON spelling never defines canonical size.
/// Prepared UTF-8 output is capped at 1 MiB and checked before every append;
/// generated mappings are capped before insertion. Generated results must fit
/// the same restoration budgets before returning.
/// Existing lower-level `prepare` remains compatible.
pub fn prepare_local(
    text: &str,
    memories: &[Value],
    existing_mappings: &[Value],
    options: &PrivacyOptions,
) -> Result<PreparedPrivacy> {
    borrowed_bounds(text, memories, existing_mappings)?;
    canonical_size(LocalInput::Prepare {
        text,
        memories: CanonicalSlice(memories),
        existing_mappings: CanonicalSlice(existing_mappings),
        enhanced: options.enhanced,
    })?;
    options.verify()?;
    let prepared = prepare_internal(
        text,
        memories,
        existing_mappings,
        Some(LOCAL_PRIVACY_MAX_TEXT_BYTES),
        Some(LOCAL_PRIVACY_MAX_ENTRIES),
    )?;
    restore_bounds(&prepared.text, &prepared.mappings)?;
    Ok(prepared)
}

/// Bounded one-pass restoration with the same input budgets as preparation.
/// Restored UTF-8 output is capped at 1 MiB. Every original/token/literal append
/// checks growth before copying; expansion fails closed and is never truncated.
pub fn restore_local(text: &str, mappings: &[Value]) -> Result<String> {
    restore_bounds(text, mappings)?;
    restore_internal(text, mappings, Some(LOCAL_PRIVACY_MAX_TEXT_BYTES), false)
}

#[cfg(test)]
mod local_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=pii.surface.semantic-parity
    #[test]
    fn synchronized_limits_accept_exact_boundaries_and_reject_one_over() {
        let text = "x".repeat(LOCAL_PRIVACY_MAX_TEXT_BYTES);
        assert_eq!(restore_local(&text, &[]).unwrap(), text);
        assert!(restore_local(&(text + "x"), &[]).is_err());
        let mappings = vec![Value::Null; LOCAL_PRIVACY_MAX_ENTRIES];
        assert_eq!(restore_local("plain", &mappings).unwrap(), "plain");
        assert!(restore_local("plain", &vec![Value::Null; LOCAL_PRIVACY_MAX_ENTRIES + 1]).is_err());
        assert!(
            prepare_local(
                "plain",
                &[Value::Null],
                &mappings,
                &PrivacyOptions::default()
            )
            .is_err()
        );
        let envelope = json!({"operation":"restore","text":"","mappings":[""]});
        let overhead = serde_json::to_vec(&envelope).unwrap().len();
        let payload = "x".repeat(LOCAL_PRIVACY_MAX_INPUT_BYTES - overhead);
        assert_eq!(restore_local("", &[json!(payload)]).unwrap(), "");
        assert!(restore_local("", &[json!(payload + "x")]).is_err());
    }

    // contract-test: supporting surface=sdks.rust assertions=pii.surface.semantic-parity
    #[test]
    fn direct_borrowed_values_are_validated_before_streamed_counting() {
        let mut deep = Value::Null;
        for _ in 0..256 {
            deep = Value::Array(vec![deep]);
        }
        let error = restore_local("plain", &[deep]).err().unwrap();
        assert!(matches!(
            error,
            Error::Invalid("Invalid typed privacy input.")
        ));
        let huge = json!("x".repeat(LOCAL_PRIVACY_MAX_INPUT_BYTES + 1));
        assert!(restore_local("plain", &[huge]).is_err());
        for number in [
            json!(9_007_199_254_740_992_u64),
            json!(-9_007_199_254_740_992_i64),
        ] {
            assert!(restore_local("plain", &[number]).is_err());
        }
    }

    // contract-test: supporting surface=sdks.rust assertions=pii.surface.semantic-parity
    #[test]
    fn integer_float_exponent_and_negative_zero_use_one_number_budget() {
        let expected =
            serde_json::to_vec(&json!({"operation":"restore","text":"plain","mappings":[0.0,""]}))
                .unwrap()
                .len();
        let padding = "x".repeat(LOCAL_PRIVACY_MAX_INPUT_BYTES - expected);
        for number in [
            json!(0),
            json!(0.0),
            serde_json::from_str::<Value>("0e0").unwrap(),
            json!(-0.0),
        ] {
            assert_eq!(
                restore_local("plain", &[number.clone(), json!(padding)]).unwrap(),
                "plain"
            );
            assert!(restore_local("plain", &[number, json!(padding.clone() + "x")]).is_err());
        }
    }

    // contract-test: supporting surface=sdks.rust assertions=pii.surface.semantic-parity
    #[test]
    fn preparation_refuses_unrestorable_generated_output_budgets() {
        let maps:Vec<Value>=(0..LOCAL_PRIVACY_MAX_ENTRIES).map(|i|json!({"original":format!("unrelated-{i}"),"placeholder":format!("[KEEP_{i}]")})).collect();
        assert!(prepare_local("a@b.co", &[], &maps, &PrivacyOptions::default()).is_err());
        assert!(
            prepare_local(
                &"a@b.co ".repeat(25_000),
                &[],
                &[],
                &PrivacyOptions::default()
            )
            .is_err()
        );
        let base = json!({"operation":"prepare","text":"a@b.co","memories":[],"existing_mappings":[{"original":"unrelated","placeholder":"[KEEP]","padding":""}],"enhanced":false});
        let padding =
            "x".repeat(LOCAL_PRIVACY_MAX_INPUT_BYTES - serde_json::to_vec(&base).unwrap().len());
        let maps = [json!({"original":"unrelated","placeholder":"[KEEP]","padding":padding})];
        assert!(prepare_local("a@b.co", &[], &maps, &PrivacyOptions::default()).is_err());
        let prepared = prepare_local(
            &"a@b.co ".repeat(24_966),
            &[],
            &[],
            &PrivacyOptions::default(),
        )
        .unwrap();
        assert_eq!(
            restore_local(&prepared.text, &prepared.mappings).unwrap(),
            "a@b.co ".repeat(24_966)
        );
    }

    // contract-test: supporting surface=sdks.rust assertions=pii.surface.semantic-parity
    #[test]
    fn replacement_growth_is_checked_before_copies_in_both_directions() {
        let token = format!("[{}]", "A".repeat(LOCAL_PRIVACY_MAX_TEXT_BYTES - 2));
        let maps = [json!({"original":"x","placeholder":token})];
        let prepared = prepare_local("x", &[], &maps, &PrivacyOptions::default()).unwrap();
        assert_eq!(prepared.text.len(), LOCAL_PRIVACY_MAX_TEXT_BYTES);
        assert_eq!(
            restore_local(&prepared.text, &prepared.mappings).unwrap(),
            "x"
        );
        assert!(
            prepare_local(&"x".repeat(524_288), &[], &maps, &PrivacyOptions::default()).is_err()
        );
        let maps =
            [json!({"original":"y".repeat(2*LOCAL_PRIVACY_MAX_TEXT_BYTES),"placeholder":"[X]"})];
        assert!(restore_local(&"[X]".repeat(349_525), &maps).is_err());
        let maps =
            [json!({"original":"y".repeat(LOCAL_PRIVACY_MAX_TEXT_BYTES),"placeholder":"[X]"})];
        assert_eq!(
            restore_local("[X]", &maps).unwrap().len(),
            LOCAL_PRIVACY_MAX_TEXT_BYTES
        );
        assert!(restore_local("[X][X]", &maps).is_err());
        // Existing low-level callers retain the original unbounded behavior.
        let maps = [json!({"original":"yyyy","placeholder":"[X]"})];
        assert_eq!(restore("[X][X]", &maps).unwrap(), "yyyyyyyy");
        assert!(restore_internal("[X][X]", &maps, Some(7), false).is_err());
        let maps = [json!({"original":"x","placeholder":"[LONG]"})];
        assert_eq!(prepare("xx", &[], &maps).unwrap().text, "[LONG][LONG]");
        assert!(prepare_internal("xx", &[], &maps, Some(11), Some(1024)).is_err());
    }

    // contract-test: supporting surface=sdks.rust assertions=pii.surface.semantic-parity
    #[test]
    fn interval_queries_and_fragments_match_naive_selection_for_all_insertion_orders() {
        // UTF-8 boundaries in a, é, 🙂, z; intervals include adjacency,
        // containment and overlap. Queries and stored intervals are nonempty.
        let boundaries = [0, 1, 3, 7, 8];
        let candidates = [(0, 1), (1, 3), (3, 7), (7, 8), (1, 7), (0, 3)];
        fn check_order(order: &[(usize, usize)], boundaries: &[usize]) {
            let mut index = RangeIndex::default();
            let mut naive: Vec<(usize, usize)> = Vec::new();
            for &(start, end) in order {
                index.insert(start, end);
                naive.push((start, end));
                for &start in boundaries {
                    for &end in boundaries {
                        if start >= end {
                            continue;
                        }
                        assert_eq!(
                            index.overlaps(start, end),
                            naive.iter().any(|&(a, b)| start < b && end > a)
                        );
                        let mut parts = vec![(start, end)];
                        for &(a, b) in &naive {
                            parts = parts
                                .into_iter()
                                .flat_map(|(s, e)| {
                                    if s >= b || e <= a {
                                        return vec![(s, e)];
                                    }
                                    let mut output = vec![];
                                    if s < a {
                                        output.push((s, a));
                                    }
                                    if e > b {
                                        output.push((b, e));
                                    }
                                    output
                                })
                                .collect();
                        }
                        let observed = index
                            .uncovered(Range {
                                start,
                                end,
                                kind: "synthetic".into(),
                            })
                            .into_iter()
                            .map(|r| (r.start, r.end))
                            .collect::<Vec<_>>();
                        assert_eq!(observed, parts);
                    }
                }
            }
        }
        fn permutations(
            remaining: &mut [(usize, usize)],
            prefix: &mut Vec<(usize, usize)>,
            boundaries: &[usize],
        ) {
            if remaining.is_empty() {
                check_order(prefix, boundaries);
                return;
            }
            for i in 0..remaining.len() {
                remaining.swap(0, i);
                prefix.push(remaining[0]);
                permutations(&mut remaining[1..], prefix, boundaries);
                let _ = prefix.pop();
                remaining.swap(0, i);
            }
        }
        let mut candidates = candidates;
        permutations(&mut candidates, &mut Vec::new(), &boundaries);
        let disjoint = [
            Range {
                start: 0,
                end: 1,
                kind: String::new(),
            },
            Range {
                start: 1,
                end: 3,
                kind: String::new(),
            },
            Range {
                start: 7,
                end: 8,
                kind: String::new(),
            },
        ];
        let index = RangeIndex::from_ranges(&disjoint);
        for &start in &boundaries {
            for &end in &boundaries {
                if start < end {
                    assert_eq!(
                        index.contains(start, end),
                        disjoint.iter().any(|r| start >= r.start && end <= r.end)
                    );
                }
            }
        }
    }

    // contract-test: supporting surface=sdks.rust assertions=pii.surface.semantic-parity
    #[test]
    fn large_existing_token_set_stays_shielded_during_known_replacement() {
        let text = "[X]".repeat(100_000) + "x";
        let maps = [json!({"original":"x","placeholder":"[X]"})];
        let output = prepare_local(&text, &[], &maps, &PrivacyOptions::default()).unwrap();
        assert_eq!(output.text, "[X]".repeat(100_001));
        assert_eq!(output.mappings.len(), 1);
        assert_eq!(
            restore_local(&output.text, &output.mappings).unwrap(),
            "x".repeat(100_001)
        );
    }
}
