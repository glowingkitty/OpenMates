use serde_json::json;

use super::run_json;
use crate::work::{CheckDefinition, parse_source_spec};

fn run(op: &str, input: serde_json::Value) -> serde_json::Value {
    serde_json::from_str(&run_json(op, &input.to_string()).expect("op runs")).expect("json")
}

#[test]
fn revision_view_parses_the_definition_and_refuses_a_hash_mismatch() {
    let definition = CheckDefinition {
        requires_deterministic: false,
        sources: vec![parse_source_spec("unit:required:tests/a").unwrap()],
    }
    .normalized()
    .unwrap();
    let text = definition.canonical_text().unwrap();
    let input = |hash: &str| {
        json!({
            "record": {"revision_id": "r1", "definition_hash": hash, "encrypted_definition": "x",
                       "sources": [], "created_at": 1, "revision_number": 2},
            "fields": {"encrypted_definition": text}
        })
    };
    let view = run(
        "checkRevisionView",
        input(&definition.definition_hash().unwrap()),
    );
    assert_eq!(view["definition"]["sources"][0]["ref"], "tests/a");
    assert_eq!(view["revisionNumber"], 2);
    assert!(
        run("checkRevisionView", input(&"0".repeat(64)))["error"]
            .as_str()
            .unwrap()
            .contains("hash")
    );
}

#[test]
fn run_view_aggregates_and_flags_staleness() {
    let sources = json!([
        {"source_binding_id": "a", "source_kind": "unit", "role": "required"},
        {"source_binding_id": "h", "source_kind": "human_confirmation", "role": "required"}
    ]);
    let view = run(
        "checkRunView",
        json!({
            "record": {"run_id": "r", "check_id": "c", "check_revision_id": "v1", "subject_revision": "abc",
                       "status": "waiting_for_confirmation", "created_at": 1, "encrypted_summary": "x",
                       "source_results": [{"source_binding_id": "a", "status": "passed", "encrypted_result": "y"}]},
            "fields": {"encrypted_summary": "Nightly", "results": {"a": "ok"}},
            "sources": sources, "currentRevisionId": "v1"
        }),
    );
    assert_eq!(view["aggregateStatus"], "waiting_for_confirmation");
    assert_eq!(view["summary"], "Nightly");
    assert_eq!(view["sourceResults"][0]["detail"], "ok");
    // The human source has no stored result yet and is reported as pending.
    assert_eq!(view["sourceResults"][1]["source_binding_id"], "h");
    assert_eq!(view["sourceResults"][1]["status"], "pending");
    assert_eq!(view["stale"], false);
}

#[test]
fn passed_run_goes_stale_on_a_new_revision() {
    let view = run(
        "checkRunView",
        json!({
            "record": {"run_id": "r", "check_id": "c", "check_revision_id": "v1", "status": "passed", "created_at": 1},
            "fields": {}, "sources": [], "currentRevisionId": "v2"
        }),
    );
    assert_eq!(view["stale"], true);
}

#[test]
fn bodies_and_validation_refuse_bad_input() {
    assert_eq!(
        run("checkConfirmBody", json!({"decision": "waived"})),
        json!({"decision": "waived"})
    );
    assert!(run("checkConfirmBody", json!({"decision": "maybe"}))["error"].is_string());
    assert!(
        run(
            "checkResultBody",
            json!({"source_kind": "human_confirmation", "status": "passed"})
        )["error"]
            .as_str()
            .unwrap()
            .contains("HUMAN")
    );
    assert_eq!(
        run(
            "checkResultBody",
            json!({"source_kind": "unit", "status": "failed", "junk": 1})
        ),
        json!({"source_kind": "unit", "status": "failed"})
    );
    let no_required = json!({"sources": [{"source_binding_id": "a", "source_kind": "unit", "role": "supporting"}]});
    assert_eq!(
        run("checkValidate", no_required)["error"],
        "CHECK_REQUIRED_SOURCE_MISSING"
    );
    assert_eq!(
        run("checkAggregate", json!({"sources": [], "statuses": {}})),
        "passed"
    );
    assert!(run_json("checkNope", "{}").is_err());
}

#[test]
fn create_body_normalises_sources_and_hashes_the_definition() {
    let input = json!({
        "check_id": "c1", "revision_id": "r1", "project_id": "p1", "title": " Pancakes ",
        "requires_deterministic": false,
        "sources": [
            {"source_kind": "unit", "role": "required", "title": "Unit", "ref": "tests/a"},
            {"source_kind": "human_confirmation", "role": "required", "title": "Taste", "ref": "Taste it"}
        ]
    });
    let out = run("checkCreateBody", input.clone());
    assert_eq!(out["title"], "Pancakes");
    assert_eq!(
        out["body"]["revision"]["sources"].as_array().unwrap().len(),
        2
    );
    let text = out["definition_text"].as_str().unwrap();
    assert_eq!(
        out["body"]["revision"]["definition_hash"],
        crate::work::text_hash(text)
    );
    assert_eq!(out["hashed_project_id"].as_str().unwrap().len(), 64);
    let mut empty = input;
    empty["title"] = json!(" ");
    assert!(run("checkCreateBody", empty)["error"].is_string());
}
