//! Upload commands: the personal and Team profile images (multipart to the
//! upload origin with only the refresh cookie) and `apps images detect-ai`
//! (the authenticated file upload pipeline that returns Sightengine
//! metadata). Embedded metadata is removed natively before every upload;
//! npm's warning is kept when the original file has to be uploaded.
use super::{
    CliError, CliOutput, Invocation, METADATA_WARNING, basename, failed, first_of, handlers,
    js_string, ordered_json, output, read_error_text, read_file, required, terminal_text,
    to_fixed_1, upload_error,
};
use crate::client::Client;
use crate::client::profile_upload::prepare_local_upload;
use crate::client::upload::UploadError;
use crate::error::Error;
use openmates_sdk::upload_privacy::upload_mime_type;
use serde_json::Value;

const DETECT_AI_FOOTER: &str = "\n\x1b[2mThis command uses the authenticated upload pipeline, which stores the image and returns Sightengine metadata.\x1b[0m\n";

fn with_warning(mut out: CliOutput, metadata_removed: bool) -> CliOutput {
    if !metadata_removed {
        out.stderr.push_str(METADATA_WARNING);
    }
    out
}

pub(super) async fn profile_picture(
    i: &Invocation,
    client: &mut Client,
) -> Result<CliOutput, CliError> {
    handlers::flags(i, &[])?;
    let file = i.positionals.first().filter(|file| !file.is_empty()).ok_or_else(|| {
        failed("Missing image file. Example: openmates settings account profile-picture set ./avatar.jpg")
    })?;
    let bytes = read_file(file)?;
    let uploaded = client
        .upload_profile_image(basename(file), bytes)
        .await
        .map_err(upload_error)?;
    let out = super::super::settings_more::mutation(i, &uploaded.result)?;
    Ok(with_warning(out, uploaded.metadata_removed))
}

pub(super) async fn team_profile_image(
    i: &Invocation,
    client: &mut Client,
) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["file", "path", "team", "team-id"])?;
    let team = required(
        first_of(i, &["team", "team-id"], Some(0)),
        "--team <team-id>",
    )?;
    let file = required(first_of(i, &["file", "path"], Some(1)), "--file <path>")?;
    let bytes = read_file(&file)?;
    let uploaded = client
        .upload_team_profile_image(&team, basename(&file), bytes)
        .await
        .map_err(upload_error)?;
    let result = &uploaded.result;
    let out = if i.boolean("json") {
        let stdout = ordered_json(&[
            ("status", result["status"].clone()),
            ("url", result["url"].clone()),
            ("team", result["team"].clone()),
        ])?;
        output(stdout, String::new())
    } else {
        output(
            format!(
                "Team profile image uploaded: {}\n",
                terminal_text(&js_string(&result["url"]))
            ),
            String::new(),
        )
    };
    Ok(with_warning(out, uploaded.metadata_removed))
}

/// npm `classifyImagesAiDetection` and `formatImagesAiDetectionLabel`.
pub(super) fn classify(score: Option<f64>) -> (&'static str, &'static str) {
    match score.filter(|score| score.is_finite()) {
        None => ("unavailable", "Detection unavailable"),
        Some(score) if score > 0.7 => ("likely_ai_generated", "Likely AI-generated"),
        Some(score) if score > 0.4 => ("possibly_ai_generated", "Possibly AI-generated"),
        Some(_) => ("likely_not_ai_generated", "Likely not AI-generated"),
    }
}
fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|n| n != 0.0 && !n.is_nan()),
        Value::String(value) => !value.is_empty(),
        _ => true,
    }
}
/// `object?.field ?? null` for a decoded JSON value.
fn field(value: &Value, name: &str) -> Value {
    value
        .get(name)
        .filter(|v| !v.is_null())
        .cloned()
        .unwrap_or(Value::Null)
}

/// npm `buildImagesAiDetectionSummary`, in its key order.
pub(super) fn detection_summary(
    file: &str,
    filename: &str,
    content_type: &str,
    embed_id: &str,
    deduplicated: &Value,
    detection: &Value,
) -> Vec<(&'static str, Value)> {
    let status = match field(detection, "status") {
        Value::Null if truthy(detection) => Value::from("success"),
        Value::Null => Value::from("unavailable"),
        status => status,
    };
    let success = status == "success";
    let score = if success {
        detection.get("ai_generated").and_then(Value::as_f64)
    } else {
        None
    };
    let (classification, label) = classify(score);
    let mut entries = vec![
        ("success", Value::Bool(success)),
        ("file", Value::from(file)),
        ("filename", Value::from(filename)),
        ("content_type", Value::from(content_type)),
        ("embed_id", Value::from(embed_id)),
    ];
    // `undefined` is omitted by JSON.stringify.
    if !deduplicated.is_null() {
        entries.push(("deduplicated", deduplicated.clone()));
    }
    entries.extend([
        ("stored", Value::Bool(true)),
        ("status", status),
        ("provider", field(detection, "provider")),
        (
            "ai_generated",
            score
                .filter(|score| score.is_finite())
                .and_then(serde_json::Number::from_f64)
                .map_or(Value::Null, Value::Number),
        ),
        ("classification", Value::from(classification)),
        ("label", Value::from(label)),
        ("error", field(detection, "error")),
    ]);
    entries
}
fn entry<'a>(entries: &'a [(&'static str, Value)], name: &str) -> &'a Value {
    entries
        .iter()
        .find(|(key, _)| *key == name)
        .map_or(&Value::Null, |(_, value)| value)
}
fn kv(out: &mut String, key: &str, value: &str) {
    out.push_str(&format!(
        "  \x1b[2m{key:<16}\x1b[0m {}\n",
        terminal_text(value)
    ));
}
/// The npm text report for a detection summary.
pub(super) fn detection_text(entries: &[(&'static str, Value)]) -> String {
    let mut out = "\x1b[1mImages › Detect AI\x1b[0m\n".to_owned();
    kv(&mut out, "File", &js_string(entry(entries, "file")));
    let provider = entry(entries, "provider");
    kv(
        &mut out,
        "Provider",
        &if provider.is_null() {
            "n/a".into()
        } else {
            js_string(provider)
        },
    );
    kv(
        &mut out,
        "Detection status",
        &js_string(entry(entries, "status")),
    );
    let probability = match entry(entries, "ai_generated").as_f64() {
        Some(score) => format!("{}%", to_fixed_1(score * 100.0)),
        None => "unavailable".into(),
    };
    kv(&mut out, "AI-generated probability", &probability);
    kv(
        &mut out,
        "Classification",
        &js_string(entry(entries, "label")),
    );
    kv(
        &mut out,
        "Stored upload embed",
        &js_string(entry(entries, "embed_id")),
    );
    let error = entry(entries, "error");
    if truthy(error) {
        kv(&mut out, "Detection error", &js_string(error));
    }
    out.push_str(DETECT_AI_FOOTER);
    out
}

fn refusal(stderr: String) -> CliOutput {
    CliOutput {
        stdout: String::new(),
        stderr,
        exit_code: 1,
    }
}

/// `apps images detect-ai|detect_ai`: npm `handleImagesDetectAi`, which
/// reports its own failures on stderr with exit 1.
pub(super) async fn detect_ai(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["file"])?;
    let file_flag = i
        .text("file")
        .map(str::trim)
        .filter(|file| !file.is_empty());
    let Some(file) = file_flag
        .or(i.positionals.first().map(String::as_str))
        .filter(|f| !f.is_empty())
    else {
        return Ok(refusal(
            "Missing image file.\n\nUsage:\n  openmates apps images detect-ai --file ./image.png [--json]\n\n"
                .into(),
        ));
    };
    let unexpected = if file_flag.is_some() {
        &i.positionals[..]
    } else {
        &i.positionals[1.min(i.positionals.len())..]
    };
    if !unexpected.is_empty() {
        return Ok(refusal(format!(
            "Unexpected argument(s): {}\n\nRun: openmates apps images detect-ai --help\n",
            terminal_text(&unexpected.join(" "))
        )));
    }
    let Ok(resolved) = std::fs::canonicalize(file) else {
        return Ok(refusal(format!(
            "\x1b[31m✗ Image file not found:\x1b[0m {}\n",
            terminal_text(file)
        )));
    };
    let resolved = resolved.to_string_lossy().into_owned();
    let filename = basename(&resolved).to_owned();
    let mut warning = String::new();
    let uploaded = async {
        let bytes = std::fs::read(&resolved)
            .map_err(|error| UploadError::Rejected(read_error_text(&resolved, &error)))?;
        let prepared = prepare_local_upload(bytes, &filename, upload_mime_type(&filename))?;
        if !prepared.sanitized {
            warning.push_str(METADATA_WARNING);
        }
        client
            .upload_file_bytes(&filename, &prepared.bytes, &prepared.mime_type)
            .await
    }
    .await;
    let upload = match uploaded {
        Ok(upload) => upload,
        Err(UploadError::Client(Error::Cancelled)) => {
            return Err(CliError::Client(Error::Cancelled));
        }
        Err(error) => {
            return Ok(refusal(format!(
                "{warning}\x1b[31m✗ Images AI detection failed:\x1b[0m {}\n",
                terminal_text(&error.to_string())
            )));
        }
    };
    let shown_filename = if upload.filename.is_empty() {
        filename.as_str()
    } else {
        upload.filename.as_str()
    };
    let mut entries = detection_summary(
        &resolved,
        shown_filename,
        &upload.content_type,
        &upload.embed_id,
        &upload.deduplicated,
        &upload.ai_detection,
    );
    let stdout = if i.boolean("json") {
        entries.push(("ai_detection", upload.ai_detection.clone()));
        ordered_json(&entries)?
    } else {
        detection_text(&entries)
    };
    Ok(output(stdout, warning))
}
