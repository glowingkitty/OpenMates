//! Request attribution for text submitted while another terminal reply is active.
use super::{
    ActiveTurn, Chat, Delivery, Message, SendQueueMode, StreamUpdate, Ui, UiCommand, markdown,
};
use openmates_sdk::view_model::{ChatWindowRecord, MessageRole, RequestId};
use zeroize::Zeroizing;

pub(super) struct FollowupTurn {
    pub(super) chat_id: String,
    pub(super) text: Zeroizing<String>,
    delivery: Delivery,
    active: Option<ActiveTurn>,
    failed: bool,
}

impl FollowupTurn {
    pub(super) fn is_pending(&self) -> bool {
        !self.failed
    }

    pub(super) fn is_streaming(&self) -> bool {
        self.is_pending() && self.active.as_ref().is_some_and(|turn| turn.expects_reply)
    }

    pub(super) fn has_submission(&self) -> bool {
        !matches!(self.delivery, Delivery::Staged)
    }
}

impl Ui {
    pub fn is_streaming_chat(&self, chat_id: Option<&str>) -> bool {
        chat_id.is_some_and(|id| {
            (self.streaming
                && self
                    .active_turn
                    .as_ref()
                    .is_some_and(|turn| turn.chat_id == id))
                || self
                    .followups
                    .values()
                    .any(|turn| turn.chat_id == id && turn.is_streaming())
        })
    }

    pub fn register_send(
        &mut self,
        request: RequestId,
        chat_id: Option<&str>,
        text: &str,
        followup: bool,
    ) {
        if let Some(chat_id) = chat_id.filter(|_| followup) {
            self.overlapping_chat = Some(chat_id.to_owned());
            self.followups.insert(
                request,
                FollowupTurn {
                    chat_id: chat_id.to_owned(),
                    text: Zeroizing::new(text.to_owned()),
                    delivery: Delivery::Staged,
                    active: None,
                    failed: false,
                },
            );
        } else {
            self.send_request = Some(request);
        }
    }

    pub fn stream_for(&mut self, request: RequestId, update: StreamUpdate, visible: bool) {
        if self.send_request == Some(request) {
            if visible {
                self.stream(update);
            } else {
                self.background_stream(update);
            }
            return;
        }
        let Some(followup) = self
            .followups
            .get_mut(&request)
            .filter(|turn| turn.is_pending())
        else {
            return;
        };
        let chat = self
            .chat
            .as_mut()
            .filter(|chat| visible && chat.id == followup.chat_id);
        self.chat_layout = None;
        match update {
            StreamUpdate::Started {
                chat_id,
                message_id,
                expects_reply,
            } if chat_id == followup.chat_id => {
                if followup.active.is_none() {
                    if let Some(chat) = chat
                        && !chat.messages.iter().any(|message| message.id == message_id)
                    {
                        chat.messages.push(Message {
                            id: message_id.clone(),
                            role: "user".into(),
                            content: followup.text.to_string(),
                            ..Default::default()
                        });
                    }
                    followup.active = Some(ActiveTurn {
                        chat_id,
                        user_id: message_id,
                        assistant: None,
                        task_id: None,
                        expects_reply,
                    });
                }
            }
            StreamUpdate::Submitted {
                chat_id,
                message_id,
            } if followup
                .active
                .as_ref()
                .is_some_and(|turn| turn.chat_id == chat_id && turn.user_id == message_id) =>
            {
                followup.delivery = Delivery::Submitted {
                    chat_id,
                    message_id,
                };
            }
            StreamUpdate::Admitted {
                chat_id,
                message_id,
            } if matches!(&followup.delivery, Delivery::Submitted { chat_id: id, message_id: user } if id == &chat_id && user == &message_id) =>
            {
                followup.delivery = Delivery::Admitted {
                    chat_id,
                    message_id,
                };
            }
            StreamUpdate::TaskAssigned {
                chat_id,
                message_id,
                task_id,
            } => {
                if let Some(turn) = followup.active.as_mut() {
                    turn.assign_task(&chat_id, &message_id, task_id);
                }
            }
            StreamUpdate::Content {
                content,
                thinking,
                mate,
            } => {
                if let (Some(chat), Some(turn)) = (chat, followup.active.as_mut()) {
                    turn.update_content(chat, content, thinking, mate);
                }
            }
            StreamUpdate::Completed {
                chat_id,
                message_id,
                content,
            } if chat_id == followup.chat_id => {
                if let (Some(chat), Some(turn)) = (chat, followup.active.as_ref()) {
                    if let Some(status) = turn.complete(chat, message_id, content) {
                        self.status = status.into();
                    }
                }
                followup.active = None;
            }
            StreamUpdate::Consent { request_id, items } => {
                let context = (!visible).then(|| {
                    self.items[0]
                        .iter()
                        .find(|item| item.id == followup.chat_id)
                        .map(|item| item.title.clone())
                        .unwrap_or_else(|| "Background chat".into())
                });
                self.stream(StreamUpdate::Consent { request_id, items });
                if let (Some(form), Some(context)) = (self.form.as_mut(), context) {
                    form.context = Some(context);
                }
            }
            StreamUpdate::Status(status) if chat.is_some() => self.set_status(&status),
            _ => {}
        }
    }

    pub fn send_queued(
        &mut self,
        request: RequestId,
        chat_id: &str,
        message_id: Option<&str>,
        mode: Option<SendQueueMode>,
    ) {
        if self.send_request == Some(request) {
            self.send_succeeded();
            self.send_request = None;
        } else if self.followups.remove(&request).is_none() {
            return;
        }
        let mode = mode.unwrap_or(SendQueueMode::FollowUp);
        if let Some(id) = message_id {
            self.queued_ids.insert(id.to_owned(), mode);
        }
        self.chat_layout = None;
        if self.chat.as_ref().is_some_and(|chat| chat.id == chat_id) {
            self.status = match mode {
                SendQueueMode::FollowUp => "Queued · it runs after the current reply",
                SendQueueMode::Steer => "Correction queued for the active work",
            }
            .into();
        }
        self.finish_overlap();
    }

    pub fn send_finished(
        &mut self,
        request: RequestId,
        chat: Chat,
        visible: bool,
        message_ids: &[Option<String>; 2],
    ) {
        let primary = self.send_request == Some(request);
        if primary {
            self.send_succeeded();
            self.send_request = None;
        } else if self.followups.remove(&request).is_none() {
            return;
        }
        if visible {
            if self.overlapping_chat.as_deref() == Some(chat.id.as_str()) {
                if let Some(current) = self.chat.as_mut().filter(|current| current.id == chat.id) {
                    // This receipt describes one send. Retain optimistic rows
                    // and replies of other sends even when absent from it.
                    for message in chat.messages {
                        if let Some(existing) =
                            current.messages.iter_mut().find(|row| row.id == message.id)
                        {
                            if message_ids.iter().flatten().any(|id| *id == message.id) {
                                *existing = message;
                            }
                        } else {
                            current.messages.push(message);
                        }
                    }
                    if !chat.title.is_empty() {
                        current.title = chat.title;
                    }
                    if !chat.category.is_empty() {
                        current.category = chat.category;
                    }
                    self.chat_layout = None;
                }
            } else if primary {
                self.set_chat(chat);
            }
        }
        self.finish_overlap();
    }

    pub fn send_failed(&mut self, request: RequestId, error: &str) {
        if self.send_request == Some(request) {
            self.send_request = None;
            self.set_error(error);
        } else if let Some(turn) = self.followups.get_mut(&request) {
            turn.failed = true;
            let submitted = turn.has_submission();
            if !submitted
                && let Some(chat) = self.chat.as_mut().filter(|chat| chat.id == turn.chat_id)
                && let Some(active) = &turn.active
            {
                chat.messages.retain(|message| {
                    message.id != active.user_id && active.assistant.as_ref() != Some(&message.id)
                });
            }
            if self
                .chat
                .as_ref()
                .is_some_and(|chat| chat.id == turn.chat_id)
            {
                let handling = if submitted {
                    "Follow-up delivery uncertain. Use /pending to refresh or /copy-pending to copy."
                } else {
                    "Follow-up retained. Use /retry to restore it to the composer."
                };
                self.status = format!("{} · {handling}", markdown::clean(error).replace('\n', " "));
            }
            self.chat_layout = None;
        }
        self.finish_overlap();
    }

    pub(super) fn stop_send(&mut self, task_id: &str) -> Vec<UiCommand> {
        let visible = self.chat.as_ref().map(|chat| chat.id.as_str());
        let mut candidates = Vec::new();
        if let Some(request) = self.send_request
            && self.pending_send.is_some()
            && self
                .active_turn
                .as_ref()
                .is_none_or(|turn| Some(turn.chat_id.as_str()) == visible)
        {
            candidates.push((request, self.active_turn.as_ref()));
        }
        candidates.extend(self.followups.iter().filter_map(|(request, turn)| {
            (turn.is_pending() && Some(turn.chat_id.as_str()) == visible)
                .then_some((*request, turn.active.as_ref()))
        }));
        if !task_id.is_empty() {
            candidates
                .retain(|(_, turn)| turn.and_then(|turn| turn.task_id.as_deref()) == Some(task_id));
        }
        match candidates.as_slice() {
            [(request, turn)] => vec![UiCommand::StopSend {
                request: *request,
                task: turn.and_then(|turn| {
                    turn.task_id
                        .as_ref()
                        .map(|task_id| (turn.chat_id.clone(), task_id.clone()))
                }),
            }],
            [] => {
                self.status =
                    "No matching response in the open chat. Use /active to open a running chat."
                        .into();
                vec![]
            }
            _ => {
                let tasks = candidates
                    .iter()
                    .filter_map(|(_, turn)| turn.and_then(|turn| turn.task_id.as_deref()))
                    .collect::<Vec<_>>();
                self.status = if tasks.is_empty() {
                    "Several responses are pending. Wait for a task ID before stopping one.".into()
                } else {
                    format!(
                        "Choose an exact task with /stop {}",
                        tasks.join(" or /stop ")
                    )
                };
                vec![]
            }
        }
    }

    pub fn stop_result(&mut self, request: RequestId, result: crate::error::Result<()>) {
        if self.send_request == Some(request) || self.followups.contains_key(&request) {
            self.status = match result {
                Ok(()) => "Stop requested for this response".into(),
                Err(error) => format!("Could not confirm the stop request · {error}"),
            };
        }
    }

    fn finish_overlap(&mut self) {
        if self.send_request.is_none() && !self.followups.values().any(FollowupTurn::is_pending) {
            self.overlapping_chat = None;
        }
    }

    pub(super) fn failed_followup_request(&self, chat_id: &str) -> Option<RequestId> {
        self.followups
            .iter()
            .filter(|(_, turn)| turn.failed && turn.chat_id == chat_id)
            .max_by_key(|(id, turn)| (turn.has_submission(), **id))
            .map(|(id, _)| *id)
    }

    pub(super) fn failed_followup(&self, chat_id: &str) -> Option<&FollowupTurn> {
        self.failed_followup_request(chat_id)
            .and_then(|id| self.followups.get(&id))
    }

    pub(super) fn reconcile_followups(&mut self, chat: &Chat) {
        self.followups.retain(|_, turn| {
            if !turn.failed || turn.chat_id != chat.id {
                return true;
            }
            let message_id = match &turn.delivery {
                Delivery::Submitted { message_id, .. } | Delivery::Admitted { message_id, .. } => {
                    message_id
                }
                Delivery::Staged => return true,
            };
            !chat
                .messages
                .iter()
                .any(|message| message.role == "user" && message.id == *message_id)
        });
    }

    pub fn update_saved_queue_labels(&mut self, window: &ChatWindowRecord) {
        for message in window
            .messages
            .iter()
            .filter(|message| message.role == MessageRole::User)
        {
            if message.metadata.queue_dispatch_status.as_deref() == Some("queued") {
                let mode = if message.metadata.queue_mode.as_deref() == Some("steer") {
                    SendQueueMode::Steer
                } else {
                    SendQueueMode::FollowUp
                };
                self.queued_ids.insert(message.id.clone(), mode);
            } else if message.metadata.queue_dispatch_status.is_some() {
                self.queued_ids.remove(&message.id);
            }
        }
    }
}

impl ActiveTurn {
    pub(super) fn assign_task(&mut self, chat_id: &str, message_id: &str, task_id: String) {
        if self.chat_id == chat_id && self.user_id == message_id && !task_id.is_empty() {
            self.task_id = Some(task_id);
        }
    }

    pub(super) fn update_content(
        &mut self,
        chat: &mut Chat,
        content: String,
        thinking: String,
        mate: String,
    ) {
        if !self.expects_reply {
            return;
        }
        let id = self
            .assistant
            .get_or_insert_with(|| format!("__pending_assistant__:{}", self.user_id));
        let message = if let Some(index) = chat
            .messages
            .iter()
            .position(|message| message.id == *id && message.role == "assistant")
        {
            &mut chat.messages[index]
        } else {
            let after_user = chat
                .messages
                .iter()
                .position(|message| message.id == self.user_id)
                .map_or(chat.messages.len(), |index| index + 1);
            chat.messages.insert(
                after_user,
                Message {
                    id: id.clone(),
                    role: "assistant".into(),
                    ..Default::default()
                },
            );
            &mut chat.messages[after_user]
        };
        message.content = content;
        message.thinking = thinking;
        if !mate.is_empty() {
            message.sender = mate;
        }
    }

    pub(super) fn complete(
        &self,
        chat: &mut Chat,
        message_id: String,
        content: String,
    ) -> Option<&'static str> {
        if message_id == self.user_id {
            if !content.is_empty() {
                return None;
            }
            if let Some(id) = &self.assistant {
                chat.messages.retain(|message| {
                    message.id != *id || !message.content.is_empty() || !message.thinking.is_empty()
                });
            }
            return Some("Message delivered");
        }
        if !self.expects_reply {
            return None;
        }
        if let Some(message) = chat.messages.iter_mut().find(|message| {
            message.role == "assistant"
                && (message.id == message_id || self.assistant.as_ref() == Some(&message.id))
        }) {
            message.id = message_id;
            message.content = content;
        } else {
            let after_user = chat
                .messages
                .iter()
                .position(|message| message.id == self.user_id)
                .map_or(chat.messages.len(), |index| index + 1);
            chat.messages.insert(
                after_user,
                Message {
                    id: message_id,
                    role: "assistant".into(),
                    content,
                    ..Default::default()
                },
            );
        }
        Some("Response complete")
    }
}
