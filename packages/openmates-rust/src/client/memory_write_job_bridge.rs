//! Sans-IO driver of the assistant Memory write job machine
//! ([`super::memory_write_jobs`]) for shells whose socket and settings store
//! live in another realm: the web page owns the WebSocket and the profile, the
//! shared Worker owns this core. The same `job_frames` state machine runs here;
//! its two IO steps (post the encrypted settings, store the history notice)
//! become [`MemoryJobEffect`]s that the shell performs and answers with
//! [`MemoryJobDriver::resume`]. Plan: `docs/plans/assistant-memory-writes/` (TASK-3).
use super::memory_documents::{
    MemoryDocumentError, MemoryResult, MemoryWriteMode, PreparedMemorySettings,
    prepare_memory_delete, prepare_memory_write,
};
use super::memory_write_jobs::{MemoryJobRunner, MemoryJobState, is_job_frame, job_frames};
use super::{Error, Result};
use crate::crypto::master::MasterCapability;
use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeMap;
use std::future::Future;
use std::rc::Rc;
use tokio::sync::{Mutex, mpsc, oneshot};
use zeroize::Zeroizing;

/// IO the shell performs for one job step. Holds ciphertext and the notice
/// plaintext, which the shell encrypts with the chat key through its existing
/// system message path; never logged by the core.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum MemoryJobEffect {
    /// POST `encrypted_settings` to `/v1/settings/encrypted-account` and keep
    /// the local profile in step. Answer `ok`, or an error code (`offline`,
    /// `rule_auth_required`, `rule_save_failed`).
    PostSettings {
        /// Master-key ciphertext of the next account settings.
        encrypted_settings: String,
    },
    /// Store the `context_entry` notice as an encrypted `role: system` message
    /// (`chat_system_message_added`, linked to `user_message_id`) and answer
    /// `ok` once the server confirmed it.
    Notice {
        /// Chat of the job.
        chat_id: String,
        /// User message of the turn.
        user_message_id: String,
        /// `context-entry-{job_id}`.
        message_id: String,
        /// Event JSON built by the core.
        content: String,
    },
    /// The step finished: send these frames in order (`[type, payload]`).
    Done {
        /// Protocol frames for the socket.
        frames: Vec<(String, Value)>,
    },
}

/// Shell answer of a [`MemoryJobEffect`]: `None` for success, else an error code.
pub type MemoryEffectOutcome = Option<String>;

type Step = (
    MemoryJobEffect,
    Option<oneshot::Sender<MemoryEffectOutcome>>,
);

/// Runner that turns IO into effects and waits for the shell's answer.
struct EffectRunner {
    master: MasterCapability,
    ciphertext: Option<String>,
    steps: mpsc::UnboundedSender<Step>,
}

impl EffectRunner {
    async fn ask(&self, effect: MemoryJobEffect) -> MemoryEffectOutcome {
        let (reply, answer) = oneshot::channel();
        if self.steps.send((effect, Some(reply))).is_err() {
            return Some("cancelled".into());
        }
        // A dropped driver (shell gone) counts as cancellation.
        answer.await.unwrap_or_else(|_| Some("cancelled".into()))
    }

    async fn post(
        &mut self,
        prepared: PreparedMemorySettings,
    ) -> MemoryResult<Option<Zeroizing<String>>> {
        let outcome = self
            .ask(MemoryJobEffect::PostSettings {
                encrypted_settings: prepared.encrypted_settings.clone(),
            })
            .await;
        match outcome.as_deref() {
            None => {
                // Later steps of the same job (rollback) read the stored state.
                self.ciphertext = Some(prepared.encrypted_settings);
                Ok(prepared.previous)
            }
            Some("cancelled") => Err(Error::Cancelled.into()),
            Some("offline") => Err(Error::Offline.into()),
            Some("rule_auth_required") => Err(Error::Authentication.into()),
            Some(_) => Err(MemoryDocumentError::SaveFailed),
        }
    }
}

impl MemoryJobRunner for EffectRunner {
    async fn write(
        &mut self,
        entry_id: &str,
        document: &str,
        mode: MemoryWriteMode,
    ) -> MemoryResult<Option<Zeroizing<String>>> {
        let prepared = prepare_memory_write(
            &self.master,
            self.ciphertext.as_deref(),
            entry_id,
            document,
            mode,
        )
        .await?;
        self.post(prepared).await
    }

    async fn delete(&mut self, entry_id: &str) -> MemoryResult<()> {
        let prepared =
            prepare_memory_delete(&self.master, self.ciphertext.as_deref(), entry_id).await?;
        self.post(prepared).await.map(drop)
    }

    async fn seal(&mut self, previous: &str) -> Result<String> {
        self.master.encrypt_server_bytes(previous.as_bytes()).await
    }

    async fn notice(
        &mut self,
        chat: &str,
        user_message: &str,
        message_id: &str,
        content: &str,
        _key: Option<&[u8; 32]>,
    ) -> Result<()> {
        let outcome = self
            .ask(MemoryJobEffect::Notice {
                chat_id: chat.into(),
                user_message_id: user_message.into(),
                message_id: message_id.into(),
                content: content.into(),
            })
            .await;
        match outcome.as_deref() {
            None => Ok(()),
            Some("cancelled") => Err(Error::Cancelled),
            Some(_) => Err(Error::Offline),
        }
    }
}

/// Per-chat job state of one shell realm. Frames of one chat run one at a
/// time (the state lock), so a repeated offer is never claimed twice.
#[derive(Default)]
pub struct MemoryJobDesk {
    chats: BTreeMap<String, Rc<Mutex<MemoryJobState>>>,
}

impl std::fmt::Debug for MemoryJobDesk {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("MemoryJobDesk")
            .field("chats", &self.chats.len())
            .finish()
    }
}

/// The shell's handle of one running frame: read effects, answer them.
pub struct MemoryJobDriver {
    steps: mpsc::UnboundedReceiver<Step>,
    reply: Option<oneshot::Sender<MemoryEffectOutcome>>,
}

impl std::fmt::Debug for MemoryJobDriver {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("MemoryJobDriver").finish_non_exhaustive()
    }
}

impl MemoryJobDesk {
    /// Forget every chat's job state (logout, account switch).
    pub fn clear(&mut self) {
        self.chats.clear();
    }

    /// Start handling one inbound frame `kind` of the job protocol.
    ///
    /// `ciphertext` is the current `encrypted_settings` of the profile. The
    /// returned future runs the state machine and must be spawned on the
    /// shell's single-threaded executor; the driver yields its effects.
    /// Frames that are not job frames, or carry no `chat_id`, finish at once
    /// with no frames.
    pub fn start(
        &mut self,
        master: MasterCapability,
        ciphertext: Option<String>,
        kind: &str,
        event: Value,
        now_s: u64,
    ) -> (impl Future<Output = ()> + use<>, MemoryJobDriver) {
        let (sender, steps) = mpsc::unbounded_channel();
        let chat = event["chat_id"]
            .as_str()
            .map(str::to_owned)
            .filter(|_| is_job_frame(kind));
        let state = chat.as_ref().map(|chat| {
            self.chats
                .entry(chat.clone())
                .or_insert_with(|| Rc::new(Mutex::new(MemoryJobState::default())))
                .clone()
        });
        let kind = kind.to_owned();
        let run = async move {
            let mut frames = Vec::new();
            if let (Some(chat), Some(state)) = (chat, state) {
                let mut runner = EffectRunner {
                    master,
                    ciphertext,
                    steps: sender.clone(),
                };
                let mut state = state.lock().await;
                // Cancellation (the shell dropped the driver) sends nothing.
                if let Ok(out) =
                    job_frames(&mut runner, &kind, &event, &chat, now_s, &mut state).await
                {
                    frames = out
                        .into_iter()
                        .map(|(name, payload)| (name.to_owned(), payload))
                        .collect();
                }
            }
            let _ = sender.send((MemoryJobEffect::Done { frames }, None));
        };
        (run, MemoryJobDriver { steps, reply: None })
    }
}

impl MemoryJobDriver {
    /// The next effect; [`MemoryJobEffect::Done`] ends the frame.
    ///
    /// # Errors
    /// `Cancelled` when the job future was dropped before finishing.
    pub async fn next(&mut self) -> Result<MemoryJobEffect> {
        let (effect, reply) = self.steps.recv().await.ok_or(Error::Cancelled)?;
        self.reply = reply;
        Ok(effect)
    }

    /// Answer the last effect (`None` = success, else an error code).
    ///
    /// # Errors
    /// `Protocol` when no effect is waiting for an answer.
    pub fn resume(&mut self, outcome: MemoryEffectOutcome) -> Result<()> {
        let reply = self.reply.take().ok_or(Error::Protocol)?;
        // The job future may already be gone (cancelled); nothing waits then.
        let _ = reply.send(outcome);
        Ok(())
    }
}

#[cfg(test)]
#[path = "memory_write_job_bridge_tests.rs"]
mod tests;
