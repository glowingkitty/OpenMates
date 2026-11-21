use super::*;
use openmates_sdk::client::{E2bConsentPolicy, SendOptions};

fn parse(args: &[&str]) -> Invocation {
    let mut values = vec!["openmates".to_owned()];
    values.extend(args.iter().map(|v| (*v).to_owned()));
    super::super::parse_from(values)
        .unwrap_or_else(|e| panic!("{e}"))
        .invocation
        .expect("invocation")
}

// contract-test: supporting surface=cli assertions=code-run.e2b.upload-consent
#[test]
fn allow_flag_parses_and_selects_the_approve_policy() {
    let with = parse(&["chats", "send", "hi", "--allow-e2b-upload"]);
    assert!(with.boolean("allow-e2b-upload"));
    assert_eq!(
        super::super::send::saved_options_for_test(&with)
            .ok()
            .expect("saved options")
            .e2b_consent,
        E2bConsentPolicy::Approve
    );
    let without = parse(&["chats", "send", "hi"]);
    assert_eq!(
        super::super::send::saved_options_for_test(&without)
            .ok()
            .expect("saved options")
            .e2b_consent,
        SendOptions::default().e2b_consent
    );
}
// contract-test: supporting surface=cli assertions=code-run.e2b.upload-consent
#[test]
fn non_interactive_request_exits_2_with_the_plain_text_and_uploads_nothing() {
    let output = refusal(REQUIRED);
    assert_eq!(output.exit_code, 2);
    assert!(output.stdout.is_empty());
    for part in [
        "E2B, a cloud sandbox provider",
        "https://openmates.org/privacy",
        "openmates remote-access",
        "--allow-e2b-upload",
        "Nothing was uploaded",
    ] {
        assert!(output.stderr.contains(part), "{part}");
    }
}
// contract-test: supporting surface=cli assertions=code-run.e2b.upload-consent
#[test]
fn declined_account_message_explains_how_to_change_it_and_exits_2() {
    let error = CliError::Client(Error::Unavailable {
        code: DECLINED,
        reason: "declined",
    });
    let output = refusal_output(&error).expect("typed refusal");
    assert_eq!(output.exit_code, 2);
    assert!(
        output.stderr.contains("declined")
            && output
                .stderr
                .contains("openmates settings e2b-upload allow")
    );
    assert!(refusal_output(&CliError::Client(Error::Io)).is_none());
}
#[test]
fn prompt_answers_map_to_three_choices_and_reject_garbage() {
    assert_eq!(parse_choice("1"), Some(E2bConsentChoice::Allow));
    assert_eq!(
        parse_choice("own machine"),
        Some(E2bConsentChoice::OwnMachine)
    );
    assert_eq!(parse_choice(""), Some(E2bConsentChoice::NotNow));
    assert_eq!(parse_choice("maybe"), None);
    let mut out = Vec::new();
    assert_eq!(
        ask(&mut "2\n".as_bytes(), &mut out),
        Some(E2bConsentChoice::OwnMachine)
    );
    assert!(
        String::from_utf8(out)
            .ok()
            .expect("saved options")
            .contains("Use my own machine")
    );
}
#[test]
fn settings_command_parses_with_optional_decision() {
    assert!(supported(&parse(&["settings", "e2b-upload"])));
    assert_eq!(
        parse(&["settings", "e2b-upload", "decline"]).positionals,
        ["decline"]
    );
}
// contract-test: supporting surface=cli assertions=code-run.e2b.upload-consent
#[test]
fn refusal_text_does_not_ask_to_send_again() {
    assert!(!refusal(REQUIRED).stderr.contains("again"));
}
// contract-test: supporting surface=cli assertions=code-run.e2b.upload-consent
#[test]
fn prompt_ignores_status_text_that_is_not_a_consent_request() {
    let (sender, mut receiver) = mpsc::unbounded_channel();
    prompt("thinking", &sender);
    prompt("e2b_upload_consent_request not-json", &sender);
    drop(sender);
    assert!(receiver.try_recv().is_err());
}
