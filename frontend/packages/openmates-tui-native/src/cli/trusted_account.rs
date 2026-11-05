//! Installed-CLI account protection. This policy is application-owned; the
//! headless SDK never discovers profiles, environment variables or trust files.
use super::{CliError, GlobalArgs, Invocation};
use serde_json::{Value, json};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::Path,
};
const PROFILE: &str = "codex-personal";
const API: &str = "https://api.dev.openmates.org";
const FILE: &str = "trusted_account.json";
#[derive(Default)]
pub struct Environment {
    pub account_guard: Option<String>,
    pub require_trusted_account: Option<String>,
    pub profile: Option<String>,
    pub state_dir: Option<String>,
    pub api_url: Option<String>,
}
impl Environment {
    pub fn capture() -> Self {
        let read = |name| std::env::var(name).ok();
        Self {
            account_guard: read("OPENMATES_ACCOUNT_GUARD"),
            require_trusted_account: read("OPENMATES_REQUIRE_TRUSTED_ACCOUNT"),
            profile: read("OPENMATES_PROFILE"),
            state_dir: read("OPENMATES_STATE_DIR"),
            api_url: read("OPENMATES_API_URL"),
        }
    }
}
pub struct Policy {
    pub enabled: bool,
    pub protected: bool,
}
fn invalid(message: &str) -> CliError {
    CliError::Invalid(message.into())
}
fn protected(command: Option<&str>) -> bool {
    !matches!(
        command,
        Some(
            "login"
                | "logout"
                | "whoami"
                | "help"
                | "version"
                | "server"
                | "docs"
                | "support"
                | "update"
                | "upgrade"
        )
    )
}
/// Call before credential discovery. Help is parsed locally and exits before
/// this policy; unknown migration commands must not bypass command blocking.
pub fn check_environment(
    globals: &GlobalArgs,
    invocation: Option<&Invocation>,
    environment: &Environment,
) -> Result<Policy, CliError> {
    let alias = environment
        .require_trusted_account
        .as_deref()
        .is_some_and(|value| {
            !value.is_empty()
                && !matches!(value.to_ascii_lowercase().as_str(), "0" | "false" | "off")
        });
    let enabled = environment.account_guard.as_deref() == Some("required") || alias;
    let command = invocation.and_then(|invocation| invocation.path.first().map(String::as_str));
    let policy = Policy {
        enabled,
        protected: enabled && protected(command),
    };
    if !enabled {
        return Ok(policy);
    }
    if globals
        .profile
        .as_deref()
        .is_some_and(|value| value != PROFILE)
    {
        return Err(invalid(
            "Trusted Codex CLI commands cannot override profile codex-personal.",
        ));
    }
    if environment.profile.as_deref() != Some(PROFILE) {
        return Err(invalid(
            "Trusted Codex CLI commands require OPENMATES_PROFILE=codex-personal.",
        ));
    }
    if environment
        .state_dir
        .as_ref()
        .is_some_and(|value| !value.is_empty())
        || globals.state_dir.is_some()
    {
        return Err(invalid(
            "Trusted Codex CLI commands cannot override the native state directory.",
        ));
    }
    if environment
        .api_url
        .as_deref()
        .map(|url| url.trim_end_matches('/'))
        != Some(API)
    {
        return Err(invalid(
            "Trusted Codex CLI commands require https://api.dev.openmates.org.",
        ));
    }
    if globals
        .api_url
        .as_deref()
        .is_some_and(|url| url.trim_end_matches('/') != API)
    {
        return Err(invalid(
            "Trusted Codex CLI commands cannot override the configured dev API URL.",
        ));
    }
    if matches!(command, Some("signup" | "e2e")) {
        return Err(invalid(
            "Signup and E2E commands are disabled for the trusted Codex CLI profile.",
        ));
    }
    Ok(policy)
}
fn account(value: &str) -> Result<&str, CliError> {
    let value = value.trim();
    if value.is_empty() || value.len() > 256 || value.chars().any(char::is_control) {
        return Err(invalid(
            "OpenMates account verification returned no valid account ID.",
        ));
    }
    Ok(value)
}
pub fn verify(expected: Option<&str>, user: &Value) -> Result<(), CliError> {
    let expected=expected.ok_or_else(||invalid("This native CLI profile is not trusted yet. Run openmates login and approve the intended account."))?;
    let actual = account(user["id"].as_str().unwrap_or(""))?;
    if account(expected)? != actual {
        return Err(invalid(
            "OpenMates account mismatch: refusing authenticated access from this CLI profile.",
        ));
    }
    Ok(())
}
fn directory(path: &Path) -> Result<(), CliError> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|_| invalid("The native trusted-account directory is unavailable."))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(super::private_path::problem(path, true).map(CliError::Invalid).unwrap_or_else(|| invalid(
            "The trusted-account directory must be a real private directory.",
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.uid() != rustix::process::geteuid().as_raw() || metadata.mode() & 0o077 != 0 {
            return Err(super::private_path::problem(path, true).map(CliError::Invalid).unwrap_or_else(|| invalid(
                "The trusted-account directory must be owned by the current user and private.",
            )));
        }
    }
    Ok(())
}
/// Read the native marker only. The caller explicitly owns any one-time
/// migration of trusted account metadata; rotating legacy sessions are never read.
pub fn load(path: &Path) -> Result<Option<String>, CliError> {
    match fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(invalid("The trusted-account directory is unavailable.")),
        Ok(_) => directory(path)?,
    }
    let target = path.join(FILE);
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(
            (rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32,
        );
    }
    let file = match options.open(&target) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => {
            return Err(invalid(
                "The trusted-account marker could not be read safely.",
            ));
        }
        Ok(file) => file,
    };
    let metadata = file
        .metadata()
        .map_err(|_| invalid("The trusted-account marker is unavailable."))?;
    if !metadata.is_file() || metadata.len() > 4096 {
        return Err(invalid("The trusted-account marker is invalid."));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.uid() != rustix::process::geteuid().as_raw() || metadata.mode() & 0o077 != 0 {
            return Err(super::private_path::problem(&target, false).map(CliError::Invalid).unwrap_or_else(|| invalid(
                "The trusted-account marker must be owned by the current user and private.",
            )));
        }
    }
    let mut bytes = vec![];
    file.take(4097)
        .read_to_end(&mut bytes)
        .map_err(|_| invalid("The trusted-account marker could not be read."))?;
    if bytes.len() > 4096 {
        return Err(invalid("The trusted-account marker is invalid."));
    }
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|_| invalid("The trusted-account marker is malformed; it was preserved."))?;
    let id = account(value["accountId"].as_str().unwrap_or(""))?;
    Ok(Some(id.to_owned()))
}
/// A previously pinned profile keeps its account boundary even when the shell
/// does not set the optional Codex guard. SDK consumers never use this policy.
pub fn enforced_profile(
    path: &Path,
    required: bool,
) -> Result<Option<std::path::PathBuf>, CliError> {
    let pinned = load(path)?.is_some();
    Ok((required || pinned).then(|| path.to_path_buf()))
}
/// Call only after the login/pairing UI explicitly approved the intended account.
/// An existing marker can never silently be reassigned to another identity.
pub fn save(path: &Path, account_id: &str) -> Result<(), CliError> {
    directory(path)?;
    let account_id = account(account_id)?;
    if let Some(expected) = load(path)? {
        if expected != account_id {
            return Err(invalid(
                "This native CLI profile is already trusted for another account.",
            ));
        }
        return Ok(());
    }
    let temporary = path.join(format!(".trusted-account-{}.tmp", uuid::Uuid::new_v4()));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32);
    }
    let publish = || -> Result<(), CliError> {
        let mut file = options
            .open(&temporary)
            .map_err(|_| invalid("The trusted-account marker could not be prepared."))?;
        let bytes = serde_json::to_vec(&json!({"accountId":account_id}))
            .map_err(|_| invalid("The trusted-account marker could not be encoded."))?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| invalid("The trusted-account marker could not be persisted."))?;
        fs::rename(&temporary, path.join(FILE))
            .map_err(|_| invalid("The trusted-account marker could not be published."))?;
        #[cfg(unix)]
        {
            File::open(path)
                .and_then(|directory| directory.sync_all())
                .map_err(|_| {
                    invalid("The trusted-account marker directory could not be synchronized.")
                })?;
        }
        Ok(())
    };
    let result = publish();
    let _ = fs::remove_file(&temporary);
    result
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    fn globals() -> GlobalArgs {
        GlobalArgs {
            demo: false,
            api_url: None,
            state_dir: None,
            encrypted_vault: false,
            profile: None,
            json: false,
            api_key: None,
        }
    }
    fn invocation(root: &str) -> Invocation {
        Invocation {
            path: vec![root.into()],
            positionals: vec![],
            flags: BTreeMap::new(),
        }
    }
    fn environment() -> Environment {
        Environment {
            account_guard: Some("required".into()),
            profile: Some(PROFILE.into()),
            api_url: Some(format!("{API}/")),
            ..Default::default()
        }
    }
    #[test]
    fn protected_commands_cannot_override_profile_state_or_api_or_run_signup() {
        let globals = globals();
        let env = environment();
        assert!(
            check_environment(&globals, Some(&invocation("tasks")), &env)
                .ok()
                .unwrap()
                .protected
        );
        assert!(
            !check_environment(&globals, Some(&invocation("login")), &env)
                .ok()
                .unwrap()
                .protected
        );
        assert!(check_environment(&globals, Some(&invocation("signup")), &env).is_err());
        let mut changed = environment();
        changed.profile = Some("test-account".into());
        assert!(check_environment(&globals, Some(&invocation("tasks")), &changed).is_err());
        let mut changed = environment();
        changed.state_dir = Some("/tmp/test-account".into());
        assert!(check_environment(&globals, Some(&invocation("tasks")), &changed).is_err());
        let mut changed = environment();
        changed.api_url = Some("https://api.example.com".into());
        assert!(check_environment(&globals, Some(&invocation("tasks")), &changed).is_err());
    }
    #[test]
    fn alias_cannot_silently_disable_guard_and_no_account_data_appears_in_errors() {
        let mut env = environment();
        env.account_guard = None;
        env.require_trusted_account = Some("required".into());
        assert!(
            check_environment(&globals(), None, &env)
                .ok()
                .unwrap()
                .protected
        );
        let error = verify(
            Some("expected-account"),
            &json!({"id":"private-wrong-account"}),
        )
        .err()
        .unwrap();
        assert!(!error.to_string().contains("private-wrong-account"));
        assert!(verify(None, &json!({"id":"account"})).is_err());
    }
    #[test]
    fn trusted_marker_is_private_and_cannot_be_rebound() {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(fs::Permissions::from_mode(0o700));
        }
        let directory = builder.tempdir().unwrap();
        assert!(
            enforced_profile(directory.path(), false)
                .ok()
                .unwrap()
                .is_none()
        );
        assert_eq!(
            enforced_profile(directory.path(), true)
                .ok()
                .unwrap()
                .as_deref(),
            Some(directory.path())
        );
        save(directory.path(), "account-one").ok().unwrap();
        // A later ordinary shell invocation must not disable an already pinned
        // profile merely because it omits the optional Codex environment guard.
        assert_eq!(
            enforced_profile(directory.path(), false)
                .ok()
                .unwrap()
                .as_deref(),
            Some(directory.path())
        );
        assert_eq!(
            load(directory.path()).ok().unwrap().as_deref(),
            Some("account-one")
        );
        assert!(save(directory.path(), "account-two").is_err());
        assert!(
            verify(
                load(directory.path()).ok().unwrap().as_deref(),
                &json!({"id":"account-one"})
            )
            .is_ok()
        );
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(directory.path().join(FILE))
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o600
            );
        }
    }
    #[cfg(unix)]
    #[test]
    fn guard_rejects_symlink_marker() {
        use std::os::unix::fs::{PermissionsExt, symlink};
        let mut builder = tempfile::Builder::new();
        builder.permissions(fs::Permissions::from_mode(0o700));
        let directory = builder.tempdir().unwrap();
        let target = directory.path().join("target");
        fs::write(&target, b"{}").unwrap();
        symlink(&target, directory.path().join(FILE)).unwrap();
        assert!(load(directory.path()).is_err());
        assert!(enforced_profile(directory.path(), false).is_err());
    }
}
