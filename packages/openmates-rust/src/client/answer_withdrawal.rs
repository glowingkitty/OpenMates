//! Withdrawn assistant answers: the server's `assistant_answer_withdrawn` event
//! replaces an answer with a localized notice. The notice supersedes the answer
//! text for display and for the encrypted assistant message persisted at turn
//! completion, and wins over any later streamed chunk of the same message.

use super::*;

/// Event kind the server sends after its postprocessing answer check.
pub(super) const EVENT_KIND: &str = "assistant_answer_withdrawn";
const MAX_NOTICE_CHARS: usize = 4000;

/// Notice observed for the current turn, keyed by the withdrawn message id.
#[derive(Default)]
pub(super) struct Withdrawal {
    notice: Option<(String, String)>,
}

impl Withdrawal {
    /// Records a withdrawal event. Events for another chat or task are ignored
    /// (`Ok(false)`); a malformed event for this turn is refused.
    ///
    /// # Errors
    /// `Error::Protocol` when `message_id`, `reason` or `notice_text` is missing
    /// or the notice is oversized.
    pub(super) fn observe(&mut self, event: &Value, chat: &str, task: &str) -> Result<bool> {
        if text(event, "chat_id") != chat {
            return Ok(false);
        }
        let event_task = text(event, "task_id");
        if !event_task.is_empty() && !task.is_empty() && event_task != task {
            return Ok(false);
        }
        let notice = text(event, "notice_text");
        if text(event, "message_id").is_empty()
            || text(event, "reason").is_empty()
            || notice.is_empty()
            || notice.chars().count() > MAX_NOTICE_CHARS
        {
            return Err(Error::Protocol);
        }
        self.notice = Some((text(event, "message_id").into(), notice.into()));
        Ok(true)
    }

    /// Notice that replaces `message_id`'s content, if that message was withdrawn.
    pub(super) fn notice_for(&self, message_id: &str) -> Option<&str> {
        self.notice
            .as_ref()
            .filter(|(id, _)| id == message_id)
            .map(|(_, notice)| notice.as_str())
    }

    /// Whether a streamed chunk of `message_id` must be dropped. Chunks that do
    /// not name their message are dropped too once a withdrawal is known, since
    /// the turn has a single assistant message.
    pub(super) fn suppresses(&self, message_id: &str) -> bool {
        self.notice
            .as_ref()
            .is_some_and(|(id, _)| message_id.is_empty() || id == message_id)
    }

    /// Notice shown while streaming, before the final frame names the message.
    pub(super) fn current_notice(&self) -> Option<&str> {
        self.notice.as_ref().map(|(_, notice)| notice.as_str())
    }
}

impl Client {
    /// Replaces an already persisted assistant message with the withdrawal
    /// notice: seals `notice` with the chat key, asks the server to store it as
    /// that message's content (`replace_withdrawn_assistant_message`, accepted
    /// only for a message the server itself withdrew) and, once acknowledged,
    /// updates the cached history row. Other devices get the change through the
    /// server's `assistant_message_replaced` broadcast.
    ///
    /// # Errors
    /// As the message actions (`Invalid`, `Forbidden`), `Offline` when the chat
    /// is not loaded or the server does not answer, `Protocol` for a refusal.
    pub async fn replace_withdrawn_message(
        &mut self,
        chat_id: &str,
        message_id: &str,
        notice: &str,
    ) -> Result<()> {
        self.check_message_action(chat_id)?;
        if message_id.is_empty() || notice.is_empty() || notice.chars().count() > MAX_NOTICE_CHARS {
            return Err(Error::Protocol);
        }
        let row = self.chats.get(chat_id).cloned().ok_or(Error::Offline)?;
        let wrapping = self.wrapping_capability().await?;
        let key = self.chat_key_with_capability(&row, &wrapping).await?;
        let sealed = crypto::encrypt_combined(notice, &key)?;
        let cancel = self.operation_cancel.clone();
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let mut ws = self.socket_with_task_jobs(false).await?;
        let result = super::message_actions::acknowledged(&cancel, async {
            super::transport::send(
                &mut ws,
                "replace_withdrawn_assistant_message",
                json!({"chat_id": chat_id, "message_id": message_id, "encrypted_content": sealed}),
            )
            .await?;
            super::transport::wait(
                &mut ws,
                "assistant_message_replaced",
                "message_id",
                message_id,
            )
            .await
        })
        .await;
        let _ = ws.close(None).await;
        result?;
        self.replace_history_content(chat_id, message_id, &sealed);
        Ok(())
    }

    /// Stores `sealed` as the content of the cached history row `message_id`;
    /// false when the row is not cached.
    pub(super) fn replace_history_content(
        &mut self,
        chat_id: &str,
        message_id: &str,
        sealed: &str,
    ) -> bool {
        let Some(row) = self.history.get_mut(chat_id).and_then(|rows| {
            rows.iter_mut()
                .find(|r| r["message_id"] == message_id || r["client_message_id"] == message_id)
        }) else {
            return false;
        };
        row["encrypted_content"] = json!(sealed);
        true
    }

    /// Applies an `assistant_answer_withdrawn` event for a chat this client has
    /// loaded: replaces the stored message with the notice (see
    /// [`Client::replace_withdrawn_message`]). `Some(chat)` when state changed;
    /// a chat the client does not hold is left to a device that has it.
    pub(super) async fn apply_withdrawal_event(
        &mut self,
        chat_id: &str,
        event: &Value,
    ) -> Result<Option<String>> {
        if !self.chats.contains_key(chat_id) {
            return Ok(None);
        }
        let mut withdrawal = Withdrawal::default();
        if !withdrawal.observe(event, chat_id, "")? {
            return Ok(None);
        }
        let message = text(event, "message_id");
        let Some(notice) = withdrawal.notice_for(message) else {
            return Ok(None);
        };
        self.replace_withdrawn_message(chat_id, message, notice)
            .await?;
        Ok(Some(chat_id.to_owned()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn event(chat: &str, message: &str, notice: &str) -> Value {
        json!({"chat_id":chat,"task_id":"task","message_id":message,"reason":"wellbeing","notice_text":notice})
    }

    #[test]
    fn valid_event_replaces_and_wins_over_later_chunks() {
        let mut w = Withdrawal::default();
        assert!(
            w.observe(&event("chat", "m1", "Withdrawn."), "chat", "task")
                .unwrap()
        );
        assert_eq!(w.notice_for("m1"), Some("Withdrawn."));
        assert_eq!(w.current_notice(), Some("Withdrawn."));
        assert!(w.suppresses("m1"));
        assert!(w.suppresses(""));
        assert!(!w.suppresses("other"));
    }

    #[test]
    fn foreign_chat_or_task_is_ignored_and_unknown_message_is_not_replaced() {
        let mut w = Withdrawal::default();
        assert!(
            !w.observe(&event("other", "m1", "x"), "chat", "task")
                .unwrap()
        );
        let mut foreign_task = event("chat", "m1", "x");
        foreign_task["task_id"] = json!("other-task");
        assert!(!w.observe(&foreign_task, "chat", "task").unwrap());
        assert!(w.current_notice().is_none());
        assert!(!w.suppresses("m1"));
        assert!(
            w.observe(&event("chat", "m1", "x"), "chat", "task")
                .unwrap()
        );
        assert_eq!(w.notice_for("unknown"), None);
    }

    #[test]
    fn malformed_event_is_refused() {
        let mut w = Withdrawal::default();
        for bad in [
            event("chat", "", "x"),
            event("chat", "m1", ""),
            event("chat", "m1", &"x".repeat(MAX_NOTICE_CHARS + 1)),
            json!({"chat_id":"chat","message_id":"m1","notice_text":"x"}),
        ] {
            assert!(matches!(
                w.observe(&bad, "chat", "task"),
                Err(Error::Protocol)
            ));
        }
    }
}
