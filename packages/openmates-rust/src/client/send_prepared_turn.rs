//! Actual original turn preparation shared by compatibility and owned drivers.
//! The resource owns prepared private context; it is not serializable, cloneable,
//! a read grant, or a replacement Client. The caller retains the actual scope.
use super::*;
pub(in crate::client) struct PreparedTurnContext {
    pub(in crate::client) team: Option<String>,
    pub(in crate::client) projects: Plain<Vec<Value>>,
    pub(in crate::client) sender: Plain<String>,
    pub(in crate::client) memories: Plain<Vec<Value>>,
    pub(in crate::client) prepared: Plain<crate::privacy::PreparedPrivacy>,
    pub(in crate::client) wait_ai: bool,
    pub(in crate::client) focus_state: Plain<Value>,
}
impl Client {
    #[allow(clippy::too_many_arguments)]
    pub(in crate::client) async fn prepare_turn_on_socket(
        &mut self,
        ws: &mut Socket,
        id: &str,
        turn: &str,
        message: &str,
        input: &str,
        key: &[u8; 32],
        wrapped: &str,
        baseline: u64,
        new_chat: bool,
        existing: &[Value],
        chat: &Chat,
        updates: &mpsc::Sender<StreamUpdate>,
        cancel: &CancellationToken,
        generation: u64,
        team_preparation: Option<Value>,
        options: &SendOptions,
        turn_scope: &AsyncCryptoScope,
    ) -> Result<PreparedTurnContext> {
        self.active_chat = Some(id.into());
        send(ws, "set_active_chat", json!({"chat_id":id})).await?;
        turn_scope.check_chat(self, id)?;
        // A fresh owner-only snapshot and one-use receipt are bound to this same
        // socket/turn. Cached privacy data cannot authorize inference.
        let team = self.team()?.map(str::to_owned);
        let snapshot = if team.is_some() {
            Plain::new(team_preparation.ok_or(Error::Protocol)?)
        } else {
            let (request_id, frame) = super::turn_stages::personal_snapshot_request(turn);
            send(ws, "personal_send_context_snapshot", frame).await?;
            let result = tokio::select! {biased;_=cancel.cancelled()=>return Err(Error::Cancelled),r=wait(ws,"personal_send_context_snapshot_result","request_id",&request_id)=>r?};
            super::turn_stages::accept_personal_snapshot(turn, result)?
        };
        let ctx = self
            .turn_snapshot_context(id, team.clone(), snapshot, turn_scope)
            .await?;
        let stage = self.turn_text_stage(
            &ctx, id, input, existing, options, cancel, generation, turn_scope,
        )?;
        let (wait_ai, created) = (stage.wait_ai, stage.created);
        // An explicit Project (`--project`) is bound before context collection,
        // so a new chat's first turn already carries that Project's context.
        let bound_project = match &options.project_id {
            Some(project) if wait_ai => {
                self.bind_project_for_send(
                    ws,
                    id,
                    project,
                    new_chat,
                    wrapped,
                    created,
                    team.as_deref(),
                    cancel,
                )
                .await?;
                turn_scope.check_chat(self, id)?;
                true
            }
            _ => false,
        };
        let (payload, prepared_turn) = self
            .finish_turn_admission(
                ctx,
                stage,
                id,
                turn,
                message,
                input,
                key,
                wrapped,
                baseline,
                new_chat,
                cancel,
                generation,
                options,
                bound_project,
                turn_scope,
            )
            .await?;
        if let Some(observation) = &self.scoped_send_observation {
            let remaining = MAX_SCOPED_SAVED_SEND_QUARANTINE_BYTES
                .checked_sub(self.scoped_send_quarantine_bytes)
                .ok_or(Error::Conflict)?;
            let bytes = scoped_admission_size(&payload, remaining)?;
            let mut observation = observation.lock().map_err(|_| Error::Cancelled)?;
            observation.admission_bytes = bytes;
            observation.admission = Some(Plain::new((*payload).clone()));
            // Team preview is already an original remote saved effect.
            if team.is_some() {
                observation.attempted = true;
            }
        }
        if team.is_some() {
            self.stage_team_preview(
                ws,
                id,
                message,
                &prepared_turn.prepared.text,
                Some(&chat.title),
            )
            .await?;
        }
        // Bind the UI before dispatch. Once submission starts, an interrupted
        // transport has an ambiguous commit outcome and must not trigger resend.
        self.deliver_turn_update(
            &turn_scope,
            id,
            updates,
            cancel,
            StreamUpdate::Started {
                chat_id: id.into(),
                message_id: message.into(),
                expects_reply: wait_ai,
            },
        )
        .await?;
        self.deliver_turn_update(
            &turn_scope,
            id,
            updates,
            cancel,
            StreamUpdate::Submitted {
                chat_id: id.into(),
                message_id: message.into(),
            },
        )
        .await?;
        // UI delivery can await a bounded host queue. Recheck the same
        // turn/owner generation and cancellation fence after that suspension,
        // before admission can cause a saved message or inference effect.
        if cancel.is_cancelled() || self.generation != generation {
            return Err(Error::Cancelled);
        }
        turn_scope.check_chat(self, id)?;
        // Mark before the transport await: a failed write is an uncertain
        // original attempt, never proof that a new turn may be replayed.
        if let Some(observation) = &self.scoped_send_observation {
            observation.lock().map_err(|_| Error::Cancelled)?.attempted = true;
        }
        transport::send_plaintext(ws, "chat_turn_admit", payload.into_inner()).await?;
        Ok(prepared_turn)
    }
}
