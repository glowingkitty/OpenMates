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
        let id = chat_id
            .map(str::to_owned)
            .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
        let turn = uuid::Uuid::new_v4().to_string();
        let message = uuid::Uuid::new_v4().to_string();
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
        let mut ws = self.socket_with_task_jobs(options.task_update_jobs).await?;
        if cancel.is_cancelled() {
            let _ = ws.close(None).await;
            return Err(Error::Cancelled);
        }
        let release_scope=AsyncCryptoScope::begin(self)?;release_scope.check_chat(self,&id)?;
        Ok(PreparedTurnTransport{generation,id,turn,message,chat,new_chat,key,wrapped,baseline,existing,team_preparation,ws,release_scope})
    }
}
