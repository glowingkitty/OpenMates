//! Restore of version K as the next version: request building, image files of version K, and range checks.
use super::*;
use crate::client::embed_updated_event::EmbedUpdateAction;
use crate::client::embed_user_revision::prepare_user_revision;
use crate::client::embed_write::keys::{NonceSource, encrypt_text};
use serde_json::json;

const EMBED: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const KEY: [u8; 32] = [9; 32];

struct Nonces(u8);
impl NonceSource for Nonces {
    fn next_nonce(&mut self) -> crate::error::Result<[u8; 12]> {
        self.0 += 1;
        Ok([self.0; 12])
    }
}

fn head(version: i64) -> EmbedHead {
    EmbedHead {
        embed_id: EMBED.into(),
        version,
        encrypted_content: encrypt_text("title: current", &KEY, None, &mut Nonces(100))
            .expect("seal"),
        created_at: 1_700_000_000,
        hashed_chat_id: None,
    }
}

fn scope() -> RevisionScope {
    RevisionScope::Chat {
        chat_id: CHAT.into(),
        team_id: None,
    }
}

fn image_v1() -> String {
    json!({
        "app_id": "images", "skill_id": "generated_image", "embed_ref": "cat-photo-x1y",
        "files": {
            "original": {"s3_key": "u/v1_original.png", "mime_type": "image/png", "encryption": "aes-gcm-nonce-prefixed-v1"},
            "preview": {"s3_key": "u/v1_preview.webp", "mime_type": "image/webp", "encryption": "aes-gcm-nonce-prefixed-v1"},
        },
        "aes_key": "A".repeat(44), "aes_nonce": "", "vault_wrapped_aes_key": "vault:v1:abc",
    })
    .to_string()
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.restore.creates-version
#[test]
fn restoring_an_image_names_version_k_files_and_index() {
    let request =
        restore_request(head(3), scope(), 1, Zeroizing::new(image_v1())).expect("request");
    assert_eq!(
        (request.action, request.restored_from),
        (EmbedUpdateAction::Restore, Some(1))
    );
    let prepared =
        prepare_user_revision(&request, &KEY, 1_800_000_000_000, &mut Nonces(0)).expect("prepare");
    let body = prepared.body();
    assert_eq!(body["restored_from"], 1);
    assert_eq!(prepared.version(), 4);
    let keys = body["files"]["head_file_keys"].as_array().expect("keys");
    assert_eq!(keys.len(), 2);
    assert!(keys.contains(&json!({"bucket": "chatfiles", "key": "u/v1_original.png"})));
    assert_eq!(body["media_index"]["vault_wrapped_aes_key"], "vault:v1:abc");
    assert_eq!(body["media_index"]["content_type"], "image/png");
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.restore.creates-version
#[test]
fn restoring_a_document_sends_only_its_content() {
    let content = Zeroizing::new("app_id: docs\ntitle: Kitchen plan v1".to_owned());
    let request = restore_request(head(2), scope(), 1, content).expect("request");
    assert!(request.files.is_none() && request.media_index.is_none());
    assert_eq!(
        request.content.as_str(),
        "app_id: docs\ntitle: Kitchen plan v1"
    );
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.restore.creates-version
#[test]
fn refuses_a_restore_of_the_head_or_outside_the_history() {
    for from in [0, 3, 4] {
        let refused = restore_request(head(3), scope(), from, Zeroizing::new("title: x".into()));
        assert!(
            matches!(
                refused,
                Err(UserRevisionError::Validation {
                    code: "invalid_restored_from"
                })
            ),
            "{from}"
        );
    }
    let broken =
        json!({"app_id": "images", "skill_id": "upload", "files": {"original": {"s3_key": "k"}}});
    assert!(matches!(
        restore_request(head(3), scope(), 1, Zeroizing::new(broken.to_string())),
        Err(UserRevisionError::Validation {
            code: "invalid_media_index"
        })
    ));
}
