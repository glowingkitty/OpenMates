//! Typing, processing and streaming indicator decisions.
//!
//! Mirrors the decisions of `ActiveChat.svelte` (`typingIndicatorLines`,
//! `typingIndicatorStatusType`) and `chats/Chat.svelte`
//! (`typingIndicatorInTitleView`). The page resolves its reactive state into the
//! flags below (chat match, accepted-turn match, model reasoning lookup, display
//! name) and renders the answer: Rust picks which lines show; translations stay
//! in the page. A line is `{"k":"key","key":..}` (a localized key),
//! `{"k":"literal","text":..}` (verbatim), `{"k":"mate","category":..,"thinking":..}`
//! ("{mate} is typing/thinking...") or `{"k":"skill","appId":..,"skillId":..}`.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use serde_json::{Value, json};

use super::args::{array, flag, opt_text, text};
use super::{parse, protocol};

fn region_flag(region: &str) -> &'static str {
    match region {
        "EU" => "\u{1F1EA}\u{1F1FA}",
        "US" => "\u{1F1FA}\u{1F1F8}",
        "APAC" => "\u{1F30F}",
        "global" => "\u{1F310}",
        "Local" => "\u{1F3E0}",
        _ => "",
    }
}

fn non_empty(value: Option<&str>) -> Option<&str> {
    value.filter(|s| !s.is_empty())
}

fn mate_line(category: &str, thinking: bool) -> Value {
    json!({"k": "mate", "category": category, "thinking": thinking})
}

fn texts(value: &Value, key: &str) -> Result<Vec<Value>, String> {
    array(value, key)?
        .iter()
        .map(|l| {
            l.as_str()
                .map(|s| json!({"k": "literal", "text": s}))
                .ok_or_else(|| protocol(()))
        })
        .collect()
}

/// Composer indicator for `{projectProgress, terminal, feedbackThisChat,
/// feedbackPresent, explicitMate, typingMatchesFeedback, phase, phaseLines,
/// anonymous, typing: {active, chatMatch, category, modelName, providerName,
/// serverRegion, reasoning, displayModelName}}`. Answers `{lines, statusType}`.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn composer_json(input: &str) -> Result<String, String> {
    let v = parse(input)?;
    let progress = opt_text(&v, "projectProgress")?;
    let terminal = flag(&v, "terminal")?;
    let feedback_here = flag(&v, "feedbackThisChat")?;
    let feedback_any = flag(&v, "feedbackPresent")?;
    let explicit_mate = flag(&v, "explicitMate")?;
    let matches = flag(&v, "typingMatchesFeedback")?;
    let phase = opt_text(&v, "phase")?;
    let anonymous = flag(&v, "anonymous")?;
    let t = v.get("typing").ok_or_else(|| protocol(()))?;
    let typing_here = flag(t, "active")? && flag(t, "chatMatch")?;
    let category = non_empty(opt_text(t, "category")?);

    let status = if progress.is_some() {
        json!("processing")
    } else if terminal {
        Value::Null
    } else if feedback_here {
        json!(if matches { "typing" } else { "processing" })
    } else if phase.is_some() && phase != Some("compressing") {
        if anonymous {
            json!("typing")
        } else {
            Value::Null
        }
    } else if phase == Some("compressing") || typing_here {
        json!("typing")
    } else {
        Value::Null
    };

    let lines: Vec<Value> = if let Some(key) = progress {
        vec![json!({"k": "key", "key": format!("embeds.projects.progress.{key}")})]
    } else if terminal {
        vec![]
    } else if feedback_here && !matches {
        let key = if explicit_mate {
            "enter_message.status.selecting_model"
        } else {
            "enter_message.status.selecting_mate_and_model"
        };
        vec![json!({"k": "key", "key": key})]
    } else if phase.is_some() && phase != Some("compressing") && !matches {
        if anonymous {
            texts(&v, "phaseLines")?
        } else {
            vec![]
        }
    } else if phase == Some("compressing") {
        texts(&v, "phaseLines")?
    } else if let (true, Some(category), true) = (typing_here, category, !feedback_any || matches) {
        let mut lines = vec![mate_line(category, flag(t, "reasoning")?)];
        if let Some(model) = non_empty(opt_text(t, "displayModelName")?) {
            lines.push(json!({"k": "literal", "text": format!("Powered by {model}")}));
        }
        if let Some(provider) = non_empty(opt_text(t, "providerName")?) {
            let emoji = non_empty(opt_text(t, "serverRegion")?).map_or("", region_flag);
            let line = if emoji.is_empty() {
                format!("via {provider}")
            } else {
                format!("via {provider} {emoji}")
            };
            lines.push(json!({"k": "literal", "text": line}));
        }
        lines
    } else {
        vec![]
    };
    Ok(json!({"lines": lines, "statusType": status}).to_string())
}

/// Chat-row title indicator for `{active, category, skill: {appId, skillId}|null,
/// reasoning}`: a `skill` line (active skill first), a `mate` line, or null.
///
/// # Errors
/// Returns the fixed `protocol` code for malformed input.
pub fn title_json(input: &str) -> Result<String, String> {
    let v = parse(input)?;
    let category = non_empty(opt_text(&v, "category")?);
    let line = match (flag(&v, "active")?, category) {
        (true, Some(category)) => match v.get("skill") {
            Some(Value::Null) => mate_line(category, flag(&v, "reasoning")?),
            Some(skill) => {
                json!({"k": "skill", "appId": text(skill, "appId")?, "skillId": text(skill, "skillId")?})
            }
            None => return Err(protocol(())),
        },
        _ => Value::Null,
    };
    Ok(line.to_string())
}
