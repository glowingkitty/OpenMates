//! Fixed, opt-in startup markers for the protected native timing benchmark.
use crate::{Error, Result};

/// A startup boundary whose probe never emits chat data or request strings.
#[derive(Clone, Copy)]
pub enum StartupPhase {
    SelectorRequest,
    SelectorDecode,
    ColdSidebarRequest,
    ColdSidebarDecode,
    ColdSidebarEnvelope,
    ColdSidebarId,
    ColdSidebarWrappers,
    ColdSidebarTimestamp,
    ColdSidebarRender,
    ColdSidebarPersist,
    ColdSidebarProjection,
    ColdSidebarPublish,
    Resume,
    Reconcile,
    Hydrate,
    LiveCanonicalRead,
    OpenedRecorded,
    OpenSelectionCompleted,
    AuthenticatedFrame,
}

impl StartupPhase {
    /// Emit only a phase, a fixed result class and monotonic milliseconds.
    pub fn record<T>(self, result: &Result<T>) {
        let phase = match self {
            Self::SelectorRequest => "selector_request",
            Self::SelectorDecode => "selector_decode",
            Self::ColdSidebarRequest => "cold_sidebar_request",
            Self::ColdSidebarDecode => "cold_sidebar_decode",
            Self::ColdSidebarEnvelope => "cold_sidebar_envelope",
            Self::ColdSidebarId => "cold_sidebar_id",
            Self::ColdSidebarWrappers => "cold_sidebar_wrappers",
            Self::ColdSidebarTimestamp => "cold_sidebar_timestamp",
            Self::ColdSidebarRender => "cold_sidebar_render",
            Self::ColdSidebarPersist => "cold_sidebar_persist",
            Self::ColdSidebarProjection => "cold_sidebar_projection",
            Self::ColdSidebarPublish => "cold_sidebar_publish",
            Self::Resume => "resume",
            Self::Reconcile => "reconcile",
            Self::Hydrate => "hydrate",
            Self::LiveCanonicalRead => "live_canonical_read",
            Self::OpenedRecorded => "opened_recorded",
            Self::OpenSelectionCompleted => "open_selection_completed",
            Self::AuthenticatedFrame => "authenticated_frame",
        };
        emit(phase, result.as_ref().err().copied());
    }

    /// Record a malformed protocol value without retaining it.
    pub fn protocol(self) -> Error {
        self.record(&Err::<(), _>(Error::Protocol));
        Error::Protocol
    }
}


fn emit(phase: &'static str, error: Option<Error>) {
    #[cfg(not(target_arch = "wasm32"))]
    {
        use std::{ffi::OsStr, io::Write, sync::OnceLock, time::Instant};
        static START: OnceLock<Instant> = OnceLock::new();
        if std::env::var_os("OPENMATES_TEST_STARTUP_PHASE_DIAGNOSTIC").as_deref() != Some(OsStr::new("1")) {
            return;
        }
        let outcome = match error {
            None => "ok",
            Some(Error::Protocol) => "protocol",
            Some(Error::Crypto) => "crypto",
            Some(Error::Offline) => "offline",
            Some(Error::Io) => "io",
            Some(Error::Cancelled) => "cancelled",
            Some(Error::Authentication | Error::Forbidden | Error::Expired) => "denied",
            Some(Error::Locked) => "locked",
            Some(Error::Invalid(_)) => "invalid",
            Some(Error::Conflict) => "conflict",
            Some(_) => "other",
        };
        let milliseconds = START.get_or_init(Instant::now).elapsed().as_millis();
        let _ = writeln!(std::io::stderr().lock(), "OPENMATES_STARTUP_STAGE {phase} {outcome} {milliseconds}");
    }
    #[cfg(target_arch = "wasm32")]
    let _ = (phase, error);
}

pub(crate) fn record_chat_row_conversion(error: &crate::view_model::ViewModelError) {
    use crate::view_model::ViewModelError::{InvalidField, MissingField, UnknownVariant};
    let (record, field) = match error {
        InvalidField { record, field } | MissingField { record, field } | UnknownVariant { record, field } => (*record, *field),
    };
    if record != "chat_row" {
        return;
    }
    let phase = match field {
        "id" => "list_convert_id",
        "status" => "list_convert_status",
        "chat_list_title" => "list_convert_title",
        "created_at" => "list_convert_created_at",
        "updated_at" => "list_convert_updated_at",
        "messages_v" => "list_convert_messages_version",
        "unread_count" => "list_convert_unread_count",
        "pinned" => "list_convert_pinned",
        "archived" => "list_convert_archived",
        "has_draft" => "list_convert_has_draft",
        "footer" => "list_convert_footer",
        _ => "list_convert_other",
    };
    emit(phase, Some(Error::Protocol));
}

pub(crate) enum ChatRowMetadataField {
    SubChatSettings,
    SharedByOthers,
    LastVisibleMessage,
    App,
    SubChatWait,
    SubChatReport,
    Parent,
    IsSubChat,
    IsShared,
    IsPrivate,
    IsHidden,
    LastMessageAt,
    LastEditedAt,
    BudgetLimit,
    BudgetSpent,
    DraftVersion,
    Team,
    Key,
    Icon,
    ActiveFocus,
    DraftPreview,
}

impl ChatRowMetadataField {
    pub(crate) fn observe<T>(self, result: Result<T>) -> Result<T> {
        if let Err(error) = result.as_ref() {
            let phase = match self {
                Self::SubChatSettings => "list_meta_sub_chat_settings",
                Self::SharedByOthers => "list_meta_shared_by_others",
                Self::LastVisibleMessage => "list_meta_last_visible_message",
                Self::App => "list_meta_app",
                Self::SubChatWait => "list_meta_sub_chat_wait",
                Self::SubChatReport => "list_meta_sub_chat_report",
                Self::Parent => "list_meta_parent",
                Self::IsSubChat => "list_meta_is_sub_chat",
                Self::IsShared => "list_meta_is_shared",
                Self::IsPrivate => "list_meta_is_private",
                Self::IsHidden => "list_meta_is_hidden",
                Self::LastMessageAt => "list_meta_last_message_at",
                Self::LastEditedAt => "list_meta_last_edited_at",
                Self::BudgetLimit => "list_meta_budget_limit",
                Self::BudgetSpent => "list_meta_budget_spent",
                Self::DraftVersion => "list_meta_draft_version",
                Self::Team => "list_meta_team",
                Self::Key => "list_meta_key",
                Self::Icon => "list_meta_icon",
                Self::ActiveFocus => "list_meta_active_focus",
                Self::DraftPreview => "list_meta_draft_preview",
            };
            emit(phase, Some(*error));
        }
        result
    }
}
