//! User-made embed versions (shared client core; spec `feature.embed-user-edits`,
//! assertions `edit.next-version`, `history.one-per-embed`, `restore.creates-version`).
//! Builds and commits `POST /v1/embeds/{embed_id}/user-revisions` for chat or
//! Project scope: encrypt with the embed key, compare-and-swap on the cached
//! head, full-snapshot history rows, idempotent retry, local cache only after
//! the committed receipt. Replaces `frontend/packages/ui/src/services/embedUserRevision.ts`
//! (legacy `commit_chat_diagram_revision`) and `embedDiffStore.commitEmbedContentRevision`.
//! Server contract: `backend/core/api/app/routes/embed_user_revisions.py` and the
//! `embed-version-transaction` operation `commitUserEmbedRevision`.
use super::embed_updated_event::{
    EmbedEventIdentity, EmbedUpdateAction, EmbedUpdateSurface, EmbedUpdatedEvent,
};
use super::embed_write::history::EncryptedDiffRow;
use super::embed_write::keys::{NonceSource, encrypt_text, hash_id};
use crate::error::Error;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::fmt;
use zeroize::Zeroizing;

#[path = "embed_user_edit_client.rs"]
mod client_io;
#[path = "embed_user_revision_refusal.rs"]
pub(crate) mod refusal;
#[path = "embed_user_restore.rs"]
mod restore;
pub use client_io::{EmbedRevisionOutcome, EventDelivery};

/// Highest version the server accepts (`MAX_VERSION` of the route).
pub const MAX_REVISION: i64 = 2_147_483_647;
/// Largest ciphertext field the route accepts (4 MiB).
pub const MAX_CIPHERTEXT_CHARS: usize = 4 * 1024 * 1024;

/// Why a user revision was not saved. Every variant has a stable [`code`](Self::code)
/// matching the server's error code where the server named one.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum UserRevisionError {
    /// The head moved: another device or the assistant saved a newer version.
    /// Carries the server's current head so the shell can reload it.
    VersionConflict {
        /// Server head version, when the server reported it.
        current_revision: Option<i64>,
        /// SHA-256 of the server head's encrypted content, when reported.
        current_content_hash: Option<String>,
    },
    /// A Project-linked embed was committed in chat scope; retry in Project scope.
    ProjectContextRequired,
    /// The account may not edit this embed in this scope (`project_access_denied`,
    /// `chat_access_denied`, `embed_type_not_editable`, `foreign_file_key`, ...).
    AccessDenied {
        /// Server code, or `forbidden` when the server named none.
        code: &'static str,
    },
    /// The request was malformed or refused as invalid (local checks and 400s).
    Validation {
        /// Stable code (`invalid_action`, `media_index_required`, ...).
        code: &'static str,
    },
    /// The server still lacks version N after the base snapshot was sent.
    BaseSnapshotRequired,
    /// Another stable refusal (`operation_payload_mismatch`, `restore_source_missing`,
    /// `immutable_history_mismatch`, `enhance_result_*`, `embed_not_found`).
    Refused {
        /// Server code.
        code: &'static str,
    },
    /// The embed key is not available on this device.
    KeyUnavailable,
    /// Transport, session, crypto or protocol failure; nothing is known to be
    /// committed unless a retry with the same operation reports it.
    Transport(Error),
}

impl UserRevisionError {
    /// Stable code for shells and bindings.
    pub fn code(&self) -> &'static str {
        match self {
            Self::VersionConflict { .. } => "embed_version_conflict",
            Self::ProjectContextRequired => "project_context_required",
            Self::AccessDenied { code } | Self::Validation { code } | Self::Refused { code } => {
                code
            }
            Self::BaseSnapshotRequired => "base_snapshot_required",
            Self::KeyUnavailable => "embed_key_unavailable",
            Self::Transport(Error::Offline) => "offline",
            Self::Transport(Error::Expired) => "session_expired",
            Self::Transport(Error::Cancelled) => "cancelled",
            Self::Transport(Error::Crypto) => "encryption_failed",
            Self::Transport(_) => "transport_failed",
        }
    }
}

impl fmt::Display for UserRevisionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::VersionConflict { .. } => {
                f.write_str("The embed changed on another device. Reload before editing.")
            }
            Self::ProjectContextRequired => {
                f.write_str("This embed belongs to a Project. Save it from the Project.")
            }
            Self::AccessDenied { .. } => f.write_str("You cannot edit this embed here."),
            Self::KeyUnavailable => {
                f.write_str("The embed's encryption key is unavailable on this device.")
            }
            Self::Transport(error) => write!(f, "{error}"),
            other => write!(f, "The edit was not saved ({}).", other.code()),
        }
    }
}

impl std::error::Error for UserRevisionError {}

impl From<Error> for UserRevisionError {
    fn from(error: Error) -> Self {
        Self::Transport(error)
    }
}

/// Result type of this module.
pub type RevisionResult<T> = std::result::Result<T, UserRevisionError>;

/// Where the version is saved. Project-linked embeds are accepted only in
/// Project scope; the server answers `project_context_required` otherwise.
/// Deserializes from the same wire form [`Self::wire`] writes
/// (`{kind: "chat", chat_id, team_id?}` | `{kind: "project", project_id,
/// team_id?}`), which is how bindings pass it in.
#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RevisionScope {
    /// The embed's chat (owner, or Team owner/admin/member with `team_id`).
    Chat {
        /// Chat id.
        chat_id: String,
        /// Team of a Team chat.
        team_id: Option<String>,
    },
    /// A Project that links the embed (Project write access).
    Project {
        /// Project id.
        project_id: String,
        /// Team of a Team Project.
        team_id: Option<String>,
    },
}

impl RevisionScope {
    /// Wire form `{kind, chat_id|project_id, team_id?}`, shared by the
    /// user-revision commit and `POST /v1/images/enhance`.
    pub(crate) fn wire(&self) -> Value {
        let (kind, field, id, team) = match self {
            Self::Chat { chat_id, team_id } => ("chat", "chat_id", chat_id, team_id),
            Self::Project {
                project_id,
                team_id,
            } => ("project", "project_id", project_id, team_id),
        };
        let mut scope = json!({"kind": kind, field: id});
        if let Some(team) = team {
            scope["team_id"] = json!(team);
        }
        scope
    }

    /// Event surface of a commit in this scope.
    pub fn surface(&self) -> EmbedUpdateSurface {
        match self {
            Self::Chat { .. } => EmbedUpdateSurface::Chat,
            Self::Project { .. } => EmbedUpdateSurface::Project,
        }
    }
}

/// One S3 object of the embed (`embeds.s3_file_keys` entry).
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct FileRef {
    /// Bucket.
    pub bucket: String,
    /// Object key.
    pub key: String,
}

/// Files of a file-backed (image) version.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RevisionFiles {
    /// Files the embed already owns (restore of version K: K's keys).
    HeadFileKeys(Vec<FileRef>),
    /// The result of an Enhance job started in the same scope.
    Enhance {
        /// The Enhance job's operation id.
        operation_id: String,
    },
}

/// The cached head the edit was made on (the local cache row). Its
/// ciphertext is the compare-and-swap base: the server hashes its stored
/// `encrypted_content` the same way.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EmbedHead {
    /// Embed id.
    pub embed_id: String,
    /// Head version N (absent `version_number` means 1).
    pub version: i64,
    /// Head `encrypted_content` exactly as cached.
    pub encrypted_content: String,
    /// Unix seconds of the head, used when the server needs its snapshot row.
    pub created_at: i64,
    /// `hashed_chat_id` of the head, when the embed has a chat.
    pub hashed_chat_id: Option<String>,
}

impl EmbedHead {
    /// Read a cached `embeds` row (`embed_id`, `version_number`,
    /// `encrypted_content`, `updated_at`/`created_at`, `hashed_chat_id`).
    ///
    /// # Errors
    /// `Validation { code: "invalid_head" }` for another embed, a missing
    /// ciphertext or a malformed version.
    pub fn from_cached_row(embed_id: &str, row: &Value, now_seconds: i64) -> RevisionResult<Self> {
        let invalid = UserRevisionError::Validation {
            code: "invalid_head",
        };
        let object = row.as_object().ok_or(invalid.clone())?;
        if object
            .get("embed_id")
            .and_then(Value::as_str)
            .is_some_and(|id| id != embed_id)
        {
            return Err(invalid);
        }
        let version = super::embed_write::pinned::head_version(row).map_err(|_| invalid.clone())?;
        let encrypted_content = text_field(object, "encrypted_content")
            .ok_or(invalid)?
            .to_owned();
        let stamp = ["updated_at", "updatedAt", "created_at", "createdAt"]
            .iter()
            .find_map(|name| object.get(*name).filter(|value| !value.is_null()));
        Ok(Self {
            embed_id: embed_id.to_owned(),
            version,
            encrypted_content,
            created_at: super::embed_write::normalize_to_unix_seconds(stamp, now_seconds),
            hashed_chat_id: text_field(object, "hashed_chat_id").map(str::to_owned),
        })
    }
}

fn text_field<'a>(object: &'a Map<String, Value>, name: &str) -> Option<&'a str> {
    object
        .get(name)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
}

/// One user-made version to commit. Plaintext fields are zeroized on drop.
pub struct UserRevisionRequest {
    /// The head the edit was made on.
    pub head: EmbedHead,
    /// Where it is saved.
    pub scope: RevisionScope,
    /// What the user did.
    pub action: EmbedUpdateAction,
    /// New head content in its stored plaintext form (the string that
    /// `encrypted_content` opens to, e.g. TOON).
    pub content: Zeroizing<String>,
    /// New text preview, when the embed type keeps one.
    pub text_preview: Option<Zeroizing<String>>,
    /// Version K a restore copies (required for restore, forbidden otherwise).
    pub restored_from: Option<i64>,
    /// Files of a file-backed version.
    pub files: Option<RevisionFiles>,
    /// Server-readable image index of the new head (required with `files`).
    pub media_index: Option<Value>,
    /// Idempotency key; a fresh UUID when `None`. Reuse it only to resend the
    /// exact same edit.
    pub operation_id: Option<String>,
}

impl UserRevisionRequest {
    /// A content edit (action `edit`) of a file-less embed: diagram, slides,
    /// sheet or document. `content` is the new head plaintext in its stored
    /// form (the string `encrypted_content` opens to), `text_preview` the new
    /// preview when the type keeps one, `operation_id` the idempotency key of
    /// a resend of the same edit (fresh when `None`). Image edits carry files
    /// and are built by Enhance, crop and restore instead.
    pub fn content_edit(
        head: EmbedHead,
        scope: RevisionScope,
        content: Zeroizing<String>,
        text_preview: Option<Zeroizing<String>>,
        operation_id: Option<String>,
    ) -> Self {
        Self {
            head,
            scope,
            action: EmbedUpdateAction::Edit,
            content,
            text_preview,
            restored_from: None,
            files: None,
            media_index: None,
            operation_id,
        }
    }

    /// Restore version `from` as the next version: `content` is version K's
    /// snapshot plaintext (read with the existing version-content reads) and,
    /// for file-backed embeds, `file_keys` are K's files.
    pub fn restore(
        head: EmbedHead,
        scope: RevisionScope,
        from: i64,
        content: Zeroizing<String>,
        text_preview: Option<Zeroizing<String>>,
        file_keys: Option<(Vec<FileRef>, Value)>,
    ) -> Self {
        let (files, media_index) = match file_keys {
            Some((keys, index)) => (Some(RevisionFiles::HeadFileKeys(keys)), Some(index)),
            None => (None, None),
        };
        Self {
            head,
            scope,
            action: EmbedUpdateAction::Restore,
            content,
            text_preview,
            restored_from: Some(from),
            files,
            media_index,
            operation_id: None,
        }
    }
}

/// A sealed revision ready to send. Holds only ciphertext and hashes. The
/// body is fixed once prepared: a resend after a lost response sends the
/// same bytes under the same `operation_id`, which the server answers with
/// its stored receipt (`idempotent: true`) instead of a second version.
#[derive(Clone, Debug)]
pub struct PreparedUserRevision {
    embed_id: String,
    operation_id: String,
    base_version: i64,
    action: EmbedUpdateAction,
    restored_from: Option<i64>,
    surface: EmbedUpdateSurface,
    hashed_chat_id: Option<String>,
    head_ciphertext: String,
    preview_ciphertext: Option<String>,
    content_hash: String,
    created_at: i64,
    body: Value,
    base_row: EncryptedDiffRow,
    next_row: EncryptedDiffRow,
    with_base: bool,
}

impl PreparedUserRevision {
    /// Operation id of this commit.
    pub fn operation_id(&self) -> &str {
        &self.operation_id
    }

    /// Version this commit creates (N+1).
    pub fn version(&self) -> i64 {
        self.base_version + 1
    }

    /// The request body as it is sent now (with the base row once the server asked).
    pub fn body(&self) -> &Value {
        &self.body
    }

    /// Add the version-N snapshot after `base_snapshot_required`. It reuses the
    /// cached head ciphertext: version N's snapshot plaintext is its head content.
    fn include_base(&mut self) {
        if self.with_base {
            return;
        }
        self.with_base = true;
        self.body["history_rows"] = json!([row_wire(&self.base_row), row_wire(&self.next_row)]);
    }
}

/// A full-snapshot `embed_diffs` row in the local cache shape (id
/// `${embed_id}_v${n}`), marked server-confirmed: it is used only once the
/// server's receipt says it holds exactly this row.
fn snapshot_row(
    embed_id: &str,
    version: i64,
    ciphertext: &str,
    created_at: i64,
) -> EncryptedDiffRow {
    EncryptedDiffRow {
        id: format!("{embed_id}_v{version}"),
        embed_id: embed_id.to_owned(),
        version_number: version,
        encrypted_snapshot: Some(ciphertext.to_owned()),
        encrypted_patch: None,
        created_at,
        server_confirmed: true,
    }
}

fn row_wire(row: &EncryptedDiffRow) -> Value {
    json!({
        "version_number": row.version_number,
        "encrypted_snapshot": row.encrypted_snapshot,
        "created_at": row.created_at,
    })
}

fn valid_operation_id(value: &str) -> bool {
    (1..=128).contains(&value.len())
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b':' | b'-'))
}

fn validation(code: &'static str) -> UserRevisionError {
    UserRevisionError::Validation { code }
}

fn validate(request: &UserRevisionRequest) -> RevisionResult<()> {
    let head = &request.head;
    if head.embed_id.is_empty() || head.embed_id.len() > 512 {
        return Err(validation("invalid_embed_id"));
    }
    if !(1..MAX_REVISION).contains(&head.version) {
        return Err(validation("invalid_expected_revision"));
    }
    if head.encrypted_content.is_empty() {
        return Err(validation("invalid_head"));
    }
    if request.content.is_empty() {
        return Err(validation("invalid_ciphertext"));
    }
    match (request.action, request.restored_from) {
        (EmbedUpdateAction::Restore, Some(from)) if (1..=head.version).contains(&from) => {}
        (EmbedUpdateAction::Restore, _) => return Err(validation("invalid_restored_from")),
        (_, Some(_)) => return Err(validation("invalid_restored_from")),
        _ => {}
    }
    let (id, team) = match &request.scope {
        RevisionScope::Chat { chat_id, team_id } => (chat_id, team_id),
        RevisionScope::Project {
            project_id,
            team_id,
        } => (project_id, team_id),
    };
    if id.is_empty()
        || id.len() > 512
        || team.as_ref().is_some_and(|t| t.is_empty() || t.len() > 512)
    {
        return Err(validation("invalid_scope"));
    }
    match (&request.files, &request.media_index) {
        (Some(_), None) => return Err(validation("media_index_required")),
        (None, Some(_)) => return Err(validation("invalid_media_index")),
        (Some(_), Some(index)) if !index.is_object() => {
            return Err(validation("invalid_media_index"));
        }
        _ => {}
    }
    match &request.files {
        Some(RevisionFiles::HeadFileKeys(keys))
            if keys.is_empty()
                || keys.len() > 64
                || keys.iter().any(|k| k.bucket.is_empty() || k.key.is_empty()) =>
        {
            return Err(validation("invalid_file_reference"));
        }
        Some(RevisionFiles::Enhance { operation_id }) if !valid_operation_id(operation_id) => {
            return Err(validation("invalid_operation_id"));
        }
        Some(RevisionFiles::Enhance { .. }) if request.action != EmbedUpdateAction::Enhance => {
            return Err(validation("invalid_file_source"));
        }
        None if request.action == EmbedUpdateAction::Enhance => {
            return Err(validation("file_source_required"));
        }
        _ => {}
    }
    if request
        .operation_id
        .as_deref()
        .is_some_and(|id| !valid_operation_id(id))
    {
        return Err(validation("invalid_operation_id"));
    }
    Ok(())
}

/// Seal `request` with the embed key into the exact route body.
///
/// - `expected_content_hash` = SHA-256 hex of the cached head's
///   `encrypted_content` (the server hashes its stored head the same way).
/// - Content and preview are encrypted with the embed key (MetadataEncryptor
///   layout, empty AAD); the history row N+1 reuses the head ciphertext, since
///   a version's snapshot plaintext is its head content.
/// - `history_rows` holds only N+1; N is added when the server asks.
///
/// # Errors
/// `Validation` for a request the server would refuse; `Transport(Crypto)`
/// when encryption fails.
pub fn prepare_user_revision(
    request: &UserRevisionRequest,
    embed_key: &[u8; 32],
    now_ms: i64,
    nonces: &mut impl NonceSource,
) -> RevisionResult<PreparedUserRevision> {
    validate(request)?;
    let head = &request.head;
    let now_seconds = now_ms.div_euclid(1000);
    let head_ciphertext = encrypt_text(&request.content, embed_key, None, nonces)?;
    let preview_ciphertext = match &request.text_preview {
        Some(preview) => Some(encrypt_text(preview, embed_key, None, nonces)?),
        None => None,
    };
    if head_ciphertext.len() > MAX_CIPHERTEXT_CHARS
        || preview_ciphertext
            .as_ref()
            .is_some_and(|p| p.len() > MAX_CIPHERTEXT_CHARS)
    {
        return Err(validation("invalid_ciphertext"));
    }
    let content_hash = hash_id(&head_ciphertext);
    let operation_id = request
        .operation_id
        .clone()
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    let next = head.version + 1;
    let next_row = snapshot_row(&head.embed_id, next, &head_ciphertext, now_seconds);
    let base_row = snapshot_row(
        &head.embed_id,
        head.version,
        &head.encrypted_content,
        head.created_at,
    );
    let mut wire_head = json!({
        "encrypted_content": head_ciphertext,
        "content_hash": content_hash,
        "status": "finished",
        "updated_at": now_seconds,
    });
    if let Some(preview) = &preview_ciphertext {
        wire_head["encrypted_text_preview"] = json!(preview);
    }
    let mut body = json!({
        "operation_id": operation_id,
        "scope": request.scope.wire(),
        "action": request.action.as_str(),
        "expected_revision": head.version,
        "expected_content_hash": hash_id(&head.encrypted_content),
        "head": wire_head,
        "history_rows": [row_wire(&next_row)],
    });
    if let Some(from) = request.restored_from {
        body["restored_from"] = json!(from);
    }
    match &request.files {
        Some(RevisionFiles::HeadFileKeys(keys)) => body["files"] = json!({"head_file_keys": keys}),
        Some(RevisionFiles::Enhance { operation_id }) => {
            body["files"] =
                json!({"new_files": [{"kind": "enhance", "operation_id": operation_id}]});
        }
        None => {}
    }
    if let Some(index) = &request.media_index {
        body["media_index"] = index.clone();
    }
    Ok(PreparedUserRevision {
        embed_id: head.embed_id.clone(),
        operation_id,
        base_version: head.version,
        action: request.action,
        restored_from: request.restored_from,
        surface: request.scope.surface(),
        hashed_chat_id: head.hashed_chat_id.clone(),
        head_ciphertext,
        preview_ciphertext,
        content_hash,
        created_at: now_seconds,
        body,
        base_row,
        next_row,
        with_base: false,
    })
}

/// The committed version as the local cache stores it. Ciphertext only.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CommittedUserRevision {
    /// Embed id.
    pub embed_id: String,
    /// Operation id of the commit.
    pub operation_id: String,
    /// New head version (N+1).
    pub version: i64,
    /// Version it was made from (N).
    pub base_version: i64,
    /// What the user did.
    pub action: EmbedUpdateAction,
    /// Version a restore copied.
    pub restored_from: Option<i64>,
    /// Where it was saved.
    pub surface: EmbedUpdateSurface,
    /// New head `encrypted_content`.
    pub encrypted_content: String,
    /// New head `encrypted_text_preview`, when sent.
    pub encrypted_text_preview: Option<String>,
    /// SHA-256 of `encrypted_content` (the server's `current_content_hash`).
    pub content_hash: String,
    /// Unix seconds of the commit (head `updated_at`, row `created_at`).
    pub updated_at: i64,
    /// History rows the server now holds for this commit (N+1, plus N when sent).
    pub history_rows: Vec<EncryptedDiffRow>,
    /// True when the server answered from an earlier receipt of this operation.
    pub idempotent: bool,
    /// True when the server wrote a pending chat notice (the embed has a chat).
    pub pending_notice: bool,
    /// `hashed_chat_id` of the head (finds the home chat of a Project edit).
    pub hashed_chat_id: Option<String>,
    /// Whether the server repointed the image index to the new files.
    pub media_index_repointed: bool,
}

impl CommittedUserRevision {
    /// The `embed_updated` event of this version for `identity`, at `created_at`.
    pub fn event(&self, identity: &EmbedEventIdentity) -> EmbedUpdatedEvent {
        EmbedUpdatedEvent::new(
            &self.embed_id,
            identity,
            self.version,
            Some(self.base_version),
            self.action,
            self.restored_from,
            self.surface,
            self.updated_at,
        )
    }

    /// Apply this version to a cached `embeds` row (head fields only; the
    /// row keeps its key wrappers, type and chat/message hashes).
    ///
    /// # Errors
    /// `Transport(Protocol)` when `row` is not an object.
    pub fn apply_to_cached_row(&self, row: &mut Value) -> RevisionResult<()> {
        let object = row.as_object_mut().ok_or(Error::Protocol)?;
        object.insert("encrypted_content".into(), json!(self.encrypted_content));
        if let Some(preview) = &self.encrypted_text_preview {
            object.insert("encrypted_text_preview".into(), json!(preview));
        }
        object.insert("version_number".into(), json!(self.version));
        object.insert("content_hash".into(), json!(self.content_hash));
        object.insert("status".into(), json!("finished"));
        object.insert("updated_at".into(), json!(self.updated_at));
        Ok(())
    }
}

/// IO of one commit: the authenticated POST and the local cache write.
#[allow(async_fn_in_trait)] // Crate-internal seam; callers are generic, never `dyn`.
pub trait UserRevisionIo {
    /// POST `body` to `/v1/embeds/{embed_id}/user-revisions` and return the
    /// 200 body.
    ///
    /// # Errors
    /// The typed refusal of the server, or `Transport` when no answer arrived.
    async fn post_user_revision(&mut self, embed_id: &str, body: &Value) -> RevisionResult<Value>;

    /// Store the committed head and history rows in the local cache. Called
    /// only after the server's committed receipt.
    ///
    /// # Errors
    /// Local storage errors.
    async fn store_committed(
        &mut self,
        committed: &CommittedUserRevision,
    ) -> crate::error::Result<()>;
}

/// Result of [`commit_prepared`].
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct UserRevisionCommit {
    /// The committed version.
    pub committed: CommittedUserRevision,
    /// False when the commit is durable on the server but the local cache
    /// write failed: the shell must refresh the embed from the server before
    /// the next edit (the next save would otherwise conflict).
    pub cache_synchronized: bool,
}

fn receipt(
    prepared: &PreparedUserRevision,
    response: &Value,
) -> RevisionResult<CommittedUserRevision> {
    let field = |name: &str| response.get(name).and_then(Value::as_str);
    if field("status") != Some("committed")
        || field("operation_id") != Some(prepared.operation_id.as_str())
        || field("embed_id") != Some(prepared.embed_id.as_str())
        || field("revision_origin") != Some("user")
        || response.get("current_revision").and_then(Value::as_i64) != Some(prepared.version())
        || field("current_content_hash") != Some(prepared.content_hash.as_str())
    {
        return Err(Error::Protocol.into());
    }
    let flag = |name: &str| {
        response
            .get(name)
            .and_then(Value::as_bool)
            .ok_or(UserRevisionError::Transport(Error::Protocol))
    };
    let mut history_rows = Vec::with_capacity(2);
    if prepared.with_base {
        history_rows.push(prepared.base_row.clone());
    }
    history_rows.push(prepared.next_row.clone());
    Ok(CommittedUserRevision {
        embed_id: prepared.embed_id.clone(),
        operation_id: prepared.operation_id.clone(),
        version: prepared.version(),
        base_version: prepared.base_version,
        action: prepared.action,
        restored_from: prepared.restored_from,
        surface: prepared.surface,
        encrypted_content: prepared.head_ciphertext.clone(),
        encrypted_text_preview: prepared.preview_ciphertext.clone(),
        content_hash: prepared.content_hash.clone(),
        updated_at: prepared.created_at,
        history_rows,
        idempotent: flag("idempotent")?,
        pending_notice: flag("pending_notice")?,
        hashed_chat_id: prepared.hashed_chat_id.clone(),
        media_index_repointed: flag("media_index_repointed")?,
    })
}

/// Commit `prepared` and then update the local cache.
///
/// Order: POST (N+1 row only) -> on `base_snapshot_required` resend once with
/// the version-N snapshot -> on a lost answer (`Transport(Offline)`) resend
/// once with the identical body under the same operation id -> verify the
/// receipt (operation, embed, version N+1, content hash) -> store in the
/// local cache. A refusal leaves the local cache untouched, so a retry starts
/// from the same base.
///
/// # Errors
/// The typed refusal of the last attempt; `Transport(Protocol)` for a receipt
/// that does not match the request.
pub async fn commit_prepared<I: UserRevisionIo>(
    io: &mut I,
    mut prepared: PreparedUserRevision,
) -> RevisionResult<UserRevisionCommit> {
    let mut resent_after_loss = false;
    let response = loop {
        match io
            .post_user_revision(&prepared.embed_id, &prepared.body)
            .await
        {
            Ok(response) => break response,
            Err(UserRevisionError::BaseSnapshotRequired) if !prepared.with_base => {
                prepared.include_base()
            }
            Err(UserRevisionError::Transport(Error::Offline)) if !resent_after_loss => {
                resent_after_loss = true
            }
            Err(error) => return Err(error),
        }
    };
    let committed = receipt(&prepared, &response)?;
    let cache_synchronized = io.store_committed(&committed).await.is_ok();
    Ok(UserRevisionCommit {
        committed,
        cache_synchronized,
    })
}

#[cfg(test)]
#[path = "embed_user_revision_tests.rs"]
mod tests;
