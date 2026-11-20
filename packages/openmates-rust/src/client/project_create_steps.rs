//! Step API of assistant-initiated Project creation for shells that own their
//! WebSocket (the web Worker binding). Shared client core: it runs the same
//! `project_create_report` as the native send loop, keeps the per-chat state
//! bounded and returns the `project_create_result` payload instead of sending
//! it. Spec: `feature.projects` `projects.creation.assistant-inferred`.
use super::*;

/// Chats whose creation state a long-lived Client keeps for its shell.
const MAX_CREATE_CHATS: usize = 16;

/// Per-chat [`ProjectCreateState`] of a long-lived Client, least recently
/// used first. An evicted state is wiped: its records hold decrypted names.
#[derive(Debug, Default)]
pub(in crate::client) struct CreateChats {
    states: BTreeMap<String, ProjectCreateState>,
    order: Vec<String>,
}

impl CreateChats {
    fn take(&mut self, chat: &str) -> ProjectCreateState {
        self.order.retain(|c| c != chat);
        self.states.remove(chat).unwrap_or_default()
    }

    fn put(&mut self, chat: &str, state: ProjectCreateState) {
        while self.order.len() >= MAX_CREATE_CHATS {
            let oldest = self.order.remove(0);
            if let Some(mut evicted) = self.states.remove(&oldest) {
                evicted.wipe();
            }
        }
        self.order.push(chat.to_owned());
        self.states.insert(chat.to_owned(), state);
    }
}

impl Client {
    /// Handle one `project_create_requested`, `project_create_confirmed` or
    /// `project_create_error` frame and return the `project_create_result`
    /// payload the shell must send, if any.
    ///
    /// A cloud request creates the encrypted Project and its default focus
    /// (`created`) or reports `failed` with a code; a duplicate request id
    /// returns `None` (one report per request id). A machine request is
    /// reported `failed`: this entry point has no machine confirmation card,
    /// so nothing is created on a machine without the user's answer.
    ///
    /// # Errors
    /// `Invalid` for a frame without a chat id, `Cancelled`, and `Protocol`
    /// after more than eight distinct requests in one chat.
    pub async fn project_create_step(
        &mut self,
        kind: &str,
        event: &Value,
    ) -> Result<Option<Value>> {
        let chat = event["chat_id"]
            .as_str()
            .filter(|chat| !chat.is_empty())
            .ok_or(Error::Invalid("project create frame without chat id"))?
            .to_owned();
        let mut state = self.create_chats.take(&chat);
        state.machine_decision = Some(MachineProjectDecision::Unavailable);
        let report = self
            .project_create_report(kind, event, &chat, now_ms() / 1000, &mut state)
            .await;
        self.create_chats.put(&chat, state);
        report
    }
}

#[cfg(test)]
#[path = "project_create_steps_tests.rs"]
mod tests;
