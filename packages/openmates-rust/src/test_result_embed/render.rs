//! Render model for the test result embed: one summary block plus a layout per
//! run kind (summary only, browser timeline with video and preview, terminal
//! step list with cast). Pure data and plain-text output; shells style it.
//! Spec: `code-run.tests.recorded-evidence`.
use super::{Evidence, RunKind, RunStatus, Step, StepStatus, TestResultEmbed};
use serde::Serialize;

/// Reference to evidence a shell can open through its asset id.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct EvidenceView {
    /// Evidence kind.
    pub kind: String,
    /// Artifact path.
    pub path: String,
    /// Encrypted asset id, when stored.
    pub asset_id: Option<String>,
    /// MIME type.
    pub mime_type: String,
    /// Size in bytes.
    pub size_bytes: u64,
}

impl From<&Evidence> for EvidenceView {
    fn from(item: &Evidence) -> Self {
        Self {
            kind: item.kind.clone(),
            path: item.path.clone(),
            asset_id: item.asset_id.clone(),
            mime_type: item.mime_type.clone(),
            size_bytes: item.size_bytes,
        }
    }
}

/// One timeline row of a browser run.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TimelineStepView {
    /// 1-based position.
    pub number: usize,
    /// Step name.
    pub name: String,
    /// Outcome.
    pub status: StepStatus,
    /// Offset into the video in ms.
    pub start_ms: u64,
    /// Step length in ms.
    pub duration_ms: u64,
    /// Failure text.
    pub error: Option<String>,
    /// True for the preview step.
    pub is_preview: bool,
}

/// One entry of a terminal run: command entered, output produced, status.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TerminalStepView {
    /// 1-based position.
    pub number: usize,
    /// Command entered (falls back to the step name).
    pub command: String,
    /// Output produced.
    pub output: String,
    /// Outcome.
    pub status: StepStatus,
}

/// One test case line.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TestLine {
    /// Test name.
    pub name: String,
    /// Outcome.
    pub status: StepStatus,
    /// Failure text.
    pub error: Option<String>,
}

/// Kind-specific layout.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "layout", rename_all = "snake_case")]
pub enum Layout {
    /// Unit run: result summary only.
    Summary,
    /// Browser run: vertical step timeline with video and preview frame.
    Timeline {
        /// Ordered steps.
        steps: Vec<TimelineStepView>,
        /// Recording, when stored.
        video: Option<EvidenceView>,
        /// Preview frame, when stored.
        preview: Option<EvidenceView>,
    },
    /// CLI run: terminal-style step list with a cast.
    Terminal {
        /// Ordered steps.
        steps: Vec<TerminalStepView>,
        /// Asciicast, when stored.
        cast: Option<EvidenceView>,
    },
}

/// Everything a shell needs to draw a test result.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TestResultRender {
    /// One-line headline, e.g. `Browser test passed`.
    pub headline: String,
    /// Run status.
    pub status: RunStatus,
    /// Counts line, e.g. `2 passed, 0 failed, 1 skipped in 4.2s`.
    pub counts: String,
    /// False when the tested revisions changed since the run.
    pub is_current: bool,
    /// Run-level error.
    pub error: Option<String>,
    /// Test cases (failed ones first).
    pub tests: Vec<TestLine>,
    /// Layout per run kind.
    pub layout: Layout,
    /// All evidence references, including trace and report.
    pub evidence: Vec<EvidenceView>,
    /// Embeds the run tested.
    pub tested_embed_ids: Vec<String>,
}

fn seconds(ms: u64) -> String {
    format!("{}.{}s", ms / 1000, (ms % 1000) / 100)
}

fn first_evidence(embed: &TestResultEmbed, kind: &str) -> Option<EvidenceView> {
    embed
        .evidence
        .iter()
        .find(|item| item.kind == kind)
        .map(EvidenceView::from)
}

fn preview_evidence(embed: &TestResultEmbed) -> Option<EvidenceView> {
    first_evidence(embed, "preview_frame")
}

fn timeline(embed: &TestResultEmbed) -> Vec<TimelineStepView> {
    embed
        .steps
        .iter()
        .enumerate()
        .map(|(index, step): (usize, &Step)| TimelineStepView {
            number: index + 1,
            name: step.name.clone(),
            status: step.status,
            start_ms: step.start_ms,
            duration_ms: step.end_ms.saturating_sub(step.start_ms),
            error: step.error.clone(),
            is_preview: step.is_preview || embed.preview_step_index == Some(index),
        })
        .collect()
}

fn terminal(embed: &TestResultEmbed) -> Vec<TerminalStepView> {
    embed
        .steps
        .iter()
        .enumerate()
        .map(|(index, step)| TerminalStepView {
            number: index + 1,
            command: step
                .command
                .clone()
                .filter(|c| !c.is_empty())
                .unwrap_or_else(|| step.name.clone()),
            output: step.output.clone().unwrap_or_default(),
            status: step.status,
        })
        .collect()
}

pub(super) fn build(embed: &TestResultEmbed) -> TestResultRender {
    let kind = match embed.kind {
        RunKind::Unit => "Unit tests",
        RunKind::Browser => "Browser test",
        RunKind::Cli => "CLI test",
    };
    let status = match embed.run_status {
        RunStatus::Passed => "passed",
        RunStatus::Failed => "failed",
        RunStatus::Error => "errored",
        RunStatus::Cancelled => "cancelled",
        RunStatus::TimedOut => "timed out",
    };
    let mut tests: Vec<TestLine> = embed
        .tests
        .iter()
        .map(|t| TestLine {
            name: t.name.clone(),
            status: t.status,
            error: t.error.clone(),
        })
        .collect();
    // Stable sort keeps source order inside each group.
    tests.sort_by_key(|t| t.status != StepStatus::Failed);
    let layout = match embed.kind {
        RunKind::Unit => Layout::Summary,
        RunKind::Browser => Layout::Timeline {
            steps: timeline(embed),
            video: first_evidence(embed, "video"),
            preview: preview_evidence(embed),
        },
        RunKind::Cli => Layout::Terminal {
            steps: terminal(embed),
            cast: first_evidence(embed, "terminal_cast"),
        },
    };
    TestResultRender {
        headline: format!("{kind} {status}"),
        status: embed.run_status,
        counts: format!(
            "{} passed, {} failed, {} skipped in {}",
            embed.passed,
            embed.failed,
            embed.skipped,
            seconds(embed.duration_ms)
        ),
        is_current: embed.is_current,
        error: embed.error.clone(),
        tests,
        layout,
        evidence: embed.evidence.iter().map(EvidenceView::from).collect(),
        tested_embed_ids: embed.tested_embed_ids.clone(),
    }
}

fn mark(status: StepStatus) -> &'static str {
    match status {
        StepStatus::Passed => "PASS",
        StepStatus::Failed => "FAIL",
        StepStatus::Skipped => "SKIP",
    }
}

fn evidence_line(label: &str, item: &Option<EvidenceView>) -> String {
    match item {
        Some(e) => format!(
            "{label}: {} (asset {})\n",
            e.path,
            e.asset_id.as_deref().unwrap_or("not stored")
        ),
        None => format!("{label}: none\n"),
    }
}

impl TestResultRender {
    /// Compact card text for chat output: headline, counts, stale marker.
    pub fn render_card(&self) -> String {
        let stale = if self.is_current {
            ""
        } else {
            " [stale: files changed since this run]"
        };
        format!("{}{stale}\n{}\n", self.headline, self.counts)
    }

    /// Full plain-text report (no ANSI): summary, tests, steps and evidence
    /// references. Untrusted fields are included verbatim; shells must escape
    /// terminal control characters before printing.
    pub fn render_full(&self) -> String {
        let mut out = self.render_card();
        if let Some(error) = &self.error {
            out.push_str(&format!("Error: {error}\n"));
        }
        for test in &self.tests {
            out.push_str(&format!("[{}] {}\n", mark(test.status), test.name));
            if let Some(error) = &test.error {
                out.push_str(&format!("      {error}\n"));
            }
        }
        match &self.layout {
            Layout::Summary => {}
            Layout::Timeline {
                steps,
                video,
                preview,
            } => {
                out.push_str("\nSteps\n");
                for step in steps {
                    let star = if step.is_preview { " (preview)" } else { "" };
                    out.push_str(&format!(
                        "{:>3}. [{}] {} at {}, {}{star}\n",
                        step.number,
                        mark(step.status),
                        step.name,
                        seconds(step.start_ms),
                        seconds(step.duration_ms)
                    ));
                    if let Some(error) = &step.error {
                        out.push_str(&format!("       {error}\n"));
                    }
                }
                out.push('\n');
                out.push_str(&evidence_line("Video", video));
                out.push_str(&evidence_line("Preview", preview));
            }
            Layout::Terminal { steps, cast } => {
                out.push_str("\nTerminal\n");
                for step in steps {
                    out.push_str(&format!("$ {}\n", step.command));
                    for line in step.output.lines() {
                        out.push_str(&format!("  {line}\n"));
                    }
                    out.push_str(&format!("[{}] step {}\n", mark(step.status), step.number));
                }
                out.push('\n');
                out.push_str(&evidence_line("Cast", cast));
            }
        }
        let others: Vec<&EvidenceView> = self
            .evidence
            .iter()
            .filter(|e| !matches!(e.kind.as_str(), "video" | "terminal_cast" | "preview_frame"))
            .collect();
        for item in others {
            out.push_str(&format!(
                "{}: {} (asset {})\n",
                item.kind,
                item.path,
                item.asset_id.as_deref().unwrap_or("not stored")
            ));
        }
        out
    }
}
