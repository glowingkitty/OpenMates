//! Pure Check models and rules: validation, canonical hashing, run aggregate, staleness.
//!
//! Mirrors `backend/core/api/app/services/user_check_service.py` so clients can
//! validate before sending and show an offline aggregate; the server stays the
//! authority. Spec: `specifications/features/checks`.
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

/// Kind of evidence a source produces.
#[derive(Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Debug)]
#[serde(rename_all = "snake_case")]
pub enum SourceKind {
    E2e,
    Unit,
    Integration,
    StaticAnalysis,
    DeterministicAudit,
    AiEvaluation,
    HumanConfirmation,
}

impl SourceKind {
    /// Kinds that can be re-run without judgement.
    pub fn is_deterministic(self) -> bool {
        !matches!(self, Self::AiEvaluation | Self::HumanConfirmation)
    }

    /// Parses the wire name (`e2e`, `static_analysis`, ...).
    pub fn parse(value: &str) -> Result<Self> {
        serde_json::from_value(serde_json::Value::String(value.to_owned()))
            .map_err(|_| Error::Invalid("CHECK_SOURCE_INVALID"))
    }
}

/// Whether a source gates the Check.
#[derive(Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Debug)]
#[serde(rename_all = "snake_case")]
pub enum SourceRole {
    Required,
    Supporting,
}

/// Plaintext gating metadata of one source (what the server sees).
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq, Debug)]
pub struct SourceBinding {
    pub source_binding_id: String,
    pub source_kind: SourceKind,
    pub role: SourceRole,
}

/// One source with its encrypted details.
///
/// `reference` is the test path or selector, the AI question or the human instruction.
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq, Debug)]
pub struct SourceDefinition {
    #[serde(default)]
    pub source_binding_id: String,
    pub source_kind: SourceKind,
    pub role: SourceRole,
    #[serde(default)]
    pub title: String,
    #[serde(default, rename = "ref")]
    pub reference: String,
    #[serde(default)]
    pub covers: Vec<String>,
}

impl SourceDefinition {
    /// The plaintext gating view of this source.
    pub fn binding(&self) -> SourceBinding {
        SourceBinding {
            source_binding_id: self.source_binding_id.clone(),
            source_kind: self.source_kind,
            role: self.role,
        }
    }
}

/// The encrypted part of a revision: gating flag plus per-source details.
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq, Debug)]
pub struct CheckDefinition {
    pub requires_deterministic: bool,
    pub sources: Vec<SourceDefinition>,
}

impl CheckDefinition {
    /// Assigns `s1`, `s2`, ... to sources without an id, then validates.
    pub fn normalized(mut self) -> Result<Self> {
        for (index, source) in self.sources.iter_mut().enumerate() {
            if source.source_binding_id.trim().is_empty() {
                source.source_binding_id = format!("s{}", index + 1);
            }
        }
        let bindings: Vec<SourceBinding> =
            self.sources.iter().map(SourceDefinition::binding).collect();
        validate_sources(&bindings, self.requires_deterministic)?;
        Ok(self)
    }

    /// Canonical definition text: the exact string that is hashed and encrypted.
    pub fn canonical_text(&self) -> Result<String> {
        Ok(serde_json::to_string(self)?)
    }

    /// Lowercase SHA-256 of the canonical text (`definition_hash`).
    pub fn definition_hash(&self) -> Result<String> {
        Ok(text_hash(&self.canonical_text()?))
    }
}

/// Lowercase SHA-256 hex of a text.
pub fn text_hash(text: &str) -> String {
    format!("{:x}", Sha256::digest(text.as_bytes()))
}

/// Refuses source sets the backend would refuse.
///
/// # Errors
/// `CHECK_SOURCE_INVALID`, `CHECK_REQUIRED_SOURCE_MISSING` or
/// `CHECK_DETERMINISTIC_SOURCE_REQUIRED`.
pub fn validate_sources(sources: &[SourceBinding], requires_deterministic: bool) -> Result<()> {
    let mut seen = BTreeSet::new();
    for source in sources {
        if source.source_binding_id.is_empty() || !seen.insert(source.source_binding_id.as_str()) {
            return Err(Error::Invalid("CHECK_SOURCE_INVALID"));
        }
    }
    let mut required = sources
        .iter()
        .filter(|s| s.role == SourceRole::Required)
        .peekable();
    if required.peek().is_none() {
        return Err(Error::Invalid("CHECK_REQUIRED_SOURCE_MISSING"));
    }
    if requires_deterministic && !required.any(|s| s.source_kind.is_deterministic()) {
        return Err(Error::Invalid("CHECK_DETERMINISTIC_SOURCE_REQUIRED"));
    }
    Ok(())
}

/// Aggregate over required sources only: failed > error > blocked > running >
/// waiting_for_confirmation > passed. A missing result counts as pending;
/// cancelled counts as error and skipped as blocked.
pub fn aggregate_status(
    sources: &[SourceBinding],
    statuses: &BTreeMap<String, String>,
) -> &'static str {
    let required: Vec<(SourceKind, &str)> = sources
        .iter()
        .filter(|s| s.role == SourceRole::Required)
        .map(|s| {
            let status = statuses
                .get(&s.source_binding_id)
                .map_or("pending", String::as_str);
            (s.source_kind, status)
        })
        .collect();
    let any = |names: &[&str]| required.iter().any(|(_, s)| names.contains(s));
    if any(&["failed"]) {
        "failed"
    } else if any(&["error", "cancelled"]) {
        "error"
    } else if any(&["blocked", "skipped"]) {
        "blocked"
    } else if required.iter().any(|(kind, s)| {
        !matches!(*s, "passed" | "waived") && *kind != SourceKind::HumanConfirmation
    }) {
        "running"
    } else if required
        .iter()
        .any(|(_, s)| !matches!(*s, "passed" | "waived"))
    {
        "waiting_for_confirmation"
    } else {
        "passed"
    }
}

/// A run, as the backend returns it.
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq, Debug)]
pub struct Run {
    pub run_id: String,
    pub check_id: String,
    pub check_revision_id: String,
    #[serde(default)]
    pub subject_revision: Option<String>,
    pub status: String,
    #[serde(default)]
    pub created_at: u64,
    #[serde(default)]
    pub finished_at: Option<u64>,
}

/// A passed run is stale when its Check revision is no longer current or it ran
/// against another subject revision than the one now being judged.
pub fn is_stale(
    latest_passed_run: Option<&Run>,
    current_revision_id: &str,
    subject_revision_now: Option<&str>,
) -> bool {
    let Some(run) = latest_passed_run.filter(|run| run.status == "passed") else {
        return false;
    };
    run.check_revision_id != current_revision_id
        || subject_revision_now.is_some_and(|now| run.subject_revision.as_deref() != Some(now))
}

/// Parses a CLI `kind:role:ref` source spec (the reference may contain colons).
pub fn parse_source_spec(spec: &str) -> Result<SourceDefinition> {
    let mut parts = spec.splitn(3, ':');
    let (Some(kind), Some(role), Some(reference)) = (parts.next(), parts.next(), parts.next())
    else {
        return Err(Error::Invalid("A source must look like kind:role:ref."));
    };
    let role = match role {
        "required" => SourceRole::Required,
        "supporting" => SourceRole::Supporting,
        _ => return Err(Error::Invalid("A source role is required or supporting.")),
    };
    if reference.trim().is_empty() {
        return Err(Error::Invalid("A source needs a reference."));
    }
    Ok(SourceDefinition {
        source_binding_id: String::new(),
        source_kind: SourceKind::parse(kind)?,
        role,
        title: reference.chars().take(80).collect(),
        reference: reference.to_owned(),
        covers: vec![],
    })
}
