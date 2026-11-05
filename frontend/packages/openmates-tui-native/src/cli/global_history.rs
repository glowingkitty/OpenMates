//! Global workspace history is metadata-only shared SDK policy. This adapter
//! preserves the original CLI list/show/undo shapes and delegates every HTTP,
//! auth, cancellation and safe-undo decision to the existing Rust client.
//! It never decrypts object history, imports a profile or retries an undo.
//! Per-object history/restore commands remain in their original helper.
use super::{CliError, CliOutput, Invocation};
use crate::{client::Client, error::Error};
use openmates_sdk::{
    sdk::OpenMates,
    sdk_history::{History, HistoryListOptions, HistoryRequestError},
};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

/// Scratch captures are never Debug/logged and erase private scalar values on
/// parse failure. Successful values move into Invocation's existing zeroizer.
pub(super) struct HistoryFlagCapture {
    flags: std::collections::BTreeMap<String, Value>,
}
impl HistoryFlagCapture {
    pub(super) fn apply(&mut self, flags: &mut std::collections::BTreeMap<String, Value>) {
        for (key, value) in std::mem::take(&mut self.flags) {
            if let Some(mut previous) = flags.insert(key, value) {
                super::erase(&mut previous);
            }
        }
    }
}
impl Drop for HistoryFlagCapture {
    fn drop(&mut self) {
        self.flags.values_mut().for_each(super::erase);
    }
}
/// Only the global history command's three legacy scalar flags need this raw
/// spelling seam. Other families, global/secret options and `--` are untouched.
pub(super) fn normalize_history_arguments(arguments: &mut Vec<std::ffi::OsString>) -> Option<HistoryFlagCapture> {
    let mut at = 1;
    while at < arguments.len() {
        let token = arguments[at].to_str()?;
        if token == "--" {
            return None;
        }
        if let Some(option) = token.strip_prefix("--") {
            let key = option.split('=').next()?;
            if matches!(key, "help" | "version") {
                at += 1;
                continue;
            }
            if matches!(key, "type" | "id" | "limit") {
                at += if !option.contains('=') && arguments.get(at + 1).and_then(|value| value.to_str()).is_some_and(|value| !value.starts_with("--")) { 2 } else { 1 };
                continue;
            }
            if !super::catalog().global_flags.iter().any(|name| name == key) {
                return None;
            }
            let switch = super::catalog().flags.iter().find(|flag| flag.long == key)
                .is_some_and(|flag| flag.arity == "switch");
            at += if !option.contains('=') && !switch { 2 } else { 1 };
            continue;
        }
        if token != "history" {
            return None;
        }
        break;
    }
    if at >= arguments.len() {
        return None;
    }
    at = 1;
    let mut capture = HistoryFlagCapture { flags: Default::default() };
    while at < arguments.len() {
        let Some(token) = arguments[at].to_str() else { return Some(capture); };
        if token == "--" {
            break;
        }
        let Some(option) = token.strip_prefix("--") else { at += 1; continue; };
        let (key, assigned) = option.split_once('=').map(|(key, value)| (key, Some(value))).unwrap_or((option, None));
        if !matches!(key, "type" | "id" | "limit") {
            at += 1;
            continue;
        }
        let key = key.to_owned();
        let (value, consumed) = if let Some(value) = assigned {
            // parseArgs uses split('=', 2), retaining only the first value part.
            (Some(value.split('=').next().unwrap_or("").to_owned()), 1)
        } else if let Some(value) = arguments.get(at + 1).and_then(|value| value.to_str()).filter(|value| !value.starts_with("--")) {
            (Some(value.to_owned()), 2)
        } else {
            (None, 1)
        };
        let merged = match value.as_deref() {
            Some(value) => {
                let previous = capture.flags.get(&key).and_then(Value::as_str).filter(|value| !value.is_empty());
                Value::String(previous.map(|previous| format!("{previous}\n{value}")).unwrap_or_else(|| value.to_owned()))
            }
            None => Value::Bool(true),
        };
        if let Some(mut previous) = capture.flags.insert(key.clone(), merged) {
            super::erase(&mut previous);
        }
        // Let Clap parse the command path and every unrelated option unchanged.
        // Scalar values are restored from the zeroizing capture after collection.
        arguments.drain(at..at + consumed);
    }
    Some(capture)
}

pub(super) fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "history" | "history list" | "history show" | "history undo"
    )
}
fn legacy_error(message: impl Into<String>) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: message.into(),
    }
}
/// Fold repeated scalar flags as the installed CLI's appendFlagValue does.
/// An empty previous value resets rather than contributing a leading newline.
fn legacy_flag(i: &Invocation, key: &str) -> Option<String> {
    match i.flags.get(key)? {
        Value::String(value) => Some(value.clone()),
        Value::Array(values) => {
            let mut result = String::new();
            for value in values {
                let value = value.as_str()?;
                if !result.is_empty() {
                    result.push('\n');
                }
                result.push_str(value);
            }
            Some(result)
        }
        _ => None,
    }
}
fn js_whitespace(c: char) -> bool {
    matches!(c, '\u{0009}'..='\u{000d}' | '\u{0020}' | '\u{00a0}' | '\u{1680}'
        | '\u{2000}'..='\u{200a}' | '\u{2028}' | '\u{2029}' | '\u{202f}'
        | '\u{205f}' | '\u{3000}' | '\u{feff}')
}
/// Radix literals are integers. Retain 53 significant bits plus a rounding bit
/// and sticky remainder, avoiding both u64 truncation and double rounding.
fn radix_number(digits: &str, radix: u32) -> f64 {
    if digits.is_empty() {
        return f64::NAN;
    }
    let width = radix.trailing_zeros();
    let mut bit_count = 0usize;
    let mut head = 0u64;
    let mut sticky = false;
    for c in digits.chars() {
        let Some(digit) = c.to_digit(radix).filter(|_| c.is_ascii()) else {
            return f64::NAN;
        };
        for shift in (0..width).rev() {
            let bit = (digit >> shift) & 1;
            if bit_count == 0 && bit == 0 {
                continue;
            }
            bit_count = bit_count.saturating_add(1);
            if bit_count <= 54 {
                head = (head << 1) | u64::from(bit);
            } else {
                sticky |= bit != 0;
            }
        }
    }
    if bit_count <= 53 {
        return head as f64;
    }
    if bit_count > 1024 {
        return f64::INFINITY;
    }
    let mut significand = head >> 1;
    if head & 1 != 0 && (sticky || significand & 1 != 0) {
        significand += 1;
    }
    let mut exponent = bit_count - 1;
    if significand == 1 << 53 {
        significand >>= 1;
        exponent += 1;
    }
    if exponent > 1023 {
        return f64::INFINITY;
    }
    f64::from_bits((((exponent + 1023) as u64) << 52) | (significand & ((1 << 52) - 1)))
}
pub(super) fn js_number(raw: &str) -> f64 {
    let raw = raw.trim_matches(js_whitespace);
    if raw.is_empty() {
        return 0.0;
    }
    match raw {
        "Infinity" | "+Infinity" => return f64::INFINITY,
        "-Infinity" => return f64::NEG_INFINITY,
        _ => {}
    }
    for (prefix, radix) in [("0x", 16), ("0X", 16), ("0b", 2), ("0B", 2), ("0o", 8), ("0O", 8)] {
        if let Some(digits) = raw.strip_prefix(prefix) {
            return radix_number(digits, radix);
        }
    }
    // Rust accepts additional spellings such as inf. Validate ECMAScript's
    // decimal string grammar before using its correctly rounded f64 parser.
    let bytes = raw.as_bytes();
    let mut at = usize::from(matches!(bytes.first(), Some(b'+' | b'-')));
    let mut digits = 0;
    while at < bytes.len() && bytes[at].is_ascii_digit() {
        at += 1;
        digits += 1;
    }
    if bytes.get(at) == Some(&b'.') {
        at += 1;
        while at < bytes.len() && bytes[at].is_ascii_digit() {
            at += 1;
            digits += 1;
        }
    }
    if digits == 0 {
        return f64::NAN;
    }
    if matches!(bytes.get(at), Some(b'e' | b'E')) {
        at += 1;
        if matches!(bytes.get(at), Some(b'+' | b'-')) {
            at += 1;
        }
        let exponent_start = at;
        while at < bytes.len() && bytes[at].is_ascii_digit() {
            at += 1;
        }
        if at == exponent_start {
            return f64::NAN;
        }
    }
    if at != bytes.len() {
        return f64::NAN;
    }
    raw.parse::<f64>().unwrap_or(f64::NAN)
}
/// Rust supplies shortest round-trip digits; apply JavaScript's fixed/scientific
/// display thresholds and explicit positive exponent sign to those digits.
pub(super) fn js_number_string(number: f64) -> String {
    if number.is_nan() {
        return "NaN".into();
    }
    if number == 0.0 {
        return "0".into();
    }
    if number.is_infinite() {
        return if number.is_sign_negative() { "-Infinity" } else { "Infinity" }.into();
    }
    let shortest = number.abs().to_string();
    let (mantissa, exponent) = shortest.split_once(['e', 'E'])
        .map(|(digits, exponent)| (digits, exponent.parse::<i32>().expect("f64 display exponent")))
        .unwrap_or((&shortest, 0));
    let point = mantissa.find('.').unwrap_or(mantissa.len()) as i32 + exponent;
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let leading = digits.len() - digits.trim_start_matches('0').len();
    let digits = digits.trim_start_matches('0').trim_end_matches('0');
    let point = point - leading as i32;
    let mut result = if number.is_sign_negative() { "-".to_owned() } else { String::new() };
    if point > 0 && point <= 21 {
        let point = point as usize;
        if digits.len() <= point {
            result.push_str(digits);
            result.extend(std::iter::repeat_n('0', point - digits.len()));
        } else {
            result.push_str(&digits[..point]);
            result.push('.');
            result.push_str(&digits[point..]);
        }
    } else if point > -6 && point <= 0 {
        result.push_str("0.");
        result.extend(std::iter::repeat_n('0', (-point) as usize));
        result.push_str(digits);
    } else {
        result.push_str(&digits[..1]);
        if digits.len() > 1 {
            result.push('.');
            result.push_str(&digits[1..]);
        }
        result.push('e');
        let exponent = point - 1;
        if exponent >= 0 {
            result.push('+');
        }
        result.push_str(&exponent.to_string());
    }
    result
}
fn list_limit(i: &Invocation) -> Option<String> {
    let number = js_number(&legacy_flag(i, "limit")?);
    (number != 0.0 && !number.is_nan()).then(|| js_number_string(number))
}

fn change_set_id<'a>(i: &'a Invocation, action: &str) -> Result<&'a str, CliError> {
    i.positionals
        .first()
        .map(String::as_str)
        .filter(|v| !v.is_empty())
        .ok_or_else(|| {
            legacy_error(format!(
                "Missing change set ID. Usage: openmates history {action} <change-set-id>"
            ))
        })
}
/// JavaScript String(value) for the original metadata table's nullable fields.
/// Native CliOutput still escapes terminal control/bidi characters.
pub(super) fn js_string(value: &Value) -> String {
    match value {
        Value::Null => "null".into(),
        Value::String(value) => value.clone(),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value
            .as_f64()
            .map(js_number_string)
            .unwrap_or_else(|| value.to_string()),
        Value::Object(_) => "[object Object]".into(),
        Value::Array(values) => values
            .iter()
            .map(|v| {
                if v.is_null() {
                    String::new()
                } else {
                    js_string(v)
                }
            })
            .collect::<Vec<_>>()
            .join(","),
    }
}
fn field(value: &Value, key: &str, fallback: &str) -> String {
    value
        .get(key)
        .filter(|v| !v.is_null())
        .map(js_string)
        .unwrap_or_else(|| fallback.into())
}
fn list_output(i: &Invocation, rows: Vec<Value>) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        return CliOutput::json(&json!({"change_sets": rows}));
    }
    // console.log is never called for the original empty list: no extra line.
    if rows.is_empty() {
        return Ok(CliOutput {
            stdout: String::new(),
            stderr: String::new(),
            exit_code: 0,
        });
    }
    Ok(CliOutput::text(
        rows.iter()
            .map(|row| {
                format!(
                    "{}  {}  {}  {}",
                    field(row, "change_set_id", "-"),
                    field(row, "namespace", "-"),
                    field(row, "action_type", "-"),
                    field(row, "status", "-")
                )
            })
            .collect::<Vec<_>>()
            .join("\n"),
    ))
}
fn undo_output(i: &Invocation, result: Value) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        return CliOutput::json(&result);
    }
    Ok(CliOutput::text(format!(
        "Undo change set created: {}",
        field(&result["change_set"], "change_set_id", "unknown")
    )))
}
fn history_error(action: &str, error: HistoryRequestError) -> CliError {
    // Owner revocation and cancellation must retain their security/lifecycle
    // meaning. A numeric HTTP status never authorizes a fallback or replay.
    if !matches!(error.source, Error::Expired | Error::Cancelled)
        && let Some(status @ 400..=599) = error.http_status
    {
        return legacy_error(format!("Workspace history {action} failed with HTTP {status}"));
    }
    error.source.into()
}
async fn execute_service(
    i: &Invocation,
    mut history: History<'_>,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    // These original scope flags do not scope global owner history. Do not
    // switch Teams or invalidate a protected chat cache merely to render it.
    super::handlers::flags(i, &["type", "id", "limit", "personal", "team"])?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let path = i.command_path();
    let output = match path.as_str() {
        "history" if !i.positionals.is_empty() => {
            return Err(legacy_error(format!(
                "Unknown history command '{}'. Run 'openmates history --help'.",
                i.positionals[0]
            )));
        }
        "history" | "history list" => {
            let options = HistoryListOptions {
                object_type: legacy_flag(i, "type").filter(|v| !v.is_empty()),
                object_id: legacy_flag(i, "id").filter(|v| !v.is_empty()),
                limit: None,
            };
            list_output(i, history.list_for_cli(options, list_limit(i).as_deref()).await.map_err(|error| history_error("list", error))?)?
        }
        "history show" => CliOutput::json(&history.show_for_cli(change_set_id(i, "show")?).await.map_err(|error| history_error("show", error))?)?,
        "history undo" => {
            // One shared SDK invocation only. No local retry, replay, object
            // restoration, guessed ownership or alternate deletion operation.
            undo_output(i, history.undo_for_cli(change_set_id(i, "undo")?).await.map_err(|error| history_error("undo", error))?)?
        }
        _ => {
            return Err(legacy_error(
                "Unknown history command. Run 'openmates history --help'.",
            ));
        }
    };
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    Ok(output)
}
pub(super) async fn execute(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    client.set_operation_cancel(cancel.clone());
    execute_service(i, client.history(), cancel).await
}
pub async fn execute_sdk_global_history(
    i: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    client.set_operation_cancel(cancel.clone());
    execute_service(i, client.history(), cancel).await
}

#[cfg(test)]
mod tests {
    use super::*;
    fn invocation(action: &str) -> Invocation {
        Invocation {
            path: if action.is_empty() {
                vec!["history".into()]
            } else {
                vec!["history".into(), action.into()]
            },
            positionals: vec![],
            flags: Default::default(),
        }
    }
    #[test]
    fn global_list_keeps_change_sets_envelope_and_empty_human_stdout() {
        let mut i = invocation("list");
        assert_eq!(list_output(&i, vec![]).ok().unwrap().stdout, "");
        let rows = vec![
            json!({"change_set_id":"chg_synthetic","namespace":"plans","action_type":"edit","status":"applied","opaque":{"encrypted_ref":"KEEP"}}),
        ];
        assert_eq!(
            list_output(&i, rows.clone()).ok().unwrap().stdout,
            "chg_synthetic  plans  edit  applied\n"
        );
        i.flags.insert("json".into(), json!(true));
        let out = list_output(&i, rows.clone()).ok().unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&out.stdout).ok().unwrap(),
            json!({"change_sets":rows})
        );
        assert!(out.stderr.is_empty());
        assert_eq!(out.exit_code, 0);
    }
    #[test]
    fn global_human_nullish_fields_and_terminal_safety_remain_distinct_from_object_history() {
        let i = invocation("list");
        let out=list_output(&i,vec![json!({"change_set_id":null,"namespace":false,"action_type":[1,null,"x"],"status":{"opaque":true}})]).ok().unwrap();
        assert_eq!(out.stdout, "-  false  1,,x  [object Object]\n");
        let out = list_output(
            &i,
            vec![json!({"change_set_id":"chg_\u{1b}[31m","namespace":"x"})],
        )
        .ok()
        .unwrap();
        assert!(!out.stdout.contains('\u{1b}'));
        assert!(out.stdout.contains("\\u001b"));
    }
    #[test]
    fn show_and_undo_missing_id_keep_original_error_exit_and_message() {
        for action in ["show", "undo"] {
            let i = invocation(action);
            let error = change_set_id(&i, action).err().unwrap();
            assert_eq!(error.exit_code(), 1);
            assert_eq!(error.code(), "command_failed");
            assert_eq!(
                error.to_string(),
                format!("Missing change set ID. Usage: openmates history {action} <change-set-id>")
            );
        }
        let mut i = invocation("undo");
        i.positionals = vec!["chg_0123456789abcdef0123456789abcdef".into()];
        assert_eq!(change_set_id(&i, "undo").ok().unwrap(), i.positionals[0]);
    }
    #[test]
    fn undo_human_uses_new_change_set_and_json_preserves_every_field() {
        let mut i = invocation("undo");
        let value = json!({"change_set":{"change_set_id":"chg_inverse"},"entries":[{"opaque":"KEEP"}],"undo_of":"chg_original"});
        assert_eq!(
            undo_output(&i, value.clone()).ok().unwrap().stdout,
            "Undo change set created: chg_inverse\n"
        );
        assert_eq!(
            undo_output(&i, json!({})).ok().unwrap().stdout,
            "Undo change set created: unknown\n"
        );
        i.flags.insert("json".into(), json!(true));
        assert_eq!(
            serde_json::from_str::<Value>(&undo_output(&i, value.clone()).ok().unwrap().stdout)
                .ok()
                .unwrap(),
            value
        );
    }
    #[test]
    fn installed_node_number_and_repeated_flag_oracle_matches_exact_wire_values() {
        let oracle: Value = serde_json::from_str(include_str!("../../tests/fixtures/global-history-number-oracle.json")).unwrap();
        assert_eq!(oracle["oracle"]["node"], "v24.20.0");
        for case in oracle["cases"].as_array().unwrap() {
            let argv = std::iter::once("openmates").chain(case["argv"].as_array().unwrap().iter().map(|value| value.as_str().unwrap()));
            let parsed = super::super::parse_from(argv).unwrap();
            let i = parsed.invocation.as_ref().unwrap();
            for key in ["type", "id", "limit"] {
                assert_eq!(i.flags.get(key), case["flags"].get(key), "{:?}", case["argv"]);
            }
            let number = legacy_flag(i, "limit").map(|raw| js_number(&raw)).unwrap_or(f64::NAN);
            if case["number_string"] != "NaN" {
                assert_eq!(format!("{:016x}", number.to_bits()), case["number_bits"].as_str().unwrap(), "{:?}", case["argv"]);
            } else {
                assert!(number.is_nan(), "{:?}", case["argv"]);
            }
            assert_eq!(js_number_string(number), case["number_string"].as_str().unwrap(), "{:?}", case["argv"]);
            assert_eq!(list_limit(i), case["limit_query"].as_str().map(str::to_owned), "{:?}", case["argv"]);
        }
    }
    #[test]
    fn actual_installed_cli_error_catch_oracle_matches_both_output_modes() {
        let oracle: Value = serde_json::from_str(include_str!("../../tests/fixtures/global-history-number-oracle.json")).unwrap();
        for case in oracle["error_cases"].as_array().unwrap() {
            let action = case["action"].as_str().unwrap();
            let status = case["status"].as_u64().unwrap() as u16;
            let source = if status == 409 { Error::Conflict } else { Error::Invalid("private server detail must never escape") };
            let error = history_error(action, HistoryRequestError { source, http_status: Some(status) });
            let stderr = if case["json"] == true {
                format!("{}\n", error.structured_error())
            } else {
                format!("Error: {error}\n")
            };
            assert_eq!(stderr, case["stderr"].as_str().unwrap());
            assert_eq!(u64::from(error.exit_code()), case["exit_code"].as_u64().unwrap());
            assert_eq!(case["stdout"], "");
        }
    }
    #[test]
    fn repeated_history_scalar_flags_fold_newlines_and_preserve_empty_reset() {
        for (values, expected) in [
            (json!(["1", "2"]), "1\n2"), (json!(["", "2"]), "2"),
            (json!(["1", ""]), "1\n"), (json!(["", ""]), ""),
        ] {
            let mut i = invocation("list");
            i.flags.insert("limit".into(), values.clone());
            i.flags.insert("type".into(), values.clone());
            i.flags.insert("id".into(), values);
            for key in ["limit", "type", "id"] {
                assert_eq!(legacy_flag(&i, key).as_deref(), Some(expected));
            }
        }
        let parsed = super::super::parse_from(["openmates", "history", "list", "--limit", "1", "--limit", "2", "--type", "task", "--type", "plan"]).unwrap();
        let i = parsed.invocation.as_ref().unwrap();
        assert_eq!(list_limit(i), None);
        assert_eq!(legacy_flag(i, "type").as_deref(), Some("task\nplan"));
    }
    #[test]
    fn history_scalar_normalization_does_not_touch_other_commands_secrets_or_end_of_options() {
        use std::ffi::OsString;
        for raw in [
            vec!["openmates", "tasks", "list", "--limit=1=2"],
            vec!["openmates", "--api-key", "history", "tasks", "list", "--limit=1=2"],
            vec!["openmates", "history", "list", "--", "--limit=1=2"],
        ] {
            let mut args: Vec<OsString> = raw.iter().map(|value| OsString::from(*value)).collect();
            let before = args.clone();
            let _capture = normalize_history_arguments(&mut args);
            assert_eq!(args, before);
        }
        let parsed = super::super::parse_from(["openmates", "--api-key", "synthetic-private-key", "history", "list", "--limit", "--type=a=b"]).unwrap();
        assert_eq!(parsed.globals.api_key.as_deref().map(String::as_str), Some("synthetic-private-key"));
        let i = parsed.invocation.as_ref().unwrap();
        assert_eq!(i.flags.get("limit"), Some(&Value::Bool(true)));
        assert_eq!(legacy_flag(i, "type").as_deref(), Some("a"));
    }
    #[test]
    fn ordinary_http_errors_keep_legacy_code_and_text_without_body_details() {
        for (action, source, status) in [
            ("list", Error::Invalid("private detail must never escape"), 422),
            ("show", Error::Invalid("private detail must never escape"), 404),
            ("undo", Error::Conflict, 409),
            ("list", Error::Offline, 503),
        ] {
            let error = history_error(action, HistoryRequestError { source, http_status: Some(status) });
            assert_eq!(error.exit_code(), 1);
            assert_eq!(error.structured_error(), json!({"error":{"code":"command_failed", "message":format!("Workspace history {action} failed with HTTP {status}")}}));
            assert!(!error.to_string().contains("private"));
        }
        for source in [Error::Expired, Error::Cancelled] {
            assert!(matches!(history_error("show", HistoryRequestError { source, http_status: Some(403) }), CliError::Client(error) if error == source));
        }
        assert!(matches!(history_error("show", Error::Forbidden.into()), CliError::Client(Error::Forbidden)));
        assert!(matches!(history_error("show", HistoryRequestError { source: Error::Forbidden, http_status: Some(302) }), CliError::Client(Error::Forbidden)));
    }
    #[test]
    fn parser_and_requirements_keep_authenticated_default_global_list() {
        let parsed = super::super::parse_from([
            "openmates",
            "history",
            "--json",
            "--type",
            "project",
            "--id",
            "owned",
            "--limit",
            "50",
        ])
        .ok()
        .unwrap();
        let i = parsed.invocation.as_ref().unwrap();
        assert_eq!(i.command_path(), "history");
        assert_eq!(i.text("type"), Some("project"));
        assert!(super::super::requirements(i).authenticated);
        assert!(super::super::requirements(i).supported);
        assert!(super::super::execute_public(i).is_none());
        let parsed = super::super::parse_from(["openmates", "history", "show", "chg_synthetic"])
            .ok()
            .unwrap();
        assert_eq!(
            parsed.invocation.as_ref().unwrap().positionals,
            ["chg_synthetic"]
        );
    }
    #[tokio::test]
    async fn cancelled_global_undo_does_not_dispatch_any_shared_operation() {
        let i = invocation("undo");
        let mut client = Client::new("http://127.0.0.1:1", None).ok().unwrap();
        let cancel = CancellationToken::new();
        cancel.cancel();
        assert!(matches!(
            execute(&i, &mut client, cancel).await,
            Err(CliError::Client(Error::Cancelled))
        ));
    }
}
