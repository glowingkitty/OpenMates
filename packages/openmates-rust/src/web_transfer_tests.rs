//! Replays the TypeScript-generated import vectors (web_transfer_ts_vectors.json,
//! checked against chatImportService.ts by transferImportVectors.test.ts) through
//! the same op sequence the page adapter (rustChatImport.ts) drives.
use super::*;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_transfer_ts_vectors.json")).expect("vectors parse")
}
fn call(f: fn(&str) -> Result<String, String>, input: Value) -> Value {
    serde_json::from_str(&f(&input.to_string()).expect("protocol-valid input"))
        .expect("json output")
}
fn assert_outcome(name: &str, got: &Value, expected: &Value) {
    if expected["ok"] == true {
        assert_eq!(got["kind"], "ok", "{name}: {got}");
        assert_eq!(got["parsed"], expected["parsed"], "{name}");
        assert_eq!(got["estimates"], expected["estimates"], "{name}");
    } else if expected["syntax"] == true {
        assert_eq!(got["kind"], "syntax", "{name}: {got}");
    } else {
        assert_eq!(got["kind"], "error", "{name}: {got}");
        assert_eq!(got["message"], expected["message"], "{name}");
    }
}
fn parse_text(case: &Value, text: &Value, container: &str, offset: &Value) -> Value {
    let meta = json!({"fileName": case["fileName"], "container": container,
        "selectedSource": case.get("selectedSource").cloned().unwrap_or(Value::Null), "utcOffsetMinutes": offset});
    let out = parse_json_import_json(&meta.to_string(), text.as_str().expect("text"))
        .expect("protocol-valid input");
    serde_json::from_str(&out).expect("json output")
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn json_imports_equal_typescript() {
    let v = vectors();
    for case in v["json"].as_array().expect("json cases") {
        let name = case["name"].as_str().expect("name");
        let route = call(import_route_json, json!({"fileName": case["fileName"]}));
        let got = if route["kind"] == "json" {
            parse_text(case, &case["text"], "json", &v["utcOffsetMinutes"])
        } else {
            route
        };
        assert_outcome(name, &got, &case["out"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn zip_imports_equal_typescript() {
    let v = vectors();
    for case in v["zip"].as_array().expect("zip cases") {
        let name = case["name"].as_str().expect("name");
        assert_eq!(
            call(import_route_json, json!({"fileName": case["fileName"]}))["kind"],
            "zip",
            "{name}"
        );
        let plan = call(zip_plan_json, json!({"entries": case["zipEntries"]}));
        let yaml = |entry: &Value| {
            case["yaml"]
                .get(entry.as_str().expect("entry name"))
                .cloned()
                .unwrap_or(Value::Null)
        };
        let got = match plan["kind"].as_str() {
            Some("conversations") => {
                let text = &case["entries"][plan["name"].as_str().expect("name")];
                parse_text(case, text, "zip", &v["utcOffsetMinutes"])
            }
            Some("openmates") => {
                let manifest = yaml(&json!("manifest.yml"));
                let checked = call(openmates_manifest_json, json!({"manifest": manifest}));
                if checked["kind"] == "ok" {
                    let values = |key: &str| {
                        plan[key]
                            .as_array()
                            .expect("names")
                            .iter()
                            .map(yaml)
                            .collect::<Vec<_>>()
                    };
                    let chats: Vec<Value> = plan["chats"]
                        .as_array()
                        .expect("chats")
                        .iter()
                        .map(|n| json!({"name": n, "value": yaml(n)}))
                        .collect();
                    call(
                        parse_openmates_archive_json,
                        json!({"manifest": manifest, "chats": chats, "embeds": values("embeds"),
                        "uploads": values("uploads"), "fileName": case["fileName"],
                        "selectedSource": case.get("selectedSource").cloned().unwrap_or(Value::Null), "utcOffsetMinutes": v["utcOffsetMinutes"]}),
                    )
                } else {
                    checked
                }
            }
            _ => plan,
        };
        assert_outcome(name, &got, &case["out"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn scan_batch_plan_equals_typescript() {
    for case in vectors()["batches"].as_array().expect("batch cases") {
        let chats: Vec<Value> = case["counts"]
            .as_array()
            .expect("counts")
            .iter()
            .zip(case["fingerprints"].as_array().expect("fps"))
            .map(|(n, f)| json!({"fingerprint": f, "messageCount": n}))
            .collect();
        let got = call(
            batch_plan_json,
            json!({"chats": chats, "maxMessages": case["maxMessages"]}),
        );
        if case["out"]["ok"] == true {
            assert_eq!(got["batches"], case["out"]["batches"], "{case}");
        } else {
            assert_eq!(got["message"], case["out"]["message"], "{case}");
        }
    }
}

#[test]
fn malformed_unit_input_is_a_protocol_refusal() {
    assert_eq!(parse_json_import_json("{}", "[]"), Err("protocol".into()));
    assert_eq!(
        zip_plan_json("{\"entries\":[{\"name\":1}]}"),
        Err("protocol".into())
    );
    assert_eq!(
        parse_json_import_json(&json!({"fileName": "a.json", "container": "json", "selectedSource": "nope", "utcOffsetMinutes": 0}).to_string(), "[]"),
        Err("protocol".into())
    );
}
