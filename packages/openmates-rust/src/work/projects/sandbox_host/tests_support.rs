//! Test builders: heads made with the client's own encrypt functions.
use super::*;
use crate::client::upload::toon_encode::encode_fields;
use zeroize::Zeroizing;

pub(super) const PROJECT: &str = "11111111-1111-4111-8111-111111111111";
pub(super) const CHAT: &str = "22222222-2222-4222-8222-222222222222";
pub(super) const EMBED_KEY: [u8; 32] = [9; 32];

pub(super) fn project_key() -> [u8; 32] {
    std::array::from_fn(|i| i as u8 + 1)
}

pub(super) fn embed_id(path: &str) -> String {
    hosted_file_identity(&project_key(), path, HostedIdentityKind::Embed)
        .unwrap_or_else(|_| "33333333-3333-4333-8333-333333333333".to_owned())
}

pub(super) fn wrapper(embed_key: &[u8; 32]) -> Value {
    json!({"key_type": "project", "hashed_project_id": hash(PROJECT),
        "encrypted_embed_key": crypto::server_fields::encrypt_bytes(embed_key, &project_key(), &[]).unwrap()})
}

/// A server head projection of `path` holding `text` at `version`.
pub(super) fn head(path: &str, text: &str, version: u64) -> Value {
    let encoded = encode_fields(&[
        ("type", json!("code")),
        ("language", json!("text")),
        ("filename", json!(path)),
        ("code", json!(text)),
        ("version_number", json!(version)),
        ("status", json!("finished")),
        ("line_count", json!(text.split('\n').count())),
    ])
    .unwrap();
    json!({
        "path": path,
        "project_item_id": hosted_file_identity(&project_key(), path, HostedIdentityKind::Item).ok(),
        "embed": {"embed_id": embed_id(path), "version_number": version,
            "encrypted_content": seal(&encoded, &EMBED_KEY).unwrap()},
        "embed_keys": [wrapper(&EMBED_KEY)],
        "has_initial_history": true,
    })
}

/// The head a client would fetch after the server committed `revision`.
pub(super) fn head_of(revision: &Revision, new_version: u64) -> Value {
    let tx = &revision.transaction;
    let key_row = match tx["create"]["key_wrappers"].as_array() {
        Some(rows) => rows.iter().find(|r| r["key_type"] == "project").unwrap().clone(),
        None => wrapper(&EMBED_KEY),
    };
    json!({
        "path": revision.path,
        "embed": {"embed_id": revision.embed_id, "version_number": new_version,
            "encrypted_content": tx["head"]["encrypted_content"]},
        "embed_keys": [{"key_type": "project", "hashed_project_id": hash(PROJECT),
            "encrypted_embed_key": key_row["encrypted_embed_key"]}],
        "has_initial_history": true,
    })
}

pub(super) fn new_tree(root: &std::path::Path) -> ProjectTree {
    let mut tree =
        ProjectTree::new(root.to_path_buf(), Zeroizing::new(project_key().to_vec())).unwrap();
    tree.set_project(PROJECT, None);
    tree.set_chat(CHAT, Some(Zeroizing::new([42; 32])));
    tree
}

pub(super) fn ten_lines() -> String {
    (1..=10).map(|n| format!("line {n}")).collect::<Vec<_>>().join("\n")
}
