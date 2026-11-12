//! Capability advertisement: `run_command` is claimed only when a command sandbox tier was detected (detection result injected).
use super::dispatch::capabilities_for;
use super::host_capability_names;
use crate::work::ProjectSourceCapability;

// contract-test: supporting surface=cli assertions=code-run.remote.confinement
#[test]
fn run_command_is_advertised_only_with_a_sandbox_tier() {
    let with = capabilities_for(true);
    assert!(with.contains(&ProjectSourceCapability::RunCommand));
    assert!(host_capability_names(true, false).contains(&"run_command"));
    let without = capabilities_for(false);
    assert!(!without.contains(&ProjectSourceCapability::RunCommand));
    assert!(!host_capability_names(false, false).contains(&"run_command"));
    assert!(without.contains(&ProjectSourceCapability::WriteRequest));
    assert_eq!(
        host_capability_names(false, false),
        super::HOST_CAPABILITIES.to_vec()
    );
}
