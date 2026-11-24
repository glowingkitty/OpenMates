//! [`LiveIo`] over the signed-in core [`Client`]: embed key and content resolution, the
//! user-revisions checkpoint write, the assistant-outcome POST, the outbox store and the
//! shell's socket adapter. Owns no live logic; it only performs the primitives that
//! [`super::driver::LiveDriver`] asks for (`live-collab.core.live-session`).
//!
//! The `Client` is borrowed for one driver call (`ClientLiveIo` holds `&mut Client`), the
//! long-lived part (outboxes, kinds, heads, the socket callback) is [`IoState`] owned by the
//! binding between calls.

#[path = "client_outbox.rs"]
mod client_outbox;
pub use client_outbox::{OutboxStorage, OutboxStorageFuture};

use super::driver::{LiveIo, LiveKeys};
use super::engine::SealedUpdate;
use super::session_types::{CheckpointRequest, CheckpointResult};
use super::stored_form::{kind_of_embed_type, stored_with_text, text_from_content};
use super::{LiveError, LiveItemKind};
use crate::client::embed_user_revision::EmbedHead;
use crate::client::embed_user_revision::team_cipher::{TeamRevisionCipher, ciphertext_epoch};
use crate::client::embed_user_revision::{RevisionScope, UserRevisionError, UserRevisionRequest};
use crate::client::project_commit_restore::restore_filters;
use crate::client::{Client, Item, segment, sha256};
use crate::crypto::Key;
use crate::error::Error;
use reqwest::Method;
use serde_json::{Value, json};
use std::collections::HashMap;
use std::rc::Rc;
use zeroize::Zeroizing;

/// Personal and pre-rotation items use the original embed key.
const INITIAL_ITEM_EPOCH: u32 = 1;

/// Bind a rotated Team epoch to one item, with an independent packet key for
/// each item. The secret input is the epoch's Team key, distributed by its
/// member wrappers. Predecessors can decrypt earlier packets only.
fn derive_item_key(team_key: &Key, item_id: &str, epoch: u32) -> Result<Key, Error> {
    let hkdf =
        hkdf::Hkdf::<sha2::Sha256>::new(Some(b"openmates-live-item-key-v1"), team_key.as_ref());
    let mut key = Zeroizing::new([0; 32]);
    let info = [epoch.to_be_bytes().as_slice(), item_id.as_bytes()].concat();
    hkdf.expand(&info, key.as_mut())
        .map_err(|_| Error::Crypto)?;
    Ok(key)
}

/// The shell's socket primitive: write one `{"type", "payload"}` frame on the open WebSocket.
pub trait LiveSend {
    /// Sends the frame; `payload_json` is the JSON object text of the payload.
    ///
    /// # Errors
    /// The socket is closed or the frame could not be queued.
    fn send(&self, message_type: &str, payload_json: &str) -> Result<(), LiveError>;
}

/// State that outlives one driver call.
#[derive(Default)]
pub struct IoState {
    /// The shell's socket callback.
    pub send: Option<Rc<dyn LiveSend>>,
    /// Kind per open item (registered by the owner before `open`).
    pub kinds: HashMap<String, LiveItemKind>,
    /// Server head version read when the key was resolved (base of the first checkpoint).
    heads: HashMap<String, i64>,
    /// Last observed local outbox for each replica. Only those entries may be retired
    /// by this replica, even if another tab has since queued more writes.
    outboxes: HashMap<String, Vec<SealedUpdate>>,
    /// Host byte storage for outboxes. Headless callers may supply no local storage.
    pub outbox_storage: Option<Rc<dyn OutboxStorage>>,
    recovery_writer: Option<String>,
    offered_recovery: std::collections::HashSet<String>,
    /// Assistant changes for items that are not open: `(embed_id, frame)`; the owner opens
    /// the item and feeds the frame again.
    pub pending_opens: Vec<(String, Value)>,
    /// Project an embed is opened in (registered by the owner with `open`): its checkpoints
    /// use the Project scope, which needs no local chat.
    pub projects: HashMap<String, String>,
    /// Team of the Project an embed is opened in (registered with `open`). Team scope
    /// travels per item: the shared Worker never sets the client's active Team.
    pub teams: HashMap<String, String>,
}

/// The scope a checkpoint is written in: the Project the item was opened in when there is
/// one, else the embed's cached chat; `None` when neither is known.
pub(super) fn revision_scope(
    project_id: Option<&str>,
    chat_id: Option<String>,
    team_id: Option<String>,
) -> Option<RevisionScope> {
    match (project_id, chat_id) {
        (Some(project_id), _) => Some(RevisionScope::Project {
            project_id: project_id.to_owned(),
            team_id,
        }),
        (None, Some(chat_id)) => Some(RevisionScope::Chat { chat_id, team_id }),
        (None, None) => None,
    }
}

#[cfg(test)]
mod scope_tests {
    //! Scoped checkpoint routing and isolation of rotated live packet keys.
    use super::*;

    #[test]
    fn rotation_derives_item_keys_only_opened_with_the_current_team_key() {
        use super::super::{LiveItemKind, PacketType, open_packet, seal_packet};

        let removed_team_key = Zeroizing::new([2; 32]);
        let current_team_key = Zeroizing::new([3; 32]);
        let item_id = "project-file";
        let epoch = 2;
        let fresh = derive_item_key(&current_team_key, item_id, epoch).unwrap();
        let old = derive_item_key(&removed_team_key, item_id, epoch).unwrap();
        let other_file = derive_item_key(&current_team_key, "other-file", epoch).unwrap();
        let packet = seal_packet(
            &fresh,
            item_id,
            LiveItemKind::Code,
            epoch,
            PacketType::Update,
            b"post-rotation",
        )
        .unwrap();
        for key in [&old, &other_file] {
            assert!(matches!(
                open_packet(
                    key,
                    item_id,
                    LiveItemKind::Code,
                    epoch,
                    PacketType::Update,
                    &packet
                ),
                Err(LiveError::Authentication)
            ));
        }
        assert_eq!(
            open_packet(
                &fresh,
                item_id,
                LiveItemKind::Code,
                epoch,
                PacketType::Update,
                &packet
            )
            .unwrap(),
            b"post-rotation"
        );
    }

    #[test]
    fn project_scope_needs_no_local_chat() {
        let scope = revision_scope(Some("p1"), None, Some("t".into())).unwrap();
        assert!(
            matches!(scope, RevisionScope::Project { project_id, team_id }
            if project_id == "p1" && team_id.as_deref() == Some("t"))
        );
        let chat = revision_scope(None, Some("c".into()), None).unwrap();
        assert!(matches!(chat, RevisionScope::Chat { .. }));
        assert!(revision_scope(None, None, None).is_none());
    }
}

/// [`LiveIo`] for one driver call.
pub struct ClientLiveIo<'a> {
    client: &'a mut Client,
    state: &'a mut IoState,
}

impl<'a> ClientLiveIo<'a> {
    /// The primitives over `client` with the long-lived `state`.
    pub fn new(client: &'a mut Client, state: &'a mut IoState) -> Self {
        Self { client, state }
    }

    /// The live kind of `embed_id` (registered, else read from the embed's type).
    ///
    /// # Errors
    /// The embed could not be read or is not live-editable.
    pub async fn kind_of(&mut self, embed_id: &str) -> Result<LiveItemKind, LiveError> {
        if let Some(kind) = self.state.kinds.get(embed_id) {
            return Ok(*kind);
        }
        self.edit_head(embed_id)
            .await
            .map_err(|_| LiveError::Io("live_read_failed"))?;
        let item = self
            .edit_item(embed_id)
            .await
            .map_err(|_| LiveError::Io("live_read_failed"))?;
        let kind = kind_of_embed_type(item.fields["type"].as_str().unwrap_or_default())
            .ok_or(LiveError::Io("live_not_editable"))?;
        self.state.kinds.insert(embed_id.to_owned(), kind);
        Ok(kind)
    }

    /// The Project `embed_id` was opened in, when the owner registered one.
    fn project_of(&self, embed_id: &str) -> Option<String> {
        self.state.projects.get(embed_id).cloned()
    }

    /// The Team of the Project `embed_id` was opened in; the client's active Team only
    /// when the owner registered none for the item.
    fn team_of(&self, embed_id: &str) -> Option<String> {
        self.state
            .teams
            .get(embed_id)
            .cloned()
            .or_else(|| self.client.team().ok().flatten().map(str::to_owned))
    }

    /// The edit head of `embed_id`. A Project file reads the row only: this device may hold
    /// neither a master nor a chat wrapper for it (the browser check of
    /// `embed_user_edit_head` would refuse), its key opens through the Project wrapper in
    /// [`Self::edit_key`], as in a Project commit restore.
    async fn edit_head(
        &mut self,
        embed_id: &str,
    ) -> Result<(EmbedHead, Option<String>), UserRevisionError> {
        if let Some(project) = self.project_of(embed_id) {
            self.project_file_head(&project, embed_id).await
        } else {
            self.client.embed_user_edit_head(embed_id).await
        }
    }

    /// The current head of a Project file, read through the Project route that admits every
    /// member of a Team Project (the socket `request_embed` admits only the embed's author).
    /// The row is cached so [`Self::edit_item`] decrypts it.
    async fn project_file_head(
        &mut self,
        project: &str,
        embed_id: &str,
    ) -> Result<(EmbedHead, Option<String>), UserRevisionError> {
        let team = self.team_of(embed_id);
        let response = self
            .client
            .projects()
            .with_filters(restore_filters(team.as_deref()))
            .project_embed_head(project, embed_id)
            .await?;
        let row = response.get("embed").cloned().ok_or(Error::Protocol)?;
        let now_seconds = i64::try_from(crate::client::now_ms() / 1000).unwrap_or(i64::MAX);
        let head = EmbedHead::from_cached_row(embed_id, &row, now_seconds)?;
        self.client.embeds.insert(embed_id.to_owned(), row);
        Ok((head, None))
    }

    /// The key of `embed_id`: the Project wrapper first for a Project file, then the master,
    /// chat and parent wrappers (an older link carries no Project wrapper).
    async fn edit_key(&mut self, embed_id: &str) -> Result<Key, Error> {
        if let Some(project) = self.project_of(embed_id) {
            let team = self.team_of(embed_id);
            let found = self
                .client
                .projects()
                .with_filters(restore_filters(team.as_deref()))
                .project_embed_key(&project, embed_id)
                .await;
            match found {
                Ok(Some(key)) => return Ok(key),
                Ok(None) | Err(Error::Crypto) => {}
                Err(error) => return Err(error),
            }
        }
        self.client.edit_embed_key(embed_id).await
    }

    async fn live_keys(&mut self, item_id: &str, stale: bool) -> Result<LiveKeys, Error> {
        let team = self.team_of(item_id);
        let row = match team.as_deref() {
            Some(team) => {
                let mut row = self.client.team_key_row(team).await?;
                if row["rotation_pending"] == true {
                    if !self.client.rotate_team_key_if_pending(team).await? {
                        return Err(Error::Conflict);
                    }
                    row = self.client.team_key_row(team).await?;
                }
                Some(row)
            }
            None => None,
        };
        // A change to the transport epoch does not change the version base of
        // an already-open editor with local changes awaiting a checkpoint.
        if !stale {
            let (head, _) = self.edit_head(item_id).await.map_err(|_| Error::Protocol)?;
            self.state.heads.insert(item_id.to_owned(), head.version);
        }
        let embed_key = self.edit_key(item_id).await?;
        let (Some(team), Some(mut row)) = (team, row) else {
            return Ok(LiveKeys {
                epoch: INITIAL_ITEM_EPOCH,
                current: embed_key,
                previous: vec![],
            });
        };
        let epoch = row
            .get("team_key_epoch")
            .filter(|value| !value.is_null())
            .map_or(Some(u64::from(INITIAL_ITEM_EPOCH)), Value::as_u64)
            .and_then(|epoch| u32::try_from(epoch).ok())
            .filter(|epoch| *epoch >= INITIAL_ITEM_EPOCH)
            .ok_or(Error::Protocol)?;
        if epoch == INITIAL_ITEM_EPOCH {
            return Ok(LiveKeys {
                epoch,
                current: embed_key,
                previous: vec![],
            });
        }
        if let Some(claimed) = self.client.claim_sealed_team_key(&team, &row).await? {
            row["encrypted_team_key"] = json!(claimed);
        }
        let wrapper = row["encrypted_team_key"].as_str().ok_or(Error::Protocol)?;
        let team_key = self.client.work_unwrap_with_master(wrapper).await?;
        let chain = row["encrypted_previous_team_keys"]
            .as_str()
            .ok_or(Error::Protocol)?;
        let mut previous = vec![(INITIAL_ITEM_EPOCH, embed_key)];
        for (older, key) in crate::client::previous_team_keys(chain, &team_key)? {
            let older = u32::try_from(older).map_err(|_| Error::Protocol)?;
            if (INITIAL_ITEM_EPOCH + 1..epoch).contains(&older) {
                previous.push((older, derive_item_key(&key, item_id, older)?));
            }
        }
        Ok(LiveKeys {
            epoch,
            current: derive_item_key(&team_key, item_id, epoch)?,
            previous,
        })
    }

    /// The decrypted cached embed, its key resolved as in [`Self::edit_key`].
    async fn edit_item(&mut self, embed_id: &str) -> Result<Item, Error> {
        let key = self.edit_key(embed_id).await?;
        self.open_edit_item(embed_id, &key).await
    }

    async fn open_edit_item(&mut self, embed_id: &str, key: &Key) -> Result<Item, Error> {
        let row = self.client.embeds.get(embed_id).ok_or(Error::Protocol)?;
        let stored = row["encrypted_content"].as_str().ok_or(Error::Protocol)?;
        let cipher = match ciphertext_epoch(stored)? {
            Some(epoch) => self.revision_cipher(embed_id, Some(epoch)).await?,
            None => None,
        };
        self.client
            .decrypt_embed_row_for_revision(embed_id, key, cipher.as_ref())
    }

    /// Resolve a Team revision key for a stored epoch, or the write epoch for a new checkpoint.
    async fn revision_cipher(
        &mut self,
        embed_id: &str,
        historical_epoch: Option<u32>,
    ) -> Result<Option<TeamRevisionCipher>, Error> {
        let Some(team) = self.team_of(embed_id) else {
            return if historical_epoch.is_none() {
                Ok(None)
            } else {
                Err(Error::Forbidden)
            };
        };
        self.client
            .team_revision_cipher(&team, embed_id, historical_epoch)
            .await
    }

    async fn store_outbox(
        &mut self,
        item_id: &str,
        entries: &[SealedUpdate],
        offline: Option<&super::engine::LiveItem>,
    ) -> Result<(), LiveError> {
        if let Some(storage) = &self.state.outbox_storage {
            let scope = client_outbox::scope(self.client, item_id)?;
            let previous = self
                .state
                .outboxes
                .get(item_id)
                .map(Vec::as_slice)
                .unwrap_or_default();
            let copy = if let Some(item) = offline {
                let writer = self
                    .state
                    .recovery_writer
                    .get_or_insert_with(|| uuid::Uuid::new_v4().to_string());
                let text = Zeroizing::new(item.text_form()?);
                let snapshot = client_outbox::RecoveryContent {
                    scope: &scope,
                    item_id,
                    team_id: self.state.teams.get(item_id).map(String::as_str),
                    project_id: self.state.projects.get(item_id).map(String::as_str),
                    kind: item.kind().as_str(),
                    text: &text,
                };
                Some(client_outbox::seal_copy(self.client, writer, entries, snapshot).await?)
            } else {
                None
            };
            client_outbox::persist(storage.as_ref(), &scope, previous, entries, copy.as_ref())
                .await?;
        }
        self.state
            .outboxes
            .insert(item_id.to_owned(), entries.to_vec());
        Ok(())
    }

    /// Searches this account's durable offline copies after admission.
    ///
    /// # Errors
    /// The browser cache could not be read or a record did not authenticate.
    pub async fn revoked_private_copies(
        &mut self,
    ) -> Result<Vec<super::session_types::Event>, LiveError> {
        let Some(storage) = &self.state.outbox_storage else {
            return Ok(Vec::new());
        };
        client_outbox::revoked_copies(
            self.client,
            storage.as_ref(),
            &mut self.state.offered_recovery,
        )
        .await
    }

    /// Takes the assistant changes that arrived for items that are not open.
    pub fn take_pending_opens(&mut self) -> Vec<(String, Value)> {
        std::mem::take(&mut self.state.pending_opens)
    }
}

impl LiveIo for ClientLiveIo<'_> {
    fn send(&mut self, message_type: &str, payload: &Value) -> Result<(), LiveError> {
        let send = self
            .state
            .send
            .as_ref()
            .ok_or(LiveError::Io("live_not_connected"))?;
        send.send(message_type, &payload.to_string())
    }

    async fn persist_outbox(
        &mut self,
        item_id: &str,
        entries: &[SealedUpdate],
    ) -> Result<(), LiveError> {
        self.store_outbox(item_id, entries, None).await
    }

    async fn persist_offline_outbox(
        &mut self,
        item_id: &str,
        entries: &[SealedUpdate],
        item: &super::engine::LiveItem,
    ) -> Result<(), LiveError> {
        self.store_outbox(item_id, entries, Some(item)).await
    }

    async fn load_outbox(&mut self, item_id: &str) -> Result<Vec<SealedUpdate>, LiveError> {
        if let Some(storage) = &self.state.outbox_storage {
            let scope = client_outbox::scope(self.client, item_id)?;
            let entries = client_outbox::load(storage.as_ref(), &scope).await?;
            self.state
                .outboxes
                .insert(item_id.to_owned(), entries.clone());
            return Ok(entries);
        }
        Ok(self
            .state
            .outboxes
            .get(item_id)
            .cloned()
            .unwrap_or_default())
    }

    async fn resolve_key(&mut self, item_id: &str, stale: bool) -> Result<LiveKeys, LiveError> {
        self.live_keys(item_id, stale)
            .await
            .map_err(|_| LiveError::Io("live_key_unavailable"))
    }

    async fn read_content(&mut self, item_id: &str) -> Result<String, LiveError> {
        let kind = self.kind_of(item_id).await?;
        let item = self
            .edit_item(item_id)
            .await
            .map_err(|_| LiveError::Io("live_read_failed"))?;
        text_from_content(kind, &item.fields["content"])
    }

    async fn write_checkpoint(&mut self, request: &CheckpointRequest) -> CheckpointResult {
        match self.checkpoint(request).await {
            Ok(result) => result,
            Err(_) => CheckpointResult::Failed,
        }
    }

    async fn read_version_text(
        &mut self,
        embed_id: &str,
        version: i64,
    ) -> Result<String, LiveError> {
        let kind = self.kind_of(embed_id).await?;
        if let Some(project) = self.project_of(embed_id) {
            let (head, _) = self
                .edit_head(embed_id)
                .await
                .map_err(|_| LiveError::Io("live_read_failed"))?;
            if version < 1 || version > head.version {
                return Err(LiveError::Io("live_read_failed"));
            }
            if version == head.version {
                return self.read_content(embed_id).await;
            }
            let team = self.team_of(embed_id);
            let key = self
                .edit_key(embed_id)
                .await
                .map_err(|_| LiveError::Io("live_key_unavailable"))?;
            let version = u64::try_from(version).map_err(|_| LiveError::Io("live_read_failed"))?;
            let rows = self
                .client
                .projects()
                .with_filters(restore_filters(team.as_deref()))
                .version_rows(&project, embed_id, version)
                .await
                .map_err(|_| LiveError::Io("live_read_failed"))?;
            let stored = self
                .client
                .replay_stored_revision_history(team.as_deref(), embed_id, &rows, &key, version)
                .await
                .map_err(|_| LiveError::Io("live_read_failed"))?;
            if kind == LiveItemKind::Code {
                // Older hosted history snapshots store file text directly.
                return Ok(crate::work::version_text(stored).to_string());
            }
            let content = crate::client::toon::decode(&stored)
                .map_err(|_| LiveError::Io("live_read_failed"))?;
            return text_from_content(kind, &content);
        }
        if let Some(team) = self.team_of(embed_id) {
            let (_, chat) = self
                .edit_head(embed_id)
                .await
                .map_err(|_| LiveError::Io("live_read_failed"))?;
            let chat = chat.ok_or(LiveError::Io("live_scope_unavailable"))?;
            let key = self
                .edit_key(embed_id)
                .await
                .map_err(|_| LiveError::Io("live_key_unavailable"))?;
            let stored = self
                .client
                .read_team_chat_revision(&team, &chat, embed_id, version, &key)
                .await
                .map_err(|_| LiveError::Io("live_read_failed"))?;
            let content = crate::client::toon::decode(&stored)
                .map_err(|_| LiveError::Io("live_read_failed"))?;
            return text_from_content(kind, &content);
        }
        let response = self
            .client
            .embed_version_content(embed_id, version)
            .await
            .map_err(|_| LiveError::Io("live_read_failed"))?;
        let stored = response["content"]
            .as_str()
            .ok_or(LiveError::Io("live_read_failed"))?;
        let content =
            crate::client::toon::decode(stored).map_err(|_| LiveError::Io("live_read_failed"))?;
        text_from_content(kind, &content)
    }

    async fn post_assistant_outcome(
        &mut self,
        embed_id: &str,
        body: &Value,
    ) -> Result<(), LiveError> {
        let path = format!("/v1/embeds/{}/assistant-change-outcome", segment(embed_id));
        self.client
            .request(Method::POST, &path, Some(body.clone()))
            .await
            .map(|_| ())
            .map_err(|_| LiveError::Io("live_outcome_failed"))
    }

    fn assistant_change_not_open(&mut self, embed_id: &str, frame: &Value) {
        self.state
            .pending_opens
            .push((embed_id.to_owned(), frame.clone()));
    }

    async fn base_version(&mut self, item_id: &str) -> Option<i64> {
        self.state.heads.get(item_id).copied()
    }

    fn opened_project(&self, item_id: &str) -> Option<&str> {
        self.state.projects.get(item_id).map(String::as_str)
    }
}

impl ClientLiveIo<'_> {
    /// One version through the user-revisions path on a freshly read head. A head that moved
    /// since `base_version` answers `Conflict` (the session retries on it: the live doc holds
    /// every change); the new version is the head plus one.
    async fn checkpoint(
        &mut self,
        request: &CheckpointRequest,
    ) -> Result<CheckpointResult, LiveError> {
        let kind = self.kind_of(&request.item_id).await?;
        let (head, chat_id) = self
            .edit_head(&request.item_id)
            .await
            .map_err(|_| LiveError::Io("live_read_failed"))?;
        if request
            .base_version
            .is_some_and(|base| base != head.version)
        {
            return Ok(CheckpointResult::Conflict(head.version));
        }
        let key = self
            .edit_key(&request.item_id)
            .await
            .map_err(|_| LiveError::Io("live_key_unavailable"))?;
        let item = self
            .open_edit_item(&request.item_id, &key)
            .await
            .map_err(|_| LiveError::Io("live_read_failed"))?;
        let cipher = match self.revision_cipher(&request.item_id, None).await {
            Ok(cipher) => cipher,
            Err(Error::Conflict) => return Ok(CheckpointResult::Failed),
            Err(_) => return Err(LiveError::Io("live_key_unavailable")),
        };
        let stored = stored_with_text(
            kind,
            &item.fields["content"],
            &request.text,
            head.version + 1,
        )?;
        // Project scope when the item was opened in a Project (no local chat needed).
        let team_id = self.team_of(&request.item_id);
        let project = self
            .state
            .projects
            .get(&request.item_id)
            .map(String::as_str);
        let scope = revision_scope(project, chat_id, team_id)
            .ok_or(LiveError::Io("live_scope_unavailable"))?;
        let version = head.version;
        let stored = Zeroizing::new(stored);
        let mut revision = match request.restored_from {
            Some(from) => UserRevisionRequest::restore(head, scope, from, stored, None, None),
            None => UserRevisionRequest::content_edit(head, scope, stored, None, None),
        };
        revision.version_kind = Some(request.version_kind.to_owned());
        revision.contributors = Some(
            request
                .contributors
                .iter()
                .map(|user| json!({"user_hash": sha256(user)}))
                .collect(),
        );
        match self
            .client
            .commit_embed_user_revision_with_cipher(revision, None, key, cipher)
            .await
        {
            Ok(outcome) => Ok(CheckpointResult::Written(outcome.commit.committed.version)),
            Err(UserRevisionError::VersionConflict {
                current_revision, ..
            }) => Ok(CheckpointResult::Conflict(
                current_revision.unwrap_or(version),
            )),
            Err(_) => Ok(CheckpointResult::Failed),
        }
    }
}
