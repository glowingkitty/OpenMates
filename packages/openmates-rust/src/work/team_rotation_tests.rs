//! Reading Team-scoped wrappers across a Team key rotation.

use super::*;
use crate::client::previous_team_keys;

const TEAM_ID: &str = "ccbbccdd-1111-4111-8111-aabbccddeeff";

/// A rotated Team (epoch 2): the previous-key chain holds the epoch-1 key.
fn rotated() -> (Key, Key, Vec<(u64, Key)>) {
    let old = crypto::random_key();
    let new = crypto::random_key();
    let chain = legacy_encrypt(
        &serde_json::to_vec(&json!([{
            "epoch":1,
            "key":base64::Engine::encode(&base64::engine::general_purpose::STANDARD, old.as_ref()),
        }]))
        .unwrap(),
        &new,
    )
    .unwrap();
    let previous = previous_team_keys(&chain, &new).unwrap();
    (old, new, previous)
}

#[test]
fn epoch_two_project_wrapper_reads_with_the_current_team_key() {
    let (_old, new, _previous) = rotated();
    let project_key = crypto::random_key();
    let mut raw = json!({"hashed_team_id":hash(TEAM_ID)});
    raw["key_wrappers"] = json!([{"key_type":"team","hashed_team_id":hash(TEAM_ID),"team_key_epoch":2,
        "encrypted_project_key":legacy_encrypt(project_key.as_ref(), &new).unwrap()}]);
    assert_eq!(
        *projects::project_key(&raw, &new, Some(TEAM_ID)).unwrap(),
        *project_key
    );
}

#[test]
fn epoch_one_wrapper_reads_through_the_previous_key_chain() {
    let (old, new, previous) = rotated();
    let item_key = crypto::random_key();
    let wrapped = legacy_encrypt(item_key.as_ref(), &old).unwrap();
    assert!(open_team_wrapper(&wrapped, 1, &new, &[]).is_err());
    assert_eq!(
        open_team_wrapper(&wrapped, 1, &new, &previous).unwrap(),
        item_key.to_vec()
    );
    // A wrapper written after the rotation carries the current key.
    let fresh = legacy_encrypt(item_key.as_ref(), &new).unwrap();
    assert_eq!(
        open_team_wrapper(&fresh, 2, &new, &previous).unwrap(),
        item_key.to_vec()
    );
    // A removed member's old key opens nothing at the current epoch.
    assert!(open_team_wrapper(&fresh, 2, &old, &[]).is_err());
}

#[test]
fn epoch_one_task_wrapper_decrypts_after_rotation_only_with_the_chain() {
    let (old, new, previous) = rotated();
    let team = "cccccccc-1111-4111-8111-aabbccddeeff";
    let raw = task_crypto::encrypt_create(
        &TaskCreate {
            title: "Before the rotation".into(),
            ..Default::default()
        },
        &[7; 32],
        &old,
        Some(team),
    )
    .unwrap();
    assert!(matches!(
        task_crypto::decrypt(raw.clone(), &[7; 32], &new, Some(team), &[]),
        Err(Error::Crypto)
    ));
    let task = task_crypto::decrypt(raw, &[7; 32], &new, Some(team), &previous).unwrap();
    assert_eq!(task.public["title"], "Before the rotation");
}

#[test]
fn new_task_and_moved_project_wrappers_carry_the_rotated_epoch() {
    let (_old, new, previous) = rotated();
    let team = "cccccccc-1111-4111-8111-aabbccddeeff";
    let mut raw = task_crypto::encrypt_create(
        &TaskCreate {
            title: "After the rotation".into(),
            ..Default::default()
        },
        &[7; 32],
        &new,
        Some(team),
    )
    .unwrap();
    stamp_team_epoch(&mut raw, 2);
    let wrapper = &raw["key_wrappers"][0];
    assert_eq!(wrapper["team_key_epoch"], 2);
    assert!(
        open_team_wrapper(
            string(wrapper, "encrypted_task_key").unwrap(),
            2,
            &new,
            &previous
        )
        .is_ok()
    );
    let task = task_crypto::decrypt(raw, &[7; 32], &new, Some(team), &previous).unwrap();
    assert_eq!(task.public["title"], "After the rotation");

    let mut moved = team_move::move_payload(team, 5, "", &[1; 32], &new, Some(&[1; 32])).unwrap();
    stamp_team_epoch(&mut moved, 2);
    assert_eq!(moved["team_project_key_wrapper"]["team_key_epoch"], 2);
}
