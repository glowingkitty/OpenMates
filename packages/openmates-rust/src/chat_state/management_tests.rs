use super::*;

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn title_and_summary_frames_encrypt_with_the_chat_key_and_bump_versions() {
    let key = crypto::random_key();
    let title = update_title("c", "Trip ✈", &key, Some("wrapped"), Some(3), 1_790_000_000).unwrap();
    assert_eq!(title.frame.frame_type, "update_title");
    assert_eq!(title.frame.payload["encrypted_chat_key"], "wrapped");
    assert_eq!(
        title.frame.payload["encrypted_title"],
        title.encrypted_title.as_str()
    );
    assert!(!title.frame.payload.to_string().contains("Trip"));
    assert_eq!(
        crypto::decrypt_combined(&title.encrypted_title, &key).unwrap(),
        "Trip ✈"
    );
    assert_eq!((title.title_v, title.updated_at), (4, 1_790_000_000));
    let bare = update_title("c", "t", &key, None, None, 1).unwrap();
    assert!(bare.frame.payload.get("encrypted_chat_key").is_none());
    assert_eq!(bare.title_v, 1);

    let versions = ComponentVersions {
        messages_v: Some(9),
        title_v: Some(5),
        metadata_v: Some(2),
        draft_v: None,
    };
    let summary =
        update_summary("c", "sum", &key, "wrapped", Some("enc-title"), versions, 7).unwrap();
    let p = &summary.frame.payload;
    assert_eq!(summary.frame.frame_type, "update_post_processing_metadata");
    assert_eq!(
        p["versions"],
        json!({"messages_v": 9, "title_v": 5, "metadata_v": 5, "draft_v": 0})
    );
    assert_eq!(
        (
            p["manual_update"].clone(),
            p["title_changed"].clone(),
            p["encrypted_title"].clone()
        ),
        (json!(true), json!(false), json!("enc-title"))
    );
    assert_eq!(
        crypto::decrypt_combined(p["encrypted_chat_summary"].as_str().unwrap(), &key).unwrap(),
        "sum"
    );
    assert_eq!(summary.metadata_v, 6);
    assert!(update_summary("c", "s", &key, "", None, versions, 7).is_err());
    let untitled =
        update_summary("c", "s", &key, "w", None, ComponentVersions::default(), 7).unwrap();
    assert!(untitled.frame.payload.get("encrypted_title").is_none());
    assert_eq!(untitled.metadata_v, 1);
}

#[test]
fn delete_pin_and_active_chat_frames_match_the_web_senders() {
    assert_eq!(
        pin_frame("c", true).payload,
        json!({"chat_id": "c", "pinned": true})
    );
    assert_eq!(
        delete_chat_frame("c", false, &[]).payload,
        json!({"chatId": "c", "removeProjectEmbeds": false})
    );
    assert_eq!(
        delete_chat_frame("c", true, &["e".into()]).payload,
        json!({"chatId": "c", "removeProjectEmbeds": true, "embed_ids_to_delete": ["e"]})
    );
    assert_eq!(
        delete_message_frame("c", "m", &[]).payload,
        json!({"chatId": "c", "messageId": "m"})
    );
    assert_eq!(
        delete_message_frame("c", "m", &["e".into()]).payload["embedIdsToDelete"],
        json!(["e"])
    );
    for (body, expected) in [
        (
            r#"{"requires_decision":true,"protected_embed_ids":["a","b"]}"#,
            Some(2),
        ),
        (
            r#"{"requires_decision":true,"protected_embed_ids":[]}"#,
            None,
        ),
        (
            r#"{"requires_decision":false,"protected_embed_ids":["a"]}"#,
            None,
        ),
        (
            r#"{"requires_decision":1,"protected_embed_ids":["a"]}"#,
            Some(1),
        ),
        (r#"{"protected_embed_ids":["a"]}"#, None),
        ("{}", None),
    ] {
        assert_eq!(deletion_decision(body).unwrap(), expected, "{body}");
    }
    assert_eq!(deletion_decision("nope").unwrap_err(), Error::Protocol);

    assert_eq!(
        active_chat_plan(Some("c"), false, false),
        ActiveChatPlan::Skip
    );
    assert_eq!(
        active_chat_plan(Some("demo"), true, true),
        ActiveChatPlan::Skip
    );
    let ActiveChatPlan::Send {
        persist_last_opened,
        frame,
    } = active_chat_plan(None, true, false)
    else {
        panic!("new chat sends")
    };
    assert_eq!(
        (persist_last_opened, frame.payload),
        (None, json!({"chat_id": null}))
    );
    let ActiveChatPlan::Send {
        persist_last_opened,
        ..
    } = active_chat_plan(Some("c"), true, false)
    else {
        panic!("sends")
    };
    assert_eq!(persist_last_opened.as_deref(), Some("c"));
    assert_eq!(
        hide_demo_chat(&["a".into()], "b"),
        Some(vec!["a".to_owned(), "b".to_owned()])
    );
    assert_eq!(hide_demo_chat(&["a".into()], "a"), None);
}

#[test]
fn pending_deletions_queue_matches_local_storage_semantics() {
    for raw in [None, Some(""), Some("{"), Some("{}"), Some("null")] {
        assert_eq!(PendingDeletions::decode(raw), PendingDeletions::default());
    }
    let mut queue = PendingDeletions::decode(Some(r#"["a",7,"b"]"#));
    assert!(queue.contains("a") && !queue.contains("7"));
    assert_eq!(queue.chat_ids(), vec!["a", "b"]);
    assert_eq!(queue.add("a"), None);
    assert_eq!(queue.add("c").as_deref(), Some(r#"["a",7,"b","c"]"#));
    assert_eq!(queue.remove("a").as_deref(), Some(r#"[7,"b","c"]"#));
    let mut single = PendingDeletions::default();
    assert_eq!(single.add("x").as_deref(), Some(r#"["x"]"#));
    assert_eq!(
        single.remove("x"),
        None,
        "an empty queue removes the storage key"
    );
    assert_eq!(PENDING_DELETIONS_KEY, "openmates_pending_chat_deletions");
}
