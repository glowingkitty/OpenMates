//! The one place that decides which chat-socket event types the shared core
//! owns and which belong to shell features that have not moved into the core
//! yet. Both directions use it: an inbound frame of the core's socket reaches
//! the shell only when [`forwards_to_shell`] says so, and a shell may send a
//! raw frame only when [`shell_may_send`] says so.
//!
//! Temporary strangler seam of `docs/plans/apple-client-core-migration/`
//! (lane A4, live updates and transport ownership): removed when A5/A6 move
//! the remaining features into the core. Compiles for native and wasm, since
//! the socket hook in `client/monitor.rs` does.

/// Who handles one socket event type while the shells migrate onto the core.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SocketEventOwner {
    /// The core consumes the frame or owns its capability (sync phases, chat
    /// list and window, send and streaming, recovery, session and transport
    /// control). Never forwarded; a shell may not send it.
    Core,
    /// The core reads the frame as a chat-list hint, and a shell feature that
    /// is not in the core yet (drafts, chat deletion, typing metadata,
    /// suggestions) still needs its content. Forwarded; a shell may not send
    /// it (it is a server event).
    CoreAndShell,
    /// Only shell features use the frame. Forwarded; a shell may send it.
    /// Every type not listed in [`CORE_EVENT_TYPES`] or
    /// [`CORE_AND_SHELL_EVENT_TYPES`] is a shell type.
    Shell,
}

/// Event types the core owns, in both directions. Exact names, no prefixes.
pub const CORE_EVENT_TYPES: &[&str] = &[
    // Phased sync, the sync feed and chat content reads (`client/sync*`,
    // `client/monitor_actor.rs`). The core's draft read consumes uncorrelated
    // `draft_versions_response` frames, so its request is core-only too.
    "phased_sync_request",
    "phase_1_last_chat_ready",
    "phase_1b_chat_content_ready",
    "phase_1b_last_chat_messages_ready",
    "phase_2_last_20_chats_ready",
    "phase_3_chunk_ready",
    "phase_3_last_100_chats_ready",
    "phased_sync_complete",
    "sync_metadata_chats",
    "sync_metadata_chats_response",
    "load_more_chats",
    "load_more_chats_response",
    "initial_sync_response",
    "initial_sync_error",
    "background_message_sync",
    "chat_sync_hint",
    "offline_sync_complete",
    "sync_status_response",
    "cache_primed",
    "cache_status_response",
    "request_chat_content_batch",
    "chat_content_batch_response",
    "get_draft_versions",
    "draft_versions_response",
    // Chat list and window hints of the live monitor (`record_change`).
    "chat_title_updated",
    "new_chat_message",
    "team_chat_message_created",
    "team_ai_response_completed",
    "team_chat_created",
    "chat_read_status_updated",
    "encrypted_chat_metadata",
    // Send, streaming and cancel (`client/send*`, view-model `Send`).
    "chat_message_added",
    "chat_message_confirmed",
    "chat_turn_preflight",
    "chat_turn_preflight_ack",
    "chat_turn_admit",
    "ai_task_initiated",
    "ai_message_update",
    "thinking_chunk",
    "thinking_complete",
    "ai_message_ready",
    "ai_typing_ended",
    "ai_background_response_completed",
    "ai_task_cancel_requested",
    "cancel_ai_task",
    "message_queued",
    "set_active_chat",
    // Completion, metadata and workflow-delivery recovery (job leases).
    "recovery_outputs_available",
    "recovery_outputs_discovery_complete",
    "recovery_jobs_available",
    "recovery_job_claim",
    "recovery_job_claimed",
    "recovery_job_persist",
    "recovery_job_persisted",
    "metadata_jobs_available",
    "metadata_jobs_request",
    "metadata_job_claim",
    "metadata_job_claimed",
    "metadata_job_persist",
    "metadata_job_persisted",
    "workflow_chat_deliveries_available",
    "workflow_chat_delivery_claim",
    "workflow_chat_delivery_claimed",
    "workflow_chat_delivery_persist",
    "workflow_chat_delivery_persisted",
    "workflow_chat_delivery_ack",
    "workflow_chat_delivery_acknowledged",
    // Session and transport control: the lifecycle heartbeat, logout, scope
    // revocation and protocol errors. An `error` frame the monitor attributes
    // to a forwarded shell frame still reaches the shell, through
    // `SocketPassthrough::observe_shell_error` (`client/monitor_error_frames.rs`);
    // any other `error` frame stays fatal for the socket.
    "native_client_lifecycle",
    "native_client_lifecycle_ack",
    "force_logout",
    "project_remote_access_revoked",
    "error",
    "ping",
    "pong",
];

/// Hints the core reads for the chat list whose content an un-migrated shell
/// feature still needs: drafts sync (`chat_draft_updated`, `draft_deleted`),
/// chat deletion cleanup (`chat_deleted`), typing metadata
/// (`ai_typing_started`: title, icons, category, model) and follow-up and
/// new-chat suggestions (`post_processing_completed`).
pub const CORE_AND_SHELL_EVENT_TYPES: &[&str] = &[
    "chat_draft_updated",
    "draft_deleted",
    "chat_deleted",
    "ai_typing_started",
    "post_processing_completed",
];

/// Classify `event_type` (the `type` field of a socket frame, or the `event`
/// field of the legacy canonical envelope).
///
/// A type the lists do not name is [`SocketEventOwner::Shell`], so a new
/// server type reaches the shell instead of disappearing. A type moves into
/// [`CORE_EVENT_TYPES`] in the deploy that moves its feature into the core.
pub fn classify_socket_event(event_type: &str) -> SocketEventOwner {
    if CORE_EVENT_TYPES.contains(&event_type) {
        SocketEventOwner::Core
    } else if CORE_AND_SHELL_EVENT_TYPES.contains(&event_type) {
        SocketEventOwner::CoreAndShell
    } else {
        SocketEventOwner::Shell
    }
}

/// Whether an inbound frame of `event_type` is delivered to the shell as
/// `ViewEvent::UnownedSocketFrame`.
pub fn forwards_to_shell(event_type: &str) -> bool {
    classify_socket_event(event_type) != SocketEventOwner::Core
}

/// Whether a shell may send a raw frame of `event_type` through the core's
/// socket (`UnownedFrameSender::send`).
pub fn shell_may_send(event_type: &str) -> bool {
    classify_socket_event(event_type) == SocketEventOwner::Shell
}
