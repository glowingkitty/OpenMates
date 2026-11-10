//! Image revision wire fixture (`tests/crypto_fixtures/image_revision_wire.json`): child revision writes and message-scoped versions.
use super::keys::{self, hash_id};
use super::*;
use crate::crypto::{Key, master::MasterCapability};
use crate::error::Error;
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};

fn wire() -> Value {
    serde_json::from_str(include_str!(
        "../../tests/crypto_fixtures/image_revision_wire.json"
    ))
    .unwrap()
}
fn ts() -> Value {
    serde_json::from_str(include_str!(
        "../../tests/crypto_fixtures/ts_embed_writes.json"
    ))
    .unwrap()
}
fn key(value: &Value) -> Key {
    keys::key_from(&STANDARD.decode(value.as_str().unwrap()).unwrap()).unwrap()
}
fn id<'a>(w: &'a Value, name: &str) -> &'a str {
    w["ids"][name].as_str().unwrap()
}
fn data(value: &Value) -> StreamedEmbedData {
    StreamedEmbedData::from_value(value.clone()).unwrap()
}
fn code(error: Error) -> &'static str {
    match error {
        Error::Unavailable { code, .. } => code,
        Error::Protocol => "protocol",
        Error::Conflict => "conflict",
        Error::Crypto => "crypto",
        Error::Invalid(_) => "invalid",
        _ => "other",
    }
}
fn decrypt(session: &EmbedWriteSession, owner: &str, ciphertext: &Value) -> String {
    session
        .with_embed_key(owner, |k| {
            keys::decrypt_text(ciphertext.as_str().unwrap(), k, None)
        })
        .unwrap()
        .as_str()
        .to_owned()
}

/// Session holding the chat key and message 1's parent key (`P1` lists the image).
async fn session(w: &Value) -> EmbedWriteSession {
    let f = ts();
    let master = MasterCapability::from_browser_raw(key(&f["keys"]["master_b64"]));
    let mut session = EmbedWriteSession::new(master);
    let chat = id(w, "chat");
    let adoption = session
        .chat_key_adoption(chat, f["wrappers"]["encrypted_chat_key"].as_str().unwrap())
        .unwrap();
    session.install(adoption.resolve().await.unwrap());
    let parent = json!({
        "embed_id": id(w, "parent_1"), "type": "app_skill_use", "status": "finished", "chat_id": chat,
        "message_id": w["ids"]["messages"][0], "user_id": id(w, "user"),
        "content": w["parents"][0]["parent_contents"][0], "embed_ids": [id(w, "image")],
    });
    session
        .plan_stream_completion(data(&parent))
        .unwrap()
        .finish(1_790_000_100_000)
        .await
        .unwrap();
    session
}
/// Stored v1 head: the ordinary child write of message 1.
async fn v1_head(session: &mut EmbedWriteSession, w: &Value) -> Value {
    session
        .plan_stream_completion(data(&w["v1_event"]))
        .unwrap()
        .finish(1_790_000_101_000)
        .await
        .unwrap()
        .local_entry
}
fn steps(prepared: &PreparedEmbedWrite) -> &[ChildRevisionStep] {
    &prepared.child_revision.as_ref().unwrap().steps
}
fn diff(step: &ChildRevisionStep) -> (RevisionRowRole, &history::EncryptedDiffRow, &Value) {
    match step {
        ChildRevisionStep::StoreEmbedDiff {
            role,
            local_row,
            server_payload,
            ..
        } => (*role, local_row, server_payload),
        ChildRevisionStep::StoreEmbed { .. } => panic!("expected a store_embed_diff step"),
    }
}
fn store(step: &ChildRevisionStep) -> &Value {
    match step {
        ChildRevisionStep::StoreEmbed { store_payload, .. } => store_payload,
        ChildRevisionStep::StoreEmbedDiff { .. } => panic!("expected a store_embed step"),
    }
}
/// The local head after every send of `prepared` succeeded.
fn confirmed_head(prepared: &PreparedEmbedWrite) -> Value {
    steps(prepared)
        .iter()
        .find_map(|step| match step {
            ChildRevisionStep::StoreEmbed {
                confirmed_entry, ..
            } => Some(confirmed_entry.clone()),
            ChildRevisionStep::StoreEmbedDiff { .. } => None,
        })
        .unwrap()
}
/// Local rows of `prepared`, confirmed (`true`) or as stored before the send.
fn local_rows(prepared: &PreparedEmbedWrite, confirmed: bool) -> Vec<history::EncryptedDiffRow> {
    steps(prepared)
        .iter()
        .filter_map(|step| match step {
            ChildRevisionStep::StoreEmbedDiff {
                local_row,
                confirmed_row,
                ..
            } => Some(if confirmed {
                confirmed_row.clone()
            } else {
                local_row.clone()
            }),
            ChildRevisionStep::StoreEmbed { .. } => None,
        })
        .collect()
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.same-embed-new-version
#[tokio::test]
async fn child_revision_writes_base_head_and_history_in_order_under_the_parent_key() {
    let w = wire();
    let mut session = session(&w).await;
    let head = v1_head(&mut session, &w).await;
    let (image, parent, chat) = (id(&w, "image"), id(&w, "parent_1"), id(&w, "chat"));
    let prepared = session
        .plan_child_revision(data(&w["v2_event"]), Some(&head), Vec::new())
        .unwrap()
        .finish(1_790_000_102_000)
        .await
        .unwrap();
    let written = steps(&prepared);
    assert_eq!(written.len(), 3);

    let (role, base, base_payload) = diff(&written[0]);
    assert_eq!(
        (role, base.version_number, base.encrypted_patch.as_deref()),
        (RevisionRowRole::BaseSnapshot, 1, None)
    );
    assert_eq!(
        decrypt(&session, parent, &json!(base.encrypted_snapshot)),
        w["content"]["v1"].as_str().unwrap()
    );
    assert_eq!(base_payload["encrypted_patch"], Value::Null);
    assert_eq!(
        base_payload["hashed_user_id"],
        json!(hash_id(id(&w, "user")))
    );

    let payload = store(&written[1]);
    assert_eq!(payload, prepared.store_payload.as_ref().unwrap());
    // Kept identity: creating message (not the changing one), chat, parent, type ciphertext.
    assert_eq!(
        payload["hashed_message_id"],
        json!(hash_id(w["ids"]["messages"][0].as_str().unwrap()))
    );
    assert_eq!(payload["hashed_chat_id"], json!(hash_id(chat)));
    assert_eq!(payload["hashed_chat_id"], head["hashed_chat_id"]);
    assert_eq!(payload["parent_embed_id"], json!(parent));
    assert_eq!(payload["embed_id"], json!(image));
    assert_eq!(payload["version_number"], json!(2));
    assert_eq!(payload["encrypted_type"], head["encrypted_type"]);
    assert!(payload.get("root_embed_id").is_none());
    assert_eq!(
        decrypt(&session, parent, &payload["encrypted_content"]),
        w["content"]["v2"].as_str().unwrap()
    );
    assert!(prepared.server_keys.is_none() && prepared.local_key_wrappers.is_empty());
    assert_eq!(
        prepared.local_entry["hashed_message_id"],
        head["hashed_message_id"]
    );
    assert_eq!(prepared.key_cache_embed_ids, vec![image.to_owned()]);
    assert!(prepared.sealed_history);

    let (role, row, row_payload) = diff(&written[2]);
    assert_eq!(
        (role, row.version_number, row.encrypted_patch.as_deref()),
        (RevisionRowRole::History, 2, None)
    );
    assert_eq!(
        decrypt(&session, parent, &row_payload["encrypted_snapshot"]),
        w["content"]["v2"].as_str().unwrap()
    );

    let json = serde_json::to_value(&prepared).unwrap();
    let ops: Vec<&str> = json["child_revision"]["steps"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| s["op"].as_str().unwrap())
        .collect();
    assert_eq!(ops, ["store_embed_diff", "store_embed", "store_embed_diff"]);
    assert_eq!(json["child_revision"]["steps"][0]["role"], "base_snapshot");
    assert_eq!(json["child_revision"]["base_version"], 1);

    // A replay with the stored rows reuses their ciphertext byte for byte.
    let existing = vec![base.clone(), row.clone()];
    let replay = session
        .plan_child_revision(data(&w["v2_event"]), Some(&head), existing)
        .unwrap()
        .finish(1_790_000_103_000)
        .await
        .unwrap();
    assert_eq!(diff(&steps(&replay)[0]).1, base);
    assert_eq!(diff(&steps(&replay)[2]).1, row);
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.same-embed-new-version
#[tokio::test]
async fn base_snapshot_is_written_only_when_required() {
    let w = wire();
    let mut session = session(&w).await;
    let v1 = v1_head(&mut session, &w).await;
    let v2 = session
        .plan_child_revision(data(&w["v2_event"]), Some(&v1), Vec::new())
        .unwrap()
        .finish(1_790_000_102_000)
        .await
        .unwrap();
    let v3 = session
        .plan_child_revision(data(&w["v3_event"]), Some(&confirmed_head(&v2)), Vec::new())
        .unwrap()
        .finish(1_790_000_103_000)
        .await
        .unwrap();
    let steps = steps(&v3);
    assert_eq!(steps.len(), 2);
    assert_eq!(store(&steps[0])["version_number"], json!(3));
    assert_eq!(
        store(&steps[0])["hashed_message_id"],
        v1["hashed_message_id"]
    );
    assert_eq!(diff(&steps[1]).0, RevisionRowRole::History);
    assert_eq!(diff(&steps[1]).1.version_number, 3);
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.same-embed-new-version
#[tokio::test]
async fn child_without_revision_keeps_the_ordinary_write() {
    let w = wire();
    let mut session = session(&w).await;
    let prepared = session
        .plan_stream_completion(data(&w["v1_event"]))
        .unwrap()
        .finish(1_790_000_101_000)
        .await
        .unwrap();
    assert!(!prepared.sealed_history && prepared.child_revision.is_none());
    assert!(
        serde_json::to_value(&prepared)
            .unwrap()
            .get("child_revision")
            .is_none()
    );
    assert_eq!(
        prepared.local_entry["hashed_message_id"],
        json!(hash_id(w["ids"]["messages"][0].as_str().unwrap()))
    );
    // A child at version > 1 without `revision` stays unsealed, as today.
    let mut legacy = w["v2_event"].clone();
    legacy.as_object_mut().unwrap().remove("revision");
    let legacy = data(&legacy);
    assert!(!legacy.sealed_history() && legacy.child_revision().unwrap().is_none());
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.same-embed-new-version
#[tokio::test]
async fn child_revision_fails_closed() {
    let w = wire();
    let mut session = session(&w).await;
    let v1 = v1_head(&mut session, &w).await;
    let plan = |s: &mut EmbedWriteSession, event: &Value, head: Option<&Value>| {
        s.plan_child_revision(data(event), head, Vec::new())
            .map(|_| ())
            .map_err(code)
    };
    assert_eq!(
        session
            .plan_stream_completion(data(&w["v2_event"]))
            .map(|_| ())
            .map_err(code),
        Err("embed_revision_head_required")
    );
    assert_eq!(
        plan(&mut session, &w["v2_event"], None),
        Err("embed_revision_head_missing")
    );
    assert_eq!(
        plan(&mut session, &w["v3_event"], Some(&v1)),
        Err("embed_revision_base_mismatch")
    );
    let mut reparented = v1.clone();
    reparented["parent_embed_id"] = json!(id(&w, "parent_2"));
    assert_eq!(
        plan(&mut session, &w["v2_event"], Some(&reparented)),
        Err("embed_revision_head_mismatch")
    );
    let mut no_message = v1.clone();
    no_message
        .as_object_mut()
        .unwrap()
        .remove("hashed_message_id");
    assert_eq!(
        plan(&mut session, &w["v2_event"], Some(&no_message)),
        Err("embed_revision_head_mismatch")
    );
    let mut skipped = w["v2_event"].clone();
    skipped["revision"]["base_version"] = json!(2);
    assert_eq!(plan(&mut session, &skipped, Some(&v1)), Err("protocol"));
    let mut root = w["v2_event"].clone();
    root.as_object_mut().unwrap().remove("parent_embed_id");
    assert_eq!(
        StreamedEmbedData::from_value(root)
            .unwrap()
            .child_revision()
            .map(|_| ())
            .map_err(code),
        Err("protocol")
    );
    let mut two_rows = w["v2_event"].clone();
    two_rows["version_history_rows"] = json!([
        w["v2_event"]["version_history_rows"][0],
        w["v2_event"]["version_history_rows"][0]
    ]);
    let planned = session
        .plan_child_revision(data(&two_rows), Some(&v1), Vec::new())
        .unwrap();
    assert_eq!(
        planned.finish(1).await.map(|_| ()).map_err(code),
        Err("protocol")
    );

    // A base head whose own revision is still unconfirmed blocks the next change.
    let v2 = session
        .plan_child_revision(data(&w["v2_event"]), Some(&v1), Vec::new())
        .unwrap()
        .finish(2)
        .await
        .unwrap();
    assert_eq!(
        plan(&mut session, &w["v3_event"], Some(&v2.local_entry)),
        Err("embed_revision_base_mismatch")
    );
    // A stored v1 row with other plaintext is a conflict, never overwritten.
    let other = history::encrypt_streamed_row(
        &json!({"embed_id": id(&w, "image"), "version_number": 1, "snapshot": "other"}),
        &session
            .with_embed_key(id(&w, "parent_1"), |k| Ok(*k))
            .unwrap(),
        1,
        &mut OsNonces,
    )
    .unwrap()
    .unwrap();
    let planned = session
        .plan_child_revision(data(&w["v2_event"]), Some(&v1), vec![other])
        .unwrap();
    assert_eq!(
        planned.finish(3).await.map(|_| ()).map_err(code),
        Err("conflict")
    );

    // Without the parent key nothing is planned (no new key for the child).
    let f = ts();
    let mut fresh = EmbedWriteSession::new(MasterCapability::from_browser_raw(key(
        &f["keys"]["master_b64"],
    )));
    assert_eq!(
        plan(&mut fresh, &w["v2_event"], Some(&v1)),
        Err("embed_parent_key_pending")
    );
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.message-shows-its-version
#[test]
fn each_message_shows_the_latest_pinned_version_up_to_it() {
    let w = wire();
    let messages: Vec<MessageParents> = serde_json::from_value(w["parents"].clone()).unwrap();
    let versions = pinned::versions_by_message(&messages, id(&w, "image")).unwrap();
    let shown: Vec<(i64, bool)> = versions
        .iter()
        .map(|v| (v.version, v.pinned_here))
        .collect();
    // m1 created v1, m2 pinned v2, m3 has no image (still v2), m4 pinned v3.
    assert_eq!(shown, [(1, false), (2, true), (2, false), (3, true)]);
    assert_eq!(
        versions[2].message_id,
        w["ids"]["messages"][2].as_str().unwrap()
    );
    let pins =
        pinned::pinned_embeds(w["parents"][1]["parent_contents"][0].as_str().unwrap()).unwrap();
    assert_eq!(
        pins,
        [PinnedEmbed {
            embed_id: id(&w, "image").into(),
            version: 2,
            embed_ref: Some("sunset-a1b".into()),
            previous_version: Some(1)
        }]
    );
    assert!(
        pinned::versions_by_message(&messages, "another-image")
            .unwrap()
            .iter()
            .all(|v| v.version == 1 && !v.pinned_here)
    );
    assert!(matches!(
        pinned::pinned_embeds("pinned_embeds: 3"),
        Err(Error::Protocol)
    ));
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.message-shows-its-version
#[tokio::test]
async fn version_content_reads_head_or_snapshot_row() {
    let w = wire();
    let mut session = session(&w).await;
    let v1 = v1_head(&mut session, &w).await;
    let v2 = session
        .plan_child_revision(data(&w["v2_event"]), Some(&v1), Vec::new())
        .unwrap()
        .finish(2)
        .await
        .unwrap();
    let v3 = session
        .plan_child_revision(data(&w["v3_event"]), Some(&confirmed_head(&v2)), Vec::new())
        .unwrap()
        .finish(3)
        .await
        .unwrap();
    let mut rows: Vec<Value> = Vec::new();
    for prepared in [&v2, &v3] {
        for step in steps(prepared) {
            if let ChildRevisionStep::StoreEmbedDiff { local_row, .. } = step {
                rows.push(serde_json::to_value(local_row).unwrap());
            }
        }
    }
    let head = &v3.local_entry;
    let image = id(&w, "image");
    let read = |k: i64, rows: &[Value]| {
        session
            .embed_version_content(image, k, head, rows)
            .map(|c| c.as_str().to_owned())
            .map_err(code)
    };
    for (k, name) in [(1, "v1"), (2, "v2"), (3, "v3")] {
        assert_eq!(
            read(k, &rows).unwrap(),
            w["content"][name].as_str().unwrap(),
            "version {k}"
        );
    }
    assert_eq!(pinned::head_version(head).unwrap(), 3);
    assert_eq!(read(4, &rows), Err("embed_version_unavailable"));
    let without_v2: Vec<Value> = rows
        .iter()
        .filter(|r| r["version_number"] != 2)
        .cloned()
        .collect();
    assert_eq!(read(2, &without_v2), Err("embed_version_unavailable"));
    // Head reads need no rows at all.
    assert_eq!(read(3, &[]).unwrap(), w["content"]["v3"].as_str().unwrap());
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.same-embed-new-version
#[tokio::test]
async fn conflicting_row_is_adopted_only_with_the_same_plaintext() {
    let w = wire();
    let mut session = session(&w).await;
    let v1 = v1_head(&mut session, &w).await;
    let v2 = session
        .plan_child_revision(data(&w["v2_event"]), Some(&v1), Vec::new())
        .unwrap()
        .finish(2)
        .await
        .unwrap();
    let (_, local, _) = diff(&steps(&v2)[2]);
    let (image, parent) = (id(&w, "image"), id(&w, "parent_1"));
    let encrypt = |text: &str| {
        session
            .with_embed_key(parent, |k| keys::encrypt_text(text, k, None, &mut OsNonces))
            .unwrap()
    };
    let page = |snapshot: String| {
        json!({"embed_id": image, "version_number": 2, "rows": [
        {"version_number": 2, "encrypted_snapshot": snapshot, "encrypted_patch": null, "created_at": 1_790_000_102}]})
    };
    // Another tab's ciphertext of the same content becomes the local row.
    let theirs = encrypt(w["content"]["v2"].as_str().unwrap());
    let adopted = session
        .adopt_child_revision_row(local, &page(theirs.clone()), 9)
        .unwrap();
    assert_eq!(
        (
            adopted.version_number,
            adopted.encrypted_snapshot.as_deref(),
            adopted.created_at
        ),
        (2, Some(theirs.as_str()), 1_790_000_102)
    );
    assert_ne!(adopted.encrypted_snapshot, local.encrypted_snapshot);
    let other = session
        .adopt_child_revision_row(local, &page(encrypt("other content")), 9)
        .map_err(code);
    assert_eq!(other.map(|_| ()), Err("embed_revision_row_diverged"));
    let wrong_version = json!({"embed_id": image, "version_number": 3, "rows": []});
    assert_eq!(
        session
            .adopt_child_revision_row(local, &wrong_version, 9)
            .map(|_| ())
            .map_err(code),
        Err("protocol")
    );
}

fn roles(prepared: &PreparedEmbedWrite) -> Vec<&'static str> {
    steps(prepared)
        .iter()
        .map(|step| match step {
            ChildRevisionStep::StoreEmbedDiff {
                role: RevisionRowRole::BaseSnapshot,
                ..
            } => "base",
            ChildRevisionStep::StoreEmbedDiff {
                role: RevisionRowRole::History,
                ..
            } => "history",
            ChildRevisionStep::StoreEmbed { .. } => "head",
        })
        .collect()
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.same-embed-new-version
#[tokio::test]
async fn resumed_revision_plans_only_the_writes_still_missing() {
    let w = wire();
    let mut session = session(&w).await;
    let v1 = v1_head(&mut session, &w).await;
    let event = &w["v2_event"];
    let first = session
        .plan_child_revision(data(event), Some(&v1), Vec::new())
        .unwrap()
        .finish(2)
        .await
        .unwrap();
    assert_eq!(roles(&first), ["base", "head", "history"]);
    assert_eq!(first.local_entry[revision::PENDING_HEAD_MARKER], json!(2));
    assert!(
        confirmed_head(&first)
            .get(revision::PENDING_HEAD_MARKER)
            .is_none()
    );
    let (unsent, sent) = (local_rows(&first, false), local_rows(&first, true));
    let first_head_payload = store(&steps(&first)[1]).clone();

    // Crash after the local head store, before its send (base row sent).
    let resumed = session
        .plan_child_revision(data(event), Some(&first.local_entry), vec![sent[0].clone()])
        .unwrap()
        .finish(3)
        .await
        .unwrap();
    assert_eq!(roles(&resumed), ["head", "history"]);
    // The resent head is byte-identical (stored ciphertext, kept identity).
    assert_eq!(store(&steps(&resumed)[0]), &first_head_payload);

    // Crash before the base send as well: the stored base row is resent first.
    let resumed = session
        .plan_child_revision(
            data(event),
            Some(&first.local_entry),
            vec![unsent[0].clone()],
        )
        .unwrap()
        .finish(3)
        .await
        .unwrap();
    assert_eq!(roles(&resumed), ["base", "head", "history"]);
    assert_eq!(diff(&steps(&resumed)[0]).1, &unsent[0]);
    // Head already at N+1 without the base row: the base cannot be rebuilt.
    let lost = session
        .plan_child_revision(data(event), Some(&first.local_entry), Vec::new())
        .unwrap();
    assert_eq!(
        lost.finish(3).await.map(|_| ()).map_err(code),
        Err("embed_revision_base_unavailable")
    );

    // Crash after the head send, before the history row (stored, unsent).
    let head = confirmed_head(&first);
    let resumed = session
        .plan_child_revision(
            data(event),
            Some(&head),
            vec![sent[0].clone(), unsent[1].clone()],
        )
        .unwrap()
        .finish(4)
        .await
        .unwrap();
    assert_eq!(roles(&resumed), ["history"]);
    assert_eq!(diff(&steps(&resumed)[0]).1, &unsent[1]);

    // Full replay: head and both rows confirmed.
    let replay = session
        .plan_child_revision(data(event), Some(&head), sent.clone())
        .unwrap();
    assert_eq!(
        replay.finish(5).await.map(|_| ()).map_err(code),
        Err("embed_revision_already_applied")
    );
    // Head at N, base already confirmed (another device sent it): skip the base.
    let fresh = session
        .plan_child_revision(data(event), Some(&v1), vec![sent[0].clone()])
        .unwrap()
        .finish(6)
        .await
        .unwrap();
    assert_eq!(roles(&fresh), ["head", "history"]);
}

// contract-test: supporting surface=sdks.rust assertions=images-generate.revision.message-shows-its-version
#[tokio::test]
async fn fetched_version_page_is_cached_as_confirmed_local_rows() {
    let w = wire();
    let mut session = session(&w).await;
    let v1 = v1_head(&mut session, &w).await;
    let v2 = session
        .plan_child_revision(data(&w["v2_event"]), Some(&v1), Vec::new())
        .unwrap()
        .finish(2)
        .await
        .unwrap();
    let head = confirmed_head(&v2);
    let image = id(&w, "image");
    let base = local_rows(&v2, false)[0].clone();
    let page = json!({"embed_id": image, "version_number": 1, "rows": [
        {"version_number": 1, "encrypted_snapshot": base.encrypted_snapshot, "encrypted_patch": null, "created_at": 1_790_000_101}]});
    let cached = session.cache_version_page(image, &head, &page, 9).unwrap();
    assert_eq!(cached.len(), 1);
    assert!(cached[0].server_confirmed);
    assert_eq!(
        (cached[0].id.as_str(), cached[0].created_at),
        (format!("{image}_v1").as_str(), 1_790_000_101)
    );
    let rows = vec![serde_json::to_value(&cached[0]).unwrap()];
    let content = session
        .embed_version_content(image, 1, &head, &rows)
        .unwrap();
    assert_eq!(content.as_str(), w["content"]["v1"].as_str().unwrap());

    let foreign = keys::encrypt_text("x", &[7u8; 32], None, &mut OsNonces).unwrap();
    let bad = |page: Value| {
        session
            .cache_version_page(image, &head, &page, 9)
            .map(|_| ())
            .map_err(code)
    };
    assert_eq!(
        bad(
            json!({"embed_id": image, "version_number": 1, "rows": [{"version_number": 1, "encrypted_snapshot": foreign}]})
        ),
        Err("crypto")
    );
    assert_eq!(
        bad(json!({"embed_id": image, "version_number": 3, "rows": []})),
        Err("protocol")
    );
    assert_eq!(
        bad(json!({"embed_id": "other", "version_number": 1, "rows": []})),
        Err("protocol")
    );
    assert_eq!(
        bad(json!({"embed_id": image, "version_number": 1, "rows": [{"version_number": 1}]})),
        Err("protocol")
    );
}
