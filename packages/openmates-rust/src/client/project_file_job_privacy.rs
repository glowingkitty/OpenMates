//! Web-mode privacy of Project file jobs: the model only ever sees
//! `[OM_PII_…]` placeholders, the device holds the originals.
//!
//! A chat with a [`PrivacyLayer`] restores placeholders in job arguments and
//! mutations before they run, and redacts the proposal of an `awaiting_approval`
//! result, the ignored-read waiting body and every completed result before the
//! frames leave the core. Prompts and applied events for the local UI keep the
//! real values. Minted tokens are sealed with the chat key into a
//! [`ProjectFilePrivacyBlob`] that the shell MUST store (web: localStorage key
//! `PROJECT_FILE_PRIVACY_PREFIX + JSON.stringify([chat_id, project_id])`)
//! before it sends the step's frames. A chat without a layer (the CLI) keeps the
//! plain mapping restore and unredacted frames.
use super::steps::ProjectFileJobFrame;
use crate::crypto::Key;
use crate::privacy::file_privacy::{open_mappings, seal_mappings, FilePrivacy};
use crate::work::HostedFileJob;
use crate::{Error, Result};
use serde::Serialize;
use serde_json::{json, Value};
use std::fmt;

/// Sealed mappings the shell must persist before sending the step's frames.
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct ProjectFilePrivacyBlob {
    /// Chat the mappings belong to.
    pub chat_id: String,
    /// Project the mappings belong to.
    pub project_id: String,
    /// Chat-key envelope (`seal_mappings`), the web's localStorage value.
    pub ciphertext: String,
}

/// Privacy layer of one chat. Holds secrets: never printed, key and originals
/// are wiped on drop.
#[derive(Clone)]
pub(in crate::client) struct PrivacyLayer {
    privacy: FilePrivacy,
    key: Key,
    project_id: String,
    sealed: usize,
    /// A later mapping update was refused; jobs fail with this code.
    poisoned: Option<&'static str>,
}

impl fmt::Debug for PrivacyLayer {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("PrivacyLayer")
    }
}

fn unavailable(code: &'static str) -> Error {
    Error::Unavailable {
        code,
        reason: "Project file privacy is unavailable.",
    }
}

/// Names the redaction stage of an untyped failure. Errors that already carry
/// a code (`Unavailable`, e.g. `pii_mapping_limit`) keep it, so a refusal never
/// hides its cause behind `pii_mapping_unavailable`.
pub(super) fn stage(error: Error, code: &'static str) -> Error {
    match error {
        Error::Unavailable { .. } => error,
        _ => unavailable(code),
    }
}

/// Stable code of a redaction failure. `pii_mapping_unavailable` is reserved
/// for a genuinely missing mapping or layer; any other error without its own
/// code is `pii_redaction_failed` (the stages in `try_redact` name theirs).
pub(super) fn refusal_code(error: &Error) -> &'static str {
    match error {
        Error::Unavailable { code, .. } => code,
        _ => "pii_redaction_failed",
    }
}

impl PrivacyLayer {
    /// Builds the layer from settings, an optional sealed blob of this chat and
    /// project and the chat's known mappings.
    ///
    /// # Errors
    /// `pii_mapping_unavailable` for a sealed blob that cannot be opened or
    /// belongs elsewhere; `pii_mapping_limit` above the mapping bound.
    pub(super) fn open(
        chat_id: &str,
        project_id: &str,
        enabled: bool,
        memories: Vec<Value>,
        sealed: Option<&str>,
        chat_mappings: &[Value],
        key: Key,
    ) -> Result<Self> {
        let saved = match sealed {
            Some(blob) => open_mappings(chat_id, project_id, blob, &key)?,
            None => Vec::new(),
        };
        let mut privacy = FilePrivacy::new(enabled, memories, &saved)?;
        privacy.add_mappings(chat_mappings)?;
        let sealed = privacy.saved_mappings().len();
        Ok(Self {
            privacy,
            key,
            project_id: project_id.to_owned(),
            sealed,
            poisoned: None,
        })
    }

    /// Adds the chat's mappings (e.g. from newly synced messages).
    pub(super) fn add_mappings(&mut self, mappings: &[Value]) {
        if let Err(Error::Unavailable { code, .. }) = self.privacy.add_mappings(mappings) {
            self.poisoned = Some(code);
        }
    }

    /// Restores placeholders: mutation fields (path/content/patch) of writes,
    /// path/query/glob of every other operation.
    ///
    /// # Errors
    /// A poisoned layer, or the restore failures of `FilePrivacy`.
    pub(super) fn restore(&self, mut job: HostedFileJob) -> Result<HostedFileJob> {
        if let Some(code) = self.poisoned {
            return Err(unavailable(code));
        }
        if matches!(job.operation.wire(), "create_file" | "update_file") {
            self.privacy.restore_mutation_fields(&mut job.arguments)?;
        } else {
            self.privacy.restore_arguments(&mut job.arguments)?;
        }
        Ok(job)
    }

    /// Redacts the exposed bodies of `frames` and seals new mappings. Returns
    /// the blob to persist when tokens were minted. On any failure every result
    /// frame becomes `failed` with a stable code instead of leaking real values.
    pub(super) fn redact_frames(
        &mut self,
        frames: &mut [ProjectFileJobFrame],
    ) -> Option<ProjectFilePrivacyBlob> {
        let outcome = self.try_redact(frames);
        match outcome {
            Ok(blob) => blob,
            Err(error) => {
                let code = refusal_code(&error);
                for frame in frames.iter_mut() {
                    if frame.name == "project_file_operation_result" {
                        frame.payload["status"] = json!("failed");
                        frame.payload["result"] = json!({ "code": code });
                    }
                }
                None
            }
        }
    }

    fn try_redact(
        &mut self,
        frames: &mut [ProjectFileJobFrame],
    ) -> Result<Option<ProjectFilePrivacyBlob>> {
        if let Some(code) = self.poisoned {
            return Err(unavailable(code));
        }
        let mut chat_id = None;
        for frame in frames.iter_mut() {
            let exposed = frame.name == "project_file_operation_result"
                && matches!(
                    frame.payload["status"].as_str(),
                    Some("awaiting_approval" | "completed")
                );
            if exposed {
                self.privacy
                    .redact_value(&mut frame.payload["result"])
                    .map_err(|error| stage(error, "pii_detection_failed"))?;
                chat_id = frame.payload["chat_id"].as_str().map(str::to_owned);
            }
        }
        let mappings = self.privacy.saved_mappings();
        let Some(chat_id) = chat_id.filter(|_| mappings.len() > self.sealed) else {
            return Ok(None);
        };
        let ciphertext = seal_mappings(&chat_id, &self.project_id, &mappings, &self.key)
            .map_err(|error| stage(error, "pii_seal_failed"))?;
        self.sealed = mappings.len();
        Ok(Some(ProjectFilePrivacyBlob {
            chat_id,
            project_id: self.project_id.clone(),
            ciphertext,
        }))
    }
}
