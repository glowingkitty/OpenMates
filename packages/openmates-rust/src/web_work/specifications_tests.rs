use serde_json::json;
use sha2::{Digest, Sha256};

use super::run_json;

fn run(op: &str, input: serde_json::Value) -> serde_json::Value {
    serde_json::from_str(&run_json(op, &input.to_string()).expect("op runs")).expect("json")
}

#[test]
fn revision_view_parses_the_document_and_refuses_a_hash_mismatch() {
    let document = r#"{"title":"Recipes","summary":"S"}"#;
    let hash = format!("{:x}", Sha256::digest(document.as_bytes()));
    let input = |hash: &str| {
        json!({
            "record": {"revision_id": "r1", "content_hash": hash, "encrypted_title": "x", "encrypted_summary": "y",
                       "encrypted_specification_document": "x", "revision_number": 2},
            "fields": {"encrypted_title": "Recipes", "encrypted_summary": "S", "encrypted_specification_document": document}
        })
    };
    let view = run("specificationRevisionView", input(&hash));
    assert_eq!(view["document"]["title"], "Recipes");
    assert_eq!(view["revisionNumber"], 2);
    assert_eq!(view["title"], "Recipes");
    let refused = run("specificationRevisionView", input(&"0".repeat(64)));
    assert!(refused["error"].as_str().unwrap().contains("hash"));
}

#[test]
fn head_view_and_approve_body() {
    let head = run(
        "specificationView",
        json!({
            "record": {"specification_id": "s1", "status": "draft", "encrypted_title": "x", "encrypted_summary": "y", "created_at": 1, "updated_at": 2},
            "fields": {"encrypted_title": "T", "encrypted_summary": "S"}
        }),
    );
    assert_eq!(head["title"], "T");
    assert_eq!(head["currentRevisionId"], serde_json::Value::Null);
    let body = run(
        "specificationApproveBody",
        json!({"revision": {"revision_id": "r1", "content_hash": "ab"}}),
    );
    assert_eq!(body, json!({"revision_id": "r1", "content_hash": "ab"}));
    assert!(
        run_json(
            "specificationApproveBody",
            &json!({"revision": {"revision_id": "r1"}}).to_string()
        )
        .is_err()
    );
    assert!(run_json("specificationNope", "{}").is_err());
}

#[test]
fn create_plan_fixes_the_committed_text_and_refuses_unresolvable_documents() {
    let ids = json!({"specification_id": "6f1c2f0e-7a41-4c5d-9e0b-1d2a3b4c5d6e", "revision_id": "0b8f6a52-33c4-4d57-8a1e-9c7d5e4f3a21"});
    let input = |document: serde_json::Value| {
        let mut input = ids.clone();
        input["document"] = document;
        input
    };
    let plan = run(
        "specificationCreatePlan",
        input(
            json!({"title": " Recipes ", "summary": "S", "requirements": [{"id": "r1", "statement": "x", "proof": {"state": "open"}}]}),
        ),
    );
    let text = plan["document_text"].as_str().unwrap();
    assert_eq!(
        plan["content_hash"],
        format!("{:x}", Sha256::digest(text.as_bytes()))
    );
    assert_eq!(plan["title"], "Recipes");
    assert!(
        !text.contains("proof"),
        "unknown reader fields are not committed"
    );
    assert_eq!(plan["specification_id"], ids["specification_id"]);
    let refused = run(
        "specificationCreatePlan",
        input(json!({"title": "", "summary": "S"})),
    );
    assert!(refused["error"].as_str().unwrap().contains("title"));
    let mut bad = input(json!({"title": "T", "summary": "S"}));
    bad["revision_id"] = json!("nope");
    assert!(run_json("specificationCreatePlan", &bad.to_string()).is_err());
}
