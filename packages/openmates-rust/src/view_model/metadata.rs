//! Extra facts of chat list rows and messages that shells show beside the
//! title and text (icon, sub-chat and budget fields, timestamps, draft
//! preview, model name, queue state, PII mappings). Projected by the client
//! from rows it already holds (`client/view_projection.rs`); every field is
//! optional and stays `None` when the row does not carry it. Plan
//! `apple-client-core-migration` (a4 lane 0).

/// List facts of one chat beyond [`super::ChatListRow`]'s display fields.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChatRowMetadata {
    /// Decrypted icon name; `None` when unset or the chat is locked.
    pub icon: Option<String>,
    /// Decrypted id of the active focus mode; `None` when none or locked.
    pub active_focus_id: Option<String>,
    /// Parent chat id of a sub-chat.
    pub parent_id: Option<String>,
    /// The chat is a sub-chat (`is_sub_chat`).
    pub is_sub_chat: Option<bool>,
    /// Team of the chat: the active team in team scope, `None` in personal scope.
    pub team_id: Option<String>,
    /// The owner shared the chat by link (`is_shared`).
    pub is_shared: Option<bool>,
    /// The chat is private, never shareable (`is_private`).
    pub is_private: Option<bool>,
    /// The chat is hidden behind the hidden-chats lock (`is_hidden`).
    pub is_hidden: Option<bool>,
    /// Server time of the last completed message (`last_message_timestamp`,
    /// the same unit as the row's `created_at`).
    pub last_message_at: Option<i64>,
    /// Server time of the last edit of any kind
    /// (`last_edited_overall_timestamp`, the list's recency order).
    pub last_edited_at: Option<i64>,
    /// Credit limit of a sub-chat subtree.
    pub budget_limit: Option<u64>,
    /// Credits spent under a sub-chat subtree.
    pub budget_spent: Option<u64>,
    /// Server draft version (`draft_v`).
    pub draft_v: Option<u64>,
    /// Decrypted draft preview text; personal scope with a draft only.
    pub draft_preview: Option<String>,
    /// Another account shared this chat with the user (`is_shared_by_others`).
    pub is_shared_by_others: Option<bool>,
    /// Id of the last message visible in the chat (`last_visible_message_id`).
    pub last_visible_message_id: Option<String>,
    /// App the chat belongs to (`app_id`).
    pub app_id: Option<String>,
    /// Sub-chat setting: the parent waits for the sub-chat to finish
    /// (`sub_chat_settings.wait_for_completion`).
    pub sub_chat_wait_for_completion: Option<bool>,
    /// Sub-chat setting: when the sub-chat reports to its parent, `each` or
    /// `all` (`sub_chat_settings.report_trigger`).
    pub sub_chat_report_trigger: Option<String>,
}

/// One personal-data replacement of a message: the placeholder the server
/// saw and the original text the device restores.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PiiMapping {
    /// Placeholder token as stored in the message.
    pub placeholder: String,
    /// Original text (personal data; shown only on this device).
    pub original: String,
    /// Kind of data such as `EMAIL`; empty when the mapping names none.
    pub kind: String,
}

/// Stored facts of one message beyond [`super::MessageRecord`]'s display
/// fields. Default (all `None`, no mappings) for messages the core added
/// itself during a send and for messages whose row the client does not hold.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MessageMetadata {
    /// Server creation time of the row (`created_at`).
    pub created_at: Option<i64>,
    /// Server time of the last edit of the row (`updated_at`).
    pub updated_at: Option<i64>,
    /// App that produced the message (`app_id`).
    pub app_id: Option<String>,
    /// Server message id (`message_id`).
    pub server_message_id: Option<String>,
    /// Client message id assigned by the sending device.
    pub client_message_id: Option<String>,
    /// For a reply: the id of the user message it answers.
    pub user_message_id: Option<String>,
    /// Raw stored status word such as `synced` or `queued`.
    pub stored_status: Option<String>,
    /// Decrypted name of the model that wrote a reply.
    pub model_name: Option<String>,
    /// Decrypted category (mate) of a reply.
    pub category: Option<String>,
    /// The reply stored reasoning.
    pub has_thinking: Option<bool>,
    /// Reasoning token count of a reply.
    pub thinking_token_count: Option<u64>,
    /// Revision of a queued message.
    pub queue_revision: Option<u64>,
    /// Queue mode of a queued message.
    pub queue_mode: Option<String>,
    /// Dispatch status of a queued message.
    pub queue_dispatch_status: Option<String>,
    /// Dispatch mode of a queued message.
    pub queue_dispatch_mode: Option<String>,
    /// Dispatch task id of a queued message.
    pub queue_dispatch_task_id: Option<String>,
    /// Personal-data mappings stored with this message.
    pub pii_mappings: Vec<PiiMapping>,
}
