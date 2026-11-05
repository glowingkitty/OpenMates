//! `benchmark prompt-budget compare` (npm comparePromptBudgetArtifacts):
//! a local comparison of two saved prompt-budget artifacts. No account,
//! network or inference is involved.
use super::super::{CliError, CliOutput, Invocation, handlers};
use super::{js_number, json_number};
use serde_json::{Value, json};

fn fail(message: impl Into<String>) -> CliError {
    CliError::Invalid(message.into())
}
fn text_flag<'a>(i: &'a Invocation, key: &str) -> Option<&'a str> {
    i.text(key).filter(|v| !v.is_empty())
}
/// JavaScript `Math.round(value * 100) / 100` (halves round toward +infinity).
fn round2(value: f64) -> f64 {
    (value * 100.0 + 0.5).floor() / 100.0
}
fn read_artifact(path: &str) -> Result<Value, CliError> {
    let raw = std::fs::read_to_string(path)
        .map_err(|_| fail(format!("ENOENT: no such file or directory, open '{path}'")))?;
    let parsed: Value = serde_json::from_str(&raw)
        .map_err(|_| fail(format!("Invalid prompt-budget artifact: {path}")))?;
    if !parsed.is_object() {
        return Err(fail(format!("Invalid prompt-budget artifact: {path}")));
    }
    Ok(parsed)
}
fn metric(baseline: &Value, postchange: &Value) -> Value {
    match (baseline.as_f64(), postchange.as_f64()) {
        (Some(b), Some(p)) => {
            let delta = round2(p - b);
            let percent = if b == 0.0 {
                Value::Null
            } else {
                json_number(round2(delta / b * 100.0))
            };
            json!({"baseline":json_number(b),"postchange":json_number(p),"delta":json_number(delta),"percent":percent})
        }
        _ => json!({"baseline":baseline,"postchange":postchange,"delta":null,"percent":null}),
    }
}
fn score(value: &Value) -> Option<f64> {
    value.as_f64()
}
fn hashes(case: &Value) -> String {
    case["promptHashes"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|v| match v {
            Value::String(s) => s.clone(),
            other => other.to_string(),
        })
        .collect::<Vec<_>>()
        .join("|")
}
fn label(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.as_f64().map(js_number).unwrap_or_default(),
        Value::Null => "null".into(),
        other => other.to_string(),
    }
}
fn score_regression(out: &mut Vec<String>, prefix: &str, what: &str, before: f64, after: f64) {
    let (b, a) = (js_number(before), js_number(after));
    if before >= 4.0 && after < 4.0 {
        out.push(format!(
            "{prefix}: {what}dropped below pass threshold ({b} -> {a})"
        ));
    } else if after < before - 1.0 {
        out.push(format!("{prefix}: {what}dropped materially ({b} -> {a})"));
    }
}
/// npm findPromptBudgetRegressions.
pub(super) fn regressions(baseline: &Value, postchange: &Value) -> Vec<String> {
    let mut out = vec![];
    let post_cases = postchange["cases"].as_array().cloned().unwrap_or_default();
    for base_case in baseline["cases"].as_array().into_iter().flatten() {
        let id = label(&base_case["id"]);
        // JavaScript Map construction keeps the last case for a repeated id.
        let Some(post_case) = post_cases.iter().rev().find(|c| c["id"] == base_case["id"]) else {
            out.push(format!("{id}: missing post-change case"));
            continue;
        };
        if hashes(base_case) != hashes(post_case) {
            out.push(format!("{id}: prompt hashes differ"));
        }
        for base_turn in base_case["turns"].as_array().into_iter().flatten() {
            let turn = label(&base_turn["turn"]);
            let Some(post_turn) = post_case["turns"]
                .as_array()
                .into_iter()
                .flatten()
                .find(|t| t["turn"] == base_turn["turn"])
            else {
                out.push(format!("{id} turn {turn}: missing post-change turn"));
                continue;
            };
            if let (Some(b), Some(a)) = (
                score(&base_turn["judge"]["score"]),
                score(&post_turn["judge"]["score"]),
            ) {
                score_regression(&mut out, &format!("{id} turn {turn}"), "score ", b, a);
            }
        }
        if let (Some(b), Some(a)) = (
            score(&base_case["continuityJudge"]["score"]),
            score(&post_case["continuityJudge"]["score"]),
        ) {
            score_regression(&mut out, &id, "continuity score ", b, a);
        }
    }
    out
}
pub(super) fn comparison(
    baseline_path: &str,
    postchange_path: &str,
    baseline: &Value,
    postchange: &Value,
) -> Result<Value, CliError> {
    if baseline["command"] != "benchmark prompt-budget"
        || postchange["command"] != "benchmark prompt-budget"
    {
        return Err(fail(
            "prompt-budget compare expects prompt-budget benchmark artifacts",
        ));
    }
    if baseline["corpusHash"] != postchange["corpusHash"] {
        return Err(fail(
            "prompt-budget artifacts use different corpus hashes and cannot be compared",
        ));
    }
    let found = regressions(baseline, postchange);
    let summary = |key: &str| metric(&baseline["summary"][key], &postchange["summary"][key]);
    let duration = summary("averageTurnDurationMs");
    let latency_improved = duration["delta"].as_f64().is_some_and(|d| d < 0.0);
    let regressed = !found.is_empty();
    Ok(json!({
        "command": "benchmark prompt-budget compare",
        "status": if regressed { "needs_fix" } else { "passed" },
        "corpusHash": baseline["corpusHash"],
        "baseline": baseline_path,
        "postchange": postchange_path,
        "deltas": {
            "averageTurnDurationMs": duration,
            "averageJudgeScore": summary("averageJudgeScore"),
            "averageContinuityScore": summary("averageContinuityScore"),
        },
        "regressions": found,
        "recommendation": if !regressed && latency_improved { "keep" } else { "adjust_or_revert" },
    }))
}
fn format_delta(delta: &Value, unit: &str) -> String {
    if delta["delta"].is_null() {
        return "n/a".into();
    }
    let percent = if delta["percent"].is_null() {
        String::new()
    } else {
        format!(" ({}%)", label(&delta["percent"]))
    };
    format!(
        "{}{unit} -> {}{unit} ({}{unit}){percent}",
        label(&delta["baseline"]),
        label(&delta["postchange"]),
        label(&delta["delta"])
    )
}
pub(super) fn comparison_text(result: &Value) -> String {
    let mut out = format!(
        "Prompt-budget comparison {}: {}\nCorpus: {}\nDuration delta: {}\nQuality delta: {}\n",
        label(&result["status"]),
        label(&result["recommendation"]),
        label(&result["corpusHash"]),
        format_delta(&result["deltas"]["averageTurnDurationMs"], "ms"),
        format_delta(&result["deltas"]["averageJudgeScore"], ""),
    );
    let items = result["regressions"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    if !items.is_empty() {
        out.push_str("Regressions:\n");
        for item in items {
            out.push_str(&format!("- {}\n", label(&item)));
        }
    }
    out
}
pub(super) fn compare(i: &Invocation) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["baseline", "postchange", "output"])?;
    let (Some(baseline_path), Some(postchange_path)) =
        (text_flag(i, "baseline"), text_flag(i, "postchange"))
    else {
        return Err(fail(
            "prompt-budget compare requires --baseline <path> and --postchange <path>",
        ));
    };
    let baseline = read_artifact(baseline_path)?;
    let postchange = read_artifact(postchange_path)?;
    let result = comparison(baseline_path, postchange_path, &baseline, &postchange)?;
    let output = text_flag(i, "output");
    if i.boolean("json") || output.is_some() {
        let mut text = serde_json::to_string_pretty(&result)
            .map_err(|_| CliError::Client(crate::error::Error::Protocol))?;
        text.push('\n');
        if let Some(path) = output {
            std::fs::write(path, &text).map_err(|_| fail(format!("Could not write {path}.")))?;
        }
        return Ok(CliOutput {
            stdout: text,
            stderr: String::new(),
            exit_code: 0,
        });
    }
    Ok(CliOutput::text(comparison_text(&result)))
}
