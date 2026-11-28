//! Durable sealed update queue for an admitted browser profile. The shared
//! client core owns partitioning, record format and merging writes across
//! replicas; the browser stores opaque bytes (live-collab.offline.merge-on-reconnect).

use super::super::engine::SealedUpdate;
use super::super::session_types::Event;
use super::super::session_wire::{outbox_from_json, outbox_to_json};
use crate::client::live::LiveError;
use crate::client::{Client, segment, sha256};
use futures_util::future::LocalBoxFuture;
use reqwest::Method;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::HashMap;

/// An asynchronous byte-store operation on the shell's local executor.
pub type OutboxStorageFuture<'a, T> = LocalBoxFuture<'a, Result<T, LiveError>>;

/// The browser's opaque persistent storage primitive. Storage never receives
/// item keys, a plaintext item, or the account and item IDs.
pub trait OutboxStorage {
    /// Lists the opaque keys beginning with the caller's account prefix.
    fn keys<'a>(&'a self, prefix: &'a str) -> OutboxStorageFuture<'a, Vec<String>>;

    /// Reads the latest committed bytes for an isolated cache key.
    /// Storage failures are distinct from an absent record.
    fn read<'a>(&'a self, key: &'a str) -> OutboxStorageFuture<'a, Option<String>>;

    /// Replaces or removes the record only if it still has the expected bytes.
    /// Returns false on a concurrent write, and an error on a storage failure.
    fn compare_and_put<'a>(
        &'a self,
        key: &'a str,
        expected: Option<&'a str>,
        next: Option<&'a str>,
    ) -> OutboxStorageFuture<'a, bool>;
}

/// One account-sealed offline copy and the pending messages it represents.
#[derive(Debug, Deserialize, PartialEq, Serialize)]
pub(super) struct RecoveryCopy {
    pub(super) writer: String,
    pub(super) messages: Vec<String>,
    pub(super) sealed: String,
}

#[derive(Default)]
pub(super) struct StoredOutbox {
    pub(super) entries: Vec<SealedUpdate>,
    pub(super) copies: Vec<RecoveryCopy>,
}

const RECOVERY_FORMAT: &str = "openmates-live-recovery-v1";

/// Data inside the authenticated account envelope. Scope binds the plaintext
/// to the record where it was written, so another item's copy cannot be used.
#[derive(Serialize)]
pub(super) struct RecoveryContent<'a> {
    pub(super) scope: &'a str,
    pub(super) item_id: &'a str,
    pub(super) team_id: Option<&'a str>,
    pub(super) project_id: Option<&'a str>,
    pub(super) kind: &'a str,
    pub(super) text: &'a str,
}

pub(super) async fn seal_copy(
    client: &Client,
    writer: &str,
    entries: &[SealedUpdate],
    content: RecoveryContent<'_>,
) -> Result<RecoveryCopy, LiveError> {
    let master = client
        .master_capability()
        .map_err(|_| LiveError::Io("live_recovery_key_unavailable"))?;
    let bytes = zeroize::Zeroizing::new(
        serde_json::to_vec(&content).map_err(|_| LiveError::Io("live_recovery_invalid"))?,
    );
    let sealed = master
        .encrypt_server_bytes(&bytes)
        .await
        .map_err(|_| LiveError::Io("live_recovery_seal_failed"))?;
    Ok(RecoveryCopy {
        writer: writer.to_owned(),
        messages: entries
            .iter()
            .map(|entry| entry.client_msg_id.clone())
            .collect(),
        sealed,
    })
}

impl StoredOutbox {
    fn parse(record: Option<&str>) -> Result<Self, LiveError> {
        let Some(record) = record else {
            return Ok(Self::default());
        };
        let value: Value = serde_json::from_str(record)
            .map_err(|_| LiveError::Io("live_outbox_invalid_record"))?;
        if value[0] == RECOVERY_FORMAT {
            let entries = outbox_from_json(&value[1].to_string())?;
            let copies = serde_json::from_value(value[2].clone())
                .map_err(|_| LiveError::Io("live_outbox_invalid_record"))?;
            return Ok(Self { entries, copies });
        }
        Ok(Self {
            entries: outbox_from_json(record)?,
            copies: Vec::new(),
        })
    }

    fn encode(&self) -> Option<String> {
        if self.entries.is_empty() {
            return None;
        }
        let entries = outbox_to_json(&self.entries);
        Some(if self.copies.is_empty() {
            entries.to_string()
        } else {
            json!([RECOVERY_FORMAT, entries, self.copies]).to_string()
        })
    }
}

fn account_prefix(client: &Client) -> Result<String, LiveError> {
    let status = client
        .browser_session_status()
        .ok_or(LiveError::Io("live_outbox_session_expired"))?;
    Ok(format!(
        "{}:",
        sha256(
            &json!([
                "openmates-live-outbox-owner-v1",
                client.base.as_str(),
                status.principal()
            ])
            .to_string()
        )
    ))
}

pub(super) fn scope(client: &Client, item_id: &str) -> Result<String, LiveError> {
    let status = client
        .browser_session_status()
        .ok_or(LiveError::Io("live_outbox_session_expired"))?;
    let legacy = sha256(
        &json!([
            "live-item-outbox-v1",
            client.base.as_str(),
            status.principal(),
            item_id
        ])
        .to_string(),
    );
    Ok(format!("{}{legacy}", account_prefix(client)?))
}

#[derive(Deserialize)]
struct OpenedRecovery {
    scope: String,
    item_id: String,
    team_id: Option<String>,
    project_id: Option<String>,
    kind: String,
    text: String,
}

impl Drop for OpenedRecovery {
    fn drop(&mut self) {
        use zeroize::Zeroize;
        self.text.zeroize();
    }
}

async fn access_removed(client: &mut Client, copy: &OpenedRecovery) -> bool {
    // Only an explicit access refusal counts. Network loss, auth expiry and
    // malformed or stale local keys cannot turn a pending edit into an export.
    if let Some(team) = copy.team_id.as_deref() {
        client.clear_http_failure();
        if client.team_key_row(team).await.is_err() {
            return client
                .http_failure()
                .is_some_and(|failure| matches!(failure.status, 403 | 404));
        }
    }
    if let Some(project) = copy.project_id.as_deref() {
        let mut path = format!("/v1/projects/{}", segment(project));
        if let Some(team) = copy.team_id.as_deref() {
            let query = url::form_urlencoded::Serializer::new(String::new())
                .append_pair("team_id", team)
                .finish();
            path.push('?');
            path.push_str(&query);
        }
        client.clear_http_failure();
        let result = client.request(Method::GET, &path, None).await;
        return result.is_err()
            && client
                .http_failure()
                .is_some_and(|failure| matches!(failure.status, 403 | 404));
    }
    false
}

pub(super) async fn revoked_copies(
    client: &mut Client,
    storage: &dyn OutboxStorage,
    offered: &mut std::collections::HashSet<String>,
) -> Result<Vec<Event>, LiveError> {
    let prefix = account_prefix(client)?;
    let master = client
        .master_capability()
        .map_err(|_| LiveError::Io("live_recovery_key_unavailable"))?;
    let mut events = Vec::new();
    for key in storage.keys(&prefix).await? {
        if !key.starts_with(&prefix) {
            continue;
        }
        let row = storage.read(&key).await?;
        let stored = StoredOutbox::parse(row.as_deref())?;
        for copy in stored.copies {
            // Match the ID an open replica uses for this same offline draft.
            let Some(id) = copy.messages.last() else {
                continue;
            };
            if offered.contains(id) {
                continue;
            }
            let bytes = master
                .decrypt_bytes(&copy.sealed)
                .await
                .map_err(|_| LiveError::Io("live_recovery_open_failed"))?;
            let mut recovered: OpenedRecovery = serde_json::from_slice(&bytes)
                .map_err(|_| LiveError::Io("live_recovery_invalid"))?;
            if recovered.scope != key || scope(client, &recovered.item_id)? != key {
                return Err(LiveError::Io("live_recovery_invalid_scope"));
            }
            let kind = super::super::LiveItemKind::parse(&recovered.kind)?;
            if access_removed(client, &recovered).await && account_prefix(client)? == prefix {
                events.push(Event::PrivateCopy {
                    item_id: recovered.item_id.clone(),
                    copy_id: id.clone(),
                    kind,
                    text: std::mem::take(&mut recovered.text),
                });
                offered.insert(id.clone());
            }
        }
    }
    Ok(events)
}

pub(super) async fn load(
    storage: &dyn OutboxStorage,
    key: &str,
) -> Result<Vec<SealedUpdate>, LiveError> {
    if let Some(record) = storage.read(key).await? {
        return Ok(StoredOutbox::parse(Some(&record))?.entries);
    }
    // A prior browser build used the hash suffix directly. Copy the exact
    // sealed row before deleting it, and respect any concurrent new write.
    if let Some((_, legacy)) = key.split_once(':')
        && let Some(record) = storage.read(legacy).await?
    {
        let entries = StoredOutbox::parse(Some(&record))?.entries;
        if storage.compare_and_put(key, None, Some(&record)).await? {
            storage.compare_and_put(legacy, Some(&record), None).await?;
            return Ok(entries);
        }
        let current = storage.read(key).await?;
        return Ok(StoredOutbox::parse(current.as_deref())?.entries);
    }
    Ok(Vec::new())
}

pub(super) async fn persist(
    storage: &dyn OutboxStorage,
    key: &str,
    previous: &[SealedUpdate],
    entries: &[SealedUpdate],
    copy: Option<&RecoveryCopy>,
) -> Result<(), LiveError> {
    if previous == entries && copy.is_none() {
        return Ok(());
    }
    for _ in 0..5 {
        let expected = storage.read(key).await?;
        let mut stored = StoredOutbox::parse(expected.as_deref())?;
        stored.entries = merge(stored.entries, previous, entries);
        reconcile_copies(&mut stored, copy);
        let next = stored.encode();
        if next == expected
            || storage
                .compare_and_put(key, expected.as_deref(), next.as_deref())
                .await?
        {
            return Ok(());
        }
    }
    Err(LiveError::Io("live_outbox_concurrent_write"))
}

fn reconcile_copies(stored: &mut StoredOutbox, copy: Option<&RecoveryCopy>) {
    let pending: std::collections::HashSet<_> = stored
        .entries
        .iter()
        .map(|entry| entry.client_msg_id.as_str())
        .collect();
    stored.copies.retain(|saved| {
        copy.is_none_or(|latest| latest.writer != saved.writer)
            && saved
                .messages
                .iter()
                .any(|id| pending.contains(id.as_str()))
    });
    if let Some(copy) = copy
        && copy.messages.iter().any(|id| pending.contains(id.as_str()))
    {
        stored.copies.push(RecoveryCopy {
            writer: copy.writer.clone(),
            messages: copy.messages.clone(),
            sealed: copy.sealed.clone(),
        });
    }
}

fn merge(
    mut stored: Vec<SealedUpdate>,
    previous: &[SealedUpdate],
    entries: &[SealedUpdate],
) -> Vec<SealedUpdate> {
    let previously_local: HashMap<_, _> = previous
        .iter()
        .map(|entry| (entry.client_msg_id.as_str(), entry))
        .collect();
    let locally_pending: HashMap<_, _> = entries
        .iter()
        .map(|entry| (entry.client_msg_id.as_str(), entry))
        .collect();
    // A replica knows only which of its own observed messages were settled.
    // It must never erase writes queued by another browser tab.
    stored.retain(|entry| {
        let id = entry.client_msg_id.as_str();
        !previously_local.contains_key(id) || locally_pending.contains_key(id)
    });
    let positions: HashMap<String, usize> = stored
        .iter()
        .enumerate()
        .map(|(index, entry)| (entry.client_msg_id.clone(), index))
        .collect();
    for entry in entries {
        let id = entry.client_msg_id.as_str();
        match (previously_local.get(id), positions.get(id).copied()) {
            (Some(prior), Some(index)) if *prior != entry && stored[index].epoch <= entry.epoch => {
                stored[index] = entry.clone();
            }
            // A missing previously observed message may have been acked by
            // another replica. Reintroducing it would send a settled write again.
            (None, None) => stored.push(entry.clone()),
            _ => {}
        }
    }
    stored
}

#[cfg(test)]
#[path = "client_outbox_tests.rs"]
mod tests;
