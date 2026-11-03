use super::*;

fn text_record() -> HighlightRecord {
    HighlightRecord::parse(
        r#"{"id":"h1","kind":"text","chat_id":"c","message_id":"m","anchor":{"exact":"quote","prefix":"pre ","suffix":" post"},
        "start":3,"end":8,"author_user_id":"u","author_display_name":"Ada","comment":"note","created_at":1790000000,"key_version":2}"#,
    )
    .unwrap()
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn add_encrypts_only_semantic_fields_in_web_payload_order() {
    let key = crypto::random_key();
    let record = text_record();
    assert_eq!(
        record.payload_plaintext(None),
        r#"{"kind":"text","anchor":{"exact":"quote","prefix":"pre ","suffix":" post"},"comment":"note","author_display_name":"Ada","created_at":1790000000}"#
    );
    let write = add_highlight(&record, &key).unwrap();
    assert_eq!(write.frame_type, "add_message_highlight");
    let payload = &write.payload;
    assert_eq!(payload["key_version"], 2);
    assert_eq!(payload["created_at"], 1790000000);
    let encrypted = payload["encrypted_payload"].as_str().unwrap();
    // The server-visible frame never contains the quote, comment or author name.
    let visible = payload.to_string();
    for secret in ["quote", "note", "Ada"] {
        assert!(!visible.contains(secret));
    }
    assert_eq!(
        crypto::decrypt_combined(encrypted, &key).unwrap(),
        record.payload_plaintext(None)
    );
    let embed = HighlightRecord::parse(r#"{"id":"h2","kind":"embed","chat_id":"c","message_id":"m","embed_id":"e","author_user_id":"u","created_at":5}"#).unwrap();
    assert_eq!(
        embed.payload_plaintext(None),
        r#"{"kind":"embed","embed_id":"e","created_at":5}"#
    );
    assert_eq!(
        add_highlight(&embed, &key).unwrap().payload["key_version"],
        Value::Null
    );
}

#[test]
fn update_stamps_seconds_and_remove_carries_no_ciphertext() {
    let key = crypto::random_key();
    let write = update_highlight(&text_record(), &key, 1790000123).unwrap();
    assert_eq!(write.payload["updated_at"], 1790000123);
    assert_eq!(
        write.record.as_ref().unwrap().updated_at,
        Some(Number::from(1790000123u64))
    );
    let plain: Value = serde_json::from_str(
        &crypto::decrypt_combined(write.payload["encrypted_payload"].as_str().unwrap(), &key)
            .unwrap(),
    )
    .unwrap();
    assert_eq!(plain["updated_at"], 1790000123);
    let remove = remove_highlight("c", "m", "h1");
    assert_eq!(remove.frame_type, "remove_message_highlight");
    assert_eq!(
        remove.payload,
        json!({"chat_id":"c","message_id":"m","id":"h1"})
    );
    for bad in [
        r#"{"id":"h","kind":"text","chat_id":"c","message_id":"m","author_user_id":"u","created_at":1}"#,
        r#"{"id":"h","kind":"embed","chat_id":"c","message_id":"m","embed_id":"","author_user_id":"u","created_at":1}"#,
        r#"{"id":"h","kind":"note","chat_id":"c","message_id":"m","author_user_id":"u","created_at":1}"#,
    ] {
        assert!(HighlightRecord::parse(bad).is_err());
    }
}

fn inbound(key: &[u8; 32], plaintext: &str) -> String {
    json!({"chat_id":"c","message_id":"m","id":"h","author_user_id":"u","created_at":10,"key_version":3,
        "encrypted_payload": crypto::encrypt_combined(plaintext, key).unwrap()})
    .to_string()
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn inbound_rows_decode_exactly_like_the_web_handler() {
    let key = crypto::random_key();
    let HighlightInbound::Store(row) = decode_added(&inbound(&key, r#"{"kind":"text","anchor":{"exact":"q","prefix":7},"comment":"  \n","author_display_name":3}"#), &key).unwrap() else {
        panic!("text row is stored");
    };
    assert_eq!(
        row.anchor,
        Some(HighlightAnchor {
            exact: "q".into(),
            prefix: String::new(),
            suffix: String::new()
        })
    );
    assert_eq!(
        (row.comment.as_deref(), row.author_display_name.as_deref()),
        (None, None)
    );
    assert_eq!(
        (
            row.created_at.as_u64(),
            row.updated_at.as_ref().and_then(Number::as_u64)
        ),
        (Some(10), Some(10))
    );
    assert_eq!(row.key_version, Some(json!(3)));
    let HighlightInbound::Store(embed) = decode_added(
        &inbound(
            &key,
            r#"{"kind":"embed","embed_id":"e","comment":" keep "}"#,
        ),
        &key,
    )
    .unwrap() else {
        panic!("embed row is stored");
    };
    assert_eq!(
        (
            embed.kind,
            embed.embed_id.as_deref(),
            embed.comment.as_deref()
        ),
        (HighlightKind::Embed, Some("e"), Some(" keep "))
    );
    for (plaintext, reason) in [
        (
            r#"{"kind":"text","comment":"legacy offsets only"}"#,
            HighlightDrop::MissingAnchor,
        ),
        (
            r#"{"kind":"text","anchor":"q"}"#,
            HighlightDrop::MissingAnchor,
        ),
        (
            r#"{"kind":"embed","embed_id":""}"#,
            HighlightDrop::MissingEmbed,
        ),
        (r#"{"kind":"other"}"#, HighlightDrop::UnknownKind),
        ("null", HighlightDrop::UnknownKind),
        ("not json", HighlightDrop::Undecryptable),
    ] {
        assert_eq!(
            decode_added(&inbound(&key, plaintext), &key).unwrap(),
            HighlightInbound::Drop(reason),
            "{plaintext}"
        );
    }
    let wrong = crypto::random_key();
    assert_eq!(
        decode_added(&inbound(&wrong, r#"{"kind":"embed","embed_id":"e"}"#), &key).unwrap(),
        HighlightInbound::Drop(HighlightDrop::Undecryptable)
    );
}

#[test]
fn updates_merge_author_creation_and_key_version_from_the_cached_row() {
    let key = crypto::random_key();
    let frame = json!({"chat_id":"c","message_id":"m","id":"h","updated_at":20,
        "encrypted_payload": crypto::encrypt_combined(r#"{"kind":"embed","embed_id":"e"}"#, &key).unwrap()})
    .to_string();
    let cached = text_record();
    let HighlightInbound::Store(row) = decode_updated(&frame, &key, Some(&cached)).unwrap() else {
        panic!("stored")
    };
    assert_eq!(
        (
            row.author_user_id.as_str(),
            row.created_at.as_u64(),
            row.key_version.clone()
        ),
        ("u", Some(1790000000), Some(json!(2)))
    );
    let HighlightInbound::Store(row) = decode_updated(&frame, &key, None).unwrap() else {
        panic!("stored")
    };
    assert_eq!(
        (
            row.author_user_id.as_str(),
            row.created_at.as_u64(),
            row.key_version
        ),
        ("", Some(20), Some(Value::Null))
    );
    assert_eq!(
        decode_updated("{}", &key, None).unwrap_err(),
        Error::Protocol
    );
}
