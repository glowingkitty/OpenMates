// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
use super::*;

const TEAM: &str = "aaaaaaaa-1111-4111-8111-aabbccddeeff";

#[test]
fn move_type_parsing_accepts_exactly_the_npm_names() {
    for name in ["chat", "project", "task", "plan", "workflow"] {
        assert_eq!(WorkspaceMoveType::parse(name).unwrap().as_str(), name);
    }
    for name in ["Chat", "projects", "", " task"] {
        assert!(WorkspaceMoveType::parse(name).is_none(), "{name:?}");
    }
    assert_eq!(
        WorkspaceMoveType::Task.route(TEAM).unwrap(),
        format!("/v1/user-tasks/{TEAM}/move")
    );
    assert!(WorkspaceMoveType::Plan.route("../x").is_err());
}

#[test]
fn project_payload_rekeys_the_slug_index_and_wraps_the_project_key_for_the_team() {
    let (project_key, team_key) = ([3u8; 32], [9u8; 32]);
    let payload = move_payload(
        TEAM,
        1_700_000_000,
        "Q3 Launch",
        &project_key,
        &team_key,
        Some(&project_key),
    )
    .unwrap();
    assert_eq!(payload["team_id"], TEAM);
    assert_eq!(payload["confirmed"], true);
    assert_eq!(payload["moved_at"], 1_700_000_000u64);
    let slug = crypto::normalize_object_slug("Q3 Launch").unwrap();
    assert_eq!(
        crypto::decrypt_combined(payload["encrypted_slug"].as_str().unwrap(), &project_key)
            .unwrap(),
        slug
    );
    assert_eq!(
        payload["slug_lookup_hash"],
        crypto::object_slug_lookup_hash(&slug, &team_key).unwrap()
    );
    let wrapper = &payload["team_project_key_wrapper"];
    assert_eq!(wrapper["key_type"], "team");
    assert_eq!(wrapper["hashed_team_id"], hash(TEAM));
    assert_eq!(wrapper["team_key_epoch"], 1);
    assert_eq!(wrapper["wrapper_version"], 1);
    assert_eq!(wrapper["created_at"], 1_700_000_000u64);
    let unwrapped = crypto::decrypt_bytes(
        wrapper["encrypted_project_key"].as_str().unwrap(),
        &team_key,
    )
    .unwrap();
    assert_eq!(unwrapped.as_slice(), project_key.as_slice());
    // npm encryptWithAesGcmCombined layout: base64(IV || ciphertext+tag), no frame.
    let raw = base64::Engine::decode(
        &base64::engine::general_purpose::STANDARD,
        wrapper["encrypted_project_key"].as_str().unwrap(),
    )
    .unwrap();
    assert_eq!(raw.len(), 12 + 32 + 16);
}

#[test]
fn slugless_objects_send_no_slug_fields_and_non_projects_no_wrapper() {
    let payload = move_payload(TEAM, 5, "", &[1; 32], &[2; 32], None).unwrap();
    assert_eq!(
        payload,
        json!({"team_id":TEAM,"confirmed":true,"moved_at":5})
    );
}

#[test]
fn move_result_spreads_the_server_response_over_success() {
    assert_eq!(
        move_result(&json!({"moved":true,"team_id":TEAM})),
        json!({"success":true,"moved":true,"team_id":TEAM})
    );
    assert_eq!(move_result(&json!({})), json!({"success":true}));
}
