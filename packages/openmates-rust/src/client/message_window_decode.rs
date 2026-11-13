//! Pure authenticated-page decoding/projection shared by ordinary and owned IO.
//! This does not authorize IO, access, persistence or publication. The caller
//! supplies its actual original negative observer; there is no default callback.
use super::*;

pub(in crate::client) fn decode_message_page_data(
    id: &str,
    row: &Value,
    key: Key,
    mut item: Plain<Item>,
    page: Value,
    options: &MessageWindowOptions,
    scope: &str,
    stored: bool,
    capture_browser: bool,
    mut negative_check: impl FnMut() -> Result<()>,
) -> Result<MessagePageData> {
    negative_check()?;
    let metadata_stamp = sha256(&serde_json::to_string(row)?);
    if page
        .get("chat_id")
        .and_then(Value::as_str)
        .is_some_and(|v| v != id)
    {
        return Err(Error::Forbidden);
    }
    // Aggregated saved reads must not join pages across a moving read
    // boundary/version/count. v1 ignores this private stamp as before.
    let metadata_stamp = if stored {
        sha256(&serde_json::to_string(&json!([
            metadata_stamp,
            page.get("messages_v"),
            page.get("server_message_count"),
            page.get("compression_boundary_timestamp"),
        ]))?)
    } else {
        metadata_stamp
    };
    let input = page["messages"].as_array().ok_or(Error::Protocol)?;
    if input.len() > options.limit || input.len() > MAX_MESSAGES {
        return Err(Error::Protocol);
    }
    let mut encrypted = PageCiphertextRows {
        values: vec![],
        guarded: capture_browser,
    };
    let mut messages = Plain::new(Vec::<Message>::new());
    let mut seen = std::collections::HashSet::new();
    let mut bytes = 0usize;
    let mut previous = None;
    for raw in input {
        let raw: Value = if let Some(s) = raw.as_str() {
            serde_json::from_str(s)?
        } else {
            raw.clone()
        };
        bytes = bytes
            .checked_add(
                crate::client::monitor::cached_view::bounded_bytes(&raw, usize::MAX)
                    .ok_or(Error::Protocol)?,
            )
            .ok_or(Error::Protocol)?;
        if bytes > MAX_MESSAGE_BYTES {
            return Err(Error::Protocol);
        }
        server_message_id(&raw)?;
        let (raw, message) = if raw.is_string() {
            // Preserve the legacy decoder's extra parse of string-valued rows.
            decode_chat_message(&raw, id, &key, &mut seen)?
        } else {
            crate::client::sync::decode_chat_message_owned(raw, id, &key, &mut seen)?
        };
        let message = Plain::new(message);
        if !valid_message_id(&message.id) {
            return Err(Error::Protocol);
        }
        let timestamp = raw
            .get("created_at")
            .and_then(Value::as_i64)
            .filter(|v| *v >= 0)
            .ok_or(Error::Protocol)?;
        let position = (timestamp, message.id.clone());
        if previous.as_ref().is_some_and(|p| p >= &position) {
            return Err(Error::Protocol);
        }
        if let Some(c) = &options.cursor {
            let boundary = (c.created_at, c.message_id.clone());
            if (options.direction == MessageWindowDirection::Before && position >= boundary)
                || (options.direction == MessageWindowDirection::After && position <= boundary)
            {
                return Err(Error::Protocol);
            }
        }
        previous = Some(position);
        encrypted.push(raw);
        messages.push(message.into_inner());
    }
    let has_more_before = boolean(&page, "has_more_before")?;
    let has_more_after = boolean(&page, "has_more_after")?;
    let start_cursor = cursor(&page, "start_cursor", id, &scope)?;
    let end_cursor = cursor(&page, "end_cursor", id, &scope)?;
    for (c, raw, message) in [
        (start_cursor.as_ref(), encrypted.first(), messages.first()),
        (end_cursor.as_ref(), encrypted.last(), messages.last()),
    ] {
        match (c, raw, message) {
            (Some(c), Some(raw), Some(message))
                if c.created_at == raw["created_at"].as_i64().ok_or(Error::Protocol)?
                    && c.message_id == message.id =>
            {
                ()
            }
            (None, None, None) => (),
            _ => return Err(Error::Protocol),
        }
    }
    let oversized_message = boolean(&page, "oversized_message")?;
    let oversized_message_cursor = cursor(&page, "oversized_message_cursor", id, &scope)?;
    if oversized_message != oversized_message_cursor.is_some() {
        return Err(Error::Protocol);
    }
    if (has_more_before && start_cursor.is_none() || has_more_after && end_cursor.is_none())
        && !oversized_message
    {
        return Err(Error::Protocol);
    }
    let anchor_found = boolean(&page, "anchor_found")?;
    validate_anchor(
        &options,
        &encrypted,
        anchor_found,
        oversized_message,
        oversized_message_cursor.as_ref(),
    )?;
    let mut mappings = Plain::new(Vec::<Value>::new());
    let mut per_message = Plain::new(std::collections::BTreeMap::<String, Vec<Value>>::new());
    for (raw, message) in encrypted.iter().zip(messages.iter()) {
        // Memory responses carry the mappings of released Memory bodies.
        if !stored {
            mappings.extend(crate::client::memory_privacy::response_mappings(message)?);
        }
        // Match bounded web viewing: only loaded user-message maps apply.
        if !stored && text(raw, "role") != "user" {
            continue;
        }
        let value = zeroize::Zeroizing::new(decrypt_optional(raw, "encrypted_pii_mappings", &key)?);
        if !value.is_empty() {
            let values = Plain::new(serde_json::from_str::<Vec<Value>>(&value)?);
            if text(raw, "role") == "user" {
                mappings.extend(values.iter().cloned());
            }
            if stored {
                per_message.insert(message.id.clone(), values.into_inner());
            }
        } else if stored {
            if let Some(ciphertext) = raw.get("encrypted_pii_mappings").and_then(Value::as_str) {
                // Match raw/JSON field presence: an empty encrypted field
                // projects [], but nonempty invalid decrypted JSON refuses.
                let values = Plain::new(if ciphertext.is_empty() {
                    vec![]
                } else {
                    serde_json::from_str::<Vec<Value>>(&value)?
                });
                per_message.insert(message.id.clone(), values.into_inner());
            }
        }
    }
    for message in messages.iter_mut().filter(|_| !stored) {
        let restored = crate::privacy::restore_page(&message.content, &mappings)?;
        replace_text(&mut message.content, restored);
        let restored = crate::privacy::restore_page(&message.thinking, &mappings)?;
        replace_text(&mut message.thinking, restored);
    }
    if optional_count(&page, "payload_bytes")? != Some(bytes as u64) {
        return Err(Error::Protocol);
    }
    negative_check()?;
    let chat_metadata = Plain::new(if stored {
        Some(super::super::saved_chat_read::metadata::chat(
            row, id, &key,
        )?)
    } else {
        None
    });
    let mut message_metadata =
        Plain::new(Vec::<super::super::saved_chat_read::SavedChatMessageMetadata>::new());
    if stored {
        for (raw, message) in encrypted.iter().zip(messages.iter()) {
            message_metadata.push(super::super::saved_chat_read::metadata::message_from_decoded(
                raw, message, id, &key,
            )?);
        }
    }
    let server_message_count = optional_count(&page, "server_message_count")?;
    let messages_version = optional_count(&page, "messages_v")?;
    // Exact raw wire data is retained ONLY for the explicit cache path.
    // Ordinary/native reads receive None with no extra clone/allocation.
    let incoming = if capture_browser {
        if super::super::monitor::cached_view::bounded_bytes(
            &(row, &encrypted.values),
            MAX_MESSAGE_BYTES,
        )
        .is_none()
        {
            return Err(Error::Protocol);
        }
        Some(BrowserIncomingMessagePage {
            metadata: Plain::new(row.clone()),
            messages: Plain::new(std::mem::take(&mut encrypted.values)),
            key,
        })
    } else {
        None
    };
    let window = ChatMessageWindow {
        chat: Chat {
            id: id.into(),
            title: std::mem::take(&mut item.title),
            category: std::mem::take(&mut item.category),
            messages: messages.into_inner(),
        },
        has_more_before,
        has_more_after,
        anchor_found,
        start_cursor,
        end_cursor,
        server_message_count,
        messages_version,
        oversized_message,
        oversized_message_cursor,
        payload_bytes: bytes,
        pii_restoration: "page_local".into(),
        history_complete: false,
    };
    let result = Plain::new(MessagePageData {
        incoming,
        window,
        mappings: per_message.into_inner(),
        metadata_stamp,
        chat_metadata: chat_metadata.into_inner(),
        message_metadata: message_metadata.into_inner(),
    });
    negative_check()?;
    Ok(result.into_inner())
}

#[cfg(test)]
#[path = "message_window_decode_tests.rs"]
mod tests;
