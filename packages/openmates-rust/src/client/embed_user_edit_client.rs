//! Signed-in [`Client`] adapters of user-made embed versions (shared core; spec
//! `feature.embed-user-edits`): the authenticated user-revision POST with typed
//! refusals, the in-memory embed cache update after the receipt, the
//! chat-key encrypted `embed_updated` system message (same send-and-confirm as
//! the Memory notices in `memory_write_jobs`) and the pending-notice reconcile
//! run when a chat window opens (`view_model::window_flows::open_window`).
use super::{
    RevisionResult, RevisionScope, UserRevisionCommit, UserRevisionError, UserRevisionIo,
    UserRevisionRequest, commit_prepared, prepare_user_revision,
};
use crate::client::embed_updated_event::{
    EmbedEventIdentity, EmbedKind, EmbedUpdatedWriter, EventWrite, NoticeReconcileReport,
    SystemEventSink, parse_pending_notices, reconcile_notices, valid_embed_ref,
};
use crate::client::embed_write::keys::OsNonces;
use crate::client::transport::{Socket, send, wait};
use crate::client::{Client, now_ms, segment, sha256, text};
use crate::crypto;
use crate::error::{Error, Result};
use reqwest::Method;
use serde::Serialize;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::time::Duration;

/// The server confirms a stored system message well within this.
const CONFIRM_TIMEOUT: Duration = Duration::from_secs(10);

/// What happened to the chat event of a committed version.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum EventDelivery {
    /// Written and confirmed now.
    Written,
    /// This device already wrote it (or the chat already shows it).
    AlreadyWritten,
    /// The embed has no chat (a Project-only file): no chat event exists.
    NoChat,
    /// Not written now; the server keeps the pending notice and the next
    /// chat open on any device of the chat writes it.
    Deferred {
        /// Why (`home_chat_unavailable`, `embed_identity_unavailable`, or the
        /// write's error code).
        code: &'static str,
    },
}

/// Result of [`Client::commit_embed_user_revision`].
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct EmbedRevisionOutcome {
    /// The committed version and whether the local cache holds it.
    pub commit: UserRevisionCommit,
    /// The chat event of the version.
    pub event: EventDelivery,
}

fn transport_error(error: Error) -> UserRevisionError {
    match error {
        Error::Forbidden => UserRevisionError::AccessDenied { code: "forbidden" },
        Error::Invalid(_) => UserRevisionError::Validation {
            code: "invalid_request",
        },
        Error::Conflict => UserRevisionError::Refused { code: "conflict" },
        other => UserRevisionError::Transport(other),
    }
}

fn error_code(error: &Error) -> &'static str {
    match error {
        Error::Offline => "offline",
        Error::Expired => "session_expired",
        Error::Forbidden => "forbidden",
        Error::Cancelled => "cancelled",
        Error::Crypto => "chat_key_unavailable",
        Error::Unavailable { code, .. } => code,
        _ => "event_write_failed",
    }
}

/// Commit transport and cache of the signed-in client.
struct ClientRevisionIo<'a> {
    client: &'a mut Client,
}

impl UserRevisionIo for ClientRevisionIo<'_> {
    async fn post_user_revision(&mut self, embed_id: &str, body: &Value) -> RevisionResult<Value> {
        // A refusal is recorded by the transport for this route only; clear an
        // older one so a network failure is never read as a refusal.
        self.client.embed_user_revision_refusal = None;
        let path = format!("/v1/embeds/{}/user-revisions", segment(embed_id));
        let result = self
            .client
            .request(Method::POST, &path, Some(body.clone()))
            .await;
        match result {
            Ok(value) => Ok(value),
            Err(error) => Err(match self.client.embed_user_revision_refusal.take() {
                Some(refusal) => refusal.into_error(),
                None => transport_error(error),
            }),
        }
    }

    async fn store_committed(&mut self, committed: &super::CommittedUserRevision) -> Result<()> {
        // The client's cache holds heads it opened; an uncached embed has
        // nothing stale to update.
        if let Some(row) = self.client.embeds.get_mut(&committed.embed_id) {
            committed
                .apply_to_cached_row(row)
                .map_err(|_| Error::Protocol)?;
        }
        Ok(())
    }
}

/// System-message transport of the signed-in client; one socket per batch.
struct ClientEventSink<'a> {
    client: &'a mut Client,
    ws: Option<Socket>,
}

impl ClientEventSink<'_> {
    async fn close(self) {
        if let Some(mut ws) = self.ws {
            let _ =
                crate::platform::time::timeout(Duration::from_millis(100), ws.close(None)).await;
        }
    }
}

impl SystemEventSink for ClientEventSink<'_> {
    async fn write_system_message(
        &mut self,
        chat_id: &str,
        message_id: &str,
        content: &str,
        created_at: i64,
    ) -> Result<()> {
        let key = match self.client.chats.get(chat_id).cloned() {
            Some(row) => {
                let wrapping = self.client.wrapping_key().await?;
                self.client.chat_key(&row, &wrapping)?
            }
            None => self.client.work_chat_key(chat_id).await?,
        };
        // Same shape as the web `chat_system_message_added` write and the
        // Memory notice; the deterministic id makes a duplicate a no-op.
        let mut payload = json!({"chat_id": chat_id, "message": {
            "message_id": message_id, "chat_id": chat_id, "role": "system",
            "encrypted_content": crypto::encrypt_combined(content, &key)?,
            "created_at": created_at, "status": "synced"}});
        if let Some(team) = self.client.team()? {
            payload["team_id"] = json!(team);
        }
        if self.ws.is_none() {
            self.ws = Some(self.client.socket_with_task_jobs(false).await?);
        }
        let ws = self.ws.as_mut().ok_or(Error::Offline)?;
        send(ws, "chat_system_message_added", payload).await?;
        crate::platform::time::timeout(
            CONFIRM_TIMEOUT,
            wait(ws, "system_message_confirmed", "message_id", message_id),
        )
        .await
        .map_err(|_| Error::Offline)??;
        Ok(())
    }
}

impl Client {
    /// Message ids already in the cached history of `chat_id`.
    fn history_message_ids(&self, chat_id: &str) -> BTreeSet<String> {
        self.history
            .get(chat_id)
            .into_iter()
            .flatten()
            .filter_map(|row| {
                ["client_message_id", "message_id", "id"]
                    .into_iter()
                    .map(|field| text(row, field))
                    .find(|id| !id.is_empty())
                    .map(str::to_owned)
            })
            .collect()
    }

    /// Ref and kind of a cached embed from its decrypted content (`embed_ref`,
    /// `app_id`, `skill_id`); `None` when the embed is not cached here, its key
    /// is unavailable, or its type is not user-editable.
    fn embed_event_identity(
        &self,
        embed_id: &str,
        wrapping: &[u8; 32],
    ) -> Option<EmbedEventIdentity> {
        let item = self.decrypt_embed_item(embed_id, wrapping).ok()?;
        let content = &item.fields["content"];
        let embed_kind =
            EmbedKind::from_app_skill(text(content, "app_id"), text(content, "skill_id"))?;
        let embed_ref = text(content, "embed_ref");
        valid_embed_ref(embed_ref).then(|| EmbedEventIdentity {
            embed_ref: embed_ref.to_owned(),
            embed_kind,
        })
    }

    /// Commit one user-made version of an embed (edit, restore, crop or an
    /// Enhance result) through `POST /v1/embeds/{embed_id}/user-revisions`,
    /// then write its `embed_updated` chat event when the embed has a chat.
    ///
    /// The embed key comes from the client's embed cache and wrappers (open
    /// the embed first); shells that own their own key session call
    /// [`prepare_user_revision`] and [`commit_prepared`] directly. `identity`
    /// names the embed for the event; when `None` it is read from the cached
    /// embed content.
    ///
    /// # Errors
    /// [`UserRevisionError`]: `KeyUnavailable`, `VersionConflict` (with the
    /// server head), `ProjectContextRequired`, `AccessDenied`, `Validation`,
    /// `Refused`, `Transport`. A failed event write is not an error of the
    /// durable commit; it is reported as [`EventDelivery::Deferred`].
    pub async fn commit_embed_user_revision(
        &mut self,
        request: UserRevisionRequest,
        identity: Option<EmbedEventIdentity>,
    ) -> RevisionResult<EmbedRevisionOutcome> {
        self.require_session()?;
        self.verify_private_operation()?;
        let wrapping = self.wrapping_key().await?;
        let key = match self.embed_key(&request.head.embed_id, &wrapping, &mut HashSet::new()) {
            Ok(key) => key,
            Err(Error::Forbidden | Error::Protocol) => {
                return Err(UserRevisionError::KeyUnavailable);
            }
            Err(error) => return Err(error.into()),
        };
        let prepared = prepare_user_revision(&request, &key, now_ms() as i64, &mut OsNonces)?;
        drop(key);
        let commit = commit_prepared(&mut ClientRevisionIo { client: self }, prepared).await?;
        let event = self
            .announce(&commit, &request.scope, identity, &wrapping)
            .await;
        Ok(EmbedRevisionOutcome { commit, event })
    }

    async fn announce(
        &mut self,
        commit: &UserRevisionCommit,
        scope: &RevisionScope,
        identity: Option<EmbedEventIdentity>,
        wrapping: &[u8; 32],
    ) -> EventDelivery {
        let committed = &commit.committed;
        if !committed.pending_notice {
            return EventDelivery::NoChat;
        }
        let chat_id = match scope {
            RevisionScope::Chat { chat_id, .. } => Some(chat_id.clone()),
            RevisionScope::Project { .. } => committed
                .hashed_chat_id
                .as_deref()
                .and_then(|hash| self.chats.keys().find(|id| sha256(id) == hash).cloned()),
        };
        let Some(chat_id) = chat_id else {
            return EventDelivery::Deferred {
                code: "home_chat_unavailable",
            };
        };
        let Some(identity) =
            identity.or_else(|| self.embed_event_identity(&committed.embed_id, wrapping))
        else {
            return EventDelivery::Deferred {
                code: "embed_identity_unavailable",
            };
        };
        let known = self.history_message_ids(&chat_id);
        let event = committed.event(&identity);
        let mut sink = ClientEventSink {
            client: self,
            ws: None,
        };
        let written = EmbedUpdatedWriter::new()
            .write(&mut sink, &chat_id, &event, &known)
            .await;
        sink.close().await;
        match written {
            Ok(EventWrite::Written) => EventDelivery::Written,
            Ok(EventWrite::AlreadyWritten) => EventDelivery::AlreadyWritten,
            Err(error) => EventDelivery::Deferred {
                code: error_code(&error),
            },
        }
    }

    /// Write the `embed_updated` events of `chat_id` that the server still
    /// lists as pending (edits made in the Projects workspace or on a device
    /// without the chat key), oldest first, with each notice's `created_at`.
    /// Embeds not cached yet are fetched once; a notice that still cannot be
    /// named stays pending and is reported as unresolved.
    ///
    /// # Errors
    /// `Invalid` for a malformed chat id; the GET's errors; `Protocol` for a
    /// malformed notice list; the first event write error.
    pub async fn reconcile_embed_update_notices(
        &mut self,
        chat_id: &str,
    ) -> Result<NoticeReconcileReport> {
        uuid::Uuid::parse_str(chat_id)
            .map_err(|_| Error::Invalid("A full chat ID is required."))?;
        self.require_session()?;
        let path = self.scoped(&format!(
            "/v1/chats/{}/pending-embed-notices",
            segment(chat_id)
        ))?;
        let response = self.request(Method::GET, &path, None).await?;
        let notices = parse_pending_notices(chat_id, &response)?;
        let known = self.history_message_ids(chat_id);
        if notices
            .iter()
            .all(|notice| known.contains(&notice.message_id))
        {
            return Ok(NoticeReconcileReport {
                already_present: notices.len(),
                ..NoticeReconcileReport::default()
            });
        }
        let wrapping = self.wrapping_key().await?;
        let mut identities: BTreeMap<String, Option<EmbedEventIdentity>> = BTreeMap::new();
        for notice in notices
            .iter()
            .filter(|notice| !known.contains(&notice.message_id))
        {
            if identities.contains_key(&notice.embed_id) {
                continue;
            }
            // A failed fetch leaves the notice unresolved (it stays pending on
            // the server); it never stops the other notices of the chat.
            if !self.embeds.contains_key(&notice.embed_id)
                && self.embed_detail(&notice.embed_id).await.is_err()
            {
                identities.insert(notice.embed_id.clone(), None);
                continue;
            }
            let identity = self.embed_event_identity(&notice.embed_id, &wrapping);
            identities.insert(notice.embed_id.clone(), identity);
        }
        let mut writer = EmbedUpdatedWriter::new();
        let mut sink = ClientEventSink {
            client: self,
            ws: None,
        };
        let report = reconcile_notices(
            &mut sink,
            &mut writer,
            chat_id,
            &notices,
            &known,
            |embed_id| identities.get(embed_id).cloned().flatten(),
        )
        .await;
        sink.close().await;
        report
    }

    /// [`Self::reconcile_embed_update_notices`] as run by the chat window open
    /// hook, after the window is shown. Personal chats only: the server stores
    /// system messages only from the chat owner, so a Team member's write
    /// would wait for a confirmation that never comes. Offline, refused or
    /// unavailable reads are deferred (the notices stay pending on the server
    /// and the next open retries); the report names why.
    ///
    /// Public so every shell's chat-open path reaches it: the native view
    /// model calls it from `open_chat`, the web Worker through its browser
    /// binding.
    ///
    /// # Errors
    /// `Cancelled` and `Expired` (the open was superseded or the session ended).
    pub async fn reconcile_embed_update_notices_on_open(
        &mut self,
        chat_id: &str,
    ) -> Result<NoticeReconcileReport> {
        if self.team()?.is_some() {
            return Ok(NoticeReconcileReport::deferred("team_chat"));
        }
        match self.reconcile_embed_update_notices(chat_id).await {
            Err(error @ (Error::Cancelled | Error::Expired)) => Err(error),
            Err(error) => Ok(NoticeReconcileReport::deferred(error_code(&error))),
            ok => ok,
        }
    }
}
