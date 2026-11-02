//! Owner-device delivery uses a fresh server claim and normal user ciphertext.
use super::transport::{Socket, send, wait_workflow};
use super::*;
#[derive(Clone)]
pub(super) struct WorkflowDelivery {
    id: String,
    chat: String,
    message: String,
    status: String,
    claim_expires: u64,
    workflow: Option<String>,
    run: Option<String>,
}
impl WorkflowDelivery {
    pub(super) fn belongs_to_chat(&self, chat: &str) -> bool { self.chat == chat }
    fn parse(row: &Value) -> Result<Self> {
        let id = required(row, "delivery_id")?.to_owned();
        let chat = required(row, "chat_id")?.to_owned();
        let message = required(row, "message_id")?.to_owned();
        for value in [&id, &chat, &message] {
            uuid::Uuid::parse_str(value).map_err(|_| Error::Protocol)?;
        }
        let status = required(row, "status")?.to_owned();
        if ![
            "delivery_pending",
            "claimed",
            "acknowledged",
            "cancelled",
            "expired",
            "failed",
        ]
        .contains(&status.as_str())
        {
            return Err(Error::Protocol);
        }
        let optional = |key: &str| -> Result<Option<String>> {
            match row.get(key) {
                None | Some(Value::Null) => Ok(None),
                Some(Value::String(v)) => {
                    uuid::Uuid::parse_str(v).map_err(|_| Error::Protocol)?;
                    Ok(Some(v.clone()))
                }
                _ => Err(Error::Protocol),
            }
        };
        Ok(Self {
            id,
            chat,
            message,
            status,
            claim_expires: row["claim_expires_at"].as_u64().unwrap_or(0),
            workflow: optional("workflow_id")?,
            run: optional("run_id")?,
        })
    }
}
pub(super) fn capture(
    kind: &str,
    payload: &Value,
    deliveries: &mut BTreeMap<String, WorkflowDelivery>,
) -> Result<()> {
    if kind != "workflow_chat_deliveries_available" {
        return Ok(());
    }
    let rows = payload["deliveries"].as_array().ok_or(Error::Protocol)?;
    if rows.len() > 256 {
        return Err(Error::Protocol);
    }
    for row in rows {
        let mut delivery = WorkflowDelivery::parse(row)?;
        if let Some(previous) = deliveries.get(&delivery.id)
            && (previous.chat != delivery.chat
                || previous.message != delivery.message
                || previous
                    .workflow
                    .as_ref()
                    .zip(delivery.workflow.as_ref())
                    .is_some_and(|(a, b)| a != b)
                || previous
                    .run
                    .as_ref()
                    .zip(delivery.run.as_ref())
                    .is_some_and(|(a, b)| a != b))
        {
            return Err(Error::Forbidden);
        }
        if let Some(previous) = deliveries.get(&delivery.id) {
            if delivery.workflow.is_none() {
                delivery.workflow = previous.workflow.clone();
            }
            if delivery.run.is_none() {
                delivery.run = previous.run.clone();
            }
        }
        deliveries.insert(delivery.id.clone(), delivery);
        if deliveries.len() > 256 {
            return Err(Error::Protocol);
        }
    }
    Ok(())
}
impl Client {
    pub(super) async fn persist_workflow_deliveries(
        &mut self,
        ws: &mut Socket,
        deliveries: &BTreeMap<String, WorkflowDelivery>,
    ) -> Result<usize> {
        let cancel = self.operation_cancel.clone();
        self.persist_workflow_deliveries_until(
            ws,
            deliveries,
            crate::platform::time::Instant::now() + Duration::from_secs(120),
            &cancel,
        )
        .await
    }
    async fn persist_workflow_deliveries_until(
        &mut self,
        ws: &mut Socket,
        deliveries: &BTreeMap<String, WorkflowDelivery>,
        deadline: crate::platform::time::Instant,
        cancel: &CancellationToken,
    ) -> Result<usize> {
        if deliveries.is_empty() {
            return Ok(0);
        }
        if self.team()?.is_some() {
            return Ok(0);
        }
        let generation = self.generation;
        let owner = required(&self.user, "id")?.to_owned();
        let master = self.require_session()?.master_key.clone();
        let mut count = 0;
        for delivery in deliveries.values() {
            if !["delivery_pending", "claimed"].contains(&delivery.status.as_str())
                || delivery.status == "claimed" && delivery.claim_expires > now_ms() / 1000
            {
                continue;
            }
            if self.operation_cancel.is_cancelled() || cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            if crate::platform::time::Instant::now() >= deadline {
                return Err(Error::Offline);
            }
            self.workflow_owner(&owner, generation)?;
            let request = uuid::Uuid::new_v4().to_string();
            send(
                ws,
                "workflow_chat_delivery_claim",
                json!({"delivery_id":delivery.id,"request_id":request}),
            )
            .await?;
            let claim = match crate::platform::time::timeout_at(
                deadline.min(crate::platform::time::Instant::now() + Duration::from_secs(20)),
                wait_workflow(ws, "workflow_chat_delivery_claimed", &request, &delivery.id),
            )
            .await
            .map_err(|_| Error::Offline)?
            {
                Ok(claim) => claim,
                Err(Error::Conflict) => continue,
                Err(error) => return Err(error),
            };
            self.workflow_owner(&owner, generation)?;
            validate_claim(delivery, &claim, now_ms() / 1000)?;
            if self.operation_cancel.is_cancelled() || cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            let mut fence = json!({"delivery_id":delivery.id,"claim_token":required(&claim,"claim_token")?,"claim_generation":claim["claim_generation"],"claim_issued_at":claim["claim_issued_at"],"claim_expires_at":claim["claim_expires_at"]});
            if claim["client_persisted"] != true {
                let (metadata, message) = encrypt_claim(&claim, &master)?;
                let request = uuid::Uuid::new_v4().to_string();
                let mut payload = fence.clone();
                payload["encrypted_chat_metadata"] = json!(serde_json::to_string(&metadata)?);
                payload["encrypted_message"] = json!(serde_json::to_string(&message)?);
                payload["request_id"] = json!(request);
                send(ws, "workflow_chat_delivery_persist", payload).await?;
                let persisted = crate::platform::time::timeout_at(
                    deadline.min(crate::platform::time::Instant::now() + Duration::from_secs(20)),
                    wait_workflow(
                        ws,
                        "workflow_chat_delivery_persisted",
                        &request,
                        &delivery.id,
                    ),
                )
                .await
                .map_err(|_| Error::Offline)??;
                self.workflow_owner(&owner, generation)?;
                validate_receipt(delivery, &persisted)?;
                if persisted["claim_generation"] != claim["claim_generation"] {
                    return Err(Error::Conflict);
                };
                if persisted["client_persisted"] != true {
                    return Err(Error::Protocol);
                }
            }
            let request = uuid::Uuid::new_v4().to_string();
            fence["request_id"] = json!(request);
            send(ws, "workflow_chat_delivery_ack", fence).await?;
            let ack = crate::platform::time::timeout_at(
                deadline.min(crate::platform::time::Instant::now() + Duration::from_secs(20)),
                wait_workflow(
                    ws,
                    "workflow_chat_delivery_acknowledged",
                    &request,
                    &delivery.id,
                ),
            )
            .await
            .map_err(|_| Error::Offline)??;
            self.workflow_owner(&owner, generation)?;
            validate_receipt(delivery, &ack)?;
            if ack["claim_generation"] != claim["claim_generation"] {
                return Err(Error::Conflict);
            };
            if ack["status"] != "acknowledged" {
                return Err(Error::Protocol);
            }
            count += 1;
        }
        Ok(count)
    }
    pub(crate) async fn drain_workflow_run_deliveries(
        &mut self,
        workflow: &str,
        run: &str,
        rows: &[Value],
        deadline: crate::platform::time::Instant,
        cancel: &CancellationToken,
    ) -> Result<usize> {
        if self.team()?.is_some() {
            return Err(Error::Forbidden);
        }
        for id in [workflow, run] {
            uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("Invalid Workflow or run ID."))?;
        }
        let mut deliveries = BTreeMap::new();
        for row in rows {
            let mut delivery = WorkflowDelivery::parse(row)?;
            delivery.workflow = Some(workflow.into());
            delivery.run = Some(run.into());
            if deliveries.insert(delivery.id.clone(), delivery).is_some() {
                return Err(Error::Protocol);
            }
        }
        if deliveries.len() > 256 {
            return Err(Error::Protocol);
        }
        if deliveries.is_empty() {
            return Ok(0);
        }
        let mut socket = crate::platform::time::timeout_at(deadline, self.socket())
            .await
            .map_err(|_| Error::Offline)??;
        let result = self
            .persist_workflow_deliveries_until(&mut socket, &deliveries, deadline, cancel)
            .await;
        let _ = socket.close(None).await;
        result
    }
    fn workflow_owner(&self, owner: &str, generation: u64) -> Result<()> {
        if self.generation != generation
            || self.team()?.is_some()
            || required(&self.user, "id")? != owner
        {
            return Err(Error::Cancelled);
        }
        self.require_session()?;
        Ok(())
    }
}
fn validate_receipt(delivery: &WorkflowDelivery, value: &Value) -> Result<()> {
    if required(value, "delivery_id")? != delivery.id
        || required(value, "chat_id")? != delivery.chat
        || required(value, "message_id")? != delivery.message
    {
        return Err(Error::Forbidden);
    }
    for (key, expected) in [
        ("workflow_id", &delivery.workflow),
        ("run_id", &delivery.run),
    ] {
        if expected
            .as_deref()
            .is_some_and(|expected| value[key].as_str() != Some(expected))
        {
            return Err(Error::Forbidden);
        }
    }
    Ok(())
}
fn validate_claim(delivery: &WorkflowDelivery, claim: &Value, now: u64) -> Result<()> {
    validate_receipt(delivery, claim)?;
    WorkflowDelivery::parse(claim)?;
    if claim["status"] != "claimed" {
        return Err(Error::Protocol);
    }
    let token = required(claim, "claim_token")?;
    if token.len() > 512
        || claim["claim_generation"].as_u64().is_none_or(|v| v == 0)
        || claim["claim_expires_at"].as_u64().is_none_or(|v| v <= now)
        || claim["claim_issued_at"].as_u64().is_none_or(|v| {
            claim["claim_expires_at"]
                .as_u64()
                .is_none_or(|expires| v > expires)
        })
        || !claim["client_persisted"].is_boolean()
    {
        return Err(Error::Protocol);
    }
    Ok(())
}
fn encrypt_claim(claim: &Value, master: &[u8; 32]) -> Result<(Value, Value)> {
    if !claim
        .as_object()
        .is_some_and(|map| map.contains_key("existing_chat"))
    {
        return Err(Error::Protocol);
    }
    let existing = &claim["existing_chat"];
    if !existing.is_null() && !existing.is_object() {
        return Err(Error::Protocol);
    }
    if existing["hashed_team_id"]
        .as_str()
        .is_some_and(|v| !v.is_empty())
    {
        return Err(Error::Forbidden);
    }
    let (key, wrapped) = if existing.is_object() {
        let wrapped = required(existing, "encrypted_chat_key")?.to_owned();
        let key = key_from_bytes(&crypto::decrypt_bytes(&wrapped, master)?)?;
        (key, wrapped)
    } else {
        let key = crypto::random_key();
        let wrapped = crypto::encrypt_bytes(key.as_ref(), master)?;
        (key, wrapped)
    };
    let created = claim["created_at"]
        .as_u64()
        .filter(|n| *n > 0)
        .ok_or(Error::Protocol)?;
    let title = existing["encrypted_title"]
        .as_str()
        .filter(|v| !v.is_empty())
        .map(str::to_owned)
        .map(Ok)
        .unwrap_or_else(|| crypto::encrypt_combined(required(claim, "title")?, &key))?;
    let category = existing["encrypted_category"]
        .as_str()
        .filter(|v| !v.is_empty())
        .map(str::to_owned)
        .map(Ok)
        .unwrap_or_else(|| crypto::encrypt_combined("openmates_official", &key))?;
    let message = required(claim, "message")?;
    if message.len() > 8 * 1024 * 1024 {
        return Err(Error::Protocol);
    }
    let rows = claim["embeds"].as_array().ok_or(Error::Protocol)?;
    if rows.len() > 256 {
        return Err(Error::Protocol);
    }
    let mut encrypted = vec![];
    let mut ids = std::collections::BTreeSet::new();
    for row in rows {
        let id = required(row, "embed_id")?;
        uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
        if !ids.insert(id) {
            return Err(Error::Protocol);
        }
        let kind = required(row, "content_type")?;
        let mut content = row["content"].as_object().cloned().ok_or(Error::Protocol)?;
        content.insert("type".into(), json!(kind));
        let preview = content
            .get("title")
            .or_else(|| content.get("name"))
            .and_then(Value::as_str)
            .unwrap_or("Workflow result");
        let embed_key = crypto::random_key();
        encrypted.push(json!({"embed_id":id,"encrypted_content":crypto::encrypt_combined(&serde_json::to_string(&content)?,&embed_key)?,"encrypted_type":crypto::encrypt_combined(kind,&embed_key)?,"encrypted_text_preview":crypto::encrypt_combined(preview,&embed_key)?,"embed_keys":[{"key_type":"master","encrypted_embed_key":crypto::encrypt_bytes(embed_key.as_ref(),master)?},{"key_type":"chat","encrypted_embed_key":crypto::encrypt_bytes(embed_key.as_ref(),&key)?}]}));
    }
    let version = existing["messages_v"]
        .as_u64()
        .unwrap_or(0)
        .checked_add(1)
        .ok_or(Error::Protocol)?;
    let metadata = json!({"encrypted_title":title,"encrypted_category":category,"encrypted_chat_key":wrapped,"created_at":existing["created_at"].as_u64().unwrap_or(created),"messages_v":version,"title_v":existing["title_v"].as_u64().unwrap_or(1)});
    let message = json!({"role":"assistant","encrypted_content":crypto::encrypt_combined(message,&key)?,"created_at":created,"embeds":encrypted});
    Ok((metadata, message))
}

#[cfg(test)]
mod tests;
