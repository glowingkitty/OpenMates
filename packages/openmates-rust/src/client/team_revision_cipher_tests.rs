//! Stored revision encryption rejects previous Team keys and misplaced ciphertext.

use super::super::{
    EmbedHead, RevisionScope, UserRevisionRequest, prepare_user_revision_with_cipher,
};
use super::*;
use crate::client::embed_write::keys::OsNonces;
use serde_json::json;

// contract-test: supporting surface=sdk assertions=live-collab.keys.rotation-on-removal
#[test]
fn stored_revision_requires_current_epoch_key_and_matching_item_version_and_field() {
    let prior = Zeroizing::new([1; 32]);
    let current = Zeroizing::new([2; 32]);
    let cipher = TeamRevisionCipher::new(&current, "document", 3).unwrap();
    let sealed = cipher
        .seal(5, "content", "post-removal revision", &mut OsNonces)
        .unwrap();

    assert_eq!(ciphertext_epoch(&sealed), Ok(Some(3)));
    assert_eq!(
        cipher.open(5, "content", &sealed).unwrap().as_str(),
        "post-removal revision"
    );
    for wrong_cipher in [
        TeamRevisionCipher::new(&prior, "document", 3).unwrap(),
        TeamRevisionCipher::new(&current, "other-document", 3).unwrap(),
        TeamRevisionCipher::new(&current, "document", 2).unwrap(),
    ] {
        assert!(matches!(
            wrong_cipher.open(5, "content", &sealed),
            Err(Error::Crypto)
        ));
    }
    assert!(matches!(
        cipher.open(4, "content", &sealed),
        Err(Error::Crypto)
    ));
    assert!(matches!(
        cipher.open(5, "preview", &sealed),
        Err(Error::Crypto)
    ));
    assert_eq!(ciphertext_epoch("OMRV1.03.invalid"), Err(Error::Crypto));
    assert_eq!(ciphertext_epoch("legacy"), Ok(None));
}

// contract-test: supporting surface=sdk assertions=live-collab.keys.rotation-on-removal
#[test]
fn prepared_checkpoint_seals_head_and_snapshot_without_resealing_historical_base() {
    let old = Zeroizing::new([7; 32]);
    let team = Zeroizing::new([8; 32]);
    let cipher = TeamRevisionCipher::new(&team, "document", 2).unwrap();
    let base = encrypt_text("previous revision", &old, None, &mut OsNonces).unwrap();
    let head = EmbedHead::from_cached_row(
        "document",
        &json!({
            "embed_id": "document", "version_number": 3, "encrypted_content": base,
        }),
        1_790_000_000,
    )
    .unwrap();
    let request = UserRevisionRequest::content_edit(
        head,
        RevisionScope::Project {
            project_id: "project".to_string(),
            team_id: Some("team".to_string()),
        },
        Zeroizing::new("post-removal revision".into()),
        Some(Zeroizing::new("post-removal preview".into())),
        None,
    );
    let mut prepared = prepare_user_revision_with_cipher(
        &request,
        &old,
        Some(&cipher),
        1_790_000_000_000,
        &mut OsNonces,
    )
    .unwrap();
    prepared.include_base();
    let body = prepared.body();
    let sealed = body["head"]["encrypted_content"].as_str().unwrap();
    let preview = body["head"]["encrypted_text_preview"].as_str().unwrap();
    assert_eq!(body["history_rows"][0]["encrypted_snapshot"], base);
    assert_eq!(body["history_rows"][1]["encrypted_snapshot"], sealed);
    assert_eq!(
        cipher.open(4, "content", sealed).unwrap().as_str(),
        "post-removal revision"
    );
    assert_eq!(
        cipher.open(4, "preview", preview).unwrap().as_str(),
        "post-removal preview"
    );
    for (framed, field) in [(sealed, "content"), (preview, "preview")] {
        let (_, payload) = envelope(framed).unwrap().unwrap();
        assert!(matches!(
            decrypt_text(payload, &old, Some(&cipher.aad(4, field))),
            Err(Error::Crypto)
        ));
    }
}
