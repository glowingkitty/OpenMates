//! Caller-reserved turn ids: accepted when canonical and fresh, refused when
//! malformed, misplaced or already present (`Client::turn_identity`).
use super::*;
use serde_json::json;

const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const NEW_CHAT: &str = "55555555-5555-4555-8555-555555555555";
const MESSAGE: &str = "44444444-4444-4444-8444-444444444444";

fn client() -> Client {
    let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
    client.chats.insert(CHAT.into(), json!({"id": CHAT}));
    client
        .history
        .insert(CHAT.into(), vec![json!({"client_message_id": MESSAGE})]);
    client
}

fn reserved(chat: Option<&str>, message: Option<&str>) -> ReservedTurnIds {
    ReservedTurnIds {
        chat_id: chat.map(str::to_owned),
        message_id: message.map(str::to_owned),
    }
}

#[test]
fn reserved_ids_name_a_new_chat_and_its_first_message() {
    let ids = reserved(Some(NEW_CHAT), Some(MESSAGE));
    let (chat, message) = client().turn_identity(None, Some(&ids)).unwrap();
    assert_eq!((chat.as_str(), message.as_str()), (NEW_CHAT, MESSAGE));
}

#[test]
fn missing_reserved_ids_are_minted() {
    let (chat, message) = client().turn_identity(None, None).unwrap();
    assert!(uuid::Uuid::parse_str(&chat).is_ok() && uuid::Uuid::parse_str(&message).is_ok());
    assert_ne!(chat, message);
    let (chat, _) = client().turn_identity(Some(CHAT), None).unwrap();
    assert_eq!(chat, CHAT);
}

#[test]
fn refuses_malformed_or_misplaced_reserved_ids() {
    let client = client();
    for (chat_id, ids) in [
        (None, reserved(Some("not-a-uuid"), None)),
        (
            None,
            reserved(Some("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"), None),
        ),
        (None, reserved(None, Some("not-a-uuid"))),
        (None, reserved(Some(NEW_CHAT), Some(NEW_CHAT))),
        (Some(CHAT), reserved(Some(NEW_CHAT), None)),
    ] {
        assert!(matches!(
            client.turn_identity(chat_id, Some(&ids)),
            Err(Error::Invalid(_))
        ));
    }
}

#[test]
fn refuses_reserved_ids_that_already_exist() {
    let client = client();
    assert!(matches!(
        client.turn_identity(None, Some(&reserved(Some(CHAT), None))),
        Err(Error::Conflict)
    ));
    assert!(matches!(
        client.turn_identity(Some(CHAT), Some(&reserved(None, Some(MESSAGE)))),
        Err(Error::Conflict)
    ));
    // The same message id is fresh in another (new) chat.
    assert!(
        client
            .turn_identity(None, Some(&reserved(Some(NEW_CHAT), Some(MESSAGE))))
            .is_ok()
    );
}
