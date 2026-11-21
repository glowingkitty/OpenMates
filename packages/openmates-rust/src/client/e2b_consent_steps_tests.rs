//! Socket-free E2B consent steps used by the web shell.
// contract-test: supporting surface=gui.web assertions=code-run.e2b.upload-consent
use super::*;
use crate::client::e2b_consent::E2bConsentChoice;

const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const KEY: [u8; 32] = [9; 32];

fn client() -> Client {
    let session = Session {
        api_url: "http://127.0.0.1:9".into(),
        session_id: "synthetic-e2b-steps".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    Client::new("http://127.0.0.1:9", Some(session)).unwrap()
}

#[test]
fn request_step_encrypts_the_contract_message_into_one_frame() {
    let step = client()
        .e2b_consent_request_step(
            &json!({"request_id":"req-1","chat_id":CHAT,"version":1}),
            &KEY,
        )
        .unwrap();
    assert_eq!(step.frames.len(), 1);
    assert_eq!(step.frames[0].name, "chat_system_message_added");
    let message = &step.frames[0].payload["message"];
    assert_eq!(message["message_id"], "req-1-e2b-request");
    assert_eq!(message["role"], "system");
    assert_eq!(message["encrypted_content"], step.message.encrypted_content);
    assert!(!step.message.encrypted_content.contains("req-1"));
    let plain: Value = serde_json::from_str(&step.message.content).unwrap();
    assert_eq!(plain["type"], "e2b_upload_consent_request");
    assert_eq!(plain["choices"], json!(["allow", "own_machine", "not_now"]));
}

#[test]
fn request_step_refuses_a_frame_without_version_or_identity() {
    assert!(
        client()
            .e2b_consent_request_step(&json!({"request_id":"r","chat_id":CHAT}), &KEY)
            .is_err()
    );
    assert!(
        client()
            .e2b_consent_request_step(&json!({"request_id":"","chat_id":CHAT,"version":1}), &KEY)
            .is_err()
    );
}

#[test]
fn answer_step_sends_the_answer_before_persisting_the_response() {
    let step = client()
        .e2b_consent_answer_step(CHAT, "req-1", E2bConsentChoice::OwnMachine, &KEY)
        .unwrap();
    let names: Vec<_> = step.frames.iter().map(|f| f.name.as_str()).collect();
    assert_eq!(
        names,
        ["e2b_upload_consent_answer", "chat_system_message_added"]
    );
    assert_eq!(
        step.frames[0].payload,
        json!({"request_id":"req-1","chat_id":CHAT,"choice":"own_machine"})
    );
    assert_eq!(step.message.message_id, "req-1-e2b-response");
    let list = serde_json::to_string(&vec![step.message.content.clone()]).unwrap();
    assert!(crate::client::e2b_consent::is_request_answered_json(&list, "req-1").unwrap());
}

#[test]
fn answer_step_refuses_empty_identities() {
    assert!(
        client()
            .e2b_consent_answer_step(CHAT, "", E2bConsentChoice::Allow, &KEY)
            .is_err()
    );
    assert!(
        client()
            .e2b_consent_answer_step("", "r", E2bConsentChoice::Allow, &KEY)
            .is_err()
    );
}
