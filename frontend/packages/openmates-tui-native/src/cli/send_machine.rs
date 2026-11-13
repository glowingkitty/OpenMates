//! `--confirm-machine-project`, `--machine-project-host` and
//! `--decline-machine-project` on `chats send`: the user's explicit answer to the
//! assistant's proposal to create a Project folder on their machine. The core
//! answers the confirmation request on the live turn socket; this file only
//! parses the flags and renders the hint.
use super::{CliError, Invocation};
use openmates_sdk::MachineProjectDecision;

/// Flags added to the allowed list of the send family.
pub(super) const FLAGS: [&str; 3] = [
    "confirm-machine-project",
    "machine-project-host",
    "decline-machine-project",
];

/// Stderr hint printed when a turn asked for confirmation that was not given.
pub(super) const HINT: &str = "The assistant needs your confirmation to create this Project on your machine. Resend with --confirm-machine-project (or --machine-project-host <hash>; list hashes with: openmates projects remote hosts), or --decline-machine-project.\n";

fn valid_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

/// Resolve the decision; no flag means the non-interactive `Unavailable` answer.
pub(super) fn decision(invocation: &Invocation) -> Result<MachineProjectDecision, CliError> {
    let confirm = invocation.boolean("confirm-machine-project");
    let decline = invocation.boolean("decline-machine-project");
    let host = invocation.text("machine-project-host");
    if invocation.has("machine-project-host") && host.is_none() {
        return Err(CliError::Invalid(
            "--machine-project-host needs a device hash.".into(),
        ));
    }
    if decline && (confirm || host.is_some()) {
        return Err(CliError::Invalid(
            "--decline-machine-project cannot be combined with --confirm-machine-project or --machine-project-host.".into(),
        ));
    }
    if decline {
        return Ok(MachineProjectDecision::Decline);
    }
    if let Some(hash) = host {
        if !valid_hash(hash) {
            return Err(CliError::Invalid(
                "--machine-project-host must be a 64-character lowercase hex device hash (see openmates projects remote hosts).".into(),
            ));
        }
        return Ok(MachineProjectDecision::Confirm {
            host_device_hash: Some(hash.to_owned()),
        });
    }
    if confirm {
        return Ok(MachineProjectDecision::Confirm {
            host_device_hash: None,
        });
    }
    Ok(MachineProjectDecision::Unavailable)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{Value, json};

    fn invocation(flags: &[(&str, Value)]) -> Invocation {
        Invocation {
            path: vec!["chats".into(), "send".into()],
            positionals: vec!["hello".into()],
            flags: flags
                .iter()
                .map(|(k, v)| (k.to_string(), v.clone()))
                .collect(),
        }
    }

    fn ok(invocation: &Invocation) -> MachineProjectDecision {
        decision(invocation).unwrap_or_else(|error| panic!("{error}"))
    }

    #[test]
    fn flags_map_to_decisions_and_exclude_each_other() {
        let hash = "ab".repeat(32);
        assert_eq!(ok(&invocation(&[])), MachineProjectDecision::Unavailable);
        assert_eq!(
            ok(&invocation(&[("confirm-machine-project", json!(true))])),
            MachineProjectDecision::Confirm {
                host_device_hash: None
            }
        );
        assert_eq!(
            ok(&invocation(&[("machine-project-host", json!(hash))])),
            MachineProjectDecision::Confirm {
                host_device_hash: Some(hash.clone())
            }
        );
        assert_eq!(
            ok(&invocation(&[("decline-machine-project", json!(true))])),
            MachineProjectDecision::Decline
        );
        for bad in [json!("ABC"), json!("AB".repeat(32)), json!("")] {
            assert!(matches!(
                decision(&invocation(&[("machine-project-host", bad)])),
                Err(CliError::Invalid(_))
            ));
        }
        for other in [
            ("confirm-machine-project", json!(true)),
            ("machine-project-host", json!(hash)),
        ] {
            assert!(matches!(
                decision(&invocation(&[
                    other,
                    ("decline-machine-project", json!(true))
                ])),
                Err(CliError::Invalid(_))
            ));
        }
    }
}
