//! Card rendering and flag validation of the assistant-created Project commands.
// contract-test: supporting surface=cli assertions=projects.creation.assistant-inferred
use super::*;

fn invocation(args: &[&str]) -> Invocation {
    super::super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|error| panic!("{error}"))
        .invocation
        .unwrap()
}

#[test]
fn card_names_the_subfolder_and_how_to_undo() {
    let card = json!({"status":"created","name":"Recipe Manager","subfolder":"web-app",
        "chatId":"aaaaaaaa-1111-4111-8111-aabbccddeeff"});
    let text = card_text(&card);
    assert!(text.starts_with("Created project Recipe Manager (files go to web-app/)."));
    assert!(
        text.contains("openmates projects undo-create --chat aaaaaaaa-1111-4111-8111-aabbccddeeff")
    );
}

#[test]
fn card_for_a_failed_request_says_nothing_was_created() {
    let text = card_text(&json!({"status":"failed","errorCode":"PROJECT_CREATE_FAILED"}));
    assert!(text.contains("No project was created (PROJECT_CREATE_FAILED)"));
}

#[test]
fn chat_must_be_a_full_uuid() {
    let ok = invocation(&[
        "openmates",
        "projects",
        "undo-create",
        "--chat",
        "aaaaaaaa-1111-4111-8111-aabbccddeeff",
    ]);
    assert!(chat_id(&ok).is_ok());
    let short = invocation(&["openmates", "projects", "created", "--chat", "abc"]);
    assert!(chat_id(&short).is_err());
}
