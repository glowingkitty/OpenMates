//! Focused regressions for single-page bounds, context and cache completeness.
//! Synthetic ciphertext only; network fixtures run only under managed Rust CI.
//! No real profiles, account services, inference or child application processes.
//! Pure validation tests reject malformed/cross-context paging selectors.
//! Full-open and strict privacy behavior remain separate contracts.
use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
const ID: &str = "22222222-2222-4222-8222-222222222222";
fn valid_cursor() -> MessageWindowCursor {
    MessageWindowCursor {
        chat_id: ID.into(),
        scope: "a".repeat(64),
        created_at: 1,
        message_id: "10000000-0000-4000-8000-000000000001".into(),
    }
}
// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn direction_cursor_shape_and_scope_are_checked_before_transport() {
    let cursor = valid_cursor();
    let options = MessageWindowOptions {
        direction: MessageWindowDirection::Before,
        cursor: Some(cursor.clone()),
        ..Default::default()
    };
    assert!(options.validate(ID, &cursor.scope).is_ok());
    for bad in [
        MessageWindowOptions {
            limit: 0,
            ..Default::default()
        },
        MessageWindowOptions {
            limit: 21,
            ..Default::default()
        },
        MessageWindowOptions {
            direction: MessageWindowDirection::Before,
            ..Default::default()
        },
        MessageWindowOptions {
            cursor: Some(cursor.clone()),
            ..Default::default()
        },
    ] {
        assert!(bad.validate(ID, &cursor.scope).is_err());
    }
    assert!(matches!(
        options.validate(ID, &"b".repeat(64)),
        Err(Error::Conflict)
    ));
    assert!(matches!(
        options.validate("11111111-1111-4111-8111-111111111111", &cursor.scope),
        Err(Error::Conflict)
    ));
    for encoded in [
        r#"{"limit":true}"#,
        r#"{"limit":2,"arbitrary":"private"}"#,
        r#"{"cursor":{"createdAt":1,"messageId":"bad","extra":true}}"#,
    ] {
        assert!(serde_json::from_str::<MessageWindowOptions>(encoded).is_err());
    }
}
// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn cursor_context_is_replaced_by_client_reset_and_team_switch() {
    let endpoint = "http://127.0.0.1:12345";
    let session: Session = serde_json::from_value(json!({"api_url":endpoint,"session_id":"synthetic","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})).unwrap();
    let mut client = Client::new(endpoint, Some(session.clone())).unwrap();
    let first = client.message_window_scope().unwrap();
    client.reset(endpoint, Some(session)).unwrap();
    let reset = client.message_window_scope().unwrap();
    assert_ne!(first, reset);
    client
        .set_team(Some("33333333-3333-4333-8333-333333333333"))
        .unwrap();
    assert_ne!(reset, client.message_window_scope().unwrap());
}
// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn page_local_restoration_retains_unknown_tokens_without_changing_strict_restore() {
    let known = "[OM_PII_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]";
    let unknown = "[OM_PII_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB]";
    let maps = [json!({"placeholder":known,"original":"Synthetic Alice"})];
    let input = format!("{known} and {unknown}");
    assert_eq!(
        crate::privacy::restore_page(&input, &maps).unwrap(),
        format!("Synthetic Alice and {unknown}")
    );
    assert!(crate::privacy::restore(&input, &maps).is_err());
    assert!(crate::privacy::restore_local(&input, &maps).is_err());
    let ambiguous = [
        maps[0].clone(),
        json!({"placeholder":known,"original":"Synthetic Bob"}),
    ];
    assert!(crate::privacy::restore_page(known, &ambiguous).is_err());
}
async fn serve(responses: Vec<Value>) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let endpoint = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        for (index, response) in responses.into_iter().enumerate() {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut raw = Vec::new();
            let header_end = loop {
                let mut byte = [0u8; 1];
                socket.read_exact(&mut byte).await.unwrap();
                raw.push(byte[0]);
                assert!(raw.len() < 16384);
                if raw.ends_with(b"\r\n\r\n") {
                    break raw.len();
                }
            };
            let head = String::from_utf8(raw[..header_end].to_vec()).unwrap();
            let content_length = head
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|n| n.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            let mut body = vec![0; content_length];
            socket.read_exact(&mut body).await.unwrap();
            if index == 0 {
                assert!(head.starts_with("POST /v1/chats/metadata/batch "));
            } else {
                assert!(head.starts_with(&format!("GET /v1/chats/{ID}/messages/window?direction=latest&limit=2&respect_compression_boundary=true ")));
            }
            let body = response.to_string();
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).as_bytes()).await.unwrap();
        }
    });
    (endpoint, task)
}
async fn exercise_page_finalization(expire_at_publication: bool) {
    let key = [9; 32];
    let master = [7; 32];
    let row = json!({"id":ID,"messages_v":99,"encrypted_chat_key":crypto::encrypt_bytes(&key,&master).unwrap(),"encrypted_title":crypto::encrypt_combined("Synthetic title",&key).unwrap()});
    let mut rows: Vec<Value> = (1..=2).map(|i| json!({"id":format!("10000000-0000-4000-8000-{i:012}"),"chat_id":ID,"created_at":i,"role":"user","encrypted_content":crypto::encrypt_combined("Synthetic bounded content",&key).unwrap()})).collect();
    let token = "[OM_PII_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]";
    rows[0]["encrypted_content"] = json!(crypto::encrypt_combined(token, &key).unwrap());
    rows[1]["role"] = json!("assistant");
    rows[1]["encrypted_pii_mappings"] = json!(
        crypto::encrypt_combined(
            &json!([{"placeholder":token,"original":"Must not apply assistant map"}]).to_string(),
            &key
        )
        .unwrap()
    );
    let bytes: usize = rows
        .iter()
        .map(|r| serde_json::to_vec(r).unwrap().len())
        .sum();
    let page = json!({"chat_id":ID,"messages":rows,"has_more_before":true,"has_more_after":false,"start_cursor":{"created_at":1,"message_id":"10000000-0000-4000-8000-000000000001"},"end_cursor":{"created_at":2,"message_id":"10000000-0000-4000-8000-000000000002"},"anchor_found":true,"payload_bytes":bytes,"oversized_message":false,"oversized_message_cursor":null,"server_message_count":99,"messages_v":99});
    let (endpoint, server) = serve(vec![json!({"chats":[row]}), page]).await;
    let session: Session=serde_json::from_value(json!({"api_url":endpoint,"session_id":"synthetic","cookies":{},"ws_token":null,"email_encryption_key":null,"paired_session_expires_at":null,"active_team_id":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","created_at":1})).unwrap();
    let mut client = Client::new(&endpoint, Some(session)).unwrap();
    client.history.insert(
        ID.into(),
        vec![json!({"sentinel":"prior-complete-ciphertext"})],
    );
    client.active_chat = Some("prior-selection".into());
    let before = client.ciphertext_snapshot();
    let publication_scope = client.message_window_scope().unwrap();
    let outcome = client
        .chat_message_window(
            ID,
            MessageWindowOptions {
                limit: 2,
                ..Default::default()
            },
        )
        .await;
    if expire_at_publication {
        let window = outcome.unwrap();
        client.session.as_mut().unwrap().paired_session_expires_at = Some(0);
        assert!(matches!(
            client.publish_message_window(&publication_scope, window),
            Err(Error::Expired)
        ));
    } else {
        let window = outcome.unwrap();
        assert_eq!(window.chat.messages.len(), 2);
        assert_eq!(window.chat.messages[0].content, token);
        assert!(window.has_more_before);
        assert!(!window.history_complete);
        assert_eq!(window.pii_restoration, "page_local");
    }
    assert_eq!(before, client.ciphertext_snapshot());
    assert_eq!(client.active_chat.as_deref(), Some("prior-selection"));
    server.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[tokio::test]
async fn one_page_never_overwrites_complete_history_or_snapshot() {
    exercise_page_finalization(false).await;
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.lifecycle,sync.startup.bounded-phases
#[tokio::test]
async fn paired_expiry_at_final_publication_returns_no_decoded_page() {
    exercise_page_finalization(true).await;
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn around_anchor_consistency_accepts_only_present_alias_or_explicit_oversize() {
    let anchor = "10000000-0000-4000-8000-000000000003";
    let alias = "30000000-0000-4000-8000-000000000003";
    let mut options = MessageWindowOptions {
        direction: MessageWindowDirection::Around,
        anchor_message_id: Some(anchor.into()),
        ..Default::default()
    };
    let unrelated = [json!({"id":"10000000-0000-4000-8000-000000000001"})];
    assert!(validate_anchor(&options, &unrelated, true, false, None).is_err());
    assert!(validate_anchor(&options, &unrelated, false, false, None).is_err());
    assert!(validate_anchor(&options, &[], true, false, None).is_err());
    assert!(validate_anchor(&options, &[], false, false, None).is_ok());
    let row = [json!({"id":alias,"client_message_id":anchor})];
    options.anchor_message_id = Some(alias.into());
    assert!(validate_anchor(&options, &row, true, false, None).is_ok());
    options.anchor_message_id = Some(anchor.into());
    let mut oversized = valid_cursor();
    oversized.message_id = anchor.into();
    assert!(validate_anchor(&options, &[], true, true, Some(&oversized)).is_ok());
    oversized.message_id = alias.into();
    assert!(validate_anchor(&options, &[], true, true, Some(&oversized)).is_err());
}

// A final page must retain the actual pre-await master/context binding, not
// merely accept whichever key happens to be present after asynchronous IO.
#[test]
fn page_publication_refuses_replaced_key_and_denial_recovery_aba(){
    for change in 0..2 {
        let session:Session=serde_json::from_value(json!({"api_url":"http://127.0.0.1:9","session_id":"synthetic","cookies":{},"ws_token":null,"email_encryption_key":null,"paired_session_expires_at":null,"active_team_id":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"","created_at":1})).unwrap();
        let mut client=Client::new("http://127.0.0.1:9",Some(session)).unwrap();
        let scope=client.message_window_scope().unwrap();let key_scope=super::super::sync_capability::AsyncCryptoScope::begin(&client).unwrap();let before=client.ciphertext_snapshot();
        let window=ChatMessageWindow{chat:Chat{id:ID.into(),title:"Synthetic prior key".into(),..Chat::default()},has_more_before:false,has_more_after:false,anchor_found:false,start_cursor:None,end_cursor:None,server_message_count:None,messages_version:None,oversized_message:false,oversized_message_cursor:None,payload_bytes:0,pii_restoration:"page_local".into(),history_complete:false};
        if change==0{client.session.as_mut().unwrap().master_key=zeroize::Zeroizing::new([9;32]);}
        else{client.task_watch_authority.deny_cached_chat(Some(ID)).unwrap();let revision=client.task_watch_authority.cached_denial_revision().unwrap();client.task_watch_authority.commit_cached_chat_recovery(ID,false,revision).unwrap();assert!(client.task_watch_authority.cached_chat_allowed(ID));}
        assert!(matches!(client.publish_message_window_with_capability(&scope,&key_scope,window),Err(Error::Cancelled)));
        assert_eq!(client.ciphertext_snapshot(),before);assert_eq!(client.credential_ack,0);
    }
}
// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn shared_saved_message_ids_are_nonempty_opaque_utf8_without_uuid_or_normalization() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/message-id-compatibility.json"
    )).unwrap();
    for case in fixture["cases"].as_array().unwrap() {
        let valid = case["value"].as_str().is_some_and(valid_message_id);
        assert_eq!(valid, case["valid"].as_bool().unwrap(), "{}", case["id"]);
        if let Some(value) = case["value"].as_str() {
            let mut cursor = valid_cursor();
            cursor.message_id = value.into();
            for direction in [MessageWindowDirection::Before, MessageWindowDirection::After] {
                let options = MessageWindowOptions { direction, cursor: Some(cursor.clone()), ..Default::default() };
                assert_eq!(options.validate(ID, &cursor.scope).is_ok(), valid);
                if valid {
                    assert!(matches!(options.validate(ID, &"b".repeat(64)), Err(Error::Conflict)));
                    assert!(matches!(options.validate("33333333-3333-4333-8333-333333333333", &cursor.scope), Err(Error::Conflict)));
                }
            }
            let options = MessageWindowOptions { direction: MessageWindowDirection::Around, anchor_message_id: Some(value.into()), ..Default::default() };
            assert_eq!(options.validate(ID, &"a".repeat(64)).is_ok(), valid);
        }
    }
    for byte in 0_u8..=127 {
        assert!(valid_message_id(&String::from(char::from(byte))));
    }
    for suffix in ["\n", "\r", "\u{2028}", "\u{2029}"] {
        assert!(valid_message_id(&format!("message{suffix}")));
    }
    assert_eq!(fixture["schema_version"], 2);
    assert!(fixture["policy"]["per_id_maximum"].is_null());
    // Former ASCII/length negatives are intentionally inverted and documented.
    assert!(fixture["cases"].as_array().unwrap().iter().any(|v| v["previous_valid"] == false && v["valid"] == true && v["policy_change"].is_string()));
    let huge = MessageWindowOptions { direction:MessageWindowDirection::Around, anchor_message_id:Some("x".repeat(MAX_MESSAGE_BYTES)), ..Default::default() };
    assert!(huge.validate(ID,&"a".repeat(64)).is_err());
    assert!(!valid_message_id(""));
    assert!(uuid::Uuid::parse_str("2222222222-10000000-0000-4000-8000-000000000001").is_err());
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn server_message_alias_preference_keeps_legacy_empty_fallback_and_database_alias() {
    let logical = "2222222222-10000000-0000-4000-8000-000000000001";
    let database = "90000000-0000-4000-8000-000000000001";
    for row in [
        json!({"client_message_id":logical,"message_id":logical,"id":database}),
        json!({"client_message_id":"","message_id":logical,"id":database}),
        json!({"client_message_id":null,"message_id":logical,"id":database}),
        json!({"message_id":logical,"id":database}),
        json!({"client_message_id":"","message_id":"","id":logical}),
    ] {
        assert_eq!(server_message_id(&row).unwrap(), logical);
    }
    for row in [
        json!({"client_message_id":logical,"message_id":"different-message","id":database}),
        json!({"client_message_id":42,"message_id":logical,"id":database}),
        json!({"client_message_id":logical,"message_id":false,"id":database}),
        json!({"client_message_id":logical,"id":{}}),
        json!({"client_message_id":"","message_id":null,"id":""}),
    ] {
        assert!(matches!(server_message_id(&row), Err(Error::Protocol)));
    }
    // Former control-only rejection is explicitly inverted; aliases above stay strict.
    assert_eq!(server_message_id(&json!({"client_message_id":"message\n","id":database})).unwrap(),"message\n");
    let page = json!({"start_cursor":{"created_at":1,"message_id":logical}});
    assert_eq!(cursor(&page, "start_cursor", ID, &"a".repeat(64)).unwrap().unwrap().message_id, logical);
    assert_eq!(segment("message:client.42@source"), "message%3Aclient.42%40source");
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[tokio::test]
async fn raw_browser_cache_capture_is_opt_in_same_response_and_keeps_wire_omissions() {
    tokio::time::timeout(std::time::Duration::from_secs(10),async{
        for capture in [false,true]{
            let owner="11111111-1111-4111-8111-111111111111";let key=[9;32];
            let metadata=json!({"id":ID,"messages_v":2,"encrypted_chat_key":crypto::encrypt_bytes(&key,&[7;32]).unwrap(),"encrypted_title":crypto::encrypt_combined("Synthetic title",&key).unwrap()});
            let rows=vec![json!({"id":"physical_a","client_message_id":"logical_a","chat_id":ID,"created_at":1,"role":"user","encrypted_content":crypto::encrypt_combined("Wire A",&key).unwrap(),"encrypted_sender_name":null,"unknown_extension":"synthetic raw only"}),json!({"id":"physical_b","client_message_id":"logical_b","chat_id":ID,"created_at":2,"role":"assistant","encrypted_content":crypto::encrypt_combined("Wire B",&key).unwrap(),"status":"synced"})];
            let bytes:usize=rows.iter().map(|r|serde_json::to_vec(r).unwrap().len()).sum();
            let page=json!({"chat_id":ID,"messages":rows,"has_more_before":false,"has_more_after":false,"start_cursor":{"created_at":1,"message_id":"logical_a"},"end_cursor":{"created_at":2,"message_id":"logical_b"},"anchor_found":true,"payload_bytes":bytes,"oversized_message":false,"oversized_message_cursor":null,"server_message_count":2,"messages_v":2});
            let (endpoint,server)=serve(vec![json!({"chats":[metadata.clone()]}),page.clone()]).await;
            let session:Session=serde_json::from_value(json!({"api_url":endpoint,"session_id":"synthetic","cookies":{},"ws_token":null,"email_encryption_key":null,"paired_session_expires_at":null,"active_team_id":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","created_at":1})).unwrap();
            let mut c=Client::new(&endpoint,None).unwrap();c.set_app_origin(Some("https://app.example.invalid".into())).unwrap();c.browser_transport=true;c.browser_credentials=Some(crate::client::credentials::BrowserCredentials::from_native_session(session));c.browser_authority=Some(crate::client::browser::BrowserAuthority{principal:owner.into(),persistence:crate::client::BrowserPersistence::MemoryOnly,owner_guards:true});c.user=json!({"id":owner});
            let options=MessageWindowOptions{limit:2,..Default::default()};
            let result=if capture{c.read_browser_cache_message_page(ID,options).await}else{c.read_message_page(ID,options,false).await};
            let mut result=Plain::new(result.unwrap());assert_eq!(result.window.chat.messages.len(),2);
            if capture{let raw=result.incoming.take().unwrap();assert_eq!(*raw.metadata,metadata);assert_eq!(&*raw.messages,page["messages"].as_array().unwrap());assert!(raw.messages[0].get("status").is_none());assert_eq!(raw.messages[0]["encrypted_sender_name"],Value::Null);assert!(raw.messages[1].get("encrypted_sender_name").is_none());}
            else{assert!(result.incoming.is_none(),"ordinary/default reads retain no raw capture");}
            server.await.unwrap();assert_eq!(c.credential_ack,0);
        }
    }).await.unwrap();
}
