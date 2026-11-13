//! Host command-protection capability (npm `inspectRemoteCommandCapability`,
//! `ensureRemoteCommandSetup`). Presets may only be enabled where the OS
//! boundary (OpenMates bubblewrap launcher plus the AppArmor broker) is
//! installed. The privileged installer is never started from here: its
//! files are not bundled into this binary and handing root a user-writable
//! copy would be unsafe, so an unsupported host fails with the npm
//! "setup required" error and the manual installer command.
use super::super::CliError;
use std::path::Path;

fn contract(code: &'static str, message: &str) -> CliError {
    CliError::Contract {
        code,
        message: message.into(),
    }
}

const BWRAP: &str = "/usr/libexec/openmates-bwrap";
const BROKER: &str = "/usr/libexec/openmates-command-apparmor";
const AA_EXEC: &str = "/usr/bin/aa-exec";
const GIT_MASK: &str = "/usr/libexec/openmates-git-config-mask.so";
const SUDO: &str = "/usr/bin/sudo";
const PROBE_PATH: &str = "/usr/local/bin:/usr/bin:/bin";

/// npm `assertTrustedRootExecutable`.
fn trusted_root_executable(path: &str, label: &str) -> Result<(), String> {
    use std::os::unix::fs::MetadataExt;
    let link = std::fs::symlink_metadata(path).map_err(|e| format!("{label}: {e}"))?;
    if link.file_type().is_symlink() {
        return Err(format!("{label} must not be a symbolic link: {path}"));
    }
    let stat = std::fs::metadata(path).map_err(|e| format!("{label}: {e}"))?;
    if !stat.is_file() || stat.uid() != 0 || stat.mode() & 0o022 != 0 || stat.mode() & 0o111 == 0 {
        return Err(format!(
            "{label} is not a trusted root-owned executable: {path}"
        ));
    }
    Ok(())
}

fn apparmor_capability() -> Result<(), String> {
    let enabled = std::fs::read_to_string("/sys/module/apparmor/parameters/enabled")
        .map_err(|e| format!("AppArmor command confinement is unavailable: {e}"))?;
    if enabled.trim() != "Y" {
        return Err("AppArmor is not enabled".into());
    }
    trusted_root_executable(AA_EXEC, "aa-exec")?;
    trusted_root_executable(BROKER, "AppArmor broker")?;
    trusted_root_executable(BWRAP, "OpenMates bubblewrap launcher")?;
    trusted_root_executable(GIT_MASK, "Git config compatibility library")?;
    trusted_root_executable(SUDO, "sudo")
}

/// `Ok(())` when the OS-enforced boundary works; else the npm reason text.
pub(super) fn inspect() -> Result<(), String> {
    if !cfg!(target_os = "linux") {
        return Err(format!(
            "OS-enforced command confinement is not implemented for {}",
            std::env::consts::OS
        ));
    }
    if !Path::new(BWRAP).exists() {
        return Err(format!(
            "OpenMates bubblewrap launcher is not installed at {BWRAP}"
        ));
    }
    apparmor_capability()?;
    let mut child = std::process::Command::new(BWRAP)
        .args([
            "--unshare-user",
            "--unshare-pid",
            "--unshare-net",
            "--disable-userns",
            "--assert-userns-disabled",
            "--ro-bind",
            "/",
            "/",
            "--",
            "/bin/true",
        ])
        .env_clear()
        .env("PATH", PROBE_PATH)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| format!("bubblewrap cannot enforce confinement: {e}"))?;
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    loop {
        match child.try_wait() {
            Ok(Some(status)) if status.success() => return Ok(()),
            Ok(Some(_)) => {
                let mut detail = String::new();
                if let Some(stderr) = child.stderr.take() {
                    use std::io::Read;
                    let _ = stderr.take(4096).read_to_string(&mut detail);
                }
                let detail = detail.trim();
                return Err(format!(
                    "bubblewrap cannot enforce confinement: {}",
                    if detail.is_empty() {
                        "kernel rejected the sandbox probe"
                    } else {
                        detail
                    }
                ));
            }
            Ok(None) if std::time::Instant::now() >= deadline => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(
                    "bubblewrap cannot enforce confinement: kernel rejected the sandbox probe"
                        .into(),
                );
            }
            Ok(None) => std::thread::sleep(std::time::Duration::from_millis(20)),
            Err(e) => return Err(format!("bubblewrap cannot enforce confinement: {e}")),
        }
    }
}

/// npm `ensureRemoteCommandSetup` without the privileged installer.
pub(super) fn ensure(inspect_result: Result<(), String>) -> Result<(), CliError> {
    let Err(reason) = inspect_result else {
        return Ok(());
    };
    Err(contract(
        "remote_command_setup_required",
        &format!(
            "Remote command protection needs one-time interactive operating-system setup ({reason}). Run the packaged installer manually (sudo -- /usr/bin/python3 scripts/setup_remote_command_apparmor.py --user <your-user>) and rerun this command; the native CLI does not start the privileged installer."
        ),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unsupported_hosts_fail_with_the_setup_required_contract_code() {
        assert!(ensure(Ok(())).is_ok());
        let error = ensure(Err("AppArmor is not enabled".into())).err().unwrap();
        assert_eq!(error.code(), "remote_command_setup_required");
        assert!(error.to_string().contains("(AppArmor is not enabled)"));
    }

    #[test]
    fn untrusted_executables_are_rejected() {
        let directory = tempfile::tempdir().unwrap();
        let file = directory.path().join("tool");
        std::fs::write(&file, "#!/bin/sh\n").unwrap();
        let reason = trusted_root_executable(file.to_str().unwrap(), "tool")
            .err()
            .unwrap();
        assert!(
            reason.contains("not a trusted root-owned executable"),
            "{reason}"
        );
        let link = directory.path().join("link");
        std::os::unix::fs::symlink(&file, &link).unwrap();
        let reason = trusted_root_executable(link.to_str().unwrap(), "tool")
            .err()
            .unwrap();
        assert!(reason.contains("must not be a symbolic link"), "{reason}");
        assert!(trusted_root_executable("/nonexistent/openmates", "tool").is_err());
    }
}
