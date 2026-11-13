//! Actual outer saved-turn transport/key preparation shared with owned phases.
//! It returns owned resources, never a Client reference or a second Client.
use super::*;
pub(in crate::client) struct PreparedTurnTransport {
    pub(in crate::client) generation:u64,
    pub(in crate::client) id:String,
    pub(in crate::client) turn:String,
    pub(in crate::client) message:String,
    pub(in crate::client) chat:Plain<Chat>,
    pub(in crate::client) new_chat:bool,
    pub(in crate::client) key:Key,
    pub(in crate::client) wrapped:String,
    pub(in crate::client) baseline:u64,
    pub(in crate::client) existing:Plain<Vec<Value>>,
    pub(in crate::client) team_preparation:Plain<Option<Value>>,
    pub(in crate::client) ws:Socket,
    pub(in crate::client) release_scope:AsyncCryptoScope,
}
impl Client {
    pub(in crate::client) async fn prepare_saved_turn_transport(&mut self,chat_id:Option<&str>,text_input:&str,
        options:&SendOptions,cancel:&CancellationToken)->Result<PreparedTurnTransport>{
        self.verify_private_operation()?;
        let generation = self.generation;
        let wrapping = self.wrapping_capability().await?;
        Self::require_turn_slug_index(&wrapping,options.slug.is_some())?;
        // Caller-reserved ids (a new chat's id, the user message id) or fresh ones.
        let (id, message) = self.turn_identity(chat_id, options.reserved_ids.as_ref())?;
        let turn = uuid::Uuid::new_v4().to_string();
        if let Some(observation) = &self.scoped_send_observation {
            let mut observation = observation.lock().map_err(|_| Error::Cancelled)?;
            observation.identity = Some(SavedSendRecoveryIdentity { chat: id.clone(), turn: turn.clone(), message: message.clone() });
        }
        let mut chat = Plain::new(if let Some(id) = chat_id {
            self.open_chat_live(id).await?
        } else {
            Chat {
                id: id.clone(),
                ..Chat::default()
            }
        });
        let details = self.chats.get(&id).cloned();
        let new_chat = details.as_ref().is_none_or(super::sync::draft_only);
        let (key, wrapped) = self.turn_chat_material_with_capability(details.as_ref(), &wrapping).await?;
        let baseline = details
            .as_ref()
            .and_then(|d| d["messages_v"].as_u64())
            .unwrap_or(0);

        let mut existing = Plain::new(vec![]);
        for row in self.history.get(&id).into_iter().flatten() {
            let mappings=Plain::new(decrypt_optional(row,"encrypted_pii_mappings",&key)?);
            if !mappings.is_empty() {
                let mappings: Vec<Value> = serde_json::from_str(&mappings)?;
                existing.extend(mappings)
            }
        }
        let team_preparation = Plain::new(if self.team()?.is_some() {
            Some(self.team_send_preparation(&id).await?)
        } else {
            None
        });
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // Session refresh can rotate a credential. Let it finish and preserve
        // the new token before honoring cancellation of the socket operation.
        // The capability is per socket: only a shell that renders the created
        // Project card opts in, so other clients keep today's behaviour.
        self.extra_socket_capabilities = Vec::new();
        if options.project_create_requests {
            self.extra_socket_capabilities.push(PROJECT_CREATE_CAPABILITY);
        }
        if options.project_file_jobs && PROJECT_FILE_JOBS_AVAILABLE {
            self.extra_socket_capabilities.push(PROJECT_FILE_JOBS_CAPABILITY);
        }
        if options.memory_write_jobs {
            self.extra_socket_capabilities.push(MEMORY_WRITE_JOBS_CAPABILITY);
        }
        let socket = self.socket_with_task_jobs(options.task_update_jobs).await;
        self.extra_socket_capabilities.clear();
        let mut ws = socket?;
        if cancel.is_cancelled() {
            let _ = ws.close(None).await;
            return Err(Error::Cancelled);
        }
        let release_scope=AsyncCryptoScope::begin(self)?;release_scope.check_chat(self,&id)?;
        Ok(PreparedTurnTransport{generation,id,turn,message,chat,new_chat,key,wrapped,baseline,existing,team_preparation,ws,release_scope})
    }
}
