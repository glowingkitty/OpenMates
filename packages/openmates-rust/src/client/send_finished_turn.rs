//! Resend of an already-finished chat turn (spec assertion
//! `chats.message.identity-idempotent`). Shared core, part of the saved-turn
//! send path. The server answers such a resend with `chat_message_confirmed`
//! carrying `turn_already_completed: true` and the original `assistant_message_id`,
//! then `ai_typing_ended`; it never streams again, sends no final frame and may
//! have dropped the recovery job (tombstone expires after 24 h), so no claim is
//! possible. The turn is finished from the canonical chat instead.
use super::turn_runtime::SavedTurnClientPhases;
use super::*;

/// `Some(assistant id)` when `kind`/`p` is the server's "this turn already
/// completed" confirmation for exactly this chat, user message and (when the
/// frame names one) turn; the inner id is `None` when the server no longer knows
/// it (it comes from the recovery job tombstone, which expires after 24 h, so
/// null/absent is the normal case for old resends). Anything else yields the
/// outer `None`, so ordinary confirmations and other turns' frames never
/// short-circuit a send.
pub(in crate::client) fn finished_assistant_id<'a>(
    kind: &str,
    p: &'a Value,
    chat: &str,
    message: &str,
    turn: &str,
) -> Option<Option<&'a str>> {
    if kind != "chat_message_confirmed"
        || p["turn_already_completed"] != true
        || text(p, "chat_id") != chat
        || text(p, "message_id") != message
    {
        return None;
    }
    let frame_turn = text(p, "turn_id");
    if !frame_turn.is_empty() && frame_turn != turn {
        return None;
    }
    Some(Some(text(p, "assistant_message_id")).filter(|id| !id.is_empty()))
}

/// Finish a resent, already-completed turn without a recovery claim: read the
/// canonical chat and deliver `Completed` with the stored assistant content.
///
/// Without an assistant id, the first assistant message after the resent user
/// message in the canonical chat is the reply.
///
/// A canonical chat that lacks the reply (not yet synced to this device, or the
/// read raced a deletion) still completes the send, but delivers no `Completed`
/// update: an empty update could render a blank answer, and the server has
/// confirmed the turn finished, so failing would only show the user a confusing
/// error for a send that succeeded. The outcome then carries the server's
/// assistant id when known (never an invented one) and normal sync delivers the
/// reply.
///
/// # Errors
/// Cancellation, a stale session/generation, or a failed canonical read.
#[allow(clippy::too_many_arguments)]
pub(in crate::client) async fn complete_finished_turn<P: SavedTurnClientPhases>(
    phases: &mut P,
    scope: &AsyncCryptoScope,
    id: &str,
    message: &str,
    assistant_id: Option<&str>,
    generation: u64,
    updates: &mpsc::Sender<StreamUpdate>,
    cancel: &CancellationToken,
    observed: SendObservations,
) -> Result<SendOutcome> {
    let chat = Plain::new(phases.open_chat_live(id).await?);
    let found = match assistant_id {
        Some(wanted) => chat.messages.iter().find(|m| m.id == wanted),
        None => chat
            .messages
            .iter()
            .skip_while(|m| m.id != message)
            .skip(1)
            .find(|m| m.role == "assistant"),
    };
    let reply_id = found
        .map(|m| m.id.clone())
        .or_else(|| assistant_id.map(str::to_owned));
    if let Some(reply) = found {
        let content = Plain::new(reply.content.clone());
        phases
            .deliver_update(
                scope,
                id,
                updates,
                cancel,
                StreamUpdate::Completed {
                    chat_id: id.into(),
                    message_id: reply.id.clone(),
                    content: content.into_inner(),
                },
            )
            .await?;
    }
    phases.check(scope, id, generation).await?;
    Ok(observed.finish(
        chat.into_inner(),
        message,
        reply_id.as_deref(),
        SendStatus::Completed,
    ))
}

#[cfg(test)]
#[path = "send_finished_turn_tests.rs"]
mod tests;
