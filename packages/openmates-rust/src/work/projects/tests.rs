use super::*;
use crate::work::tasks::tests::{client, mock};
const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";
const TEAM: &str = "ccbbccdd-1111-4111-8111-aabbccddeeff";
fn input() -> ProjectCreate {
    ProjectCreate {
        project_id: Some(PROJECT.into()),
        name: "Private Project".into(),
        description: "Private description".into(),
        write_mode: Some(ProjectWriteMode::AlwaysAsk),
        ..Default::default()
    }
}
fn raw() -> Value {
    encode_create(&input(), &[8; 32], &[7; 32], None).unwrap()
}
#[test]
fn create_encrypts_required_focus_and_policy_without_private_wire_fields() {
    let raw = raw();
    for text in ["Private Project", "Private description"] {
        assert!(!raw.to_string().contains(text));
    }
    assert_eq!(raw["write_mode"], "always_ask");
    let focus_id = raw["default_focus_id"].as_str().unwrap();
    uuid(focus_id).unwrap();
    let settings: Value = serde_json::from_str(
        &crypto::decrypt_combined(raw["encrypted_settings"].as_str().unwrap(), &[8; 32]).unwrap(),
    )
    .unwrap();
    assert_eq!(settings["default_focus"]["focus_id"], focus_id);
    assert_eq!(
        decode(raw, zeroize::Zeroizing::new([8; 32]))
            .unwrap()
            .public["name"],
        "Private Project"
    );
    assert!(
        encode_create(
            &ProjectCreate {
                name: "Project".into(),
                ..Default::default()
            },
            &[8; 32],
            &[7; 32],
            None
        )
        .is_err()
    );
}
#[test]
fn project_scope_and_settings_reject_wrong_wrappers_and_focus_binding() {
    let mut raw = raw();
    raw["hashed_team_id"] = json!(hash(TEAM));
    assert!(matches!(
        project_key(&raw, &[7; 32], None),
        Err(Error::Forbidden)
    ));
    let wrapped = crypto::encrypt_bytes(&[8; 32], &[9; 32]).unwrap();
    raw["key_wrappers"] = json!([{"key_type":"team","hashed_team_id":hash(TEAM),"team_key_epoch":1,"encrypted_project_key":wrapped}]);
    assert_eq!(*project_key(&raw, &[9; 32], Some(TEAM)).unwrap(), [8; 32]);
    raw["key_wrappers"][0]["team_key_epoch"] = json!(2);
    assert!(matches!(
        project_key(&raw, &[9; 32], Some(TEAM)),
        Err(Error::Forbidden)
    ));
    let settings = json!({"encrypted_settings":raw["encrypted_settings"],"default_focus_id_hash":hash("other")});
    assert!(matches!(
        decode_settings(&settings, &[8; 32]),
        Err(Error::Forbidden)
    ));
}
#[tokio::test]
async fn explicit_rest_team_scope_uses_fresh_verified_team_key_independent_of_selected_chat_scope()
{
    let mut project = encode_create(&input(), &[8; 32], &[9; 32], Some(TEAM)).unwrap();
    project["hashed_team_id"] = json!(hash(TEAM));
    let wrapped = crypto::encrypt_bytes(&[9; 32], &[7; 32]).unwrap();
    let (api, server) = mock(vec![
        json!({"project":project}),
        json!({"team":{"team_id":TEAM,"encrypted_team_key":wrapped}}),
    ])
    .await;
    let mut client = client(&api);
    assert!(client.session().unwrap().active_team_id.is_none());
    let value = client
        .projects()
        .with_filters(ProjectFilters {
            team_id: Some(TEAM.into()),
            ..Default::default()
        })
        .show(PROJECT)
        .await
        .unwrap();
    assert_eq!(value["name"], "Private Project");
    assert!(client.session().unwrap().active_team_id.is_none());
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with(&format!("GET /v1/projects/{PROJECT}?team_id={TEAM} ")));
    assert!(requests[1].starts_with(&format!("GET /v1/teams/{TEAM} ")));
}
#[tokio::test]
async fn archived_selectors_and_destructive_confirmation_preserve_scope() {
    let mut project = raw();
    project["archived"] = json!(true);
    let (api, server) = mock(vec![json!({"projects":[project]})]).await;
    let mut client = client(&api);
    assert_eq!(
        client.projects().show("private-project").await.unwrap()["project_id"],
        PROJECT
    );
    assert!(server.await.unwrap()[0].starts_with("GET /v1/projects?include_archived=true "));
    assert!(matches!(
        client.projects().delete(PROJECT, false).await,
        Err(Error::Invalid(_))
    ));
}
