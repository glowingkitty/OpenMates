//! Selected foreground discovery, using existing authenticated socket offers.
//! Deliberately no phased-sync request, global absence proof, TTL receipt or
//! unrelated ciphertext inventory mutation. The strict reader remains separate.
use super::*;

impl Client {
    /// Discover foreground recovery for one exact Chat using the existing
    /// authenticated startup offers. This is not a complete account inventory.
    /// The caller still owns durable recovery checkpoints and save-before-output.
    /// Direct npm/Python exposure/conformance is REQUIRED before SDK release.
    pub async fn completion_recovery_jobs_for_chat(
        &mut self,
        id: &str,
        cancel: &CancellationToken,
    ) -> Result<Vec<CompletionRecoveryJob>> {
        canonical_uuid(id)?;
        let fence = self.recovery_fence(cancel)?;
        let epoch = self.fresh_auth.operation_epoch();
        let mut ws = fence.run(self.completion_recovery_socket()).await?;
        fence.check_client(self)?;
        // Socket validation may legitimately rotate credentials/install the
        // authenticated principal. Capture crypto owner scope after admission;
        // retain the original master/credential RecoveryFence across that IO.
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, id)?;
        let check = |client: &Client| -> Result<()> {
            fence.check_client(client)?;
            scope.check_chat(client, id)?;
            if client.fresh_auth.operation_epoch() != epoch {
                return Err(Error::Cancelled);
            }
            Ok(())
        };
        check(self)?;
        let mut main = BTreeMap::new();
        let mut metadata = BTreeMap::new();
        let mut outputs = BTreeMap::new();
        let mut deliveries = BTreeMap::new();
        let discovery = fence.run(async {
            let mut completed = false;
            let mut metadata_seen = self.team()?.is_some();
            let mut foreground = false;
            let mut metadata_deadline = None;
            for _ in 0..1000 {
                check(self)?;
                let received = if let Some(deadline) = metadata_deadline {
                    match crate::platform::time::timeout_at(deadline, receive_ephemeral(&mut ws)).await {
                        Ok(result) => result?,
                        // Match existing bounded metadata discovery: omission
                        // does not erase work or grant any freshness/absence.
                        Err(_) => break,
                    }
                } else {
                    receive_ephemeral(&mut ws).await?
                };
                check(self)?;
                let (kind, payload) = received;
                if kind == "native_client_lifecycle_ack" {
                    if payload["is_foreground"] != true { return Err(Error::Forbidden); }
                    foreground = true;
                }
                capture(&kind, &payload, &mut main, &mut metadata)?;
                metadata_seen |= kind == "metadata_jobs_available";
                super::super::workflow_delivery::capture(&kind, &payload, &mut deliveries)?;
                if let Some(done) = super::super::recovery::capture(&kind, &payload, &mut outputs)? {
                    completed = done;
                }
                if completed && foreground {
                    if metadata_seen { break; }
                    if metadata_deadline.is_none() {
                        let deadline = Instant::now() + Duration::from_secs(3);
                        crate::platform::time::timeout_at(deadline,
                            send(&mut ws, "metadata_jobs_request", json!({"protocol_version":1})))
                            .await.map_err(|_| Error::Offline)??;
                        check(self)?;
                        metadata_deadline = Some(deadline);
                    }
                }
            }
            if !completed || !foreground { return Err(Error::Protocol); }
            Ok(())
        }).await;
        check(self)?;
        // A failed/incomplete startup transaction never publishes offers. Only
        // independent replay failures AFTER a valid completion may preserve a
        // genuine main job, matching the existing sync publication boundary.
        discovery?;
        // Publish only selected offers. Preserve any prior unrelated in-memory
        // offers and every durable pending record; those need their own turn.
        main.retain(|_, job| job.chat_id == id);
        let personal = self.team()?.is_none();
        metadata.retain(|_, job| personal && job.chat_id == id);
        self.completion_recovery_jobs.retain(|_, job| job.chat_id != id);
        self.metadata_recovery_jobs.retain(|_, job| job.chat_id != id);
        self.completion_recovery_jobs.extend(main.clone());
        self.metadata_recovery_jobs.extend(metadata.clone());
        let selected_main_available = !main.is_empty();
        outputs.retain(|_, output| selected_output(output, id));
        deliveries.retain(|_, delivery| delivery.belongs_to_chat(id));
        let replay = fence.run(async {
            check(self)?;
            self.replay_outputs(&mut ws, &outputs, None).await?;
            check(self)?;
            self.persist_workflow_deliveries(&mut ws, &deliveries).await?;
            check(self)
        }).await;
        let _ = fence.run(async { ws.close(None).await.map_err(|_| Error::Offline) }).await;
        check(self)?;
        match replay {
            Ok(()) => {},
            Err(Error::Offline | Error::Conflict | Error::Protocol) if selected_main_available => {},
            Err(error) => return Err(error),
        }
        Ok(main.into_values().chain(metadata.into_values()).collect())
    }
}
fn selected_output(output: &Value, id: &str) -> bool {
    output["root_chat_id"].as_str() == Some(id)
        || output["target_chat_id"].as_str() == Some(id)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn selected_outputs_include_selected_root_or_target_never_unrelated() {
        let chat = "22222222-2222-4222-8222-222222222222";
        assert!(selected_output(&json!({"root_chat_id":chat,"target_chat_id":"other"}),chat));
        assert!(selected_output(&json!({"root_chat_id":"other","target_chat_id":chat}),chat));
        assert!(!selected_output(&json!({"root_chat_id":"other","target_chat_id":"other"}),chat));
        assert!(!selected_output(&json!({}),chat));
    }
}
