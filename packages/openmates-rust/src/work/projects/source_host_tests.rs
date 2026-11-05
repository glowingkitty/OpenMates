// Supporting SDK primitive/loopback coverage; no end-to-end or native execution claim.
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
use super::*;
use crate::client::{SourceHostAdapter, SourceHostOperation, SourceHostOptions};
use crate::work::tasks::tests::{client, mock};
const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";
const TEAM: &str = "ccbbccdd-1111-4111-8111-aabbccddeeff";
struct ReadAdapter;
impl SourceHostAdapter for ReadAdapter {
    fn implemented_capabilities(&self) -> Vec<ProjectSourceCapability> {
        vec![ProjectSourceCapability::Read]
    }
    fn supports_operation(&self, op: SourceHostOperation) -> bool {
        matches!(
            op,
            SourceHostOperation::List
                | SourceHostOperation::ReadText
                | SourceHostOperation::ReadImageChunk
                | SourceHostOperation::ReadFileChunk
        )
    }
}
fn project() -> Value {
    let mut raw = encode_create(
        &ProjectCreate {
            name: "Private".into(),
            project_id: Some(PROJECT.into()),
            write_mode: Some(ProjectWriteMode::AlwaysAsk),
            ..Default::default()
        },
        &[8; 32],
        &[9; 32],
        Some(TEAM),
    )
    .unwrap();
    raw["hashed_team_id"] = json!(hash(TEAM));
    raw
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[tokio::test]
async fn fresh_team_safe_projection_attached_by_label_is_required_for_host_not_read_grant() {
    for (label, expected) in [("attached_by_you", true), ("team_source", false)] {
        let (api,server)=mock(vec![json!({"success":true,"ws_token":"token","user":{"id":"host"}}),json!({"project":project()}),json!({"team":{"team_id":TEAM,"encrypted_team_key":crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap()}}),json!({"sources":[{"source_id":"source","capabilities":["read"],"status":"offline","ownership_label":label}]})]).await;
        let mut client = client(&api);
        let binding = client
            .projects()
            .with_filters(ProjectFilters {
                team_id: Some(TEAM.into()),
                ..Default::default()
            })
            .source_host_binding(PROJECT, "source", Arc::new(ReadAdapter))
            .await;
        if expected {
            assert!(
                client
                    .prepare_source_host(
                        vec![binding.unwrap()],
                        SourceHostOptions {
                            source_session_id: "source-session".into(),
                            confirmed_takeover: false
                        },
                        tokio_util::sync::CancellationToken::new()
                    )
                    .is_ok()
            );
        } else {
            assert!(matches!(binding, Err(Error::Forbidden)));
        }
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 4);
        assert!(requests[3].starts_with(&format!(
            "GET /v1/projects/{PROJECT}/sources?team_id={TEAM} "
        )));
        assert!(client.session().unwrap().active_team_id.is_none());
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[tokio::test]
async fn source_revocation_or_missing_implemented_subset_denies_fresh_host_binding() {
    for (status, caps) in [("revoked", json!(["read"])), ("offline", json!(["search"]))] {
        let (api,server)=mock(vec![json!({"success":true,"ws_token":"token","user":{"id":"host"}}),json!({"project":project()}),json!({"team":{"team_id":TEAM,"encrypted_team_key":crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap()}}),json!({"sources":[{"source_id":"source","capabilities":caps,"status":status,"ownership_label":"attached_by_you"}]})]).await;
        let mut client = client(&api);
        assert!(matches!(
            client
                .projects()
                .with_filters(ProjectFilters {
                    team_id: Some(TEAM.into()),
                    ..Default::default()
                })
                .source_host_binding(PROJECT, "source", Arc::new(ReadAdapter))
                .await,
            Err(Error::Forbidden)
        ));
        assert_eq!(server.await.unwrap().len(), 4);
    }
}
