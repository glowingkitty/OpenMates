use super::*;
use serde_json::json;

fn opened(revisions: Value, current: &str) -> Value {
    json!({
        "specification": {"specification_id": "s1", "current_revision_id": current,
            "title": "Billing", "current_revision_number": 3, "updated_at": 50},
        "revision": {"revision_id": current, "content_hash": "h3", "document": {
            "title": "Billing", "project": "P", "category": "feature", "summary": "S",
            "outcome": "O", "role": "product",
            "scope": {"included": ["a"], "excluded": ["b"]},
            "assumptions": ["x"], "designDecisions": ["d"],
            "chapters": [{"id": "c1", "title": "T", "introduction": "I",
                "requirementIds": ["r1"], "flowIds": ["f1"], "modelIds": ["m1"]}],
            "requirements": [{"id": "r1", "statement": "St", "appliesTo": ["web"],
                "example": "E", "proof": {"state": "passed", "title": "pt", "explanation": "pe"}}],
            "flows": [{"id": "f1", "title": "F", "kind": "edge", "steps": ["1"],
                "requiredCheckRefs": ["chk"]}],
            "models": [{"id": "m1", "description": "D",
                "fields": [{"name": "n", "type": "string", "description": "fd"}]}],
            "relatedSpecifications": [{"title": "Other", "role": "design", "relation": "refines"}],
        }},
        "revisions": revisions,
    })
}

fn rev(id: &str, number: u64, state: Value) -> Value {
    json!({"revision_id": id, "revision_number": number, "approval_state": state,
        "approved_at": 77, "created_at": 9, "summary": "s", "content_hash": format!("h{number}")})
}

#[test]
fn document_marshals_every_field() {
    let view = opened(json!([rev("r3", 3, Value::Null)]), "r3");
    let rec = opened_record(&view).expect("marshals");
    let doc = rec.document;
    assert_eq!(doc.role, "product");
    assert_eq!(doc.scope_included, vec!["a"]);
    assert_eq!(doc.design_decisions, vec!["d"]);
    assert_eq!(doc.chapters[0].requirement_ids, vec!["r1"]);
    assert_eq!(doc.requirements[0].proof_state.as_deref(), Some("passed"));
    assert_eq!(doc.requirements[0].applies_to, vec!["web"]);
    assert_eq!(doc.flows[0].required_check_refs, vec!["chk"]);
    assert_eq!(doc.models[0].fields[0].field_type, "string");
    assert_eq!(doc.related[0].relation, "refines");
    assert_eq!(rec.viewed_content_hash, "h3");
}

#[test]
fn missing_optional_fields_are_empty() {
    let view = json!({"specification": {"specification_id": "s1"},
        "revision": {"revision_id": "r1", "content_hash": "h", "document": {}},
        "revisions": []});
    let rec = opened_record(&view).expect("marshals");
    assert_eq!(rec.document.role, "");
    assert!(rec.document.requirements.is_empty());
    assert_eq!(rec.current_revision_id, "r1");
    assert_eq!(rec.approval_state, "draft");
}

#[test]
fn approval_state_draft_approved_and_stale() {
    let draft = opened(json!([rev("r3", 3, Value::Null)]), "r3");
    let rec = opened_record(&draft).unwrap();
    assert_eq!(rec.approval_state, "draft");
    assert_eq!(rec.approved_revision_id, None);

    let approved = opened(json!([rev("r3", 3, json!("approved")), rev("r2", 2, Value::Null)]), "r3");
    let rec = opened_record(&approved).unwrap();
    assert_eq!(rec.approval_state, "approved");
    assert_eq!(rec.approved_revision_id.as_deref(), Some("r3"));
    assert_eq!(rec.approved_at, Some(77));

    let stale = opened(json!([rev("r3", 3, Value::Null), rev("r2", 2, json!("approved"))]), "r3");
    let rec = opened_record(&stale).unwrap();
    assert_eq!(rec.approval_state, "stale");
    assert_eq!(rec.approved_revision_id.as_deref(), Some("r2"));
}

#[test]
fn revision_status_follows_the_web_rule() {
    let view = opened(
        json!([rev("r3", 3, Value::Null), rev("r2", 2, json!("approved")), rev("r1", 1, Value::Null)]),
        "r3",
    );
    let statuses: Vec<_> = opened_record(&view)
        .unwrap()
        .revisions
        .into_iter()
        .map(|r| r.status)
        .collect();
    assert_eq!(statuses, vec!["draft", "approved", "superseded"]);
}

#[test]
fn list_item_counts_requirements_and_proof() {
    let view = json!({
        "specification": {"specification_id": "s1", "title": "Billing",
            "current_revision_number": 4, "updated_at": 123},
        "revision": {"approval_state": "approved", "document": {"category": "feature",
            "requirements": [
                {"proof": {"state": "passed"}}, {"proof": {"state": "open"}},
                {"proof": {"state": "open"}}, {"proof": {"state": "stale"}}, {}]}},
    });
    let item = list_item_record(&view).unwrap();
    assert_eq!(item.status, "approved");
    assert_eq!(item.kind, "feature");
    assert_eq!(item.revision_number, 4);
    assert_eq!(item.updated_at, 123);
    assert_eq!(item.requirement_count, 5);
    assert_eq!((item.proof_passed, item.proof_open, item.proof_stale), (1, 2, 1));
    let draft = json!({"specification": {"specification_id": "s", "title": "t"},
        "revision": {"approval_state": null, "document": {}}});
    let item = list_item_record(&draft).unwrap();
    assert_eq!((item.status.as_str(), item.kind.as_str(), item.updated_at), ("draft", "", 0));
}
