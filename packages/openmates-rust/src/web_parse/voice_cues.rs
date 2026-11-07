//! Assistant voice-delivery cue stripping for the read projection.
//!
//! Part of the shared `web_parse` core (the `parse` unit of the browser Worker).
//! Mirrors `frontend/packages/ui/src/message_parsing/voiceDeliveryCues.ts`
//! (`stripVoiceDeliveryCues`): a single left-to-right scan with the leftmost-match
//! semantics of its regular expression; the cue allowlist is shared with
//! `assistant_speech/projection.py`. Proven by `voice_cues_ts_vectors.json`.
//! Spec: specifications/surfaces/sdk (sdk.client.thin-platform-boundary).
use super::blocks::js_ws;

/// Cue names accepted inside `<!-- voice:... -->` (keep in sync with the TS/Python lists).
const CUES: [&str; 6] = ["curious", "excited", "thoughtful", "whispers", "laughs", "short pause"];

/// End offset of a closed code literal that starts at `start` (a run of `marker`
/// bytes): up to and including the first later occurrence of the same run, or the
/// end of input when it is never closed (streamed code stays literal).
fn code_literal_end(input: &str, start: usize, marker: u8) -> Option<usize> {
    let bytes = input.as_bytes();
    let run_end = start + bytes[start..].iter().take_while(|&&b| b == marker).count();
    // Tildes only open a fence from three upward; a shorter run is plain text.
    if marker == b'~' && run_end - start < 3 {
        return None;
    }
    let run = &input[start..run_end];
    Some(match input[run_end..].find(run) {
        Some(offset) => run_end + offset + run.len(),
        None => input.len(),
    })
}

/// End offset of a complete allowlisted cue comment starting at `start`.
fn complete_cue_end(input: &str, start: usize) -> Option<usize> {
    let rest = input[start..].strip_prefix("<!--")?.trim_start_matches(js_ws);
    let rest = rest.strip_prefix("voice:")?;
    CUES.iter().find_map(|cue| {
        let after = rest.strip_prefix(cue)?.trim_start_matches(js_ws).strip_prefix("-->")?;
        Some(input.len() - after.len())
    })
}

/// True for a streamed, not yet terminated cue (`<!-- voice:` without any `>` after).
fn is_unterminated_cue(input: &str, start: usize) -> bool {
    input[start..]
        .strip_prefix("<!--")
        .map(|r| r.trim_start_matches(js_ws))
        .and_then(|r| r.strip_prefix("voice:"))
        .is_some_and(|r| !r.contains('>'))
}

/// Replace every voice cue outside code literals by one space.
///
/// Inline (backtick) and tilde fences are copied verbatim; a complete allowlisted
/// cue becomes one space, and an unterminated cue at the stream end swallows the
/// rest of the input into one space. Never fails.
pub fn strip_voice_cues(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut out = String::with_capacity(input.len());
    let (mut index, mut copied) = (0, 0);
    while index < bytes.len() {
        let literal_end = match bytes[index] {
            marker @ (b'`' | b'~') => Some(code_literal_end(input, index, marker)),
            _ => None,
        };
        if let Some(end) = literal_end {
            index = end.unwrap_or_else(|| {
                // A short tilde run is not a literal: step over exactly that run.
                index + bytes[index..].iter().take_while(|&&b| b == b'~').count()
            });
        } else if bytes[index] == b'<' {
            let end = complete_cue_end(input, index)
                .or_else(|| is_unterminated_cue(input, index).then_some(input.len()));
            match end {
                Some(end) => {
                    out.push_str(&input[copied..index]);
                    out.push(' ');
                    index = end;
                    copied = end;
                }
                None => index += 1,
            }
        } else {
            index += 1;
        }
    }
    out.push_str(&input[copied..]);
    out
}
