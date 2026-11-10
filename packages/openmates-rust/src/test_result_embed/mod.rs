//! Typed model and decoder for the Code test result embed (`code-test-result`).
//! Shared core: the Rust CLI renders it today, web and Apple bind to the same
//! model. The backend writes the content in
//! `backend/apps/code/tasks/test_result_embed.py` (TOON text, decrypted by the
//! caller); the contract is
//! `docs/plans/agentic-tests-and-git-sync/contracts/test-run.md`
//! (assertion `code-run.tests.recorded-evidence`). Evidence bytes are never part
//! of the content: only encrypted asset ids are referenced.
mod render;

use crate::toon_decode;
use serde::{Deserialize, Deserializer, Serialize};

pub use render::{
    EvidenceView, Layout, TerminalStepView, TestLine, TestResultRender, TimelineStepView,
};

/// Embed type id registered for the backend (`backend_type`).
pub const EMBED_TYPE: &str = "test_result";
/// Frontend embed type id stored in embed metadata.
pub const FRONTEND_TYPE: &str = "code-test-result";

/// Why a test result embed could not be decoded.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TestResultError {
    /// The TOON text was malformed.
    Toon(toon_decode::ToonDecodeError),
    /// The content decoded but does not have the test result shape; the text names the field problem.
    Shape(String),
}

impl TestResultError {
    /// Stable machine code for CLI JSON errors.
    pub fn code(&self) -> &'static str {
        match self {
            Self::Toon(_) => "toon_decode_failed",
            Self::Shape(_) => "test_result_invalid",
        }
    }
}

impl std::fmt::Display for TestResultError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Toon(error) => write!(f, "{error}"),
            Self::Shape(reason) => write!(f, "test_result_invalid: {reason}"),
        }
    }
}

impl std::error::Error for TestResultError {}

/// Kind of run the result belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RunKind {
    /// Unit tests: summary only.
    Unit,
    /// Browser run: video, step timeline and preview frame.
    Browser,
    /// CLI run: terminal step list and a cast.
    Cli,
}

/// Final status of the run.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RunStatus {
    /// Every test passed.
    Passed,
    /// Exit code non-zero or a test failed.
    Failed,
    /// Setup, server or report problem.
    Error,
    /// Cancelled by the user.
    Cancelled,
    /// The test command timed out.
    TimedOut,
}

/// Status of one step or test.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StepStatus {
    /// Completed without failure.
    Passed,
    /// Failed.
    Failed,
    /// Not run.
    Skipped,
}

/// One file revision the run used.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct Revision {
    /// Project-relative path.
    pub path: String,
    /// Revision identifier.
    pub revision: String,
}

/// One test case.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct TestCase {
    /// Test name.
    pub name: String,
    /// Outcome.
    pub status: StepStatus,
    /// Duration in ms.
    #[serde(default)]
    pub duration_ms: u64,
    /// Failure text.
    #[serde(default)]
    pub error: Option<String>,
}

/// One ordered step of the run.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct Step {
    /// Step name.
    pub name: String,
    /// Offset from the start of the run (video timeline for browser runs).
    #[serde(default)]
    pub start_ms: u64,
    /// End offset.
    #[serde(default)]
    pub end_ms: u64,
    /// Outcome.
    pub status: StepStatus,
    /// Failure text.
    #[serde(default)]
    pub error: Option<String>,
    /// True for the step used as preview frame.
    #[serde(default)]
    pub is_preview: bool,
    /// CLI runs: command entered.
    #[serde(default)]
    pub command: Option<String>,
    /// CLI runs: output produced.
    #[serde(default)]
    pub output: Option<String>,
}

/// Reference to an encrypted evidence asset.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct Evidence {
    /// `video`, `terminal_cast`, `preview_frame`, `trace` or `report`.
    pub kind: String,
    /// Normalized artifact path.
    pub path: String,
    /// MIME type.
    #[serde(default)]
    pub mime_type: String,
    /// Size in bytes.
    #[serde(default)]
    pub size_bytes: u64,
    /// Encrypted artifact id; absent when storage failed.
    #[serde(default)]
    pub asset_id: Option<String>,
    /// Step index for a preview frame.
    #[serde(default)]
    pub at_step: Option<usize>,
}

/// Decoded content of a test result embed.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct TestResultEmbed {
    /// Run kind.
    pub kind: RunKind,
    /// `e2b` or `remote_source`.
    pub target: String,
    /// Run status.
    pub run_status: RunStatus,
    /// Process exit code when known.
    #[serde(default)]
    pub exit_code: Option<i64>,
    /// Run duration in ms.
    #[serde(default)]
    pub duration_ms: u64,
    /// Passed test count.
    #[serde(default)]
    pub passed: u64,
    /// Failed test count.
    #[serde(default)]
    pub failed: u64,
    /// Skipped test count.
    #[serde(default)]
    pub skipped: u64,
    /// Run-level error text.
    #[serde(default)]
    pub error: Option<String>,
    /// Index into `steps` of the preview step.
    #[serde(default)]
    pub preview_step_index: Option<usize>,
    /// Code Run execution id.
    #[serde(default)]
    pub execution_id: Option<String>,
    /// Project the files belong to.
    #[serde(default)]
    pub project_id: Option<String>,
    /// Code/application embeds the run tested.
    #[serde(default, deserialize_with = "id_list")]
    pub tested_embed_ids: Vec<String>,
    /// Revisions the run used.
    #[serde(default)]
    pub revisions: Vec<Revision>,
    /// Test cases.
    #[serde(default)]
    pub tests: Vec<TestCase>,
    /// Ordered steps.
    #[serde(default)]
    pub steps: Vec<Step>,
    /// Evidence references.
    #[serde(default)]
    pub evidence: Vec<Evidence>,
    /// False once the tested revisions changed.
    #[serde(default = "yes")]
    pub is_current: bool,
    /// Why the result is stale (`revisions_changed`).
    #[serde(default)]
    pub stale_reason: Option<String>,
}

fn yes() -> bool {
    true
}

/// TOON joins arrays of scalars with `|` when flattened; accept both forms.
fn id_list<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Vec<String>, D::Error> {
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum Form {
        List(Vec<String>),
        Joined(String),
    }
    Ok(match Form::deserialize(deserializer)? {
        Form::List(list) => list,
        Form::Joined(text) => text
            .split('|')
            .map(str::trim)
            .filter(|part| !part.is_empty())
            .map(str::to_owned)
            .collect(),
    })
}

impl TestResultEmbed {
    /// Decode decrypted TOON embed content.
    ///
    /// # Errors
    /// [`TestResultError::Toon`] for malformed TOON, [`TestResultError::Shape`]
    /// when required fields are missing or have the wrong type.
    pub fn decode_toon(text: &str) -> Result<Self, TestResultError> {
        let json = toon_decode::decode_to_json_text(text).map_err(TestResultError::Toon)?;
        Self::decode_json(&json)
    }

    /// Decode content already converted to JSON text (web Worker boundary, CLI version reads).
    ///
    /// # Errors
    /// [`TestResultError::Shape`] when the JSON does not have the test result shape.
    pub fn decode_json(json: &str) -> Result<Self, TestResultError> {
        serde_json::from_str(json).map_err(|error| TestResultError::Shape(error.to_string()))
    }

    /// Decode from content that may be TOON text or JSON text, as returned by
    /// embed version reads.
    ///
    /// # Errors
    /// As [`Self::decode_toon`] / [`Self::decode_json`].
    pub fn decode_content(text: &str) -> Result<Self, TestResultError> {
        if text.trim_start().starts_with('{') {
            Self::decode_json(text)
        } else {
            Self::decode_toon(text)
        }
    }

    /// Build the render model for this result.
    pub fn render_model(&self) -> TestResultRender {
        render::build(self)
    }
}

#[cfg(test)]
mod tests;
