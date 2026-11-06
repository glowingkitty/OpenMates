//! IdeaBucket capture (npm addIdeaBucketText / settings / status / process).
//! The captured ideas become an encrypted draft (master key) plus a fresh chat
//! key; the server only receives ciphertext and sparse scheduling metadata.
use super::Account;
use crate::{Error, Result};
use reqwest::Method;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

const APP_ID: &str = "ideabucket";
const SETTINGS_TYPE: &str = "processing_settings";
pub const IDEABUCKET_DEFAULT_PROCESSING_PROMPT: &str = "These are my captured ideas for today. Please process them, group related thoughts, suggest next actions, and ask clarifying questions where needed:\n\nIf an idea requires deeper work, create or suggest sub-chats for focused research, planning, todos, docs, or implementation.";

/// Text capture input (npm addIdeaBucketText params).
#[derive(Clone, Default)]
pub struct IdeaBucketText<'a> {
    pub text: &'a str,
    pub chat_id: Option<&'a str>,
    pub bucket_id: Option<&'a str>,
    pub scheduled_send_at: Option<i64>,
    pub prompt: Option<&'a str>,
}

fn minutes(time: &str) -> Option<u32> {
    let (h, m) = time.split_once(':')?;
    if h.len() != 2 || m.len() != 2 {
        return None;
    }
    let (h, m) = (h.parse::<u32>().ok()?, m.parse::<u32>().ok()?);
    (h < 24 && m < 60).then_some(h * 60 + m)
}
/// npm normalizeIdeaBucketProcessingTimes with its exact messages.
pub fn normalize_processing_times(value: &Value) -> std::result::Result<Vec<String>, String> {
    let raw: Vec<String> = match value {
        Value::Array(items) => items
            .iter()
            .map(|v| {
                v.as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| v.to_string())
            })
            .collect(),
        Value::String(text) => text.split(',').map(str::to_owned).collect(),
        _ => vec!["09:00".into()],
    };
    let mut times: Vec<String> = vec![];
    for time in raw
        .iter()
        .map(|t| t.trim().to_owned())
        .filter(|t| !t.is_empty())
    {
        if !times.contains(&time) {
            times.push(time);
        }
    }
    times.sort_by_key(|t| minutes(t).unwrap_or(u32::MAX));
    if times.is_empty() || times.len() > 3 {
        return Err("IdeaBucket processing_times must include one to three HH:MM values.".into());
    }
    if let Some(bad) = times.iter().find(|t| minutes(t).is_none()) {
        return Err(format!(
            "Invalid IdeaBucket processing time '{bad}'. Expected HH:MM in 24-hour format."
        ));
    }
    Ok(times)
}
fn settings_json(
    data: Option<&Value>,
    entry: Option<(&Value, &Value)>,
) -> std::result::Result<Value, String> {
    let prompt = data
        .and_then(|d| d["processing_prompt"].as_str())
        .map(str::trim)
        .filter(|p| !p.is_empty())
        .unwrap_or(IDEABUCKET_DEFAULT_PROCESSING_PROMPT);
    let times =
        normalize_processing_times(data.map(|d| &d["processing_times"]).unwrap_or(&Value::Null))?;
    let mut value = json!({"processingPrompt":prompt,"processingTimes":times,"source":"default"});
    if let Some((id, version)) = entry {
        value["entryId"] = id.clone();
        value["itemVersion"] = version.clone();
        value["source"] = json!("account");
    }
    Ok(value)
}
/// Next HH:MM slot after `now` (UTC; npm uses the host time zone).
pub(crate) fn next_send_at(now: i64, times: &[String]) -> i64 {
    let day = now - now.rem_euclid(86_400);
    times
        .iter()
        .filter_map(|t| minutes(t))
        .map(|m| {
            let candidate = day + i64::from(m) * 60;
            if candidate <= now {
                candidate + 86_400
            } else {
                candidate
            }
        })
        .min()
        .unwrap_or(day + 86_400 + 9 * 3600)
}
/// UTC calendar date (npm `toISOString().slice(0, 10)`).
pub(crate) fn today(now: i64) -> String {
    // Civil-from-days (H. Hinnant), valid for the proleptic Gregorian calendar.
    let z = now.div_euclid(86_400) + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}")
}

/// One captured idea (npm `IdeaBucketPreparedIdea`): markdown content, preview
/// text and the server-processable payload object (without its `index`).
pub(crate) struct PreparedIdea {
    pub content: String,
    pub preview: String,
    pub payload: Value,
}

/// npm `buildIdeaBucketMarkdown`.
pub(crate) fn ideas_markdown(prompt: &str, ideas: &[PreparedIdea]) -> String {
    let mut blocks = vec![prompt.trim().to_owned()];
    for (index, idea) in ideas.iter().enumerate() {
        blocks.push(format!(
            "----- Idea {} -----\n{}\n-----------------",
            index + 1,
            idea.content.trim()
        ));
    }
    blocks.join("\n\n")
}

/// The `update_draft` payload and the npm result (without `draftV`).
#[allow(clippy::too_many_arguments)]
pub(crate) fn ideas_draft(
    chat_id: &str,
    bucket: &str,
    scheduled: i64,
    prompt: &str,
    ideas: &[PreparedIdea],
    version: i64,
    master: &[u8; 32],
    chat_key: &[u8; 32],
) -> Result<(Value, Value)> {
    if ideas.is_empty() {
        return Err(Error::Invalid("IdeaBucket add requires at least one idea."));
    }
    let markdown = ideas_markdown(prompt, ideas);
    let joined = ideas.iter().map(|i| i.preview.as_str()).collect::<Vec<_>>().join(" ");
    let preview_text: String = joined.trim().chars().take(120).collect();
    let preview = format!("IdeaBucket {bucket}: {preview_text}");
    let mut numbered = vec![];
    for (index, idea) in ideas.iter().enumerate() {
        let mut item = idea.payload.as_object().cloned().ok_or(Error::Protocol)?;
        item.insert("index".into(), json!(index + 1));
        numbered.push(Value::Object(item));
    }
    let payload = json!({"prompt":prompt,"processing_window_id":bucket,"ideas":numbered}).to_string();
    let payload_hash = Sha256::digest(payload.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    let encrypt = |bytes: &[u8], key: &[u8; 32]| crate::work::legacy_encrypt(bytes, key);
    let draft = json!({
        "chat_id":chat_id,
        "encrypted_draft_md":encrypt(markdown.as_bytes(), master)?,
        "encrypted_draft_preview":encrypt(preview.as_bytes(), master)?,
        "ideabucket":true,
        "ideabucket_processing_window_id":bucket,
        "ideabucket_processing_version":version,
        "encrypted_chat_key":encrypt(chat_key, master)?,
        "scheduled_send_at":scheduled,
        "server_vault_encrypted_processing_payload":encrypt(payload.as_bytes(), master)?,
        "client_encrypted_future_user_message":encrypt(markdown.as_bytes(), chat_key)?,
        "client_encrypted_ideabucket_system_event":encrypt(
            json!({"type":"ideabucket_triggered_send","processing_window_id":bucket,"source":"openmates_cli"}).to_string().as_bytes(),
            chat_key,
        )?,
        "payload_hash":payload_hash,
    });
    let result = json!({"chatId":chat_id,"bucketId":bucket,"processingWindowId":bucket,"scheduledSendAt":scheduled,
        "processingPayloadSynced":true,"payloadHash":payload_hash,"markdown":markdown,"preview":preview});
    Ok((draft, result))
}

/// Single text idea (npm addIdeaBucketText).
#[cfg(test)]
#[allow(clippy::too_many_arguments)]
pub(crate) fn text_draft(
    chat_id: &str,
    bucket: &str,
    scheduled: i64,
    prompt: &str,
    text: &str,
    now: i64,
    master: &[u8; 32],
    chat_key: &[u8; 32],
) -> Result<(Value, Value)> {
    ideas_draft(chat_id, bucket, scheduled, prompt, &[text_idea(text)], now, master, chat_key)
}

fn text_idea(text: &str) -> PreparedIdea {
    PreparedIdea {
        content: text.to_owned(),
        preview: text.to_owned(),
        payload: json!({"type":"text","text":text}),
    }
}

/// `--chat` (validated) or a fresh chat ID.
pub(crate) fn ideabucket_chat_id(chat_id: Option<&str>) -> Result<String> {
    let chat_id = chat_id
        .map(str::to_owned)
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    uuid::Uuid::parse_str(&chat_id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
    Ok(chat_id)
}

impl Account<'_> {
    /// Current settings (latest account entry, else defaults).
    pub async fn ideabucket_settings(&mut self) -> Result<Value> {
        let mut entries = self
            .memories()
            .await?
            .into_iter()
            .filter(|m| m["app_id"] == APP_ID && m["item_type"] == SETTINGS_TYPE)
            .collect::<Vec<_>>();
        entries.sort_by(|a, b| {
            b["updated_at"]
                .as_f64()
                .unwrap_or(0.0)
                .total_cmp(&a["updated_at"].as_f64().unwrap_or(0.0))
        });
        let value = match entries.first() {
            None => settings_json(None, None),
            Some(entry) => settings_json(
                Some(&entry["data"]),
                Some((&entry["id"], &entry["item_version"])),
            ),
        };
        value.map_err(|_| Error::Invalid("Stored IdeaBucket processing times are invalid."))
    }
    /// Save prompt/times into the encrypted account memory (create or update).
    pub async fn save_ideabucket_settings(
        &mut self,
        prompt: Option<&str>,
        times: Option<&str>,
    ) -> Result<Value> {
        let current = self.ideabucket_settings().await?;
        let data = json!({
            "processing_prompt":prompt.map(Value::from).unwrap_or(current["processingPrompt"].clone()),
            "processing_times":times.map(Value::from).unwrap_or(current["processingTimes"].clone()),
        });
        let mut settings = settings_json(Some(&data), None)
            .map_err(|_| Error::Invalid("Invalid IdeaBucket processing times."))?;
        let value = json!({"processing_prompt":settings["processingPrompt"],
            "processing_times":settings["processingTimes"].as_array().map(|t| t.iter().filter_map(Value::as_str).collect::<Vec<_>>().join(",")).unwrap_or_default()});
        match (current["entryId"].as_str(), current["itemVersion"].as_u64()) {
            (Some(id), Some(version)) => {
                self.update_memory(id, APP_ID, SETTINGS_TYPE, &value, version)
                    .await?;
                settings["entryId"] = json!(id);
                settings["itemVersion"] = json!(version);
            }
            _ => {
                let created = self.create_memory(APP_ID, SETTINGS_TYPE, &value).await?;
                settings["entryId"] = created["id"].clone();
                settings["itemVersion"] = json!(1);
            }
        }
        settings["source"] = json!("account");
        Ok(settings)
    }
    pub async fn ideabucket_status(&mut self, bucket: Option<&str>) -> Result<Value> {
        self.client.require_session()?;
        let route = match bucket {
            Some(bucket) => format!(
                "/v1/ideabucket/buckets/{}",
                super::settings_ops::segment(bucket, "Invalid IdeaBucket bucket ID.")?
            ),
            None => "/v1/ideabucket/buckets".into(),
        };
        self.client.request(Method::GET, &route, None).await
    }
    pub async fn process_ideabucket(&mut self, bucket: &str, now: bool) -> Result<Value> {
        self.client.require_session()?;
        let bucket = super::settings_ops::segment(bucket, "Invalid IdeaBucket bucket ID.")?;
        self.client
            .request(
                Method::POST,
                &format!("/v1/ideabucket/buckets/{bucket}/process"),
                Some(json!({"now":now})),
            )
            .await
    }
    /// Add one text idea to the processing bucket's encrypted draft.
    pub async fn add_ideabucket_text(&mut self, input: IdeaBucketText<'_>) -> Result<Value> {
        let text = input.text.trim();
        if text.is_empty() {
            return Err(Error::Invalid(
                "IdeaBucket text capture requires non-empty text.",
            ));
        }
        let chat_id = ideabucket_chat_id(input.chat_id)?;
        let (draft, result) = self
            .prepare_ideabucket_draft(
                &[text_idea(text)],
                &chat_id,
                input.bucket_id,
                input.scheduled_send_at,
                input.prompt,
            )
            .await?;
        self.save_ideabucket_draft(&chat_id, draft, result).await
    }
    /// Resolve bucket, schedule and prompt (account settings when omitted) and
    /// encrypt the draft for `ideas` (npm addIdeaBucketPreparedIdeas, pre-save).
    pub(crate) async fn prepare_ideabucket_draft(
        &mut self,
        ideas: &[PreparedIdea],
        chat_id: &str,
        bucket_id: Option<&str>,
        scheduled_send_at: Option<i64>,
        prompt: Option<&str>,
    ) -> Result<(Value, Value)> {
        let now = crate::work::now() as i64;
        let bucket = bucket_id.map(str::to_owned).unwrap_or_else(|| today(now));
        let settings = if prompt.is_none() || scheduled_send_at.is_none() {
            Some(self.ideabucket_settings().await?)
        } else {
            None
        };
        let scheduled = scheduled_send_at.unwrap_or_else(|| match &settings {
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
        let prompt = prompt
            .map(str::to_owned)
            .or_else(|| {
                settings
                    .as_ref()
                    .and_then(|s| s["processingPrompt"].as_str().map(str::to_owned))
            })
            .unwrap_or_else(|| IDEABUCKET_DEFAULT_PROCESSING_PROMPT.into());
        let master = self.client.require_session()?.master_key.clone();
        ideas_draft(
            chat_id,
            &bucket,
            scheduled,
            &prompt,
            ideas,
            now,
            &master,
            &crate::crypto::random_key(),
        )
    }
    /// Save a prepared draft and add the receipt's `draftV`.
    pub(crate) async fn save_ideabucket_draft(
        &mut self,
        chat_id: &str,
        draft: Value,
        mut result: Value,
    ) -> Result<Value> {
        let receipt = self
            .client
            .account_ws_receipt(
                "update_draft",
                draft,
                "draft_update_receipt",
                "chat_id",
                chat_id,
            )
            .await?;
        result["draftV"] = json!(receipt["draft_v"].as_f64().unwrap_or(0.0) as i64);
        Ok(result)
    }
}

#[cfg(test)]
#[path = "ideabucket_tests.rs"]
mod tests;
