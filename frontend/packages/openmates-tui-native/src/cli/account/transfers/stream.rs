//! `settings notifications stream`: npm `streamNotifications` over the shared
//! authenticated SSE transport. Each event is written and flushed as it
//! arrives; `--count` stops after that many printed events.
use super::{
    CliError, CliOutput, Invocation, failed, handlers, ordered_json, output, required_number,
    value_json,
};
use crate::client::{Client, SseMessage, SseOpen};
use serde_json::Value;

/// One printable event: parsed JSON, or npm's `{event, data}` fallback.
pub(super) enum Notification {
    Json(Value),
    Raw { event: String, data: String },
}
/// npm filter and decoding; `None` skips a non-notification event.
pub(super) fn decode(message: SseMessage) -> Option<Notification> {
    if message
        .event
        .as_deref()
        .is_some_and(|event| !event.is_empty() && event != "notification")
    {
        return None;
    }
    Some(match serde_json::from_str::<Value>(&message.data) {
        Ok(value) => Notification::Json(value),
        Err(_) => Notification::Raw {
            event: message.event.unwrap_or_else(|| "message".into()),
            data: message.data,
        },
    })
}
pub(super) fn render(notification: Notification, json: bool) -> Result<String, CliError> {
    match (notification, json) {
        (Notification::Json(value), true) => value_json(&value),
        (Notification::Json(value), false) => super::super::reminders::ordinary(&value),
        (Notification::Raw { event, data }, true) => ordered_json(&[
            ("event", Value::String(event)),
            ("data", Value::String(data)),
        ]),
        (Notification::Raw { event, data }, false) => {
            let value = serde_json::json!({"event": event, "data": data});
            let keys = ["event".to_owned(), "data".to_owned()];
            super::super::reminders::ordinary_with_root_keys(&value, Some(&keys))
        }
    }
}

pub(super) async fn notifications(
    i: &Invocation,
    client: &mut Client,
) -> Result<CliOutput, CliError> {
    use std::io::Write;
    handlers::flags(i, &["count"])?;
    let count = if i.has("count") {
        Some(required_number(i, "count")?)
    } else {
        None
    };
    let mut stream = match client.open_sse("/v1/notifications/stream").await? {
        SseOpen::Stream(stream) => stream,
        SseOpen::Status(status) => {
            return Err(failed(format!("SSE request failed with HTTP {status}")));
        }
    };
    let json = i.boolean("json");
    let mut received = 0u64;
    while let Some(message) = stream.next().await? {
        let Some(notification) = decode(message) else {
            continue;
        };
        let text = render(notification, json)?;
        let mut stdout = std::io::stdout().lock();
        stdout
            .write_all(text.as_bytes())
            .and_then(|()| stdout.flush())
            .map_err(|_| CliError::Client(crate::error::Error::Io))?;
        received += 1;
        if count.is_some_and(|count| received as f64 >= count) {
            break;
        }
    }
    Ok(output(String::new(), String::new()))
}
