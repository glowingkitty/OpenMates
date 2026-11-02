// contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
use super::*;
fn invocation() -> Invocation {
    Invocation {
        path: vec!["apps".into(), "code".into(), "get_docs".into()],
        positionals: vec![],
        flags: Default::default(),
    }
}
#[test]
fn generic_run_refusal_preserves_stderr_and_exit_one_even_under_json() {
    let mut i = invocation();
    i.path = vec!["apps".into(), "run".into()];
    i.flags.insert("json".into(), json!(true));
    let output = super::super::execute_public(&i)
        .unwrap_or_else(|| panic!("local refusal"))
        .unwrap_or_else(|_| panic!("local refusal"));
    assert_eq!(output.exit_code, 1);
    assert!(output.stdout.is_empty());
    assert_eq!(output.stderr, REFUSAL);
}
#[test]
fn flat_typed_input_preserves_positional_precedence_and_joined_question() {
    let mut i = invocation();
    i.positionals = vec!["Svelte 5".into(), "How".into(), "routing?".into()];
    i.flags.insert("library".into(), json!("ignored"));
    assert_eq!(
        input(&i).unwrap_or_else(|_| panic!("synthetic input")),
        json!({"library":"Svelte 5","question":"How routing?"})
    );
    i.positionals.clear();
    i.flags.insert("question".into(), json!("How?"));
    assert_eq!(
        input(&i).unwrap_or_else(|_| panic!("synthetic input")),
        json!({"library":"ignored","question":"How?"})
    );
}
#[test]
fn explicit_json_object_bypasses_shape_flags_and_positionals() {
    let mut i = invocation();
    i.positionals = vec!["ignored".into()];
    i.flags.insert(
        "input".into(),
        json!("{\"library\":\"Rust\",\"question\":\"ownership?\",\"extra\":true}"),
    );
    assert_eq!(
        input(&i).unwrap_or_else(|_| panic!("synthetic input"))["extra"],
        true
    );
    for raw in ["[]", "null", "invalid"] {
        i.flags.insert("input".into(), json!(raw));
        assert!(input(&i).is_err());
    }
}
#[test]
fn missing_fields_and_unported_artifact_or_routing_flags_fail_before_sdk() {
    let mut i = invocation();
    assert!(matches!(
        input(&i),
        Err(CliError::Contract {
            code: "command_failed",
            ..
        })
    ));
    for flag in [
        "output",
        "output-dir",
        "overwrite",
        "disable-prompt-injection-protection",
        "model",
        "provider",
    ] {
        i.flags.insert(flag.into(), json!("synthetic"));
        assert!(input(&i).is_err());
        i.flags.clear();
    }
}
#[test]
fn actual_parser_preserves_multiple_docs_positionals_and_refusal_route() {
    let parsed = super::super::parse_from([
        "openmates",
        "apps",
        "code",
        "get_docs",
        "Svelte",
        "How",
        "routing?",
        "--json",
    ])
    .unwrap_or_else(|_| panic!("synthetic parser"));
    assert_eq!(
        parsed
            .invocation
            .unwrap_or_else(|| panic!("synthetic invocation"))
            .positionals,
        vec!["Svelte", "How", "routing?"]
    );
    let parsed = super::super::parse_from(["openmates", "apps", "run", "arbitrary", "--json"])
        .unwrap_or_else(|_| panic!("refusal parser"));
    assert_eq!(
        public(&parsed.invocation.unwrap())
            .unwrap()
            .unwrap_or_else(|_| panic!("refusal"))
            .exit_code,
        1
    );
}
#[tokio::test]
async fn pre_cancelled_typed_execution_never_dispatches() {
    let mut i = invocation();
    i.flags.insert("json".into(), json!(true));
    i.flags.insert(
        "input".into(),
        json!("{\"library\":\"Rust\",\"question\":\"ownership?\"}"),
    );
    let mut sdk = OpenMates::new(openmates_sdk::SdkOptions {
        api_url: "http://127.0.0.1:9".into(),
        credentials: openmates_sdk::SdkCredentials::ApiKey(
            openmates_sdk::ApiKey::new("sk-api-synthetic.synthetic")
                .unwrap_or_else(|_| panic!("synthetic key")),
        ),
        device_id: "synthetic".into(),
        client_options: Default::default(),
    })
    .unwrap_or_else(|_| panic!("synthetic SDK"));
    let cancel = CancellationToken::new();
    cancel.cancel();
    assert!(matches!(
        execute_sdk_apps(&i, &mut sdk, cancel).await,
        Err(CliError::Client(Error::Cancelled))
    ));
}
