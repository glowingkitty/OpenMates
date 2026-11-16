//! Approval validation of a claimed remote command.
//!
//! One-run approvals are checked like `#validateApproval` in
//! `remoteCommandRuntime.ts`: the approval must name this execution and the
//! exact request digest. Preset approvals need the local grant store and the
//! `.openmates/permissions.yml` match, which this host does not provide yet,
//! so they are refused with a typed error instead of being trusted.
//! spec: specifications/features/app-skills/code-run code-run.remote.*

use super::wire::{Approval, RemoteCommandErrorCode};

/// Typed refusal reported as the terminal `error_code` / `error_message`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct ApprovalRefusal {
    /// Machine-readable code.
    pub(crate) code: RemoteCommandErrorCode,
    /// Fixed human-readable reason (never contains request data).
    pub(crate) message: &'static str,
}

/// Approval the runtime would act on: the server approval bound to the
/// verified request digest and execution.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct RuntimeApproval {
    /// Approval kind carried by the claim.
    pub(crate) approval: Approval,
    /// Execution the approval is bound to.
    pub(crate) execution_id: String,
    /// Digest of the exact request the approval covers.
    pub(crate) request_digest: String,
}

fn digests_equal(a: &str, b: &str) -> bool {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    let mut diff = a.len() ^ b.len();
    for i in 0..a.len().max(b.len()) {
        diff |= usize::from(a.get(i).copied().unwrap_or(0) ^ b.get(i).copied().unwrap_or(0));
    }
    diff == 0
}

/// Validate `approval` for `execution_id` against the locally verified
/// `request_digest`.
///
/// # Errors
/// `invalid_approval` when the digest differs, the one-run approval belongs
/// to another execution, or a preset approval cannot be checked here.
pub(crate) fn validate_approval(
    approval: &RuntimeApproval,
    execution_id: &str,
    request_digest: &str,
) -> Result<(), ApprovalRefusal> {
    if !digests_equal(&approval.request_digest, request_digest) {
        return Err(ApprovalRefusal {
            code: RemoteCommandErrorCode::InvalidApproval,
            message: "Approval does not match the exact command and resources",
        });
    }
    match &approval.approval {
        Approval::OneRun => {
            if approval.execution_id != execution_id {
                return Err(ApprovalRefusal {
                    code: RemoteCommandErrorCode::InvalidApproval,
                    message: "One-run approval belongs to another execution",
                });
            }
            Ok(())
        }
        Approval::Preset { .. } => Err(ApprovalRefusal {
            code: RemoteCommandErrorCode::InvalidApproval,
            message: "Preset approval cannot be checked against trusted active grants",
        }),
    }
}

/// Build the runtime approval for a claim, `None` when the request was
/// stopped (no approval is offered then, as in the TS runtime).
pub(crate) fn runtime_approval(
    approval: &Approval,
    execution_id: &str,
    request_digest: &str,
    stopped: bool,
) -> Option<RuntimeApproval> {
    (!stopped).then(|| RuntimeApproval {
        approval: approval.clone(),
        execution_id: execution_id.to_owned(),
        request_digest: request_digest.to_owned(),
    })
}

/// Refusal for a missing approval (`approval_required`).
pub(crate) fn approval_required() -> ApprovalRefusal {
    ApprovalRefusal {
        code: RemoteCommandErrorCode::ApprovalRequired,
        message: "This exact command requires user approval",
    }
}
