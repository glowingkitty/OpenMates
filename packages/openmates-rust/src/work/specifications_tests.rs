use super::*;

fn document() -> SpecificationDocument {
    SpecificationDocument {
        title: "Recipe planning".into(),
        summary: "Save recipes and plan meals".into(),
        requirements: vec![SpecRequirement {
            id: "R1".into(),
            statement: "Save a recipe".into(),
            ..Default::default()
        }],
        flows: vec![SpecFlow {
            id: "F1".into(),
            title: "Save".into(),
            kind: "user_flow".into(),
            steps: vec!["Open".into()],
            ..Default::default()
        }],
        chapters: vec![SpecChapter {
            id: "C1".into(),
            title: "Basics".into(),
            requirement_ids: vec!["R1".into()],
            flow_ids: vec!["F1".into()],
            ..Default::default()
        }],
        ..Default::default()
    }
}

#[test]
fn validation_refuses_unresolved_references_and_bad_kinds() {
    assert!(document().validate().is_ok());
    let mut bad = document();
    bad.chapters[0].flow_ids.push("missing".into());
    assert!(bad.validate().is_err());
    let mut bad = document();
    bad.flows[0].kind = "story".into();
    assert!(bad.validate().is_err());
    let mut bad = document();
    bad.requirements.push(bad.requirements[0].clone());
    assert!(bad.validate().is_err());
    let mut bad = document();
    bad.summary = " ".into();
    assert!(bad.validate().is_err());
}

#[test]
fn guided_fields_round_trip_and_roles_are_checked() {
    let mut doc = document();
    doc.role = "product".into();
    doc.assumptions = vec!["Pickup only".into()];
    doc.design_decisions = vec!["One-page order form".into()];
    doc.related_specifications = vec![SpecRelated {
        title: "Ordering - technical".into(),
        role: "technical".into(),
        relation: "implements payments".into(),
    }];
    assert!(doc.validate().is_ok());
    let text = serde_json::to_value(&doc).unwrap();
    assert_eq!(text["designDecisions"][0], "One-page order form");
    assert_eq!(text["relatedSpecifications"][0]["role"], "technical");
    let back: SpecificationDocument = serde_json::from_value(text).unwrap();
    assert_eq!(back, doc);
    let plain = serde_json::to_value(document()).unwrap();
    assert!(plain.get("assumptions").is_none() && plain.get("role").is_none());
    let mut bad = doc.clone();
    bad.role = "marketing".into();
    assert!(bad.validate().is_err());
    let mut bad = doc;
    bad.related_specifications[0].title = " ".into();
    assert!(bad.validate().is_err());
}

#[test]
fn revision_body_round_trips_and_binds_the_plaintext_hash() {
    let key = crypto::random_key();
    let input = SpecificationInput {
        document: document(),
        ..Default::default()
    };
    let (body, revision) = Specifications::revision_body(&input, &key).unwrap();
    assert_eq!(body["revision_id"], revision);
    assert_eq!(
        body["project_surface_catalog_revision_id"],
        DEFAULT_CATALOG_REVISION
    );
    let raw = json!({
        "revision_id": revision, "revision_number": 1, "approval_state": "draft",
        "content_hash": body["content_hash"], "encrypted_title": body["encrypted_title"],
        "encrypted_summary": body["encrypted_summary"],
        "encrypted_specification_document": body["encrypted_specification_document"],
    });
    let view = Specifications::revision_view(&raw, &key, true).unwrap();
    assert_eq!(view["title"], "Recipe planning");
    let back: SpecificationDocument = serde_json::from_value(view["document"].clone()).unwrap();
    assert_eq!(back, document());
    let mut tampered = raw.clone();
    tampered["content_hash"] = json!(content_hash("other"));
    assert!(matches!(
        Specifications::revision_view(&tampered, &key, true),
        Err(Error::Conflict)
    ));
}

#[test]
fn only_the_exact_project_wrapper_unwraps_the_specification_key() {
    let key = crypto::random_key();
    let project_key = crypto::random_key();
    let project = "11111111-1111-4111-8111-111111111111";
    let wrapper = |id: &str| {
        json!({"key_type":"project","hashed_project_id":hash(id),
        "encrypted_specification_key": crypto::server_fields::encrypt_bytes(key.as_ref(), &project_key, &[]).unwrap()})
    };
    let head = json!({"key_wrappers":[wrapper(project)]});
    assert_eq!(
        Specifications::spec_key(&head, project, &project_key)
            .unwrap()
            .as_ref(),
        key.as_ref()
    );
    let other = json!({"key_wrappers":[wrapper("22222222-2222-4222-8222-222222222222")]});
    assert!(matches!(
        Specifications::spec_key(&other, project, &project_key),
        Err(Error::Forbidden)
    ));
    let wrong_key = crypto::random_key();
    assert!(Specifications::spec_key(&head, project, &wrong_key).is_err());
}
