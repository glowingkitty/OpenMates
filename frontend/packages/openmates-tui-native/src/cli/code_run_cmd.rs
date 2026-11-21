//! `openmates apps code run`: run code in an E2B sandbox through the
//! `code/run` app skill with an API key.
//!
//! This adapter only reads files from disk; request building, limits and the
//! human output live in the shared core (`openmates_sdk::code_run_request`).
//! The run is polled to a final state by the SDK. Out of scope for now:
//! `--url`, `--repo`, chat-bound runs and live streaming.
use super::{CliError, CliOutput, Invocation, e2b_consent_cmd};
use crate::error::Error;
use openmates_sdk::{
    client::{Client, DirectAppSkillAdmission, E2bConsentChoice},
    code_run_request::{self as core, CodeRunError, CodeRunFile},
    sdk::OpenMates,
};
use serde_json::Value;
use std::{future::Future, path::Path};
use tokio_util::sync::CancellationToken;

const ALLOWED: &[&str] = &[
    "code",
    "language",
    "source-filename",
    "entry",
    "file",
    "dir",
    "include",
    "exclude",
    "no-internet",
    "allow-e2b-upload",
];
const OUT_OF_SCOPE: &[&str] = &["url", "repo", "chat", "target-embed"];

/// True for the `apps code run` command path.
pub(super) fn is_code_run(invocation: &Invocation) -> bool {
    invocation.command_path() == "apps code run"
}

fn invalid(error: CodeRunError) -> CliError {
    CliError::Invalid(error.to_string())
}

fn check_flags(i: &Invocation) -> Result<(), CliError> {
    for key in i.flags.keys() {
        if OUT_OF_SCOPE.contains(&key.as_str()) {
            return Err(CliError::Unsupported {
                command: i.command_path(),
                reason: format!(
                    "Option --{key} is not available in the native CLI yet; use --code, --file or --dir."
                ),
            });
        }
        if !super::handlers::GLOBALS.contains(&key.as_str()) && !ALLOWED.contains(&key.as_str()) {
            return Err(CliError::Unsupported {
                command: i.command_path(),
                reason: format!("Option --{key} is not ported for this native handler."),
            });
        }
    }
    Ok(())
}

fn read(path: &Path) -> Result<Vec<u8>, CliError> {
    std::fs::read(path)
        .map_err(|e| CliError::Invalid(format!("Cannot read {}: {}", path.display(), e.kind())))
}

fn walk(
    root: &Path,
    dir: &Path,
    include: &[&str],
    exclude: &[String],
    out: &mut Vec<(String, std::path::PathBuf)>,
) -> Result<(), CliError> {
    let entries = std::fs::read_dir(dir).map_err(|e| {
        CliError::Invalid(format!("Cannot read {}: {}", dir.display(), e.kind()))
    })?;
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        let path = entry.path();
        let rel = path
            .strip_prefix(root)
            .map(|p| p.to_string_lossy().replace('\\', "/"))
            .unwrap_or_else(|_| name.clone());
        if core::matches_any(&rel, exclude) || core::matches_any(&name, exclude) {
            continue;
        }
        let Ok(kind) = entry.file_type() else { continue };
        if kind.is_dir() {
            walk(root, &path, include, exclude, out)?;
        } else if kind.is_file() && (include.is_empty() || core::matches_any(&rel, include)) {
            out.push((rel, path));
        }
    }
    Ok(())
}

/// Read the flags' files from disk and build the request body.
fn build_body(i: &Invocation, allow_upload: bool) -> Result<Value, CliError> {
    check_flags(i)?;
    let (language, entry) = (i.text("language"), i.text("entry"));
    let mut files = vec![];
    if let Some(code) = i.text("code") {
        files.push(
            core::inline_file(code, language, i.text("source-filename"), entry).map_err(invalid)?,
        );
    }
    for path in i.values("file") {
        let name = Path::new(path)
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default();
        files.push(CodeRunFile {
            path: name,
            content: read(Path::new(path))?,
            language: None,
        });
    }
    let include = i.values("include");
    let exclude: Vec<String> = core::DEFAULT_IGNORES
        .iter()
        .map(|s| (*s).to_owned())
        .chain(i.values("exclude").into_iter().map(str::to_owned))
        .collect();
    for dir in i.values("dir") {
        let root = Path::new(dir);
        if !root.is_dir() {
            return Err(CliError::Invalid(format!(
                "Code Run --dir is not a directory: {dir}"
            )));
        }
        let mut found = vec![];
        walk(root, root, &include, &exclude, &mut found)?;
        found.sort();
        for (rel, path) in found {
            files.push(CodeRunFile {
                path: rel,
                content: read(&path)?,
                language: None,
            });
        }
    }
    core::build_direct_request(files, entry, !i.boolean("no-internet"), allow_upload)
        .map_err(invalid)
}

fn finish(i: &Invocation, response: &Value, mut stderr: String) -> Result<CliOutput, CliError> {
    let data = if response["data"].is_object() { &response["data"] } else { response };
    let result = data["results"]
        .get(0)
        .filter(|r| r["final"].is_object())
        .ok_or_else(|| CliError::Invalid("Code Run did not return an execution id.".into()))?;
    let status = &result["final"];
    let mut output = if i.boolean("json") {
        CliOutput::json(result)?
    } else {
        CliOutput {
            stdout: super::terminal_text(&core::format_final_status(status)),
            stderr: String::new(),
            exit_code: 0,
        }
    };
    if !i.boolean("json") {
        stderr.push_str(&super::terminal_text(&core::final_status_stderr(status)));
    }
    let state = status["status"].as_str().unwrap_or("unknown");
    let code = status["exit_code"].as_i64();
    if state != "finished" || code != Some(0) {
        let code = code.map_or("unknown".to_owned(), |c| c.to_string());
        stderr.push_str(&format!("Code Run {state} with exit code {code}.\n"));
        output.exit_code = 1;
    }
    output.stderr = stderr;
    Ok(output)
}

/// Ask the user (interactive only) whether to allow the E2B upload once.
fn consent_allowed(i: &Invocation) -> bool {
    e2b_consent_cmd::can_prompt(i)
        && matches!(
            e2b_consent_cmd::ask(&mut std::io::stdin().lock(), &mut std::io::stderr()),
            Some(E2bConsentChoice::Allow)
        )
}

/// Print a progress line on stderr right away (not with the buffered final
/// output), so it appears before the run's own output.
fn print_progress(line: &str) {
    use std::io::Write;
    let mut stderr = std::io::stderr();
    // Best effort, like the other CLI progress lines: a closed stderr must not fail the run.
    let _ = stderr.write_all(line.as_bytes());
    let _ = stderr.flush();
}

/// Build, send (with the E2B consent step) and render one Code Run.
/// `progress` receives the starting line once, before the billable request.
async fn flow<F, Fut>(
    i: &Invocation,
    progress: impl FnOnce(&str),
    mut send: F,
) -> Result<CliOutput, CliError>
where
    F: FnMut(Value) -> Fut,
    Fut: Future<Output = Result<Value, Error>>,
{
    let mut allow = i.boolean("allow-e2b-upload");
    let mut body = build_body(i, allow)?;
    let request = &body["requests"][0];
    let count = request["files"].as_array().map_or(0, Vec::len);
    let starting = if i.boolean("json") {
        String::new()
    } else {
        format!(
            "Starting Code Run for {} ({count} file{})...\n",
            request["entry_path"].as_str().unwrap_or(""),
            if count == 1 { "" } else { "s" }
        )
    };
    if !starting.is_empty() {
        progress(&starting);
    }
    loop {
        match send(body.clone()).await {
            Ok(response) => return finish(i, &response, String::new()),
            Err(error) => {
                let error = CliError::Client(error);
                let Some(refusal) = e2b_consent_cmd::refusal_output(&error) else {
                    return Err(error);
                };
                if allow || !consent_allowed(i) {
                    return Ok(refusal);
                }
                allow = true;
                body["allow_e2b_upload"] = Value::Bool(true);
            }
        }
    }
}

/// Execute `apps code run` with an API key.
pub(super) async fn execute(
    i: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    check_flags(i)?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    client.set_operation_cancel(cancel.clone());
    let sdk = &*client;
    let output = flow(i, print_progress, |body| async move {
        sdk.apps().code().run(body).await
    })
    .await;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    output
}

/// Execute `apps code run` with the logged-in session. The caller already
/// holds the direct-app-skill `admission` and the operation cancellation; the
/// core posts the run, polls every status path and maps the E2B consent 403.
pub(super) async fn execute_session(
    i: &Invocation,
    client: &mut Client,
    admission: &DirectAppSkillAdmission,
) -> Result<CliOutput, CliError> {
    check_flags(i)?;
    let client = tokio::sync::Mutex::new(client);
    flow(i, print_progress, |body| {
        let client = &client;
        async move { client.lock().await.run_code_with_status(body, admission).await }
    })
    .await
}

#[cfg(test)]
#[path = "code_run_cmd_tests.rs"]
mod tests;
