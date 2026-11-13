//! API-key IdeaBucket (npm `client.ideabucket`). Settings live in an encrypted
//! account Memory; captured ideas are encrypted locally (master key and a fresh chat
//! key) and only ciphertext plus sparse scheduling metadata reaches the server.
use crate::{
    Error, OpenMates, Result,
    account::{
        IDEABUCKET_DEFAULT_PROCESSING_PROMPT, next_send_at, normalize_processing_times, today,
    },
    crypto,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

const APP_ID: &str = "ideabucket";
const SETTINGS_TYPE: &str = "processing_settings";

#[derive(Clone, Default)]
pub struct IdeaBucketAddInput {
    pub text: String,
    pub chat_id: Option<String>,
    pub bucket_id: Option<String>,
    pub scheduled_send_at: Option<i64>,
    pub prompt: Option<String>,
}
#[derive(Clone, Default)]
pub struct IdeaBucketSettingsInput {
    pub processing_prompt: Option<String>,
    pub processing_times: Option<Vec<String>>,
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn bucket_segment(id: &str) -> Result<String> {
    if id.is_empty() || id.len() > 128 {
        return Err(Error::Invalid("Invalid IdeaBucket bucket ID."));
    }
    Ok(url::form_urlencoded::byte_serialize(id.as_bytes())
        .collect::<String>()
        .replace('+', "%20"))
}
fn times_error(_: String) -> Error {
    Error::Invalid("Invalid IdeaBucket processing times.")
}

/// npm `normalizeSettings`; `source` is `account` only when an entry exists.
fn settings_value(data: Option<&Value>, entry: Option<(&str, Option<u64>)>) -> Result<Value> {
    let prompt = data
        .and_then(|d| d["processing_prompt"].as_str())
        .map(str::trim)
        .filter(|p| !p.is_empty())
        .unwrap_or(IDEABUCKET_DEFAULT_PROCESSING_PROMPT);
    let times =
        normalize_processing_times(data.map(|d| &d["processing_times"]).unwrap_or(&Value::Null))
            .map_err(times_error)?;
    let mut value =
        json!({"processingPrompt": prompt, "processingTimes": times, "source": "default"});
    if let Some((id, version)) = entry {
        value["entryId"] = json!(id);
        if let Some(version) = version {
            value["itemVersion"] = json!(version);
        }
        value["source"] = json!("account");
    }
    Ok(value)
}

/// npm `buildIdeaBucketMarkdown`.
pub fn ideabucket_markdown(prompt: &str, idea: &str) -> String {
    format!(
        "{}\n\n----- Idea 1 -----\n{}\n-----------------",
        prompt.trim(),
        idea.trim()
    )
}

/// The server-processable payload and its hash exactly as npm serializes them.
pub fn processing_payload(prompt: &str, bucket_id: &str, idea: &str) -> (String, String) {
    let payload = json!({"prompt":prompt,"bucket_id":bucket_id,"processing_window_id":bucket_id,"ideas":[{"index":1,"type":"text","text":idea}]}).to_string();
    let hash = hex(&Sha256::digest(payload.as_bytes()));
    (payload, hash)
}

pub struct IdeaBucket<'a> {
    client: &'a mut OpenMates,
}
impl<'a> IdeaBucket<'a> {
    pub(crate) fn new(client: &'a mut OpenMates) -> Self {
        Self { client }
    }
    pub async fn settings(&mut self) -> Result<Value> {
        let response = self
            .client
            .memories()
            .list(&[
                ("app_id", Some(APP_ID.into())),
                ("item_type", Some(SETTINGS_TYPE.into())),
            ])
            .await?;
        let entry = response["memories"].as_array().and_then(|m| m.first());
        let Some(entry) = entry else {
            return settings_value(None, None);
        };
        let data = entry["data"].as_object().map(|_| &entry["data"]);
        match entry["id"].as_str() {
            Some(id) => settings_value(data, Some((id, entry["item_version"].as_u64()))),
            None => settings_value(data, None),
        }
    }
    /// Refused like npm/Python: typed app memories were replaced by Memories
    /// (create/update removed 2026-11-07, backend answers 410), so settings are
    /// no longer written through the SDK.
    ///
    /// # Errors
    /// Always [`Error::Invalid`]; nothing is sent.
    pub async fn save_settings(&mut self, _input: IdeaBucketSettingsInput) -> Result<Value> {
        Err(Error::Invalid(
            "Typed app memories were replaced by Memories; Idea Bucket settings are no longer stored as a typed memory.",
        ))
    }
    pub async fn add(&mut self, input: IdeaBucketAddInput) -> Result<Value> {
        let payload = self.encrypted_add_payload(input).await?;
        let bucket = bucket_segment(
            payload["ideabucket_processing_window_id"]
                .as_str()
                .ok_or(Error::Protocol)?,
        )?;
        self.client
            .post(&format!("/v1/sdk/ideabucket/buckets/{bucket}/add"), payload)
            .await
    }
    pub async fn status(&self, bucket_id: Option<&str>) -> Result<Value> {
        match bucket_id {
            Some(id) => {
                self.client
                    .get(&format!(
                        "/v1/sdk/ideabucket/buckets/{}",
                        bucket_segment(id)?
                    ))
                    .await
            }
            None => self.client.get("/v1/sdk/ideabucket/buckets").await,
        }
    }
    pub async fn process(&self, bucket_id: &str, now: bool) -> Result<Value> {
        self.client
            .post(
                &format!(
                    "/v1/sdk/ideabucket/buckets/{}/process",
                    bucket_segment(bucket_id)?
                ),
                json!({"now": now}),
            )
            .await
    }
    async fn encrypted_add_payload(&mut self, input: IdeaBucketAddInput) -> Result<Value> {
        let idea = input.text.trim().to_owned();
        if idea.is_empty() {
            return Err(Error::Invalid("IdeaBucket add requires non-empty text."));
        }
        self.client.verify_private_operation()?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| Error::Protocol)?
            .as_secs() as i64;
        let bucket = input.bucket_id.clone().unwrap_or_else(|| today(now));
        let settings = if input.prompt.is_none() || input.scheduled_send_at.is_none() {
            Some(self.settings().await?)
        } else {
            None
        };
        let scheduled = input.scheduled_send_at.unwrap_or_else(|| match &settings {
            Some(s) if s["source"] == "account" => next_send_at(
                now,
                &s["processingTimes"]
                    .as_array()
                    .map(|t| {
                        t.iter()
                            .filter_map(Value::as_str)
                            .map(str::to_owned)
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default(),
            ),
            _ => now - now.rem_euclid(86_400) + 86_400 + 9 * 3600,
        });
        let chat_id = input
            .chat_id
            .clone()
            .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
        let prompt = input
            .prompt
            .clone()
            .or_else(|| {
                settings
                    .as_ref()
                    .and_then(|s| s["processingPrompt"].as_str().map(str::to_owned))
            })
            .unwrap_or_else(|| IDEABUCKET_DEFAULT_PROCESSING_PROMPT.into());
        let master = self.client.master_key().await?;
        let chat_key = crypto::random_key();
        build_payload(
            &chat_id, &bucket, scheduled, &prompt, &idea, now, &master, &chat_key,
        )
    }
}

#[allow(clippy::too_many_arguments)]
fn build_payload(
    chat_id: &str,
    bucket: &str,
    scheduled: i64,
    prompt: &str,
    idea: &str,
    now: i64,
    master: &[u8; 32],
    chat_key: &[u8; 32],
) -> Result<Value> {
    let markdown = ideabucket_markdown(prompt, idea);
    let preview = format!(
        "IdeaBucket {bucket}: {}",
        idea.chars().take(120).collect::<String>()
    );
    let (payload, payload_hash) = processing_payload(prompt, bucket, idea);
    let event = json!({"type":"ideabucket_triggered_send","bucket_id":bucket,"processing_window_id":bucket,"source":"openmates_sdk"}).to_string();
    Ok(json!({
        "chat_id": chat_id,
        "encrypted_draft_md": crypto::encrypt_combined(&markdown, master)?,
        "encrypted_draft_preview": crypto::encrypt_combined(&preview, master)?,
        "ideabucket": true,
        "ideabucket_processing_window_id": bucket,
        "ideabucket_processing_version": now,
        "encrypted_chat_key": crypto::encrypt_bytes(chat_key, master)?,
        "scheduled_send_at": scheduled,
        "server_vault_encrypted_processing_payload": crypto::encrypt_combined(&payload, master)?,
        "client_encrypted_future_user_message": crypto::encrypt_combined(&markdown, chat_key)?,
        "client_encrypted_ideabucket_system_event": crypto::encrypt_combined(&event, chat_key)?,
        "payload_hash": payload_hash,
    }))
}
impl OpenMates {
    pub fn ideabucket(&mut self) -> IdeaBucket<'_> {
        IdeaBucket::new(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ApiKey, ClientOptions, SdkCredentials, SdkOptions};
    #[test]
    fn markdown_payload_and_settings_match_npm() {
        assert_eq!(
            ideabucket_markdown(" P ", " idea "),
            "P\n\n----- Idea 1 -----\nidea\n-----------------"
        );
        let (payload, hash) = processing_payload("P", "2026-01-02", "idea");
        assert_eq!(
            serde_json::from_str::<Value>(&payload).unwrap(),
            json!({"prompt":"P","bucket_id":"2026-01-02","processing_window_id":"2026-01-02","ideas":[{"index":1,"type":"text","text":"idea"}]})
        );
        assert_eq!(hash, hex(&Sha256::digest(payload.as_bytes())));
        let defaults = settings_value(None, None).unwrap();
        assert_eq!(
            (
                defaults["processingTimes"].clone(),
                defaults["source"].clone()
            ),
            (json!(["09:00"]), json!("default"))
        );
        let stored = settings_value(
            Some(&json!({"processing_prompt":" Go ","processing_times":"17:30, 09:00,09:00"})),
            Some(("e1", Some(3))),
        )
        .unwrap();
        assert_eq!(
            stored,
            json!({"processingPrompt":"Go","processingTimes":["09:00","17:30"],"source":"account","entryId":"e1","itemVersion":3})
        );
        assert!(settings_value(Some(&json!({"processing_times":"25:00"})), None).is_err());
    }
    #[test]
    fn payload_is_encrypted_with_master_and_chat_keys_and_roundtrips() {
        let (master, chat) = ([3u8; 32], [4u8; 32]);
        let p = build_payload(
            "c1",
            "b1",
            1_800_000_000,
            "P",
            "idea",
            1_700_000_000,
            &master,
            &chat,
        )
        .unwrap();
        let open = |field: &str, key: &[u8; 32]| {
            crypto::decrypt_combined(p[field].as_str().unwrap(), key).unwrap()
        };
        assert_eq!(
            open("encrypted_draft_md", &master),
            ideabucket_markdown("P", "idea")
        );
        assert_eq!(
            open("encrypted_draft_preview", &master),
            "IdeaBucket b1: idea"
        );
        assert_eq!(
            open("client_encrypted_future_user_message", &chat),
            ideabucket_markdown("P", "idea")
        );
        let event: Value =
            serde_json::from_str(&open("client_encrypted_ideabucket_system_event", &chat)).unwrap();
        assert_eq!(
            (event["source"].clone(), event["bucket_id"].clone()),
            (json!("openmates_sdk"), json!("b1"))
        );
        assert_eq!(
            crypto::decrypt_bytes(p["encrypted_chat_key"].as_str().unwrap(), &master)
                .unwrap()
                .as_slice(),
            &chat
        );
        let vault = open("server_vault_encrypted_processing_payload", &master);
        assert_eq!(
            p["payload_hash"].as_str().unwrap(),
            hex(&Sha256::digest(vault.as_bytes()))
        );
        assert_eq!(
            (
                p["ideabucket"].clone(),
                p["ideabucket_processing_version"].clone()
            ),
            (json!(true), json!(1_700_000_000))
        );
    }
    #[tokio::test]
    async fn empty_text_bucket_ids_and_credentials_are_refused_before_transport() {
        let mut api = OpenMates::new(SdkOptions {
            api_url: "http://127.0.0.1:1".into(),
            credentials: SdkCredentials::ApiKey(
                ApiKey::new("sk-api-ideaOwnerA.localSetupSuffix").unwrap(),
            ),
            device_id: "synthetic-idea-device".into(),
            client_options: ClientOptions::default(),
        })
        .unwrap();
        assert!(matches!(
            api.ideabucket()
                .add(IdeaBucketAddInput {
                    text: "  ".into(),
                    ..Default::default()
                })
                .await,
            Err(Error::Invalid(_))
        ));
        assert!(matches!(
            api.ideabucket().status(Some("")).await,
            Err(Error::Invalid(_))
        ));
        let mut anon = OpenMates::new(SdkOptions {
            api_url: "http://127.0.0.1:1".into(),
            credentials: SdkCredentials::Anonymous {
                anonymous_id: "synthetic-idea-anon".into(),
            },
            device_id: "synthetic-idea-device".into(),
            client_options: ClientOptions::default(),
        })
        .unwrap();
        assert_eq!(
            anon.ideabucket().status(None).await,
            Err(Error::Authentication)
        );
        assert_eq!(
            anon.ideabucket().process("b1", true).await,
            Err(Error::Authentication)
        );
    }
}
