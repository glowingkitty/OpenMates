//! Explicit one-request consent. Neither caller decisions nor buffered frames
//! replace the original credential/chat scope or authorize another request.
use super::memory_catalog;
use super::plaintext::{Plain, Wipe};
use super::sync_capability::AsyncCryptoScope;
use super::transport::{Socket, receive, send_plaintext, wait};
use super::*;
use std::collections::BTreeSet;
struct ConsentKeys {
    keys: BTreeSet<String>,
}
impl Wipe for ConsentKeys {
    fn wipe(&mut self) {
        for mut key in std::mem::take(&mut self.keys) {
            key.wipe();
        }
    }
}
impl ConsentKeys {
    fn insert(&mut self, key: String) {
        if let Some(mut duplicate) = self.keys.replace(key) {
            duplicate.wipe();
        }
    }
}
enum ConsentInbox {
    CallerCancelled,
    Deadline,
    Revoked,
    Decision(Plain<Option<(String, Vec<String>)>>),
    Frame(Result<Plain<(String, Value)>>),
}
impl Client {
    #[allow(clippy::too_many_arguments)]
    pub(super) async fn subchat_consent(
        &mut self,
        ws: &mut Socket,
        event: &Value,
        chat: &str,
        task: &str,
        updates: &mpsc::Sender<StreamUpdate>,
        cancel: &CancellationToken,
        policy: SendConsentPolicy,
    ) -> Result<Vec<(String, Value)>> {
        let scope = AsyncCryptoScope::begin(self)?;
        self.require_browser_owner_guards()?;
        scope.check_chat(self, chat)?;
        let proposals = event["sub_chats"].as_array().ok_or(Error::Protocol)?;
        let allowed = subchat_capacity(event)?;
        if policy != SendConsentPolicy::Caller {
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            let approved = allowed && policy == SendConsentPolicy::ApproveRequested;
            scope.check_chat(self, chat)?;
            let result=send_plaintext(ws,"sub_chat_confirmation",json!({"chat_id":chat,"task_id":task,"action":if approved{"approve"}else{"cancel"},"approve_count":if approved{Some(proposals.len())}else{None}})).await;
            scope.check_chat(self, chat)?;
            result?;
            return Ok(vec![]);
        }
        let request_id = Plain::new(format!("subchat:{chat}:{task}"));
        if allowed {
            let mut entries = Plain::new(Vec::<Value>::new());
            for proposal in proposals {
                entries.push(json!({"title":proposal["title"],"prompt":proposal["prompt"],"mate":proposal["mate"]}));
            }
            let mut items = Plain::new(Vec::<Item>::new());
            items.push(Item{id:"start_sub_chats".into(),title:format!("Start {} sub-chats",proposals.len()),description:"Approve this proposed batch. Each sub-chat can perform additional work and use credits.".into(),fields:json!({"consent_kind":"sub_chats","entries":&*entries}),..Item::default()});
            if updates.is_closed() {
                return Err(Error::Cancelled);
            }
            let delivered = self
                .deliver_turn_update(
                    &scope,
                    chat,
                    updates,
                    cancel,
                    StreamUpdate::Consent {
                        request_id: request_id.to_string(),
                        items: items.into_inner(),
                    },
                )
                .await;
            scope.check_chat(self, chat)?;
            delivered?;
            if updates.is_closed() {
                return Err(Error::Cancelled);
            }
            let mut deferred = Plain::new(Vec::<(String, Value)>::new());
            let mut size = 0usize;
            let deadline = crate::platform::time::Instant::now() + Duration::from_secs(600);
            let decision = loop {
                let next = self
                    .consent_input(
                        ws,
                        &scope,
                        chat,
                        cancel,
                        deadline,
                        "The caller did not supply a sub-chat consent receiver.",
                    )
                    .await?;
                match next {
                    ConsentInbox::CallerCancelled => {
                        // Preserve the original cancellation notice only while
                        // the original authority still permits a WS effect.
                        scope.check_chat(self, chat)?;
                        let _result = send_plaintext(
                            ws,
                            "sub_chat_confirmation",
                            json!({"chat_id":chat,"task_id":task,"action":"cancel"}),
                        )
                        .await;
                        scope.check_chat(self, chat)?;
                        return Err(Error::Cancelled);
                    }
                    ConsentInbox::Deadline => break false,
                    ConsentInbox::Revoked => return Err(Error::Cancelled),
                    ConsentInbox::Decision(mut decision) => {
                        let (id, ids) = decision.as_mut().ok_or(Error::Cancelled)?;
                        if id.as_str() != request_id.as_str() {
                            continue;
                        }
                        if ids.iter().any(|id| id != "start_sub_chats") || ids.len() > 1 {
                            return Err(Error::Forbidden);
                        }
                        break ids.len() == 1;
                    }
                    ConsentInbox::Frame(frame) => {
                        let frame = frame?;
                        let serialized = zeroize::Zeroizing::new((*frame).1.to_string());
                        size += (*frame).0.len() + serialized.len();
                        if deferred.len() >= 256 || size > 16 * 1024 * 1024 {
                            return Err(Error::Protocol);
                        }
                        deferred.push(frame.into_inner());
                    }
                }
            };
            scope.check_chat(self, chat)?;
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            let result=send_plaintext(ws,"sub_chat_confirmation",json!({"chat_id":chat,"task_id":task,"action":if decision{"approve"}else{"cancel"},"approve_count":if decision{Some(proposals.len())}else{None}})).await;
            scope.check_chat(self, chat)?;
            result?;
            Ok(deferred.into_inner())
        } else {
            scope.check_chat(self, chat)?;
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            let result = send_plaintext(
                ws,
                "sub_chat_confirmation",
                json!({"chat_id":chat,"task_id":task,"action":"cancel"}),
            )
            .await;
            scope.check_chat(self, chat)?;
            result?;
            Ok(vec![])
        }
    }
    #[allow(clippy::too_many_arguments)]
    pub(super) async fn memory_consent(
        &mut self,
        ws: &mut Socket,
        event: &Value,
        chat_id: &str,
        user_message: &str,
        key: &[u8; 32],
        memories: &[Value],
        mappings: &[Value],
        updates: &mpsc::Sender<StreamUpdate>,
        cancel: &CancellationToken,
        policy: SendConsentPolicy,
    ) -> Result<(Vec<(String, Value)>, SendMemoryRequest, Vec<Value>)> {
        let scope = AsyncCryptoScope::begin(self)?;
        self.require_browser_owner_guards()?;
        scope.check_chat(self, chat_id)?;
        // Personal Memory documents (`memory-<id>`) are decided from this
        // device's stored load mode, never from the server, under the same
        // owner/chat scope as the answer.
        let memory_keys = event["requested_keys"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .filter_map(Value::as_str)
            .filter(|key| memory_catalog::is_memory_request_key(key) && key.len() <= 256)
            .take(64)
            .map(str::to_owned)
            .collect::<BTreeSet<_>>();
        let decision = Plain::new(self.memory_request_decision(chat_id, &memory_keys).await?);
        scope.check_chat(self, chat_id)?;
        self.memory_consent_decided(
            ws,
            &scope,
            event,
            chat_id,
            user_message,
            key,
            memories,
            mappings,
            decision,
            updates,
            cancel,
            policy,
        )
        .await
    }
    /// [`Self::memory_consent`] once the Memory documents are decided: Auto
    /// include ones are answered without asking, Ask first ones join the
    /// consent dialog, and without dialog keys nothing is persisted to approve.
    #[allow(clippy::too_many_arguments)]
    pub(super) async fn memory_consent_decided(
        &mut self,
        ws: &mut Socket,
        scope: &AsyncCryptoScope,
        event: &Value,
        chat_id: &str,
        user_message: &str,
        key: &[u8; 32],
        memories: &[Value],
        mappings: &[Value],
        decision: Plain<memory_catalog::MemoryRequestDecision>,
        updates: &mpsc::Sender<StreamUpdate>,
        cancel: &CancellationToken,
        policy: SendConsentPolicy,
    ) -> Result<(Vec<(String, Value)>, SendMemoryRequest, Vec<Value>)> {
        scope.check_chat(self, chat_id)?;
        let key = zeroize::Zeroizing::new(*key);
        let request_id = Plain::new(
            event
                .get("request_id")
                .and_then(Value::as_str)
                .filter(|id| !id.is_empty() && id.len() <= 128)
                .ok_or(Error::Protocol)?
                .to_owned(),
        );
        let mut requested = Plain::new(ConsentKeys {
            keys: BTreeSet::new(),
        });
        for value in event["requested_keys"].as_array().ok_or(Error::Protocol)? {
            // `memory-<id>` keys carry ids of up to 240 characters.
            let value = value
                .as_str()
                .filter(|v| !v.is_empty() && v.len() <= 256)
                .ok_or(Error::Protocol)?;
            requested.insert(value.to_owned());
        }
        if requested.keys.len() > 64 {
            return Err(Error::Protocol);
        }
        let mut dialog = Plain::new(ConsentKeys {
            keys: requested
                .keys
                .iter()
                .filter(|key| !memory_catalog::is_memory_request_key(key))
                .cloned()
                .collect(),
        });
        for memory in &decision.ask {
            dialog.insert(memory.key());
        }
        // Only Auto include Memories were requested: answer at once, with no
        // request/response pair to approve (web `handleRequestAppSettingsMemoriesImpl`).
        let needs_dialog = !dialog.keys.is_empty();
        let mut items = Plain::new(Vec::<Item>::new());
        for category in dialog
            .keys
            .iter()
            .filter(|key| !memory_catalog::is_memory_request_key(key))
        {
            let mut entries = Plain::new(Vec::<Value>::new());
            for memory in memories
                .iter()
                .filter(|m| format!("{}-{}", text(m, "app_id"), text(m, "item_type")) == *category)
            {
                entries.push(memory["data"].clone());
            }
            items.push(Item {
                id: category.clone(),
                title: category.replace('_', " "),
                description: format!("{} saved entries", entries.len()),
                fields: json!({"entries":&*entries}),
                ..Item::default()
            });
        }
        for memory in &decision.ask {
            items.push(memory_catalog::ask_first_item(memory));
        }
        if needs_dialog {
            let mut request_content = Plain::new(
                json!({"type":"app_settings_memories_request","user_message_id":user_message,"request_id":request_id.as_str(),"requested_keys":&dialog.keys}),
            );
            if !decision.auto.is_empty() {
                // `withAutoMemoryIds`: lets another device re-resolve them.
                let ids: BTreeSet<&str> = decision.auto.iter().map(|m| m.id.as_str()).collect();
                request_content["auto_memory_ids"] = json!(ids);
            }
            let request_message = Plain::new(format!(
                "{user_message}-memory-request-{}",
                request_id.as_str()
            ));
            self.persist_consent_system(
                ws,
                scope,
                chat_id,
                &request_message,
                user_message,
                &key,
                request_content,
                cancel,
            )
            .await?;
            scope.check_chat(self, chat_id)?;
        }
        let mut deferred = Plain::new(Vec::<(String, Value)>::new());
        let mut approved = if !needs_dialog {
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            Plain::new(ConsentKeys {
                keys: BTreeSet::new(),
            })
        } else if policy == SendConsentPolicy::Caller {
            if updates.is_closed() {
                return Err(Error::Cancelled);
            }
            let delivered = self
                .deliver_turn_update(
                    scope,
                    chat_id,
                    updates,
                    cancel,
                    StreamUpdate::Consent {
                        request_id: request_id.to_string(),
                        items: items.into_inner(),
                    },
                )
                .await;
            scope.check_chat(self, chat_id)?;
            delivered?;
            if updates.is_closed() {
                return Err(Error::Cancelled);
            }
            let mut buffered = 0usize;
            let deadline = crate::platform::time::Instant::now() + Duration::from_secs(600);
            loop {
                let next = self
                    .consent_input(
                        ws,
                        scope,
                        chat_id,
                        cancel,
                        deadline,
                        "The caller did not supply a private-memory consent receiver.",
                    )
                    .await?;
                match next {
                    ConsentInbox::CallerCancelled
                    | ConsentInbox::Deadline
                    | ConsentInbox::Revoked => return Err(Error::Cancelled),
                    ConsentInbox::Decision(mut decision) => {
                        let (id, ids) = decision.as_mut().ok_or(Error::Cancelled)?;
                        if id.as_str() != request_id.as_str() {
                            continue;
                        }
                        let mut selected = Plain::new(ConsentKeys {
                            keys: BTreeSet::new(),
                        });
                        for id in std::mem::take(ids) {
                            selected.insert(id);
                        }
                        if !selected.keys.is_subset(&dialog.keys) {
                            return Err(Error::Forbidden);
                        }
                        break selected;
                    }
                    ConsentInbox::Frame(frame) => {
                        let frame = frame?;
                        let serialized = zeroize::Zeroizing::new((*frame).1.to_string());
                        buffered += (*frame).0.len() + serialized.len();
                        if deferred.len() >= 256 || buffered > 16 * 1024 * 1024 {
                            return Err(Error::Protocol);
                        }
                        deferred.push(frame.into_inner());
                    }
                }
            }
        } else {
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            Plain::new(ConsentKeys {
                keys: if policy == SendConsentPolicy::ApproveRequested {
                    dialog.keys.clone()
                } else {
                    BTreeSet::new()
                },
            })
        };
        let mut entries = Plain::new(Vec::<Value>::new());
        for memory in memories.iter().filter(|m| {
            let category = format!("{}-{}", text(m, "app_id"), text(m, "item_type"));
            !memory_catalog::is_memory_request_key(&category) && approved.keys.contains(&category)
        }) {
            entries.push(json!({"app_id":memory["app_id"],"item_key":memory["item_type"],"content":memory["data"]}));
        }
        // Auto include Memories are released by their own mode; Ask first ones
        // only when approved (a rejection still sends the Auto include ones).
        let released_ask = decision
            .ask
            .iter()
            .filter(|m| approved.keys.contains(&m.key()))
            .collect::<Vec<_>>();
        for memory in decision.auto.iter().chain(released_ask.iter().copied()) {
            entries.push(memory.response_entry());
        }
        // Released bodies are anonymized like message text: real details never
        // reach the server or the model (plan decision D-5).
        let added = Plain::new(memory_privacy::anonymize_entries(
            entries.as_mut_slice(),
            memories,
            mappings,
        )?);
        scope.check_chat(self, chat_id)?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let result = send_plaintext(
            ws,
            "app_settings_memories_confirmed",
            json!({"chat_id":chat_id,"app_settings_memories":&*entries}),
        )
        .await;
        scope.check_chat(self, chat_id)?;
        result?;
        let mut categories = Plain::new(Vec::<Value>::new());
        for category in approved
            .keys
            .iter()
            .filter(|key| !memory_catalog::is_memory_request_key(key))
        {
            let matching = memories
                .iter()
                .filter(|m| format!("{}-{}", text(m, "app_id"), text(m, "item_type")) == *category)
                .collect::<Vec<_>>();
            categories.push(json!({"appId":matching.first().map(|m|text(m,"app_id")).unwrap_or(""),"itemType":matching.first().map(|m|text(m,"item_type")).unwrap_or(""),"entryCount":matching.len()}));
        }
        for memory in &released_ask {
            categories.push(json!({"appId":memory_catalog::MEMORY_RESPONSE_APP_ID,"itemType":memory.id,"entryCount":1}));
        }
        if !decision.auto.is_empty() {
            categories.push(json!({"appId":memory_catalog::MEMORY_RESPONSE_APP_ID,"itemType":"memories","entryCount":decision.auto.len()}));
        }
        // The web client stores no response for a silent answer without content.
        if needs_dialog || !entries.is_empty() {
            let mut response = Plain::new(
                json!({"type":"app_settings_memories_response","user_message_id":user_message,"action":if entries.is_empty(){"rejected"}else{"included"},"categories":&*categories}),
            );
            if !added.is_empty() {
                // Chat-key encrypted with the message: history restores them.
                response["pii_mappings"] = json!(&*added);
            }
            let response_message = Plain::new(format!(
                "{user_message}-memory-response-{}",
                request_id.as_str()
            ));
            self.persist_consent_system(
                ws,
                scope,
                chat_id,
                &response_message,
                user_message,
                &key,
                response,
                cancel,
            )
            .await?;
            scope.check_chat(self, chat_id)?;
        }
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        for memory in &decision.auto {
            approved.insert(memory.key());
        }
        let record = Plain::new(SendMemoryRequest {
            request_id: Some(request_id.into_inner()),
            requested_keys: std::mem::take(&mut requested.keys).into_iter().collect(),
            approved_keys: std::mem::take(&mut approved.keys).into_iter().collect(),
            entry_count: entries.len() as u64,
        });
        Ok((deferred.into_inner(), record.into_inner(), added.into_inner()))
    }
    #[allow(clippy::too_many_arguments)]
    async fn consent_input(
        &mut self,
        ws: &mut Socket,
        scope: &AsyncCryptoScope,
        chat: &str,
        cancel: &CancellationToken,
        deadline: crate::platform::time::Instant,
        missing: &'static str,
    ) -> Result<ConsentInbox> {
        scope.check_chat(self, chat)?;
        let master = self.master_capability()?;
        let expiry = self.require_credentials()?.paired_session_expires_at;
        let expired = async {
            if let Some(deadline) = expiry {
                loop {
                    let remaining = deadline.saturating_sub(now_ms());
                    if remaining == 0 {
                        break;
                    }
                    crate::platform::time::sleep(Duration::from_millis(remaining)).await;
                }
            } else {
                std::future::pending::<()>().await
            }
        };
        let receiver = self.consent.as_mut().ok_or(Error::Invalid(missing))?;
        let next = tokio::select! {biased;
            _=cancel.cancelled()=>ConsentInbox::CallerCancelled,
            _=self.operation_cancel.cancelled()=>ConsentInbox::Revoked,
            _=self.task_watch_authority.cancel.cancelled()=>ConsentInbox::Revoked,
            _=master.cancelled()=>ConsentInbox::Revoked,
            _=expired=>ConsentInbox::Revoked,
            _=crate::platform::time::sleep_until(deadline)=>ConsentInbox::Deadline,
            decision=receiver.recv()=>ConsentInbox::Decision(Plain::new(decision)),
            frame=receive(ws)=>ConsentInbox::Frame(frame.map(Plain::new)),
        };
        scope.check_chat(self, chat)?;
        Ok(next)
    }
    #[allow(clippy::too_many_arguments)]
    async fn persist_consent_system(
        &mut self,
        ws: &mut Socket,
        scope: &AsyncCryptoScope,
        chat: &str,
        message: &str,
        user: &str,
        key: &[u8; 32],
        content: Plain<Value>,
        cancel: &CancellationToken,
    ) -> Result<()> {
        scope.check_chat(self, chat)?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let serialized = zeroize::Zeroizing::new(content.to_string());
        let encrypted = crypto::encrypt_combined(&serialized, key)?;
        drop(serialized);
        drop(content);
        let mut payload = json!({"chat_id":chat,"message":{"message_id":message,"chat_id":chat,"role":"system","user_message_id":user,"encrypted_content":encrypted,"created_at":now_ms()/1000,"status":"synced"}});
        if let Some(team) = self.team()? {
            payload["team_id"] = json!(team);
        }
        scope.check_chat(self, chat)?;
        let result = send_plaintext(ws, "chat_system_message_added", payload).await;
        scope.check_chat(self, chat)?;
        result?;
        let result = wait(ws, "system_message_confirmed", "message_id", message).await;
        scope.check_chat(self, chat)?;
        result?;
        Ok(())
    }
}
fn subchat_capacity(event: &Value) -> Result<bool> {
    let count = event["sub_chats"].as_array().ok_or(Error::Protocol)?.len() as u64;
    if count == 0 || count > 100 {
        return Ok(false);
    }
    let number = |field: &str| -> Result<Option<u64>> {
        match event.get(field) {
            None | Some(Value::Null) => Ok(None),
            Some(v) => v.as_u64().map(Some).ok_or(Error::Protocol),
        }
    };
    if number("remaining_sub_chats")?.is_some_and(|limit| count > limit) {
        return Ok(false);
    }
    if let (Some(max), Some(existing)) = (
        number("max_direct_sub_chats")?,
        number("existing_sub_chats")?,
    ) && existing.checked_add(count).is_none_or(|n| n > max)
    {
        return Ok(false);
    }
    Ok(true)
}
#[cfg(test)]
mod subchat_tests {
    use super::*;
    #[test]
    fn approval_requires_nonempty_batch_within_fresh_server_limits() {
        assert!(!subchat_capacity(&json!({"sub_chats":[]})).unwrap());
        assert!(!subchat_capacity(&json!({"sub_chats":[{},{}],"remaining_sub_chats":1})).unwrap());
        assert!(
            !subchat_capacity(
                &json!({"sub_chats":[{},{}],"existing_sub_chats":4,"max_direct_sub_chats":5})
            )
            .unwrap()
        );
        assert!(subchat_capacity(&json!({"sub_chats":[{},{}],"existing_sub_chats":3,"max_direct_sub_chats":5,"remaining_sub_chats":2})).unwrap());
        assert!(subchat_capacity(&json!({"sub_chats":[{}],"remaining_sub_chats":-1})).is_err());
    }
    #[tokio::test]
    async fn explicit_policy_approves_only_the_current_bounded_batch_without_a_receiver() {
        use futures_util::StreamExt;
        for (policy, remaining, action) in [
            (SendConsentPolicy::Reject, 2, "cancel"),
            (SendConsentPolicy::ApproveRequested, 2, "approve"),
            (SendConsentPolicy::ApproveRequested, 1, "cancel"),
        ] {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let address = listener.local_addr().unwrap();
            let server = tokio::spawn(async move {
                let (stream, _) = listener.accept().await.unwrap();
                let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
                let frame = ws.next().await.unwrap().unwrap();
                serde_json::from_str::<Value>(frame.to_text().unwrap()).unwrap()
            });
            let (stream, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
                .await
                .unwrap();
            let mut ws = super::super::transport::test_socket(stream);
            let session = Session {
                api_url: "http://127.0.0.1:1".into(),
                session_id: "synthetic-consent".into(),
                cookies: Default::default(),
                ws_token: None,
                master_key: zeroize::Zeroizing::new([7; 32]),
                hashed_email: "synthetic".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: None,
            };
            let mut client = Client::new("http://127.0.0.1:1", Some(session)).unwrap();
            let (updates, _) = mpsc::channel(1);
            let frames=client.subchat_consent(&mut ws,&json!({"sub_chats":[{"title":"one"},{"title":"two"}],"remaining_sub_chats":remaining}),"chat","task",&updates,&CancellationToken::new(),policy).await.unwrap();
            assert!(frames.is_empty());
            let sent = server.await.unwrap();
            assert_eq!(sent["type"], "sub_chat_confirmation");
            assert_eq!(sent["payload"]["action"], action);
            assert_eq!(sent["payload"]["chat_id"], "chat");
            assert_eq!(sent["payload"]["task_id"], "task");
            if action == "approve" {
                assert_eq!(sent["payload"]["approve_count"], 2);
            }
        }
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "consent_scope_tests.rs"]
mod scope_tests;
