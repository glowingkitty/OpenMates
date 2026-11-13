//! Bounded ripgrep runner for content search (npm `runRgCommand`,
//! `buildRgContentSearchArgs`, `baseRgArgs` in `remoteAccess.ts`).
//!
//! Ripgrep runs with `--no-config`, a minimal `C` locale environment and
//! negative `--iglob`s for `.git`, binary extensions, every private glob and
//! multiply-linked files, so it never opens a protected file. Output is capped
//! at 2 MiB total and 64 KiB per line, the run is killed after 10 seconds, and
//! reading stops once `max_results + 1` matches arrived (exit by cap is success).

use super::path_policy::PathPolicy;
use super::reads::{BINARY_EXTENSIONS, DEFAULT_MAX_READ_BYTES};
use super::search::{Request, SEARCH_TIMEOUT};
use super::{HostError, HostResult};
use std::io::{BufRead, BufReader, Read};
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

const MAX_RG_STDOUT_BYTES: usize = 2 * 1024 * 1024;
const MAX_RG_LINE_BYTES: usize = 64 * 1024;

/// Why ripgrep produced no usable output.
pub(crate) enum RgError {
    /// `rg` is not installed (npm `ENOENT`): callers fall back or refuse regex.
    Missing,
    /// Any other failure, already mapped to an npm code.
    Failed(HostError),
}

fn base_args(policy: &PathPolicy, hardlinks: &[String]) -> Vec<String> {
    // --no-require-git keeps .gitignore semantics in attached plain folders too.
    let mut args: Vec<String> = ["--no-config", "--hidden", "--color", "never", "--no-require-git"]
        .iter()
        .map(|s| (*s).to_owned())
        .collect();
    let mut patterns: Vec<String> = vec![".git".into(), ".git/**".into(), "**/.git/**".into()];
    for extension in BINARY_EXTENSIONS {
        patterns.push(format!("*{extension}"));
        patterns.push(format!("**/*{extension}"));
    }
    patterns.extend(policy.rg_exclusion_globs().iter().cloned());
    patterns.extend(hardlinks.iter().cloned());
    for pattern in patterns {
        args.push("--iglob".into());
        args.push(format!("!{}", pattern.replace('\\', "/")));
    }
    args
}

/// Content search arguments (npm `buildRgContentSearchArgs`).
pub(crate) fn content_args(
    request: &Request,
    search_path: &str,
    policy: &PathPolicy,
    hardlinks: &[String],
) -> Vec<String> {
    let mut args = base_args(policy, hardlinks);
    args.extend(
        ["--json", "--line-number", "--max-filesize"]
            .iter()
            .map(|s| (*s).to_owned()),
    );
    args.push(DEFAULT_MAX_READ_BYTES.to_string());
    if !request.regex {
        args.push("--fixed-strings".into());
    }
    if let Some(glob) = &request.glob {
        args.push("--glob".into());
        args.push(glob.clone());
    }
    args.extend(["--regexp".to_owned(), request.query.clone(), "--".to_owned()]);
    args.push(search_path.to_owned());
    args
}

/// Run a content search and return the JSON output lines.
///
/// # Errors
/// [`RgError::Missing`] when `rg` is not on `PATH`; otherwise
/// `operation_failed` for timeouts, byte-limit overruns and rg failures.
pub(crate) fn content_search(
    request: &Request,
    root: &Path,
    search_path: &str,
    policy: &PathPolicy,
    hardlinks: &[String],
) -> Result<Vec<String>, RgError> {
    run_rg(
        &content_args(request, search_path, policy, hardlinks),
        root,
        request.max_results + 1,
    )
}

fn failed(message: &str) -> RgError {
    RgError::Failed(HostError::failed(message))
}

fn run_rg(args: &[String], cwd: &Path, max_matches: usize) -> Result<Vec<String>, RgError> {
    let mut command = Command::new("rg");
    command
        .args(args)
        .current_dir(cwd)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .env_clear()
        .env("LC_ALL", "C")
        .env("LANG", "C");
    if let Some(path) = std::env::var_os("PATH") {
        command.env("PATH", path);
    }
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Err(RgError::Missing),
        Err(error) => return Err(failed(&format!("rg could not start: {error}"))),
    };
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| failed("rg stdout is unavailable"))?;
    let child = Arc::new(Mutex::new(child));
    let finished = Arc::new(AtomicBool::new(false));
    let timed_out = Arc::new(AtomicBool::new(false));
    let watchdog = {
        let (child, finished, timed_out) = (child.clone(), finished.clone(), timed_out.clone());
        std::thread::spawn(move || {
            let deadline = std::time::Instant::now() + SEARCH_TIMEOUT;
            while !finished.load(Ordering::Acquire) {
                if std::time::Instant::now() >= deadline {
                    timed_out.store(true, Ordering::Release);
                    if let Ok(mut child) = child.lock() {
                        let _ = child.kill();
                    }
                    return;
                }
                std::thread::sleep(std::time::Duration::from_millis(50));
            }
        })
    };
    let outcome = read_bounded_lines(stdout, max_matches);
    let kill = |child: &Arc<Mutex<std::process::Child>>| -> HostResult<()> {
        let mut guard = child
            .lock()
            .map_err(|_| HostError::failed("rg process lock poisoned"))?;
        let _ = guard.kill();
        Ok(())
    };
    let capped = match &outcome {
        Ok((_, capped)) => *capped,
        Err(_) => true,
    };
    if capped {
        kill(&child).map_err(RgError::Failed)?;
    }
    let status = child
        .lock()
        .map_err(|_| failed("rg process lock poisoned"))?
        .wait()
        .map_err(|e| failed(&format!("rg wait failed: {e}")))?;
    finished.store(true, Ordering::Release);
    let _ = watchdog.join();
    if timed_out.load(Ordering::Acquire) {
        return Err(failed("Remote source search timed out"));
    }
    let (lines, capped) = outcome.map_err(RgError::Failed)?;
    match status.code() {
        Some(0 | 1) => Ok(lines),
        _ if capped => Ok(lines),
        code => Err(failed(&format!("rg failed with exit code {code:?}"))),
    }
}

/// Read newline-delimited output within the byte caps; `true` when the match
/// cap stopped reading early.
fn read_bounded_lines(stdout: impl Read, max_matches: usize) -> HostResult<(Vec<String>, bool)> {
    let mut reader = BufReader::new(stdout);
    let (mut lines, mut total, mut matches) = (Vec::new(), 0usize, 0usize);
    let mut buffer = Vec::new();
    loop {
        buffer.clear();
        let read = (&mut reader)
            .take(MAX_RG_LINE_BYTES as u64 + 1)
            .read_until(b'\n', &mut buffer)
            .map_err(|e| HostError::failed(format!("rg output failed: {e}")))?;
        if read == 0 {
            return Ok((lines, false));
        }
        total += read;
        let line_bytes = buffer.strip_suffix(b"\n").unwrap_or(&buffer);
        if total > MAX_RG_STDOUT_BYTES || line_bytes.len() > MAX_RG_LINE_BYTES {
            return Err(HostError::failed(
                "Remote source search output exceeded its byte limit",
            ));
        }
        if line_bytes.is_empty() {
            continue;
        }
        let line = String::from_utf8_lossy(line_bytes).into_owned();
        if line.contains("\"type\":\"match\"") {
            matches += 1;
        }
        lines.push(line);
        if matches >= max_matches {
            return Ok((lines, true));
        }
    }
}
