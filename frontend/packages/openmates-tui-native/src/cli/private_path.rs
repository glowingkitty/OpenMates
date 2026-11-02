//! Actionable messages for the native state directory's privacy checks.
//!
//! The credential store and trusted-account marker require owner-only
//! permissions (directories 0700, files 0600) and refuse anything else. The
//! store reports a refusal as a generic local I/O error; this module names
//! the exact path and the command that fixes it. Checks are never relaxed.
use super::CliError;
use std::path::Path;

/// `~/…` for paths under the home directory, otherwise the full path.
pub fn display(path: &Path) -> String {
    let home = directories::BaseDirs::new().map(|dirs| dirs.home_dir().to_path_buf());
    match home.as_deref().and_then(|home| path.strip_prefix(home).ok()) {
        Some(rest) if !rest.as_os_str().is_empty() => format!("~/{}", rest.display()),
        _ => path.display().to_string(),
    }
}
fn quoted(path: &Path) -> String {
    let shown = display(path);
    if shown.chars().all(|c| c.is_ascii_alphanumeric() || "/~._-".contains(c)) {
        shown
    } else {
        format!("'{}'", shown.replace('\'', "'\\''"))
    }
}

/// Why `path` fails the owner-only policy, with the fix; `None` if it passes
/// or does not exist.
pub fn problem(path: &Path, directory: bool) -> Option<String> {
    let metadata = std::fs::symlink_metadata(path).ok()?;
    let kind = if directory { "directory" } else { "file" };
    if metadata.file_type().is_symlink() || metadata.is_dir() != directory {
        return Some(format!(
            "{} must be a real {kind}, not a symlink or a {}. Move it aside and retry.",
            quoted(path),
            if directory { "file" } else { "directory" },
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.uid() != rustix::process::geteuid().as_raw() {
            return Some(format!(
                "{} is owned by another user. The OpenMates state {kind} must belong to you; fix it with `sudo chown {}$(id -un) {}`.",
                quoted(path),
                if directory { "-R " } else { "" },
                quoted(path),
            ));
        }
        let mode = metadata.mode() & 0o777;
        let wanted = if directory { 0o700 } else { 0o600 };
        if mode & 0o077 != 0 {
            return Some(format!(
                "{} is accessible by other users (mode {mode:o}). Run `chmod {wanted:o} {}` and retry.",
                quoted(path),
                quoted(path),
            ));
        }
    }
    None
}

/// Check a native state directory and its direct entries before the store
/// refuses them with a generic error.
pub fn state_dir_problem(state_dir: &Path) -> Option<String> {
    if let Some(problem) = problem(state_dir, true) {
        return Some(problem);
    }
    let entries = std::fs::read_dir(state_dir).ok()?;
    for entry in entries.flatten().take(4096) {
        let Ok(kind) = entry.file_type() else { continue };
        if kind.is_symlink() {
            continue;
        }
        if let Some(problem) = problem(&entry.path(), kind.is_dir()) {
            return Some(problem);
        }
    }
    None
}

/// Preflight for commands that open the state directory (the directory only;
/// entries are checked when the store actually refuses one, see `explain`).
pub fn preflight(state_dir: &Path) -> Result<(), CliError> {
    match problem(state_dir, true) {
        Some(message) => Err(CliError::Invalid(message)),
        None => Ok(()),
    }
}

/// Turn the store's generic local I/O refusal into the actionable cause when
/// one of the state directory's entries breaks the owner-only policy.
pub fn explain(state_dir: &Path, error: crate::error::Error) -> CliError {
    match (error, state_dir_problem(state_dir)) {
        (crate::error::Error::Io, Some(message)) => CliError::Invalid(message),
        (error, _) => error.into(),
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    fn set(path: &Path, mode: u32) {
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode)).unwrap();
    }
    #[test]
    fn shared_state_directory_and_files_name_the_path_and_chmod_fix() {
        let root = tempfile::tempdir().unwrap();
        let state = root.path().join("state dir");
        std::fs::create_dir(&state).unwrap();
        set(&state, 0o700);
        assert!(state_dir_problem(&state).is_none());
        set(&state, 0o775);
        let message = state_dir_problem(&state).unwrap();
        assert!(message.contains("state dir"), "{message}");
        assert!(message.contains("mode 775"), "{message}");
        assert!(message.contains("chmod 700 '"), "{message}");
        set(&state, 0o700);
        let file = state.join("credential-key");
        std::fs::write(&file, b"x").unwrap();
        set(&file, 0o644);
        let message = state_dir_problem(&state).unwrap();
        assert!(message.contains("credential-key") && message.contains("chmod 600"), "{message}");
        assert!(preflight(&state).is_ok());
        let explained = explain(&state, crate::error::Error::Io).to_string();
        assert!(explained.contains("credential-key"), "{explained}");
        set(&file, 0o600);
        assert!(matches!(explain(&state, crate::error::Error::Io), CliError::Client(_)));
        assert!(preflight(&root.path().join("missing")).is_ok());
    }
}
