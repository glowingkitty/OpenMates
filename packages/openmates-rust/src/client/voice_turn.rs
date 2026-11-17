//! Socket-free voice-call turn preparation for the web shared Worker. The page
//! sends the frames on its one main socket; the core builds them. A call
//! prepares the text-independent half when speech probably ended and commits
//! the text-dependent half on the final transcript. Wraps the sans-IO stages of
//! `send_turn_stages.rs`, so the payload equals the socket path's.
//! Voice admission requires `turn_id == message_id`, so one id serves both.
use super::turn_stages::{
    TurnSnapshotContext, accept_personal_snapshot, personal_snapshot_request,
};
use super::*;

/// Text-independent half of a voice turn. Holds decrypted private context in
/// zeroizing fields; not Clone, not Serialize, no Debug. Dropping it is the
/// discard: it emits nothing and wipes the context.
pub(in crate::client) struct PreparedVoiceTurn {
    chat_id: String,
    turn_id: String,
    generation: u64,
    context: TurnSnapshotContext,
}

/// Result of committing the final transcript. Nothing has been sent: the page
/// sends `admit` as `chat_turn_admit` and writes `user_message` locally.
pub(in crate::client) struct CommittedVoiceTurn {
    /// Payload of the `chat_turn_admit` frame (wipes on drop).
    pub(in crate::client) admit: Plain<Value>,
    /// The encrypted user message object, for the later local row write.
    pub(in crate::client) user_message: Plain<Value>,
    /// Whether the turn asks for an AI reply.
    pub(in crate::client) wait_ai: bool,
}

impl Client {
    /// The `personal_send_context_snapshot` request (purpose "send") the page
    /// sends for `turn_id`; returns its request id and frame payload.
    pub(in crate::client) fn voice_turn_snapshot_frame(
        &self,
        _chat_id: &str,
        turn_id: &str,
    ) -> (String, Value) {
        personal_snapshot_request(turn_id)
    }

    /// Validate the snapshot result and run the text-independent stage.
    ///
    /// # Errors
    /// `Error::Invalid` for a Team chat (voice calls are personal only);
    /// `Error::Protocol` for a result of another request, turn, or an
    /// unsuccessful/unchanged snapshot; scope errors when the owner changed.
    pub(in crate::client) async fn prepare_voice_turn(
        &self,
        chat_id: &str,
        turn_id: &str,
        request_id: &str,
        snapshot_result: Value,
    ) -> Result<PreparedVoiceTurn> {
        if self.team()?.is_some() {
            return Err(Error::Invalid(
                "Voice calls are only available in personal chats.",
            ));
        }
        let snapshot_result = Plain::new(snapshot_result);
        if text(&snapshot_result, "request_id") != request_id {
            return Err(Error::Protocol);
        }
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, chat_id)?;
        let snapshot = accept_personal_snapshot(turn_id, snapshot_result.into_inner())?;
        let context = self
            .turn_snapshot_context(chat_id, None, snapshot, &scope)
            .await?;
        Ok(PreparedVoiceTurn {
            chat_id: chat_id.into(),
            turn_id: turn_id.into(),
            generation: self.generation,
            context,
        })
    }

    /// `commit_voice_turn` with the chat key, its server wrapper, the messages
    /// version baseline, the new-chat flag and the PII mapping history all
    /// derived from the client's own state exactly as the socket path's
    /// `prepare_saved_turn_transport` does, so no key material crosses a shell
    /// boundary. Sends nothing and needs no socket.
    ///
    /// # Errors
    /// As `commit_voice_turn`, plus key-material errors of the chat.
    pub(in crate::client) async fn commit_voice_turn_from_state(
        &mut self,
        prepared: PreparedVoiceTurn,
        final_text: &str,
        created_at: Option<u64>,
        options: &SendOptions,
    ) -> Result<CommittedVoiceTurn> {
        self.verify_private_operation()?;
        let id = prepared.chat_id.clone();
        // The call bootstrap admits its chat into this client (`admit_chat`:
        // row, key wrapper, messages_v, bounded history) before its first
        // turn is built, so the row is always here. An unknown or keyless row would
        // mint a fresh chat key for an existing chat, so the voice path
        // refuses instead of catching up on its own.
        if !self.has_voice_turn_chat_key(&id) {
            return Err(Error::Unavailable {
                code: "voice_turn_chat_unknown",
                reason: "VOICE_TURN_REQUIRES_STORED_CHAT_KEY",
            });
        }
        let details = self.chats.get(&id).cloned();
        let baseline = details
            .as_ref()
            .and_then(|d| d["messages_v"].as_u64())
            .unwrap_or(0);
        // A chat with messages needs its previous history in the admission
        // (web: `prepareSavedPersonalAdmissionHistory`). Without it the server
        // asks the page for history, which only the legacy path can answer.
        if baseline > 0 && self.history.get(&id).is_none_or(Vec::is_empty) {
            return Err(Error::Unavailable {
                code: "voice_turn_history_missing",
                reason: "VOICE_TURN_REQUIRES_PREVIOUS_HISTORY",
            });
        }
        let wrapping = self.wrapping_capability().await?;
        let new_chat = details.as_ref().is_none_or(super::super::sync::draft_only);
        let (key, wrapped) = self
            .turn_chat_material_with_capability(details.as_ref(), &wrapping)
            .await?;
        let mut existing = Plain::new(vec![]);
        for row in self.history.get(&id).into_iter().flatten() {
            let mappings = Plain::new(decrypt_optional(row, "encrypted_pii_mappings", &key)?);
            if !mappings.is_empty() {
                let mappings: Vec<Value> = serde_json::from_str(&mappings)?;
                existing.extend(mappings)
            }
        }
        self.commit_voice_turn(
            prepared, final_text, created_at, &key, &wrapped, baseline, new_chat, &existing,
            options,
        )
        .await
    }

    /// The committed turn's encrypted user row joins this client's history
    /// (ciphertext only), like the page's optimistic row: the next turn's AI
    /// history must hold it, and the server echoes no row to the sender.
    /// Skipped when the message id is already known.
    fn remember_voice_user_row(&mut self, chat_id: &str, turn_id: &str, user_message: &Value) {
        let rows = self.history.entry(chat_id.to_owned()).or_default();
        if rows
            .iter()
            .any(|row| row["message_id"] == turn_id || row["client_message_id"] == turn_id)
        {
            return;
        }
        let mut row = user_message.clone();
        row["message_id"] = json!(turn_id);
        rows.push(row);
    }

    fn has_voice_turn_chat_key(&self, chat_id: &str) -> bool {
        self.chats
            .get(chat_id)
            .and_then(|row| row["encrypted_chat_key"].as_str())
            .is_some_and(|key| !key.is_empty())
    }

    /// Run the text-dependent stage for the final transcript and build the
    /// `chat_turn_admit` payload without sending anything. The scope is begun
    /// afresh here (no socket is needed to obtain it); the generation captured
    /// at prepare time must still match. `created_at` (seconds) is the time the
    /// page gave its optimistic row; the admitted row carries the same time so
    /// the local and canonical rows agree, as on the TypeScript send path.
    /// `None` stamps the commit time.
    ///
    /// # Errors
    /// `Error::Invalid` when `options.project_id` is set (no Project bind
    /// without a socket) or `options.voice_call` is missing/for another turn;
    /// `Error::Cancelled` when the client generation changed since prepare.
    #[allow(clippy::too_many_arguments)] // mirrors the socket path's turn inputs
    pub(in crate::client) async fn commit_voice_turn(
        &mut self,
        prepared: PreparedVoiceTurn,
        final_text: &str,
        created_at: Option<u64>,
        key: &[u8; 32],
        wrapped: &str,
        baseline: u64,
        new_chat: bool,
        existing: &[Value],
        options: &SendOptions,
    ) -> Result<CommittedVoiceTurn> {
        if options.project_id.is_some() {
            return Err(Error::Invalid("Voice turns cannot bind a Project."));
        }
        match &options.voice_call {
            Some(call) if call.turn_id == prepared.turn_id => {}
            _ => return Err(Error::Invalid("A voice turn needs its voice call fields.")),
        }
        let PreparedVoiceTurn {
            chat_id,
            turn_id,
            generation,
            context,
        } = prepared;
        if self.generation != generation {
            return Err(Error::Cancelled);
        }
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, &chat_id)?;
        let cancel = CancellationToken::new();
        let mut stage = self.turn_text_stage(
            &context, &chat_id, final_text, existing, options, &cancel, generation, &scope,
        )?;
        if let Some(created) = created_at.filter(|created| *created > 0) {
            stage.created = created;
        }
        let (admit, turn) = self
            .finish_turn_admission(
                context, stage, &chat_id, &turn_id, &turn_id, final_text, key, wrapped, baseline,
                new_chat, &cancel, generation, options, false, &scope,
            )
            .await?;
        let user_message = Plain::new(admit["encrypted_user_message"].clone());
        self.remember_voice_user_row(&chat_id, &turn_id, &user_message);
        Ok(CommittedVoiceTurn {
            admit,
            user_message,
            wait_ai: turn.wait_ai,
        })
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "voice_turn_tests.rs"]
mod tests;
