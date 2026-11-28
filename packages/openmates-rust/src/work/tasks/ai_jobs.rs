//! Reuse the typed Task codecs for a server-staged, owner-authorized AI update.
//! This only prepares ciphertext; the caller owns the fenced WS transaction.
use super::*;
use crate::work::task_crypto::{
    decode_with_key, encrypt_create_fields, encrypt_patch_fields, task_key_wrapper,
};
impl Tasks<'_> {
    pub(crate) async fn encrypt_update_job(
        &mut self,
        claim: &Value,
        active_chat: &str,
        active_key: &[u8; 32],
    ) -> Result<(Value, Key, Option<Key>)> {
        let id = string(claim, "task_id")?;
        uuid(id)?;
        let expected = claim["expected_task_version"]
            .as_u64()
            .ok_or(Error::Protocol)?;
        let private = claim["private_patch"].as_object().ok_or(Error::Protocol)?;
        if private
            .keys()
            .any(|key| !["title", "description", "blocked_reason"].contains(&key.as_str()))
        {
            return Err(Error::Invalid(
                "Unsupported private Task job field; the job remains pending.",
            ));
        }
        let safe = claim["safe_metadata"].as_object().ok_or(Error::Protocol)?;
        let text = |field: &str| -> Result<Option<String>> {
            match private.get(field) {
                None | Some(Value::Null) => Ok(None),
                Some(Value::String(v)) => Ok(Some(v.clone())),
                _ => Err(Error::Protocol),
            }
        };
        let status = optional_string(&claim["safe_metadata"], "status")?;
        let assign = optional_string(&claim["safe_metadata"], "assignee_type")?;
        let target = match safe.get("primary_chat_id") {
            None => None,
            Some(Value::Null) => Some(None),
            Some(Value::String(id)) => Some(Some(uuid(id)?.to_owned())),
            _ => return Err(Error::Protocol),
        };
        let opaque = matches!(&self.backend, Backend::Cookie(client) if client.browser_session_status().is_some());
        let (master, wrapping) = if opaque && self.filters.team_id.is_none() {
            (None, None)
        } else {
            let (master, wrapping) = self.keys().await?;
            (Some(master), Some(wrapping))
        };
        if self.filters.team_id.is_some() && target.is_some() {
            return Err(Error::Invalid(
                "Team Task context moves cannot prove all required wrappers on this server.",
            ));
        }
        let (mut payload, task_key) = if claim["operation"] == "create" {
            // The current authoritative server explicitly refuses Team creates.
            if self.filters.team_id.is_some() {
                return Err(Error::Invalid(
                    "Creating Team Tasks through update jobs is unsupported.",
                ));
            }
            if expected != 0 {
                return Err(Error::Conflict);
            }
            let chat = target.clone().unwrap_or_else(|| Some(active_chat.into()));
            let projects = match safe.get("linked_project_ids") {
                None => Vec::new(),
                Some(value) => serde_json::from_value::<Vec<String>>(value.clone())?,
            };
            let plan = optional_string(&claim["safe_metadata"], "plan_id")?;
            let input = TaskCreate {
                task_id: Some(id.into()),
                title: text("title")?.unwrap_or_else(|| "Untitled task".into()),
                description: text("description")?.unwrap_or_default(),
                status,
                assign,
                primary_chat_id: chat.clone(),
                linked_project_ids: projects,
                plan_id: plan,
                ..Default::default()
            };
            let key = crypto::random_key();
            let wrapped = self.backend.wrap_with_master(key.as_ref()).await?;
            let mut payload =
                encrypt_create_fields(&input, &key, wrapped, wrapping.as_deref(), None)?;
            let mut wrappers = vec![
                json!({"key_type":"master","encrypted_task_key":payload["encrypted_task_key"],"created_at":now()}),
            ];
            if let Some(chat) = chat {
                let key_chat = self.job_chat_key(&chat, active_chat, active_key).await?;
                wrappers.push(json!({"key_type":"chat","hashed_chat_id":hash(&chat),"encrypted_task_key":crypto::server_fields::encrypt_bytes(key.as_ref(),&key_chat, &[])?,"created_at":now()}));
            }
            if !input.linked_project_ids.is_empty() || input.plan_id.is_some() {
                let Backend::Cookie(client) = &mut self.backend else {
                    return Err(Error::Forbidden);
                };
                let mut seen = std::collections::BTreeSet::new();
                for id in &input.linked_project_ids {
                    uuid(id)?;
                    if !seen.insert(id) {
                        return Err(Error::Protocol);
                    }
                    let project = client.projects().resolve(id).await?;
                    wrappers.push(json!({
                        "key_type": "project",
                        "hashed_project_id": hash(id),
                        "encrypted_task_key": crypto::server_fields::encrypt_bytes(key.as_ref(), &project.key, &[])?,
                        "created_at": now(),
                    }));
                }
                if let Some(id) = &input.plan_id {
                    uuid(id)?;
                    let response = self
                        .backend
                        .request(Method::GET, &format!("/v1/user-plans/{id}"), None, None)
                        .await?;
                    let plan = &response["plan"];
                    if plan["plan_id"] != id.as_str() {
                        return Err(Error::Forbidden);
                    }
                    let plan_key = self
                        .backend
                        .unwrap_with_master(crate::work::plans::personal_plan_key_wrapper(plan)?)
                        .await?;
                    wrappers.push(json!({
                        "key_type": "plan",
                        "hashed_plan_id": hash(id),
                        "encrypted_task_key": crypto::server_fields::encrypt_bytes(key.as_ref(), &plan_key, &[])?,
                        "created_at": now(),
                    }));
                }
            }
            payload["key_wrappers"] = json!(wrappers);
            (payload, key)
        } else {
            let task = if opaque {
                self.read_personal_job_task(id, false).await?
            } else {
                self.resolve(id).await?
            };
            readonly(&task)?;
            if claim["source_task_chat_id"]
                .as_str()
                .is_some_and(|source| task.public["primary_chat_id"] != source)
            {
                return Err(Error::Forbidden);
            }
            if task.raw["version"].as_u64() != Some(expected) {
                return Err(Error::Conflict);
            }
            let patch = TaskPatch {
                title: text("title")?,
                description: text("description")?,
                status,
                assign,
                primary_chat_id: target.clone(),
                ..Default::default()
            };
            let mut payload =
                encrypt_patch_fields(&task, &patch, master.as_deref(), wrapping.as_deref())?;
            if let Some(reason) = text("blocked_reason")? {
                payload["encrypted_blocked_reason"] = json!(crypto::server_fields::encrypt_text(
                    &reason,
                    &task.key,
                    &[]
                )?);
            }
            if let Some(target) = target {
                let wrappers = self
                    .job_wrappers(
                        &task,
                        target.as_deref(),
                        active_chat,
                        active_key,
                        wrapping.as_deref(),
                    )
                    .await?;
                payload["key_wrappers"] = json!(wrappers);
            }
            (payload, task.key.clone())
        };
        // Explicit staged lifecycle metadata is distinct from private text.
        for field in [
            "position",
            "created_at",
            "updated_at",
            "queue_state",
            "ai_execution_state",
            "blocked_reason_code",
            "due_at",
            "priority",
        ] {
            if let Some(value) = safe.get(field) {
                if value.is_null() {
                    if matches!(
                        field,
                        "blocked_reason_code" | "ai_execution_state" | "due_at"
                    ) {
                        payload[field] = Value::Null;
                    }
                    continue;
                }
                if matches!(
                    field,
                    "position" | "created_at" | "updated_at" | "due_at" | "priority"
                ) && !value.is_i64()
                    && !value.is_u64()
                {
                    return Err(Error::Protocol);
                }
                if matches!(
                    field,
                    "queue_state" | "ai_execution_state" | "blocked_reason_code"
                ) && !value.is_string()
                {
                    return Err(Error::Protocol);
                }
                payload[field] = value.clone();
            }
        }
        if payload["priority"].as_u64().is_some_and(|v| v > 4) {
            return Err(Error::Protocol);
        }
        Ok((payload, task_key, wrapping))
    }
    /// Read and authenticate the canonical Personal Task with an opaque master.
    async fn read_personal_job_task(
        &mut self,
        id: &str,
        include_wrappers: bool,
    ) -> Result<Resolved> {
        if self.filters.team_id.is_some() {
            return Err(Error::Forbidden);
        }
        let Backend::Cookie(client) = &mut self.backend else {
            return Err(Error::Forbidden);
        };
        let mut row = client.request_committed_task(id, false).await?["task"].clone();
        if row["source"] == "workflow_run"
            || row["task_id"] != id
            || row["hashed_user_id"]
                != hash(
                    client
                        .browser_session_status()
                        .ok_or(Error::Authentication)?
                        .principal(),
                )
        {
            return Err(Error::Forbidden);
        }
        if include_wrappers || !row["encrypted_task_key"].is_string() {
            row["key_wrappers"] =
                client.request_committed_task(id, true).await?["key_wrappers"].clone();
        }
        let key = client
            .work_unwrap_with_master(task_key_wrapper(&row, None)?)
            .await?;
        decode_with_key(row, key)
    }

    /// Prove the saved ciphertext and key wrapper using the browser's master binding.
    pub(crate) async fn verify_personal_job_write(
        &mut self,
        id: &str,
        key: &[u8; 32],
        expected: &Value,
        version: u64,
    ) -> Result<()> {
        let task = self.read_personal_job_task(id, true).await?;
        crate::work::verify_task_job_fields(&task, key, expected, version)
    }

    /// Return the authenticated Personal Task state needed to recover a receipt.
    pub(crate) async fn read_personal_job_result(&mut self, id: &str) -> Result<Value> {
        Ok(self.read_personal_job_task(id, false).await?.public)
    }

    async fn job_chat_key(&mut self, id: &str, active: &str, key: &[u8; 32]) -> Result<Key> {
        uuid(id)?;
        if id == active {
            return Ok(zeroize::Zeroizing::new(*key));
        }
        match &mut self.backend {
            Backend::Cookie(client) => {
                if client.work_team()?.as_deref() != self.filters.team_id.as_deref() {
                    return Err(Error::Forbidden);
                }
                client.work_chat_key(id).await
            }
            Backend::ApiKey(_) => Err(Error::Forbidden),
        }
    }
    async fn job_wrappers(
        &mut self,
        task: &Resolved,
        target: Option<&str>,
        active: &str,
        active_key: &[u8; 32],
        wrapping: Option<&[u8; 32]>,
    ) -> Result<Vec<Value>> {
        let id = string(&task.raw, "task_id")?;
        let p = self.scoped(&format!("/v1/user-tasks/{id}/key-wrappers"), &[]);
        let result = self.backend.request(Method::GET, &p, None, None).await?;
        let rows = result["key_wrappers"].as_array().ok_or(Error::Protocol)?;
        let mut wrappers = vec![];
        let team = self.filters.team_id.clone();
        if let Some(team) = &team {
            let candidates = rows
                .iter()
                .filter(|r| {
                    r["key_type"] == "team"
                        && r["hashed_team_id"] == hash(team)
                        && crate::work::team_epoch_ok(r)
                })
                .collect::<Vec<_>>();
            if candidates.len() != 1 {
                return Err(Error::Forbidden);
            }
            let verified = crypto::decrypt_bytes(
                string(candidates[0], "encrypted_task_key")?,
                wrapping.ok_or(Error::Crypto)?,
            )?;
            if verified.as_slice() != task.key.as_ref() {
                return Err(Error::Crypto);
            }
            wrappers.push(json!({"key_type":"team","hashed_team_id":hash(team),"team_key_epoch":candidates[0]["team_key_epoch"].as_u64().unwrap_or(1),"encrypted_task_key":string(candidates[0],"encrypted_task_key")?,"created_at":now()}));
        } else {
            wrappers.push(json!({"key_type":"master","encrypted_task_key":self.backend.wrap_with_master(task.key.as_ref()).await?,"created_at":now()}));
        }
        if let Some(chat) = target {
            let chat_key = self.job_chat_key(chat, active, active_key).await?;
            wrappers.push(json!({"key_type":"chat","hashed_chat_id":hash(chat),"encrypted_task_key":crypto::server_fields::encrypt_bytes(task.key.as_ref(),&chat_key, &[])?,"created_at":now()}));
        }
        let projects = task.public["linked_project_ids"]
            .as_array()
            .ok_or(Error::Protocol)?;
        let mut required = projects
            .iter()
            .map(|id| id.as_str().map(hash).ok_or(Error::Protocol))
            .collect::<Result<std::collections::BTreeSet<_>>>()?;
        let plan = task.public["plan_id"].as_str().map(hash);
        let mut plan_seen = false;
        for row in rows {
            let kind = string(row, "key_type")?;
            let retain = if kind == "project" {
                required.remove(string(row, "hashed_project_id")?)
            } else if kind == "plan" && plan.as_deref() == row["hashed_plan_id"].as_str() {
                if plan_seen {
                    return Err(Error::Forbidden);
                }
                plan_seen = true;
                true
            } else {
                false
            };
            if !retain {
                continue;
            }
            if row["expires_at"]
                .as_u64()
                .is_some_and(|expires| expires <= now())
            {
                return Err(Error::Forbidden);
            }
            if row["hashed_task_id"]
                .as_str()
                .is_some_and(|actual| actual != hash(id))
            {
                return Err(Error::Forbidden);
            }
            string(row, "encrypted_task_key")?;
            let mut retained = json!({});
            for field in [
                "key_type",
                "hashed_project_id",
                "hashed_plan_id",
                "encrypted_task_key",
                "created_at",
                "expires_at",
            ] {
                if let Some(value) = row.get(field) {
                    retained[field] = value.clone();
                }
            }
            wrappers.push(retained);
        }
        if !required.is_empty() || plan.is_some() && !plan_seen {
            return Err(Error::Forbidden);
        }
        Ok(wrappers)
    }
}
fn optional_string(value: &Value, field: &str) -> Result<Option<String>> {
    match value.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(v)) => Ok(Some(v.clone())),
        _ => Err(Error::Protocol),
    }
}

#[cfg(test)]
mod tests {
    use super::super::tests::{client, mock};
    use super::*;
    const TASK: &str = "11111111-1111-4111-8111-111111111111";
    const CHAT: &str = "22222222-2222-4222-8222-222222222222";
    const OLD: &str = "33333333-3333-4333-8333-333333333333";
    const PROJECT: &str = "44444444-4444-4444-8444-444444444444";
    const PLAN: &str = "55555555-5555-4555-8555-555555555555";
    fn row() -> Value {
        json!({"task_id":TASK,"version":3,"encrypted_task_key":crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap(),"encrypted_title":crypto::encrypt_combined("Old private title",&[9;32]).unwrap(),"encrypted_description":crypto::encrypt_combined("Old private description",&[9;32]).unwrap(),"encrypted_linked_project_ids":crypto::encrypt_combined("[]",&[9;32]).unwrap(),"primary_chat_id":OLD,"priority":0,"status":"todo"})
    }
    fn claim() -> Value {
        json!({"task_id":TASK,"operation":"update","expected_task_version":3,"private_patch":{"title":"New private title"},"safe_metadata":{"status":"todo","updated_at":42}})
    }
    // contract-test: supporting surface=cli assertions=tasks.content.client-encrypted,tasks.lifecycle.visible
    #[tokio::test]
    async fn update_reuses_authenticated_task_key_and_rejects_stale_versions() {
        for version in [3, 4] {
            let mut raw = row();
            raw["version"] = json!(version);
            let (api, server) = mock(vec![json!({"task":raw})]).await;
            let result = client(&api)
                .tasks()
                .encrypt_update_job(&claim(), CHAT, &[8; 32])
                .await;
            if version == 3 {
                let (payload, key, _) = result.unwrap();
                assert_eq!(*key, [9; 32]);
                assert_eq!(payload["version"], 3);
                assert_eq!(
                    crypto::decrypt_combined(payload["encrypted_title"].as_str().unwrap(), &key)
                        .unwrap(),
                    "New private title"
                );
                assert!(!payload.to_string().contains("private"));
            } else {
                assert!(matches!(result, Err(Error::Conflict)));
            }
            assert!(
                server
                    .await
                    .unwrap()
                    .iter()
                    .all(|request| request.starts_with("GET "))
            );
        }
    }
    #[tokio::test]
    async fn move_preserves_project_and_plan_wrappers_and_replaces_only_chat_scope() {
        let mut raw = row();
        raw["encrypted_linked_project_ids"] = json!(
            crypto::encrypt_combined(&serde_json::to_string(&vec![PROJECT]).unwrap(), &[9; 32])
                .unwrap()
        );
        raw["plan_id"] = json!(PLAN);
        let project = json!({"key_type":"project","hashed_project_id":hash(PROJECT),"encrypted_task_key":crypto::encrypt_bytes(&[9;32],&[10;32]).unwrap(),"created_at":1,"expires_at":null});
        let plan = json!({"key_type":"plan","hashed_plan_id":hash(PLAN),"encrypted_task_key":crypto::encrypt_bytes(&[9;32],&[11;32]).unwrap(),"created_at":1,"expires_at":null});
        let wrappers = json!([{"key_type":"master","encrypted_task_key":raw["encrypted_task_key"]},{"key_type":"chat","hashed_chat_id":hash(OLD),"encrypted_task_key":crypto::encrypt_bytes(&[9;32],&[12;32]).unwrap()},project,plan]);
        let (api, server) = mock(vec![json!({"task":raw}), json!({"key_wrappers":wrappers})]).await;
        let mut claim = claim();
        claim["operation"] = json!("move");
        claim["source_task_chat_id"] = json!(OLD);
        claim["safe_metadata"]["primary_chat_id"] = json!(CHAT);
        let (payload, key, _) = client(&api)
            .tasks()
            .encrypt_update_job(&claim, CHAT, &[8; 32])
            .await
            .unwrap();
        let wrappers = payload["key_wrappers"].as_array().unwrap();
        assert_eq!(wrappers.len(), 4);
        assert!(wrappers.contains(&project) && wrappers.contains(&plan));
        let chat = wrappers
            .iter()
            .find(|row| row["key_type"] == "chat")
            .unwrap();
        assert_eq!(chat["hashed_chat_id"], hash(CHAT));
        assert_eq!(
            &*crypto::decrypt_bytes(chat["encrypted_task_key"].as_str().unwrap(), &[8; 32])
                .unwrap(),
            key.as_ref()
        );
        assert!(
            server
                .await
                .unwrap()
                .iter()
                .all(|request| request.starts_with("GET "))
        );
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
mod field_interop_tests {
    use super::*;
    use crate::work::task_crypto::field_interop_support::{assert_web, case};
    use crate::work::tasks::tests::{client, mock};
    #[tokio::test]
    async fn actual_job_create_and_move_wrappers_read_in_web_legacy_decoders() {
        const TASK: &str = "11111111-1111-4111-8111-111111111111";
        const CHAT: &str = "22222222-2222-4222-8222-222222222222";
        let mut fresh_client = client("http://127.0.0.1:1");
        let create = json!({"task_id":TASK,"operation":"create","expected_task_version":0,"private_patch":{"title":"Job title"},"safe_metadata":{"primary_chat_id":CHAT}});
        let (created, key, _) = fresh_client
            .tasks()
            .encrypt_update_job(&create, CHAT, &[8; 32])
            .await
            .unwrap();
        let row = json!({"task_id":TASK,"version":3,"encrypted_task_key":crypto::encrypt_bytes(&key[..],&[7;32]).unwrap(),"encrypted_title":crypto::encrypt_combined("Old title",&key).unwrap(),"encrypted_description":crypto::encrypt_combined("",&key).unwrap(),"encrypted_linked_project_ids":crypto::encrypt_combined("[]",&key).unwrap(),"primary_chat_id":CHAT,"priority":0,"status":"todo"});
        let wrappers =
            json!([{"key_type":"master","encrypted_task_key":row["encrypted_task_key"]}]);
        let (api, server) = mock(vec![json!({"task":row}), json!({"key_wrappers":wrappers})]).await;
        let claim = json!({"task_id":TASK,"operation":"move","expected_task_version":3,"private_patch":{"blocked_reason":"Private blocker"},"safe_metadata":{"primary_chat_id":CHAT}});
        let (moved, moved_key, _) = client(&api)
            .tasks()
            .encrypt_update_job(&claim, CHAT, &[8; 32])
            .await
            .unwrap();
        assert_eq!(*key, *moved_key);
        let mut cases = vec![case(
            "job.blocked_reason",
            "object-text",
            moved["encrypted_blocked_reason"].as_str().unwrap(),
            &key,
            b"Private blocker",
            "",
        )];
        for (label, payload) in [("create", created), ("move", moved)] {
            for wrapper in payload["key_wrappers"].as_array().unwrap() {
                let (kind, wrapping) = if wrapper["key_type"] == "master" {
                    ("master-binary", [7; 32])
                } else {
                    ("object-binary", [8; 32])
                };
                cases.push(case(
                    label,
                    kind,
                    wrapper["encrypted_task_key"].as_str().unwrap(),
                    &wrapping,
                    &key[..],
                    "",
                ));
            }
        }
        assert_web(cases);
        assert!(server.await.unwrap().iter().all(|r| r.starts_with("GET ")));
    }
}
