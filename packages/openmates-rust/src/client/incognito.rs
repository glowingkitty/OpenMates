//! Volatile inference. Nothing in this module enters saved chat caches, recovery
//! journals, credentials, or draft state. Closing the authenticated socket
//! revokes its server-owned volatile session nonce.
use super::{send_observations::SendObservations, transport, *};
use crate::privacy::{PreparedPrivacy, prepare, restore};
use transport::{Socket, send};

const MAX_RESPONSE: usize = 16 * 1024 * 1024;
const MAX_EVENT: usize = 1024 * 1024;

impl Client {
    fn ephemeral_preflight(
        &self,
        text: &str,
        options: &SendOptions,
        anonymous: bool,
    ) -> Result<PreparedPrivacy> {
        options.validate()?;
        if options.project_id.is_some() || options.slug.is_some() {
            return Err(Error::Invalid(
                "Volatile chats cannot have a Project or saved slug.",
            ));
        }
        if options.memory_consent == SendConsentPolicy::ApproveRequested
            || options.sub_chat_consent == SendConsentPolicy::ApproveRequested
        {
            return Err(Error::Invalid(
                "Volatile chats cannot approve saved memories or sub-chats.",
            ));
        }
        if self
            .session
            .as_ref()
            .is_some_and(|s| s.active_team_id.is_some())
        {
            return Err(Error::Invalid(
                "Native volatile chat is available only in Personal scope.",
            ));
        }
        if text.trim().is_empty()
            || (anonymous && text.chars().count() > 20_000)
            || (!anonymous && text.len() > 1_000_000)
        {
            return Err(Error::Invalid(if anonymous {
                "Enter a message of at most 20,000 characters."
            } else {
                "Enter a message of at most 1 MB."
            }));
        }
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        self.verify_private_operation()?;
        if options.pii_detection {
            prepare(text, &[], &[])
        } else {
            Ok(PreparedPrivacy {
                text: text.into(),
                mappings: vec![],
            })
        }
    }
    fn register_ephemeral(&mut self, id: &str) -> Result<()> {
        // Never evict identifiers and accidentally permit a later draft write.
        if self.ephemeral_chats.len() >= 4096 {
            return Err(Error::Invalid(
                "Reset this client before starting more volatile chats.",
            ));
        }
        self.ephemeral_chats.insert(id.into());
        Ok(())
    }
    pub(super) async fn send_incognito(
        &mut self,
        chat: Option<&str>,
        input: &str,
        options: SendOptions,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> Result<SendOutcome> {
        if chat.is_some() {
            return Err(Error::Invalid(
                "Volatile continuation requires caller-owned history, which is not yet supported.",
            ));
        }
        let prepared = self.ephemeral_preflight(input, &options, false)?;
        self.require_session()?; // Never downgrade a rejected/expired session.
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let chat = uuid::Uuid::new_v4().to_string();
        let user = uuid::Uuid::new_v4().to_string();
        self.register_ephemeral(&chat)?;
        // Auth refresh completes before cancellation so rotations remain visible.
        let mut ws = self.ephemeral_socket().await?;
        let result = self
            .incognito_on_socket(
                &mut ws, &chat, &user, input, &prepared, &options, &updates, &cancel,
            )
            .await;
        // Close on every error, timeout and successful return. No lease/recovery
        // survives this socket, and no saved persistence receipt is claimed.
        let _ = crate::platform::time::timeout(Duration::from_secs(1), ws.close(None)).await;
        if matches!(result, Err(Error::Expired)) {
            self.forget_session();
        }
        result
    }
    #[allow(clippy::too_many_arguments)]
    async fn incognito_on_socket(
        &self,
        ws: &mut Socket,
        chat: &str,
        user: &str,
        input: &str,
        prepared: &PreparedPrivacy,
        options: &SendOptions,
        updates: &mpsc::Sender<StreamUpdate>,
        cancel: &CancellationToken,
    ) -> Result<SendOutcome> {
        if cancel.is_cancelled() || self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let created = now_ms() / 1000;
        let message = json!({"message_id":user,"chat_id":chat,"role":"user","sender_name":"User",
            "status":"sent","content":prepared.text,"created_at":created,"chat_has_title":false});
        send(ws, "set_active_chat", json!({"chat_id":chat})).await?;
        notify(
            updates,
            StreamUpdate::Started {
                chat_id: chat.into(),
                message_id: user.into(),
                expects_reply: true,
            },
        );
        notify(
            updates,
            StreamUpdate::Submitted {
                chat_id: chat.into(),
                message_id: user.into(),
            },
        );
        send(ws,"chat_message_added",json!({"chat_id":chat,"is_incognito":true,"client_capabilities":[],
            "active_focus_id":null,"focus_phase_state":null,"message":message,"message_history":[message]})).await?;
        let deadline = crate::platform::time::Instant::now() + response_timeout(options);
        let mut stream = VolatileStream::new(chat, user, input, &prepared.mappings);
        loop {
            let frame = tokio::select! {biased;
                _=cancel.cancelled()=>Err(Error::Cancelled),
                _=self.operation_cancel.cancelled()=>Err(Error::Cancelled),
                r=crate::platform::time::timeout_at(deadline, transport::receive_ephemeral(ws))=>r.map_err(|_|Error::Offline).and_then(|v|v),
            };
            let (kind, payload) = match frame {
                Ok(frame) => frame,
                Err(error) => {
                    if !stream.task.is_empty() {
                        let _ = crate::platform::time::timeout(
                            Duration::from_millis(250),
                            send(
                                ws,
                                "cancel_ai_task",
                                json!({"task_id":stream.task,"chat_id":chat}),
                            ),
                        )
                        .await;
                    }
                    return Err(error);
                }
            };
            stream.accept(&kind, &payload, false, updates)?;
            if stream.final_chunk {
                return stream.finish(updates);
            }
        }
    }

    /// Explicit anonymous text inference against the public cloud allowance.
    /// `anonymous_id` is caller-owned and must be separate from account/device
    /// identity. No Cookie, bearer, Origin or account device headers are sent,
    /// even when this Client has credentials. No credential fallback occurs.
    /// Durable Task jobs, saved memory and saved-chat options are disabled by
    /// volatile policy. History/learning-mode continuations are not yet exposed.
    pub async fn send_anonymous(
        &mut self,
        anonymous_id: &str,
        input: &str,
        options: SendOptions,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> Result<SendOutcome> {
        if anonymous_id.is_empty()
            || anonymous_id.len() > 128
            || !anonymous_id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
        {
            return Err(Error::Invalid(
                "Supply a separate anonymous identifier of 1 to 128 URL-safe characters.",
            ));
        }
        let prepared = self.ephemeral_preflight(input, &options, true)?;
        let chat = format!("anonymous-{}", uuid::Uuid::new_v4());
        let user = format!("anonymous-message-{}", uuid::Uuid::new_v4());
        self.register_ephemeral(&chat)?;
        let deadline = crate::platform::time::Instant::now() + response_timeout(&options);
        // All futures below are anonymous-only: dropping them cannot lose a
        // refresh-cookie rotation, because account cookies are never attached.
        tokio::select! {biased;
            _=cancel.cancelled()=>Err(Error::Cancelled),
            _=self.operation_cancel.cancelled()=>Err(Error::Cancelled),
            r=crate::platform::time::timeout_at(deadline,self.anonymous_request(anonymous_id,&chat,&user,input,&prepared,&options,&updates))=>r.map_err(|_|Error::Offline)?,
        }
    }
    #[allow(clippy::too_many_arguments)]
    async fn anonymous_request(
        &self,
        anonymous_id: &str,
        chat: &str,
        user: &str,
        input: &str,
        prepared: &PreparedPrivacy,
        options: &SendOptions,
        updates: &mpsc::Sender<StreamUpdate>,
    ) -> Result<SendOutcome> {
        let status = self
            .http
            .get(self.url("/v1/anonymous/free-usage/status")?)
            .header("X-OpenMates-Anonymous-ID", anonymous_id)
            .header("X-OpenMates-SDK", self.options.identity.header())
            .header("Accept", "application/json")
            .send()
            .await
            .map_err(|_| Error::Offline)?;
        anonymous_status(status.status())?;
        let bytes = bounded_body(status, MAX_EVENT).await?;
        let status: Value = serde_json::from_slice(&bytes)?;
        if status["active"] != true || status["can_send_text"] != true {
            return Err(Error::SignupRequired);
        }
        notify(
            updates,
            StreamUpdate::Started {
                chat_id: chat.into(),
                message_id: user.into(),
                expects_reply: true,
            },
        );
        notify(
            updates,
            StreamUpdate::Submitted {
                chat_id: chat.into(),
                message_id: user.into(),
            },
        );
        let mut response = self
            .http
            .post(self.url("/v1/anonymous/chat/stream")?)
            .header("X-OpenMates-Anonymous-ID", anonymous_id)
            .header("X-OpenMates-SDK", self.options.identity.header())
            .header("Accept", "text/event-stream")
            .timeout(response_timeout(options))
            .json(
                &json!({"anonymous_id":anonymous_id,"client_chat_id":chat,"client_message_id":user,
                "plaintext_message":prepared.text,"message_history":[]}),
            )
            .send()
            .await
            .map_err(|_| Error::Offline)?;
        anonymous_status(response.status())?;
        let mut stream = VolatileStream::new(chat, user, input, &prepared.mappings);
        if response
            .headers()
            .get("Content-Type")
            .and_then(|v| v.to_str().ok())
            .is_some_and(|v| {
                v.split(';')
                    .next()
                    .is_some_and(|v| v.trim() == "application/json")
            })
        {
            let body: Value = serde_json::from_slice(&bounded_body(response, MAX_RESPONSE).await?)?;
            if body["status"] != "completed" || body["chatId"] != chat {
                return Err(Error::Protocol);
            }
            stream.assistant = required(&body, "messageId")?.into();
            stream.content = required(&body, "assistant")?.into();
            stream.observed.capture_owned(
                "anonymous_completion",
                &json!({"category":body["category"],"model_name":body["modelName"]}),
            )?;
            if let Some(rows) = body["followUpSuggestions"].as_array() {
                stream.observed.suggestions = rows
                    .iter()
                    .map(|row| row.as_str().map(str::to_owned).ok_or(Error::Protocol))
                    .collect::<Result<_>>()?;
            }
            stream.final_chunk = true;
            return stream.finish(updates);
        }
        if !response
            .headers()
            .get("Content-Type")
            .and_then(|v| v.to_str().ok())
            .is_some_and(|v| {
                v.split(';')
                    .next()
                    .is_some_and(|v| v.trim() == "text/event-stream")
            })
        {
            return Err(Error::Protocol);
        }
        let mut parser = Sse::default();
        while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
            for event in parser.push(&chunk)? {
                let frame: Value = serde_json::from_slice(&event)?;
                let kind = required(&frame, "type")?;
                let payload = frame.get("payload").unwrap_or(&frame);
                stream.accept(kind, payload, true, updates)?;
            }
        }
        if !parser.pending.is_empty() || !stream.ended || !stream.final_chunk {
            return Err(Error::Protocol);
        }
        stream.finish(updates)
    }
}

fn response_timeout(options: &SendOptions) -> Duration {
    Duration::from_millis(options.response_timeout_ms.unwrap_or(120_000))
}
fn notify(updates: &mpsc::Sender<StreamUpdate>, update: StreamUpdate) {
    let _ = updates.try_send(update);
}
fn anonymous_status(status: reqwest::StatusCode) -> Result<()> {
    if status.is_success() {
        return Ok(());
    }
    Err(match status.as_u16() {
        404 | 429 => Error::SignupRequired,
        400 | 422 => Error::Invalid("The anonymous request was rejected."),
        401 | 403 | 300..=399 => Error::Forbidden,
        500..=599 => Error::Offline,
        _ => Error::Protocol,
    })
}
async fn bounded_body(
    mut response: crate::platform::http::Response,
    max: usize,
) -> Result<Vec<u8>> {
    if response.content_length().is_some_and(|n| n > max as u64) {
        return Err(Error::Protocol);
    }
    let mut bytes = vec![];
    while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
        if bytes.len() + chunk.len() > max {
            return Err(Error::Protocol);
        }
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

// The same strict turn reducer covers cookie WS payloads and anonymous SSE.
// It never treats streamed text as proof that a saved object was persisted.
struct VolatileStream<'a> {
    chat: &'a str,
    user: &'a str,
    input: &'a str,
    mappings: &'a [Value],
    task: String,
    assistant: String,
    content: String,
    thinking: String,
    embeds: BTreeMap<String, Item>,
    observed: SendObservations,
    final_chunk: bool,
    ended: bool,
    sequence: u64,
    received: usize,
}
impl<'a> VolatileStream<'a> {
    fn new(chat: &'a str, user: &'a str, input: &'a str, mappings: &'a [Value]) -> Self {
        Self {
            chat,
            user,
            input,
            mappings,
            task: String::new(),
            assistant: String::new(),
            content: String::new(),
            thinking: String::new(),
            embeds: BTreeMap::new(),
            observed: Default::default(),
            final_chunk: false,
            ended: false,
            sequence: 0,
            received: 0,
        }
    }
    fn accept(
        &mut self,
        kind: &str,
        p: &Value,
        anonymous: bool,
        updates: &mpsc::Sender<StreamUpdate>,
    ) -> Result<()> {
        let chat = p["chat_id"].as_str().or_else(|| p["chatId"].as_str());
        let user = p["user_message_id"].as_str();
        if chat.is_some_and(|v| v != self.chat) || user.is_some_and(|v| v != self.user) {
            return Ok(());
        }
        let size = p.to_string().len();
        self.received = self.received.checked_add(size).ok_or(Error::Protocol)?;
        if size > MAX_EVENT || self.received > MAX_RESPONSE {
            return Err(Error::Protocol);
        }
        if kind == "error" {
            // A direct per-socket refusal can precede task allocation. Never
            // echo backend text, which may contain private input or credentials.
            return Err(match p["code"].as_str() {
                Some("insufficient_credits" | "insufficient_balance" | "credit_limit_exceeded") => {
                    Error::Invalid("Insufficient credits for this request.")
                }
                Some("volatile_live_session_required") => {
                    Error::Invalid("A live incognito session could not be established.")
                }
                _ => Error::Protocol,
            });
        }
        if kind == "ai_task_initiated" && chat == Some(self.chat) && user == Some(self.user) {
            let task = p["ai_task_id"]
                .as_str()
                .or_else(|| p["task_id"].as_str())
                .filter(|v| !v.is_empty())
                .ok_or(Error::Protocol)?;
            if !self.task.is_empty() && self.task != task {
                return Err(Error::Protocol);
            }
            self.task = task.into();
            return Ok(());
        }
        // The authenticated typing listener intentionally omits task_id. Its
        // message_id is the AI task ID; exact chat+user binds it to this turn.
        if kind == "ai_typing_started" && chat == Some(self.chat) && user == Some(self.user) {
            let assistant = required(p, "message_id")?;
            let task = p["task_id"].as_str().unwrap_or(assistant);
            if (!self.task.is_empty() && self.task != task)
                || (!self.assistant.is_empty() && self.assistant != assistant)
            {
                return Err(Error::Protocol);
            }
            self.task = task.into();
            self.assistant = assistant.into();
            self.observed.capture_owned(kind, p)?;
            return Ok(());
        }
        if (chat == Some(self.chat)
            && matches!(
                kind,
                "request_app_settings_memories"
                    | "sub_chat_confirmation_required"
                    | "task_update_jobs_available"
                    | "task_event"
            ))
            || (kind == "task_update_jobs_available"
                && p["jobs"]
                    .as_array()
                    .is_some_and(|jobs| jobs.iter().any(|job| job["chat_id"] == self.chat)))
        {
            return Err(Error::Protocol);
        }
        let task = p["task_id"].as_str().or_else(|| p["taskId"].as_str());
        if self.task.is_empty() || task.is_some_and(|v| v != self.task) {
            return Ok(());
        }
        if chat != Some(self.chat) || task != Some(self.task.as_str()) {
            return Ok(());
        }
        if matches!(kind, "ai_task_error" | "ai_error") {
            return Err(Error::Protocol);
        }
        if matches!(
            kind,
            "task_update_jobs_available"
                | "task_event"
                | "sub_chat_confirmation_required"
                | "request_app_settings_memories"
        ) {
            return Err(Error::Protocol); // Volatile policy forbids private durable work.
        }
        if kind == "ai_task_ended" {
            if p["status"] != "completed" || !self.final_chunk {
                return Err(Error::Protocol);
            }
            self.ended = true;
            return Ok(());
        }
        if matches!(
            kind,
            "ai_typing_started"
                | "ai_message_update"
                | "ai_message_chunk"
                | "ai_background_response_completed"
        ) {
            let message = required(p, "message_id")?;
            if self.assistant.is_empty() {
                self.assistant = message.into();
            }
            if self.assistant != message {
                return Err(Error::Protocol);
            }
        }
        self.observed.capture_owned(kind, p)?;
        if kind == "send_embed_data" {
            if p["message_id"].as_str() != Some(self.assistant.as_str())
                || p["already_encrypted"] == true
            {
                return Err(Error::Protocol);
            }
            let id = required(p, "embed_id")?;
            if self.embeds.len() >= 100 {
                return Err(Error::Protocol);
            }
            self.embeds.insert(
                id.into(),
                Item {
                    id: id.into(),
                    title: p["title"].as_str().unwrap_or("Result").into(),
                    category: p["type"].as_str().unwrap_or_default().into(),
                    fields: p.clone(),
                    ..Item::default()
                },
            );
        }
        if kind == "thinking_chunk" {
            self.thinking.push_str(text(p, "content"));
        }
        if matches!(
            kind,
            "ai_message_update" | "ai_message_chunk" | "ai_background_response_completed"
        ) {
            if p["signup_required"] == true {
                return Err(Error::SignupRequired);
            }
            if p.get("rejection_reason").is_some_and(|v| !v.is_null()) {
                return Err(Error::Protocol);
            }
            if anonymous {
                let sequence = p["sequence"]
                    .as_u64()
                    .filter(|n| *n > self.sequence)
                    .ok_or(Error::Protocol)?;
                self.sequence = sequence;
            }
            if let Some(content) = p["full_content_so_far"]
                .as_str()
                .or_else(|| p["full_content"].as_str())
            {
                self.content = content.into();
            }
            let continuation = [
                "waiting_for_skill_completion",
                "awaiting_async_skill_continuation",
                "awaiting_focus_mode_continuation",
                "awaiting_sub_chats_completion",
                "is_project_operation_pending",
            ]
            .iter()
            .any(|key| p[*key] == true);
            if (p["is_final_chunk"] == true || kind == "ai_background_response_completed")
                && !continuation
            {
                self.final_chunk = true;
            }
        }
        if self.content.len() + self.thinking.len() > MAX_RESPONSE {
            return Err(Error::Protocol);
        }
        if kind == "thinking_chunk"
            || matches!(
                kind,
                "ai_message_update" | "ai_message_chunk" | "ai_background_response_completed"
            )
        {
            notify(
                updates,
                StreamUpdate::Content {
                    content: restore(&self.content, self.mappings)?,
                    thinking: restore(&self.thinking, self.mappings)?,
                    mate: self.observed.mate.clone().unwrap_or_default(),
                },
            );
        }
        Ok(())
    }
    fn finish(self, updates: &mpsc::Sender<StreamUpdate>) -> Result<SendOutcome> {
        if !self.final_chunk || self.assistant.is_empty() || self.content.trim().is_empty() {
            return Err(Error::Protocol);
        }
        let content = restore(&self.content, self.mappings)?;
        let thinking = restore(&self.thinking, self.mappings)?;
        let chat = Chat {
            id: self.chat.into(),
            title: String::new(),
            category: self.observed.category.clone().unwrap_or_default(),
            messages: vec![
                Message {
                    id: self.user.into(),
                    role: "user".into(),
                    sender: "User".into(),
                    content: self.input.into(),
                    ..Message::default()
                },
                Message {
                    id: self.assistant.clone(),
                    role: "assistant".into(),
                    sender: "Assistant".into(),
                    content: content.clone(),
                    thinking,
                    embeds: self.embeds.into_values().collect(),
                },
            ],
        };
        notify(
            updates,
            StreamUpdate::Completed {
                chat_id: self.chat.into(),
                message_id: self.assistant.clone(),
                content,
            },
        );
        Ok(self.observed.finish(
            chat,
            self.user,
            Some(&self.assistant),
            SendStatus::Completed,
        ))
    }
}

#[derive(Default)]
struct Sse {
    pending: Vec<u8>,
    total: usize,
}
impl Sse {
    fn push(&mut self, chunk: &[u8]) -> Result<Vec<Vec<u8>>> {
        self.total = self.total.checked_add(chunk.len()).ok_or(Error::Protocol)?;
        if self.total > MAX_RESPONSE {
            return Err(Error::Protocol);
        }
        self.pending.extend_from_slice(chunk);
        let mut events = vec![];
        while let Some((end, sep)) = [
            self.pending
                .windows(2)
                .position(|v| v == b"\n\n")
                .map(|n| (n, 2)),
            self.pending
                .windows(4)
                .position(|v| v == b"\r\n\r\n")
                .map(|n| (n, 4)),
        ]
        .into_iter()
        .flatten()
        .min_by_key(|v| v.0)
        {
            if end > MAX_EVENT {
                return Err(Error::Protocol);
            }
            let frame = std::str::from_utf8(&self.pending[..end]).map_err(|_| Error::Protocol)?;
            let data = frame
                .lines()
                .filter_map(|line| {
                    line.strip_prefix("data:")
                        .map(|v| v.strip_prefix(' ').unwrap_or(v))
                })
                .collect::<Vec<_>>()
                .join("\n");
            if !data.is_empty() {
                events.push(data.into_bytes());
            }
            self.pending.drain(..end + sep);
        }
        if self.pending.len() > MAX_EVENT {
            return Err(Error::Protocol);
        }
        Ok(events)
    }
}

#[cfg(test)]
mod tests;
