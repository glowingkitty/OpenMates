//! Sans-IO stages of one turn preparation, shared by the socket path
//! (`prepare_turn_on_socket`) and the voice-call split (`voice_turn`).
//! Stage order is unchanged from the single function: snapshot request and
//! validation, text-independent context (Memories, catalog, documents), then
//! the text-dependent half. None of these stages touches a socket; secret
//! fields live in `Plain` so dropping a context zeroizes it.
use super::prepared_turn::PreparedTurnContext;
use super::*;

/// Text-independent half of a turn: the fresh privacy snapshot and everything
/// derived from it without the user's text. Not Clone/Serialize/Debug; drop wipes.
pub(crate) struct TurnSnapshotContext {
    pub(in crate::client) team: Option<String>,
    pub(in crate::client) snapshot: Plain<Value>,
    pub(in crate::client) projects: Plain<Vec<Value>>,
    pub(in crate::client) sender: Plain<String>,
    pub(in crate::client) memories: Plain<Vec<Value>>,
    pub(in crate::client) memory_metadata: std::collections::BTreeSet<String>,
    pub(in crate::client) memory_catalog: Plain<Vec<Value>>,
    pub(in crate::client) personal_chars: usize,
}

/// Text-dependent privacy result that the Project bind and admission build on.
pub(in crate::client) struct TurnTextStage {
    pub(in crate::client) prepared: Plain<crate::privacy::PreparedPrivacy>,
    pub(in crate::client) wait_ai: bool,
    pub(in crate::client) created: u64,
}

/// The `personal_send_context_snapshot` request of a personal turn: a fresh
/// request id and the frame payload (purpose "send", bound to `turn`).
pub(in crate::client) fn personal_snapshot_request(turn: &str) -> (String, Value) {
    let request_id = uuid::Uuid::new_v4().to_string();
    let frame = json!({"request_id":request_id,"purpose":"send","turn_id":turn});
    (request_id, frame)
}

/// Validate a `personal_send_context_snapshot_result` payload: it must be a
/// changed, successful snapshot for this turn carrying a one-use receipt.
///
/// # Errors
/// `Error::Protocol` for any mismatch; the payload is wiped on rejection.
pub(in crate::client) fn accept_personal_snapshot(
    turn: &str,
    result: Value,
) -> Result<Plain<Value>> {
    let snapshot = Plain::new(result);
    if snapshot["success"] != true
        || snapshot["unchanged"] != false
        || text(&snapshot, "turn_id") != turn
    {
        return Err(Error::Protocol);
    }
    required(&snapshot, "receipt_id")?;
    Ok(snapshot)
}

impl Client {
    /// Decode Project candidates and Memories/settings/documents of a validated
    /// snapshot (or Team preparation) without the user's text.
    pub(in crate::client) async fn turn_snapshot_context(
        &self,
        id: &str,
        team: Option<String>,
        snapshot: Plain<Value>,
        turn_scope: &AsyncCryptoScope,
    ) -> Result<TurnSnapshotContext> {
        let (projects, sender) = if team.is_some() {
            let projects = Plain::new(
                snapshot["project_candidates"]
                    .as_array()
                    .ok_or(Error::Protocol)?
                    .clone(),
            );
            let sender = Plain::new(required(&snapshot, "sender_name")?.to_owned());
            (projects, sender)
        } else {
            let projects = Plain::new(
                self.decode_project_candidates(
                    snapshot["project_candidates"]
                        .as_array()
                        .ok_or(Error::Protocol)?,
                )
                .await?,
            );
            (projects, Plain::new(String::from("User")))
        };
        let master = self.master_capability()?;
        turn_scope.check_chat(self, id)?;
        let memory_snapshot = &snapshot["personal_memories"];
        let mut memories = Plain::new(vec![]);
        let mut memory_metadata = std::collections::BTreeSet::new();
        for raw in memory_snapshot["memories"]
            .as_array()
            .ok_or(Error::Protocol)?
        {
            let plain = Plain::new(
                master
                    .decrypt_text(required(raw, "encrypted_item_json")?)
                    .await?,
            );
            turn_scope.check_chat(self, id)?;
            let data = Plain::new(serde_json::from_str::<Value>(&plain)?);
            if !data.is_object() {
                return Err(Error::Protocol);
            }
            memory_metadata.insert(format!(
                "{}-{}",
                required(raw, "app_id")?,
                required(raw, "item_type")?
            ));
            memories.push(json!({"id":raw["id"],"app_id":raw["app_id"],"item_type":raw["item_type"],"data":&*data}));
        }
        let settings = Plain::new(
            self.decrypt_optional_with_capability(memory_snapshot, "encrypted_settings", &master)
                .await?,
        );
        turn_scope.check_chat(self, id)?;
        // Metadata-only personal Memory catalog from the same fresh snapshot
        // (web `collectMemoryCatalog`): the server can select only these and
        // then asks for their bodies through `request_app_settings_memories`.
        let (personal_catalog, personal_chars) = super::memory_catalog::send_memory_catalog_sized(
            &settings,
            i64::try_from(now_ms()).unwrap_or(i64::MAX),
        );
        let memory_catalog = Plain::new(
            personal_catalog
                .into_iter()
                .map(|entry| json!(entry))
                .collect::<Vec<Value>>(),
        );
        let settings = Plain::new(if settings.is_empty() {
            json!({})
        } else {
            serde_json::from_str::<Value>(&settings)?
        });
        if !settings.is_object() {
            return Err(Error::Protocol);
        }
        let mut docs = Plain::new(BTreeMap::new());
        let mut chars = 0usize;
        for field in ["rule_documents", "memory_documents"] {
            for value in settings[field].as_array().into_iter().flatten() {
                let doc = text(value, "document");
                let doc_id = text(value, "id");
                if !doc_id.is_empty()
                    && doc_id.len() <= 240
                    && doc.len() <= 24_000
                    && (value["source"].is_null() || value["source"] == "personal")
                {
                    if let Some(mut previous) = docs.insert(
                        doc_id.to_owned(),
                        json!({"id":doc_id,"source":"personal","document":doc}),
                    ) {
                        previous.wipe();
                    }
                }
            }
        }
        let mut selected_docs = Plain::new(vec![]);
        for _ in 0..24 {
            let Some((mut doc_id, mut value)) = docs.pop_first() else {
                break;
            };
            doc_id.wipe();
            chars += text(&value, "document").len();
            if chars <= 64_000 {
                selected_docs.push(value);
            } else {
                value.wipe();
            }
        }
        let docs = selected_docs;
        if !docs.is_empty() {
            memory_metadata.insert("openmates-memories".into());
            for doc in docs.iter() {
                memories.push(json!({"id":doc["id"],"app_id":"openmates","item_type":"memories","data":{"document":doc["document"]}}));
            }
        }
        Ok(TurnSnapshotContext {
            team,
            snapshot,
            projects,
            sender,
            memories,
            memory_metadata,
            memory_catalog,
            personal_chars,
        })
    }

    /// Attachments and privacy preparation of the user's text, the AI-wait
    /// decision and the shared creation time. Fences cancel/generation/scope.
    #[allow(clippy::too_many_arguments)] // mirrors the turn inputs of the single original function
    pub(in crate::client) fn turn_text_stage(
        &self,
        ctx: &TurnSnapshotContext,
        id: &str,
        input: &str,
        existing: &[Value],
        options: &SendOptions,
        cancel: &CancellationToken,
        generation: u64,
        turn_scope: &AsyncCryptoScope,
    ) -> Result<TurnTextStage> {
        let team = ctx.team.clone();
        let memories = &ctx.memories;
        // Attachment references join the text before privacy preparation (it
        // never cuts into reference blocks), so the stored message, the
        // inference content and the PII mappings all see the same text.
        let composed = Plain::new(super::send_attachments::content_with_references(
            input,
            &options.embeds,
        ));
        let prepared = Plain::new(super::send_attachments::prepare_turn_privacy(
            &composed, &memories, existing, options,
        )?);
        if cancel.is_cancelled() || self.generation != generation {
            return Err(Error::Cancelled);
        }
        let wait_ai = should_wait_for_ai(&prepared.text, team.as_deref());
        turn_scope.check_chat(self, id)?;
        // One creation time for the stored chat shell and the turn's chat
        // metadata: the server completes an existing empty shell only when
        // every field it already holds matches (`canCompleteChatMetadata`).
        let created = now_ms() / 1000;
        Ok(TurnTextStage {
            prepared,
            wait_ai,
            created,
        })
    }

    /// `chat_has_title` of a turn, as the web sender decides it (`title_v > 0`):
    /// an existing chat whose row says it has no title yet (a call chat before
    /// its first turn) still gets its title generated. A row without `title_v`
    /// keeps the existing-chat meaning.
    pub(in crate::client) fn turn_chat_has_title(&self, id: &str, new_chat: bool) -> bool {
        !new_chat
            && !self
                .chats
                .get(id)
                .is_some_and(|row| row["title_v"].as_u64() == Some(0))
    }

    /// Project context, encrypted user message, inference request and payload
    /// of a turn. `bound_project` is true when the socket path already bound
    /// an explicit Project. Returns the `chat_turn_admit` payload.
    #[allow(clippy::too_many_arguments)] // mirrors the turn inputs of the single original function
    pub(in crate::client) async fn finish_turn_admission(
        &mut self,
        ctx: TurnSnapshotContext,
        stage: TurnTextStage,
        id: &str,
        turn: &str,
        message: &str,
        input: &str,
        key: &[u8; 32],
        wrapped: &str,
        baseline: u64,
        new_chat: bool,
        cancel: &CancellationToken,
        generation: u64,
        options: &SendOptions,
        bound_project: bool,
        turn_scope: &AsyncCryptoScope,
    ) -> Result<(Plain<Value>, PreparedTurnContext)> {
        let TurnSnapshotContext {
            team,
            snapshot,
            projects,
            sender,
            memories,
            memory_metadata,
            mut memory_catalog,
            personal_chars,
        } = ctx;
        let TurnTextStage {
            prepared,
            wait_ai,
            created,
        } = stage;
        let master = self.master_capability()?;
        let has_title = self.turn_chat_has_title(id, new_chat);
        let mut project_context = Plain::new(if (new_chat && !bound_project) || !wait_ai {
            json!({})
        } else {
            self.active_project_context(id, &prepared.text).await?
        });
        // Ask first Project Memories join the personal catalog under its bounds.
        if let Some(Value::Array(project_rows)) = project_context
            .as_object_mut()
            .and_then(|context| context.remove("project_memory_catalog"))
        {
            let merged = super::memory_catalog::merge_project_catalog(
                std::mem::take(&mut *memory_catalog),
                personal_chars,
                project_rows,
            );
            *memory_catalog = merged;
        }
        turn_scope.check_chat(self, id)?;
        let recovery = crypto::recovery_keypair(key, id, 1)?;
        let mut encrypted = json!({"client_message_id":message,"chat_id":id,"encrypted_content":crypto::encrypt_combined(&prepared.text,key)?,"encrypted_sender_name":crypto::encrypt_combined(&sender,key)?,"role":"user","created_at":created,"updated_at":created});
        if !prepared.mappings.is_empty() {
            let encoded = Plain::new(serde_json::to_string(&prepared.mappings)?);
            encrypted["encrypted_pii_mappings"] = json!(crypto::encrypt_combined(&encoded, key)?);
        }
        let mut inference = Plain::new(
            json!({"chat_id":id,"client_capabilities":[],"is_incognito":false,"message":{"message_id":message,"chat_id":id,"role":"user","sender_name":"User","status":"sent","content":prepared.text,"created_at":created,"chat_has_title":has_title},"turn_id":turn,"recovery_public_key":recovery.public_key,"chat_key_version":1,"custom_memory_documents":[],"app_settings_memories_metadata":memory_metadata,"project_focus_candidates":projects.as_slice()}),
        );
        if let Some(call) = &options.voice_call {
            for (name, value) in call.message_fields() {
                inference["message"][name] = value;
            }
        }
        if !memory_catalog.is_empty() {
            inference["memory_catalog"] = Value::Array(std::mem::take(&mut *memory_catalog));
        }
        if options.task_update_jobs {
            inference["client_capabilities"] = json!(["task_update_jobs"]);
        }
        if options.project_create_requests {
            // The server also requires this on the turn request, not only on the socket.
            let capabilities = inference["client_capabilities"]
                .as_array_mut()
                .ok_or(Error::Protocol)?;
            capabilities.push(json!(PROJECT_CREATE_CAPABILITY));
        }
        if options.project_file_jobs && PROJECT_FILE_JOBS_AVAILABLE {
            let capabilities = inference["client_capabilities"]
                .as_array_mut()
                .ok_or(Error::Protocol)?;
            capabilities.push(json!(PROJECT_FILE_JOBS_CAPABILITY));
        }
        if options.memory_write_jobs {
            let capabilities = inference["client_capabilities"]
                .as_array_mut()
                .ok_or(Error::Protocol)?;
            capabilities.push(json!(MEMORY_WRITE_JOBS_CAPABILITY));
        }
        if let Some(restrictions) = options.server_region.routing_restrictions() {
            inference["model_routing_restrictions"] = restrictions;
        }
        let (active_focus, focus_state) = self.current_focus_state(id, key)?;
        inference["active_focus_id"] = json!(active_focus);
        inference["focus_phase_state"] = focus_state.clone();
        if let Some(context) = project_context.as_object() {
            for (k, v) in context {
                inference[k] = v.clone();
            }
        }
        if new_chat {
            inference["encrypted_chat_key"] = json!(wrapped)
        }
        // Attachments: cleartext copies for the inference cache and the
        // client-encrypted bundle the server stores with the message.
        let cleartext_embeds = Plain::new(super::send_attachments::cleartext_embeds(
            &options.embeds,
            created,
        ));
        if !cleartext_embeds.is_empty() {
            inference["embeds"] = json!(cleartext_embeds.as_slice());
        }
        let encrypted_embeds = if cleartext_embeds.is_empty() {
            vec![]
        } else {
            // The bundle is bound to the owner: the server checks its hash.
            let owner = text(&self.user, "id");
            let owner = if owner.is_empty() {
                required(&self.user, "user_id")?
            } else {
                owner
            }
            .to_owned();
            let scope = super::send_attachments::BundleScope {
                chat_id: id,
                message_id: message,
                user_id: &owner,
                created,
            };
            let bundle =
                super::send_attachments::encrypted_bundle(&options.embeds, &scope, key, &master)
                    .await?;
            turn_scope.check_chat(self, id)?;
            bundle
        };
        if !encrypted_embeds.is_empty() {
            inference["encrypted_embeds"] = Value::Array(encrypted_embeds.clone());
        }
        if let Some(rows) = self.history.get(id) {
            let mut history = Plain::new(vec![]);
            for row in rows {
                let sender = Plain::new(decrypt_optional(row, "encrypted_sender_name", key)?);
                let content = Plain::new(decrypt_optional(row, "encrypted_content", key)?);
                // Presentation-only history events never reach the AI (web:
                // withoutPresentationOnlyEvents); they may carry sealed Undo data.
                if row["role"] == "system"
                    && crate::client::embed_updated_event::is_presentation_only_event(&content)
                {
                    continue;
                }
                history.push(json!({"message_id":row.get("client_message_id").or_else(||row.get("message_id")).or_else(||row.get("id")),"chat_id":id,"role":row["role"],"sender_name":sender.as_str(),"content":content.as_str(),"created_at":row["created_at"]}));
            }
            if !history.is_empty() {
                inference["message_history"] = json!(history.as_slice());
            }
        }
        if let Some(team) = &team {
            inference["team_id"] = json!(team);
            let mut envelope = encrypted.clone();
            envelope["message_id"] = json!(message);
            inference["message"].wipe();
            inference["message"] = envelope;
            let mut prior_value = Plain::new(
                inference
                    .as_object_mut()
                    .ok_or(Error::Protocol)?
                    .remove("message_history"),
            );
            let prior = Plain::new(match prior_value.take() {
                Some(Value::Array(rows)) => rows,
                Some(mut other) => {
                    other.wipe();
                    vec![]
                }
                None => vec![],
            });
            if !wait_ai {
                let replacement = Plain::new(
                    json!({"chat_id":id,"team_id":team,"turn_id":turn,"is_incognito":false,"message":inference["message"],"recovery_public_key":recovery.public_key,"chat_key_version":1}),
                );
                inference.wipe();
                *inference = replacement.into_inner();
                if new_chat {
                    inference["encrypted_chat_key"] = json!(wrapped)
                }
                // A Team message without AI still stores its attachments.
                if !encrypted_embeds.is_empty() {
                    inference["encrypted_embeds"] = Value::Array(encrypted_embeds.clone());
                }
            }
            if wait_ai {
                let mut history = prior;
                history.push(json!({"role":"user","content":prepared.text,"sender_name":sender.as_str(),"created_at":created}));
                inference["team_ai_invocation"] = json!({"history":history.as_slice()});
                inference["message_history"] = json!(history.as_slice());
            }
        }
        let mut payload = Plain::new(
            json!({"protocol_version":1,"chat_id":id,"turn_id":turn,"message_id":message,"chat_key_version":1,"encrypted_chat_key":wrapped,"recovery_public_key":recovery.public_key,"expected_messages_v":baseline,"encrypted_user_message":encrypted}),
        );
        payload["inference_request"] = inference.into_inner();
        if let Some(team) = &team {
            payload["team_id"] = json!(team)
        } else {
            payload["privacy_receipt_id"] = snapshot["receipt_id"].clone();
            payload["privacy_generation"] = snapshot["privacy_generation"].clone();
        }
        if new_chat {
            payload["encrypted_chat_metadata"] = self
                .turn_chat_metadata(
                    id,
                    input,
                    key,
                    wrapped,
                    created,
                    team.as_deref(),
                    wait_ai,
                    options,
                )
                .await?;
            turn_scope.check_chat(self, id)?;
        }
        if cancel.is_cancelled() || self.generation != generation {
            return Err(Error::Cancelled);
        }
        turn_scope.check_chat(self, id)?;
        Ok((
            payload,
            PreparedTurnContext {
                team,
                projects,
                sender,
                memories,
                prepared,
                wait_ai,
                focus_state: Plain::new(focus_state),
            },
        ))
    }
}
