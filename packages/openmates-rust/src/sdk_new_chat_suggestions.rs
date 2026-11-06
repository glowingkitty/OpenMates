//! API-key new-chat suggestions list (npm `client.newChatSuggestions`).
use crate::{OpenMates, Result, sdk_transport::with_query};
use serde_json::Value;

#[derive(Clone, Default)]
pub struct NewChatSuggestionsOptions {
    pub limit: Option<u32>,
}
pub struct NewChatSuggestions<'a> {
    client: &'a OpenMates,
}
impl<'a> NewChatSuggestions<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self {
        Self { client }
    }
    /// The limit defaults to 10 exactly like npm and Python.
    pub async fn list(&self, options: NewChatSuggestionsOptions) -> Result<Value> {
        self.client.get(&suggestions_path(&options)).await
    }
}
fn suggestions_path(options: &NewChatSuggestionsOptions) -> String {
    with_query(
        "/v1/sdk/new-chat-suggestions",
        &[("limit", Some(options.limit.unwrap_or(10).to_string()))],
    )
}
impl OpenMates {
    pub fn new_chat_suggestions(&self) -> NewChatSuggestions<'_> {
        NewChatSuggestions::new(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn default_limit_is_ten() {
        assert_eq!(
            suggestions_path(&Default::default()),
            "/v1/sdk/new-chat-suggestions?limit=10"
        );
        assert_eq!(
            suggestions_path(&NewChatSuggestionsOptions { limit: Some(0) }),
            "/v1/sdk/new-chat-suggestions?limit=0"
        );
    }
}
