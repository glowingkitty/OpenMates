//! Daily inspirations for the home banner (web `dailyInspirationDB.ts`,
//! `loadDefaultInspirations.ts`, TS CLI `getDailyInspirations`).
//!
//! Signed-in accounts read their persisted, master-key encrypted rows from
//! `GET /v1/daily-inspirations`; with none stored (or none readable) the public
//! cleartext defaults from `GET /v1/default-inspirations` apply. Only the
//! fields a terminal banner shows are decoded.
use crate::client::*;

/// One inspiration as the home banner shows it.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Inspiration {
    pub id: String,
    pub phrase: String,
    pub title: String,
    pub category: String,
    /// Feature title when the inspiration promotes an app feature.
    pub feature_title: Option<String>,
    /// `chats` when the server sets no surface.
    pub surface: String,
}

fn string(row: &Value, field: &str) -> String {
    row.get(field).and_then(Value::as_str).unwrap_or_default().to_owned()
}

fn decrypted(row: &Value, field: &str, key: &[u8; 32]) -> String {
    row.get(field)
        .and_then(Value::as_str)
        .and_then(|ciphertext| crypto::decrypt_combined(ciphertext, key).ok())
        .unwrap_or_default()
}

/// Decode the persisted rows; rows whose phrase does not decrypt are skipped.
pub(crate) fn personal_inspirations(rows: &[Value], master: &[u8; 32]) -> Vec<Inspiration> {
    rows.iter()
        .filter_map(|row| {
            let phrase = decrypted(row, "encrypted_phrase", master);
            if phrase.is_empty() {
                return None;
            }
            let feature_title = serde_json::from_str::<Value>(&decrypted(row, "encrypted_feature_metadata", master))
                .ok()
                .and_then(|feature| feature.get("title").and_then(Value::as_str).map(str::to_owned))
                .filter(|title| !title.is_empty());
            Some(Inspiration {
                id: string(row, "daily_inspiration_id"),
                phrase,
                title: decrypted(row, "encrypted_title", master),
                category: decrypted(row, "encrypted_category", master),
                feature_title,
                surface: Some(string(row, "surface")).filter(|s| !s.is_empty()).unwrap_or_else(|| "chats".into()),
            })
        })
        .collect()
}

pub(crate) fn public_inspirations(rows: &[Value]) -> Vec<Inspiration> {
    rows.iter()
        .map(|row| Inspiration {
            id: string(row, "inspiration_id"),
            phrase: string(row, "phrase"),
            title: string(row, "title"),
            category: string(row, "category"),
            feature_title: row.get("feature").and_then(|f| f.get("title")).and_then(Value::as_str).map(str::to_owned).filter(|t| !t.is_empty()),
            surface: Some(string(row, "surface")).filter(|s| !s.is_empty()).unwrap_or_else(|| "chats".into()),
        })
        .filter(|inspiration| !inspiration.phrase.is_empty())
        .collect()
}

fn rows(data: &Value) -> Vec<Value> {
    data.get("inspirations").and_then(Value::as_array).cloned().unwrap_or_default()
}

impl Client {
    /// The chat-surface inspirations for the home banner, personal first.
    pub async fn daily_inspirations(&mut self, lang: &str) -> Result<Vec<Inspiration>> {
        self.require_canonical_read_profile()?;
        let master = self.require_session()?.master_key.clone();
        let personal = self.request(Method::GET, "/v1/daily-inspirations", None).await?;
        let mut found = personal_inspirations(&rows(&personal), &master);
        if found.is_empty() {
            let path = format!("/v1/default-inspirations?lang={}", segment(lang));
            let public = self.request(Method::GET, &path, None).await?;
            found = public_inspirations(&rows(&public));
        }
        found.retain(|inspiration| inspiration.surface == "chats");
        Ok(found)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust
    #[test]
    fn personal_rows_decrypt_and_public_rows_are_cleartext() {
        let key = [9u8; 32];
        let enc = |text: &str| crypto::encrypt_combined(text, &key).unwrap();
        let personal = personal_inspirations(
            &[
                json!({"daily_inspiration_id": "i1", "encrypted_phrase": enc("Learn Rust"), "encrypted_title": enc("Rust"),
                       "encrypted_category": enc("software_development"), "encrypted_feature_metadata": enc("{\"title\":\"Feature\"}")}),
                json!({"daily_inspiration_id": "i2", "encrypted_phrase": "not-ciphertext"}),
                json!({"daily_inspiration_id": "i3", "encrypted_phrase": enc("Apps tip"), "surface": "apps"}),
            ],
            &key,
        );
        assert_eq!(personal.len(), 2);
        assert_eq!(personal[0].phrase, "Learn Rust");
        assert_eq!(personal[0].feature_title.as_deref(), Some("Feature"));
        assert_eq!(personal[0].surface, "chats");
        assert_eq!(personal[1].surface, "apps");
        let public = public_inspirations(&[json!({"inspiration_id": "p1", "phrase": "Hello", "title": "T", "category": "travel"}), json!({"inspiration_id": "p2"})]);
        assert_eq!(public.len(), 1);
        assert_eq!(public[0].category, "travel");
    }
}
