//! ZIP export parity: replays the page adapter's requests and TypeScript outputs
//! from `web_transfer_zip_ts_vectors.json`, plus Rust-only edge checks.
use super::*;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_transfer_zip_ts_vectors.json"))
        .expect("zip vectors parse")
}

/// Runs a unit entry point on the request exactly as the page serialized it.
fn call(f: fn(&str) -> Result<String, String>, request: &Value) -> Value {
    serde_json::from_str(&f(&request.to_string()).expect("protocol-valid input"))
        .expect("json output")
}

#[test]
fn chat_zip_plans_equal_typescript() {
    let cases = vectors()["chat"].as_array().expect("chat cases").clone();
    assert!(cases.len() >= 9);
    for case in cases {
        let name = case["name"].as_str().expect("name");
        let got = call(zip_chat_plan_json, &case["request"]);
        assert_eq!(got["kind"], "ok", "{name}");
        assert_eq!(got["base"], case["out"]["base"], "{name}: base");
        assert_eq!(got["zipName"], case["out"]["zipName"], "{name}: zip name");
        assert_eq!(got["entries"], case["out"]["entries"], "{name}: entries");
    }
}

#[test]
fn code_file_names_equal_typescript() {
    for case in vectors()["codeFiles"].as_array().expect("code file cases") {
        let name = case["name"].as_str().expect("name");
        let got = call(zip_code_files_json, &case["request"]);
        assert_eq!(got["names"], case["out"]["names"], "{name}: names");
        if !case["out"]["zipName"].is_null() {
            assert_eq!(got["zipName"], case["out"]["zipName"], "{name}: zip name");
        }
    }
}

#[test]
fn application_zip_equals_typescript() {
    for case in vectors()["application"]
        .as_array()
        .expect("application cases")
    {
        let name = case["name"].as_str().expect("name");
        let got = call(zip_application_json, &case["request"]);
        assert_eq!(got["zipName"], case["out"]["zipName"], "{name}: zip name");
        assert_eq!(got["paths"], case["out"]["paths"], "{name}: paths");
    }
}

#[test]
fn bulk_zip_name_equals_typescript() {
    let bulk = &vectors()["bulk"];
    let got = call(zip_bulk_name_json, &bulk["request"]);
    assert_eq!(got["zipName"], bulk["out"]["zipName"]);
}

/// Account vectors keep the request as source text: re-serializing through `Value`
/// would sort object keys, but the archive must see the page's key order.
#[derive(serde::Deserialize)]
struct AccountCase<'a> {
    name: String,
    #[serde(borrow)]
    request: &'a serde_json::value::RawValue,
    out: Value,
}

#[derive(serde::Deserialize)]
struct AccountVectors<'a> {
    #[serde(borrow)]
    account: Vec<AccountCase<'a>>,
}

#[test]
fn account_export_archives_equal_typescript() {
    let text = include_str!("web_transfer_zip_ts_vectors.json");
    let parsed: AccountVectors = serde_json::from_str(text).expect("account vectors parse");
    assert!(parsed.account.len() >= 9);
    let mut errors = 0;
    for case in parsed.account {
        let got: Value = serde_json::from_str(
            &account_export_archive_json(case.request.get()).expect("protocol-valid input"),
        )
        .expect("json output");
        assert_eq!(got["kind"], case.out["kind"], "{}: {got}", case.name);
        if case.out["kind"] == "ok" {
            assert_eq!(got["entries"], case.out["entries"], "{}", case.name);
        } else {
            errors += 1;
            assert_eq!(got["message"], case.out["message"], "{}", case.name);
        }
    }
    assert!(errors >= 5, "the secret guards are exercised");
}

#[test]
fn trailing_dot_stays_when_stripping_extensions() {
    assert_eq!(zip::strip_extension("a.b.c"), "a.b");
    assert_eq!(zip::strip_extension("trailing."), "trailing.");
    assert_eq!(zip::strip_extension("noext"), "noext");
    assert_eq!(zip::strip_extension(".hidden"), "");
}

#[test]
fn malformed_zip_input_is_a_protocol_refusal() {
    assert_eq!(zip_chat_plan_json("{}"), Err("protocol".into()));
    assert_eq!(zip_chat_plan_json("not json"), Err("protocol".into()));
    assert_eq!(
        zip_code_files_json("{\"nowIso\":1,\"files\":[]}"),
        Err("protocol".into())
    );
    assert_eq!(
        zip_application_json("{\"paths\":[1]}"),
        Err("protocol".into())
    );
    assert_eq!(zip_bulk_name_json("{}"), Err("protocol".into()));
    assert_eq!(
        account_export_archive_json("{\"export\":{}}"),
        Err("protocol".into())
    );
}
