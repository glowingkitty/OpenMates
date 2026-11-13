//! Caller-reserved identity of one turn: the chat id of a new chat and the
//! client message id of the user message, chosen by a shell before the send so
//! it can route to the new chat, key its optimistic row and journal the turn
//! before any network request (web `chatSyncServiceSenders.ts` and the Apple
//! `ChatSendPipeline` reserve both). Shared core (`client::send`), spec
//! `specifications/features/chats` (`chats.message.identity-idempotent`).
use super::{Client, Error, Result};

/// Ids a shell reserved for its next turn. Both are canonical lowercase
/// hyphenated UUIDs. `chat_id` names a NEW chat and is only accepted when the
/// send has no chat id; `message_id` may accompany a send into an existing
/// chat too. Never serialized: the SDK JSON options do not carry it.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReservedTurnIds {
    /// The new chat's id; `None` lets the core choose one.
    pub chat_id: Option<String>,
    /// The user message's client id; `None` lets the core choose one.
    pub message_id: Option<String>,
}

/// A canonical lowercase hyphenated UUID (the form the core itself mints).
fn canonical_uuid(value: &str) -> bool {
    uuid::Uuid::parse_str(value).is_ok_and(|id| id.hyphenated().to_string() == value)
}

impl ReservedTurnIds {
    /// Check the form of the reserved ids without any client state, so a
    /// shell's malformed id is refused before anything is shown.
    ///
    /// # Errors
    /// `Invalid` for a non-canonical id or a message id equal to the chat id.
    pub fn check_format(&self) -> Result<()> {
        if self
            .chat_id
            .as_deref()
            .is_some_and(|id| !canonical_uuid(id))
        {
            return Err(Error::Invalid("Reserved chat ID must be a canonical UUID."));
        }
        if let Some(id) = &self.message_id
            && (!canonical_uuid(id) || self.chat_id.as_ref() == Some(id))
        {
            return Err(Error::Invalid(
                "Reserved message ID must be a canonical UUID distinct from the chat ID.",
            ));
        }
        Ok(())
    }
}

impl Client {
    /// The chat and user-message ids of a turn into `chat_id` (`None`: a new
    /// chat), taking `reserved` ids where given and minting the rest.
    ///
    /// Idempotency invariant: a reserved id never aliases existing state. A
    /// reserved new-chat id that is already a known (saved, draft-only or
    /// volatile) chat, or a reserved message id already in that chat's
    /// history, is refused, so a shell's retry of a committed turn can never
    /// overwrite it under the same id.
    ///
    /// # Errors
    /// `Invalid` for a non-canonical id, a reserved chat id together with
    /// `chat_id`, or a message id equal to the chat id; `Conflict` when a
    /// reserved id already exists.
    pub(in crate::client) fn turn_identity(
        &self,
        chat_id: Option<&str>,
        reserved: Option<&ReservedTurnIds>,
    ) -> Result<(String, String)> {
        let reserved = reserved.cloned().unwrap_or_default();
        reserved.check_format()?;
        let chat = match (chat_id, reserved.chat_id) {
            (Some(_), Some(_)) => {
                return Err(Error::Invalid(
                    "A reserved chat ID applies only to a new chat.",
                ));
            }
            (Some(id), None) => id.to_owned(),
            (None, Some(id)) => {
                if self.chats.contains_key(&id) || self.is_ephemeral_chat(&id) {
                    return Err(Error::Conflict);
                }
                id
            }
            (None, None) => uuid::Uuid::new_v4().to_string(),
        };
        let message = match reserved.message_id {
            Some(id) => {
                if !canonical_uuid(&id) || id == chat {
                    return Err(Error::Invalid(
                        "Reserved message ID must be a canonical UUID distinct from the chat ID.",
                    ));
                }
                if self.history_has_message(&chat, &id) {
                    return Err(Error::Conflict);
                }
                id
            }
            None => uuid::Uuid::new_v4().to_string(),
        };
        Ok((chat, message))
    }

    /// Whether `chat`'s cached history already holds message `id` (by client
    /// or server message id).
    fn history_has_message(&self, chat: &str, id: &str) -> bool {
        self.history.get(chat).into_iter().flatten().any(|row| {
            ["client_message_id", "message_id", "id"]
                .iter()
                .any(|field| row.get(*field).and_then(|value| value.as_str()) == Some(id))
        })
    }
}

#[cfg(test)]
#[path = "send_reserved_ids_tests.rs"]
mod tests;
