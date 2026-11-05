//! Native adapter policy only; authenticated backend execution is owned by E2E.
use super::*;
use openmates_sdk::client::saved_chat_read::SavedChatRead;
fn command(args:&[&str])->Invocation {super::super::parse_from(args.iter().copied()).unwrap().invocation.unwrap()}
fn fixture(id:&str)->SavedChatRead {
    let suite:Value=serde_json::from_str(include_str!("../../tests/crypto_fixtures/session-saved-chat-read.json")).unwrap();
    let vector=suite["capabilities"]["session.saved-chat-read.v1"]["vectors"].as_array().unwrap().iter().find(|v|v["id"]==id).unwrap();
    serde_json::from_value(vector["expected_public_paging"].clone()).unwrap()
}
// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,cli.surface.semantic-parity
#[test]
fn only_default_human_show_is_bounded_and_all_is_an_explicit_strict_path() {
    let id="22222222-2222-4222-8222-222222222222";
    for (args,bounded) in [
        (vec!["openmates","chats","show",id],true),
        (vec!["openmates","chats","show",id,"--json=false"],true),
        (vec!["openmates","chats","show",id,"--all"],false),
        (vec!["openmates","chats","show",id,"--json"],false),
        (vec!["openmates","chats","show",id,"--json","--all"],false),
        (vec!["openmates","chats","show",id,"--json","--raw"],false),
        (vec!["openmates","chats","messages",id],false),
    ] {
        let invocation=command(&args);assert!(saved_show_flags(&invocation).is_ok());assert_eq!(bounded_human_show(&invocation),bounded);
        assert!(matches!(saved_read_recovery(&invocation),Ok(Some(SavedReadRecovery::Selected(value))) if value==id));
    }
    let invocation=command(&["openmates","chats","messages",id,"--all"]);
    assert!(saved_show_flags(&invocation).is_err());
    let invocation=command(&["openmates","chats","show",id,"--api-key","synthetic"]);
    assert!(matches!(saved_read_recovery(&invocation),Err(CliError::Unsupported{..})));
    let invocation=command(&["openmates","chats","show","prefix"]);
    assert!(matches!(saved_read_recovery(&invocation),Err(CliError::Invalid(_))));
    let invocation=command(&["openmates","chats","show",id,"--raw"]);
    assert!(matches!(saved_read_recovery(&invocation),Err(CliError::Unsupported{..})));
}
// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,cli.surface.semantic-parity
#[test]
fn truthful_bounded_footer_reports_actual_count_and_does_not_claim_completion() {
    let read=fixture("default-30-from-65");let text=bounded_show_text(&read);
    assert!(text.contains("Showing 30 messages from a bounded window. Use --all to request full history."));
    let short=fixture("browser-one-page-underfilled-budget");let text=bounded_show_text(&short);
    assert!(text.contains("Showing 8 messages from a bounded window."));assert!(!text.contains("Showing 30"));
    let empty=fixture("around-missing-target-stays-empty");let text=bounded_show_text(&empty);
    assert!(text.contains("Showing 0 messages from a bounded window."));assert!(!text.contains("Use --all"));
    assert!(!read.window.history_complete);
}
// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,cli.surface.semantic-parity
#[test]
fn oversized_human_view_reports_omission_without_implicit_exact_or_full_claim() {
    let read=fixture("around-oversized-no-implicit-exact");let text=bounded_show_text(&read);
    assert!(text.contains("exceeds the bounded window size and was omitted"));assert!(text.contains("Showing 0 messages"));
    assert!(read.window.oversized_message_cursor.is_some());assert!(!read.window.history_complete);
}
