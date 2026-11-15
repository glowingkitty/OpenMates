use super::*;
use serde_json::json;

fn key() -> [u8; 32] {
    std::array::from_fn(|i| i as u8 + 7)
}

fn snapshot(number: u64, text: &str) -> Value {
    json!({
        "version_number": number,
        "encrypted_snapshot": crypto::server_fields::encrypt_text(text, &key(), &[]).unwrap(),
    })
}

#[test]
fn replay_returns_the_text_of_the_requested_version() {
    let rows = [snapshot(1, "a\n"), snapshot(2, "b\n")];
    assert_eq!(*replay_rows(&rows[..1], &key(), 1).unwrap(), "a\n");
    assert_eq!(*replay_rows(&rows, &key(), 2).unwrap(), "b\n");
}

#[test]
fn replay_rejects_gapped_short_and_empty_chains() {
    let gapped = [snapshot(1, "a\n"), snapshot(3, "c\n")];
    assert_eq!(
        replay_rows(&gapped, &key(), 3).unwrap_err(),
        ReplayError::Core(Error::Protocol)
    );
    let rows = [snapshot(1, "a\n")];
    assert_eq!(
        replay_rows(&rows, &key(), 2).unwrap_err(),
        ReplayError::Core(Error::Protocol)
    );
    assert_eq!(
        replay_rows(&[], &key(), 1).unwrap_err(),
        ReplayError::Core(Error::Protocol)
    );
}

#[test]
fn replay_refuses_a_patch_row_without_a_snapshot_chain_start() {
    let patch_only = [json!({
        "version_number": 1,
        "encrypted_patch": crypto::server_fields::encrypt_text("x", &key(), &[]).unwrap(),
    })];
    assert_eq!(
        replay_rows(&patch_only, &key(), 1).unwrap_err(),
        ReplayError::Core(Error::Protocol)
    );
}

fn wrapped(embed_key: &[u8; 32], project: Option<&str>) -> Value {
    let mut row = json!({
        "key_type": "project",
        "encrypted_embed_key": crypto::server_fields::encrypt_bytes(embed_key, &key(), &[]).unwrap(),
    });
    if let Some(project) = project {
        row["hashed_project_id"] = json!(hash(project));
    }
    row
}

const PROJECT: &str = "11111111-1111-4111-8111-111111111111";
const EMBED: &str = "22222222-2222-4222-8222-222222222222";

#[test]
fn project_wrapper_opens_the_file_key_with_the_project_key() {
    let embed_key = [9u8; 32];
    let response = json!({
        "embed": {"embed_id": EMBED},
        "embed_keys": [{"key_type": "chat", "encrypted_embed_key": "x"}, wrapped(&embed_key, Some(PROJECT))],
    });
    let opened = project_wrapped_embed_key(&response, EMBED, PROJECT, &key()).unwrap();
    assert_eq!(opened.as_deref(), Some(&embed_key));
    let unhashed = json!({"embed": {"embed_id": EMBED}, "embed_keys": [wrapped(&embed_key, None)]});
    assert!(
        project_wrapped_embed_key(&unhashed, EMBED, PROJECT, &key())
            .unwrap()
            .is_some()
    );
}

#[test]
fn project_wrapper_read_skips_other_projects_and_refuses_other_embeds() {
    let other = "33333333-3333-4333-8333-333333333333";
    let response =
        json!({"embed": {"embed_id": EMBED}, "embed_keys": [wrapped(&[9u8; 32], Some(other))]});
    assert!(
        project_wrapped_embed_key(&response, EMBED, PROJECT, &key())
            .unwrap()
            .is_none()
    );
    let chat_only = json!({"embed": {"embed_id": EMBED}, "embed_keys": [{"key_type": "chat", "encrypted_embed_key": "x"}]});
    assert!(
        project_wrapped_embed_key(&chat_only, EMBED, PROJECT, &key())
            .unwrap()
            .is_none()
    );
    assert_eq!(
        project_wrapped_embed_key(&response, other, PROJECT, &key()).unwrap_err(),
        Error::Forbidden
    );
    let wrong_key = [1u8; 32];
    let mine =
        json!({"embed": {"embed_id": EMBED}, "embed_keys": [wrapped(&[9u8; 32], Some(PROJECT))]});
    assert_eq!(
        project_wrapped_embed_key(&mine, EMBED, PROJECT, &wrong_key).unwrap_err(),
        Error::Crypto
    );
}
