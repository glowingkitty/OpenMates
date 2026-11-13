//! `remote-access` shell preflight: explicit Rust-host gaps and npm flag contracts.
use super::{preflight, supported};
use crate::cli::{CliError, Invocation};
use serde_json::{Value, json};
use std::collections::BTreeMap;

fn invocation(flags: &[(&str, Value)], positionals: &[&str]) -> Invocation {
    Invocation {
        path: vec!["remote-access".into()],
        positionals: positionals.iter().map(|p| (*p).to_owned()).collect(),
        flags: flags.iter().map(|(k, v)| ((*k).to_owned(), v.clone())).collect::<BTreeMap<_, _>>(),
    }
}

fn code(result: Option<Result<crate::cli::CliOutput, CliError>>) -> String {
    match result {
        Some(Err(CliError::Contract { code, .. })) => code.to_owned(),
        Some(Err(CliError::Invalid(message))) => format!("invalid: {message}"),
        Some(Err(_)) => "other error".into(),
        Some(Ok(_)) => "ok".into(),
        None => "none".into(),
    }
}

#[test]
fn enable_commands_fails_explicitly_in_the_rust_host() {
    let result = preflight(&invocation(&[("enable-commands", json!(true))], &[]));
    assert_eq!(code(result), "remote_commands_unsupported");
    let valued = preflight(&invocation(&[("enable-commands", json!("yes"))], &[]));
    assert_eq!(code(valued), "invalid_enable_commands");
}

#[test]
fn task_cache_is_an_explicit_gap() {
    let result = preflight(&invocation(&[("task-cache", json!("/tmp/cache"))], &[]));
    assert_eq!(code(result), "task_cache_unsupported");
}

#[test]
fn positional_and_internal_options_are_refused() {
    assert!(code(preflight(&invocation(&[], &["folder"]))).contains("--path <folder>"));
    assert!(code(preflight(&invocation(&[("source-id", json!("x"))], &[]))).contains("--source-id"));
    assert_eq!(
        code(preflight(&invocation(&[("write-policy", json!("sometimes"))], &[]))),
        "invalid_write_policy"
    );
}

#[test]
fn valid_flags_pass_preflight_to_the_authenticated_run() {
    let ok = invocation(
        &[("path", json!(["/tmp"])), ("personal", json!(true)), ("write-policy", json!("always_ask")), ("project", json!("new"))],
        &[],
    );
    assert!(supported(&ok));
    assert!(preflight(&ok).is_none());
    assert!(crate::cli::requirements(&ok).authenticated);
}
