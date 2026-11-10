//! Image revision wire fixture: recovery receipts of a revision's sealed `(embed, N+1)` and `(diff, N+1)` outputs.
use super::child_revision_tests::{code, confirmed_head, data, diff, id, local_rows, session, steps, store, v1_head, wire};
use super::keys::{self, derive_embed_key, hash_id};
use super::revision_recovery::{RevisionRecoveryReceipt as Receipt, ReceiptSource, is_child_revision_row};
use super::*;
use serde_json::{Value, json};

fn verified(digest: String, source: ReceiptSource) -> Receipt {
    Receipt::Verified { canonical_digest: digest, canonical_source: source }
}
/// `[encrypted_snapshot, null]` digest as the extension and the web shell compute it.
fn row_digest(snapshot: &str) -> String {
    hash_id(&format!("[\"{snapshot}\",null]"))
}
/// The bounded-v1 page of `version` holding `rows` (`EncryptedDiffRow`s).
fn page(image: &str, version: i64, rows: &[&history::EncryptedDiffRow]) -> Value {
    json!({"embed_id": image, "version_number": version, "rows": rows.iter().map(|row| json!({
        "version_number": row.version_number, "encrypted_snapshot": row.encrypted_snapshot,
        "encrypted_patch": row.encrypted_patch, "created_at": row.created_at,
    })).collect::<Vec<_>>()})
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.same-embed-new-version
#[tokio::test]
async fn revision_embed_output_is_verified_against_the_head_that_keeps_the_creating_message() {
    let w = wire();
    let mut session = session(&w).await;
    let v1 = v1_head(&mut session, &w).await;
    let sealed = data(&w["v2_event"]);
    // Before any device wrote version 2, the head is still at 1: the shell writes first.
    assert_eq!(session.child_revision_embed_receipt(&sealed, &v1, None, Some(&v1)), Ok(Receipt::NotApplied));

    let v2 = session.plan_child_revision(data(&w["v2_event"]), Some(&v1), Vec::new()).unwrap().finish(2).await.unwrap();
    let head = store(&steps(&v2)[1]).clone();
    // The head keeps message 1's hash; the sealed payload names the changing message 2.
    assert_eq!(head["hashed_message_id"], json!(hash_id(w["ids"]["messages"][0].as_str().unwrap())));
    assert_ne!(head["hashed_message_id"], json!(hash_id(w["v2_event"]["message_id"].as_str().unwrap())));
    let expected = verified(hash_id(head["encrypted_content"].as_str().unwrap()), ReceiptSource::Head);
    assert_eq!(session.child_revision_embed_receipt(&sealed, &head, None, Some(&v1)), Ok(expected.clone()));
    // A fresh device without a local head still proves the version by its content.
    assert_eq!(session.child_revision_embed_receipt(&sealed, &head, None, None), Ok(expected));
    let json = serde_json::to_value(session.child_revision_embed_receipt(&sealed, &head, None, None).unwrap()).unwrap();
    assert_eq!((json["state"].as_str(), json["canonical_source"].as_str()), (Some("verified"), Some("head")));
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.message-shows-its-version
#[tokio::test]
async fn superseded_revision_output_is_verified_by_its_version_row() {
    let w = wire();
    let mut session = session(&w).await;
    let image = id(&w, "image");
    let v1 = v1_head(&mut session, &w).await;
    let v2 = session.plan_child_revision(data(&w["v2_event"]), Some(&v1), Vec::new()).unwrap().finish(2).await.unwrap();
    let v3 = session
        .plan_child_revision(data(&w["v3_event"]), Some(&confirmed_head(&v2)), local_rows(&v2, true))
        .unwrap()
        .finish(3)
        .await
        .unwrap();
    let head_v3 = store(&steps(&v3)[0]).clone();
    let sealed = data(&w["v2_event"]);
    assert_eq!(
        session.child_revision_embed_receipt(&sealed, &head_v3, None, Some(&confirmed_head(&v3))),
        Ok(Receipt::VersionPageRequired { version: 2 })
    );
    let (base, row) = (diff(&steps(&v2)[0]).1, diff(&steps(&v2)[2]).1);
    let snapshot = row.encrypted_snapshot.clone().unwrap();
    let full = page(image, 2, &[base, row]);
    assert_eq!(
        session.child_revision_embed_receipt(&sealed, &head_v3, Some(&full), None),
        Ok(verified(row_digest(&snapshot), ReceiptSource::VersionRow))
    );
    // Row 2 holding version 3's content is not this output's version.
    let v3_row = diff(&steps(&v3)[1]).1.clone();
    let mut swapped = v3_row.clone();
    swapped.version_number = 2;
    assert_eq!(
        session.child_revision_embed_receipt(&sealed, &head_v3, Some(&page(image, 2, &[&swapped])), None).map_err(code),
        Err("embed_revision_canonical_differs")
    );
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.same-embed-new-version
#[tokio::test]
async fn revision_embed_receipt_refuses_another_identity_or_content() {
    let w = wire();
    let mut session = session(&w).await;
    let v1 = v1_head(&mut session, &w).await;
    let v2 = session.plan_child_revision(data(&w["v2_event"]), Some(&v1), Vec::new()).unwrap().finish(2).await.unwrap();
    let head = store(&steps(&v2)[1]).clone();
    let sealed = data(&w["v2_event"]);
    let receipt = |head: &Value, stored: Option<&Value>| session.child_revision_embed_receipt(&sealed, head, None, stored).map_err(code);
    let changed = |name: &str, value: Value| {
        let mut row = head.clone();
        row[name] = value;
        row
    };
    let mut other_message = v1.clone();
    other_message["hashed_message_id"] = json!(hash_id("msg-0009-assistant"));
    assert_eq!(receipt(&head, Some(&other_message)), Err("embed_revision_head_mismatch"));
    assert_eq!(receipt(&changed("parent_embed_id", json!("other-parent")), None), Err("embed_revision_head_mismatch"));
    assert_eq!(receipt(&changed("hashed_chat_id", json!(hash_id("other-chat"))), None), Err("embed_revision_head_mismatch"));
    assert_eq!(receipt(&changed("hashed_message_id", Value::Null), None), Err("embed_revision_head_mismatch"));
    let other_content = session
        .with_embed_key(id(&w, "parent_1"), |key| keys::encrypt_text("other", key, None, &mut OsNonces))
        .unwrap();
    assert_eq!(receipt(&changed("encrypted_content", json!(other_content)), None), Err("embed_revision_canonical_differs"));
    // An ordinary payload (no `revision`) never takes this path.
    assert_eq!(
        session.child_revision_embed_receipt(&data(&w["v1_event"]), &v1, None, None).map_err(code),
        Err("protocol")
    );
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.same-embed-new-version
#[tokio::test]
async fn revision_history_output_opens_with_the_parent_key_not_the_child_id_key() {
    let w = wire();
    let mut session = session(&w).await;
    let image = id(&w, "image");
    let v1 = v1_head(&mut session, &w).await;
    let sealed_row = w["v2_event"]["version_history_rows"][0].clone();
    assert!(is_child_revision_row(&sealed_row));
    // The extension stores row 2 only after the head reached 2.
    assert_eq!(session.child_revision_row_receipt(&sealed_row, &v1, None), Ok(Receipt::NotApplied));

    let v2 = session.plan_child_revision(data(&w["v2_event"]), Some(&v1), Vec::new()).unwrap().finish(2).await.unwrap();
    let head = store(&steps(&v2)[1]).clone();
    let row = diff(&steps(&v2)[2]).1;
    assert_eq!(session.child_revision_row_receipt(&sealed_row, &head, None), Ok(Receipt::NotApplied));
    assert_eq!(
        session.child_revision_row_receipt(&sealed_row, &head, Some(&page(image, 2, &[row]))),
        Ok(verified(row_digest(row.encrypted_snapshot.as_deref().unwrap()), ReceiptSource::VersionRow))
    );
    // The former web path opened the row with HKDF(chat key, child id): it never opens.
    let chat_key = keys::key_from(&[3u8; 32]).unwrap();
    let child_id_key = derive_embed_key(&chat_key, image).unwrap();
    let text = sealed_row["snapshot"].as_str().unwrap();
    let mut wrong = row.clone();
    wrong.encrypted_snapshot = Some(keys::encrypt_text(text, &child_id_key, None, &mut OsNonces).unwrap());
    assert_eq!(
        session.child_revision_row_receipt(&sealed_row, &head, Some(&page(image, 2, &[&wrong]))).map_err(code),
        Err("crypto")
    );
    let mut root = head.clone();
    root["parent_embed_id"] = Value::Null;
    assert_eq!(
        session.child_revision_row_receipt(&sealed_row, &root, None).map_err(code),
        Err("embed_revision_head_mismatch")
    );
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.same-embed-new-version
#[test]
fn only_snapshot_only_rows_above_version_one_are_child_revision_rows() {
    let row = |version: i64, patch: Value| json!({"embed_id": "image-1", "version_number": version, "snapshot": "s", "patch": patch});
    assert!(is_child_revision_row(&row(2, Value::Null)));
    assert!(!is_child_revision_row(&row(1, Value::Null)));
    assert!(!is_child_revision_row(&row(2, json!("--- v1"))));
    assert!(!is_child_revision_row(&json!({"embed_id": "image-1", "version_number": 2})));
}
