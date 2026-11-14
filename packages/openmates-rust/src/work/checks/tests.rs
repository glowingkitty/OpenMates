use super::logic::*;
use std::collections::BTreeMap;

fn source(id: &str, kind: SourceKind, role: SourceRole) -> SourceBinding {
    SourceBinding {
        source_binding_id: id.into(),
        source_kind: kind,
        role,
    }
}

fn statuses(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| ((*k).into(), (*v).into()))
        .collect()
}

#[test]
fn validation_mirrors_the_backend() {
    use SourceKind::*;
    use SourceRole::*;
    assert!(validate_sources(&[], false).is_err());
    assert!(validate_sources(&[source("a", Unit, Supporting)], false).is_err());
    assert!(
        validate_sources(
            &[source("a", Unit, Required), source("a", E2e, Required)],
            false
        )
        .is_err()
    );
    assert!(validate_sources(&[source("a", HumanConfirmation, Required)], true).is_err());
    assert!(
        validate_sources(
            &[
                source("a", HumanConfirmation, Required),
                source("b", Unit, Supporting)
            ],
            true
        )
        .is_err()
    );
    assert!(
        validate_sources(
            &[
                source("a", HumanConfirmation, Required),
                source("b", E2e, Required)
            ],
            true
        )
        .is_ok()
    );
    assert!(validate_sources(&[source("a", AiEvaluation, Required)], false).is_ok());
}

#[test]
fn aggregate_orders_failed_error_blocked_running_waiting_passed() {
    use SourceKind::*;
    use SourceRole::*;
    let sources = [
        source("t", Unit, Required),
        source("h", HumanConfirmation, Required),
        source("s", E2e, Supporting),
    ];
    assert_eq!(aggregate_status(&sources, &statuses(&[])), "running");
    assert_eq!(
        aggregate_status(&sources, &statuses(&[("t", "passed")])),
        "waiting_for_confirmation"
    );
    assert_eq!(
        aggregate_status(&sources, &statuses(&[("t", "passed"), ("h", "waived")])),
        "passed"
    );
    assert_eq!(
        aggregate_status(&sources, &statuses(&[("t", "passed"), ("s", "failed")])),
        "waiting_for_confirmation"
    );
    assert_eq!(
        aggregate_status(&sources, &statuses(&[("t", "cancelled"), ("h", "blocked")])),
        "error"
    );
    assert_eq!(
        aggregate_status(&sources, &statuses(&[("t", "skipped")])),
        "blocked"
    );
    assert_eq!(
        aggregate_status(&sources, &statuses(&[("t", "failed"), ("h", "blocked")])),
        "failed"
    );
}

#[test]
fn staleness_depends_on_revision_and_subject() {
    let run = |status: &str, rev: &str, subject: Option<&str>| Run {
        run_id: "r".into(),
        check_id: "c".into(),
        check_revision_id: rev.into(),
        subject_revision: subject.map(Into::into),
        status: status.into(),
        created_at: 1,
        finished_at: None,
    };
    assert!(!is_stale(None, "v1", None));
    assert!(!is_stale(
        Some(&run("passed", "v1", Some("abc"))),
        "v1",
        Some("abc")
    ));
    assert!(is_stale(
        Some(&run("passed", "v1", Some("abc"))),
        "v2",
        None
    ));
    assert!(is_stale(
        Some(&run("passed", "v1", Some("abc"))),
        "v1",
        Some("def")
    ));
    assert!(is_stale(
        Some(&run("passed", "v1", None)),
        "v1",
        Some("def")
    ));
    assert!(!is_stale(Some(&run("failed", "v1", None)), "v2", None));
}

#[test]
fn definition_hash_is_stable_and_ids_are_assigned() {
    let def = |spec: &str| {
        CheckDefinition {
            requires_deterministic: false,
            sources: vec![parse_source_spec(spec).unwrap()],
        }
        .normalized()
        .unwrap()
    };
    let a = def("unit:required:tests/a.rs::case");
    assert_eq!(a.sources[0].source_binding_id, "s1");
    assert_eq!(
        a.definition_hash().unwrap(),
        def("unit:required:tests/a.rs::case")
            .definition_hash()
            .unwrap()
    );
    assert_ne!(
        a.definition_hash().unwrap(),
        def("unit:required:tests/b.rs").definition_hash().unwrap()
    );
    assert_eq!(a.definition_hash().unwrap().len(), 64);
    assert_eq!(a.sources[0].reference, "tests/a.rs::case");
    assert!(
        a.canonical_text()
            .unwrap()
            .contains(r#""ref":"tests/a.rs::case""#)
    );
}

#[test]
fn source_specs_are_parsed_strictly() {
    assert!(parse_source_spec("unit").is_err());
    assert!(parse_source_spec("magic:required:x").is_err());
    assert!(parse_source_spec("unit:optional:x").is_err());
    assert!(parse_source_spec("unit:required: ").is_err());
    let ai = parse_source_spec("ai_evaluation:required:Is the tone calm?").unwrap();
    assert_eq!(ai.source_kind, SourceKind::AiEvaluation);
}
