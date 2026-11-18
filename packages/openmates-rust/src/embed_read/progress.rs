//! spec: sdk.client.thin-platform-boundary
//! Live progress of a running app-skill embed (port of the web
//! `embedProgress.ts`). The server re-sends the "processing" embed with a
//! `progress` object; later frames (higher `seq`) replace earlier ones. The
//! status line is returned as an i18n key plus values so every shell translates
//! it with its own strings (`embeds.progress_*`).

use serde_json::Value;

/// One validated progress frame.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EmbedProgress {
    /// Number of sources the skill searches (at least 1).
    pub sources_total: u32,
    /// Sources finished so far, never above `sources_total`.
    pub sources_done: u32,
    /// Results found so far.
    pub result_count: u32,
    /// Frame sequence number; the highest wins.
    pub seq: u32,
}

/// Translatable status line: an `embeds.progress_*` key and its numeric values.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProgressLine {
    /// Full i18n key, for example `embeds.progress_results`.
    pub key: &'static str,
    /// `(placeholder, value)` pairs to substitute into the translation.
    pub values: Vec<(&'static str, u32)>,
    /// Text placed before the translated key (`2/4 · `), empty when none.
    pub prefix: String,
}

fn count(raw: &Value, field: &str) -> Option<u32> {
    raw.get(field)?.as_u64().and_then(|n| u32::try_from(n).ok())
}

/// Validate a decoded `progress` value; `None` when absent or malformed.
pub fn parse_embed_progress(value: &Value) -> Option<EmbedProgress> {
    let sources_total = count(value, "sources_total").filter(|n| *n >= 1)?;
    let sources_done = count(value, "sources_done")?;
    Some(EmbedProgress {
        sources_total,
        sources_done: sources_done.min(sources_total),
        result_count: count(value, "result_count")?,
        seq: count(value, "seq")?,
    })
}

/// Keep the frame with the higher `seq`; a lower or equal one is ignored.
pub fn next_embed_progress(
    current: Option<EmbedProgress>,
    incoming: Option<EmbedProgress>,
) -> Option<EmbedProgress> {
    match (current, incoming) {
        (cur, None) => cur,
        (Some(cur), Some(inc)) if inc.seq <= cur.seq => Some(cur),
        (_, inc) => inc,
    }
}

/// Status line of a frame, mirroring `formatEmbedProgress`.
pub fn progress_line(progress: &EmbedProgress) -> ProgressLine {
    let results: Option<(&'static str, Vec<(&'static str, u32)>)> = match progress.result_count {
        0 => None,
        1 => Some(("embeds.progress_result_one", vec![])),
        n => Some(("embeds.progress_results", vec![("count", n)])),
    };
    if progress.sources_total == 1 {
        let (key, values) = results.unwrap_or(("embeds.progress_searching", vec![]));
        return ProgressLine {
            key,
            values,
            prefix: String::new(),
        };
    }
    match results {
        None => ProgressLine {
            key: "embeds.progress_searching_sources",
            values: vec![
                ("total", progress.sources_total),
                ("done", progress.sources_done),
            ],
            prefix: String::new(),
        },
        Some((key, values)) => ProgressLine {
            key,
            values,
            prefix: format!("{}/{} · ", progress.sources_done, progress.sources_total),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn p(total: u32, done: u32, results: u32, seq: u32) -> EmbedProgress {
        EmbedProgress {
            sources_total: total,
            sources_done: done,
            result_count: results,
            seq,
        }
    }

    #[test]
    fn parses_valid_and_rejects_malformed() {
        let ok = json!({"sources_total":4,"sources_done":2,"result_count":17,"seq":3});
        assert_eq!(parse_embed_progress(&ok), Some(p(4, 2, 17, 3)));
        assert_eq!(parse_embed_progress(&json!(null)), None);
        let zero = json!({"sources_total":0,"sources_done":0,"result_count":0,"seq":1});
        assert_eq!(parse_embed_progress(&zero), None);
        let text = json!({"sources_total":"4","sources_done":2,"result_count":1,"seq":1});
        assert_eq!(parse_embed_progress(&text), None);
        let neg = json!({"sources_total":4,"sources_done":-1,"result_count":1,"seq":1});
        assert_eq!(parse_embed_progress(&neg), None);
        let over = json!({"sources_total":2,"sources_done":9,"result_count":0,"seq":1});
        assert_eq!(parse_embed_progress(&over), Some(p(2, 2, 0, 1)));
    }

    #[test]
    fn higher_seq_wins() {
        let a = p(4, 1, 3, 2);
        let b = p(4, 2, 3, 3);
        assert_eq!(next_embed_progress(Some(a), Some(b)), Some(b));
        assert_eq!(next_embed_progress(Some(b), Some(a)), Some(b));
        assert_eq!(next_embed_progress(Some(b), Some(p(4, 0, 0, 3))), Some(b));
        assert_eq!(next_embed_progress(Some(b), None), Some(b));
        assert_eq!(next_embed_progress(None, Some(a)), Some(a));
    }

    #[test]
    fn lines_match_web_formatting() {
        let l = progress_line(&p(4, 2, 17, 1));
        assert_eq!(l.key, "embeds.progress_results");
        assert_eq!(l.values, vec![("count", 17)]);
        assert_eq!(l.prefix, "2/4 · ");
        let l = progress_line(&p(4, 0, 0, 1));
        assert_eq!(l.key, "embeds.progress_searching_sources");
        assert_eq!(l.values, vec![("total", 4), ("done", 0)]);
        assert_eq!(
            progress_line(&p(1, 0, 17, 1)).key,
            "embeds.progress_results"
        );
        assert_eq!(progress_line(&p(1, 0, 17, 1)).prefix, "");
        assert_eq!(
            progress_line(&p(1, 0, 1, 1)).key,
            "embeds.progress_result_one"
        );
        assert_eq!(
            progress_line(&p(1, 0, 0, 1)).key,
            "embeds.progress_searching"
        );
        assert_eq!(progress_line(&p(3, 1, 1, 1)).prefix, "1/3 · ");
    }
}
