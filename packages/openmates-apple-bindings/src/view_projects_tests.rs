//! Project operations on `ViewModelCore`: refused while signed out, and the
//! record mappings of land outcomes and refusals.
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::{CHAT, core};
use crate::*;
use openmates_sdk::view_model::RemoteRefusal;
use openmates_sdk::work::GitLandOutcome;
use std::sync::Arc;

const OPERATION: &str = "66666666-6666-4666-8666-666666666666";

#[tokio::test(flavor = "multi_thread")]
async fn signed_out_project_operations_are_refused_with_authentication() {
    let dir = private_dir();
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), "http://127.0.0.1:9", &keychain, &events);
    core.start(None).await.unwrap();
    assert_eq!(
        core.undo_created_project(CHAT.into(), None).await,
        Err(CoreError::Authentication)
    );
    assert_eq!(
        core.git_status("p".into(), None, CHAT.into(), None).await,
        Err(CoreError::Authentication)
    );
    assert_eq!(
        core.git_commit(
            "p".into(),
            None,
            CHAT.into(),
            OPERATION.into(),
            "m".into(),
            None
        )
        .await,
        Err(CoreError::Authentication)
    );
    assert_eq!(
        core.git_land("p".into(), None, CHAT.into(), OPERATION.into(), None)
            .await,
        Err(CoreError::Authentication)
    );
    let command = RemoteCommandRecord {
        argv: vec!["true".into()],
        cwd: None,
        timeout_ms: 1000,
        max_output_bytes: None,
    };
    assert_eq!(
        core.run_remote_command(
            "p".into(),
            None,
            CHAT.into(),
            OPERATION.into(),
            command,
            None
        )
        .await,
        Err(CoreError::Authentication)
    );
}

#[test]
fn land_conflicts_and_refusals_map_to_records() {
    let conflict = GitLandOutcome::Conflict {
        landed: false,
        code: "land_conflict".into(),
        conflicting_paths: vec!["a.txt".into()],
    };
    assert_eq!(
        GitLandResultRecord::from(conflict),
        GitLandResultRecord::Conflict {
            code: "land_conflict".into(),
            conflicting_paths: vec!["a.txt".into()],
        }
    );
    let refusal = RemoteRefusalRecord::from(RemoteRefusal {
        code: "no_worktree".into(),
        message: "none".into(),
    });
    assert_eq!(refusal.code, "no_worktree");
}

#[test]
fn machine_decisions_map_to_core_decisions() {
    use openmates_sdk::client::MachineProjectDecision as Core;
    assert_eq!(
        Core::from(MachineProjectDecisionRecord::Confirm {
            host_device_hash: Some("h".into())
        }),
        Core::Confirm {
            host_device_hash: Some("h".into())
        }
    );
    assert_eq!(
        Core::from(MachineProjectDecisionRecord::Decline),
        Core::Decline
    );
}
