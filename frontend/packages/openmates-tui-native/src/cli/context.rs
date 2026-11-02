//! Personal context aliases use the caller's explicit SDK session and local
//! context transition. Like the legacy CLI, switching Personal needs no HTTP.
use super::{CliError, CliOutput, Invocation, handlers};
use crate::{client::Client, error::Error};
use serde_json::json;
use tokio_util::sync::CancellationToken;

pub(super) fn supported(invocation: &Invocation) -> bool {
    match invocation.command_path().as_str() {
        "switch-to personal" | "teams personal" => true,
        "switch-to" => invocation
            .positionals
            .first()
            .is_some_and(|target| target.eq_ignore_ascii_case("personal")),
        _ => false,
    }
}

pub(super) fn execute(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    handlers::flags(invocation, &[])?;
    if invocation.has("api-key") {
        return Err(CliError::Unsupported {
            command: invocation.command_path(),
            reason: "Personal context selection requires an explicit Cookie session; API-key credentials cannot select a stored session context.".into(),
        });
    }
    let count = usize::from(invocation.command_path() == "switch-to");
    if !supported(invocation) || invocation.positionals.len() != count {
        return Err(CliError::Invalid(
            "Use openmates switch-to personal or openmates teams personal.".into(),
        ));
    }
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    let session = client.session().ok_or(Error::Authentication)?;
    if session.is_expired() {
        return Err(Error::Expired.into());
    }
    client.set_team(None)?;
    // set_team invalidates work belonging to the former context. Keep this
    // invocation attached to its caller's cancellation after the transition.
    client.set_operation_cancel(cancel);
    handlers::output(
        invocation,
        json!({"active_team_id":null,"context":"personal","target":"personal"}),
        "Active context: personal".into(),
    )
}

#[cfg(test)]
mod tests {
    // contract-test: supporting surface=cli assertions=cli.migration.complete-compatible,cli.pairing.expiry-upgrade
    use super::*;
    use serde_json::Value;
    use std::collections::BTreeMap;

    const API: &str = "http://127.0.0.1:1";
    const TEAM: &str = "11111111-1111-4111-8111-111111111111";

    fn invocation(path: &str, target: &[&str], json: bool) -> Invocation {
        Invocation {
            path: path.split(' ').map(str::to_owned).collect(),
            positionals: target.iter().map(|value| (*value).into()).collect(),
            flags: if json {
                BTreeMap::from([("json".into(), json!(true))])
            } else {
                BTreeMap::new()
            },
        }
    }
    fn client() -> Client {
        client_with_expiry(None).unwrap()
    }
    fn client_with_expiry(expires: Option<u64>) -> Result<Client, Error> {
        Client::new(
            API,
            Some(openmates_sdk::Session {
                api_url: API.into(),
                session_id: "context-fixture".into(),
                cookies: BTreeMap::new(),
                ws_token: None,
                master_key: zeroize::Zeroizing::new([7; 32]),
                hashed_email: "synthetic-owner".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: expires,
                active_team_id: Some(TEAM.into()),
            }),
        )
    }

    #[test]
    fn personal_aliases_preserve_legacy_output_without_network() {
        for (path, targets) in [
            ("switch-to personal", vec![]),
            ("teams personal", vec![]),
            ("switch-to", vec!["PeRsOnAl"]),
        ] {
            for json in [false, true] {
                let mut client = client();
                let invocation = invocation(path, &targets, json);
                assert!(supported(&invocation));
                let output = execute(&invocation, &mut client, CancellationToken::new())
                    .unwrap_or_else(|error| panic!("{error}"));
                assert_eq!(output.exit_code, 0);
                assert!(output.stderr.is_empty());
                assert!(client.session().unwrap().active_team_id.is_none());
                if json {
                    assert_eq!(
                        serde_json::from_str::<Value>(&output.stdout).unwrap(),
                        json!({"active_team_id":null,"context":"personal","target":"personal"})
                    );
                } else {
                    assert_eq!(output.stdout, "Active context: personal\n");
                }
            }
        }
    }

    #[test]
    fn personal_aliases_require_explicit_session_and_preserve_cancelled_context() {
        let invocation = invocation("teams personal", &[], false);
        let mut anonymous = Client::new(API, None).unwrap();
        assert!(matches!(
            execute(&invocation, &mut anonymous, CancellationToken::new()),
            Err(CliError::Client(Error::Authentication))
        ));
        assert!(anonymous.session().is_none());

        let mut client = client();
        let cancel = CancellationToken::new();
        cancel.cancel();
        assert!(matches!(
            execute(&invocation, &mut client, cancel),
            Err(CliError::Client(Error::Cancelled))
        ));
        assert_eq!(
            client.session().unwrap().active_team_id.as_deref(),
            Some(TEAM)
        );
    }

    #[tokio::test]
    async fn actual_parser_and_dispatch_preserve_personal_alias_output_and_admission() {
        for command in [
            ["openmates", "switch-to", "personal"],
            ["openmates", "teams", "personal"],
            ["openmates", "switch-to", "PeRsOnAl"],
        ] {
            let parsed =
                super::super::parse_from(command).unwrap_or_else(|error| panic!("{error}"));
            let invocation = parsed.invocation.expect("Personal invocation");
            let requirements = super::super::requirements(&invocation);
            assert!(requirements.supported && requirements.authenticated);
            assert!(super::super::execute_public(&invocation).is_none());
            let mut selected = client();
            let output =
                super::super::execute(&invocation, &mut selected, CancellationToken::new())
                    .await
                    .unwrap_or_else(|error| panic!("{error}"));
            assert_eq!(output.stdout, "Active context: personal\n");
            assert!(selected.session().unwrap().active_team_id.is_none());

            // Shared SDK admission rejects an already expired session before
            // constructing a Client; do not fabricate an invalid client state.
            assert!(matches!(client_with_expiry(Some(1)), Err(Error::Expired)));
        }
        let parsed = super::super::parse_from([
            "openmates",
            "teams",
            "personal",
            "--api-key",
            "synthetic-key",
        ])
        .unwrap_or_else(|error| panic!("{error}"));
        let mut selected = client();
        assert!(matches!(
            super::super::execute(
                &parsed.invocation.unwrap(),
                &mut selected,
                CancellationToken::new()
            )
            .await,
            Err(CliError::Unsupported { .. })
        ));
        assert_eq!(
            selected.session().unwrap().active_team_id.as_deref(),
            Some(TEAM)
        );
        // This exercises the library parser/dispatcher, not the outer profile,
        // online admission, durable persistence or trusted-account runtime.
    }

    #[test]
    fn personal_aliases_reject_unported_flags_and_extra_arguments_before_mutation() {
        let mut client = client();
        let mut unsupported = invocation("teams personal", &[], true);
        unsupported.flags.insert("team".into(), json!(TEAM));
        assert!(execute(&unsupported, &mut client, CancellationToken::new()).is_err());
        let extra = invocation("teams personal", &["unexpected"], false);
        assert!(execute(&extra, &mut client, CancellationToken::new()).is_err());
        assert_eq!(
            client.session().unwrap().active_team_id.as_deref(),
            Some(TEAM)
        );
        assert!(!supported(&invocation("switch-to", &[TEAM], false)));
    }
}
