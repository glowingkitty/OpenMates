//! PII pattern table of the web composer: regexes, validators, placeholder
//! prefixes, labels and settings categories. Port of `PII_PATTERNS`,
//! `PII_TYPE_TO_CATEGORY` and `getPIILabel` in `piiDetectionService.ts`.
//! JS regex quirks are kept: ASCII-only `\b`/`\d`/`/i`, JS `\s` set, and the
//! two lookaheads (`HOME_FOLDER`, `USER_AT_HOSTNAME`) are applied by `fit`.
//! spec: specifications/features/pii-protection#pii.composer.detect-redact-exclude
use super::utf16::{WS_CLASS, is_js_ws, is_word, js_trim, len16};
use regex::Regex;
use std::sync::OnceLock;

/// One detection pattern in priority order.
pub(crate) struct PiiPattern {
    /// `PIIType` name.
    pub kind: &'static str,
    /// Compiled regex (lookaheads removed; see `fit`).
    pub regex: Regex,
    /// Placeholder prefix (`[PREFIX_n_suffix]`).
    pub prefix: &'static str,
    /// Human readable label.
    pub label: &'static str,
}

/// `[type, placeholder prefix, label]` in TS pattern order.
const META: &[(&str, &str, &str)] = &[
    ("AWS_ACCESS_KEY", "AWS_KEY", "AWS Access Key"),
    ("OPENAI_KEY", "OPENAI_KEY", "OpenAI API Key"),
    ("ANTHROPIC_KEY", "ANTHROPIC_KEY", "Anthropic API Key"),
    ("GITHUB_PAT", "GITHUB_TOKEN", "GitHub Token"),
    ("STRIPE_KEY", "STRIPE_KEY", "Stripe API Key"),
    ("GOOGLE_API_KEY", "GOOGLE_KEY", "Google API Key"),
    ("SLACK_TOKEN", "SLACK_TOKEN", "Slack Token"),
    ("AWS_SECRET_KEY", "AWS_SECRET", "AWS Secret Key"),
    ("TWILIO_KEY", "TWILIO_KEY", "Twilio Key"),
    ("SENDGRID_KEY", "SENDGRID_KEY", "SendGrid API Key"),
    ("AZURE_KEY", "AZURE_KEY", "Azure Key"),
    ("HUGGINGFACE_KEY", "HF_TOKEN", "Hugging Face Token"),
    ("DATABRICKS_TOKEN", "DATABRICKS_TOKEN", "Databricks Token"),
    ("FIREBASE_KEY", "FIREBASE_KEY", "Firebase Key"),
    ("GENERIC_SECRET", "SECRET", "Secret/Credential"),
    ("PRIVATE_KEY", "PRIVATE_KEY", "Private Key"),
    ("JWT", "JWT_TOKEN", "JWT Token"),
    ("EMAIL", "EMAIL", "Email Address"),
    ("CREDIT_CARD", "CARD", "Credit Card"),
    ("SSN", "SSN", "SSN"),
    ("PHONE", "PHONE", "Phone Number"),
    ("IPV4", "IP", "IP Address"),
    ("IPV6", "IPV6", "IPv6 Address"),
    ("IBAN", "IBAN", "IBAN"),
    ("HOME_FOLDER", "HOME_PATH", "Home Folder"),
    ("USER_AT_HOSTNAME", "USER_HOST", "User@Hostname"),
    ("MAC_ADDRESS", "MAC", "MAC Address"),
    ("PASSPORT", "PASSPORT", "Passport Number"),
    ("TAX_ID", "TAX_ID", "Tax ID"),
    ("VEHICLE_PLATE", "PLATE", "Vehicle Plate"),
    ("CRYPTO_WALLET", "WALLET", "Crypto Wallet"),
];

/// Regex source per `META` entry (same order). `{ws}` is the JS `\s` class body.
fn sources() -> Vec<String> {
    let ws = WS_CLASS;
    let b = r"(?-u:\b)";
    let secret_value_ws = format!("(?u:['\":{ws}=])");
    vec![
        format!(r"{b}AKIA[0-9A-Z]{{16}}{b}"),
        format!(r"{b}sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{{20,200}}{b}"),
        format!(r"{b}sk-ant-api03-[A-Za-z0-9_-]{{90,110}}{b}"),
        format!(r"{b}(?:ghp_[a-zA-Z0-9]{{36}}|github_pat_[a-zA-Z0-9]{{22}}_[a-zA-Z0-9]{{59}}|gho_[a-zA-Z0-9]{{36}}){b}"),
        format!(r"{b}[sr]k_(?:live|test)_[0-9a-zA-Z]{{24,99}}{b}"),
        format!(r"{b}AIza[0-9A-Za-z\-_]{{35}}{b}"),
        format!(r"{b}xox[bpras]-[0-9a-zA-Z-]{{10,250}}{b}"),
        format!(r"(?i-u:(?:aws_secret|secret_key|secretkey|secret_access_key){secret_value_ws}+[0-9a-zA-Z/+=]{{40}}\b)"),
        format!(r"{b}(?:AC[a-f0-9]{{32}}|SK[a-f0-9]{{32}}){b}"),
        format!(r"{b}SG\.[a-zA-Z0-9_-]{{22}}\.[a-zA-Z0-9_-]{{43}}{b}"),
        format!(r"(?i-u:(?:azure|subscription|ocp-apim)[_-]?(?:key|secret|token){secret_value_ws}+[0-9a-f]{{32}}\b)"),
        format!(r"{b}hf_[a-zA-Z0-9]{{34,}}{b}"),
        format!(r"{b}dapi[a-f0-9]{{32,40}}{b}"),
        format!(r"{b}AAAA[A-Za-z0-9_-]{{100,200}}{b}"),
        format!(r#"(?i-u:(?:api[_-]?key|api[_-]?secret|secret[_-]?key|auth[_-]?token|access[_-]?token|bearer[_-]?token|private[_-]?key|password|passwd|credential|client[_-]?secret|app[_-]?secret|signing[_-]?key|encryption[_-]?key){secret_value_ws}+['"]?[A-Za-z0-9_\-/.+=]{{8,200}}['"]?)"#),
        r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----(?s:.)*?-----END (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----".to_string(),
        format!(r"{b}eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+"),
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}".to_string(),
        format!(r"{b}(?:4[0-9]{{3}}[-{ws}]?[0-9]{{4}}[-{ws}]?[0-9]{{4}}[-{ws}]?[0-9]{{4}}|5[1-5][0-9]{{2}}[-{ws}]?[0-9]{{4}}[-{ws}]?[0-9]{{4}}[-{ws}]?[0-9]{{4}}|3[47][0-9]{{2}}[-{ws}]?[0-9]{{6}}[-{ws}]?[0-9]{{5}}|6(?:011|5[0-9]{{2}})[-{ws}]?[0-9]{{4}}[-{ws}]?[0-9]{{4}}[-{ws}]?[0-9]{{4}}){b}"),
        format!(r"{b}[0-9]{{3}}[-{ws}]?[0-9]{{2}}[-{ws}]?[0-9]{{4}}{b}"),
        format!(r"(?:(?:\+|00)[1-9][0-9]{{0,2}}[-.{ws}/]?(?:\(?[0-9]{{1,5}}\)?[-.{ws}/]?){{1,4}}[0-9]{{2,4}})|(?:\+?1[-.{ws}]?)?\(?[2-9][0-9]{{2}}\)?[-.{ws}]?[0-9]{{3}}[-.{ws}]?[0-9]{{4}}|(?:0[0-9][-.{ws}/]?(?:\(?[0-9]{{1,5}}\)?[-.{ws}/]?){{1,4}}[0-9]{{2,4}})"),
        format!(r"{b}(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){{3}}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?){b}"),
        format!(r"{b}(?:[0-9a-fA-F]{{1,4}}:){{7}}[0-9a-fA-F]{{1,4}}{b}"),
        format!(r"{b}[A-Z]{{2}}[0-9]{{2}}[{ws}]?[0-9A-Z]{{4}}[{ws}]?(?:[0-9A-Z]{{4}}[{ws}]?){{1,7}}[0-9A-Z]{{1,4}}{b}"),
        // Lookaheads removed: `fit_home_folder` re-applies them.
        r"(?:/home/|/Users/|[A-Z]:\\Users\\)[a-zA-Z0-9_.-]{1,64}|PS [A-Z]:\\Users\\[a-zA-Z0-9_.-]{1,64}|PS /(?:home|Users)/[a-zA-Z0-9_.-]{1,64}".to_string(),
        format!(r"{b}[a-zA-Z0-9_][a-zA-Z0-9_.-]{{0,31}}@[a-zA-Z0-9_][a-zA-Z0-9_.-]{{0,63}}"),
        format!(r"{b}(?:[0-9A-Fa-f]{{2}}[:-]){{5}}[0-9A-Fa-f]{{2}}{b}"),
        format!(r"(?i-u:(?:passport|reisepass|passeport|pass(?:port)?(?u:[._{ws}-])?(?:no|nr|num(?:ber)?|#))(?u:[:#={ws}])*[A-Z0-9]{{6,9}}\b)"),
        tax_id(ws),
        format!(r"(?i-u:(?:license(?u:[_{ws}-])?plate|plate(?u:[_{ws}-])?(?:number|no|nr)|kennzeichen|nummernschild|kfz(?u:[_{ws}-])?kennzeichen|immatriculation|registration(?u:[_{ws}-])?(?:number|no|nr|plate)|vrm|numberplate)(?u:[:#={ws}])*[A-Z0-9]{{1,4}}(?u:[{ws}-])?[A-Z0-9]{{1,4}}(?u:[{ws}-])?[A-Z0-9]{{1,6}}\b)"),
        format!(r"{b}(?:bc1[a-z0-9]{{25,87}}|[13][a-km-zA-HJ-NP-Z1-9]{{25,34}}|0x[0-9a-fA-F]{{40}}){b}"),
    ]
}

fn tax_id(ws: &str) -> String {
    let sp = " ?";
    let vat = format!(
        "AT{sp}U[0-9]{{8}}|BE{sp}0?[0-9]{{9,10}}|BG{sp}[0-9]{{9,10}}|HR{sp}[0-9]{{11}}|CY{sp}[0-9]{{8}}[A-Z]|CZ{sp}[0-9]{{8,10}}|DK{sp}[0-9]{{8}}|EE{sp}[0-9]{{9}}|FI{sp}[0-9]{{8}}|FR{sp}[0-9A-Z]{{2}}[0-9]{{9}}|DE{sp}[0-9]{{9}}|EL{sp}[0-9]{{9}}|HU{sp}[0-9]{{8}}|IE{sp}[0-9]{{7}}[A-Z]{{1,2}}|IT{sp}[0-9]{{11}}|LV{sp}[0-9]{{11}}|LT{sp}[0-9]{{9,12}}|LU{sp}[0-9]{{8}}|MT{sp}[0-9]{{8}}|NL{sp}[0-9]{{9}}B[0-9]{{2}}|PL{sp}[0-9]{{10}}|PT{sp}[0-9]{{9}}|RO{sp}[0-9]{{2,10}}|SK{sp}[0-9]{{10}}|SI{sp}[0-9]{{8}}|ES{sp}[A-Z0-9][0-9]{{7}}[A-Z0-9]|SE{sp}[0-9]{{12}}|GB{sp}[0-9]{{9}}(?:[0-9]{{3}})?"
    );
    let sep = format!("(?u:[_{ws}-])?");
    let tail = format!("(?:(?i-u:[A-Z0-9/-])|(?u:[{ws}])){{5,20}}");
    let context = format!(
        "(?:tax{sep}(?:id|number|no|nr)|steuer(?:nummer|identifikationsnummer|nr|ident(?:nummer)?)|tin{sep}(?:number|no|nr)|vat{sep}(?:id|number|no|nr)|tax{sep}identification(?:{sep}number)?)(?u:[:#={ws}])+"
    );
    format!("(?i-u:\\b(?:{vat})\\b)|(?i-u:{context}){tail}")
}

/// The compiled pattern table in priority order.
pub(crate) fn patterns() -> &'static [PiiPattern] {
    static TABLE: OnceLock<Vec<PiiPattern>> = OnceLock::new();
    TABLE.get_or_init(|| {
        META.iter()
            .zip(sources())
            .map(|(&(kind, prefix, label), source)| PiiPattern {
                kind,
                prefix,
                label,
                regex: Regex::new(&source).expect("fixed composer PII pattern compiles"),
            })
            .collect()
    })
}

/// `PII_TYPE_TO_CATEGORY` (settings category key of each type).
pub(crate) fn category(kind: &str) -> Option<&'static str> {
    Some(match kind {
        "EMAIL" => "email_addresses",
        "ADDRESS" => "addresses",
        "PERSON_NAME" => "names",
        "BANK_ACCOUNT" | "IBAN" => "iban_bank_account",
        "GOVERNMENT_ID" => "government_ids",
        "DRIVERS_LICENSE" => "drivers_licenses",
        "IMEI" => "imei_numbers",
        "PHONE" => "phone_numbers",
        "CREDIT_CARD" => "credit_card_numbers",
        "SSN" => "social_security_numbers",
        "TAX_ID" => "tax_id_vat",
        "PASSPORT" => "passport_numbers",
        "CRYPTO_WALLET" => "crypto_wallets",
        "VEHICLE_PLATE" => "vehicle_plate",
        "AWS_ACCESS_KEY" | "AWS_SECRET_KEY" | "OPENAI_KEY" | "ANTHROPIC_KEY" | "GITHUB_PAT" | "STRIPE_KEY"
        | "GOOGLE_API_KEY" | "SLACK_TOKEN" | "TWILIO_KEY" | "SENDGRID_KEY" | "AZURE_KEY" | "HUGGINGFACE_KEY"
        | "DATABRICKS_TOKEN" | "FIREBASE_KEY" => "api_keys",
        "GENERIC_SECRET" => "generic_secrets",
        "PRIVATE_KEY" => "private_keys",
        "JWT" => "jwt_tokens",
        "IPV4" | "IPV6" => "ip_addresses",
        "HOME_FOLDER" => "home_folder",
        "USER_AT_HOSTNAME" => "user_at_hostname",
        "MAC_ADDRESS" => "mac_addresses",
        _ => return None,
    })
}

/// Every key of `PII_TYPE_TO_CATEGORY` (used to build the generated-placeholder pattern).
pub(crate) const CATEGORY_KEYS: &[&str] = &[
    "EMAIL", "ADDRESS", "PERSON_NAME", "BANK_ACCOUNT", "GOVERNMENT_ID", "DRIVERS_LICENSE", "IMEI", "PHONE",
    "CREDIT_CARD", "SSN", "IBAN", "TAX_ID", "PASSPORT", "CRYPTO_WALLET", "VEHICLE_PLATE", "AWS_ACCESS_KEY",
    "AWS_SECRET_KEY", "OPENAI_KEY", "ANTHROPIC_KEY", "GITHUB_PAT", "STRIPE_KEY", "GOOGLE_API_KEY", "SLACK_TOKEN",
    "TWILIO_KEY", "SENDGRID_KEY", "AZURE_KEY", "HUGGINGFACE_KEY", "DATABRICKS_TOKEN", "FIREBASE_KEY",
    "GENERIC_SECRET", "PRIVATE_KEY", "JWT", "IPV4", "IPV6", "HOME_FOLDER", "USER_AT_HOSTNAME", "MAC_ADDRESS",
];

/// `getPIILabel`: the model labels first, then the pattern label, then the type itself.
pub(crate) fn label(kind: &str) -> String {
    match kind {
        "ADDRESS" => "Address".into(),
        "PERSON_NAME" => "Name".into(),
        "BANK_ACCOUNT" => "Bank account".into(),
        "GOVERNMENT_ID" => "Government ID".into(),
        "DRIVERS_LICENSE" => "Driver\u{2019}s license".into(),
        "IMEI" => "Device identifier".into(),
        _ => patterns().iter().find(|p| p.kind == kind).map_or_else(|| kind.to_string(), |p| p.label.to_string()),
    }
}

/// `getSecretSuffix(match, 3)`: last three UTF-16 units after trimming trailing quotes/whitespace.
pub(crate) fn secret_suffix(matched: &str) -> String {
    let cleaned = matched.trim_end_matches(|c: char| matches!(c, '\'' | '"' | ';') || is_js_ws(c));
    if len16(cleaned) <= 3 {
        return cleaned.to_string();
    }
    let units: Vec<u16> = cleaned.encode_utf16().collect();
    String::from_utf16_lossy(&units[units.len() - 3..])
}

fn digits(value: &str) -> Vec<u32> {
    value.chars().filter_map(|c| c.to_digit(10).filter(|_| c.is_ascii_digit())).collect()
}

fn fixed(pattern: &str) -> Regex {
    Regex::new(pattern).expect("fixed validator pattern compiles")
}

fn phone_valid(value: &str) -> bool {
    static DATES: OnceLock<[Regex; 5]> = OnceLock::new();
    let dates = DATES.get_or_init(|| {
        [
            fixed(r"^[0-9]{4}$"),
            fixed(r"^[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}$"),
            fixed(r"^[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4}$"),
            fixed(r"^(?:19|20)[0-9]{6}$"),
            fixed(r"^0[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{1,2}$"),
        ]
    });
    let trimmed = js_trim(value);
    let count = digits(trimmed).len();
    (7..=15).contains(&count) && !dates.iter().any(|d| d.is_match(trimmed))
}

fn iban_valid(value: &str) -> bool {
    let cleaned: String = value.chars().filter(|c| !is_js_ws(*c)).collect::<String>().to_uppercase();
    if !(15..=34).contains(&len16(&cleaned)) {
        return false;
    }
    let chars: Vec<char> = cleaned.chars().collect();
    let mut remainder = 0u64;
    for c in chars[4..].iter().chain(&chars[..4]) {
        match c {
            '0'..='9' => remainder = (remainder * 10 + u64::from(*c as u8 - b'0')) % 97,
            'A'..='Z' => remainder = (remainder * 100 + u64::from(*c as u8 - b'A') + 10) % 97,
            _ => return false,
        }
    }
    remainder == 1
}

/// The per-type `validate` hook; true when the type has none.
pub(crate) fn valid(kind: &str, value: &str) -> bool {
    match kind {
        "CREDIT_CARD" => {
            let d = digits(value);
            (13..=19).contains(&d.len())
                && d.iter().rev().enumerate().map(|(i, &x)| if i % 2 == 1 { let n = x * 2; if n > 9 { n - 9 } else { n } } else { x }).sum::<u32>() % 10 == 0
        }
        "SSN" => {
            let d = digits(value);
            d.len() == 9 && {
                let area = d[0] * 100 + d[1] * 10 + d[2];
                area != 0 && area != 666 && area < 900 && (d[3] * 10 + d[4]) != 0 && d[5..].iter().any(|v| *v != 0)
            }
        }
        "PHONE" => phone_valid(value),
        "IPV4" => value != "127.0.0.1" && value != "0.0.0.0" && !["192.168.", "10.", "172."].iter().any(|p| value.starts_with(p)),
        "IBAN" => iban_valid(value),
        "HOME_FOLDER" => {
            static PREFIX: OnceLock<Regex> = OnceLock::new();
            let prefix = PREFIX.get_or_init(|| fixed(&format!(r"(?i-u:^(?:PS(?u:[{WS_CLASS}])+)?(?:/home/|/Users/|[A-Z]:\\Users\\))")));
            let user = prefix.replace(value, "").to_lowercase();
            !["root", "admin", "shared", "public", "default", "guest", "nobody", "daemon", "www-data", "ubuntu"].contains(&user.as_str())
        }
        "USER_AT_HOSTNAME" => {
            let lower = value.to_lowercase();
            let mut parts = lower.split('@');
            let (user, host) = (parts.next().unwrap_or(""), parts.next().unwrap_or(""));
            !["github.com", "gitlab.com", "bitbucket.org", "ssh.dev.azure.com"].contains(&host)
                && !["root", "admin", "guest", "nobody", "daemon", "www-data", "noreply", "no-reply", "git", "svn", "user", "test", "ubuntu"].contains(&user)
        }
        "MAC_ADDRESS" => {
            let n = value.replace([':', '-'], "").to_uppercase();
            n != "000000000000" && n != "FFFFFFFFFFFF"
        }
        _ => true,
    }
}

/// Re-applies the removed regex lookaheads. `text` is the haystack, `start..end` the greedy match.
/// Returns the final end (shortened like regex backtracking) or `None` when the match fails.
pub(crate) fn fit(kind: &str, text: &str, start: usize, end: usize) -> Option<usize> {
    match kind {
        "HOME_FOLDER" => {
            let matched = &text[start..end];
            let close: &[char] = if matched.starts_with("PS /") { &['/', '>'] } else if matched.starts_with("PS ") { &['\\', '>'] } else { &['/', '\\'] };
            let min_end = user_start(matched) + start + 1;
            let mut at = end;
            loop {
                let prev = text[..at].chars().next_back()?;
                let next = text[at..].chars().next();
                if next.is_some_and(|c| close.contains(&c)) || next.map_or(is_word(prev), |c| is_word(prev) != is_word(c)) {
                    return Some(at);
                }
                at -= prev.len_utf8();
                if at < min_end {
                    return None;
                }
            }
        }
        "USER_AT_HOSTNAME" => text[end..].chars().next().filter(|c| is_js_ws(*c) || *c == ':' || *c == '~').map(|_| end),
        _ => Some(end),
    }
}

/// Byte offset inside a HOME_FOLDER match where the user-name class starts.
fn user_start(matched: &str) -> usize {
    ["/home/", "/Users/", "\\Users\\"].iter().filter_map(|p| matched.find(p).map(|i| i + p.len())).min().unwrap_or(0)
}
