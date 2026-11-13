//! Who a generic server `error` frame on the live monitor socket answers: the
//! core's own request, or a raw shell frame written through the passthrough
//! (`view_model::socket_passthrough`, temporary strangler seam removed with
//! A5/A6 of `docs/plans/apple-client-core-migration/`).
//!
//! Server error frames name neither the request type nor a generic request id
//! (`backend/core/api/app/routes/websockets.py`), so attribution uses what this
//! socket has in flight. Of the core's monitor requests only the phased sync
//! (`phased_sync_request`, also the draft-metadata read) is answered with a
//! generic `error`, and always with a payload whose one field is `message`
//! (`websockets.py` context-epoch check, `phased_sync_handler.py`). The
//! lifecycle heartbeat, `set_active_chat`, `get_draft_versions` and
//! `sync_metadata_chats` never are (the last reports failures in its own
//! response). Hence:
//! - no shell frame written on this socket: the core's (fatal, as before);
//! - a phased-sync read in flight and a `message`-only payload: the core's
//!   (fatal; a shell error of the same shape in that window is not
//!   distinguishable and retires the socket too);
//! - otherwise: the shell's, forwarded as an unowned `error` frame, and the
//!   socket stays up.
use super::Changes;
use super::actor::MonitorReadRequest;
use serde_json::Value;
use std::sync::Arc;

/// Forward `payload` to the shell when it answers a shell frame; returns
/// whether it did. `read` is the core read in flight on this socket, if any.
/// `false` means the error is the core's and the caller keeps its fatal path.
pub(super) fn forward_shell_error(
    changes: Option<&Arc<Changes>>,
    read: Option<&MonitorReadRequest>,
    payload: &Value,
) -> bool {
    let Some(changes) = changes else {
        return false;
    };
    if !changes.passthrough.shell_wrote() {
        return false;
    }
    if read.is_some_and(answers_with_error) && is_phased_sync_error(payload) {
        return false;
    }
    changes.passthrough.observe_shell_error(payload);
    true
}

/// Whether the server may answer `read` with a generic `error` frame.
fn answers_with_error(read: &MonitorReadRequest) -> bool {
    match read {
        MonitorReadRequest::RecentSync
        | MonitorReadRequest::InitialStartup(_)
        | MonitorReadRequest::RecentSyncWithExpandedMetadata(_)
        | MonitorReadRequest::DraftMetadata(_) => true,
        MonitorReadRequest::DraftVersions(_) => false,
    }
}

/// The phased-sync error shape: an object whose only field is a `message`
/// string.
fn is_phased_sync_error(payload: &Value) -> bool {
    payload.as_object().is_some_and(|fields| {
        fields.len() == 1 && fields.get("message").is_some_and(Value::is_string)
    })
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "monitor_error_frames_tests.rs"]
mod tests;
