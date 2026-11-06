//! Worker-side embed key resolution over the TypeScript-generated wrapper
//! vectors (tests/crypto_fixtures/ts_embed_writes.json): master wrapper, chat
//! wrapper, wrong chat key, legacy child inheritance and the early HKDF key.
use super::keys;
use super::*;
use crate::crypto::{Key, master::MasterCapability};
use crate::error::Error;
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::Value;

fn fixture() -> Value {
    serde_json::from_str(include_str!(
        "../../tests/crypto_fixtures/ts_embed_writes.json"
    ))
    .unwrap()
}
fn key(value: &Value) -> Key {
    keys::key_from(&STANDARD.decode(value.as_str().unwrap()).unwrap()).unwrap()
}
fn session(f: &Value) -> EmbedWriteSession {
    EmbedWriteSession::new(MasterCapability::from_browser_raw(key(
        &f["keys"]["master_b64"],
    )))
}
fn wrappers(case: &Value) -> Vec<Value> {
    case["expected"]["local_key_wrappers"]
        .as_array()
        .unwrap()
        .clone()
}
fn text<'a>(value: &'a Value, path: &[&str]) -> &'a str {
    path.iter()
        .fold(value, |value, key| &value[*key])
        .as_str()
        .unwrap()
}

/// Resolves the planned candidates in order and installs the first that opens (the adapter loop).
async fn resolve(session: &mut EmbedWriteSession, lookup: KeyLookup) -> Result<bool, Vec<String>> {
    match lookup {
        KeyLookup::Loaded => Ok(true),
        KeyLookup::NoWrappers => Ok(false),
        KeyLookup::Wrappers {
            candidates,
            pending_chat_hashes,
        } => {
            for candidate in candidates {
                if let Ok(adopted) = candidate.resolve().await {
                    session.install(adopted);
                    return Ok(true);
                }
            }
            Err(pending_chat_hashes)
        }
    }
}

fn assert_opens_typescript_content(session: &EmbedWriteSession, case: &Value) {
    let embed_id = text(case, &["input", "embed_id"]);
    let material = session.embed_key_material(embed_id).unwrap();
    assert_eq!(
        *material,
        *key(&case["embed_key_b64"]),
        "{embed_id}: resolved key"
    );
    let content = keys::decrypt_text(
        text(case, &["expected", "local_entry", "encrypted_content"]),
        &material,
        None,
    )
    .unwrap();
    assert_eq!(content.as_str(), text(case, &["input", "content"]));
}

#[tokio::test]
async fn master_wrapper_resolves_the_typescript_embed_key_first() {
    let f = fixture();
    let case = &f["finalized"][0];
    let mut session = session(&f);
    let hashed_chat = keys::hash_id(text(case, &["input", "chat_id"]));
    let lookup = session.plan_key_lookup(
        text(case, &["input", "embed_id"]),
        Some(&hashed_chat),
        &wrappers(case),
    );
    let KeyLookup::Wrappers {
        candidates,
        pending_chat_hashes,
    } = &lookup
    else {
        panic!("wrappers expected")
    };
    assert_eq!(
        candidates.len(),
        1,
        "only the master wrapper is usable without the chat key"
    );
    assert_eq!(pending_chat_hashes, &vec![hashed_chat.clone()]);
    assert_eq!(resolve(&mut session, lookup).await, Ok(true));
    assert_opens_typescript_content(&session, case);
    assert!(matches!(
        session.plan_key_lookup(text(case, &["input", "embed_id"]), None, &[]),
        KeyLookup::Loaded
    ));
}

#[tokio::test]
async fn chat_wrapper_needs_the_validated_chat_key_and_then_resolves() {
    let f = fixture();
    let case = &f["finalized"][3];
    let rows = wrappers(case);
    assert!(
        rows.iter().all(|row| row["key_type"] == "chat"),
        "local-only vector carries only the chat wrapper"
    );
    let (embed_id, chat_id) = (
        text(case, &["input", "embed_id"]),
        text(case, &["input", "chat_id"]),
    );
    let hashed_chat = keys::hash_id(chat_id);
    let mut session = session(&f);
    let lookup = session.plan_key_lookup(embed_id, Some(&hashed_chat), &rows);
    let pending = resolve(&mut session, lookup).await;
    assert_eq!(
        pending,
        Err(vec![hashed_chat.clone()]),
        "no chat key: pending on that chat, no substitute key"
    );
    session
        .install_chat_key(chat_id, &*key(&f["keys"]["chat_key_b64"]))
        .unwrap();
    let lookup = session.plan_key_lookup(embed_id, Some(&hashed_chat), &rows);
    assert_eq!(resolve(&mut session, lookup).await, Ok(true));
    assert_opens_typescript_content(&session, case);
    session.forget_chat(chat_id);
    assert!(
        !session.has_embed_key(embed_id),
        "chat-adopted embed keys are forgotten with their chat"
    );
}

#[tokio::test]
async fn chat_wrapper_with_the_wrong_chat_key_stays_unavailable() {
    let f = fixture();
    let case = &f["finalized"][0];
    let rows: Vec<Value> = wrappers(case)
        .into_iter()
        .filter(|row| row["key_type"] == "chat")
        .collect();
    let (embed_id, chat_id) = (
        text(case, &["input", "embed_id"]),
        text(case, &["input", "chat_id"]),
    );
    let mut session = session(&f);
    session
        .install_chat_key(chat_id, &*key(&f["keys"]["other_chat_key_b64"]))
        .unwrap();
    let lookup = session.plan_key_lookup(embed_id, Some(&keys::hash_id(chat_id)), &rows);
    assert_eq!(resolve(&mut session, lookup).await, Err(vec![]));
    assert!(matches!(
        session.embed_key_material(embed_id),
        Err(Error::Unavailable {
            code: "embed_key_unavailable",
            ..
        })
    ));
}

#[tokio::test]
async fn legacy_child_without_wrappers_inherits_the_resolved_parent_key() {
    let f = fixture();
    let (parent, child) = (&f["finalized"][0], &f["finalized"][2]);
    let child_id = text(child, &["input", "embed_id"]);
    let parent_id = text(child, &["input", "parent_embed_id"]);
    assert_eq!(parent_id, text(parent, &["input", "embed_id"]));
    let mut session = session(&f);
    assert!(matches!(
        session.plan_key_lookup(child_id, None, &[]),
        KeyLookup::NoWrappers
    ));
    assert!(
        !session.inherit_parent_key(child_id, parent_id),
        "parent key not loaded yet"
    );
    let lookup = session.plan_key_lookup(parent_id, None, &wrappers(parent));
    assert_eq!(resolve(&mut session, lookup).await, Ok(true));
    assert!(
        !session.inherit_parent_key(parent_id, parent_id),
        "self reference refused"
    );
    assert!(session.inherit_parent_key(child_id, parent_id));
    assert_opens_typescript_content(&session, child);
}

#[test]
fn early_parent_key_is_the_typescript_hkdf_derivation() {
    let f = fixture();
    let case = &f["derivation"][0];
    let embed_id = text(case, &["embed_id"]);
    let mut session = session(&f);
    assert!(
        !session.derive_early_parent_key(embed_id, "chat-1").unwrap(),
        "no chat key: derived later"
    );
    session
        .install_chat_key("chat-1", &*key(&case["chat_key_b64"]))
        .unwrap();
    assert!(session.derive_early_parent_key(embed_id, "chat-1").unwrap());
    assert_eq!(
        *session.embed_key_material(embed_id).unwrap(),
        *key(&case["embed_key_b64"])
    );
    assert!(matches!(
        session.install_chat_key("", &[0u8; 32]),
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        session.install_chat_key("chat-2", &[0u8; 16]),
        Err(Error::Crypto)
    ));
}
