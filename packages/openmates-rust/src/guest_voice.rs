//! Guest voice wire format and speech requests in the shared client core.
//! The browser supplies microphone chunks and plays returned audio. Guest calls
//! use a credential-free first-party endpoint (video-call.guest-calls).

use serde::Deserialize;
use serde_json::{Value, json};
use url::Url;

use crate::client::assistant_speech::project_assistant_speech;
use crate::web_parse::voice_cues::strip_voice_cues;

const PRIVACY_VERSION: u8 = 3;

#[derive(Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case")]
enum Request {
    Connect {
        base: String,
        anonymous_id: String,
        #[serde(default)]
        instant_feedback: bool,
    },
    Microphone {
        data: String,
    },
    Receive {
        frame: String,
    },
    Speech {
        base: String,
        anonymous_id: String,
        markdown: String,
        language: String,
    },
}

fn connect(base: &str, anonymous_id: &str, instant_feedback: bool) -> Result<Value, &'static str> {
    let mut url = Url::parse(base).map_err(|_| "invalid_guest_voice_url")?;
    let scheme = match url.scheme() {
        "https" => "wss",
        "http" => "ws",
        _ => return Err("invalid_guest_voice_url"),
    };
    url.set_scheme(scheme)
        .map_err(|_| "invalid_guest_voice_url")?;
    url.set_path("/v1/voice-call/guest");
    url.set_query(None);
    url.set_fragment(None);
    url.query_pairs_mut()
        .append_pair("anonymous_id", anonymous_id);
    let mut start = json!({"type":"start","privacy_ack_version":PRIVACY_VERSION});
    if instant_feedback {
        start["instant_feedback"] = true.into();
    }
    Ok(json!({
        "url": url.as_str(),
        "start": start.to_string(),
        "pause": json!({"type":"audio_stream_end"}).to_string(),
        "quiet": json!({"type":"audio_stream_end","verified_silence":true}).to_string(),
        "ping": json!({"type":"ping"}).to_string(),
        "hangup": json!({"type":"hangup"}).to_string(),
    }))
}

fn feedback_clip(frame: &Value) -> Option<Value> {
    let id = frame["clip"]["clip_id"]
        .as_str()
        .filter(|id| id.len() <= 96)?;
    let url = frame["clip"]["asset_url"].as_str()?;
    let path = url
        .strip_prefix("/audio/assistant-acknowledgements/")?
        .strip_suffix(".mp3")?;
    let valid_part = |part: &str| {
        !part.is_empty()
            && part.len() <= 64
            && part
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-".contains(&byte))
    };
    if path.split('/').count() != 3 || !path.split('/').all(valid_part) || !valid_part(id) {
        return None;
    }
    Some(json!({"id":id,"url":url}))
}

fn receive(frame: &str) -> Result<Value, &'static str> {
    let frame: Value = serde_json::from_str(frame).map_err(|_| "invalid_message")?;
    Ok(match frame["type"].as_str() {
        Some("ready") => json!({"type":"ready"}),
        Some("ended") => json!({"type":"ended"}),
        Some("waiting") => match (frame["active"].as_bool(), frame["line"].as_str()) {
            (Some(true), Some("waiting_start")) => {
                let mut waiting = json!({"type":"waiting","active":true,"line":"waiting_start"});
                if frame.get("clip").is_some() {
                    waiting["clip"] = feedback_clip(&frame).unwrap_or(Value::Null);
                }
                waiting
            }
            (Some(false), Some("waiting_resume")) => {
                json!({"type":"waiting","active":false,"line":"waiting_resume"})
            }
            _ => return Err("invalid_frame"),
        },
        Some(kind @ ("voice_feedback" | "voice_feedback_stop")) => feedback_clip(&frame)
            .map(|clip| json!({"type":kind,"clip":clip}))
            .unwrap_or(Value::Null),
        Some("error")
            if frame["signup_required"] == true || frame["code"] == "anonymous_usage_limit" =>
        {
            json!({"type":"limit"})
        }
        Some("error") => {
            json!({"type":"error","code":frame["code"].as_str().unwrap_or("call_failed")})
        }
        Some("transcript") => {
            let Some(text) = frame["text"]
                .as_str()
                .map(str::trim)
                .filter(|text| !text.is_empty())
            else {
                return Ok(Value::Null);
            };
            let turn_id = match &frame["turn_id"] {
                Value::String(id) => id.clone(),
                Value::Number(id) => id.to_string(),
                _ => "guest-turn".into(),
            };
            json!({"type":"transcript","text":text,"messageId":turn_id,"submitted":frame["final"] == true})
        }
        _ => Value::Null,
    })
}

/// Builds socket frames and speech requests, and reads the guest call's server
/// events. Returns a fixed error code for a malformed command, frame, or URL.
pub fn plan_json(input: &str) -> Result<String, &'static str> {
    let request = serde_json::from_str(input).map_err(|_| "invalid_guest_voice_request")?;
    let result = match request {
        Request::Connect {
            base,
            anonymous_id,
            instant_feedback,
        } => connect(&base, &anonymous_id, instant_feedback)?,
        Request::Microphone { data } => json!({"type":"mic_audio","data":data}),
        Request::Receive { frame } => receive(&frame)?,
        Request::Speech {
            base,
            anonymous_id,
            markdown,
            language,
        } => {
            let mut url = Url::parse(&base).map_err(|_| "invalid_guest_voice_url")?;
            url.set_path("/v1/anonymous/speech");
            url.set_query(None);
            url.set_fragment(None);
            let bodies: Vec<_> = project_assistant_speech(&strip_voice_cues(&markdown), &language)
                .into_iter()
                .map(|segment| {
                    json!({
                        "anonymous_id":anonymous_id,
                        "text":segment.speakable_text,
                        "language":language
                    })
                    .to_string()
                })
                .collect();
            json!({"url":url.as_str(),"bodies":bodies})
        }
    };
    Ok(result.to_string())
}

#[cfg(test)]
#[path = "guest_voice_tests.rs"]
mod tests;
