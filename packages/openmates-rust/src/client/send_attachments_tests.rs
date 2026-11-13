//! Exact `chat_turn_admit` payload of turns carrying composer embeds or PII exclusions.
// contract-test: supporting surface=sdks.rust assertions=pii.composer.detect-redact-exclude
use super::super::embed_write::keys::{decrypt_text, unwrap_key, unwrap_key_with_master};
use super::super::*;
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::tungstenite::Message as Frame;

const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const TURN: &str = "33333333-3333-4333-8333-333333333333";
const MESSAGE: &str = "44444444-4444-4444-8444-444444444444";
const IMAGE: &str = "55555555-5555-4555-8555-555555555555";
const CODE: &str = "66666666-6666-4666-8666-666666666666";
const IMAGE_CONTENT: &str = "type: image\nfilename: garden-shed.png\ns3_base_url: https://files.example.org\naes_key: synthetic-file-key\nstatus: finished";
const CODE_CONTENT: &str = "type: code\nlanguage: python\ncode: print(\"hello\")";

fn client() -> Client {
    let mut session = super::super::sdk_boundary_tests::session();
    session.api_url = "http://127.0.0.1:1".into();
    session.master_key = zeroize::Zeroizing::new([7; 32]);
    let mut c = Client::new("http://127.0.0.1:1", Some(session)).unwrap();
    c.user = json!({"id": OWNER});
    c
}

fn image() -> SendEmbed {
    SendEmbed {
        embed_id: IMAGE.into(),
        kind: "image".into(),
        reference_type: None,
        status: "finished".into(),
        content: Some(Zeroizing::new(IMAGE_CONTENT.into())),
        text_preview: Some(Zeroizing::new("garden-shed.png".into())),
        embed_ids: None,
    }
}

fn code() -> SendEmbed {
    SendEmbed {
        embed_id: CODE.into(),
        kind: "code-code".into(),
        reference_type: Some("code".into()),
        status: "finished".into(),
        content: Some(Zeroizing::new(CODE_CONTENT.into())),
        text_preview: None,
        embed_ids: None,
    }
}

/// The new-chat admission one real `prepare_turn_on_socket` sends to a
/// synthetic peer, plus the chat key used.
async fn admitted(input: &str, options: SendOptions) -> (Value, Key, Client) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let peer = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let mut admitted = None;
        while let Some(raw) = ws.next().await {
            let raw = raw.unwrap();
            if matches!(raw, Frame::Close(_)) {
                return admitted.expect("admission");
            }
            let event: Value = serde_json::from_str(&raw.into_text().unwrap()).unwrap();
            match event["type"].as_str().unwrap() {
                "set_active_chat" => {}
                "personal_send_context_snapshot" => {
                    let reply = json!({"type": "personal_send_context_snapshot_result", "payload": {
                        "success": true, "unchanged": false,
                        "request_id": event["payload"]["request_id"], "turn_id": TURN,
                        "receipt_id": "synthetic-receipt", "privacy_generation": 1,
                        "project_candidates": [], "personal_memories": {"memories": []}}});
                    ws.send(Frame::Text(reply.to_string().into()))
                        .await
                        .unwrap();
                }
                "chat_turn_admit" => admitted = Some(event["payload"].clone()),
                other => panic!("unexpected frame {other}"),
            }
        }
        panic!("missing close")
    });
    let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
        .await
        .unwrap();
    let mut socket = transport::test_socket(inner);
    let mut c = client();
    // A new chat's key, wrapped with the synthetic native master key.
    let key = crypto::random_key();
    let wrapped = crypto::server_fields::encrypt_bytes(key.as_ref(), &[7; 32], &[]).unwrap();
    let chat = Chat {
        id: CHAT.into(),
        ..Default::default()
    };
    let (tx, _rx) = mpsc::channel(16);
    let scope = super::super::sync_capability::AsyncCryptoScope::begin(&c).unwrap();
    let generation = c.generation;
    c.prepare_turn_on_socket(
        &mut socket,
        CHAT,
        TURN,
        MESSAGE,
        input,
        &key,
        &wrapped,
        0,
        true,
        &[],
        &chat,
        &tx,
        &CancellationToken::new(),
        generation,
        None,
        &options,
        &scope,
    )
    .await
    .unwrap();
    let _ = socket.close(None).await;
    let body = crate::platform::time::timeout(Duration::from_secs(3), peer)
        .await
        .unwrap()
        .unwrap();
    (body, key, c)
}

fn reference(kind: &str, id: &str) -> String {
    format!("```json\n{{\"type\": \"{kind}\", \"embed_id\": \"{id}\"}}\n```")
}

/// Assert one encrypted bundle entry decrypts to `embed` under the derived
/// key and carries the master then chat wrapper of that key.
async fn assert_bundle_entry(entry: &Value, embed: &SendEmbed, key: &Key, c: &Client) {
    let embed_key = derive_embed_key(key, &embed.embed_id).unwrap();
    let (chat_hash, user_hash) = (hash_id(CHAT), hash_id(OWNER));
    let mut keys: Vec<&str> = entry
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    keys.sort_unstable();
    let mut expected = vec![
        "created_at",
        "embed_id",
        "embed_keys",
        "encrypted_content",
        "encrypted_type",
        "hashed_chat_id",
        "hashed_message_id",
        "hashed_user_id",
        "status",
        "updated_at",
    ];
    if embed.text_preview.is_some() {
        expected.push("encrypted_text_preview");
        expected.sort_unstable();
    }
    assert_eq!(keys, expected);
    assert_eq!(entry["embed_id"], embed.embed_id);
    assert_eq!(entry["status"], "finished");
    assert_eq!(entry["hashed_chat_id"], chat_hash);
    assert_eq!(entry["hashed_message_id"], hash_id(MESSAGE));
    assert_eq!(entry["hashed_user_id"], user_hash);
    let open =
        |field: &str| decrypt_text(entry[field].as_str().unwrap(), &embed_key, None).unwrap();
    assert_eq!(open("encrypted_type").as_str(), embed.kind);
    assert_eq!(
        open("encrypted_content").as_str(),
        embed.content.as_ref().unwrap().as_str()
    );
    if let Some(preview) = &embed.text_preview {
        assert_eq!(open("encrypted_text_preview").as_str(), preview.as_str());
    }
    let wrappers = entry["embed_keys"].as_array().unwrap();
    assert_eq!(wrappers.len(), 2);
    let embed_hash = hash_id(&embed.embed_id);
    for (wrapper, kind, chat) in [
        (&wrappers[0], "master", Value::Null),
        (&wrappers[1], "chat", json!(chat_hash)),
    ] {
        assert_eq!(wrapper["key_type"], kind);
        assert_eq!(wrapper["hashed_embed_id"], embed_hash);
        assert_eq!(wrapper["hashed_chat_id"], chat);
        assert_eq!(wrapper["hashed_user_id"], user_hash);
        assert_eq!(wrapper["created_at"], entry["created_at"]);
    }
    let master = c.master_capability().unwrap();
    let by_master = unwrap_key_with_master(
        wrappers[0]["encrypted_embed_key"].as_str().unwrap(),
        &master,
    )
    .await
    .unwrap();
    let by_chat = unwrap_key(wrappers[1]["encrypted_embed_key"].as_str().unwrap(), key).unwrap();
    assert_eq!(*by_master, *embed_key);
    assert_eq!(*by_chat, *embed_key);
}

fn content_of(body: &Value, key: &Key) -> String {
    let inference = body["inference_request"]["message"]["content"]
        .as_str()
        .unwrap()
        .to_owned();
    let stored = crypto::decrypt_combined(
        body["encrypted_user_message"]["encrypted_content"]
            .as_str()
            .unwrap(),
        key,
    )
    .unwrap();
    assert_eq!(
        stored, inference,
        "the stored and the inference content agree"
    );
    inference
}

#[tokio::test]
async fn uploaded_image_embed_becomes_reference_cleartext_copy_and_wrapped_bundle() {
    let options = SendOptions {
        pii_detection: false,
        embeds: vec![image()],
        ..Default::default()
    };
    let (body, key, c) = admitted("  What is in this picture?  ", options).await;
    let content = content_of(&body, &key);
    assert_eq!(
        content,
        format!("What is in this picture?\n\n{}", reference("image", IMAGE))
    );
    let request = &body["inference_request"];
    let created = request["message"]["created_at"].clone();
    assert_eq!(
        request["embeds"],
        json!([{"embed_id": IMAGE, "type": "image", "status": "finished",
        "content": IMAGE_CONTENT, "text_preview": "garden-shed.png",
        "createdAt": created, "updatedAt": created}])
    );
    let bundle = request["encrypted_embeds"].as_array().unwrap();
    assert_eq!(bundle.len(), 1);
    assert_bundle_entry(&bundle[0], &image(), &key, &c).await;
    assert_eq!(bundle[0]["created_at"], created);
    // Keys and plaintext never reach the server outside their envelopes.
    let wire = body.to_string();
    assert_eq!(
        wire.matches("synthetic-file-key").count(),
        1,
        "only the cleartext inference copy"
    );
    assert!(body.get("embeds").is_none() && body.get("encrypted_embeds").is_none());
}

#[tokio::test]
async fn code_embed_uses_its_reference_type_and_keeps_an_existing_reference_once() {
    let text = format!("Explain this\n\n{}", reference("code", CODE));
    let options = SendOptions {
        pii_detection: false,
        embeds: vec![code()],
        ..Default::default()
    };
    let (body, key, c) = admitted(&text, options).await;
    assert_eq!(content_of(&body, &key), text);
    let request = &body["inference_request"];
    let created = request["message"]["created_at"].clone();
    assert_eq!(
        request["embeds"],
        json!([{"embed_id": CODE, "type": "code-code", "status": "finished",
        "content": CODE_CONTENT, "createdAt": created, "updatedAt": created}])
    );
    let bundle = request["encrypted_embeds"].as_array().unwrap();
    assert_eq!(bundle.len(), 1);
    assert_bundle_entry(&bundle[0], &code(), &key, &c).await;
}

#[tokio::test]
async fn two_embeds_keep_composer_order_and_a_stored_reference_has_no_bundle() {
    let stored = SendEmbed {
        embed_id: "77777777-7777-4777-8777-777777777777".into(),
        kind: "pdf".into(),
        status: "finished".into(),
        ..Default::default()
    };
    let options = SendOptions {
        pii_detection: false,
        embeds: vec![image(), code(), stored.clone()],
        ..Default::default()
    };
    let (body, key, c) = admitted("Compare both", options).await;
    assert_eq!(
        content_of(&body, &key),
        format!(
            "Compare both\n\n{}\n\n{}\n\n{}",
            reference("image", IMAGE),
            reference("code", CODE),
            reference("pdf", &stored.embed_id)
        )
    );
    let request = &body["inference_request"];
    let ids: Vec<&str> = request["embeds"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| e["embed_id"].as_str().unwrap())
        .collect();
    assert_eq!(ids, [IMAGE, CODE]);
    let bundle = request["encrypted_embeds"].as_array().unwrap();
    assert_eq!(bundle.len(), 2);
    assert_bundle_entry(&bundle[0], &image(), &key, &c).await;
    assert_bundle_entry(&bundle[1], &code(), &key, &c).await;
}

#[tokio::test]
async fn attachment_only_turn_sends_only_the_reference_block() {
    let options = SendOptions {
        pii_detection: false,
        embeds: vec![image()],
        ..Default::default()
    };
    let (body, key, _) = admitted("", options).await;
    assert_eq!(content_of(&body, &key), reference("image", IMAGE));
}

#[tokio::test]
async fn pii_exclusion_leaves_the_excluded_span_in_clear_while_others_are_replaced() {
    let options = SendOptions {
        pii_detection: true,
        pii_exclusions: crate::privacy::PiiExclusions {
            originals: vec![Zeroizing::new("alice@example.org".into())],
            placeholders: vec![],
        },
        pii_mappings: vec![SendPiiMapping {
            placeholder: "[OM_PII_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB]".into(),
            original: Zeroizing::new("Example Lane 7".into()),
            kind: "ADDRESS".into(),
        }],
        ..Default::default()
    };
    let (body, key, _) = admitted("Mail alice@example.org and bob@example.org about [OM_PII_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB]", options).await;
    let content = content_of(&body, &key);
    assert!(
        content.starts_with("Mail alice@example.org and [OM_PII_"),
        "{content}"
    );
    assert!(!content.contains("bob@example.org"));
    assert!(content.ends_with(" about [OM_PII_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB]"));
    let mappings: Value = serde_json::from_str(
        &crypto::decrypt_combined(
            body["encrypted_user_message"]["encrypted_pii_mappings"]
                .as_str()
                .unwrap(),
            &key,
        )
        .unwrap(),
    )
    .unwrap();
    let originals: Vec<&str> = mappings
        .as_array()
        .unwrap()
        .iter()
        .map(|m| m["original"].as_str().unwrap())
        .collect();
    assert_eq!(originals, ["Example Lane 7", "bob@example.org"]);
    assert_eq!(
        mappings[0],
        json!({"original": "Example Lane 7",
        "placeholder": "[OM_PII_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB]", "type": "ADDRESS"})
    );
    assert!(!body.to_string().contains("bob@example.org"));
}

#[test]
fn validation_refuses_malformed_attachments_and_mappings() {
    assert!(validate(&[image(), code()], &[], false).is_ok());
    let bad = |embed: SendEmbed| matches!(validate(&[embed], &[], false), Err(Error::Invalid(_)));
    assert!(bad(SendEmbed {
        embed_id: "id\"injection".into(),
        ..image()
    }));
    assert!(bad(SendEmbed {
        embed_id: String::new(),
        ..image()
    }));
    assert!(bad(SendEmbed {
        kind: "image\"".into(),
        ..image()
    }));
    assert!(bad(SendEmbed {
        reference_type: Some("a b".into()),
        ..image()
    }));
    assert!(bad(SendEmbed {
        status: String::new(),
        ..image()
    }));
    assert!(bad(SendEmbed {
        content: Some(Zeroizing::new(String::new())),
        ..image()
    }));
    assert!(bad(SendEmbed {
        embed_ids: Some(vec!["../x".into()]),
        ..image()
    }));
    assert!(matches!(
        validate(&[image(), image()], &[], false),
        Err(Error::Invalid(_))
    ));
    let reference_only = SendEmbed {
        content: None,
        ..image()
    };
    assert!(validate(std::slice::from_ref(&reference_only), &[], false).is_ok());
    assert!(matches!(
        validate(&[reference_only], &[], true),
        Err(Error::Invalid(_))
    ));
    let mapping = |placeholder: &str, original: &str| SendPiiMapping {
        placeholder: placeholder.into(),
        original: Zeroizing::new(original.into()),
        kind: String::new(),
    };
    assert!(validate(&[], &[mapping("[EMAIL_1]", "a@example.org")], false).is_ok());
    assert!(matches!(
        validate(&[], &[mapping("EMAIL_1", "a@example.org")], false),
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        validate(&[], &[mapping("[EMAIL_1]", "")], false),
        Err(Error::Invalid(_))
    ));
    assert_eq!(
        mapping("[EMAIL_1]", "a@example.org").to_value()["type"],
        "OTHER"
    );
    assert!(!format!("{:?}", image()).contains("synthetic-file-key"));
    let options = SendOptions {
        embeds: vec![SendEmbed {
            embed_id: "bad id".into(),
            ..image()
        }],
        ..Default::default()
    };
    assert!(matches!(options.validate(), Err(Error::Invalid(_))));
}
