//! Worker binding of the core frame-ingest and chat-admission entries.
//!
//! The page keeps the socket and forwards raw chat frames; the core `Client`
//! this handle owns applies them (`Client::ingest_socket_frames`) and loads
//! chats the page created (`Client::admit_chat`). Same handle/generation guard
//! as the neighbouring `BrowserCoreClient` methods; errors are fixed codes only.
//! Spec: `specifications/architecture/sync`.
use super::*;

/// Most frames one ingest call accepts; the page batches below this.
const MAX_FRAMES: usize = 256;
/// Largest `frames_json` accepted, so a hostile page cannot pin the Worker.
const MAX_FRAMES_BYTES: usize = 8 * 1024 * 1024;

fn code(value: &'static str) -> JsValue {
    JsValue::from_str(value)
}

#[wasm_bindgen]
impl BrowserCoreClient {
    /// Apply already-received socket frames (`frames_json`: a JSON array of
    /// frames) to this core client, in order. Returns
    /// `{appliedSeq, changedChats:[{chatId, messagesV}], ignored}`; `appliedSeq`
    /// is the monotonic ordering barrier a later op compares against.
    ///
    /// Error codes: `session_expired` (stale handle/generation or ended
    /// session), `invalid_frames` (not an array, too large or malformed chat
    /// frame), `local_profile_read_only`, `unavailable`.
    pub async fn ingest_socket_frames(&mut self, handle: &str, generation: f64, frames_json: &str) -> Result<String, JsValue> {
        let status = self.status(handle, generation)?;
        if status.local_read_only {
            return Err(code("local_profile_read_only"));
        }
        if frames_json.len() > MAX_FRAMES_BYTES {
            return Err(code("invalid_frames"));
        }
        let frames: Vec<serde_json::Value> = serde_json::from_str(frames_json).map_err(|_| code("invalid_frames"))?;
        if frames.len() > MAX_FRAMES {
            return Err(code("invalid_frames"));
        }
        let summary = self.client.ingest_socket_frames(&frames).await.map_err(|error| match error {
            openmates_sdk::Error::Protocol => code("invalid_frames"),
            openmates_sdk::Error::Expired | openmates_sdk::Error::Authentication | openmates_sdk::Error::Cancelled => code("session_expired"),
            _ => code("unavailable"),
        })?;
        serde_json::to_string(&summary).map_err(|_| code("unavailable"))
    }

    /// Load one chat the page created or opened into this same core client
    /// (row, chat key, `messages_v`, bounded history). Returns
    /// `{chatId, messagesV, historyRows}`; never an empty success.
    ///
    /// Error codes: `session_expired`, `local_profile_read_only`, `forbidden`,
    /// `chat_unknown`, `chat_key_unavailable`, `invalid_chat_id`, `unavailable`.
    pub async fn admit_chat(&mut self, handle: &str, generation: f64, chat_id: &str, team_id: Option<String>) -> Result<String, JsValue> {
        let status = self.status(handle, generation)?;
        if status.local_read_only {
            return Err(code("local_profile_read_only"));
        }
        let admission = self.client.admit_chat(chat_id, team_id.as_deref()).await.map_err(|error| code(error.code()))?;
        serde_json::to_string(&admission).map_err(|_| code("unavailable"))
    }
}
