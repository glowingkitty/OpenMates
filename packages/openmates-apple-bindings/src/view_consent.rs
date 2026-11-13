//! Answer a consent request of a running turn on `ViewModelCore`
//! (`StreamEvent.consent`), through the core's `ConsentAnswerer`. It does not
//! queue behind the actor: the turn that waits for the answer holds it.
//! Bindings only marshal. Spec `client-core`.
use crate::CoreError;
use crate::view_core::{ViewModelCore, lock};
use openmates_sdk::error::Error;

#[uniffi::export]
impl ViewModelCore {
    /// Answer consent request `request_id` of `chat_id`, approving exactly
    /// the items in `approved_item_ids` (an empty list declines).
    ///
    /// # Errors
    /// `Invalid` for an unknown, already answered or ended request, another
    /// chat's request, an unlisted item or more than 64 items; `Cancelled`
    /// when no turn reads answers any more; `Offline` when signed out.
    pub fn answer_consent(
        &self,
        chat_id: String,
        request_id: String,
        approved_item_ids: Vec<String>,
    ) -> Result<(), CoreError> {
        let answerer = lock(&self.shared.consent).clone().ok_or(Error::Offline)?;
        answerer
            .answer(&chat_id, &request_id, approved_item_ids)
            .map_err(CoreError::from)
    }
}
