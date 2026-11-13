//! API-key new-chat suggestions list (npm `client.newChatSuggestions`).
use crate::client::new_chat_suggestions::{NewChatSuggestion, decrypt_new_chat_suggestions};
use crate::{Error, OpenMates, Result, sdk_transport::with_query};
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
    /// Suggestions decrypted locally with the API-key-wrapped account key, in
    /// the shape the session CLI prints. `limit` of `None` omits the query
    /// parameter so the server default applies; rows that do not decrypt are
    /// skipped and the rest are listed newest first, like the session path.
    pub async fn new_chat_suggestions_decrypted(
        &mut self,
        limit: Option<u32>,
    ) -> Result<Vec<NewChatSuggestion>> {
        let path = with_query(
            "/v1/sdk/new-chat-suggestions",
            &[("limit", limit.map(|limit| limit.to_string()))],
        );
        let response = self.get(&path).await?;
        let master = self.master_key().await?;
        decrypt_suggestion_rows(&response, &master, limit)
    }
}
fn decrypt_suggestion_rows(
    response: &Value,
    master: &[u8; 32],
    limit: Option<u32>,
) -> Result<Vec<NewChatSuggestion>> {
    let rows = response
        .get("suggestions")
        .and_then(Value::as_array)
        .ok_or(Error::Protocol)?;
    Ok(decrypt_new_chat_suggestions(
        rows,
        master,
        limit.map(i64::from),
    ))
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
    #[test]
    fn rows_decrypt_with_the_wrapped_key_and_skip_foreign_ciphertext() {
        let key = [9u8; 32];
        let other = [3u8; 32];
        let enc = |text: &str, key: &[u8; 32]| crate::crypto::encrypt_combined(text, key).unwrap();
        let response = serde_json::json!({"limit":10,"suggestions":[
            {"id":"a","chat_id":"c1","encrypted_suggestion":enc("[Travel] Plan a trip",&key),"created_at":1},
            {"id":"b","encrypted_suggestion":enc("Not mine",&other),"created_at":9},
            {"id":"c","encrypted_suggestion":enc("Newest",&key),"created_at":7},
        ]});
        let rows = decrypt_suggestion_rows(&response, &key, Some(10)).unwrap();
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].body, "Newest");
        assert_eq!(rows[1].body, "Plan a trip");
        assert_eq!(rows[1].chat_id.as_deref(), Some("c1"));
    }
    #[test]
    fn a_response_without_a_suggestion_list_is_a_protocol_error() {
        assert_eq!(
            decrypt_suggestion_rows(&serde_json::json!({}), &[1u8; 32], None),
            Err(Error::Protocol)
        );
    }
}
