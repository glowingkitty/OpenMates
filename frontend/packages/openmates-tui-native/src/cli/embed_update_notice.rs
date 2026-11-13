//! Chat transcript lines for `embed_updated` system events (spec
//! `feature.embed-user-edits`, assertions `event.chat-notice` and
//! `event.collapse`). The core decides which rows are events and folds runs
//! of one embed (`group_embed_updated_events`); this shell module only words
//! a folded run as one quiet line, for the CLI transcript and the TUI. Other
//! system rows (memory events, Undo markers) take the core's
//! `system_event_line` wording (`feature.app-memories`); chat orchestration
//! events take the core's `chat_orchestration::event_line`
//! (`feature.chat-orchestration`).
use crate::model::Message;
use openmates_sdk::client::chat_orchestration;
use openmates_sdk::client::embed_updated_event::{
    ChatHistoryItem, EmbedKind, EmbedUpdateAction, EmbedUpdateSurface, EmbedUpdatedGroup,
    HistoryRow, group_embed_updated_events,
};
use openmates_sdk::client::system_event_line::{
    SystemEventLine, system_event_line, undone_memory_write_jobs,
};

/// One entry of a rendered chat transcript.
pub(crate) enum TranscriptItem<'a> {
    /// An ordinary message, rendered as before.
    Message(&'a Message),
    /// A folded run of user edits of one embed, or another system event, as
    /// one line.
    Notice(String),
}

/// The transcript of `messages` in history order, with every run of
/// `embed_updated` events replaced by one notice line and every other system
/// row replaced by its core [`system_event_line`] (or dropped when hidden), so
/// a system row never prints as an "Assistant" bubble with raw JSON.
pub(crate) fn transcript_items(messages: &[Message]) -> Vec<TranscriptItem<'_>> {
    let undone = undone_memory_write_jobs(
        messages
            .iter()
            .filter(|message| message.role == "system")
            .map(|message| message.content.as_str()),
    );
    let rows: Vec<HistoryRow<'_>> = messages
        .iter()
        .map(|message| HistoryRow {
            message_id: &message.id,
            role: &message.role,
            content: &message.content,
        })
        .collect();
    group_embed_updated_events(&rows)
        .into_iter()
        .filter_map(|item| match item {
            ChatHistoryItem::Message { index } => {
                let message = messages.get(index)?;
                if message.role != "system" {
                    return Some(TranscriptItem::Message(message));
                }
                if let Some(event) = chat_orchestration::parse_event(&message.content) {
                    return Some(TranscriptItem::Notice(chat_orchestration::event_line(
                        &event, None,
                    )));
                }
                match system_event_line(&message.content, &undone) {
                    SystemEventLine::Hidden => None,
                    SystemEventLine::Line(line) => Some(TranscriptItem::Notice(line)),
                }
            }
            ChatHistoryItem::EmbedUpdated(group) => {
                Some(TranscriptItem::Notice(notice_line(&group)))
            }
        })
        .collect()
}

fn kind_label(kind: EmbedKind) -> &'static str {
    match kind {
        EmbedKind::Image => "Image",
        EmbedKind::Diagram => "Diagram",
        EmbedKind::Slides => "Slides",
        EmbedKind::Sheet => "Sheet",
        EmbedKind::Document => "Document",
    }
}

/// "Image updated · version 3 (enhanced)"; a run of several edits reads
/// "Image updated, 3 changes · version 5 (enhanced)", naming the newest one.
pub(crate) fn notice_line(group: &EmbedUpdatedGroup) -> String {
    let mut line = format!("{} updated", kind_label(group.embed_kind));
    if group.change_count > 1 {
        line.push_str(&format!(", {} changes", group.change_count));
    }
    line.push_str(&format!(" · version {}", group.latest_version));
    let action = match (group.latest_action, group.restored_from) {
        (EmbedUpdateAction::Enhance, _) => "enhanced".to_owned(),
        (EmbedUpdateAction::Restore, Some(from)) => format!("restored version {from}"),
        (EmbedUpdateAction::Restore, None) => "restored".to_owned(),
        (EmbedUpdateAction::Crop, _) => "cropped".to_owned(),
        (EmbedUpdateAction::Edit, _) => "edited".to_owned(),
    };
    let place = match group.surface {
        EmbedUpdateSurface::Project => " in a Project",
        EmbedUpdateSurface::Chat => "",
    };
    line.push_str(&format!(" ({action}{place})"));
    line
}

/// The core's chat-open reconcile for a one-shot `chats show`: writes the
/// chat events of edits made elsewhere (Projects, other devices). True when
/// it wrote any, so the caller reads the window again to show them. Offline,
/// Team and refused reads are deferred by the core and leave the output alone.
///
/// # Errors
/// `Cancelled` and `Expired` from the core.
pub(crate) async fn reconcile_on_open(
    client: &mut crate::client::Client,
    chat_id: &str,
) -> Result<bool, crate::error::Error> {
    let report = client
        .reconcile_embed_update_notices_on_open(chat_id)
        .await?;
    Ok(report.written > 0)
}

/// `chats show` (bounded page): after the reconcile wrote events, the page
/// read again with them; `None` when nothing was written.
///
/// # Errors
/// The reconcile's and the read's errors.
async fn bounded_read_after_reconcile(
    client: &mut crate::client::Client,
    selector: &str,
    chat_id: &str,
) -> Result<Option<openmates_sdk::client::saved_chat_read::SavedChatRead>, crate::error::Error> {
    if !reconcile_on_open(client, chat_id).await? {
        return Ok(None);
    }
    use openmates_sdk::client::saved_chat_read::{SavedChatContentMode, SavedChatReadOptions};
    // Same bounded viewing page as the first read in `chats show`.
    let read = client
        .saved_chat_read(
            selector,
            SavedChatReadOptions {
                limit: 30,
                max_pages: 1,
                content_mode: SavedChatContentMode::Stored,
                ..Default::default()
            },
        )
        .await?;
    Ok(Some(read))
}

/// `chats show --all` / `chats messages`: the opened chat, opened again when
/// the reconcile wrote events so they are part of the output.
///
/// # Errors
/// The reconcile's and the open's errors.
async fn chat_after_reconcile(
    client: &mut crate::client::Client,
    chat: crate::model::Chat,
) -> Result<crate::model::Chat, crate::error::Error> {
    if reconcile_on_open(client, &chat.id).await? {
        return client.open_chat(&chat.id).await;
    }
    Ok(chat)
}

type BoxedRead<'a, T> = std::pin::Pin<
    Box<dyn std::future::Future<Output = Result<T, crate::error::Error>> + Send + 'a>,
>;

/// [`bounded_read_after_reconcile`] boxed in its own frame, so the `chats
/// show` dispatcher's poll frame does not grow.
#[inline(never)]
pub(crate) fn bounded_read_after_reconcile_boxed<'a>(
    client: &'a mut crate::client::Client,
    selector: &'a str,
    chat_id: &'a str,
) -> BoxedRead<'a, Option<openmates_sdk::client::saved_chat_read::SavedChatRead>> {
    Box::pin(bounded_read_after_reconcile(client, selector, chat_id))
}

/// [`chat_after_reconcile`] boxed in its own frame (see above).
#[inline(never)]
pub(crate) fn chat_after_reconcile_boxed(
    client: &mut crate::client::Client,
    chat: crate::model::Chat,
) -> BoxedRead<'_, crate::model::Chat> {
    Box::pin(chat_after_reconcile(client, chat))
}

#[cfg(test)]
#[path = "embed_update_notice_tests.rs"]
mod tests;
