//! UniFFI mirrors of the core view-model metadata records
//! (`openmates_sdk::view_model::{ChatRowMetadata, MessageMetadata,
//! PiiMapping}`) carried by `ChatListRowRecord.metadata` and
//! `MessageViewRecord.metadata`. Each maps its core counterpart 1:1 (same
//! fields, no defaults, no logic). Plan `apple-client-core-migration` (a4
//! lane 0). Plaintext (draft preview, PII originals): never log it.
use openmates_sdk::view_model::{ChatRowMetadata, MessageMetadata, PiiMapping};

/// List facts of one chat beyond the display fields (core `ChatRowMetadata`).
/// Every field is `None` when the held row does not carry it.
#[derive(Clone, Debug, Default, PartialEq, Eq, uniffi::Record)]
pub struct ChatRowMetadataRecord {
    /// Decrypted icon name; `None` when unset or the chat is locked.
    pub icon: Option<String>,
    /// Decrypted id of the active focus mode.
    pub active_focus_id: Option<String>,
    /// Parent chat id of a sub-chat.
    pub parent_id: Option<String>,
    /// The chat is a sub-chat.
    pub is_sub_chat: Option<bool>,
    /// Team of the chat: the active team in team scope, `None` in personal scope.
    pub team_id: Option<String>,
    /// The owner shared the chat by link.
    pub is_shared: Option<bool>,
    /// The chat is private, never shareable.
    pub is_private: Option<bool>,
    /// The chat is hidden behind the hidden-chats lock.
    pub is_hidden: Option<bool>,
    /// Server time of the last completed message (`last_message_timestamp`).
    pub last_message_at: Option<i64>,
    /// Server time of the last edit of any kind (`last_edited_overall_timestamp`).
    pub last_edited_at: Option<i64>,
    /// Credit limit of a sub-chat subtree.
    pub budget_limit: Option<u64>,
    /// Credits spent under a sub-chat subtree.
    pub budget_spent: Option<u64>,
    /// Server draft version.
    pub draft_v: Option<u64>,
    /// Decrypted draft preview text; personal scope with a draft only.
    pub draft_preview: Option<String>,
    /// Another account shared this chat with the user.
    pub is_shared_by_others: Option<bool>,
    /// Id of the last message visible in the chat.
    pub last_visible_message_id: Option<String>,
    /// App the chat belongs to.
    pub app_id: Option<String>,
    /// Sub-chat setting: the parent waits for the sub-chat to finish.
    pub sub_chat_wait_for_completion: Option<bool>,
    /// Sub-chat setting: `each` or `all`.
    pub sub_chat_report_trigger: Option<String>,
}

/// One personal-data replacement of a message (core `PiiMapping`).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct PiiMappingRecord {
    /// Placeholder token as stored in the message.
    pub placeholder: String,
    /// Original text (personal data; shown only on this device).
    pub original: String,
    /// Kind of data such as `EMAIL`; empty when the mapping names none.
    pub kind: String,
}

/// Stored facts of one message beyond its display fields (core
/// `MessageMetadata`). All `None` and no mappings for messages the core added
/// during a send and for messages whose row the core does not hold.
#[derive(Clone, Debug, Default, PartialEq, Eq, uniffi::Record)]
pub struct MessageMetadataRecord {
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
    pub pii_mappings: Vec<PiiMappingRecord>,
}

impl From<ChatRowMetadata> for ChatRowMetadataRecord {
    fn from(value: ChatRowMetadata) -> Self {
        Self {
            icon: value.icon,
            active_focus_id: value.active_focus_id,
            parent_id: value.parent_id,
            is_sub_chat: value.is_sub_chat,
            team_id: value.team_id,
            is_shared: value.is_shared,
            is_private: value.is_private,
            is_hidden: value.is_hidden,
            last_message_at: value.last_message_at,
            last_edited_at: value.last_edited_at,
            budget_limit: value.budget_limit,
            budget_spent: value.budget_spent,
            draft_v: value.draft_v,
            draft_preview: value.draft_preview,
            is_shared_by_others: value.is_shared_by_others,
            last_visible_message_id: value.last_visible_message_id,
            app_id: value.app_id,
            sub_chat_wait_for_completion: value.sub_chat_wait_for_completion,
            sub_chat_report_trigger: value.sub_chat_report_trigger,
        }
    }
}

impl From<PiiMapping> for PiiMappingRecord {
    fn from(value: PiiMapping) -> Self {
        Self {
            placeholder: value.placeholder,
            original: value.original,
            kind: value.kind,
        }
    }
}

impl From<MessageMetadata> for MessageMetadataRecord {
    fn from(value: MessageMetadata) -> Self {
        Self {
            created_at: value.created_at,
            updated_at: value.updated_at,
            app_id: value.app_id,
            server_message_id: value.server_message_id,
            client_message_id: value.client_message_id,
            user_message_id: value.user_message_id,
            stored_status: value.stored_status,
            model_name: value.model_name,
            category: value.category,
            has_thinking: value.has_thinking,
            thinking_token_count: value.thinking_token_count,
            queue_revision: value.queue_revision,
            queue_mode: value.queue_mode,
            queue_dispatch_status: value.queue_dispatch_status,
            queue_dispatch_mode: value.queue_dispatch_mode,
            queue_dispatch_task_id: value.queue_dispatch_task_id,
            pii_mappings: value.pii_mappings.into_iter().map(Into::into).collect(),
        }
    }
}
