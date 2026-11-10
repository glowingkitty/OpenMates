//! Typed sealed output replay (OMCR2). Immutable identities and canonical
//! ciphertext rereads, rather than transient stream text, authorize every ACK.
use super::transport::{Socket, send, wait};
use super::*;
use super::{
    plaintext::{Plain, Wipe},
    sync_capability::AsyncCryptoScope,
};
use crate::crypto::master::MasterCapability;
use zeroize::Zeroize;
#[derive(Clone)]
struct Prepared {
    identity: Value,
    ready: Value,
    content: Value,
    key: Key,
}
impl Wipe for Prepared {
    fn wipe(&mut self) {
        crate::model::zeroize_json(&mut self.identity);
        crate::model::zeroize_json(&mut self.ready);
        crate::model::zeroize_json(&mut self.content);
        self.key.zeroize();
    }
}
impl Client {
    pub(super) async fn replay_outputs(
        &mut self,
        ws: &mut Socket,
        outputs: &BTreeMap<String, Value>,
        root_hint: Option<(&str, &[u8; 32])>,
    ) -> Result<usize> {
        if outputs.len() > 10_000 {
            return Err(Error::Protocol);
        }
        self.require_canonical_read_profile()?;
        let scope = ReplayScope::begin(self)?;
        let owner = self
            .user
            .get("id")
            .or_else(|| self.user.get("user_id"))
            .and_then(Value::as_str)
            .ok_or(Error::Protocol)?
            .to_owned();
        scope.check(self)?;
        let wrapping = self.wrapping_capability().await?;
        scope.check(self)?;
        let team = self.team()?.map(str::to_owned);
        let mut root_keys: BTreeMap<String, Key> = BTreeMap::new();
        let mut prepared = Plain::new(Vec::<Prepared>::new());
        for output in outputs.values() {
            validate_output(output)?;
            check_replay_scope(self, &scope, output)?;
            let root = required(output, "root_chat_id")?;
            if output.get("root_hashed_team_id").is_some_and(|h| {
                h != &team
                    .as_deref()
                    .map(sha256)
                    .map(Value::String)
                    .unwrap_or(Value::Null)
            }) {
                continue;
            }
            if !root_keys.contains_key(root) {
                let key = if let Some((id, key)) = root_hint.filter(|(id, _)| *id == root) {
                    let _ = id;
                    zeroize::Zeroizing::new(*key)
                } else {
                    let path = self.scoped("/v1/chats/metadata/batch")?;
                    let data = self
                        .replay_request(
                            &scope,
                            output,
                            Method::POST,
                            &path,
                            Some(json!({"chat_ids":[root]})),
                        )
                        .await?;
                    let row = data["chats"]
                        .as_array()
                        .ok_or(Error::Protocol)?
                        .iter()
                        .find(|r| text(r, "id") == root)
                        .ok_or(Error::Forbidden)?
                        .clone();
                    remember_selected_chat_wrapper(self, &scope, &row)?;
                    check_replay_scope(self, &scope, output)?;
                    let key = self.chat_key_with_capability(&row, &wrapping).await?;
                    check_replay_scope(self, &scope, output)?;
                    self.insert_chat_row(root.into(), row);
                    key
                };
                root_keys.insert(root.into(), key);
            }
            let key = root_keys.get(root).ok_or(Error::Crypto)?.clone();
            let ready = match scoped_output_request(
                self,
                &scope,
                ws,
                "recovery_output_get",
                "recovery_output_ready",
                output,
                json!({}),
            )
            .await
            {
                Ok(v) => v,
                Err(Error::Protocol) => {
                    let status = scoped_output_request(
                        self,
                        &scope,
                        ws,
                        "recovery_output_status",
                        "recovery_output_status_ready",
                        output,
                        json!({}),
                    )
                    .await?;
                    same_identity(output, &status)?;
                    if status["state"] == "ACKNOWLEDGED" && status["canonical_verified"] == true {
                        self.verify_acknowledged_output(output, &status, &key, &scope)
                            .await?;
                        continue;
                    } else {
                        return Err(Error::Protocol);
                    }
                }
                Err(e) => return Err(e),
            };
            same_identity(output, &ready)?;
            let recovery = crypto::recovery_keypair(
                &key,
                root,
                output["chat_key_version"].as_u64().ok_or(Error::Protocol)? as u32,
            )?;
            let aad = output_aad(&owner, output)?;
            let envelope: Value = serde_json::from_str(required(&ready, "sealed_payload")?)?;
            let plain = crypto::open_recovery_with_aad(
                &envelope,
                &recovery.private_key,
                &aad,
                2,
                16 * 1024 * 1024,
            )?;
            let mut data = Plain::new(serde_json::from_slice::<Value>(&plain)?);
            for field in [
                "record_id",
                "target_chat_id",
                "subject_id",
                "output_kind",
                "output_version",
            ] {
                if data.get(field) != output.get(field) {
                    return Err(Error::Crypto);
                }
            }
            if !data.get("content").is_some_and(Value::is_object) {
                return Err(Error::Protocol);
            }
            let content = std::mem::take(&mut data["content"]);
            prepared.push(Prepared {
                identity: output.clone(),
                ready,
                content,
                key,
            });
        }
        prepared.sort_by_key(|p| {
            (
                match text(&p.identity, "output_kind") {
                    "message" => 0,
                    "embed" => 1,
                    "diff" => 2,
                    "summary" => 3,
                    _ => 4,
                },
                p.identity["output_version"].as_u64().unwrap_or(0),
            )
        });
        let mut handled = 0;
        let mut deferred = prepared;
        while !deferred.is_empty() {
            let next = deferred
                .iter()
                .position(|p| {
                    let parent = text(&p.content, "parent_embed_id");
                    parent.is_empty()
                        || !deferred.iter().any(|other| {
                            text(&other.identity, "output_kind") == "embed"
                                && text(&other.identity, "subject_id") == parent
                                && other.identity["target_chat_id"] == p.identity["target_chat_id"]
                        })
                })
                .ok_or(Error::Invalid("Recovery artifact dependencies are cyclic."))?;
            let item = Plain::new(deferred.remove(next));
            self.persist_output(ws, &item, &wrapping, &owner, &scope)
                .await?;
            handled += 1;
        }
        scope.check(self)?;
        Ok(handled)
    }
    async fn persist_output(
        &mut self,
        ws: &mut Socket,
        p: &Prepared,
        wrapping: &MasterCapability,
        owner: &str,
        scope: &ReplayScope,
    ) -> Result<()> {
        let o = &p.identity;
        check_replay_scope(self, scope, o)?;
        let c = &p.content;
        let r = &p.ready;
        let key = &p.key;
        let target = required(o, "target_chat_id")?;
        let subject = required(o, "subject_id")?;
        let kind = required(o, "output_kind")?;
        let now = now_ms() / 1000;
        match kind {
            "message" => {
                let role = o
                    .get("message_role")
                    .and_then(Value::as_str)
                    .unwrap_or("assistant");
                if !["user", "assistant"].contains(&role)
                    || c.get("role")
                        .and_then(Value::as_str)
                        .is_some_and(|v| v != role)
                {
                    return Err(Error::Protocol);
                }
                let mut encrypted = json!({"client_message_id":subject,"chat_id":target,"role":role,"encrypted_content":crypto::encrypt_combined(c.get("content").and_then(Value::as_str).ok_or(Error::Protocol)?,key)?,"created_at":c["created_at"].as_u64().unwrap_or(now),"updated_at":now});
                for (src, dst) in [
                    ("category", "encrypted_category"),
                    ("model_name", "encrypted_model_name"),
                    ("thinking_content", "encrypted_thinking_content"),
                    ("thinking_signature", "encrypted_thinking_signature"),
                ] {
                    if let Some(value) = c.get(src).and_then(Value::as_str) {
                        encrypted[dst] = json!(crypto::encrypt_combined(value, key)?);
                    }
                }
                if role == "assistant" {
                    encrypted["encrypted_sender_name"] =
                        json!(crypto::encrypt_combined("Assistant", key)?)
                }
                let mut payload = json!({"expected_messages_v":r["messages_v"],if role=="user"{"encrypted_user_message"}else{"encrypted_assistant_message"}:encrypted});
                if let Some(wrapped) = r
                    .get("encrypted_chat_key")
                    .and_then(Value::as_str)
                    .filter(|s| !s.is_empty())
                {
                    check_replay_scope(self, scope, o)?;
                    let canonical = wrapping.decrypt_bytes(wrapped).await?;
                    check_replay_scope(self, scope, o)?;
                    if canonical.as_slice() != key.as_ref() {
                        return Err(Error::Crypto);
                    }
                } else {
                    check_replay_scope(self, scope, o)?;
                    let encrypted_key = wrapping.encrypt_server_bytes(key.as_ref()).await?;
                    check_replay_scope(self, scope, o)?;
                    payload["encrypted_chat_key"] = json!(encrypted_key);
                    payload["encrypted_title"] = json!(crypto::encrypt_combined("Sub-chat", key)?)
                }
                let ack = scoped_output_request(
                    self,
                    scope,
                    ws,
                    "recovery_output_persist_message",
                    "recovery_output_persisted",
                    o,
                    payload,
                )
                .await?;
                acknowledged(&ack)?;
            }
            "summary" => {
                let summary = c
                    .get("summary")
                    .and_then(Value::as_str)
                    .ok_or(Error::Protocol)?;
                let mut payload = json!({"expected_metadata_v":r["metadata_v"],"encrypted_summary":crypto::encrypt_combined(summary,key)?});
                if let Some(version) = c.get("source_metadata_v") {
                    if version.as_u64().is_none() || summary.chars().count() > 1000 {
                        return Err(Error::Protocol);
                    }
                    payload["source_metadata_v"] = version.clone();
                    for (field, max) in [("title", 200), ("category", 100), ("icon", 100)] {
                        if let Some(value) = c.get(field) {
                            let text = value
                                .as_str()
                                .filter(|v| !v.is_empty() && v.chars().count() <= max)
                                .ok_or(Error::Protocol)?;
                            payload[format!("encrypted_{field}")] =
                                json!(crypto::encrypt_combined(text, key)?);
                        }
                    }
                }
                let ack = scoped_output_request(
                    self,
                    scope,
                    ws,
                    "recovery_output_persist_summary",
                    "recovery_output_summary_persisted",
                    o,
                    payload,
                )
                .await?;
                acknowledged(&ack)?;
            }
            "checkpoint" => {
                if text(c, "summary_message_id") != subject {
                    return Err(Error::Protocol);
                }
                let ids = c["covered_message_ids"]
                    .as_array()
                    .filter(|v| !v.is_empty() && v.len() <= 20_000)
                    .ok_or(Error::Protocol)?;
                let mut previous = "";
                for id in ids {
                    let id = id
                        .as_str()
                        .filter(|s| !s.is_empty() && s.len() <= 255)
                        .ok_or(Error::Protocol)?;
                    if id <= previous {
                        return Err(Error::Protocol);
                    }
                    previous = id;
                }
                if ids
                    .iter()
                    .map(|v| v.as_str().unwrap_or("").len() + 3)
                    .sum::<usize>()
                    > 1_048_576
                {
                    return Err(Error::Protocol);
                }
                let encrypted = crypto::encrypt_combined(
                    c.get("summary_content")
                        .and_then(Value::as_str)
                        .ok_or(Error::Protocol)?,
                    key,
                )?;
                scoped_send(self, scope, o, ws,"store_chat_compression_checkpoint",json!({"chat_id":target,"checkpoint_id":subject,"encrypted_summary":encrypted,"compressed_up_to_timestamp":c["compressed_up_to_timestamp"],"compressed_up_to_message_id":required(c,"compressed_up_to_message_id")?,"covered_message_ids":ids,"compressed_message_count":c["compressed_message_count"],"summary_token_estimate":c["summary_token_estimate"],"key_version":o["chat_key_version"],"created_at":now})).await?;
                let receipt = scoped_wait(
                    self,
                    scope,
                    o,
                    ws,
                    "chat_compression_checkpoint_stored",
                    "chat_id",
                    target,
                )
                .await?;
                let saved = &receipt["checkpoint"];
                if text(saved, "id") != subject
                    || saved["compressed_up_to_message_id"] != c["compressed_up_to_message_id"]
                    || saved["covered_message_ids"] != c["covered_message_ids"]
                {
                    return Err(Error::Protocol);
                }
                let ack=scoped_output_request(self, scope, ws,"recovery_output_ack_checkpoint","recovery_output_checkpoint_acknowledged",o,json!({"encrypted_summary":required(saved,"encrypted_summary")?,"compressed_up_to_message_id":c["compressed_up_to_message_id"],"covered_message_ids":ids})).await?;
                acknowledged(&ack)?;
            }
            "embed" | "diff" => self.persist_sealed_embed(ws, p, owner, scope).await?,
            _ => return Err(Error::Protocol),
        }
        check_replay_scope(self, scope, o)?;
        Ok(())
    }
    async fn persist_sealed_embed(
        &mut self,
        ws: &mut Socket,
        p: &Prepared,
        owner: &str,
        scope: &ReplayScope,
    ) -> Result<()> {
        let o = &p.identity;
        check_replay_scope(self, scope, o)?;
        let c = &p.content;
        let target = required(o, "target_chat_id")?;
        let id = required(o, "subject_id")?;
        let version = o["output_version"].as_u64().ok_or(Error::Protocol)?;
        if text(c, "embed_id") != id
            || c.get("version_number")
                .and_then(Value::as_u64)
                .is_some_and(|v| v != version)
        {
            return Err(Error::Protocol);
        }
        let path = self.scoped(&format!(
            "/v1/embeds/chats/{}/embeds/{}",
            segment(target),
            segment(id)
        ))?;
        let mut existing = self.replay_optional_get(scope, o, &path).await?;
        let mut parent = c
            .get("parent_embed_id")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .map(str::to_owned);
        if let Some(before) = &existing {
            if text(&before["embed"], "hashed_chat_id") != sha256(target) {
                return Err(Error::Forbidden);
            }
            let canonical = text(&before["embed"], "parent_embed_id");
            if parent.as_deref().is_some_and(|p| p != canonical) {
                return Err(Error::Crypto);
            }
            parent = if canonical.is_empty() {
                None
            } else {
                Some(canonical.into())
            };
        }
        let key_subject = parent.as_deref().unwrap_or(id);
        let key = crypto::derive_embed_key(&p.key, key_subject)?;
        let master = self.master_capability()?;
        let owner_hash = sha256(owner);
        let team_hash = self.team()?.map(sha256);
        let key_path = self.scoped(&format!(
            "/v1/embeds/chats/{}/embeds/{}",
            segment(target),
            segment(key_subject)
        ))?;
        let parent_page = if parent.is_some() {
            let page = self
                .replay_request(scope, o, Method::GET, &key_path, None)
                .await?;
            if text(&page["embed"], "hashed_chat_id") != sha256(target)
                || !text(&page["embed"], "parent_embed_id").is_empty()
            {
                return Err(Error::Forbidden);
            }
            Some(page)
        } else {
            None
        };
        let key_page = parent_page.as_ref().or(existing.as_ref());
        if let Some(page) = key_page {
            verify_wrappers_with_capability(
                self,
                scope,
                &page["embed_keys"],
                key_subject,
                target,
                &key,
                &p.key,
                &master,
                &owner_hash,
            )
            .await?;
        }
        let mut source = "head";
        let digest;
        if text(o, "output_kind") == "diff" {
            if c["version_number"].as_u64() != Some(version)
                || (version == 1
                    && (c.get("snapshot").and_then(Value::as_str).is_none()
                        || c.get("patch").and_then(Value::as_str).is_some()))
                || (version > 1 && c.get("patch").and_then(Value::as_str).is_none())
            {
                return Err(Error::Protocol);
            }
            digest = self
                .persist_canonical_embed_diff(
                    ws,
                    super::persistence::HistoryWrite {
                        embed: id,
                        chat: target,
                        version,
                        key: &key,
                        snapshot: c.get("snapshot").and_then(Value::as_str),
                        patch: c.get("patch").and_then(Value::as_str),
                        owner_hash: &owner_hash,
                        created_at: c["created_at"].as_u64().unwrap_or(now_ms() / 1000),
                        recovery_record: Some(required(o, "record_id")?),
                        allow_missing_revision: true,
                    },
                    &|client| check_replay_scope(client, scope, o),
                )
                .await?;
            source = "version_row";
        } else {
            let content = c
                .get("content")
                .and_then(Value::as_str)
                .ok_or(Error::Protocol)?;
            let kind = required(c, "type")?;
            let message = required(c, "message_id")?;
            let current_version = existing
                .as_ref()
                .map(|p| p["embed"]["version_number"].as_u64().unwrap_or(1));
            if let Some(current) = current_version {
                let page = existing.as_ref().ok_or(Error::Protocol)?;
                let head = &page["embed"];
                if text(head, "hashed_user_id") != owner_hash
                    || head.get("hashed_team_id").and_then(Value::as_str) != team_hash.as_deref()
                    || zeroize::Zeroizing::new(crypto::decrypt_combined(
                        required(head, "encrypted_type")?,
                        &key,
                    )?)
                    .as_str()
                        != kind
                {
                    return Err(Error::Crypto);
                }
                if current == version {
                    if zeroize::Zeroizing::new(crypto::decrypt_combined(
                        required(head, "encrypted_content")?,
                        &key,
                    )?)
                    .as_str()
                        != content
                        || text(head, "hashed_message_id") != sha256(message)
                    {
                        return Err(Error::Crypto);
                    }
                    digest = sha256(required(head, "encrypted_content")?);
                } else if current + 1 == version && parent.is_none() {
                    let types = verify_wrappers_with_capability(
                        self,
                        scope,
                        &page["embed_keys"],
                        id,
                        target,
                        &key,
                        &p.key,
                        &master,
                        &owner_hash,
                    )
                    .await?;
                    if types.len() != 2
                        || page["embed_keys"]
                            .as_array()
                            .is_none_or(|rows| rows.len() != 2)
                        || text(head, "embed_id") != id
                        || text(head, "hashed_embed_id") != sha256(id)
                        || head["status"] != "finished"
                        || current > 2_147_483_647
                        || head
                            .get("root_embed_id")
                            .and_then(Value::as_str)
                            .is_some_and(|value| value != id)
                    {
                        return Err(Error::Crypto);
                    }
                    let decoded = Plain::new(super::toon::decode(content)?);
                    for field in ["app_id", "skill_id"] {
                        if let Some(value) = c.get(field).or_else(|| decoded.get(field))
                            && head.get(field) != Some(value)
                        {
                            return Err(Error::Crypto);
                        }
                    }
                    if (team_hash.is_some()
                        || head["workspace_origin"] == "chat"
                        || !head["app_id"].is_null()
                        || !head["skill_id"].is_null())
                        && (text(head, "app_id").is_empty() || text(head, "skill_id").is_empty())
                    {
                        return Err(Error::Crypto);
                    }
                    let encrypted_type = required(head, "encrypted_type")?.to_owned();
                    digest = self
                        .store_sealed_head(ws, o, c, &key, Some(&encrypted_type), owner, scope)
                        .await?;
                } else if current > version {
                    let history_path = self.scoped(&format!(
                        "/v1/embeds/{}/versions/{version}?capability=bounded-v1&chat_id={}",
                        segment(id),
                        segment(target)
                    ))?;
                    let history = self
                        .replay_request(scope, o, Method::GET, &history_path, None)
                        .await?;
                    if text(&history, "embed_id") != id
                        || history["version_number"].as_u64() != Some(version)
                    {
                        return Err(Error::Protocol);
                    }
                    let rows = history["rows"]
                        .as_array()
                        .filter(|rows| !rows.is_empty() && rows.len() <= 33)
                        .ok_or(Error::Protocol)?;
                    let mut previous = rows[0]["version_number"]
                        .as_u64()
                        .ok_or(Error::Protocol)?
                        .checked_sub(1)
                        .ok_or(Error::Protocol)?;
                    let mut reconstructed: Option<zeroize::Zeroizing<String>> = None;
                    for row in rows {
                        let v = row["version_number"].as_u64().ok_or(Error::Protocol)?;
                        if v != previous + 1 {
                            return Err(Error::Protocol);
                        }
                        reconstructed = if let Some(snapshot) = row["encrypted_snapshot"].as_str() {
                            Some(zeroize::Zeroizing::new(crypto::decrypt_combined(
                                snapshot, &key,
                            )?))
                        } else {
                            let content = reconstructed
                                .as_ref()
                                .map(|s| s.as_str())
                                .ok_or(Error::Protocol)?;
                            Some(zeroize::Zeroizing::new(super::patch::apply(
                                content,
                                &zeroize::Zeroizing::new(crypto::decrypt_combined(
                                    required(row, "encrypted_patch")?,
                                    &key,
                                )?),
                            )?))
                        };
                        previous = v;
                    }
                    let decoded = Plain::new(super::toon::decode(content)?);
                    if text(&decoded, "type") != kind {
                        return Err(Error::Crypto);
                    }
                    let sealed_source = zeroize::Zeroizing::new(historical_source(&decoded, kind)?);
                    let last = rows.last().ok_or(Error::Protocol)?;
                    if previous != version
                        || reconstructed.as_ref().map(|s| s.as_str())
                            != Some(sealed_source.as_str())
                    {
                        return Err(Error::Crypto);
                    }
                    digest = sha256(
                        &json!([last["encrypted_snapshot"], last["encrypted_patch"]]).to_string(),
                    );
                    source = "version_row";
                } else {
                    return Err(Error::Protocol);
                }
            } else {
                if version > 1 && parent.is_none() {
                    return Err(Error::Forbidden);
                }
                digest = self
                    .store_sealed_head(ws, o, c, &key, None, owner, scope)
                    .await?;
            }
        }
        // Bootstrap only a newly sealed root. Existing wrappers must authenticate
        // the derived key before any missing wrapper is added.
        let existing_types = if let Some(page) = key_page {
            verify_wrappers_with_capability(
                self,
                scope,
                &page["embed_keys"],
                key_subject,
                target,
                &key,
                &p.key,
                &master,
                &owner_hash,
            )
            .await?
        } else {
            std::collections::BTreeSet::new()
        };
        let mut wrappers = vec![];
        for kind in ["master", "chat"] {
            if !existing_types.contains(kind) {
                check_replay_scope(self, scope, o)?;
                let encrypted = if kind == "master" {
                    master.encrypt_server_bytes(key.as_ref()).await?
                } else {
                    crypto::server_fields::encrypt_bytes(key.as_ref(), &p.key, &[])?
                };
                check_replay_scope(self, scope, o)?;
                wrappers.push(json!({"hashed_embed_id":sha256(key_subject),"key_type":kind,"hashed_chat_id":if kind=="chat"{Some(sha256(target))}else{None},"encrypted_embed_key":encrypted,"hashed_user_id":owner_hash,"created_at":now_ms()/1000}));
            }
        }
        if !wrappers.is_empty() {
            let receipt = scoped_store_output(
                self,
                scope,
                ws,
                "store_embed_keys",
                "store_embed_keys_confirmed",
                o,
                json!({"keys":wrappers}),
            )
            .await?;
            if receipt["failed_count"] != 0
                || receipt["created_count"].as_u64() != Some(wrappers.len() as u64)
                || receipt["requested_count"].as_u64() != Some(wrappers.len() as u64)
            {
                return Err(Error::Protocol);
            }
        }
        let keys = self
            .replay_request(scope, o, Method::GET, &key_path, None)
            .await?;
        let types = verify_wrappers_with_capability(
            self,
            scope,
            &keys["embed_keys"],
            key_subject,
            target,
            &key,
            &p.key,
            &master,
            &owner_hash,
        )
        .await?;
        if !types.contains("master") || !types.contains("chat") {
            return Err(Error::Protocol);
        }
        check_replay_scope(self, scope, o)?;
        self.embed_keys.extend(
            keys["embed_keys"]
                .as_array()
                .ok_or(Error::Protocol)?
                .iter()
                .cloned(),
        );
        existing = Some(
            self.replay_request(scope, o, Method::GET, &path, None)
                .await?,
        );
        let head = &existing.as_ref().ok_or(Error::Protocol)?["embed"];
        if text(head, "hashed_chat_id") != sha256(target)
            || head
                .get("parent_embed_id")
                .and_then(Value::as_str)
                .filter(|s| !s.is_empty())
                != parent.as_deref()
        {
            return Err(Error::Crypto);
        }
        if source == "head" {
            if head["version_number"].as_u64().unwrap_or(1) != version
                || sha256(required(head, "encrypted_content")?) != digest
                || zeroize::Zeroizing::new(crypto::decrypt_combined(
                    required(head, "encrypted_content")?,
                    &key,
                )?)
                .as_str()
                    != required(c, "content")?
                || zeroize::Zeroizing::new(crypto::decrypt_combined(
                    required(head, "encrypted_type")?,
                    &key,
                )?)
                .as_str()
                    != required(c, "type")?
            {
                return Err(Error::Crypto);
            }
        } else {
            let history_path = self.scoped(&format!(
                "/v1/embeds/{}/versions/{version}?capability=bounded-v1&chat_id={}",
                segment(id),
                segment(target)
            ))?;
            let history = self
                .replay_request(scope, o, Method::GET, &history_path, None)
                .await?;
            let row = super::persistence::canonical_history_row(&history, id, version)?;
            if sha256(&json!([row["encrypted_snapshot"], row["encrypted_patch"]]).to_string())
                != digest
            {
                return Err(Error::Crypto);
            }
        }
        self.publish_recovered_embed(scope, o, id, head)?;
        let ack = scoped_output_request(
            self,
            scope,
            ws,
            "recovery_output_ack_embed",
            "recovery_output_embed_acknowledged",
            o,
            json!({"canonical_digest":digest,"canonical_source":source}),
        )
        .await?;
        acknowledged(&ack)?;
        check_replay_scope(self, scope, o)?;
        Ok(())
    }
    // Actual private publication boundary, after all canonical validation and
    // immediately before the existing ACK continuation. No await separates the
    // final resource/owner/ACL/wrapper-expiry check from cache mutation.
    fn publish_recovered_embed(
        &mut self,
        scope: &ReplayScope,
        o: &Value,
        id: &str,
        head: &Value,
    ) -> Result<()> {
        check_replay_scope(self, scope, o)?;
        self.embeds.insert(id.into(), head.clone());
        Ok(())
    }
    async fn store_sealed_head(
        &mut self,
        ws: &mut Socket,
        o: &Value,
        c: &Value,
        key: &[u8; 32],
        canonical_type: Option<&str>,
        owner: &str,
        scope: &ReplayScope,
    ) -> Result<String> {
        let encrypted = crypto::server_fields::encrypt_text(required(c, "content")?, key, &[])?;
        let kind =
            canonical_type
                .map(str::to_owned)
                .unwrap_or(crypto::server_fields::encrypt_text(
                    required(c, "type")?,
                    key,
                    &[],
                )?);
        let target = required(o, "target_chat_id")?;
        let mut payload = json!({"embed_id":o["subject_id"],"chat_id":target,"encrypted_content":encrypted,"encrypted_type":kind,"status":"finished","hashed_chat_id":sha256(target),"hashed_message_id":sha256(required(c,"message_id")?),"hashed_user_id":sha256(owner),"version_number":o["output_version"],"is_private":c["is_private"]==true,"is_shared":c["is_shared"]==true,"created_at":c["createdAt"].as_u64().unwrap_or(now_ms()/1000),"updated_at":c["updatedAt"].as_u64().unwrap_or(now_ms()/1000)});
        for field in [
            "parent_embed_id",
            "embed_ids",
            "content_hash",
            "app_id",
            "skill_id",
        ] {
            if let Some(v) = c.get(field) {
                payload[field] = v.clone()
            }
        }
        if text(c, "parent_embed_id").is_empty() && canonical_type.is_none() {
            let decoded = Plain::new(super::toon::decode(required(c, "content")?)?);
            let app = c.get("app_id").or_else(|| decoded.get("app_id"));
            let skill = c.get("skill_id").or_else(|| decoded.get("skill_id"));
            if app.is_some() || skill.is_some() {
                let app = app.and_then(Value::as_str).ok_or(Error::Protocol)?;
                let skill = skill.and_then(Value::as_str).ok_or(Error::Protocol)?;
                if !regex::Regex::new(r"^[a-z][a-z0-9_]{0,63}$")
                    .expect("static")
                    .is_match(app)
                    || !regex::Regex::new(r"^[a-z][a-z0-9_-]{0,63}$")
                        .expect("static")
                        .is_match(skill)
                {
                    return Err(Error::Protocol);
                }
                payload["app_id"] = json!(app);
                payload["skill_id"] = json!(skill);
            }
        }
        if let Some(task) = c.get("task_id").and_then(Value::as_str) {
            payload["hashed_task_id"] = json!(sha256(task))
        }
        if let Some(text) = c.get("text_preview").and_then(Value::as_str) {
            payload["encrypted_text_preview"] =
                json!(crypto::server_fields::encrypt_text(text, key, &[])?)
        }
        if let Some(team) = self.team()? {
            payload["team_id"] = json!(team);
            payload["hashed_team_id"] = json!(sha256(team))
        }
        let receipt = scoped_store_output(
            self,
            scope,
            ws,
            "store_embed",
            "store_embed_confirmed",
            o,
            payload,
        )
        .await?;
        let digest = sha256(&encrypted);
        if receipt["canonical_source"] != "head" || text(&receipt, "canonical_digest") != digest {
            return Err(Error::Protocol);
        }
        Ok(digest)
    }
    async fn replay_optional_get(
        &mut self,
        scope: &ReplayScope,
        o: &Value,
        path: &str,
    ) -> Result<Option<Value>> {
        match self.replay_request(scope, o, Method::GET, path, None).await {
            Ok(v) => Ok(Some(v)),
            Err(Error::Invalid(_)) => Ok(None),
            Err(e) => Err(e),
        }
    }
    async fn verify_acknowledged_output(
        &mut self,
        o: &Value,
        status: &Value,
        key: &[u8; 32],
        scope: &ReplayScope,
    ) -> Result<()> {
        if !["embed", "diff"].contains(&text(o, "output_kind")) {
            return Ok(());
        }
        let target = required(o, "target_chat_id")?;
        let id = required(o, "subject_id")?;
        let path = self.scoped(&format!(
            "/v1/embeds/chats/{}/embeds/{}",
            segment(target),
            segment(id)
        ))?;
        let data = self
            .replay_request(scope, o, Method::GET, &path, None)
            .await?;
        let head = &data["embed"];
        if text(head, "hashed_chat_id") != sha256(target) {
            return Err(Error::Forbidden);
        }
        let parent = text(head, "parent_embed_id");
        let embed_key = crypto::derive_embed_key(key, if parent.is_empty() { id } else { parent })?;
        if status["canonical_source"] == "head" {
            if head["version_number"] != o["output_version"]
                || sha256(required(head, "encrypted_content")?) != text(status, "canonical_digest")
            {
                return Err(Error::Crypto);
            }
            let _plain = zeroize::Zeroizing::new(crypto::decrypt_combined(
                required(head, "encrypted_content")?,
                &embed_key,
            )?);
        } else if status["canonical_source"] == "version_row" {
            let version = o["output_version"].as_u64().ok_or(Error::Protocol)?;
            let path = self.scoped(&format!(
                "/v1/embeds/{}/versions/{version}?capability=bounded-v1&chat_id={}",
                segment(id),
                segment(target)
            ))?;
            let data = self
                .replay_request(scope, o, Method::GET, &path, None)
                .await?;
            let row = super::persistence::canonical_history_row(&data, id, version)?;
            if sha256(&json!([row["encrypted_snapshot"], row["encrypted_patch"]]).to_string())
                != text(status, "canonical_digest")
            {
                return Err(Error::Crypto);
            }
            for field in ["encrypted_snapshot", "encrypted_patch"] {
                if let Some(v) = row[field].as_str() {
                    let _plain = zeroize::Zeroizing::new(crypto::decrypt_combined(v, &embed_key)?);
                }
            }
        } else {
            return Err(Error::Protocol);
        }
        check_replay_scope(self, scope, o)?;
        Ok(())
    }
    async fn replay_request(
        &mut self,
        scope: &ReplayScope,
        o: &Value,
        method: Method,
        path: &str,
        body: Option<Value>,
    ) -> Result<Value> {
        check_replay_scope(self, scope, o)?;
        let value = Plain::new(self.request(method, path, body).await?);
        check_replay_scope(self, scope, o)?;
        Ok(value.into_inner())
    }
}

// An operation-local restriction, not a session/key/association grant. A validated
// wrapper deadline is retained through subsequent IO and ACK gates, including
// when that wrapper expired while an opaque AES future was suspended.
struct ReplayScope {
    crypto: AsyncCryptoScope,
    wrapper_expiry: std::sync::Mutex<Option<u64>>,
}
impl ReplayScope {
    fn begin(client: &Client) -> Result<Self> {
        let scope = Self {
            crypto: AsyncCryptoScope::begin(client)?,
            wrapper_expiry: std::sync::Mutex::new(None),
        };
        scope.check(client)?;
        Ok(scope)
    }
    fn check(&self, client: &Client) -> Result<()> {
        self.crypto.check(client)?;
        if self
            .wrapper_expiry
            .lock()
            .map_err(|_| Error::Cancelled)?
            .is_some_and(|at| at <= now_ms())
        {
            return Err(Error::Conflict);
        }
        Ok(())
    }
    fn check_chat(&self, client: &Client, id: &str) -> Result<()> {
        self.check(client)?;
        self.crypto.check_chat(client, id)
    }
    fn remember_wrapper(&self, row: &Value) -> Result<()> {
        for name in ["wrapper_version", "team_key_epoch"] {
            if let Some(value) = row.get(name).filter(|v| !v.is_null()) {
                match value.as_u64() {
                    Some(1) => {}
                    Some(_) => return Err(Error::Conflict),
                    None => return Err(Error::Protocol),
                }
            }
        }
        if let Some(value) = row.get("expires_at").filter(|v| !v.is_null()) {
            let at = value
                .as_u64()
                .ok_or(Error::Protocol)?
                .checked_mul(1000)
                .ok_or(Error::Protocol)?;
            if at <= now_ms() {
                return Err(Error::Conflict);
            }
            let mut deadline = self.wrapper_expiry.lock().map_err(|_| Error::Cancelled)?;
            *deadline = Some(deadline.map_or(at, |old| old.min(at)));
        }
        Ok(())
    }
}
fn check_replay_scope(client: &Client, scope: &ReplayScope, o: &Value) -> Result<()> {
    client.require_canonical_read_profile()?;
    scope.check_chat(client, required(o, "root_chat_id")?)?;
    scope.check_chat(client, required(o, "target_chat_id")?)
}
fn remember_selected_chat_wrapper(client: &Client, scope: &ReplayScope, row: &Value) -> Result<()> {
    if text(row, "chat_visibility") == "direct" {
        client.native_master_key()?;
        return Ok(());
    }
    let id = required(row, "id")?;
    let team = client.team()?;
    // Retain the established first matching wrapper semantics of chat_key.
    if let Some(wrapper) = client
        .wrappers
        .iter()
        .chain(row["chat_key_wrappers"].as_array().into_iter().flatten())
        .find(|w| {
            text(w, "hashed_chat_id") == sha256(id)
                && text(w, "key_type") == if team.is_some() { "team" } else { "master" }
                && team.is_none_or(|team| text(w, "hashed_team_id") == sha256(team))
        })
    {
        scope.remember_wrapper(wrapper)?;
    }
    Ok(())
}
#[allow(clippy::too_many_arguments)]
async fn verify_wrappers_with_capability(
    client: &Client,
    scope: &ReplayScope,
    rows: &Value,
    subject: &str,
    chat: &str,
    key: &[u8; 32],
    chat_key: &[u8; 32],
    master: &MasterCapability,
    owner_hash: &str,
) -> Result<std::collections::BTreeSet<String>> {
    let mut kinds = std::collections::BTreeSet::new();
    for row in rows.as_array().ok_or(Error::Protocol)? {
        scope.check_chat(client, chat)?;
        let kind = text(row, "key_type");
        if !["master", "chat"].contains(&kind) {
            continue;
        }
        if text(row, "hashed_user_id") != owner_hash
            || (kind == "master" && !text(row, "hashed_chat_id").is_empty())
            || text(row, "hashed_embed_id") != sha256(subject)
            || (kind == "chat" && text(row, "hashed_chat_id") != sha256(chat))
            || !kinds.insert(kind.into())
        {
            return Err(Error::Crypto);
        }
        scope.remember_wrapper(row)?;
        let encrypted = required(row, "encrypted_embed_key")?;
        let decoded = if kind == "master" {
            master.decrypt_bytes(encrypted).await?
        } else {
            crypto::server_fields::decrypt_bytes(encrypted, chat_key, &[])?
        };
        scope.check_chat(client, chat)?;
        scope.remember_wrapper(row)?;
        if decoded.as_slice() != key {
            return Err(Error::Crypto);
        }
    }
    scope.check_chat(client, chat)?;
    Ok(kinds)
}
async fn scoped_send(
    client: &Client,
    scope: &ReplayScope,
    o: &Value,
    ws: &mut Socket,
    kind: &str,
    payload: Value,
) -> Result<()> {
    check_replay_scope(client, scope, o)?;
    send(ws, kind, payload).await?;
    check_replay_scope(client, scope, o)
}
async fn scoped_wait(
    client: &Client,
    scope: &ReplayScope,
    o: &Value,
    ws: &mut Socket,
    kind: &str,
    field: &str,
    value: &str,
) -> Result<Value> {
    check_replay_scope(client, scope, o)?;
    let result = Plain::new(wait(ws, kind, field, value).await?);
    check_replay_scope(client, scope, o)?;
    Ok(result.into_inner())
}
async fn scoped_output_request(
    client: &Client,
    scope: &ReplayScope,
    ws: &mut Socket,
    kind: &str,
    response: &str,
    o: &Value,
    extra: Value,
) -> Result<Value> {
    output_request_with_gate(ws, kind, response, o, extra, &|| {
        check_replay_scope(client, scope, o)
    })
    .await
}
async fn scoped_store_output(
    client: &Client,
    scope: &ReplayScope,
    ws: &mut Socket,
    kind: &str,
    response: &str,
    o: &Value,
    extra: Value,
) -> Result<Value> {
    store_output_with_gate(ws, kind, response, o, extra, &|| {
        check_replay_scope(client, scope, o)
    })
    .await
}
// Existing receipt fixtures retain their original native helper signature.
#[cfg(test)]
async fn store_output(
    ws: &mut Socket,
    kind: &str,
    response: &str,
    o: &Value,
    extra: Value,
) -> Result<Value> {
    store_output_with_gate(ws, kind, response, o, extra, &|| Ok(())).await
}

#[cfg(test)]
fn verify_wrappers(
    rows: &Value,
    subject: &str,
    chat: &str,
    key: &[u8; 32],
    chat_key: &[u8; 32],
    master: &[u8; 32],
    owner_hash: &str,
) -> Result<std::collections::BTreeSet<String>> {
    let mut kinds = std::collections::BTreeSet::new();
    for row in rows.as_array().ok_or(Error::Protocol)? {
        let kind = text(row, "key_type");
        if !["master", "chat"].contains(&kind) {
            continue;
        }
        if text(row, "hashed_user_id") != owner_hash
            || (kind == "master" && !text(row, "hashed_chat_id").is_empty())
            || text(row, "hashed_embed_id") != sha256(subject)
            || (kind == "chat" && text(row, "hashed_chat_id") != sha256(chat))
            || !kinds.insert(kind.into())
        {
            return Err(Error::Crypto);
        }
        let decoded = crypto::decrypt_bytes(
            required(row, "encrypted_embed_key")?,
            if kind == "master" { master } else { chat_key },
        )?;
        if decoded.as_slice() != key {
            return Err(Error::Crypto);
        }
    }
    Ok(kinds)
}
async fn output_request_with_gate(
    ws: &mut Socket,
    kind: &str,
    response: &str,
    o: &Value,
    extra: Value,
    gate: &impl Fn() -> Result<()>,
) -> Result<Value> {
    let request = uuid::Uuid::new_v4().to_string();
    let mut payload =
        json!({"protocol_version":1,"record_id":required(o,"record_id")?,"request_id":request});
    payload
        .as_object_mut()
        .ok_or(Error::Protocol)?
        .extend(extra.as_object().ok_or(Error::Protocol)?.clone());
    gate()?;
    send(ws, kind, payload).await?;
    gate()?;
    let response = Plain::new(wait(ws, response, "request_id", &request).await?);
    gate()?;
    if response
        .get("record_id")
        .is_some_and(|v| v != &o["record_id"])
    {
        return Err(Error::Crypto);
    }
    Ok(response.into_inner())
}
async fn store_output_with_gate(
    ws: &mut Socket,
    kind: &str,
    response: &str,
    o: &Value,
    extra: Value,
    gate: &impl Fn() -> Result<()>,
) -> Result<Value> {
    let request = uuid::Uuid::new_v4().to_string();
    let mut payload = json!({"request_id":request,"recovery_record_id":required(o,"record_id")?});
    payload
        .as_object_mut()
        .ok_or(Error::Protocol)?
        .extend(extra.as_object().ok_or(Error::Protocol)?.clone());
    let embed = if matches!(kind, "store_embed" | "store_embed_diff") {
        Some(required(&extra, "embed_id")?)
    } else {
        None
    };
    gate()?;
    send(ws, kind, payload).await?;
    gate()?;
    let result = Plain::new(if let Some(embed) = embed {
        super::persistence::wait_embed_receipt(ws, response, &request, embed).await?
    } else {
        wait(ws, response, "request_id", &request).await?
    });
    gate()?;
    Ok(result.into_inner())
}
#[cfg(test)]
#[path = "../../tests/recovery_store_receipts/mod.rs"]
mod store_receipt_tests;
fn acknowledged(value: &Value) -> Result<()> {
    if value["state"] == "ACKNOWLEDGED" {
        Ok(())
    } else {
        Err(Error::Protocol)
    }
}
fn same_identity(expected: &Value, actual: &Value) -> Result<()> {
    for field in [
        "record_id",
        "root_chat_id",
        "target_chat_id",
        "turn_id",
        "subject_id",
        "output_kind",
        "output_version",
        "chat_key_version",
    ] {
        if expected.get(field) != actual.get(field) {
            return Err(Error::Crypto);
        }
    }
    if expected.get("root_hashed_team_id").is_some()
        && expected.get("root_hashed_team_id") != actual.get("root_hashed_team_id")
    {
        return Err(Error::Crypto);
    }
    Ok(())
}
pub(super) fn validate_output(value: &Value) -> Result<()> {
    for field in ["record_id", "root_chat_id", "target_chat_id", "turn_id"] {
        let id = required(value, field)?;
        if uuid::Uuid::parse_str(id)
            .map_err(|_| Error::Protocol)?
            .to_string()
            != id
        {
            return Err(Error::Protocol);
        }
    }
    let subject = required(value, "subject_id")?;
    if subject.len() > 255 || subject.chars().any(|c| c.is_control()) {
        return Err(Error::Protocol);
    }
    if !["message", "embed", "diff", "summary", "checkpoint"].contains(&text(value, "output_kind"))
        || value["output_version"]
            .as_u64()
            .is_none_or(|v| v == 0 || v > u32::MAX as u64)
        || value["chat_key_version"]
            .as_u64()
            .is_none_or(|v| v == 0 || v > u32::MAX as u64)
    {
        return Err(Error::Protocol);
    }
    Ok(())
}
fn output_aad(owner: &str, o: &Value) -> Result<Vec<u8>> {
    validate_output(o)?;
    let mut data = b"OMCR2".to_vec();
    for value in [
        owner,
        required(o, "root_chat_id")?,
        required(o, "target_chat_id")?,
        required(o, "turn_id")?,
        required(o, "record_id")?,
    ] {
        if uuid::Uuid::parse_str(value)
            .map_err(|_| Error::Crypto)?
            .to_string()
            != value
        {
            return Err(Error::Crypto);
        }
        append(&mut data, value.as_bytes())?;
    }
    append(&mut data, required(o, "subject_id")?.as_bytes())?;
    append(&mut data, required(o, "output_kind")?.as_bytes())?;
    data.extend((o["chat_key_version"].as_u64().ok_or(Error::Crypto)? as u32).to_be_bytes());
    data.extend((o["output_version"].as_u64().ok_or(Error::Crypto)? as u32).to_be_bytes());
    Ok(data)
}
fn append(data: &mut Vec<u8>, bytes: &[u8]) -> Result<()> {
    let length = u32::try_from(bytes.len()).map_err(|_| Error::Crypto)?;
    data.extend(length.to_be_bytes());
    data.extend(bytes);
    Ok(())
}

fn historical_source(data: &Value, kind: &str) -> Result<String> {
    match kind {
        "mail" => {
            for field in ["receiver", "subject", "content", "footer"] {
                if data
                    .get(field)
                    .is_some_and(|v| !v.is_null() && !v.is_string())
                {
                    return Err(Error::Protocol);
                }
            }
            let mut parts = Plain::new(Vec::<String>::new());
            for field in ["receiver", "subject"] {
                let value = text(data, field);
                if !value.is_empty() {
                    parts.push(format!(
                        "{}: {value}",
                        if field == "receiver" { "to" } else { "subject" }
                    ))
                }
            }
            parts.push("content:".into());
            if !text(data, "content").is_empty() {
                parts.push(text(data, "content").into())
            }
            if !text(data, "footer").is_empty() {
                parts.push("footer:".into());
                parts.push(text(data, "footer").into())
            }
            Ok(parts.join("\n"))
        }
        "document" if !text(data, "html").is_empty() => Ok(text(data, "html").into()),
        "document" | "notebook" => {
            let model = &data[if kind == "document" {
                "docx_model"
            } else {
                "notebook"
            }];
            if model.is_object() {
                serde_json::to_string_pretty(model).map_err(|_| Error::Protocol)
            } else if kind == "notebook" && data["content"].is_string() {
                Ok(text(data, "content").into())
            } else {
                Err(Error::Protocol)
            }
        }
        _ => {
            let field = match kind {
                "code" | "pcb_schematic" => "code",
                "sheet" => "table",
                "mermaid" => "diagram_code",
                "diagram_html" => "html_source",
                "deck" => "slides_markup",
                _ => return Err(Error::Protocol),
            };
            data[field]
                .as_str()
                .map(str::to_owned)
                .ok_or(Error::Protocol)
        }
    }
}
pub(super) fn capture(
    kind: &str,
    payload: &Value,
    outputs: &mut BTreeMap<String, Value>,
) -> Result<Option<bool>> {
    if kind == "recovery_outputs_discovery_complete" {
        return match text(payload, "status") {
            "completed" | "disabled" => Ok(Some(true)),
            _ => Err(Error::Protocol),
        };
    }
    if kind != "recovery_outputs_available" {
        return Ok(None);
    }
    let rows = payload["outputs"]
        .as_array()
        .filter(|rows| rows.len() <= 100)
        .ok_or(Error::Protocol)?;
    for row in rows {
        validate_output(row)?;
        let id = required(row, "record_id")?;
        if let Some(previous) = outputs.get(id) {
            if previous != row {
                return Err(Error::Crypto);
            }
        } else {
            if outputs.len() >= 10_000 {
                return Err(Error::Protocol);
            }
            outputs.insert(id.into(), row.clone());
        }
    }
    Ok(None)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn opens_shared_v2_output_with_purpose_identity() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../tests/crypto_fixtures/chat_recovery_output_v2.json"
        ))
        .unwrap();
        let mut output = fixture["identity"].clone();
        output["chat_key_version"] = output["key_version"].clone();
        let owner = required(&output, "owner_id").unwrap().to_owned();
        let key = key_from_bytes(
            &crypto::decode_url(required(&fixture, "recovery_private_key").unwrap(), 32).unwrap(),
        )
        .unwrap();
        let aad = output_aad(&owner, &output).unwrap();
        let plain =
            crypto::open_recovery_with_aad(&fixture["envelope"], &key, &aad, 2, 16 * 1024 * 1024)
                .unwrap();
        assert_eq!(&*plain, required(&fixture, "plaintext").unwrap().as_bytes());
        for field in [
            "target_chat_id",
            "subject_id",
            "output_kind",
            "output_version",
        ] {
            let mut changed = output.clone();
            changed[field] = match field {
                "target_chat_id" => json!("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                "subject_id" => json!("different"),
                "output_kind" => json!("summary"),
                _ => json!(2),
            };
            assert!(
                crypto::open_recovery_with_aad(
                    &fixture["envelope"],
                    &key,
                    &output_aad(&owner, &changed).unwrap(),
                    2,
                    16 * 1024 * 1024
                )
                .is_err()
            );
        }
    }
    #[test]
    fn immutable_discovery_and_bounds() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../tests/crypto_fixtures/chat_recovery_output_v2.json"
        ))
        .unwrap();
        let mut row = fixture["identity"].clone();
        row["chat_key_version"] = row["key_version"].clone();
        let mut outputs = BTreeMap::new();
        capture(
            "recovery_outputs_available",
            &json!({"outputs":[row.clone()]}),
            &mut outputs,
        )
        .unwrap();
        let mut changed = row.clone();
        changed["subject_id"] = json!("changed");
        assert!(
            capture(
                "recovery_outputs_available",
                &json!({"outputs":[changed]}),
                &mut outputs
            )
            .is_err()
        );
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "recovery/opaque_tests.rs"]
mod opaque_tests;
