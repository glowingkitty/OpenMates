//! Stateful per-account AI stream assembler of the web client: the buffered
//! thinking stream, the recovery final-event timestamps and the final-chunk
//! completion plan.
//!
//! The assembler lives in the shared Worker `ws` unit (mounted through
//! `rustCore/ws/streamOps.ts`); the page only receives small render-ready
//! decisions. Invariant: a stale final chunk (another task is active in the
//! chat) never ends the active task, and a continuation final
//! (`awaiting_async_skill_continuation`) never ends the processing status.
//! Mirrors `handleAIThinkingChunkImpl`, `handleAIThinkingCompleteImpl`,
//! `persistThinkingToDb`'s field build, the final-chunk branch of
//! `handleAIMessageUpdateImpl` and `recoveryAssistantTimestamp.ts`.
//! spec: specifications/architecture/sync#sync.client.shared-rust-policy
use serde_json::{json, Map, Value};

use super::{field, nullish, parse, protocol, safe_integer, truthy};

/// Recovery final timestamps kept per account (`MAX_FINAL_TIMESTAMPS`).
pub const MAX_FINAL_TIMESTAMPS: usize = 128;
/// Age after which a recovery final timestamp is dropped (`MAX_AGE_MS`).
pub const MAX_AGE_MS: f64 = 600_000.0;
/// Thinking buffers kept at once. The TypeScript map never evicted; a bound
/// keeps the Worker from growing per reload (oldest buffer is dropped first).
pub const MAX_THINKING_BUFFERS: usize = 256;

struct Thinking {
    message_id: String,
    chat_id: String,
    content: String,
    signature: Option<String>,
    total_tokens: Option<Value>,
}

struct FinalStamp {
    identity: [String; 4],
    created_at: i64,
    received_at: f64,
}

/// Per-account stream state. One instance lives in the `ws` unit.
#[derive(Default)]
pub struct StreamAssembler {
    thinking: Vec<Thinking>,
    finals: Vec<FinalStamp>,
}

fn text(value: &Value, key: &str) -> Option<String> {
    field(value, key).and_then(Value::as_str).map(str::to_owned)
}

/// `a || b` over optional string fields (empty string falls through).
fn first_truthy(value: &Value, a: &str, b: &str) -> Option<String> {
    text(value, a)
        .filter(|s| !s.is_empty())
        .or_else(|| text(value, b))
}

impl StreamAssembler {
    /// Routes one assembler op by name.
    ///
    /// Ops: `thinkingChunk`, `thinkingComplete`, `finalTimestampRecord`,
    /// `finalTimestampGet`, `finalChunkPlan`, `reset`.
    ///
    /// # Errors
    /// `protocol` for an unknown op or malformed input.
    pub fn dispatch(&mut self, op: &str, input: &str) -> Result<String, String> {
        let input = parse(input)?;
        let out = match op {
            "thinkingChunk" => self.thinking_chunk(&input)?,
            "thinkingComplete" => self.thinking_complete(&input)?,
            "finalTimestampRecord" => self.final_record(&input),
            "finalTimestampGet" => self.final_get(&input)?,
            "finalChunkPlan" => final_chunk_plan(&input),
            "reset" => {
                self.thinking.clear();
                self.finals.clear();
                json!({ "ok": true })
            }
            _ => return Err(protocol(())),
        };
        Ok(out.to_string())
    }

    fn thinking_chunk(&mut self, input: &Value) -> Result<Value, String> {
        let message_id =
            first_truthy(input, "message_id", "task_id").ok_or_else(|| protocol(()))?;
        let chat_id = text(input, "chat_id").ok_or_else(|| protocol(()))?;
        let piece = text(input, "content").unwrap_or_default();
        match self
            .thinking
            .iter_mut()
            .find(|t| t.message_id == message_id)
        {
            Some(entry) => {
                // The TS rebuilt the entry from the new chunk's chat id.
                entry.chat_id = chat_id;
                entry.content.push_str(&piece);
            }
            None => {
                if self.thinking.len() >= MAX_THINKING_BUFFERS {
                    self.thinking.remove(0);
                }
                self.thinking.push(Thinking {
                    message_id: message_id.clone(),
                    chat_id,
                    content: piece,
                    signature: None,
                    total_tokens: None,
                });
            }
        }
        Ok(json!({ "message_id": message_id }))
    }

    fn thinking_complete(&mut self, input: &Value) -> Result<Value, String> {
        let message_id =
            first_truthy(input, "message_id", "task_id").ok_or_else(|| protocol(()))?;
        let Some(entry) = self
            .thinking
            .iter_mut()
            .find(|t| t.message_id == message_id)
        else {
            return Ok(json!({ "message_id": message_id, "fields": null }));
        };
        if let Some(signature) = nullish(field(input, "signature")).and_then(Value::as_str) {
            entry.signature = Some(signature.to_owned());
        }
        if let Some(tokens) = nullish(field(input, "total_tokens")) {
            entry.total_tokens = Some(tokens.clone());
        }
        // `persistThinkingToDb`: signature is dropped when empty, the flag follows the content.
        let mut fields = Map::new();
        fields.insert(
            "thinking_content".into(),
            Value::String(entry.content.clone()),
        );
        if let Some(signature) = entry.signature.as_ref().filter(|s| !s.is_empty()) {
            fields.insert(
                "thinking_signature".into(),
                Value::String(signature.clone()),
            );
        }
        fields.insert(
            "has_thinking".into(),
            Value::Bool(!entry.content.is_empty()),
        );
        if let Some(tokens) = &entry.total_tokens {
            fields.insert("thinking_token_count".into(), tokens.clone());
        }
        Ok(json!({ "message_id": message_id, "chat_id": entry.chat_id, "fields": fields }))
    }

    fn final_record(&mut self, input: &Value) -> Value {
        let event = field(input, "event").cloned().unwrap_or(Value::Null);
        let now = super::num(field(input, "now"));
        let created = safe_integer(field(&event, "created_at")).filter(|c| *c > 0);
        let ids = [
            "chat_id",
            "message_id",
            "recovery_job_id",
            "recovery_turn_id",
        ]
        .map(|k| text(&event, k).filter(|s| !s.is_empty()));
        let valid = field(&event, "is_final_chunk").and_then(Value::as_bool) == Some(true)
            && safe_integer(field(&event, "recovery_protocol_version")) == Some(1)
            && ids.iter().all(Option::is_some)
            && truthy(field(&event, "user_message_id"))
            && created.is_some();
        let (true, Some(created_at)) = (valid, created) else {
            return json!({ "recorded": false });
        };
        self.finals
            .retain(|stamp| now - stamp.received_at <= MAX_AGE_MS);
        let identity = ids.map(|id| id.unwrap_or_default());
        match self.finals.iter_mut().find(|s| s.identity == identity) {
            // `Map.set` on an existing key keeps its position in eviction order.
            Some(existing) => {
                existing.created_at = created_at;
                existing.received_at = now;
            }
            None => self.finals.push(FinalStamp {
                identity,
                created_at,
                received_at: now,
            }),
        }
        while self.finals.len() > MAX_FINAL_TIMESTAMPS {
            self.finals.remove(0);
        }
        json!({ "recorded": true, "createdAt": created_at })
    }

    fn final_get(&self, input: &Value) -> Result<Value, String> {
        let identity = ["chat_id", "message_id", "job_id", "turn_id"].map(|k| text(input, k));
        if identity.iter().any(Option::is_none) {
            return Err(protocol(()));
        }
        let identity = identity.map(|id| id.unwrap_or_default());
        let now = super::num(field(input, "now"));
        let created = self
            .finals
            .iter()
            .find(|s| s.identity == identity && now - s.received_at <= MAX_AGE_MS)
            .map(|s| s.created_at);
        Ok(json!({ "createdAt": created }))
    }
}

/// Final-chunk plan of `handleAIMessageUpdateImpl`. Input `{payload:{task_id,
/// user_message_id, awaiting_async_skill_continuation, interrupted_by_revocation,
/// interrupted_by_soft_limit, rejection_reason}, activeTask:{taskId,
/// userMessageId}|null}`; output `{action:"ignore",reason:"awaiting"|"stale"}` or
/// `{action:"final", status, matched, userMessageId}`.
fn final_chunk_plan(input: &Value) -> Value {
    let payload = field(input, "payload").cloned().unwrap_or(Value::Null);
    let flag = |key: &str| truthy(field(&payload, key));
    if flag("awaiting_async_skill_continuation")
        && !flag("interrupted_by_revocation")
        && !flag("interrupted_by_soft_limit")
        && !flag("rejection_reason")
    {
        return json!({ "action": "ignore", "reason": "awaiting" });
    }
    let task_id = field(&payload, "task_id");
    let active = nullish(field(input, "activeTask"));
    if let Some(active) = active {
        if field(active, "taskId") != task_id {
            return json!({ "action": "ignore", "reason": "stale" });
        }
    }
    let status = if flag("interrupted_by_revocation") {
        "cancelled"
    } else if flag("interrupted_by_soft_limit") {
        "timed_out"
    } else {
        "completed"
    };
    let user_message_id = match active {
        Some(active) => field(active, "userMessageId").cloned(),
        None => field(&payload, "user_message_id").cloned(),
    };
    json!({ "action": "final", "status": status, "matched": active.is_some(), "userMessageId": user_message_id })
}
