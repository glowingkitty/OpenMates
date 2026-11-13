//! User-made embed versions on `ViewModelCore` for the Apple shell (spec
//! `feature.embed-user-edits`): the version history with provenance, a content
//! edit committed as the next version, restore of an earlier version, the
//! chat-open reconcile of pending `embed_updated` notices and the timeline
//! grouping of those events. Image Enhance lives in `view_embed_enhance.rs`.
//! The core (`Client::embed_version_history`, `embed_user_edit_head`,
//! `commit_embed_user_revision`, `restore_embed_version`,
//! `reconcile_embed_update_notices_on_open`, `group_embed_updated_events`) owns
//! keys, encryption and the compare-and-swap; this module only marshals
//! plaintext presentation records and maps the core's refusals to the typed
//! `EmbedEditError`. Mirrors `browser_embed_user_edit.rs`; plan
//! `apple-client-core-migration`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use crate::view_records::MessageRoleRecord;
use futures_util::future::BoxFuture;
use openmates_sdk::{
    Client,
    client::embed_updated_event::{
        ChatHistoryItem, EmbedKind, EmbedUpdateAction, EmbedUpdateSurface, EmbedUpdatedGroup,
        HistoryRow, NoticeReconcileReport, group_embed_updated_events,
    },
    client::embed_user_revision::{
        EmbedRevisionOutcome, EventDelivery, RevisionScope, UserRevisionError, UserRevisionRequest,
    },
    client::embed_version_history::{EmbedVersionEntry, EmbedVersionHistory},
    client::embed_write::pinned::RevisionOrigin,
    error::{Error, Result},
    view_model::ViewHost,
};
use std::sync::Arc;
use zeroize::Zeroizing;

/// Why an embed edit, restore, Enhance or history read failed. Each case is
/// a stable code Swift can switch on; `code` fields carry the server's or
/// core's stable code (`embed_type_not_editable`, `restore_source_missing`,
/// ...). Messages never contain content, keys or URLs.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error, uniffi::Error)]
pub enum EmbedEditError {
    /// The embed changed meanwhile (another device or the assistant saved a
    /// newer version): reload it before editing again. Code
    /// `embed_version_conflict`.
    #[error("embed_version_conflict")]
    VersionConflict {
        /// The server's head version, when known.
        current_version: Option<i64>,
    },
    /// The embed belongs to a Project: save it in `EmbedScopeRecord.project`.
    #[error("project_context_required")]
    ProjectContextRequired,
    /// The Enhance result is saved in another scope than it was started in.
    #[error("enhance_scope_mismatch")]
    ScopeMismatch,
    /// This account may not edit this embed here.
    #[error("{code}")]
    AccessDenied {
        /// `forbidden`, `chat_access_denied`, `embed_type_not_editable`, ...
        code: String,
    },
    /// The request was malformed (nothing was saved).
    #[error("{code}")]
    Validation {
        /// `invalid_restored_from`, `invalid_scope`, `invalid_head`, ...
        code: String,
    },
    /// Another stable refusal of the server.
    #[error("{code}")]
    Refused {
        /// `restore_source_missing`, `operation_payload_mismatch`, ...
        code: String,
    },
    /// The embed key is not available on this device.
    #[error("embed_key_unavailable")]
    KeyUnavailable,
    /// Not enough credits for Enhance (nothing charged).
    #[error("insufficient_credits")]
    InsufficientCredits,
    /// Team images cannot be enhanced yet.
    #[error("team_enhance_unavailable")]
    TeamUnavailable,
    /// The embed, chat, Project link or Enhance job does not exist.
    #[error("{code}")]
    NotFound {
        /// `embed_not_found`, `enhance_not_found`, ...
        code: String,
    },
    /// The image cannot be enhanced (`not_an_image`, `unsupported_format`, ...).
    #[error("{code}")]
    InvalidSource {
        /// Stable code.
        code: String,
    },
    /// Too many Enhance requests; retry later.
    #[error("rate_limited")]
    RateLimited,
    /// The Enhance job is being updated; retry the same call.
    #[error("enhance_job_busy")]
    Busy,
    /// The operation id belongs to another embed or account.
    #[error("operation_id_conflict")]
    OperationConflict,
    /// A service is temporarily unavailable.
    #[error("{code}")]
    Unavailable {
        /// Server or core code.
        code: String,
    },
    /// The Enhance job failed on the server; nothing was charged.
    #[error("enhance_failed")]
    EnhanceFailed {
        /// The job's operation id.
        operation_id: String,
        /// Server failure code.
        code: String,
    },
    /// The Enhance result was not saved within 24 hours and is gone.
    #[error("enhance_result_expired")]
    EnhanceExpired {
        /// The job's operation id.
        operation_id: String,
    },
    /// The Enhance job is still running.
    #[error("enhance_result_not_ready")]
    EnhanceNotReady {
        /// The job's operation id.
        operation_id: String,
    },
    /// The wait ended before the job settled; the job keeps running. Keep
    /// `operation_id` and call `saveImageEnhanceResult` later.
    #[error("enhance_timeout")]
    EnhanceTimeout {
        /// The job's operation id.
        operation_id: String,
    },
    /// No network connection; nothing is known to be saved unless a retry
    /// with the same operation id reports it.
    #[error("offline")]
    Offline,
    /// The session ended (`Session(Expired)` was emitted when the server
    /// rejected it).
    #[error("session_expired")]
    SessionExpired,
    /// Signed out or not admitted.
    #[error("authentication")]
    Authentication,
    /// The server asks to verify this device (`Session(VerificationRequired)`).
    #[error("verification_required")]
    VerificationRequired,
    /// `cancellation` fired.
    #[error("cancelled")]
    Cancelled,
    /// Another transport, crypto, storage or protocol failure.
    #[error("{code}")]
    Transport {
        /// `protocol`, `encryption_failed`, `io`, `locked`, `conflict`, ...
        code: String,
    },
    /// Binding failure (runtime shut down or task panicked).
    #[error("internal: {reason}")]
    Internal {
        /// Fixed, non-secret reason.
        reason: String,
    },
}

impl From<Error> for EmbedEditError {
    fn from(error: Error) -> Self {
        let transport = |code: &str| Self::Transport { code: code.into() };
        match error {
            Error::Offline => Self::Offline,
            Error::Expired => Self::SessionExpired,
            Error::Authentication | Error::TwoFactorRequired | Error::SignupRequired => {
                Self::Authentication
            }
            Error::VerificationRequired => Self::VerificationRequired,
            Error::Cancelled => Self::Cancelled,
            Error::Forbidden => Self::AccessDenied {
                code: "forbidden".into(),
            },
            Error::Invalid(_) => Self::Validation {
                code: "invalid_request".into(),
            },
            Error::Unavailable { code, .. } => Self::Unavailable { code: code.into() },
            Error::Conflict => transport("conflict"),
            Error::Crypto => transport("encryption_failed"),
            Error::Protocol => transport("protocol"),
            Error::Io => transport("io"),
            Error::Locked => transport("locked"),
        }
    }
}

impl From<CoreError> for EmbedEditError {
    fn from(error: CoreError) -> Self {
        match error {
            CoreError::Internal { reason } => Self::Internal { reason },
            CoreError::Cancelled => Self::Cancelled,
            CoreError::Offline => Self::Offline,
            CoreError::Expired => Self::SessionExpired,
            CoreError::Authentication
            | CoreError::TwoFactorRequired
            | CoreError::SignupRequired => Self::Authentication,
            CoreError::VerificationRequired => Self::VerificationRequired,
            CoreError::Forbidden => Self::AccessDenied {
                code: "forbidden".into(),
            },
            CoreError::Invalid { .. } => Self::Validation {
                code: "invalid_request".into(),
            },
            CoreError::Unavailable { code, .. } => Self::Unavailable { code },
            CoreError::Crypto => Self::Transport {
                code: "encryption_failed".into(),
            },
            CoreError::Locked => Self::Transport {
                code: "locked".into(),
            },
            CoreError::Io => Self::Transport { code: "io".into() },
            CoreError::Protocol => Self::Transport {
                code: "protocol".into(),
            },
            CoreError::Conflict => Self::Transport {
                code: "conflict".into(),
            },
            // Memory commands never run here; kept explicit so a new core
            // error kind fails to compile instead of being mapped silently.
            CoreError::Memory { code } => Self::Refused { code },
        }
    }
}

impl From<UserRevisionError> for EmbedEditError {
    fn from(error: UserRevisionError) -> Self {
        match error {
            UserRevisionError::VersionConflict {
                current_revision, ..
            } => Self::VersionConflict {
                current_version: current_revision,
            },
            UserRevisionError::ProjectContextRequired => Self::ProjectContextRequired,
            UserRevisionError::AccessDenied { code } => Self::AccessDenied { code: code.into() },
            UserRevisionError::Validation { code } => Self::Validation { code: code.into() },
            UserRevisionError::BaseSnapshotRequired => Self::Refused {
                code: "base_snapshot_required".into(),
            },
            UserRevisionError::Refused { code } => Self::Refused { code: code.into() },
            UserRevisionError::KeyUnavailable => Self::KeyUnavailable,
            UserRevisionError::Transport(error) => error.into(),
        }
    }
}

/// Where a version is saved or read (core `RevisionScope`). A Project-linked
/// embed is saved only in Project scope (`ProjectContextRequired` otherwise).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum EmbedScopeRecord {
    /// The embed's chat (`team_id` for a Team chat).
    Chat {
        /// Chat id.
        chat_id: String,
        /// Team of a Team chat.
        team_id: Option<String>,
    },
    /// A Project that links the embed.
    Project {
        /// Project id.
        project_id: String,
        /// Team of a Team Project.
        team_id: Option<String>,
    },
}

impl From<EmbedScopeRecord> for RevisionScope {
    fn from(value: EmbedScopeRecord) -> Self {
        match value {
            EmbedScopeRecord::Chat { chat_id, team_id } => Self::Chat { chat_id, team_id },
            EmbedScopeRecord::Project {
                project_id,
                team_id,
            } => Self::Project {
                project_id,
                team_id,
            },
        }
    }
}

/// Who made a version.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum EmbedRevisionOriginRecord {
    /// The assistant (generation or revision).
    Assistant,
    /// The user (edit, Enhance, restore, crop).
    User,
}

/// What the user did to make a version.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum EmbedUpdateActionRecord {
    /// A content edit.
    Edit,
    /// An image Enhance result.
    Enhance,
    /// A copy of an earlier version.
    Restore,
    /// A cropped image.
    Crop,
}

impl From<EmbedUpdateAction> for EmbedUpdateActionRecord {
    fn from(value: EmbedUpdateAction) -> Self {
        match value {
            EmbedUpdateAction::Edit => Self::Edit,
            EmbedUpdateAction::Enhance => Self::Enhance,
            EmbedUpdateAction::Restore => Self::Restore,
            EmbedUpdateAction::Crop => Self::Crop,
        }
    }
}

/// Where a user edit was made.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum EmbedUpdateSurfaceRecord {
    /// In the embed's chat.
    Chat,
    /// In the Projects workspace.
    Project,
}

impl From<EmbedUpdateSurface> for EmbedUpdateSurfaceRecord {
    fn from(value: EmbedUpdateSurface) -> Self {
        match value {
            EmbedUpdateSurface::Chat => Self::Chat,
            EmbedUpdateSurface::Project => Self::Project,
        }
    }
}

/// User-editable embed kinds, shown as "<Kind> updated".
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum EmbedKindRecord {
    /// Generated or uploaded image.
    Image,
    /// HTML diagram.
    Diagram,
    /// Slides deck.
    Slides,
    /// Sheet.
    Sheet,
    /// Document.
    Document,
}

impl From<EmbedKind> for EmbedKindRecord {
    fn from(value: EmbedKind) -> Self {
        match value {
            EmbedKind::Image => Self::Image,
            EmbedKind::Diagram => Self::Diagram,
            EmbedKind::Slides => Self::Slides,
            EmbedKind::Sheet => Self::Sheet,
            EmbedKind::Document => Self::Document,
        }
    }
}

/// One stored version of an embed.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct EmbedVersionRecord {
    /// Version number (1 is the assistant's first version).
    pub version: i64,
    /// Who made it.
    pub origin: EmbedRevisionOriginRecord,
    /// What the user did; `nil` for assistant versions.
    pub action: Option<EmbedUpdateActionRecord>,
    /// Unix seconds it was stored, when the server reported it.
    pub created_at: Option<i64>,
    /// True for the head version (what the embed shows now).
    pub is_current: bool,
}

/// The version history of one embed, oldest first.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct EmbedVersionHistoryRecord {
    /// Embed id.
    pub embed_id: String,
    /// The server's head version.
    pub current_version: i64,
    /// Every listed version, ascending.
    pub versions: Vec<EmbedVersionRecord>,
}

fn version_record(entry: EmbedVersionEntry, current_version: i64) -> EmbedVersionRecord {
    EmbedVersionRecord {
        version: entry.version,
        origin: match entry.origin {
            RevisionOrigin::Assistant => EmbedRevisionOriginRecord::Assistant,
            RevisionOrigin::User => EmbedRevisionOriginRecord::User,
        },
        action: entry.action.map(Into::into),
        created_at: entry.created_at,
        is_current: entry.version == current_version,
    }
}

impl From<EmbedVersionHistory> for EmbedVersionHistoryRecord {
    fn from(value: EmbedVersionHistory) -> Self {
        let current = value.current_version;
        Self {
            embed_id: value.embed_id,
            current_version: current,
            versions: value
                .versions
                .into_iter()
                .map(|entry| version_record(entry, current))
                .collect(),
        }
    }
}

/// What happened to the chat event of a committed version.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum EmbedEventDeliveryRecord {
    /// The `embed_updated` event was written and confirmed now.
    Written,
    /// This device (or the chat) already has it.
    AlreadyWritten,
    /// The embed has no chat (a Project-only file).
    NoChat,
    /// Not written now; the next chat open on any device writes it.
    Deferred {
        /// `home_chat_unavailable`, `embed_identity_unavailable`, `offline`, ...
        code: String,
    },
}

/// A version committed by an edit, restore or Enhance save.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct EmbedRevisionOutcomeRecord {
    /// Embed id.
    pub embed_id: String,
    /// Idempotency key of the commit.
    pub operation_id: String,
    /// The new head version (N+1).
    pub version: i64,
    /// The version it was made from (N).
    pub base_version: i64,
    /// What the user did.
    pub action: EmbedUpdateActionRecord,
    /// The version a restore copied.
    pub restored_from: Option<i64>,
    /// Where it was saved.
    pub surface: EmbedUpdateSurfaceRecord,
    /// True when the server answered from an earlier receipt of the same operation.
    pub idempotent: bool,
    /// False when the commit is durable but the core's cached head was not
    /// updated: refresh the embed before the next edit.
    pub cache_synchronized: bool,
    /// The chat event of the version.
    pub event: EmbedEventDeliveryRecord,
}

impl From<EmbedRevisionOutcome> for EmbedRevisionOutcomeRecord {
    fn from(value: EmbedRevisionOutcome) -> Self {
        let committed = value.commit.committed;
        Self {
            embed_id: committed.embed_id,
            operation_id: committed.operation_id,
            version: committed.version,
            base_version: committed.base_version,
            action: committed.action.into(),
            restored_from: committed.restored_from,
            surface: committed.surface.into(),
            idempotent: committed.idempotent,
            cache_synchronized: value.commit.cache_synchronized,
            event: match value.event {
                EventDelivery::Written => EmbedEventDeliveryRecord::Written,
                EventDelivery::AlreadyWritten => EmbedEventDeliveryRecord::AlreadyWritten,
                EventDelivery::NoChat => EmbedEventDeliveryRecord::NoChat,
                EventDelivery::Deferred { code } => {
                    EmbedEventDeliveryRecord::Deferred { code: code.into() }
                }
            },
        }
    }
}

/// Outcome of a pending-notice reconcile of one chat.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct EmbedNoticeReconcileRecord {
    /// Events written and confirmed now (they arrive as new system messages).
    pub written: u64,
    /// Notices whose message the chat already has.
    pub already_present: u64,
    /// Message ids left pending (the embed is not nameable on this device).
    pub unresolved_message_ids: Vec<String>,
    /// Set when the reconcile did not run now (`team_chat`, `offline`, ...);
    /// the next open retries.
    pub deferred_code: Option<String>,
}

impl From<NoticeReconcileReport> for EmbedNoticeReconcileRecord {
    fn from(value: NoticeReconcileReport) -> Self {
        Self {
            written: value.written as u64,
            already_present: value.already_present as u64,
            unresolved_message_ids: value.unresolved,
            deferred_code: value.deferred.map(str::to_owned),
        }
    }
}

/// One message of an open chat window as the timeline grouping reads it.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct EmbedTimelineRowRecord {
    /// Message id.
    pub message_id: String,
    /// Author role (only system messages can be embed events).
    pub role: MessageRoleRecord,
    /// Decrypted content as in `MessageViewRecord.content`.
    pub content: String,
}

/// A folded run of `embed_updated` events of one embed ("Image updated, 3 changes").
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct EmbedUpdatedGroupRecord {
    /// Embed of the run.
    pub embed_id: String,
    /// Its ref, to open the embed.
    pub embed_ref: String,
    /// Kind shown as "<Kind> updated".
    pub embed_kind: EmbedKindRecord,
    /// Newest version of the run.
    pub latest_version: i64,
    /// Events in the run.
    pub change_count: u64,
    /// Action of the newest event.
    pub latest_action: EmbedUpdateActionRecord,
    /// Unix seconds of the newest event.
    pub latest_created_at: i64,
    /// Version the newest event restored (restore only).
    pub restored_from: Option<i64>,
    /// Where the newest edit was made.
    pub surface: EmbedUpdateSurfaceRecord,
    /// Message ids of the run, oldest first.
    pub message_ids: Vec<String>,
}

impl From<EmbedUpdatedGroup> for EmbedUpdatedGroupRecord {
    fn from(value: EmbedUpdatedGroup) -> Self {
        Self {
            embed_id: value.embed_id,
            embed_ref: value.embed_ref,
            embed_kind: value.embed_kind.into(),
            latest_version: value.latest_version,
            change_count: value.change_count as u64,
            latest_action: value.latest_action.into(),
            latest_created_at: value.latest_created_at,
            restored_from: value.restored_from,
            surface: value.surface.into(),
            message_ids: value.message_ids,
        }
    }
}

/// One item of the chat timeline: an ordinary message or a folded event run.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum EmbedTimelineItemRecord {
    /// Input row `index`, rendered as before.
    Message {
        /// Index into the input rows.
        index: u64,
        /// Its message id.
        message_id: String,
    },
    /// A run of user edits of one embed, rendered as one notice.
    EmbedUpdated {
        /// The folded run.
        group: EmbedUpdatedGroupRecord,
    },
}

fn role_name(role: MessageRoleRecord) -> &'static str {
    match role {
        MessageRoleRecord::User => "user",
        MessageRoleRecord::Assistant => "assistant",
        MessageRoleRecord::System => "system",
    }
}

/// Fold the `embed_updated` system events of an open chat window (rows in
/// window order, as `ChatWindow` delivers them) the way the web timeline
/// shows them: consecutive events of one embed with no other row between
/// them become one `EmbedUpdated` item; every other row, including an
/// invalid event payload, stays a `Message`. Pure; no actor or network.
#[uniffi::export]
pub fn embed_update_timeline(rows: Vec<EmbedTimelineRowRecord>) -> Vec<EmbedTimelineItemRecord> {
    let borrowed: Vec<HistoryRow<'_>> = rows
        .iter()
        .map(|row| HistoryRow {
            message_id: &row.message_id,
            role: role_name(row.role),
            content: &row.content,
        })
        .collect();
    group_embed_updated_events(&borrowed)
        .into_iter()
        .map(|item| match item {
            ChatHistoryItem::Message { index } => EmbedTimelineItemRecord::Message {
                index: index as u64,
                message_id: rows[index].message_id.clone(),
            },
            ChatHistoryItem::EmbedUpdated(group) => EmbedTimelineItemRecord::EmbedUpdated {
                group: group.into(),
            },
        })
        .collect()
}

/// A typed embed command result inside the actor: session losses go back to
/// `settle_auth` as core errors (so a rejected session signs out and a
/// verification request is announced), every other outcome stays typed.
fn split<T>(
    result: std::result::Result<T, EmbedEditError>,
) -> Result<std::result::Result<T, EmbedEditError>> {
    match result {
        Err(EmbedEditError::SessionExpired) => Err(Error::Expired),
        Err(EmbedEditError::Authentication) => Err(Error::Authentication),
        Err(EmbedEditError::VerificationRequired) => Err(Error::VerificationRequired),
        other => Ok(other),
    }
}

impl ViewModelCore {
    /// Run `work` on the signed-in client, holding the actor (so it never
    /// interleaves with open, send or sync), until it ends or `cancellation`
    /// fires (`Cancelled`; a commit already sent stays idempotent under its
    /// operation id).
    pub(crate) async fn embed_command<T, F>(
        &self,
        cancellation: Option<Arc<CoreCancellation>>,
        work: F,
    ) -> std::result::Result<T, EmbedEditError>
    where
        T: Send + 'static,
        F: for<'a> FnOnce(&'a mut Client) -> BoxFuture<'a, std::result::Result<T, EmbedEditError>>
            + Send
            + 'static,
    {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        let outcome = self
            .run(async move {
                shared
                    .signed_in(token, move |host, _sink, cancel| {
                        Box::pin(async move {
                            let client = host.core_mut().client_mut();
                            let typed = tokio::select! {
                                biased;
                                () = cancel.cancelled() => Err(EmbedEditError::Cancelled),
                                result = work(client) => result,
                            };
                            split(typed)
                        })
                    })
                    .await
            })
            .await;
        match outcome {
            Ok(typed) => typed,
            Err(error) => Err(error.into()),
        }
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// The version history of `embed_id` with who made each version
    /// (assistant or user, and the user's action), oldest first, read from
    /// the server (metadata only). `scope` is the chat or Project the embed
    /// is shown in (required for Team embeds; `nil` reads as the owner).
    /// Waits for a running command.
    ///
    /// # Errors
    /// `Authentication` signed out; `AccessDenied`, `NotFound`-like refusals
    /// as `AccessDenied { forbidden }`; `Offline`; `Transport { protocol }`
    /// for a malformed page; `Cancelled`.
    pub async fn embed_version_history(
        &self,
        embed_id: String,
        scope: Option<EmbedScopeRecord>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<EmbedVersionHistoryRecord, EmbedEditError> {
        let scope: Option<RevisionScope> = scope.map(Into::into);
        self.embed_command(cancellation, move |client| {
            Box::pin(async move {
                let history = client
                    .embed_version_history(&embed_id, scope.as_ref())
                    .await?;
                Ok(history.into())
            })
        })
        .await
    }

    /// Commit a user edit of a document, sheet, diagram or slides embed as
    /// its next version: `content` is the new head plaintext in its stored
    /// form (the TOON string the embed content opens to; zeroized after the
    /// call), `text_preview` the new preview when the type keeps one,
    /// `operation_id` the idempotency key of a resend of the same edit
    /// (`nil`: fresh). The head is the core's cached head (fetched once when
    /// not cached). Writes the chat's `embed_updated` event when the embed
    /// has a chat (`event`).
    ///
    /// # Errors
    /// `VersionConflict` (reload, then edit again), `ProjectContextRequired`,
    /// `AccessDenied`, `Validation`, `Refused`, `KeyUnavailable`, `Offline`,
    /// `SessionExpired`, `Cancelled`, `Transport`.
    pub async fn commit_embed_edit(
        &self,
        embed_id: String,
        scope: EmbedScopeRecord,
        content: String,
        text_preview: Option<String>,
        operation_id: Option<String>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<EmbedRevisionOutcomeRecord, EmbedEditError> {
        let content = Zeroizing::new(content);
        let text_preview = text_preview.map(Zeroizing::new);
        let scope: RevisionScope = scope.into();
        self.embed_command(cancellation, move |client| {
            Box::pin(async move {
                let (head, _) = client.embed_user_edit_head(&embed_id).await?;
                let request = UserRevisionRequest::content_edit(
                    head,
                    scope,
                    content,
                    text_preview,
                    operation_id,
                );
                let outcome = client.commit_embed_user_revision(request, None).await?;
                Ok(outcome.into())
            })
        })
        .await
    }

    /// Restore version `from_version` of `embed_id` as its next version
    /// (content and, for images, its files); every version stays in the
    /// history. Personal account only (the version read is Personal).
    ///
    /// # Errors
    /// `Validation { invalid_restored_from }` unless `1 <= from_version <
    /// head`; `Refused { restore_source_missing }`; otherwise as
    /// `commitEmbedEdit`.
    pub async fn restore_embed_version(
        &self,
        embed_id: String,
        scope: EmbedScopeRecord,
        from_version: i64,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<EmbedRevisionOutcomeRecord, EmbedEditError> {
        let scope: RevisionScope = scope.into();
        self.embed_command(cancellation, move |client| {
            Box::pin(async move {
                let (head, _) = client.embed_user_edit_head(&embed_id).await?;
                let outcome = client
                    .restore_embed_version(head, scope, from_version, None)
                    .await?;
                Ok(outcome.into())
            })
        })
        .await
    }

    /// Write the `embed_updated` events the server still lists as pending
    /// for `chat_id` (edits made in the Projects workspace or on another
    /// device). `openChat` already runs this once after the window is shown;
    /// call it again after a reconnect. Written events reach the window as
    /// new system messages. Offline, Team chats and refused reads come back
    /// as `deferred_code`, not as errors.
    ///
    /// # Errors
    /// `Authentication` signed out; `SessionExpired`; `Cancelled`.
    pub async fn reconcile_embed_update_notices(
        &self,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<EmbedNoticeReconcileRecord, EmbedEditError> {
        self.embed_command(cancellation, move |client| {
            Box::pin(async move {
                let report = client
                    .reconcile_embed_update_notices_on_open(&chat_id)
                    .await?;
                Ok(report.into())
            })
        })
        .await
    }
}
