// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::super::parity_test_support::{mock, parsed};
use super::*;
use serde_json::json;

/// Bare roots cannot go through the clap-backed `parsed` helper.
fn bare(args: &[&str]) -> Invocation {
    Invocation { path: args[1..].iter().map(|s| (*s).to_owned()).collect(), positionals: vec![], flags: Default::default() }
}

#[test]
fn group_help_and_help_command_are_public_and_supported() {
    for args in [
        vec!["openmates", "account"],
        vec!["openmates", "e2e"],
        vec!["openmates", "help"],
    ] {
        let invocation = bare(&args);
        let requirements = super::super::handlers::requirements(&invocation);
        assert!(requirements.supported && !requirements.authenticated, "{args:?}");
        let output = super::super::handlers::execute_public(&invocation).expect("public").ok().expect("help text");
        assert!(output.stdout.contains("Usage"), "{args:?}");
    }
    let with = |rest: &[&str]| Invocation {
        path: vec!["help".into()],
        positionals: rest.iter().map(|s| (*s).to_owned()).collect(),
        flags: Default::default(),
    };
    let topic = help(&with(&["ideabucket"])).unwrap().ok().unwrap();
    assert!(topic.stdout.contains("ideabucket"));
    assert!(help(&with(&["nope"])).unwrap().is_err());
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
#[test]
fn booking_link_rendering_keeps_the_npm_contract() {
    let ok = json!({"success": true, "booking_url": "https://x.test/b", "booking_provider": "Acme", "credits_charged": 3});
    let text = render_booking(&parsed(&["openmates", "apps", "travel", "booking-link"]), ok.clone()).ok().unwrap();
    assert!(text.stdout.contains("URL: https://x.test/b") && text.stdout.contains("(3 credits)"));
    let json_out = render_booking(&parsed(&["openmates", "apps", "travel", "booking-link", "--json"]), ok.clone()).ok().unwrap();
    assert_eq!(serde_json::from_str::<serde_json::Value>(&json_out.stdout).unwrap(), ok);
    let failure = json!({"success": false, "error": "expired"});
    assert!(matches!(render_booking(&parsed(&["openmates", "apps", "travel", "booking-link"]), failure.clone()), Err(CliError::Invalid(m)) if m.contains("expired")));
    assert!(render_booking(&parsed(&["openmates", "apps", "travel", "booking-link", "--json"]), failure).is_ok());
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
#[tokio::test]
async fn booking_link_validates_flags_and_posts_the_token() {
    let (mut client, server) = mock(vec![json!({"success": true, "booking_url": "https://x.test/b"})]).await;
    for (args, message) in [
        (vec!["openmates", "apps", "travel", "booking-link"], "Missing --token"),
        (vec!["openmates", "apps", "travel", "booking-link", "--token", "t", "--context", "{bad"], "Invalid --context JSON."),
    ] {
        match execute(&parsed(&args), &mut client).await {
            Err(CliError::Invalid(actual)) => assert!(actual.starts_with(message), "{args:?}: {actual}"),
            _ => panic!("expected invalid input for {args:?}"),
        }
    }
    let out = execute(&parsed(&["openmates", "apps", "travel", "booking-link", "--token", "tok", "--json"]), &mut client).await.ok().unwrap();
    assert!(out.stdout.contains("https://x.test/b"));
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/apps/travel/booking-link "));
    assert!(requests[0].contains(r#""booking_token":"tok""#));
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
#[tokio::test]
async fn inspirations_print_public_rows_after_empty_personal_rows() {
    let (mut client, server) = mock(vec![
        json!({"inspirations": []}),
        json!({"inspirations": [{"inspiration_id": "p1", "phrase": "Plan a trip", "title": "Trips", "category": "travel"}]}),
    ])
    .await;
    let out = execute(&parsed(&["openmates", "inspirations", "--lang", "de", "--json"]), &mut client).await.ok().unwrap();
    let rows: serde_json::Value = serde_json::from_str(&out.stdout).unwrap();
    assert_eq!(rows[0]["phrase"], "Plan a trip");
    assert!(server.await.unwrap()[1].contains("lang=de"));
    assert!(inspirations_text(&[], "en").contains("No inspirations"));
}
