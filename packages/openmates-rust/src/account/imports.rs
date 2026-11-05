//! Account Import V1 flow (port of the npm CLI `runAccountImport`): preview,
//! confirm, server-side scan and compression in cursor-checked batches, then
//! client-side encryption of the sanitized chats and completion. Imported chats
//! are always personal: a fresh random chat key wrapped by the master key, and
//! every field encrypted with that chat key exactly like a natively sent chat.
//! The caller owns confirmation; nothing here prompts, prints or reads files.
use super::Account;
use super::imports_parse::{
    ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE, COMPRESSION_SUMMARY_CATEGORY, ParsedAccountImport,
    ParsedImportChat, ParsedImportMessage, append_compression_summary,
    build_account_import_message_batches, prefix16,
};
use crate::client::overview::parse_time;
use crate::{Error, Result, crypto};
use reqwest::Method;
use serde_json::{Value, json};
use std::collections::BTreeMap;

/// The preview result shared by `--dry-run` and the full import.
#[derive(Clone, Debug, PartialEq)]
pub struct AccountImportPlan {
    /// `{source, parser_format, parsed{...}, preview}` exactly as the npm CLI prints it.
    pub result: Value,
    pub selected_count: i64,
}
impl AccountImportPlan {
    pub fn can_import(&self) -> bool {
        self.result["preview"]["can_import"] != Value::Bool(false)
    }
    pub fn blocked_reason(&self) -> String {
        match &self.result["preview"]["reason"] {
            Value::Null => "unknown".into(),
            Value::String(s) => s.clone(),
            other => other.to_string(),
        }
    }
}

/// JavaScript `Number(value)` (missing/`undefined` uses `missing`).
fn js_number(value: Option<&Value>, missing: f64) -> f64 {
    match value {
        None => missing,
        Some(Value::Null) => 0.0,
        Some(Value::Number(n)) => n.as_f64().unwrap_or(f64::NAN),
        Some(Value::Bool(b)) => f64::from(u8::from(*b)),
        Some(Value::String(s)) if s.trim().is_empty() => 0.0,
        Some(Value::String(s)) => s.trim().parse().unwrap_or(f64::NAN),
        Some(_) => f64::NAN,
    }
}
fn number_or(value: &Value, fallback: f64) -> f64 {
    value.as_f64().unwrap_or(fallback)
}
fn utf16_len(text: &str) -> usize {
    text.encode_utf16().count()
}
fn seconds(value: Option<&str>, now: u64) -> u64 {
    value
        .and_then(|v| parse_time(Some(&Value::String(v.into())), 0))
        .filter(|ms| *ms >= 0)
        .map_or(now, |ms| (ms / 1000) as u64)
}
fn acknowledged(value: &Value, sequence: usize) -> bool {
    value["status"] == "acknowledged" && value["sequence"].as_f64() == Some(sequence as f64)
}

impl Account<'_> {
    async fn imports(
        &mut self,
        method: Method,
        route: String,
        body: Option<Value>,
    ) -> Result<Value> {
        self.client.require_session()?;
        self.client.request(method, &route, body).await
    }
    fn import_route(import_id: &str, action: &str) -> Result<String> {
        let id = super::settings_ops::segment(import_id, "Invalid account import ID.")?;
        Ok(format!("/v1/account-imports/{id}/{action}"))
    }

    /// POST /v1/account-imports/preview and the npm selection arithmetic.
    pub async fn preview_account_import(
        &mut self,
        parsed: &ParsedAccountImport,
        select_all: bool,
    ) -> Result<AccountImportPlan> {
        let fingerprints: Vec<&str> = parsed
            .chats
            .iter()
            .map(|c| c.source_fingerprint.as_str())
            .collect();
        let tokens: Vec<usize> = parsed
            .chats
            .iter()
            .map(|c| {
                c.messages
                    .iter()
                    .map(|m| utf16_len(&m.content))
                    .sum::<usize>()
                    .div_ceil(4)
            })
            .collect();
        let preview = self
            .imports(
                Method::POST,
                "/v1/account-imports/preview".into(),
                Some(json!({
                    "source": parsed.source.as_str(),
                    "parser_format": parsed.parser_format.as_str(),
                    "chat_count": parsed.chats.len(),
                    "source_fingerprints": fingerprints,
                    "estimated_tokens": 0,
                    "estimated_tokens_by_chat": tokens,
                    "estimated_bytes": 0,
                })),
            )
            .await?;
        let default_count = number_or(&preview["default_selection_count"], 0.0);
        let max_count = number_or(&preview["max_batch_count"], default_count);
        let chats = parsed.chats.len() as f64;
        let selected = if select_all {
            chats.min(max_count)
        } else {
            default_count.min(chats).min(max_count)
        };
        let selected_count = if selected.is_finite() {
            selected.trunc() as i64
        } else {
            0
        };
        Ok(AccountImportPlan {
            result: json!({
                "source": parsed.source.as_str(),
                "parser_format": parsed.parser_format.as_str(),
                "parsed": {
                    "chat_count": parsed.chats.len(),
                    "selected_count": selected_count,
                    "skipped_domains": parsed.skipped_domains,
                    "source_fingerprints": fingerprints,
                },
                "preview": preview,
            }),
            selected_count,
        })
    }

    /// Runs a confirmed import. The caller already checked `can_import`, a
    /// positive selection and the user's confirmation.
    pub async fn run_account_import(
        &mut self,
        parsed: &ParsedAccountImport,
        plan: &AccountImportPlan,
    ) -> Result<Value> {
        if !plan.can_import() || plan.selected_count <= 0 {
            return Err(Error::Invalid("No chats are selected for import."));
        }
        let import_id = plan.result["preview"]["import_id"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
        let count = (plan.selected_count as usize).min(parsed.chats.len());
        let selected = &parsed.chats[..count];
        let fingerprints: Vec<&str> = selected
            .iter()
            .map(|c| c.source_fingerprint.as_str())
            .collect();
        let confirmation = self
            .imports(
                Method::POST,
                Self::import_route(&import_id, "confirm")?,
                Some(json!({"selected_fingerprints": fingerprints})),
            )
            .await?;
        let status_route = Self::import_route(&import_id, "status")?;
        let initial_status = self
            .imports(Method::GET, status_route.clone(), None)
            .await?;
        if js_number(initial_status.get("last_scan_sequence"), -1.0) != -1.0
            || js_number(initial_status.get("last_compression_sequence"), -1.0) != -1.0
        {
            return Err(Error::Invalid(
                "Resuming this import requires the client-held sanitized batch state.",
            ));
        }
        let batches =
            build_account_import_message_batches(selected, ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE)
                .map_err(|_| Error::Protocol)?;
        let mut sanitized: Vec<ParsedImportChat> = selected
            .iter()
            .map(|c| ParsedImportChat {
                messages: vec![],
                ..c.clone()
            })
            .collect();
        let mut sanitized_batches: Vec<(Vec<ParsedImportMessage>, usize)> = vec![];
        let mut scan_batches = vec![];
        let scan_route = Self::import_route(&import_id, "scan")?;
        for (sequence, batch) in batches.iter().enumerate() {
            let scanned = self
                .imports(
                    Method::POST,
                    scan_route.clone(),
                    Some(json!({
                        "batch_id": batch.batch_id,
                        "sequence": sequence,
                        "final_batch": sequence + 1 == batches.len(),
                        "chats": [batch.chat],
                    })),
                )
                .await?;
            if !acknowledged(&scanned, sequence)
                || scanned["batch_id"].as_str() != Some(batch.batch_id.as_str())
                || !scanned["chats"].is_array()
            {
                return Err(Error::Invalid(
                    "Account import scan batch was not acknowledged at the expected cursor.",
                ));
            }
            let chat = scanned["chats"]
                .get(0)
                .filter(|c| !c.is_null())
                .ok_or(Error::Invalid(
                    "Account import scan acknowledgement omitted the sanitized chat.",
                ))?;
            let messages: Vec<ParsedImportMessage> =
                serde_json::from_value(chat["messages"].clone())?;
            sanitized[batch.chat_index]
                .messages
                .extend(messages.iter().cloned());
            sanitized_batches.push((messages, batch.chat_index));
            scan_batches.push(scanned);
        }
        let post_scan_status = self
            .imports(Method::GET, status_route.clone(), None)
            .await?;
        if js_number(post_scan_status.get("last_scan_sequence"), f64::NAN)
            != (batches.len() as f64 - 1.0)
        {
            return Err(Error::Invalid(
                "Account import scan status cursor did not advance as expected.",
            ));
        }
        let mut summaries: BTreeMap<String, String> = BTreeMap::new();
        let mut compression_batches = vec![];
        let compress_route = Self::import_route(&import_id, "compress")?;
        for (sequence, (messages, _)) in sanitized_batches.iter().enumerate() {
            let batch = &batches[sequence];
            let fingerprint = &batch.source_fingerprint;
            let final_batch = batches
                .get(sequence + 1)
                .is_none_or(|next| &next.source_fingerprint != fingerprint);
            let mut body = json!({
                "batch_id": format!("compress-{}-{}", prefix16(fingerprint), batch.chunk_index),
                "sequence": sequence,
                "final_batch": final_batch,
                "scan_sequence": sequence,
                "source_fingerprint": fingerprint,
                "sanitized_messages": messages,
            });
            if let Some(prior) = summaries.get(fingerprint) {
                body["prior_summary"] = json!(prior);
            }
            let compressed = self
                .imports(Method::POST, compress_route.clone(), Some(body))
                .await?;
            if !acknowledged(&compressed, sequence) {
                return Err(Error::Invalid(
                    "Account import compression batch was not acknowledged at the expected cursor.",
                ));
            }
            if let Some(summary) = compressed["summary"]
                .as_str()
                .filter(|s| !s.trim().is_empty())
            {
                summaries.insert(fingerprint.clone(), summary.to_owned());
            }
            compression_batches.push(compressed);
        }
        let post_compression_status = self.imports(Method::GET, status_route, None).await?;
        if js_number(
            post_compression_status.get("last_compression_sequence"),
            f64::NAN,
        ) != (sanitized_batches.len() as f64 - 1.0)
        {
            return Err(Error::Invalid(
                "Account import compression status cursor did not advance as expected.",
            ));
        }
        for chat in &mut sanitized {
            let summary = summaries.get(&chat.source_fingerprint).cloned();
            append_compression_summary(chat, summary.as_deref());
        }
        let encrypted = self.encrypt_import_chats(&sanitized)?;
        let persistence = self
            .imports(
                Method::POST,
                Self::import_route(&import_id, "persist-encrypted")?,
                Some(json!({"chats": encrypted})),
            )
            .await?;
        let complete = self
            .imports(
                Method::POST,
                Self::import_route(&import_id, "complete")?,
                Some(json!({
                    "imported_chat_ids": persistence["imported_chat_ids"].as_array().cloned().unwrap_or_default(),
                    "source_fingerprints": sanitized.iter().map(|c| c.source_fingerprint.as_str()).collect::<Vec<_>>(),
                    "encrypted_record_counts": persistence.get("encrypted_record_counts").filter(|v| !v.is_null()).cloned().unwrap_or(json!({"chats": 0, "messages": 0})),
                    "client_failures": persistence.get("failures").filter(|v| !v.is_null()).cloned().unwrap_or(json!([])),
                })),
            )
            .await?;
        let mut out = plan.result.clone();
        out["import_id"] = json!(import_id);
        out["confirmation"] = confirmation;
        out["initial_status"] = initial_status;
        out["post_scan_status"] = post_scan_status;
        out["scan"] = scan_batches.last().cloned().unwrap_or(Value::Null);
        out["scan_batches"] = json!(scan_batches);
        out["compression"] = compression_batches.last().cloned().unwrap_or(Value::Null);
        out["compression_batches"] = json!(compression_batches);
        out["post_compression_status"] = post_compression_status;
        out["persistence"] = persistence;
        out["complete"] = complete;
        Ok(out)
    }

    /// Personal chats: random chat key wrapped by the master key (IV||ciphertext,
    /// like the send path), every field in the chat-key combined format.
    fn encrypt_import_chats(&mut self, chats: &[ParsedImportChat]) -> Result<Vec<Value>> {
        let master = self.client.require_session()?.master_key.clone();
        let now = crate::client::now_ms() / 1000;
        let mut out = vec![];
        for chat in chats {
            let key = crypto::random_key();
            let wrapped = crypto::server_fields::encrypt_bytes(key.as_ref(), &master, &[])?;
            let mut messages = vec![];
            let mut previous_user: Option<String> = None;
            for message in &chat.messages {
                let message_id = uuid::Uuid::new_v4().to_string();
                let identity = (message.role == "assistant")
                    .then_some(message.imported_assistant_identity.as_ref())
                    .flatten();
                let summary =
                    message.provider_metadata["import_type"] == COMPRESSION_SUMMARY_CATEGORY;
                let sender = identity.map_or(
                    match message.role.as_str() {
                        "assistant" => "AI assistant",
                        "system" => "System",
                        _ => "User",
                    },
                    |i| i.sender_name.as_str(),
                );
                let mut row = json!({
                    "message_id": message_id,
                    "role": message.role,
                    "encrypted_content": crypto::encrypt_combined(&message.content, &key)?,
                    "encrypted_sender_name": crypto::encrypt_combined(sender, &key)?,
                    "created_at": seconds(message.created_at.as_deref(), now),
                    "updated_at": now,
                });
                if let Some(identity) = identity {
                    row["encrypted_category"] =
                        json!(crypto::encrypt_combined(&identity.category, &key)?);
                    row["encrypted_model_name"] =
                        json!(crypto::encrypt_combined(&identity.model_name, &key)?);
                } else if summary {
                    let model = if chat.selected_source.is_empty() {
                        "other"
                    } else {
                        &chat.selected_source
                    };
                    row["encrypted_category"] = json!(crypto::encrypt_combined(
                        COMPRESSION_SUMMARY_CATEGORY,
                        &key
                    )?);
                    row["encrypted_model_name"] = json!(crypto::encrypt_combined(model, &key)?);
                }
                if message.role == "assistant"
                    && let Some(user) = &previous_user
                {
                    row["user_message_id"] = json!(user);
                }
                if message.role == "user" {
                    previous_user = Some(message_id);
                }
                messages.push(row);
            }
            let title = chat
                .title
                .as_deref()
                .filter(|t| !t.is_empty())
                .unwrap_or("Imported chat");
            out.push(json!({
                "chat_id": uuid::Uuid::new_v4().to_string(),
                "encrypted_title": crypto::encrypt_combined(title, &key)?,
                "encrypted_chat_key": wrapped,
                "created_at": seconds(chat.created_at.as_deref(), now),
                "updated_at": seconds(chat.updated_at.as_deref(), now),
                "source_fingerprint": chat.source_fingerprint,
                "messages": messages,
            }));
        }
        Ok(out)
    }

    /// POST /v1/settings/import-chat with an already parsed `{chats:[...]}` payload.
    pub async fn import_chat_export(&mut self, payload: Value) -> Result<Value> {
        if !payload["chats"].is_array() {
            return Err(Error::Invalid(
                "JSON import must contain a chats array, a chat object, or messages.",
            ));
        }
        self.imports(
            Method::POST,
            "/v1/settings/import-chat".into(),
            Some(payload),
        )
        .await
    }
}

#[cfg(test)]
#[path = "imports_tests.rs"]
mod tests;
