//! One-run approval validation and preset refusal tests.

use super::approval::*;
use super::wire::{Approval, RemoteCommandErrorCode};

fn one_run(exec: &str, digest: &str) -> RuntimeApproval {
    runtime_approval(&Approval::OneRun, exec, digest, false).unwrap()
}

#[test]
fn one_run_needs_matching_digest_and_execution() {
    assert_eq!(
        validate_approval(&one_run("e1", "abc"), "e1", "abc"),
        Ok(())
    );
    let digest = validate_approval(&one_run("e1", "abc"), "e1", "abd").unwrap_err();
    assert_eq!(digest.code, RemoteCommandErrorCode::InvalidApproval);
    let other = validate_approval(&one_run("e2", "abc"), "e1", "abc").unwrap_err();
    assert_eq!(other.code, RemoteCommandErrorCode::InvalidApproval);
    assert!(other.message.contains("another execution"));
}

#[test]
fn preset_is_refused_and_stop_drops_approval() {
    let preset = Approval::Preset {
        preset_id: "p".into(),
        definition_digest: "a".repeat(64),
    };
    let approval = runtime_approval(&preset, "e1", "abc", false).unwrap();
    assert_eq!(
        validate_approval(&approval, "e1", "abc").unwrap_err().code,
        RemoteCommandErrorCode::InvalidApproval
    );
    assert!(runtime_approval(&Approval::OneRun, "e1", "abc", true).is_none());
    assert_eq!(
        approval_required().code,
        RemoteCommandErrorCode::ApprovalRequired
    );
}
