// contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
use super::*;
use std::collections::BTreeMap;
fn invocation(path: &str, ids: &[&str]) -> Invocation {
    Invocation {
        path: path.split(' ').map(str::to_owned).collect(),
        positionals: ids.iter().map(|v| (*v).into()).collect(),
        flags: BTreeMap::new(),
    }
}
#[test]
fn default_help_and_unknown_subcommand_need_no_account() {
    let i = invocation("drafts", &[]);
    let output = super::super::execute_public(&i)
        .unwrap()
        .unwrap_or_else(|_| panic!("draft help"));
    assert_eq!(output.stdout, format!("{HELP}\n"));
    assert_eq!(output.exit_code, 0);
    assert!(output.stderr.is_empty());
    let error = public(&invocation("drafts", &["unknown"]))
        .unwrap()
        .err()
        .unwrap();
    assert!(
        matches!(error,CliError::Contract{code:"command_failed",message} if message=="Unknown drafts subcommand 'unknown'.")
    );
}
#[test]
fn output_keeps_legacy_camel_case_ciphertext_and_null_preview() {
    let d = DraftRecord {
        encrypted: openmates_sdk::sdk_drafts::EncryptedDraftRecord {
            chat_id: "chat-1".into(),
            encrypted_draft_md: "opaque".into(),
            encrypted_draft_preview: None,
            draft_v: 2,
        },
        markdown: "Synthetic draft".into(),
        preview: None,
    };
    let value = record(d);
    assert_eq!(
        value,
        json!({"chatId":"chat-1","encryptedDraftMd":"opaque","encryptedDraftPreview":null,"draftV":2,"markdown":"Synthetic draft","preview":null})
    );
    let output = CliOutput::json(&json!({"draft":value})).unwrap_or_else(|_| panic!("draft JSON"));
    assert_eq!(
        serde_json::from_str::<Value>(&output.stdout).unwrap()["draft"]["preview"],
        Value::Null
    );
}
#[tokio::test]
async fn api_key_sync_and_missing_get_never_use_cookie_fallback() {
    let mut sdk = OpenMates::new(openmates_sdk::SdkOptions {
        api_url: "http://127.0.0.1:9".into(),
        credentials: openmates_sdk::SdkCredentials::ApiKey(
            openmates_sdk::ApiKey::new("sk-api-synthetic.synthetic").unwrap(),
        ),
        device_id: "synthetic".into(),
        client_options: Default::default(),
    })
    .unwrap();
    assert!(matches!(
        execute_sdk_drafts(
            &invocation("drafts sync", &[]),
            &mut sdk,
            CancellationToken::new()
        )
        .await,
        Err(CliError::Client(Error::Unavailable {
            code: "api_key_draft_sync_unavailable",
            ..
        }))
    ));
    assert!(
        matches!(execute_sdk_drafts(&invocation("drafts get",&[]),&mut sdk,CancellationToken::new()).await,Err(CliError::Contract{code:"command_failed",message}) if message=="Missing chat ID for draft get.")
    );
}
#[test]
fn actual_parser_admits_flags_and_separates_read_from_existing_mutations() {
    for argv in [
        vec!["openmates", "drafts", "list", "--refresh", "--json"],
        vec![
            "openmates",
            "drafts",
            "get",
            "11111111-1111-4111-8111-111111111111",
            "--refresh",
        ],
        vec!["openmates", "drafts", "sync"],
    ] {
        let parsed = super::super::parse_from(argv).unwrap();
        let i = parsed.invocation.unwrap();
        assert!(supported(&i));
        assert!(super::super::requirements(&i).supported);
    }
    assert!(!supported(&invocation("drafts clear", &["id"])));
    assert!(!supported(&invocation("drafts create", &["text"])));
}

#[test]
fn actual_draft_refresh_parser_and_read_policy_match_maintained_scalar_oracle() {
    let oracle: Value = serde_json::from_str(include_str!("../../tests/fixtures/draft-refresh-oracle.json")).unwrap();
    assert_eq!(oracle["cases"].as_array().unwrap().len(), 42);
    for case in oracle["cases"].as_array().unwrap() {
        let argv=case["argv"].as_array().unwrap().iter().map(|value| value.as_str().unwrap());
        let parsed=super::super::parse_from(argv).unwrap();
        let i=parsed.invocation.as_ref().unwrap();
        let expected=case.get("refreshFlag").filter(|value| !value.is_null());
        assert_eq!(i.flags.get("refresh"),expected,"{:?}",case["argv"]);
        assert_eq!(force_refresh(i),case["forceRefresh"].as_bool().unwrap(),"{:?}",case["argv"]);
        assert!(supported(i));
        assert!(super::super::requirements(i).supported);
    }
}
#[test]
fn refresh_optional_presence_is_scoped_and_does_not_rewrite_other_families() {
    let registry=super::super::catalog().flags.iter().find(|flag| flag.long=="refresh").unwrap();
    assert_eq!(registry.arity,"value");
    assert_eq!(registry.arity_overrides.get("drafts").map(String::as_str),Some("optional_value_presence"));
    for argv in [vec!["openmates","chats","list","--refresh","true"],vec!["openmates","history","list","--refresh"],vec!["openmates","apps","search","--refresh=false"]] {
        let mut raw=argv.into_iter().map(std::ffi::OsString::from).collect::<Vec<_>>();
        let before=raw.clone();normalize_refresh_arguments(&mut raw);assert_eq!(raw,before);
    }
}

#[test]
fn public_parser_rejects_raw_nul_before_presence_capture_without_echoing_values() {
    for argv in [
        vec!["openmates", "drafts", "list", "--refresh=\0openmates_presence"],
        vec!["openmates", "drafts", "get", "synthetic-id", "--refresh", "\0openmates_presence"],
        vec!["openmates", "--api-key", "synthetic-secret\0private", "drafts", "list"],
    ] {
        let result=super::super::parse_from(argv);
        let Err(error)=result else { panic!("Raw NUL must not reach capture or Clap"); };
        assert_eq!(error.kind(),clap::error::ErrorKind::InvalidValue);
        let message=error.to_string();
        assert!(message.contains("must not contain NUL bytes"));
        for private in ["synthetic-secret", "openmates_presence", "private", "\0"] {
            assert!(!message.contains(private),"NUL refusal must not echo input");
        }
    }
}

#[test]
fn refresh_read_support_never_admits_clear_mutation_flags() {
    let id = "11111111-1111-4111-8111-111111111111";
    for refresh in [vec!["--refresh"], vec!["--refresh=true"], vec!["--refresh=false"],
        vec!["--refresh", "true"], vec!["--refresh", "false"], vec!["--refresh="]]
    {
        let mut argv = vec!["openmates", "drafts", "clear", id];
        argv.extend(refresh);
        let Err(error) = super::super::parse_from(argv) else {
            panic!("Draft clearing must reject every refresh form before execution");
        };
        assert_eq!(error.kind(), clap::error::ErrorKind::InvalidValue);
        assert!(error.to_string().contains("does not accept --refresh"));
    }
    assert!(super::super::parse_from(["openmates", "drafts", "clear", id]).is_ok());
}
