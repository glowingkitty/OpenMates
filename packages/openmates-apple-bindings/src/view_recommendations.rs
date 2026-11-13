//! Chat Recommendations on `ViewModelCore`: the open recommendations of a
//! chat, decrypted by the core from `chats.encrypted_recommendations`
//! (`Client::chat_recommendations`), exported to Swift. Bindings only
//! marshal presentation records. Mirrors the web
//! `hydrateChatRecommendations`; spec `features.app-memories`
//! (`app-memories.suggestions.*`).
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use openmates_sdk::client::recommendations::{
    ChatRecommendation, RecommendationAction, RecommendationKind,
};
use crate::view_memories::MemoryFieldsRecord;
use openmates_sdk::client::memory_document_fields::{MemoryDocumentFields, parse_memory_document};
use openmates_sdk::client::recommendation_actions::{
    RecommendationDraftFailure, RecommendationDraftOutcome,
};
use openmates_sdk::error::Error;
use openmates_sdk::view_model::ViewHost;
use std::sync::Arc;

/// Kind of entry a recommendation would create or update.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum RecommendationKindRecord {
    /// A Memory.
    Memory,
    /// A workflow.
    Workflow,
}

/// Whether a recommendation creates or updates an entry.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum RecommendationActionRecord {
    /// Create a new entry.
    Create,
    /// Update the entry `target_id` names.
    Update,
}

/// One open recommendation as shown on the card.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ChatRecommendationRecord {
    /// Stable id of the recommendation.
    pub id: String,
    /// Memory or workflow.
    pub kind: RecommendationKindRecord,
    /// Create or update.
    pub action: RecommendationActionRecord,
    /// Existing entry id when updating.
    pub target_id: Option<String>,
    /// Short title.
    pub title: String,
    /// One or two sentences.
    pub summary: String,
}

fn record(item: ChatRecommendation) -> ChatRecommendationRecord {
    ChatRecommendationRecord {
        id: item.id,
        kind: match item.kind {
            RecommendationKind::Memory => RecommendationKindRecord::Memory,
            RecommendationKind::Workflow => RecommendationKindRecord::Workflow,
        },
        action: match item.action {
            RecommendationAction::Create => RecommendationActionRecord::Create,
            RecommendationAction::Update => RecommendationActionRecord::Update,
        },
        target_id: item.target_id,
        title: item.title,
        summary: item.summary,
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// The open recommendations of `chat_id` (Memory and Workflow
    /// suggestions of the latest completed turn), decrypted on this device;
    /// empty when the chat has none.
    ///
    /// # Errors
    /// `Authentication` when signed out; chat read errors (`Forbidden`,
    /// `Offline`, `Crypto`, `Expired`); `Cancelled`.
    pub async fn chat_recommendations(
        &self,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<Vec<ChatRecommendationRecord>, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, _sink, cancel| {
                    Box::pin(async move {
                        let result = tokio::select! {
                            biased;
                            () = cancel.cancelled() => Err(Error::Cancelled),
                            result = host.core_mut().client_mut().chat_recommendations(&chat_id) => result,
                        };
                        // Rotated cookies are durable before Swift sees the result.
                        host.core_mut().persist().await?;
                        result.map(|items| items.into_iter().map(record).collect())
                    })
                })
                .await
        })
        .await
    }
}

/// Outcome of accepting a Memory recommendation (billed draft request).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum RecommendationDraftStatusRecord {
    /// `fields` holds the unsaved draft for the Memory editor.
    Draft,
    /// The update changes nothing ("already up to date").
    UpToDate,
    /// The account cannot pay for the draft (HTTP 402).
    InsufficientCredits,
    /// The Memory an update targets no longer exists.
    MemoryNotFound,
    /// The server refused or answered with something unusable.
    RequestFailed,
    /// No response twice, or the retried request id was already received.
    NetworkUnavailable,
}

/// Result of `recommendation_memory_draft`.
#[derive(Clone, PartialEq, Eq, uniffi::Record)]
pub struct RecommendationDraftRecord {
    /// What happened.
    pub status: RecommendationDraftStatusRecord,
    /// The draft fields when `status` is `Draft`.
    pub fields: Option<MemoryFieldsRecord>,
    /// Id of the Memory an update edits; `None` for a new Memory.
    pub existing_id: Option<String>,
}

fn status_only(status: RecommendationDraftStatusRecord) -> RecommendationDraftRecord {
    RecommendationDraftRecord {
        status,
        fields: None,
        existing_id: None,
    }
}

fn draft_fields(fields: &MemoryDocumentFields, app_id: Option<String>) -> MemoryFieldsRecord {
    MemoryFieldsRecord {
        title: fields.title.clone(),
        description: fields.description.clone(),
        when_to_use: fields.when_to_use.clone(),
        body: fields.body.clone(),
        load_mode: fields.load_mode.map(Into::into),
        valid_from: fields.valid_from.clone(),
        valid_until: fields.valid_until.clone(),
        references: fields.references.clone(),
        app_id: app_id.or_else(|| fields.app_id.clone()),
    }
}

fn draft_record(outcome: RecommendationDraftOutcome) -> RecommendationDraftRecord {
    use RecommendationDraftStatusRecord as Status;
    match outcome {
        RecommendationDraftOutcome::UpToDate => status_only(Status::UpToDate),
        RecommendationDraftOutcome::Failed(failure) => status_only(match failure {
            RecommendationDraftFailure::InsufficientCredits => Status::InsufficientCredits,
            RecommendationDraftFailure::MemoryNotFound => Status::MemoryNotFound,
            RecommendationDraftFailure::RequestFailed => Status::RequestFailed,
            RecommendationDraftFailure::NetworkUnavailable => Status::NetworkUnavailable,
        }),
        RecommendationDraftOutcome::Draft(draft) => match parse_memory_document(&draft.document) {
            Ok(fields) => RecommendationDraftRecord {
                status: Status::Draft,
                fields: Some(draft_fields(&fields, draft.app_id)),
                existing_id: draft.existing_id,
            },
            Err(_) => status_only(Status::RequestFailed),
        },
    }
}

fn core_recommendation(item: ChatRecommendationRecord) -> ChatRecommendation {
    ChatRecommendation {
        id: item.id,
        kind: match item.kind {
            RecommendationKindRecord::Memory => RecommendationKind::Memory,
            RecommendationKindRecord::Workflow => RecommendationKind::Workflow,
        },
        action: match item.action {
            RecommendationActionRecord::Create => RecommendationAction::Create,
            RecommendationActionRecord::Update => RecommendationAction::Update,
        },
        target_id: item.target_id,
        title: item.title,
        summary: item.summary,
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// Accepts a Memory recommendation of `chat_id`: the billed create-draft
    /// or update-preview request built from the chat's latest turn. Request
    /// failures (insufficient credits, network, refused) come back as a
    /// status, not an error.
    ///
    /// # Errors
    /// `Authentication` when signed out; chat read errors; `Cancelled`.
    pub async fn recommendation_memory_draft(
        &self,
        chat_id: String,
        recommendation: ChatRecommendationRecord,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<RecommendationDraftRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        let item = core_recommendation(recommendation);
        self.run(async move {
            shared
                .signed_in(token, move |host, _sink, cancel| {
                    Box::pin(async move {
                        let result = tokio::select! {
                            biased;
                            () = cancel.cancelled() => Err(Error::Cancelled),
                            result = host.core_mut().client_mut().recommendation_memory_draft(&chat_id, &item) => result,
                        };
                        host.core_mut().persist().await?;
                        result.map(draft_record)
                    })
                })
                .await
        })
        .await
    }

    /// Marks a recommendation resolved after its entry was saved (encrypted
    /// state written back with the chat key); no-op when it is no longer open.
    ///
    /// # Errors
    /// `Authentication` when signed out; chat read and socket errors; `Cancelled`.
    pub async fn resolve_chat_recommendation(
        &self,
        chat_id: String,
        recommendation_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, _sink, cancel| {
                    Box::pin(async move {
                        let result = tokio::select! {
                            biased;
                            () = cancel.cancelled() => Err(Error::Cancelled),
                            result = host.core_mut().client_mut().resolve_chat_recommendation(&chat_id, &recommendation_id) => result,
                        };
                        host.core_mut().persist().await?;
                        result
                    })
                })
                .await
        })
        .await
    }
}
