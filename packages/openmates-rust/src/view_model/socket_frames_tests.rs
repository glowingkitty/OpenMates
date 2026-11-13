//! The core-owned versus forwarded socket event decision: types the core's
//! socket code handles are never forwarded and never sendable by a shell.
use super::socket_frames::{
    CORE_AND_SHELL_EVENT_TYPES, CORE_EVENT_TYPES, SocketEventOwner, classify_socket_event,
    forwards_to_shell, shell_may_send,
};
use std::collections::BTreeSet;

/// Every type the core's socket code matches on today: the live monitor's
/// hints (`client/monitor.rs` `record_change`, `observe_frame`), its reads
/// (`client/monitor_actor.rs` `correlated`, draft and startup reads) and the
/// transport (`force_logout`, `error`). Keep in step with that code: a type
/// added there and not here or in the lists fails
/// `core_handled_types_are_never_forwarded_to_the_shell`.
const CORE_HANDLED: &[&str] = &[
    "chat_title_updated",
    "new_chat_message",
    "ai_message_update",
    "ai_background_response_completed",
    "team_chat_message_created",
    "team_ai_response_completed",
    "team_chat_created",
    "chat_read_status_updated",
    "chat_sync_hint",
    "recovery_jobs_available",
    "metadata_jobs_available",
    "project_remote_access_revoked",
    "recovery_outputs_discovery_complete",
    "phase_1_last_chat_ready",
    "phase_1b_chat_content_ready",
    "phase_1b_last_chat_messages_ready",
    "phase_2_last_20_chats_ready",
    "phase_3_chunk_ready",
    "phased_sync_complete",
    "sync_metadata_chats_response",
    "load_more_chats_response",
    "draft_versions_response",
    "force_logout",
    "error",
];

#[test]
fn core_handled_types_are_never_forwarded_to_the_shell() {
    for kind in CORE_HANDLED {
        assert_eq!(
            classify_socket_event(kind),
            SocketEventOwner::Core,
            "{kind}"
        );
        assert!(!forwards_to_shell(kind), "{kind} would be handled twice");
        assert!(!shell_may_send(kind), "{kind}");
    }
}

#[test]
fn shared_hints_are_forwarded_but_never_sendable() {
    for kind in CORE_AND_SHELL_EVENT_TYPES {
        assert_eq!(classify_socket_event(kind), SocketEventOwner::CoreAndShell);
        assert!(forwards_to_shell(kind));
        assert!(!shell_may_send(kind));
    }
}

#[test]
fn unlisted_types_belong_to_the_shell() {
    for kind in [
        "embed_update",
        "reminder_fired",
        "update_draft",
        "synthetic_new_event",
    ] {
        assert_eq!(
            classify_socket_event(kind),
            SocketEventOwner::Shell,
            "{kind}"
        );
        assert!(forwards_to_shell(kind));
        assert!(shell_may_send(kind));
    }
}

#[test]
fn the_lists_are_disjoint_and_free_of_duplicates() {
    let core: BTreeSet<_> = CORE_EVENT_TYPES.iter().collect();
    let shared: BTreeSet<_> = CORE_AND_SHELL_EVENT_TYPES.iter().collect();
    assert_eq!(core.len(), CORE_EVENT_TYPES.len());
    assert_eq!(shared.len(), CORE_AND_SHELL_EVENT_TYPES.len());
    assert!(core.is_disjoint(&shared));
}
