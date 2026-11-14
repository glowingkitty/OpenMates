//! Live app-skill embed progress for the Apple shell (spec
//! `app-skills.progress.live-status`). The core (`embed_read::progress`) owns
//! frame validation, the highest-`seq`-wins rule and the status-line choice;
//! this module only marshals them. Swift passes the decoded `progress` object
//! as JSON text and translates the returned `embeds.progress_*` key itself.
//! Mirrors the web `embedProgress.ts`; plan `apple-client-core-migration`.
use openmates_sdk::embed_read::progress::{
    EmbedProgress, next_embed_progress, parse_embed_progress, progress_line,
};

/// One validated progress frame.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Record)]
pub struct EmbedProgressRecord {
    /// Sources the skill searches (at least 1).
    pub sources_total: u32,
    /// Sources finished so far.
    pub sources_done: u32,
    /// Results found so far.
    pub result_count: u32,
    /// Frame sequence number; the highest wins.
    pub seq: u32,
}

/// Translatable status line: key, numeric values and a literal prefix.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct EmbedProgressLineRecord {
    /// Full i18n key (`embeds.progress_*`).
    pub key: String,
    /// Placeholder names, parallel to `value_numbers`.
    pub value_names: Vec<String>,
    /// Placeholder values, parallel to `value_names`.
    pub value_numbers: Vec<u32>,
    /// Literal text shown before the translated key, such as `2/4 · `.
    pub prefix: String,
}

impl From<EmbedProgress> for EmbedProgressRecord {
    fn from(p: EmbedProgress) -> Self {
        Self {
            sources_total: p.sources_total,
            sources_done: p.sources_done,
            result_count: p.result_count,
            seq: p.seq,
        }
    }
}

impl From<EmbedProgressRecord> for EmbedProgress {
    fn from(p: EmbedProgressRecord) -> Self {
        Self {
            sources_total: p.sources_total,
            sources_done: p.sources_done,
            result_count: p.result_count,
            seq: p.seq,
        }
    }
}

/// Validate the JSON text of a decoded embed `progress` object; `None` when it
/// is malformed or not JSON.
#[uniffi::export]
pub fn embed_progress_parse(progress_json: String) -> Option<EmbedProgressRecord> {
    let value: serde_json::Value = serde_json::from_str(&progress_json).ok()?;
    parse_embed_progress(&value).map(Into::into)
}

/// Keep the frame with the higher `seq`; lower or equal frames are ignored.
#[uniffi::export]
pub fn embed_progress_next(
    current: Option<EmbedProgressRecord>,
    incoming: Option<EmbedProgressRecord>,
) -> Option<EmbedProgressRecord> {
    next_embed_progress(current.map(Into::into), incoming.map(Into::into)).map(Into::into)
}

/// The status line of a frame as key, values and prefix for the shell to translate.
#[uniffi::export]
pub fn embed_progress_line(progress: EmbedProgressRecord) -> EmbedProgressLineRecord {
    let line = progress_line(&progress.into());
    EmbedProgressLineRecord {
        key: line.key.to_string(),
        value_names: line.values.iter().map(|(n, _)| (*n).to_string()).collect(),
        value_numbers: line.values.iter().map(|(_, v)| *v).collect(),
        prefix: line.prefix,
    }
}
