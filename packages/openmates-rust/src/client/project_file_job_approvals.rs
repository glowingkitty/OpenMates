//! Interactive approvals of Project file jobs: the shell-facing half of the
//! file-job protocol (`project_file_jobs`). Part of the shared client core.
//! Keeps pending prompts, remembered accept decisions, applied-change events and
//! the bounded per-chat job state of a long-lived Client (the web Worker).
//! Mirrors the approval maps of `projectFileJobExecutor.ts` (web executor).
use super::FileJobState;
#[cfg(feature = "workflow-yaml")]
use crate::work::HostedFileMutation;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

/// Pending prompts kept per chat (older ones are dropped; the server re-offers).
const MAX_PENDING: usize = 16;
/// Remembered accept decisions per chat.
const MAX_REMEMBERED: usize = 64;
/// Applied events kept until the shell takes them.
const MAX_APPLIED: usize = 64;
/// Chats whose job state a long-lived Client keeps.
const MAX_CHATS: usize = 8;

/// What a recorded prompt grants when the user accepts.
#[derive(Clone, Debug)]
enum Grant {
    /// Execute the write whose recomputed digest equals this one.
    Write(String),
    /// Execute the ignored-file read with this key (see [`read_key`]).
    Read(String),
}

#[derive(Clone, Debug)]
struct Pending {
    operation_id: String,
    scope: Value,
    grant: Grant,
}

/// Approval state of one chat's file jobs.
#[derive(Clone, Debug, Default)]
pub(super) struct Approvals {
    /// Whether always-ask writes and ignored reads wait for the shell.
    pub(super) interactive: bool,
    pending: Vec<Pending>,
    fresh: Vec<Value>,
    approved: BTreeMap<String, String>,
    approved_reads: BTreeSet<String>,
    applied: Vec<Value>,
}

/// The stable key of an ignored-file read approval:
/// `[project_id, source_id, chat_id, path]`.
pub(super) fn read_key(job: &Value, path: &str) -> String {
    json!([job["project_id"], job["source_id"], job["chat_id"], path]).to_string()
}

impl Approvals {
    /// Whether the user accepted this operation with exactly this digest.
    pub(super) fn write_approved(&self, operation: &str, digest: &str) -> bool {
        self.approved.get(operation).is_some_and(|d| d == digest)
    }

    /// Whether the user accepted reading this ignored path.
    pub(super) fn read_approved(&self, key: &str) -> bool {
        self.approved_reads.contains(key)
    }

    /// The run finished: drop the remembered digest.
    pub(super) fn forget(&mut self, operation: &str) {
        self.approved.remove(operation);
    }

    fn push_pending(&mut self, pending: Pending, prompt: Value) {
        // A re-offered job replaces its earlier prompt instead of duplicating it.
        self.pending
            .retain(|p| p.operation_id != pending.operation_id);
        if self.pending.len() >= MAX_PENDING {
            self.pending.remove(0);
        }
        self.pending.push(pending);
        self.fresh.push(prompt);
    }

    /// Record the always-ask write prompt shown to the user (`mutation` is the
    /// restored proposal).
    pub(super) fn prompt_write(
        &mut self,
        job: &Value,
        scope: Value,
        digest: &str,
        mutation: Value,
    ) {
        let operation_id = job["operation_id"].as_str().unwrap_or_default().to_owned();
        let prompt = json!({"kind": "write", "operation_id": job["operation_id"],
            "chat_id": job["chat_id"], "project_id": job["project_id"],
            "proposal_commitment": digest, "mutation": mutation});
        let grant = Grant::Write(digest.to_owned());
        self.push_pending(
            Pending {
                operation_id,
                scope,
                grant,
            },
            prompt,
        );
    }

    /// Record the ignored-file read prompt.
    pub(super) fn prompt_read(&mut self, job: &Value, scope: Value, key: String, path: &str) {
        let operation_id = job["operation_id"].as_str().unwrap_or_default().to_owned();
        let prompt = json!({"kind": "read", "operation_id": job["operation_id"],
            "chat_id": job["chat_id"], "project_id": job["project_id"],
            "source_id": job["source_id"], "path": path});
        self.push_pending(
            Pending {
                operation_id,
                scope,
                grant: Grant::Read(key),
            },
            prompt,
        );
    }

    /// Record an applied change for the shell (bounded until taken). The
    /// event carries the restored mutation so the shell can render the diff
    /// card; it stays on the device (local UI only, never sent to the server).
    #[cfg(feature = "workflow-yaml")]
    pub(super) fn record_applied(&mut self, job: &Value, mutation: &HostedFileMutation) {
        let mut event = json!({"project_id": job["project_id"], "chat_id": job["chat_id"],
            "operation": mutation.operation.wire(), "path": mutation.path});
        if let Some(target) = &mutation.new_path {
            event["new_path"] = json!(target);
        }
        // Serializing a validated mutation cannot fail; an event without it
        // still refreshes the file list.
        if let Ok(shown) = serde_json::to_value(mutation) {
            event["mutation"] = shown;
        }
        if self.applied.len() >= MAX_APPLIED {
            self.applied.remove(0);
        }
        self.applied.push(event);
    }

    /// Prompts recorded since the last call.
    pub(super) fn take_prompts(&mut self) -> Vec<Value> {
        std::mem::take(&mut self.fresh)
    }

    /// Applied-change events recorded since the last call.
    pub(super) fn take_applied(&mut self) -> Vec<Value> {
        std::mem::take(&mut self.applied)
    }

    /// Apply the user's decision. `Some((frame, scope, finished))` is the frame
    /// to send; `None` when no such prompt is pending. An accept remembers the
    /// grant and asks for a NEW lease (`claim`); a decline rejects.
    pub(super) fn decide(
        &mut self,
        operation: &str,
        accept: bool,
    ) -> Option<(&'static str, Value, bool)> {
        let at = self
            .pending
            .iter()
            .position(|p| p.operation_id == operation)?;
        let pending = self.pending.remove(at);
        if !accept {
            return Some(("project_file_operation_reject", pending.scope, true));
        }
        match pending.grant {
            Grant::Write(digest) => {
                if self.approved.len() >= MAX_REMEMBERED && !self.approved.contains_key(operation) {
                    self.approved.pop_first();
                }
                self.approved.insert(operation.to_owned(), digest);
            }
            Grant::Read(key) => {
                if self.approved_reads.len() >= MAX_REMEMBERED {
                    self.approved_reads.pop_first();
                }
                self.approved_reads.insert(key);
            }
        }
        Some(("project_file_operation_claim", pending.scope, false))
    }
}

/// Per-chat [`FileJobState`] of a long-lived Client, bounded to [`MAX_CHATS`].
#[derive(Clone, Debug, Default)]
pub(in crate::client) struct FileJobChats {
    states: BTreeMap<String, FileJobState>,
    order: Vec<String>,
}

impl FileJobChats {
    /// Take the chat's state out (a fresh one when unknown); give it back with
    /// [`FileJobChats::put`]. Taking avoids borrowing the Client twice.
    pub(super) fn take(&mut self, chat: &str, interactive: bool) -> FileJobState {
        let mut state = self.states.remove(chat).unwrap_or_default();
        self.order.retain(|c| c != chat);
        state.approvals.interactive = interactive;
        state
    }

    /// Store the chat's state, evicting the least recently used chat.
    pub(super) fn put(&mut self, chat: &str, state: FileJobState) {
        while self.order.len() >= MAX_CHATS {
            let oldest = self.order.remove(0);
            self.states.remove(&oldest);
        }
        self.order.push(chat.to_owned());
        self.states.insert(chat.to_owned(), state);
    }
}
