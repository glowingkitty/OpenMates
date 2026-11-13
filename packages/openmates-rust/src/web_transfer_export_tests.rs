//! Chat export parity: replays the page adapter's requests and TypeScript outputs
//! from `web_transfer_export_ts_vectors.json`, plus Rust-only edge checks.
use super::export::restore_pii;
use super::yaml::js_number_string;
use super::*;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_transfer_export_ts_vectors.json"))
        .expect("export vectors parse")
}
fn call(f: fn(&str) -> Result<String, String>, input: &Value) -> Value {
    serde_json::from_str(&f(&input.to_string()).expect("protocol-valid input"))
        .expect("json output")
}

/// One YAML vector with its request kept as source text: re-serializing through
/// `Value` would sort object keys, but the emitter must see the page's key order.
#[derive(serde::Deserialize)]
struct YamlCase<'a> {
    name: String,
    #[serde(borrow)]
    request: &'a serde_json::value::RawValue,
    out: String,
}

#[derive(serde::Deserialize)]
struct YamlVectors<'a> {
    #[serde(borrow)]
    yaml: Vec<YamlCase<'a>>,
}

#[test]
fn chat_yaml_equals_typescript() {
    let text = include_str!("web_transfer_export_ts_vectors.json");
    let parsed: YamlVectors = serde_json::from_str(text).expect("yaml vectors parse");
    assert!(!parsed.yaml.is_empty());
    for case in parsed.yaml {
        let got: Value = serde_json::from_str(
            &export_yaml_json(case.request.get()).expect("protocol-valid input"),
        )
        .expect("json output");
        assert_eq!(got["kind"], "ok", "{}: {got}", case.name);
        assert_eq!(got["yaml"], case.out, "{}", case.name);
    }
}

#[test]
fn filenames_equal_typescript() {
    for case in vectors()["filename"].as_array().expect("filename cases") {
        let name = case["name"].as_str().expect("name");
        let got = call(export_filename_json, &case["request"]);
        if case["out"]["ok"] == true {
            assert_eq!(got["kind"], "ok", "{name}: {got}");
            assert_eq!(got["filename"], case["out"]["filename"], "{name}");
        } else {
            assert_eq!(got["kind"], "error", "{name}: {got}");
            assert_eq!(got["message"], case["out"]["message"], "{name}");
        }
    }
}

#[test]
fn pii_restore_equals_typescript() {
    for case in vectors()["pii"].as_array().expect("pii cases") {
        let name = case["name"].as_str().expect("name");
        let mappings: Vec<(Vec<u16>, Vec<u16>)> = case["mappings"]
            .as_array()
            .expect("mappings")
            .iter()
            .map(|m| {
                let units = |key: &str| m[key].as_str().expect(key).encode_utf16().collect();
                (units("placeholder"), units("original"))
            })
            .collect();
        let text = case["text"].as_str().expect("text");
        assert_eq!(
            restore_pii(text, &mappings),
            case["out"].as_str().expect("out"),
            "{name}"
        );
    }
}

#[test]
fn draft_kind_equals_typescript() {
    for case in vectors()["draftKind"].as_array().expect("draft cases") {
        let got = call(export_draft_kind_json, &json!({"draft": case["draft"]}));
        assert_eq!(got["cleartext"], case["cleartext"], "{}", case["draft"]);
    }
}

#[test]
fn numbers_print_like_javascript() {
    let cases: [(f64, &str); 14] = [
        (0.0, "0"),
        (-0.0, "0"),
        (1.0, "1"),
        (-2.5, "-2.5"),
        (0.1, "0.1"),
        (1e21, "1e+21"),
        (1e20, "100000000000000000000"),
        (123456789012345680000.0, "123456789012345680000"),
        (1e-7, "1e-7"),
        (1.5e-7, "1.5e-7"),
        (0.000001, "0.000001"),
        (5e-324, "5e-324"),
        (f64::MAX, "1.7976931348623157e+308"),
        (1152921504606846976.0, "1152921504606847000"),
    ];
    for (value, expected) in cases {
        assert_eq!(js_number_string(value), expected, "{value:e}");
    }
}

#[test]
fn malformed_export_input_is_a_protocol_refusal() {
    assert_eq!(export_yaml_json("{}"), Err("protocol".into()));
    assert_eq!(export_yaml_json("not json"), Err("protocol".into()));
    assert_eq!(
        export_filename_json("{\"extension\":1}"),
        Err("protocol".into())
    );
    assert_eq!(
        export_draft_kind_json("{\"draft\":null}"),
        Err("protocol".into())
    );
    let bad_embed = json!({"exportedAt": "t", "titles": {}, "summaries": {}, "messages": [],
        "checkpoints": [], "embeds": [{"kind": "other"}]});
    assert_eq!(
        export_yaml_json(&bad_embed.to_string()),
        Err("protocol".into())
    );
    let bad_pii = json!({"exportedAt": "t", "titles": {}, "summaries": {}, "messages": [],
        "checkpoints": [], "embeds": [], "pii": {"hidden": false, "mappings": [{"placeholder": 1}]}});
    assert_eq!(
        export_yaml_json(&bad_pii.to_string()),
        Err("protocol".into())
    );
}
