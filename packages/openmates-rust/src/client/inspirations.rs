//! Daily inspirations for the home banner (web `dailyInspirationDB.ts`,
//! `loadDefaultInspirations.ts`, TS CLI `getDailyInspirations`).
//!
//! Signed-in accounts read their persisted, master-key encrypted rows from
//! `GET /v1/daily-inspirations`; with none stored (or none readable) the public
//! cleartext defaults from `GET /v1/default-inspirations` apply. The banner
//! fields are typed; `legacy_json` carries the full npm CLI
//! `getDailyInspirations` row shape for `inspirations --json`.
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
    /// The row exactly as the npm CLI `DailyInspiration` JSON shows it
    /// (assistant response, content type, video, follow-ups, feature, ...).
    pub legacy_json: Value,
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
            let feature = serde_json::from_str::<Value>(&decrypted(row, "encrypted_feature_metadata", master))
                .ok()
                .filter(Value::is_object);
            let feature_title = feature
                .as_ref()
                .and_then(|feature| feature.get("title").and_then(Value::as_str).map(str::to_owned))
                .filter(|title| !title.is_empty());
            let video = serde_json::from_str::<Value>(&decrypted(row, "encrypted_video_metadata", master)).unwrap_or(Value::Null);
            let follow_ups = serde_json::from_str::<Value>(&decrypted(row, "encrypted_follow_up_suggestions", master))
                .ok()
                .and_then(|value| value.as_array().map(|items| strings(items)))
                .unwrap_or_default();
            let id = string(row, "daily_inspiration_id");
            let title = decrypted(row, "encrypted_title", master);
            let category = decrypted(row, "encrypted_category", master);
            let mut legacy = json!({
                "id": id, "phrase": phrase, "title": title,
                "assistant_response": decrypted(row, "encrypted_assistant_response", master),
                "category": category, "content_type": content_type(row), "video": video,
                "generated_at": generated_at(row), "follow_up_suggestions": follow_ups,
                "feature": feature.unwrap_or(Value::Null),
                "is_opened": row.get("is_opened").and_then(Value::as_bool) == Some(true),
            });
            with_surface(&mut legacy, row);
            Some(Inspiration {
                id,
                phrase,
                title,
                category,
                feature_title,
                surface: surface(row),
                legacy_json: legacy,
            })
        })
        .collect()
}

pub(crate) fn public_inspirations(rows: &[Value]) -> Vec<Inspiration> {
    rows.iter()
        .map(|row| {
            let feature = row.get("feature").filter(|f| f.is_object()).cloned();
            let mut legacy = json!({
                "id": string(row, "inspiration_id"), "phrase": string(row, "phrase"), "title": string(row, "title"),
                "assistant_response": string(row, "assistant_response"), "category": string(row, "category"),
                "content_type": content_type(row), "video": public_video(row.get("video")),
                "generated_at": generated_at(row),
                "feature": feature.clone().unwrap_or(Value::Null),
                "follow_up_suggestions": row.get("follow_up_suggestions").and_then(Value::as_array).map(|items| strings(items)).unwrap_or_default(),
            });
            with_surface(&mut legacy, row);
            Inspiration {
                id: string(row, "inspiration_id"),
                phrase: string(row, "phrase"),
                title: string(row, "title"),
                category: string(row, "category"),
                feature_title: feature.as_ref().and_then(|f| f.get("title")).and_then(Value::as_str).map(str::to_owned).filter(|t| !t.is_empty()),
                surface: surface(row),
                legacy_json: legacy,
            }
        })
        .filter(|inspiration| !inspiration.phrase.is_empty())
        .collect()
}

fn surface(row: &Value) -> String {
    Some(string(row, "surface")).filter(|s| !s.is_empty()).unwrap_or_else(|| "chats".into())
}

/// npm sets `surface` only when the server sent a string.
fn with_surface(legacy: &mut Value, row: &Value) {
    if let Some(surface) = row.get("surface").and_then(Value::as_str) {
        legacy["surface"] = Value::String(surface.to_owned());
    }
}

/// npm defaults a missing content type to `video`.
fn content_type(row: &Value) -> String {
    row.get("content_type").and_then(Value::as_str).unwrap_or("video").to_owned()
}

/// npm keeps a numeric `generated_at` and reports 0 otherwise.
fn generated_at(row: &Value) -> Value {
    row.get("generated_at").filter(|v| v.is_number()).cloned().unwrap_or_else(|| json!(0))
}

fn strings(items: &[Value]) -> Vec<String> {
    items.iter().filter_map(Value::as_str).map(str::to_owned).collect()
}

/// The npm public-row video projection (typed fields, nullable extras).
fn public_video(video: Option<&Value>) -> Value {
    let Some(video) = video.filter(|v| v.is_object()) else { return Value::Null };
    let text = |field: &str| video.get(field).and_then(Value::as_str).unwrap_or_default().to_owned();
    let nullable = |field: &str, keep: fn(&Value) -> bool| video.get(field).filter(|v| keep(v)).cloned().unwrap_or(Value::Null);
    json!({
        "youtube_id": text("youtube_id"), "title": text("title"), "thumbnail_url": text("thumbnail_url"),
        "channel_name": nullable("channel_name", Value::is_string),
        "view_count": nullable("view_count", Value::is_number),
        "duration_seconds": nullable("duration_seconds", Value::is_number),
        "published_at": nullable("published_at", Value::is_string),
    })
}

fn rows(data: &Value) -> Vec<Value> {
    data.get("inspirations").and_then(Value::as_array).cloned().unwrap_or_default()
}

impl Client {
    /// Today's inspirations for every surface, personal first (npm
    /// `getDailyInspirations` order); the chat home banner keeps `surface == "chats"`.
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
        assert_eq!(public[0].legacy_json["content_type"], "video");
        assert_eq!(public[0].legacy_json["video"], Value::Null);
        assert!(public[0].legacy_json.get("surface").is_none());
        assert_eq!(personal[0].legacy_json["feature"]["title"], "Feature");
        assert_eq!(personal[0].legacy_json["is_opened"], false);
        assert_eq!(personal[1].legacy_json["surface"], "apps");
    }
}
