//! Owner-scoped Task update-job leases and separate durable event confirmation.
//! This module remains unexported until its synthetic protocol checks pass.
use super::task_job_payload::{TaskJobClaim, event_message, persist_payload};
use super::transport::Socket;
#[cfg(target_arch = "wasm32")]
use task_job_io::BrowserExchange;
use task_job_io::TaskJobTransport;

#[path = "task_job_io.rs"]
mod task_job_io;
use super::*;
pub(super) fn capture(
    kind: &str,
    payload: &Value,
    jobs: &mut BTreeMap<String, Value>,
) -> Result<()> {
    if kind != "task_update_jobs_available" {
        return Ok(());
    }
    let rows = payload["jobs"].as_array().ok_or(Error::Protocol)?;
    if rows.len() > 256 {
        return Err(Error::Protocol);
    }
    for row in rows {
        let id = required(row, "job_id")?;
        if id.len() > 128 {
            return Err(Error::Protocol);
        }
        for field in ["task_id", "chat_id"] {
            uuid::Uuid::parse_str(required(row, field)?).map_err(|_| Error::Protocol)?;
        }
        for field in ["revision", "task_key_version", "expires_at"] {
            row[field].as_u64().ok_or(Error::Protocol)?;
        }
        jobs.insert(id.into(), row.clone());
        if jobs.len() > 256
            || jobs.values().map(|v| v.to_string().len()).sum::<usize>() > 16 * 1024 * 1024
        {
            return Err(Error::Protocol);
        }
    }
    Ok(())
}
impl Client {
    pub(super) async fn persist_task_jobs(
        &mut self,
        socket: &mut Socket,
        jobs: &BTreeMap<String, Value>,
        events: &[Value],
        active: Option<(&str, &[u8; 32], &str)>,
        cancel: &CancellationToken,
    ) -> Result<std::collections::BTreeSet<String>> {
        self.persist_task_jobs_with(socket, jobs, events, active, cancel)
            .await
    }

    /// Persist offered jobs from the browser's authenticated socket using its
    /// borrowed Worker session and existing page transport. No keys leave Rust.
    #[cfg(target_arch = "wasm32")]
    pub async fn run_browser_task_jobs<F, Fut>(&mut self, offer: &Value, exchange: F) -> Result<Vec<String>>
    where
        F: FnMut(Value) -> Fut,
        Fut: std::future::Future<Output = Result<Value>>,
    {
        if self.browser_credentials.is_none() || self.team()?.is_some() {
            return Err(Error::Forbidden);
        }
        self.require_work_authority()?;
        let mut jobs = BTreeMap::new();
        capture("task_update_jobs_available", offer, &mut jobs)?;
        if let Some(chat) = offer.get("chat_id") {
            let message = required(offer, "message_id")?;
            for job in jobs.values_mut() {
                if &job["chat_id"] != chat {
                    return Err(Error::Forbidden);
                }
                job["message_id"] = json!(message);
            }
        }
        let cancel = self.operation_cancel.clone();
        let handled = self
            .persist_task_jobs_with(&mut BrowserExchange(exchange), &jobs, &[], None, &cancel)
            .await?;
        handled
            .iter()
            .map(|id| required(&jobs[id], "task_id").map(str::to_owned))
            .collect()
    }

    async fn persist_task_jobs_with(
        &mut self,
        transport: &mut impl TaskJobTransport,
        jobs: &BTreeMap<String, Value>,
        events: &[Value],
        active: Option<(&str, &[u8; 32], &str)>,
        cancel: &CancellationToken,
    ) -> Result<std::collections::BTreeSet<String>> {
        if jobs.len() > 256 || events.len() > 1024 {
            return Err(Error::Protocol);
        }
        let mut handled = std::collections::BTreeSet::new();
        if jobs.is_empty() {
            return Ok(handled);
        }
        let generation = self.generation;
        let owner = required(&self.user, "id")?.to_owned();
        let team = self.team()?.map(str::to_owned);
        let deadline = crate::platform::time::Instant::now() + Duration::from_secs(120);
        for (job_id, job) in jobs {
            if crate::platform::time::Instant::now() >= deadline {
                return Err(Error::Offline);
            }
            let event = events
                .iter()
                .find(|event| event["task_update_job_id"] == *job_id);
            // Inline Task jobs omit the system event. In an active send, only
            // a job captured from that chat and user turn can proceed without it.
            if let Some((chat, _, user_message)) = active
                && event.is_none()
                && (job["chat_id"] != chat || job["message_id"] != user_message)
            {
                continue;
            }
            if job["expires_at"]
                .as_u64()
                .is_none_or(|expires| expires <= now_ms() / 1000)
            {
                continue;
            }
            self.task_job_owner(&owner, generation, team.as_deref())?;
            if self.operation_cancel.is_cancelled() || cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            let preflight_key = if active.is_none() {
                let source = required(job, "chat_id")?;
                let fresh = async {
                    if self.browser_credentials.is_some() {
                        return self.edit_chat_key(source).await;
                    }
                    self.open_chat_live(source).await?;
                    let wrapping = self.wrapping_key().await?;
                    self.chat_key(self.chats.get(source).ok_or(Error::Protocol)?, &wrapping)
                }
                .await;
                match fresh {
                    Ok(key) => Some(key),
                    Err(Error::Forbidden | Error::Invalid(_)) => continue,
                    Err(error) => return Err(error),
                }
            } else {
                None
            };
            self.task_job_owner(&owner, generation, team.as_deref())?;
            let expected_chat = active.map(|(chat, _, _)| chat);
            let expected_user = active.map(|(_, _, user)| user);
            if let Some(event) = event
                && (event["task_id"] != job["task_id"]
                    || expected_chat.is_some_and(|chat| event["chat_id"] != chat)
                    || expected_user.is_some_and(|user| event["message_id"] != user))
            {
                return Err(Error::Forbidden);
            }
            let request = uuid::Uuid::new_v4().to_string();
            let raw = match transport
                .job(
                    "task_update_job_claim",
                    json!({"protocol_version":1,"job_id":job_id,"request_id":request}),
                    "task_update_job_claimed",
                    &request,
                    job_id,
                )
                .await
            {
                Ok(value) => value,
                Err(Error::Conflict) => continue,
                Err(error) => return Err(error),
            };
            self.task_job_owner(&owner, generation, team.as_deref())?;
            let claim = TaskJobClaim::parse(
                &raw,
                job,
                team.as_deref(),
                expected_chat,
                expected_user,
                now_ms() / 1000,
            )?;
            if let Some(event) = event
                && (event["task_id"] != claim.task_id
                    || event["chat_id"] != claim.chat_id
                    || event
                        .get("message_id")
                        .is_some_and(|id| id != &claim.message_id))
            {
                return Err(Error::Forbidden);
            }
            if self.operation_cancel.is_cancelled() || cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            if claim.task_key_version != 1 {
                return Err(Error::Protocol);
            }
            if let Some(source) = &claim.source_task_chat_id {
                uuid::Uuid::parse_str(source).map_err(|_| Error::Protocol)?;
            }
            let key = if let Some((chat, key, _)) =
                active.filter(|(chat, _, _)| *chat == claim.chat_id)
            {
                let _ = chat;
                zeroize::Zeroizing::new(*key)
            } else if let Some(key) = preflight_key {
                key
            } else {
                self.work_chat_key(&claim.chat_id).await?
            };
            self.task_job_owner(&owner, generation, team.as_deref())?;
            let fallback = json!({"event_id":format!("task-event-{}",claim.job_id),"chat_id":claim.chat_id,"task_id":claim.task_id,"event_type":match claim.operation.as_str(){"create"=>"created","move"=>"moved","update"=>"updated","complete"=>"completed","block"=>"blocked","unblock"=>"unblocked",_=>return Err(Error::Protocol)},"title":claim.private_patch["title"],"status":claim.safe_metadata["status"],"created_at":claim.safe_metadata["updated_at"].as_u64().unwrap_or(now_ms()/1000),"task_update_job_id":claim.job_id});
            let event = event.unwrap_or(&fallback);
            let system = if let Some(system) = self.existing_task_event(&claim)? {
                Some(system)
            } else {
                event_message(job_id, &claim.message_id, event, &key, now_ms() / 1000)?
            };
            let system_cipher = system
                .as_ref()
                .map(|system| required(system, "encrypted_content"))
                .transpose()?;
            if claim.state == "LEASED" {
                let (encrypted, task_key, wrapping) = self
                    .tasks()
                    .encrypt_update_job(&raw, &claim.chat_id, &key)
                    .await?;
                self.task_job_owner(&owner, generation, team.as_deref())?;
                if self.operation_cancel.is_cancelled() || cancel.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                if claim.lease_expires_at <= now_ms() / 1000 {
                    return Err(Error::Conflict);
                }
                let request = uuid::Uuid::new_v4().to_string();
                let mut payload = persist_payload(&claim, encrypted, system_cipher)?;
                let expected = payload["encrypted_task_payload"].clone();
                payload["request_id"] = json!(request);
                // After dispatch, finish the canonical receipt even if cancelled.
                let receipt = transport
                    .job(
                        "task_update_job_persist",
                        payload,
                        "task_update_job_persisted",
                        &request,
                        job_id,
                    )
                    .await?;
                if receipt["task_id"] != claim.task_id
                    || !matches!(
                        receipt["state"].as_str(),
                        Some("TASK_PERSISTED" | "TERMINAL")
                    )
                {
                    return Err(Error::Protocol);
                }
                let version = if claim.operation == "create" {
                    1
                } else {
                    claim
                        .expected_task_version
                        .checked_add(1)
                        .ok_or(Error::Protocol)?
                };
                if let Some(wrapping) = wrapping {
                    let mut canonical =
                        self.request_committed_task(&claim.task_id, false).await?["task"].clone();
                    if canonical["task_id"] != claim.task_id {
                        return Err(Error::Forbidden);
                    }
                    let wrappers = self.request_committed_task(&claim.task_id, true).await?;
                    canonical["key_wrappers"] = wrappers["key_wrappers"].clone();
                    crate::work::verify_task_job_persistence(
                        canonical,
                        &wrapping,
                        team.as_deref(),
                        &task_key,
                        &expected,
                        version,
                        &owner,
                    )?;
                } else {
                    self.tasks()
                        .verify_personal_job_write(&claim.task_id, &task_key, &expected, version)
                        .await?;
                }
            } else {
                // A replay still proves canonical Task ownership/Team wrappers.
                let current = if self.browser_credentials.is_some() {
                    self.tasks()
                        .read_personal_job_result(&claim.task_id)
                        .await?
                } else {
                    self.tasks().show(&claim.task_id).await?
                };
                verify_persisted_claim(&claim, &current)?;
            }
            self.task_job_owner(&owner, generation, team.as_deref())?;
            if let Some(system) = &system {
                let mut payload = json!({"chat_id":claim.chat_id,"message":system});
                if let Some(team) = &team {
                    payload["team_id"] = json!(team)
                }
                let confirmed = transport
                    .system_message(payload, required(system, "message_id")?)
                    .await?;
                if confirmed["chat_id"]
                    .as_str()
                    .is_some_and(|id| id != claim.chat_id)
                {
                    return Err(Error::Forbidden);
                }
                self.task_job_owner(&owner, generation, team.as_deref())?;
                let request = uuid::Uuid::new_v4().to_string();
                let receipt = transport.job(
                    "task_update_job_event_confirmed",
                    json!({"protocol_version":1,"job_id":job_id,"request_id":request,"event_system_message_id":system["message_id"]}),
                    "task_update_job_event_confirmed",
                    &request,
                    job_id,
                ).await?;
                if receipt["state"] != "TERMINAL" || receipt["task_id"] != claim.task_id {
                    return Err(Error::Protocol);
                }
            }
            self.task_job_owner(&owner, generation, team.as_deref())?;
            handled.insert(job_id.clone());
        }
        Ok(handled)
    }
    fn task_job_owner(&self, owner: &str, generation: u64, team: Option<&str>) -> Result<()> {
        if self.generation != generation
            || self.team()? != team
            || required(&self.user, "id")? != owner
        {
            return Err(Error::Cancelled);
        }
        self.require_work_authority()?;
        Ok(())
    }
    fn existing_task_event(&self, claim: &TaskJobClaim) -> Result<Option<Value>> {
        let mut existing = None;
        for row in self
            .history
            .get(&claim.chat_id)
            .into_iter()
            .flatten()
            .filter(|row| row["role"] == "system" && row["task_update_job_id"] == claim.job_id)
        {
            if row["user_message_id"] != claim.message_id {
                return Err(Error::Forbidden);
            }
            let id = row
                .get("client_message_id")
                .or_else(|| row.get("message_id"))
                .or_else(|| row.get("id"))
                .and_then(Value::as_str)
                .filter(|id| !id.is_empty())
                .ok_or(Error::Protocol)?;
            if existing
                .as_ref()
                .is_some_and(|previous: &Value| previous["message_id"] != id)
            {
                return Err(Error::Protocol);
            }
            existing = Some(
                json!({"message_id":id,"role":"system","encrypted_content":required(row,"encrypted_content")?,"created_at":row["created_at"].as_u64().ok_or(Error::Protocol)?,"user_message_id":claim.message_id,"task_update_job_id":claim.job_id}),
            );
        }
        Ok(existing)
    }
}
fn verify_persisted_claim(claim: &TaskJobClaim, current: &Value) -> Result<()> {
    let version = if claim.operation == "create" {
        1
    } else {
        claim
            .expected_task_version
            .checked_add(1)
            .ok_or(Error::Protocol)?
    };
    if current["task_id"] != claim.task_id || current["version"].as_u64() != Some(version) {
        return Err(Error::Conflict);
    }
    for (field, value) in claim.private_patch.as_object().ok_or(Error::Protocol)? {
        if current[field] != *value {
            return Err(Error::Conflict);
        }
    }
    for field in [
        "status",
        "assignee_type",
        "primary_chat_id",
        "position",
        "queue_state",
        "ai_execution_state",
        "blocked_reason_code",
        "priority",
        "due_at",
        "created_at",
        "updated_at",
    ] {
        if let Some(expected) = claim.safe_metadata.get(field)
            && current[field] != *expected
        {
            return Err(Error::Conflict);
        }
    }
    Ok(())
}
#[cfg(test)]
mod tests;
