use super::*;
use crate::chat_state::js::utf16_len;

fn source(json: &str) -> ForkSourceMessage {
    serde_json::from_str(json).unwrap()
}

#[test]
fn fork_point_slices_a_stable_created_at_order() {
    let messages = vec![
        source(r#"{"message_id":"c","created_at":30}"#),
        source(r#"{"message_id":"a","created_at":10}"#),
        source(r#"{"message_id":"none"}"#),
        source(r#"{"message_id":"b1","created_at":20}"#),
        source(r#"{"message_id":"b2","created_at":20}"#),
    ];
    let ids = |m: Vec<ForkSourceMessage>| m.into_iter().map(|m| m.message_id).collect::<Vec<_>>();
    assert_eq!(
        ids(messages_to_copy(messages.clone(), "b1").unwrap()),
        vec!["none", "a", "b1"]
    );
    assert_eq!(
        ids(messages_to_copy(messages.clone(), "c").unwrap()).len(),
        5
    );
    assert_eq!(
        messages_to_copy(messages, "missing").unwrap_err(),
        Error::Invalid("Fork point message not found")
    );
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn copied_messages_are_reencrypted_and_drop_sensitive_fields() {
    let key = crypto::random_key();
    let chat_id = "0123456789-abcdefghij";
    let src = source(
        r#"{"message_id":"m","role":"assistant","created_at":5,"content":"hello","sender_name":"Mate","category":"code","model_name":"m1",
        "thinking_content":"secret thoughts","pii_mappings":[{"x":1}],"user_message_id":"u","encrypted_content":"ignored"}"#,
    );
    let copy = reencrypt_message(&src, chat_id, fork_message_id(chat_id), &key).unwrap();
    assert!(copy.message_id.starts_with("abcdefghij-") && copy.message_id.len() == 11 + 36);
    assert_eq!(
        (copy.chat_id.as_str(), copy.status, copy.role.clone()),
        (chat_id, "synced", json!("assistant"))
    );
    for (cipher, plain) in [
        (&copy.encrypted_content, "hello"),
        (&copy.encrypted_sender_name, "Mate"),
        (&copy.encrypted_category, "code"),
        (&copy.encrypted_model_name, "m1"),
    ] {
        assert_eq!(
            crypto::decrypt_combined(cipher.as_deref().unwrap(), &key).unwrap(),
            plain
        );
    }
    let row = serde_json::to_string(&copy).unwrap();
    for leaked in ["secret thoughts", "pii", "user_message_id", "hello", "Mate"] {
        assert!(!row.contains(leaked), "{leaked}");
    }
    let demo = reencrypt_message(
        &source(r#"{"message_id":"d","role":"user","content":"","encrypted_content":"blob"}"#),
        chat_id,
        "n".into(),
        &key,
    )
    .unwrap();
    assert_eq!(demo.encrypted_content.as_deref(), Some("blob"));
    assert!(demo.created_at.is_none() && demo.encrypted_sender_name.is_none());
    let batch = reencrypt_batch(&[src.clone(), src], chat_id, &key).unwrap();
    assert_ne!(batch[0].message_id, batch[1].message_id);
}

#[test]
fn category_icon_copy_and_metadata_frame_match_the_web_fork() {
    let (old, new) = (crypto::random_key(), crypto::random_key());
    let category = crypto::encrypt_combined("travel", &old).unwrap();
    let copied = copy_chat_field(Some(&category), &old, &new)
        .unwrap()
        .unwrap();
    assert_eq!(crypto::decrypt_combined(&copied, &new).unwrap(), "travel");
    assert_eq!(
        copy_chat_field(Some(&category), &new, &new).unwrap(),
        None,
        "undecryptable is skipped"
    );
    assert_eq!(
        copy_chat_field(
            Some(&crypto::encrypt_combined("", &old).unwrap()),
            &old,
            &new
        )
        .unwrap(),
        None
    );
    assert_eq!(copy_chat_field(None, &old, &new).unwrap(), None);

    let messages = vec![
        reencrypt_message(
            &source(r#"{"message_id":"a","role":"user","created_at":1,"content":"q"}"#),
            "chat",
            "n1".into(),
            &new,
        )
        .unwrap(),
        reencrypt_message(
            &source(r#"{"message_id":"b","role":"assistant"}"#),
            "chat",
            "n2".into(),
            &new,
        )
        .unwrap(),
    ];
    let chat = ForkChat {
        chat_id: "chat",
        encrypted_chat_key: "wrapped",
        encrypted_title: "title",
        encrypted_category: Some(&copied),
        encrypted_icon: None,
        user_id: Some("user"),
        message_count: 2,
        now_seconds: 99,
    };
    let payload = fork_metadata_payload(&chat, &messages);
    assert_eq!(
        payload["message_history"].as_array().unwrap().len(),
        1,
        "messages without content are not injected"
    );
    let entry = &payload["message_history"][0];
    assert_eq!(
        (
            entry["message_id"].clone(),
            entry["chat_id"].clone(),
            entry["created_at"].clone()
        ),
        (json!("n1"), json!("chat"), json!(1))
    );
    assert!(entry.get("encrypted_sender_name").is_none());
    assert_eq!(
        payload["versions"],
        json!({"messages_v": 2, "title_v": 1, "last_edited_overall_timestamp": 99})
    );
    assert_eq!(payload["encrypted_chat_category"], copied.as_str());
    assert!(payload.get("encrypted_icon").is_none());
    let record = fork_chat_record(&chat);
    assert_eq!(
        (
            record["user_id"].clone(),
            record["unread_count"].clone(),
            record["encrypted_category"].clone()
        ),
        (json!("user"), json!(0), json!(copied))
    );
    assert!(record.get("encrypted_icon").is_none());
    assert_eq!(
        crypto::decrypt_combined(&encrypt_fork_title("Fork", &new).unwrap(), &new).unwrap(),
        "Fork"
    );
}

#[test]
fn explain_selection_normalizes_like_the_web_client() {
    assert_eq!(
        normalize_explain_selection("  a\n\t b\u{00A0}\u{FEFF}c  "),
        "a b c"
    );
    assert_eq!(normalize_explain_selection(" \n "), "");
    assert_eq!(
        utf16_len(&normalize_explain_selection(&"x".repeat(600))),
        500
    );
    let astral = format!("{}{}", "x".repeat(499), "🔒🔒");
    assert_eq!(normalize_explain_selection(&astral), "x".repeat(499));
    assert_eq!(
        normalize_explain_selection(&format!("{}🔒", "x".repeat(498))),
        format!("{}🔒", "x".repeat(498))
    );
}
