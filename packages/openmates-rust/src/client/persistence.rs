//! Ciphertext persistence and canonical receipts for streamed artifacts.
use super::plaintext::Plain;
use super::sync_capability::AsyncCryptoScope;
use super::transport::{Socket, send, wait};
use super::*;
impl Client {
    // Each identifier is a separate authenticated protocol fence.
    #[allow(clippy::too_many_arguments)]
    pub(super) async fn persist_stream_artifacts(
        &mut self,
        ws: &mut Socket,
        chat: &str,
        message: &str,
        key: &[u8; 32],
        task: &str,
        embeds: &BTreeMap<String, Value>,
        checkpoints: &[Value],
    ) -> Result<Vec<Item>> {
        let scope = AsyncCryptoScope::begin(self)?;
        self.require_canonical_read_profile()?;
        self.require_browser_owner_guards()?;
        scope.check_chat(self, chat)?;
        // A completed error future is fenced too: a revoked operation cannot
        // continue after an absence/error or publish a receipt from old authority.
        macro_rules! scoped_await {
            ($future:expr) => {{
                scope.check_chat(self, chat)?;
                let result = $future.await;
                scope.check_chat(self, chat)?;
                result
            }};
        }
        let key = zeroize::Zeroizing::new(*key);
        let user = self
            .user
            .get("id")
            .or_else(|| self.user.get("user_id"))
            .and_then(Value::as_str)
            .ok_or_else(|| super::send::refusal_trace::protocol_at!())?
            .to_owned();
        let user_hash = sha256(&user);
        let chat_hash = sha256(chat);
        let master = self.master_capability()?;
        let team = self.team()?.map(str::to_owned);
        let mut keys: BTreeMap<String, Key> = BTreeMap::new();
        let mut pending = Plain::new(embeds.clone());
        let checkpoints = Plain::new(checkpoints.to_vec());
        let mut items = Plain::new(Vec::<Item>::new());
        // Parent-before-child ordering is independent of delivery order.
        while !pending.is_empty() {
            let ready = pending
                .iter()
                .find(|(_, row)| {
                    text(row, "parent_embed_id").is_empty()
                        || keys.contains_key(text(row, "parent_embed_id"))
                })
                .map(|(id, _)| id.clone())
                .ok_or(Error::Invalid(
                    "An artifact's parent key is unavailable; its output remains pending.",
                ))?;
            let row = Plain::new(pending.remove(&ready).ok_or_else(|| super::send::refusal_trace::protocol_at!())?);
            if text(&row, "message_id") != message
                && !super::send::frame_task_matches(text(&row, "task_id"), task)
            {
                { super::send::refusal_trace::note("persistence_65"); return Err(Error::Forbidden); }
            }
            let parent = text(&row, "parent_embed_id");
            let embed_key = if parent.is_empty() {
                crypto::derive_embed_key(&key, &ready)?
            } else {
                keys.get(parent).ok_or(Error::Crypto)?.clone()
            };
            let source = required(&row, "content")?;
            let kind = required(&row, "type")?;
            let version = row["version_number"].as_u64().unwrap_or(1);
            let message_id = row
                .get("message_id")
                .and_then(Value::as_str)
                .filter(|s| !s.is_empty())
                .unwrap_or(message);
            let path = self.scoped(&format!(
                "/v1/embeds/chats/{}/embeds/{}",
                segment(chat),
                segment(&ready)
            ))?;
            let canonical = match scoped_await!(self.request(Method::GET, &path, None)) {
                Ok(v) => Some(v),
                Err(Error::Invalid(_)) => None,
                Err(e) => return Err(e),
            };
            if let Some(canonical) = canonical {
                let head = canonical.get("embed").ok_or_else(|| super::send::refusal_trace::protocol_at!())?;
                if text(head, "hashed_chat_id") != chat_hash
                    || text(head, "hashed_embed_id") != sha256(&ready)
                    || head["version_number"].as_u64().unwrap_or(1) != version
                    || text(head, "parent_embed_id") != parent
                    || text(head, "hashed_message_id") != sha256(message_id)
                {
                    super::send::refusal_trace::note(if head["version_number"].as_u64().unwrap_or(1) != version {
                        "stream_artifact_version_differs"
                    } else {
                        "stream_artifact_identity_differs"
                    });
                    return Err(super::send::refusal_trace::protocol_at!());
                }
                let canonical_source = zeroize::Zeroizing::new(crypto::decrypt_combined(
                    required(head, "encrypted_content")?,
                    &embed_key,
                )?);
                let canonical_kind = zeroize::Zeroizing::new(crypto::decrypt_combined(
                    required(head, "encrypted_type")?,
                    &embed_key,
                )?);
                if canonical_source.as_str() != source || canonical_kind.as_str() != kind {
                    super::send::refusal_trace::note("stream_artifact_content_differs");
                    return Err(super::send::refusal_trace::protocol_at!());
                }
                scope.check_chat(self, chat)?;
                self.embeds.insert(ready.clone(), head.clone());
                self.embed_keys.extend(
                    canonical["embed_keys"]
                        .as_array()
                        .ok_or_else(|| super::send::refusal_trace::protocol_at!())?
                        .iter()
                        .cloned(),
                );
            } else {
                if version != 1 {
                    return Err(Error::Invalid(
                        "This artifact revision requires native sealed recovery replay; its output remains pending.",
                    ));
                }
                let encrypted = crypto::server_fields::encrypt_text(source, &embed_key, &[])?;
                let encrypted_type = crypto::server_fields::encrypt_text(kind, &embed_key, &[])?;
                let request = uuid::Uuid::new_v4().to_string();
                let mut payload = json!({"request_id":request,"embed_id":ready,"chat_id":chat,"encrypted_type":encrypted_type,"encrypted_content":encrypted,"encrypted_text_preview":crypto::server_fields::encrypt_text(text(&row,"text_preview"),&embed_key,&[])?,"status":"finished","hashed_chat_id":chat_hash,"hashed_message_id":sha256(message_id),"hashed_user_id":user_hash,"version_number":1,"created_at":now_ms()/1000,"updated_at":now_ms()/1000});
                if !parent.is_empty() {
                    payload["parent_embed_id"] = json!(parent)
                }
                if let Some(ids) = row.get("embed_ids") {
                    payload["embed_ids"] = ids.clone()
                }
                if let Some(team) = &team {
                    payload["team_id"] = json!(team);
                    payload["hashed_team_id"] = json!(sha256(team))
                }
                scoped_await!(send(ws, "store_embed", payload))?;
                let receipt = scoped_await!(wait_embed_receipt(
                    ws,
                    "store_embed_confirmed",
                    &request,
                    &ready
                ))?;
                if receipt["canonical_source"] != "head"
                    || text(&receipt, "canonical_digest") != sha256(&encrypted)
                {
                    return Err(super::send::refusal_trace::protocol_at!());
                }
                if parent.is_empty() {
                    let request = uuid::Uuid::new_v4().to_string();
                    let master_wrapper =
                        scoped_await!(master.encrypt_server_bytes(embed_key.as_ref()))?;
                    let wrappers = json!([{"hashed_embed_id":sha256(&ready),"key_type":"master","hashed_chat_id":null,"encrypted_embed_key":master_wrapper,"hashed_user_id":user_hash,"created_at":now_ms()/1000},{"hashed_embed_id":sha256(&ready),"key_type":"chat","hashed_chat_id":chat_hash,"encrypted_embed_key":crypto::server_fields::encrypt_bytes(embed_key.as_ref(),&key,&[])?,"hashed_user_id":user_hash,"created_at":now_ms()/1000}]);
                    scoped_await!(send(
                        ws,
                        "store_embed_keys",
                        json!({"request_id":request,"keys":wrappers}),
                    ))?;
                    let ack = scoped_await!(wait(
                        ws,
                        "store_embed_keys_confirmed",
                        "request_id",
                        &request
                    ))?;
                    if ack["failed_count"] != 0 || ack["created_count"] != 2 {
                        return Err(super::send::refusal_trace::protocol_at!());
                    }
                    scope.check_chat(self, chat)?;
                    self.embed_keys
                        .extend(wrappers.as_array().ok_or_else(|| super::send::refusal_trace::protocol_at!())?.iter().cloned());
                }
                let stored = scoped_await!(self.request(Method::GET, &path, None))?;
                let head = stored.get("embed").ok_or_else(|| super::send::refusal_trace::protocol_at!())?;
                if text(head, "encrypted_content") != encrypted
                    || text(head, "encrypted_type") != encrypted_type
                    || text(head, "hashed_chat_id") != chat_hash
                    || text(head, "hashed_embed_id") != sha256(&ready)
                {
                    return Err(super::send::refusal_trace::protocol_at!());
                }
                scope.check_chat(self, chat)?;
                self.embeds.insert(ready.clone(), head.clone());
            }
            for history in row["version_history_rows"].as_array().into_iter().flatten() {
                if text(history, "embed_id") != ready {
                    return Err(super::send::refusal_trace::protocol_at!());
                }
                let history_version = history["version_number"].as_u64().ok_or_else(|| super::send::refusal_trace::protocol_at!())?;
                self.persist_canonical_embed_diff(
                    ws,
                    HistoryWrite {
                        embed: &ready, chat, version: history_version,
                        key: &embed_key,
                        snapshot: history.get("snapshot").and_then(Value::as_str),
                        patch: history.get("patch").and_then(Value::as_str),
                        owner_hash: &user_hash, created_at: now_ms()/1000,
                        recovery_record: None, allow_missing_revision: false,
                    },
                    &|client| scope.check_chat(client, chat),
                ).await?;
            }
            keys.insert(ready.clone(), embed_key.clone());
            let decoded = Plain::new(super::toon::decode(source)?);
            scope.check_chat(self, chat)?;
            let item = stream_artifact_item(ready, kind, decoded);
            items.push(item.into_inner());
        }
        for checkpoint in checkpoints.iter() {
            if text(checkpoint, "chat_id") != chat {
                { super::send::refusal_trace::note("persistence_214"); return Err(Error::Forbidden); }
            }
            let checkpoint_id = required(checkpoint, "checkpoint_id")?;
            let summary = checkpoint
                .get("summary_content")
                .or_else(|| checkpoint.get("summary"))
                .and_then(Value::as_str)
                .ok_or_else(|| super::send::refusal_trace::protocol_at!())?;
            scoped_await!(send(
                ws,
                "store_chat_compression_checkpoint",
                json!({"chat_id":chat,"checkpoint_id":checkpoint_id,"encrypted_summary":crypto::encrypt_combined(summary,&key)?,"compressed_up_to_timestamp":checkpoint["compressed_up_to_timestamp"],"compressed_up_to_message_id":checkpoint["compressed_up_to_message_id"],"covered_message_ids":checkpoint["covered_message_ids"],"compressed_message_count":checkpoint["compressed_message_count"],"summary_token_estimate":checkpoint["summary_token_estimate"],"key_version":1,"created_at":now_ms()/1000})
            ))?;
            let receipt = scoped_await!(wait(
                ws,
                "chat_compression_checkpoint_stored",
                "chat_id",
                chat
            ))?;
            let stored = &receipt["checkpoint"];
            if text(stored, "id") != checkpoint_id
                || stored["compressed_up_to_message_id"]
                    != checkpoint["compressed_up_to_message_id"]
                || stored["covered_message_ids"] != checkpoint["covered_message_ids"]
            {
                return Err(super::send::refusal_trace::protocol_at!());
            }
        }
        scope.check_chat(self, chat)?;
        self.require_canonical_read_profile()?;
        Ok(items.into_inner())
    }
}
/// Shared ordinary-stream/recovery operation. A conflict authorizes one fresh
/// canonical read, never another mutation. No unknown write outcome is retried.
pub(super) struct HistoryWrite<'a> {
    pub embed: &'a str,
    pub chat: &'a str,
    pub version: u64,
    pub key: &'a [u8; 32],
    pub snapshot: Option<&'a str>,
    pub patch: Option<&'a str>,
    pub owner_hash: &'a str,
    pub created_at: u64,
    pub recovery_record: Option<&'a str>,
    pub allow_missing_revision: bool,
}
impl Client {
    pub(super) async fn persist_canonical_embed_diff(
        &mut self, ws: &mut Socket, write: HistoryWrite<'_>,
        gate: &impl Fn(&Client) -> Result<()>,
    ) -> Result<String> {
        macro_rules! guarded {
            ($future:expr) => {{
                gate(self)?;
                let result = $future.await;
                gate(self)?;
                result
            }};
        }
        let before = guarded!(self.request_embed_history(write.embed, write.chat, write.version))?;
        if let Some(page) = before {
            return equivalent_history_digest(&page, &write);
        }
        if !write.allow_missing_revision && (write.version != 1 || write.patch.is_some()) {
            return Err(Error::Invalid(
                "This artifact history requires sealed replay; its output remains pending.",
            ));
        }
        if !write.allow_missing_revision && write.snapshot.is_none() { return Err(super::send::refusal_trace::protocol_at!()); }
        let snapshot = write.snapshot.map(|plain| crypto::server_fields::encrypt_text(plain, write.key, &[])).transpose()?;
        let patch = write.patch.map(|plain| crypto::server_fields::encrypt_text(plain, write.key, &[])).transpose()?;
        let digest = sha256(&json!([snapshot, patch]).to_string());
        let request = uuid::Uuid::new_v4().to_string();
        let mut payload = json!({"request_id":request,"embed_id":write.embed,"version_number":write.version,
            "encrypted_snapshot":snapshot,"encrypted_patch":patch,"hashed_user_id":write.owner_hash,"created_at":write.created_at});
        if let Some(record) = write.recovery_record { payload["recovery_record_id"] = json!(record); }
        guarded!(send(ws, "store_embed_diff", payload))?;
        let outcome = guarded!(wait_embed_diff_receipt(ws, &request, write.embed, write.version))?;
        if let Some(receipt) = outcome {
            if receipt["canonical_source"] != "version_row" || text(&receipt, "canonical_digest") != digest {
                return Err(super::send::refusal_trace::protocol_at!());
            }
            return Ok(digest);
        }
        // Only a fully correlated embed_diff_conflict reaches this branch.
        let page = guarded!(self.request_embed_history(write.embed, write.chat, write.version))?
            .ok_or(Error::Conflict)?;
        equivalent_history_digest(&page, &write)
    }
}
/// Validate the bounded response envelope before selecting exactly one row.
pub(super) fn canonical_history_row<'a>(page: &'a Value, embed: &str, version: u64) -> Result<&'a Value> {
    if page["embed_id"] != embed || page["version_number"].as_u64() != Some(version) {
        return Err(super::send::refusal_trace::protocol_at!());
    }
    let mut matches = page["rows"].as_array().ok_or_else(|| super::send::refusal_trace::protocol_at!())?.iter()
        .filter(|row| row["version_number"].as_u64() == Some(version));
    let row = matches.next().ok_or_else(|| super::send::refusal_trace::protocol_at!())?;
    if matches.next().is_some() { return Err(super::send::refusal_trace::protocol_at!()); }
    Ok(row)
}
fn equivalent_history_digest(page: &Value, write: &HistoryWrite<'_>) -> Result<String> {
    let row = canonical_history_row(page, write.embed, write.version)?;
    for (field, expected) in [("encrypted_snapshot", write.snapshot), ("encrypted_patch", write.patch)] {
        let cipher = match row.get(field) {
            None | Some(Value::Null) => None,
            Some(Value::String(value)) => Some(value.as_str()),
            _ => return Err(super::send::refusal_trace::protocol_at!()),
        };
        let plaintext = Plain::new(cipher.map(|value| crypto::decrypt_combined(value, write.key)).transpose()?);
        if plaintext.as_deref() != expected { return Err(Error::Crypto); }
    }
    // Digest the accepted canonical ciphertext, which can differ from fresh AES
    // ciphertext for the same plaintext. Recovery ACKs must pin this exact row.
    Ok(sha256(&json!([row["encrypted_snapshot"], row["encrypted_patch"]]).to_string()))
}
/// None means only the exact correlated immutable-row conflict. Unknown errors,
/// wrong embeds/versions and malformed receipts fail closed without a fresh read.
async fn wait_embed_diff_receipt(
    ws: &mut Socket, request: &str, embed: &str, version: u64,
) -> Result<Option<Value>> {
    let (kind, receipt) = super::transport::wait_embed_diff_outcome(ws, request).await?;
    if receipt["embed_id"] != embed || receipt["version_number"].as_u64() != Some(version) {
        return Err(super::send::refusal_trace::protocol_at!());
    }
    if kind == "error" {
        return if receipt["code"] == "embed_diff_conflict" { Ok(None) } else { Err(Error::Protocol) };
    }
    Ok(Some(receipt))
}
// Move decoded plaintext into an already guarded Item without json! cloning
// a disarmed Value. All fallible/async work is outside this immediate transfer.
fn stream_artifact_item(id: String, kind: &str, decoded: Plain<Value>) -> Plain<Item> {
    let mut item = Plain::new(Item {
        id,
        title: decoded
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or(kind)
            .into(),
        category: kind.into(),
        fields: json!({"type":kind}),
        ..Item::default()
    });
    let fields = item
        .fields
        .as_object_mut()
        .expect("constructed object fields");
    fields.insert("content".into(), decoded.into_inner());
    item
}
/// Canonical embed and diff receipts echo both the request and artifact IDs.
/// A receipt for another artifact cannot authorize this write's readback.
pub(super) async fn wait_embed_receipt(
    ws: &mut Socket,
    response: &str,
    request: &str,
    embed: &str,
) -> Result<Value> {
    let receipt = wait(ws, response, "request_id", request).await?;
    if receipt["embed_id"] != embed {
        return Err(super::send::refusal_trace::protocol_at!());
    }
    Ok(receipt)
}
#[cfg(test)]
#[path = "../../tests/ws_receipt_peer/mod.rs"]
pub(super) mod receipt_test_peer;
#[cfg(test)]
#[path = "../../tests/embed_store_receipts/mod.rs"]
mod receipt_tests;

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "persistence_opaque_tests.rs"]
mod opaque_tests;

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "persistence_history_tests.rs"]
mod history_tests;
