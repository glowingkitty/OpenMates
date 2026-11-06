//! Argument parsing and dispatch of `teams member(s) message` before any request.
use super::*;
fn invocation(positionals: &[&str], flags: &[(&str, Value)]) -> Invocation {
    Invocation {
        path: vec!["teams".into(), "members".into(), "message".into()],
        positionals: positionals
            .iter()
            .map(|value| (*value).to_owned())
            .collect(),
        flags: flags
            .iter()
            .map(|(key, value)| ((*key).to_owned(), value.clone()))
            .collect(),
    }
}
const TEAM: &str = "88888888-8888-4888-8888-888888888888";
fn hash() -> String {
    "a".repeat(64)
}
#[test]
fn both_spellings_are_native_and_arguments_follow_npm() {
    let mut singular = invocation(&[], &[]);
    singular.path[1] = "member".into();
    assert!(supported(&singular) && supported(&invocation(&[], &[])));
    let hash = hash();
    let (team, member, text) = arguments(&invocation(&[TEAM, &hash, "hello", " there "], &[]))
        .ok()
        .unwrap();
    assert_eq!(
        (team.as_str(), member.as_str(), text.as_str()),
        (TEAM, hash.as_str(), "hello  there")
    );
    let (_, _, empty) = arguments(&invocation(&[TEAM, &hash], &[])).ok().unwrap();
    assert!(empty.is_empty());
}
#[test]
fn malformed_scope_hash_and_unported_flags_fail_before_any_request() {
    let upper = "A".repeat(64);
    for positionals in [
        vec![],
        vec![TEAM],
        vec!["not-a-team", "x"],
        vec![TEAM, "short"],
        vec![TEAM, upper.as_str()],
    ] {
        assert!(matches!(
            arguments(&invocation(&positionals, &[])),
            Err(CliError::Invalid(_))
        ));
    }
    let hash = hash();
    assert!(arguments(&invocation(&[TEAM, &hash], &[("json", Value::Bool(true))])).is_ok());
    assert!(matches!(
        arguments(&invocation(
            &[TEAM, &hash],
            &[("model", Value::String("x".into()))]
        )),
        Err(CliError::Unsupported { .. })
    ));
}
