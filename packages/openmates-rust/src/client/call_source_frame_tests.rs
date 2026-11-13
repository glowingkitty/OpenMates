//! Call source frame persistence: validation, chat refusal and the sealed embed payload (decrypt round trip).
use super::*;
use crate::client::upload::parse_upload_response;
use base64::engine::general_purpose::STANDARD;

const UPLOAD: &str = r#"{"embed_id":"e1","filename":"f.jpg","content_type":"image/jpeg","content_hash":"h1","files":{"original":{"s3_key":"u/o.jpg","width":2,"height":2}},"s3_base_url":"https://s3.example","aes_key":"QUVTS0VZ","aes_nonce":"Tk9OQ0U=","vault_wrapped_aes_key":"vault:v1:w","ai_detection":null,"deduplicated":false}"#;

fn frame() -> CallSourceFrame {
    CallSourceFrame {
        call_id: "call-1".into(),
        chat_id: "chat-1".into(),
        message_id: "msg-1".into(),
        frame_id: "frame_1-a".into(),
        data: STANDARD.encode([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]),
        captured_at: 12.5,
        created_at: 1_700_000_000,
        source: CallSourceKind::Screen,
    }
}

#[test]
fn accepts_a_valid_jpeg_frame_and_decodes_it() {
    let bytes = validate_frame(&frame()).unwrap();
    assert_eq!(bytes.as_slice(), &[0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]);
}

#[test]
fn rejects_invalid_frames() {
    let mut cases = vec![];
    let mut push = |edit: &dyn Fn(&mut CallSourceFrame)| {
        let mut f = frame();
        edit(&mut f);
        cases.push(f);
    };
    push(&|f| f.call_id.clear());
    push(&|f| f.chat_id.clear());
    push(&|f| f.message_id.clear());
    push(&|f| f.frame_id = "bad id!".into());
    push(&|f| f.frame_id = "a".repeat(241));
    push(&|f| f.captured_at = f64::NAN);
    push(&|f| f.created_at = i64::MAX);
    push(&|f| f.data.clear());
    push(&|f| f.data = "====".into());
    push(&|f| f.data = "not base64!".into());
    push(&|f| f.data = "A".repeat(6_000_001));
    push(&|f| f.data = STANDARD.encode(b"\x89PNG....")); // not JPEG
    for case in cases {
        assert_eq!(validate_frame(&case).err(), Some(CallSourceError::InvalidFrame));
    }
}

#[test]
fn refuses_team_and_direct_chats() {
    assert!(refuse_chat(&json!({"id": "c"})).is_ok());
    for row in [
        json!({"team_id": "t1"}),
        json!({"hashed_team_id": "abc"}),
        json!({"chat_visibility": "direct"}),
    ] {
        assert_eq!(refuse_chat(&row), Err(CallSourceError::ChatUnavailable));
    }
}

#[test]
fn payload_decrypts_with_the_derived_key_and_has_two_wrappers() {
    let upload = parse_upload_response(UPLOAD.as_bytes()).unwrap();
    let chat_key = [7u8; 32];
    let prepared = prepare_store(
        &upload,
        &frame(),
        7,
        &chat_key,
        |_| Ok("master-wrapped".into()),
        "user-1",
        1_700_000_001,
        &mut OsNonces,
    )
    .unwrap();
    let key = keys::derive_embed_key(&chat_key, "e1").unwrap();
    let p = &prepared.payload;
    let open = |field: &str| keys::decrypt_text(p[field].as_str().unwrap(), &key, None).unwrap();
    assert_eq!(open("encrypted_type").as_str(), "images-image");
    assert_eq!(open("encrypted_text_preview").as_str(), "call-source-frame_1-a.jpg");
    let content = open("encrypted_content");
    for line in [
        "app_id: images",
        "skill_id: upload",
        "type: image",
        "status: finished",
        "file_size: 7",
        "file_type: image/jpeg",
        "source_frame_id: frame_1-a",
        "captured_at: 12.5",
        "source: screen",
        "source_call_id: call-1",
        "content_hash: h1",
    ] {
        assert!(content.lines().any(|l| l == line), "missing {line}\n{}", content.as_str());
    }
    assert_eq!(p["hashed_chat_id"], keys::hash_id("chat-1"));
    assert_eq!(p["hashed_message_id"], keys::hash_id("msg-1"));
    assert_eq!(p["hashed_user_id"], keys::hash_id("user-1"));
    assert_eq!((p["is_private"].clone(), p["is_shared"].clone()), (json!(true), json!(false)));
    assert_eq!(prepared.keys.len(), 2);
    assert_eq!(prepared.keys[0]["key_type"], "master");
    assert_eq!(prepared.keys[0]["hashed_chat_id"], Value::Null);
    assert_eq!(prepared.keys[0]["encrypted_embed_key"], "master-wrapped");
    assert_eq!(prepared.keys[1]["key_type"], "chat");
    let unwrapped = keys::unwrap_key(prepared.keys[1]["encrypted_embed_key"].as_str().unwrap(), &chat_key).unwrap();
    assert_eq!(unwrapped.as_slice(), key.as_slice());
}

#[test]
fn error_collapses_to_shell_envelope() {
    assert_eq!(Error::from(CallSourceError::InvalidFrame), Error::Invalid("Invalid call source frame"));
    assert_eq!(Error::from(CallSourceError::ChatUnavailable), Error::Forbidden);
    assert_eq!(Error::from(CallSourceError::AwaitingSync), Error::Offline);
    assert!(keys_confirmed(&json!({"failed_count":0,"created_count":2}), 2));
    assert!(!keys_confirmed(&json!({"failed_count":1,"created_count":1}), 2));
}
