//! Team response decisions (shared Rust core `work` op, slice 2: Teams).
//!
//! spec: specifications/features/teams#teams.lifecycle.encrypted-profiled
//!
//! Mirrors the pure logic of the web `teamService.ts` over server replies and
//! page-decrypted plaintexts: the Team view (`decryptTeam`), member profiles,
//! invite recipient hints, the wallet balance decision, the invite key context,
//! invite results, profile-image upload outcomes and the created Team record.
//! The page keeps fetch, the Team key cache, every scope fence, WebCrypto
//! (invite HKDF/AES-GCM, key wrap/unwrap) and the invite secret: no key bytes
//! and no invite secret ever reach these decisions. Parity: `teams_ts_vectors.json`.

use serde_json::{Map, Value, json};

use super::{Decision, member, object, or, refusal, team_bodies, text, truthy};
use crate::web_apps::js_string;

/// Runs one Team op: response decisions here, paths and bodies in [`team_bodies`].
///
/// # Errors
/// `unknown_op:<name>` or a malformed-input error; TS refusals come back as `{"error"}`.
pub(crate) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "teamView" => view(input),
        "teamMemberProfiles" => member_profiles(input),
        "teamInviteHints" => invite_hints(input),
        "teamBilling" => billing(input),
        "teamInviteKeyContext" => invite_key_context(input),
        "teamInviteResult" => invite_result(input),
        "teamProfileImageOutcome" => profile_image_outcome(input),
        "teamCreatedRecord" => created_record(input),
        _ => team_bodies::run(op, input),
    }
}

/// Characters removed by `String.prototype.trim` (WhiteSpace + LineTerminator; Rust's set differs).
fn js_space(c: char) -> bool {
    matches!(
        c,
        '\u{0009}'..='\u{000D}'
            | '\u{0020}'
            | '\u{00A0}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200A}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202F}'
            | '\u{205F}'
            | '\u{3000}'
            | '\u{FEFF}'
    )
}

/// `value.trim()` in JavaScript.
pub(crate) fn js_trim(value: &str) -> &str {
    value.trim_matches(js_space)
}

/// `Number.parseInt(text, 10)`: leading JS whitespace, an optional sign, then
/// the longest ASCII digit run; no digits is `NaN`.
pub(crate) fn parse_int(text: &str) -> f64 {
    let rest = text.trim_start_matches(js_space);
    let (negative, rest) = match rest.as_bytes().first() {
        Some(b'-') => (true, &rest[1..]),
        Some(b'+') => (false, &rest[1..]),
        _ => (false, rest),
    };
    let digits = &rest[..rest.bytes().take_while(u8::is_ascii_digit).count()];
    if digits.is_empty() {
        return f64::NAN;
    }
    // An ASCII digit run always parses (very long runs round to infinity, as in JS).
    let value: f64 = digits.parse().expect("an ASCII digit run is a valid float literal");
    if negative { -value } else { value }
}

/// A JS number as `JSON.stringify` writes it: safe integers as integers
/// (`-0` is `0`), other finite values as floats, `NaN`/`Infinity` as `null`.
pub(crate) fn number(value: f64) -> Value {
    if value.fract() == 0.0 && value.abs() < 9_007_199_254_740_992.0 {
        // The guard keeps the value inside i64; the cast drops only the `-0` sign.
        return json!(value as i64);
    }
    serde_json::Number::from_f64(value).map_or(Value::Null, Value::Number)
}

/// `Number.isInteger(value)` for a JSON member.
fn is_integer(value: Option<&Value>) -> bool {
    value.and_then(Value::as_f64).is_some_and(|f| f.is_finite() && f.fract() == 0.0)
}

/// A JS property read: only plain objects carry named members here.
fn field<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    value.as_object().and_then(|object| object.get(key))
}

/// `value ?? <next>`: a missing or `null` member is nullish.
fn nullish(value: Option<&Value>) -> Option<&Value> {
    value.filter(|v| !v.is_null())
}

/// The TypeError text V8 raises when a member of an `undefined`/`null` reply is read.
fn read_error(input: &Value, name: &str, key: &str) -> Option<Value> {
    match input.get(name) {
        None => Some(refusal(&format!("Cannot read properties of undefined (reading '{key}')"))),
        Some(Value::Null) => Some(refusal(&format!("Cannot read properties of null (reading '{key}')"))),
        Some(_) => None,
    }
}

/// `defaultProfileImageMetadata()` (TS literal order).
const DEFAULT_PROFILE_IMAGE: &str =
    r##"{"version":1,"mode":"generated","icon_name":"team","icon_color":"#ffffff","background_color":"#4d73ff"}"##;

/// The JSON text of `defaultProfileImageMetadata()` for encryption steps.
pub(crate) fn default_profile_image_json() -> &'static str {
    DEFAULT_PROFILE_IMAGE
}

fn default_profile_image() -> Value {
    serde_json::from_str(DEFAULT_PROFILE_IMAGE).expect("the default profile image literal is valid JSON")
}

/// `ownTeamMemberProfile().avatar`.
fn default_avatar() -> Value {
    json!({ "mode": "generated", "icon_name": "mate", "background_color": "#4d73ff" })
}

/// `{ ...DEFAULT_SECURITY_POLICY, ...record.security_policy }` as ordered
/// `[name, value]` pairs: the page rebuilds the object with `Object.fromEntries`
/// so the policy it later PATCHes keeps the TS key order (serde maps are sorted).
fn security_policy(record: &Map<String, Value>) -> Value {
    let mut pairs: Vec<(String, Value)> = vec![
        ("restrict_email_domains".into(), json!(false)),
        ("allowed_email_domains".into(), json!([])),
        ("require_invite_link_approval".into(), json!(true)),
        ("require_strong_auth".into(), json!(false)),
    ];
    let overrides: Vec<(String, Value)> = match record.get("security_policy") {
        Some(Value::Object(policy)) => policy.iter().map(|(k, v)| (k.clone(), v.clone())).collect(),
        // Spreading an array or string copies its indices (never sent by the server).
        Some(Value::Array(items)) => items.iter().enumerate().map(|(i, v)| (i.to_string(), v.clone())).collect(),
        Some(Value::String(s)) => {
            s.encode_utf16().enumerate().map(|(i, unit)| (i.to_string(), json!(String::from_utf16_lossy(&[unit])))).collect()
        }
        _ => Vec::new(),
    };
    for (name, value) in overrides {
        match pairs.iter_mut().find(|(seen, _)| *seen == name) {
            Some(pair) => pair.1 = value,
            None => pairs.push((name, value)),
        }
    }
    Value::Array(pairs.into_iter().map(|(k, v)| json!([k, v])).collect())
}

/// `decryptTeam` after the Team key lookup (the page keeps the `null` key and id cases).
fn view(input: &Value) -> Decision {
    let record = object(input, "record")?;
    let fields = object(input, "fields")?;
    let profile_text = text(record, fields, "encrypted_profile_image_metadata")?;
    let profile = if profile_text.is_empty() {
        default_profile_image()
    } else {
        match serde_json::from_str::<Value>(profile_text) {
            Ok(Value::Object(parsed)) => Value::Object(parsed),
            _ => default_profile_image(),
        }
    };
    let zero_text = text(record, fields, "encrypted_zero_balance")?;
    let zero = parse_int(if zero_text.is_empty() { "0" } else { zero_text });
    let name = text(record, fields, "encrypted_name")?;
    let mut out = Map::new();
    // The page only asks for a record whose `team_id` it has checked (TS `!teamId` returns null first).
    out.insert("team_id".into(), record.get("team_id").cloned().ok_or("missing_field:record.team_id")?);
    out.insert("name".into(), json!(if name.is_empty() { "Untitled team" } else { name }));
    out.insert("description".into(), json!(text(record, fields, "encrypted_description")?));
    out.insert("role".into(), or(record, "role", json!("viewer")));
    out.insert("status".into(), or(record, "status", json!("active")));
    out.insert("profileImageMetadata".into(), profile);
    out.insert("zeroBalance".into(), if zero.is_finite() { number(zero) } else { json!(0) });
    out.insert("createdAt".into(), or(record, "created_at", json!(0)));
    out.insert("updatedAt".into(), or(record, "updated_at", json!(0)));
    out.insert("securityPolicy".into(), security_policy(record));
    Ok(Value::Object(out))
}

/// The page plaintexts of an op: one entry per item, `null` when the item had
/// no ciphertext or its decrypt failed (the TS `catch` paths).
fn plaintexts(input: &Value) -> Result<Vec<Option<&str>>, String> {
    member(input, "plaintexts")?
        .as_array()
        .ok_or("bad_field:plaintexts")?
        .iter()
        .map(|item| match item {
            Value::Null => Ok(None),
            Value::String(s) => Ok(Some(s.as_str())),
            _ => Err("bad_field:plaintexts".to_owned()),
        })
        .collect()
}

/// `loadTeamMembers` profile parsing: a profile only for a JSON object with a
/// non-blank string `display_name`; the page keeps its own member otherwise.
fn member_profiles(input: &Value) -> Decision {
    let profiles: Vec<Value> = plaintexts(input)?
        .into_iter()
        .map(|text| {
            // A null decrypt parses "{}" in TS: no display name, the member as is.
            let Some(Ok(Value::Object(parsed))) = text.map(serde_json::from_str::<Value>) else {
                return Value::Null;
            };
            match parsed.get("display_name") {
                Some(Value::String(name)) if !js_trim(name).is_empty() => {
                    json!({ "display_name": name, "avatar": or(&parsed, "avatar", default_avatar()) })
                }
                _ => Value::Null,
            }
        })
        .collect();
    Ok(json!({ "profiles": profiles }))
}

/// `loadTeamInvites` recipient hints: `String(hint.recipient_email ?? "")`,
/// `""` for a missing, undecryptable or malformed hint.
fn invite_hints(input: &Value) -> Decision {
    let emails: Vec<Value> = plaintexts(input)?
        .into_iter()
        .map(|text| match text.map(serde_json::from_str::<Value>) {
            Some(Ok(Value::Object(hint))) => json!(nullish(hint.get("recipient_email")).map_or(String::new(), js_string)),
            _ => json!(""),
        })
        .collect();
    Ok(json!({ "recipient_emails": emails }))
}

/// `loadTeamBilling`'s balance decision. Without `decrypt` it answers
/// `{"decrypt": <encrypted balance>}` when the TS code would decrypt the
/// snapshot; the page then decrypts with its Team key and asks again with
/// `decrypt: {team_key, plaintext}` (`team_key: false` when it had none).
fn billing(input: &Value) -> Decision {
    if let Some(refused) = read_error(input, "billing", "version") {
        return Ok(refused);
    }
    let billing = member(input, "billing")?;
    let version = field(billing, "version");
    let authoritative = is_integer(version);
    let raw = if authoritative {
        field(billing, "balance_credits")
    } else {
        nullish(field(billing, "balance_credits"))
            .or_else(|| nullish(field(billing, "credits")))
            .or_else(|| field(billing, "balance"))
    };
    let raw_is_number = matches!(raw, Some(Value::Number(_)));
    let mut balance = match raw {
        Some(Value::Number(n)) => n.as_f64().unwrap_or(f64::NAN),
        None | Some(Value::Null) => parse_int(""),
        Some(other) => parse_int(&js_string(other)),
    };
    let encrypted = match field(billing, "encrypted_balance") {
        Some(Value::String(s)) => Some(s.as_str()),
        _ => None,
    };
    if authoritative && (!raw_is_number || !(balance.is_finite() && balance.fract() == 0.0) || balance < 0.0) {
        return Ok(refusal("Team wallet balance is unavailable"));
    }
    let unusable = |b: f64| !b.is_finite() || b < 0.0;
    if unusable(balance) && encrypted.is_some_and(|s| !s.is_empty()) {
        let Some(decrypt) = input.get("decrypt") else {
            return Ok(json!({ "decrypt": encrypted }));
        };
        let decrypt = decrypt.as_object().ok_or("bad_field:decrypt")?;
        if truthy(decrypt.get("team_key")) {
            balance = match decrypt.get("plaintext") {
                None | Some(Value::Null) => parse_int("0"),
                Some(Value::String(s)) => parse_int(s),
                Some(_) => return Err("bad_field:decrypt.plaintext".into()),
            };
        }
    }
    let mut out = Map::new();
    if unusable(balance) {
        // `team.zeroBalance`; an absent one stays absent (JSON.stringify drops undefined).
        if let Some(zero) = input.get("zero_balance") {
            out.insert("balanceCredits".into(), zero.clone());
        }
    } else {
        out.insert("balanceCredits".into(), number(balance));
    }
    if authoritative {
        out.insert("version".into(), version.cloned().unwrap_or(Value::Null));
    }
    out.insert("encryptedBalance".into(), encrypted.map_or(Value::Null, |s| json!(s)));
    Ok(Value::Object(out))
}

/// `acceptTeamInviteFromFragment`'s preview checks: the Team id, KDF origin
/// (`location_origin` is the page's `window.location.origin`), the sealed
/// invite key and whether the invite is a link (no recipient binding).
fn invite_key_context(input: &Value) -> Decision {
    if let Some(refused) = read_error(input, "invite", "invite_key_kdf_context") {
        return Ok(refused);
    }
    let invite = member(input, "invite")?;
    let context = field(invite, "invite_key_kdf_context");
    let read = |key: &str| context.and_then(|c| nullish(field(c, key)));
    let team_id = read("team_id").map_or(String::new(), js_string);
    let origin = js_string(read("origin").unwrap_or(member(input, "location_origin")?));
    let encrypted = nullish(field(invite, "encrypted_invite_team_key")).map_or(String::new(), js_string);
    if team_id.is_empty() || encrypted.is_empty() {
        return Ok(refusal("Invite is missing encrypted team key"));
    }
    let is_link = field(invite, "kind") == Some(&json!("link")) || !truthy(field(invite, "hashed_recipient_email"));
    Ok(json!({ "team_id": team_id, "origin": origin, "encrypted": encrypted, "is_link": is_link }))
}

/// The `TeamInviteResult` facts of `createTeamEmailInvite` (`delivery: "email"`)
/// and `createTeamLinkInvite` (`"link"`); the page adds `raw` and the secret-bearing `inviteUrl`.
fn invite_result(input: &Value) -> Decision {
    if let Some(refused) = read_error(input, "invite", "invite_id") {
        return Ok(refused);
    }
    let invite = member(input, "invite")?;
    let role = member(input, "role")?;
    let link = member(input, "delivery")?.as_str() == Some("link");
    let created = json!("created");
    let status = nullish(field(invite, "status")).unwrap_or(&created);
    Ok(json!({
        "inviteId": js_string(nullish(field(invite, "invite_id")).unwrap_or(member(input, "invite_id")?)),
        "role": if link { role.clone() } else { nullish(field(invite, "role")).unwrap_or(role).clone() },
        "status": js_string(status),
        "deliveryStatus": if link {
            "link".to_owned()
        } else {
            js_string(nullish(field(invite, "delivery_status")).unwrap_or(&created))
        },
    }))
}

/// `uploadTeamProfileImage`'s reply mapping: `{"outcome": "ok"}`,
/// `{"outcome": "account_deleted"}` (the page runs the lockout side effects) or
/// `{"outcome": "error", "detail"}` for the page's `TeamApiError`.
fn profile_image_outcome(input: &Value) -> Decision {
    if let Some(refused) = read_error(input, "data", "status") {
        return Ok(refused);
    }
    let data = member(input, "data")?;
    let status = field(data, "status").and_then(Value::as_str);
    let error = |detail: Value| Ok(json!({ "outcome": "error", "detail": detail }));
    match status {
        Some("account_deleted") => Ok(json!({ "outcome": "account_deleted" })),
        Some("rejected") => {
            let last = field(data, "reject_count").and_then(Value::as_f64) == Some(3.0);
            error(json!(if last { "IMAGE_REJECTED_FINAL_WARNING" } else { "IMAGE_REJECTED" }))
        }
        Some("ok") if truthy(input.get("ok")) => Ok(json!({ "outcome": "ok" })),
        _ => error(nullish(field(data, "detail")).cloned().unwrap_or(json!("IMAGE_UPLOAD_FAILED"))),
    }
}

/// `createTeam`'s record for the first decrypt: the members the TS literal
/// sets over `...returnedTeam`, as ordered pairs (the page spreads
/// `Object.fromEntries(overrides)` over its own reply object, keeping key order).
/// `sent` is the body the page sent; an absent fallback stays absent.
fn created_record(input: &Value) -> Decision {
    let empty = Map::new();
    let returned = match input.get("returned") {
        None | Some(Value::Null) => &empty,
        Some(Value::Object(team)) => team,
        Some(_) => return Err("bad_field:returned".into()),
    };
    let sent = object(input, "sent")?;
    let team_id = or(returned, "team_id", member(input, "team_id")?.clone());
    let mut pairs: Vec<Value> = vec![json!(["team_id", team_id])];
    let mut fallback = |name: &str, value: Option<Value>| {
        if let Some(value) = value {
            pairs.push(json!([name, value]));
        }
    };
    let sent_or = |name: &str| nullish(returned.get(name)).or_else(|| sent.get(name)).cloned();
    fallback("encrypted_name", sent_or("encrypted_name"));
    fallback("encrypted_description", sent_or("encrypted_description"));
    fallback("encrypted_profile_image_metadata", sent_or("encrypted_profile_image_metadata"));
    fallback("encrypted_team_key", sent.get("encrypted_team_key").cloned());
    fallback("encrypted_zero_balance", sent_or("encrypted_zero_balance"));
    fallback("role", Some(or(returned, "role", json!("owner"))));
    fallback("created_at", sent_or("created_at"));
    fallback("updated_at", sent_or("updated_at"));
    let created_id = pairs[0][1].clone();
    Ok(json!({ "team_id": created_id, "overrides": pairs }))
}
