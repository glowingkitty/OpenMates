//! Original native-session negatives for fixed account settings reads only.
use super::*;
pub(crate) struct SettingsRemindersRead {
    generation: u64,
    parent: CancellationToken,
    child: CancellationToken,
}
impl SettingsRemindersRead {
    pub(crate) fn check(&self, client: &Client) -> Result<()> {
        client.require_session()?;
        if self.generation != client.generation
            || self.parent != client.operation_parent
            || self.child != client.current_operation_child()
            || self.parent.is_cancelled()
            || self.child.is_cancelled()
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    pub(crate) async fn cancelled(&self) {
        tokio::select! { biased; _ = self.parent.cancelled() => {}, _ = self.child.cancelled() => {} }
    }
    pub(crate) fn check_after_response<T>(
        &self,
        client: &Client,
        result: &Result<T>,
    ) -> Result<()> {
        // Authoritative HTTP 401/owner denial can revoke original credentials.
        // Preserve that original failure rather than replacing it with a new
        // session/cancellation error. Successful output still needs all guards.
        if result.is_ok() {
            self.check(client)?;
        }
        Ok(())
    }
}
impl Client {
    pub(crate) fn begin_settings_reminders_read(&self) -> Result<SettingsRemindersRead> {
        self.require_session()?;
        let original = SettingsRemindersRead {
            generation: self.generation,
            parent: self.operation_parent.clone(),
            child: self.current_operation_child(),
        };
        original.check(self)?;
        Ok(original)
    }

    /// One Personal app-settings/memories WebSocket mutation and its receipt
    /// (`store_app_settings_memories_entry` / `delete_app_settings_memories_entry`).
    /// Waits like the legacy CLI: 15 seconds for the matching `entry_id`.
    /// Ciphertext is prepared by the caller; this never decrypts or retries.
    pub(crate) async fn settings_memory_exchange(
        &mut self,
        kind: &str,
        payload: Value,
        reply: &str,
        entry_id: &str,
    ) -> Result<Value> {
        self.require_session()?;
        if self.team()?.is_some() {
            return Err(Error::Unavailable {
                code: "team_memories_unavailable",
                reason: "Team Memories require an explicitly scoped native flow.",
            });
        }
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let mut ws = self.socket_with_task_jobs(false).await?;
        super::transport::send(&mut ws, kind, payload).await?;
        let deadline = crate::platform::time::Instant::now() + std::time::Duration::from_secs(15);
        let receipt = crate::platform::time::timeout_at(
            deadline,
            super::transport::wait(&mut ws, reply, "entry_id", entry_id),
        )
        .await
        .map_err(|_| Error::Offline);
        let _ = ws.close(None).await;
        let receipt = receipt??;
        if receipt.get("success") == Some(&Value::Bool(false)) {
            return Err(Error::Protocol);
        }
        Ok(receipt)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn client() -> Client {
        let origin = "https://never-contact.example.invalid";
        let session = Session {
            api_url: origin.into(),
            session_id: "synthetic-settings-session".into(),
            cookies: BTreeMap::from([("auth_refresh_token".into(), "fixture".into())]),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([0; 32]),
            hashed_email: "synthetic".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 0,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        Client::new(origin, Some(session)).unwrap()
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn original_owner_epoch_refuses_decode_fallback_and_retains_authoritative_errors() {
        let mut client = client();
        let original = client.begin_settings_reminders_read().unwrap();
        client.generation = client.generation.wrapping_add(1);
        // This is the exact successful value produced by malformed/empty JSON.
        assert_eq!(
            original.check_after_response(&client, &Ok(json!({}))),
            Err(Error::Cancelled)
        );
        assert_eq!(
            original.check_after_response(&client, &Err::<Value, _>(Error::Forbidden)),
            Ok(())
        );
        client.forget_session();
        assert_eq!(
            original.check_after_response(&client, &Err::<Value, _>(Error::Expired)),
            Ok(())
        );
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn original_parent_and_child_cannot_be_replaced_by_live_successors() {
        let mut client = client();
        let original = client.begin_settings_reminders_read().unwrap();
        client.operation_cancel = CancellationToken::new();
        assert_eq!(original.check(&client), Err(Error::Cancelled));
        let original = client.begin_settings_reminders_read().unwrap();
        client.operation_parent = CancellationToken::new();
        assert_eq!(original.check(&client), Err(Error::Cancelled));
    }
}
