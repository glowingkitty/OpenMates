//! Unread chat counters for the terminal UI (`feature.chat-unread@1`).
//!
//! Same rules as the web app: the server counts each finished assistant reply
//! as unread. A chat becomes read only once the last line of its newest reply
//! has been on screen, or when the user answers it (a follow-up implies the
//! reply was read). Opening an unread chat starts at the newest reply instead
//! of the tail, so closing it after reading only the first lines keeps it
//! unread. The counter shows on sidebar rows and "Continue" cards, capped at 9+.
use super::{Item, Ui, UiCommand};
use serde_json::{Value, json};

pub(super) fn unread_count(item: &Item) -> u64 {
    item.fields
        .get("unread_count")
        .and_then(Value::as_u64)
        .unwrap_or(0)
}

/// `"●2 "`-style prefix for list labels; empty when the chat is read.
pub(super) fn badge_prefix(item: &Item) -> String {
    match unread_count(item) {
        0 => String::new(),
        count if count > 9 => "●9+ ".into(),
        count => format!("●{count} "),
    }
}

impl Ui {
    fn chat_unread(&self, id: &str) -> u64 {
        self.items[0]
            .iter()
            .find(|item| item.id == id)
            .map_or(0, unread_count)
    }
    /// Called when a chat opens: unread chats start at the newest reply.
    pub(super) fn arm_unread_anchor(&mut self, chat_id: &str) {
        self.open_at_latest_reply = self.chat_unread(chat_id) > 0;
    }
    /// Clear the counter locally and return the server write, if any.
    pub(super) fn mark_chat_read(&mut self, chat_id: &str) -> Option<UiCommand> {
        let mut changed = false;
        for item in self.items.iter_mut().flatten() {
            if item.id == chat_id && unread_count(item) > 0 {
                item.fields["unread_count"] = json!(0);
                changed = true;
            }
        }
        changed.then(|| UiCommand::MarkRead(chat_id.to_owned()))
    }
    /// Before painting: honour a pending "open at the newest reply" request.
    pub(super) fn apply_unread_anchor(&mut self) {
        if !self.open_at_latest_reply {
            return;
        }
        if let Some((start, _)) = self.latest_reply_rows {
            self.open_at_latest_reply = false;
            self.scroll = start;
            self.follow_tail = false;
        }
    }
    /// After painting: once the newest reply's last row is on screen, mark read.
    pub(super) fn observe_read_position(&mut self, height: usize) {
        // A cached view that is still refreshing is replaced by the canonical
        // read; marking now would persist underneath that in-flight handoff and
        // close the chat. The next paint after the refresh settles marks it.
        if self.visible_chat_streaming() || self.open_at_latest_reply || self.is_cached_chat_refreshing() {
            return;
        }
        let (Some((_, last)), Some(id)) = (
            self.latest_reply_rows,
            self.chat.as_ref().map(|chat| chat.id.clone()),
        ) else {
            return;
        };
        if last < self.scroll + height
            && let Some(command) = self.mark_chat_read(&id)
        {
            self.deferred_commands.push(command);
        }
    }
    /// Commands produced while drawing (read detection). The runtime drains
    /// them after every paint.
    pub fn take_deferred_commands(&mut self) -> Vec<UiCommand> {
        std::mem::take(&mut self.deferred_commands)
    }
}

#[cfg(test)]
#[path = "unread_tests.rs"]
mod tests;
