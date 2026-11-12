//! Sandbox tiers for confined source-host commands (plan
//! native-agentic-coding-readiness R9; shared core, native source host only).
//!
//! One interface, three tiers: rootless bubblewrap (Linux, unprivileged user
//! namespaces allowed), bubblewrap through the OpenMates AppArmor launcher
//! (`/usr/libexec/openmates-bwrap`, installed once by
//! `scripts/setup_remote_command_apparmor.py` where Ubuntu restricts user
//! namespaces) and Seatbelt (`sandbox-exec`, macOS, no sudo). No tier means
//! the command is refused; there is no unconfined tier. Profile generation is
//! pure so both platforms are testable anywhere.
//! spec: specifications/features/app-skills/code-run `code-run.remote.confinement`.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

/// The dedicated bubblewrap copy the AppArmor setup installs (npm
/// `REMOTE_COMMAND_BWRAP`); its profile grants `userns` and nothing else.
pub(crate) const APPARMOR_BWRAP: &str = "/usr/libexec/openmates-bwrap";
/// Distribution bubblewrap locations; never looked up through `PATH`, so a
/// user-writable directory cannot substitute the launcher.
const SYSTEM_BWRAP: [&str; 2] = ["/usr/bin/bwrap", "/usr/local/bin/bwrap"];
/// macOS Seatbelt launcher.
pub(crate) const SANDBOX_EXEC: &str = "/usr/bin/sandbox-exec";
/// `HOME` inside a bubblewrap sandbox (on its private `/tmp` tmpfs).
pub(crate) const BWRAP_HOME: &str = "/tmp/openmates-home";
const PROBE_TIMEOUT: Duration = Duration::from_secs(5);

/// Which confinement ran a command (reported in the result as `sandbox`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum SandboxTier {
    /// Distribution bubblewrap with unprivileged user namespaces.
    Bubblewrap,
    /// The OpenMates bubblewrap copy allowed user namespaces by AppArmor.
    BubblewrapAppArmor,
    /// macOS `sandbox-exec` with a generated profile.
    Seatbelt,
}

impl SandboxTier {
    /// Stable wire name.
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Bubblewrap => "bubblewrap",
            Self::BubblewrapAppArmor => "bubblewrap_apparmor",
            Self::Seatbelt => "seatbelt",
        }
    }
}

/// A usable sandbox launcher on this machine.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Sandbox {
    /// The tier the launcher provides.
    pub(crate) tier: SandboxTier,
    /// Absolute launcher path.
    pub(crate) executable: PathBuf,
}

/// Why no tier is available, as a stable requester code.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Unavailable {
    /// The OS has no supported confinement (anything but Linux and macOS).
    UnsupportedPlatform,
    /// A supported OS whose sandbox is missing or blocked (for example
    /// Ubuntu 24.04 user-namespace restrictions without the AppArmor setup).
    ConfinementUnavailable,
}

impl Unavailable {
    /// Stable error code for requesters.
    pub(crate) fn code(self) -> &'static str {
        match self {
            Self::UnsupportedPlatform => "unsupported_platform",
            Self::ConfinementUnavailable => "confinement_unavailable",
        }
    }
}

/// A read-only system location visible to the command. On Linux a symlink
/// (merged `/usr`: `/bin -> usr/bin`) is recreated as a symlink instead of
/// bound, so the sandbox layout matches the host.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct SystemPath {
    /// Absolute path.
    pub(crate) path: PathBuf,
    /// Symlink target when `path` is a symlink.
    pub(crate) link: Option<PathBuf>,
}

/// A path whose content the command must not see.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct MaskedPath {
    /// Absolute path inside a mounted area.
    pub(crate) path: PathBuf,
    /// Directory (hidden as an empty read-only tmpfs) or file (`/dev/null`).
    pub(crate) directory: bool,
}

/// Git admin locations a command in a chat worktree needs outside its root.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct GitAccess {
    /// Read-only: the repository's common Git directory (refs, packed refs, HEAD).
    pub(crate) read_only: Vec<PathBuf>,
    /// Read-write: the worktree's admin directory, the object store and
    /// `refs/openmates/chats/`, so the chat can commit to its hidden ref.
    pub(crate) writable: Vec<PathBuf>,
}

/// Everything a profile is generated from; all paths are canonical.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ConfinementPlan {
    /// The request root, the only general read-write area.
    pub(crate) root: PathBuf,
    /// Working directory (the root or a directory inside it).
    pub(crate) cwd: PathBuf,
    /// Git admin access for a worktree or a root inside a larger repository.
    pub(crate) git: GitAccess,
    /// Private paths, `.git/config` files and state hidden from the command.
    pub(crate) masked: Vec<MaskedPath>,
    /// Read-only system locations.
    pub(crate) system: Vec<SystemPath>,
    /// Host scratch directory for `HOME`/`TMPDIR` (Seatbelt only; bubblewrap
    /// uses a private tmpfs).
    pub(crate) scratch: PathBuf,
}

/// Bubblewrap arguments (after the launcher path) that run `argv` confined.
///
/// Layout: new user/PID/IPC/UTS/cgroup/network namespaces (no network, no
/// nested user namespaces, no capabilities, own session, dies with the host),
/// read-only system paths, private `/proc`, `/dev`, `/tmp`, the root
/// read-write at its real path (so Git's absolute worktree links resolve),
/// Git admin paths, then every mask last so no later mount re-exposes a
/// private path.
pub(crate) fn bwrap_argv(plan: &ConfinementPlan, argv: &[String]) -> Vec<OsString> {
    let mut args: Vec<OsString> = [
        "--unshare-all",
        "--unshare-user",
        "--disable-userns",
        "--assert-userns-disabled",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
    ]
    .iter()
    .map(OsString::from)
    .collect();
    let mut push = |items: &[&std::ffi::OsStr]| args.extend(items.iter().map(|i| i.to_os_string()));
    for system in &plan.system {
        match &system.link {
            Some(target) => push(&[
                "--symlink".as_ref(),
                target.as_os_str(),
                system.path.as_os_str(),
            ]),
            None => push(&[
                "--ro-bind".as_ref(),
                system.path.as_os_str(),
                system.path.as_os_str(),
            ]),
        }
    }
    push(&[
        "--proc".as_ref(),
        "/proc".as_ref(),
        "--dev".as_ref(),
        "/dev".as_ref(),
    ]);
    push(&[
        "--tmpfs".as_ref(),
        "/tmp".as_ref(),
        "--dir".as_ref(),
        BWRAP_HOME.as_ref(),
    ]);
    push(&[
        "--bind".as_ref(),
        plan.root.as_os_str(),
        plan.root.as_os_str(),
    ]);
    for path in &plan.git.read_only {
        push(&["--ro-bind".as_ref(), path.as_os_str(), path.as_os_str()]);
    }
    for path in &plan.git.writable {
        push(&["--bind".as_ref(), path.as_os_str(), path.as_os_str()]);
    }
    for mask in &plan.masked {
        if mask.directory {
            push(&["--tmpfs".as_ref(), mask.path.as_os_str()]);
            push(&["--remount-ro".as_ref(), mask.path.as_os_str()]);
        } else {
            push(&[
                "--ro-bind".as_ref(),
                "/dev/null".as_ref(),
                mask.path.as_os_str(),
            ]);
        }
    }
    push(&["--chdir".as_ref(), plan.cwd.as_os_str(), "--".as_ref()]);
    args.extend(argv.iter().map(OsString::from));
    args
}

/// A Seatbelt profile string is refused when a path cannot be quoted safely.
#[derive(Debug, PartialEq, Eq)]
pub(crate) struct UnquotablePath(pub(crate) PathBuf);

fn sbpl_string(path: &Path) -> Result<String, UnquotablePath> {
    let Some(text) = path.to_str() else {
        return Err(UnquotablePath(path.to_path_buf()));
    };
    if text.chars().any(|c| c.is_control()) {
        return Err(UnquotablePath(path.to_path_buf()));
    }
    Ok(format!(
        "\"{}\"",
        text.replace('\\', "\\\\").replace('"', "\\\"")
    ))
}

/// Seatbelt (SBPL) profile with the same rules as [`bwrap_argv`]: deny by
/// default, read-only system paths, read-write root and scratch, the Git
/// admin paths, no network. Masks come last because the last matching
/// Seatbelt rule wins. File metadata stays readable (path resolution and
/// `getcwd` need it); the spec allows private names to stay visible.
///
/// # Errors
/// [`UnquotablePath`] for a non-UTF-8 path or one with control characters.
pub(crate) fn seatbelt_profile(plan: &ConfinementPlan) -> Result<String, UnquotablePath> {
    let mut out = String::from(concat!(
        "(version 1)\n(deny default)\n(allow process-fork)\n(allow process-exec)\n",
        "(allow signal (target same-sandbox))\n(allow sysctl-read)\n(allow file-read-metadata)\n",
        "(allow mach-lookup (global-name \"com.apple.system.opendirectoryd.libinfo\") ",
        "(global-name \"com.apple.system.notification_center\") ",
        "(global-name \"com.apple.system.logger\"))\n",
        "(allow file-read* (literal \"/dev/urandom\") (literal \"/dev/random\") (literal \"/dev/zero\"))\n",
        "(allow file-read* file-write-data (literal \"/dev/null\"))\n",
    ));
    for system in &plan.system {
        out.push_str(&format!(
            "(allow file-read* (subpath {}))\n",
            sbpl_string(&system.path)?
        ));
    }
    out.push_str(&format!(
        "(allow file-read* file-write* (subpath {}) (subpath {}))\n",
        sbpl_string(&plan.root)?,
        sbpl_string(&plan.scratch)?
    ));
    for path in &plan.git.read_only {
        out.push_str(&format!(
            "(allow file-read* (subpath {}))\n",
            sbpl_string(path)?
        ));
    }
    for path in &plan.git.writable {
        out.push_str(&format!(
            "(allow file-read* file-write* (subpath {}))\n",
            sbpl_string(path)?
        ));
    }
    for mask in &plan.masked {
        let filter = if mask.directory { "subpath" } else { "literal" };
        out.push_str(&format!(
            "(deny file-read* file-write* ({filter} {}))\n",
            sbpl_string(&mask.path)?
        ));
    }
    out.push_str("(deny network*)\n");
    Ok(out)
}

/// Linux system paths bound read-only (the existing ones, with their links).
/// `/home`, `/root`, `/var`, `/opt`, `/srv`, `/mnt` and `/run` stay unmounted.
pub(crate) fn linux_system_paths() -> Vec<SystemPath> {
    existing_system_paths(&[
        "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32", "/etc",
    ])
}

/// macOS system paths readable by the command.
pub(crate) fn macos_system_paths() -> Vec<SystemPath> {
    existing_system_paths(&[
        "/usr",
        "/bin",
        "/sbin",
        "/System",
        "/Library/Developer/CommandLineTools",
        "/Applications/Xcode.app",
        "/private/etc",
        "/private/var/db/timezone",
        "/opt/homebrew",
    ])
}

fn existing_system_paths(candidates: &[&str]) -> Vec<SystemPath> {
    candidates
        .iter()
        .map(Path::new)
        .filter_map(|path| {
            let metadata = std::fs::symlink_metadata(path).ok()?;
            let link = if metadata.file_type().is_symlink() {
                Some(std::fs::read_link(path).ok()?)
            } else {
                None
            };
            Some(SystemPath {
                path: path.to_path_buf(),
                link,
            })
        })
        .collect()
}

/// The best working tier on this machine, probed on every call so a setup
/// completed while the host runs takes effect without a restart.
///
/// # Errors
/// [`Unavailable`] when no tier works; the caller refuses the command.
pub(crate) fn detect() -> Result<Sandbox, Unavailable> {
    if cfg!(target_os = "macos") {
        let executable = PathBuf::from(SANDBOX_EXEC);
        let mut probe = Command::new(&executable);
        probe.args(["-p", "(version 1)(allow default)", "/usr/bin/true"]);
        return if trusted_launcher(&executable) && probe_ok(probe) {
            Ok(Sandbox {
                tier: SandboxTier::Seatbelt,
                executable,
            })
        } else {
            Err(Unavailable::ConfinementUnavailable)
        };
    }
    if !cfg!(target_os = "linux") {
        return Err(Unavailable::UnsupportedPlatform);
    }
    let candidates = std::iter::once((APPARMOR_BWRAP, SandboxTier::BubblewrapAppArmor))
        .chain(SYSTEM_BWRAP.iter().map(|p| (*p, SandboxTier::Bubblewrap)));
    for (path, tier) in candidates {
        let executable = PathBuf::from(path);
        if !trusted_launcher(&executable) {
            continue;
        }
        let mut probe = Command::new(&executable);
        probe.args(bwrap_probe_args());
        if probe_ok(probe) {
            return Ok(Sandbox { tier, executable });
        }
    }
    Err(Unavailable::ConfinementUnavailable)
}

/// The probe uses the same namespace flags as real runs, so a kernel that
/// allows user namespaces but not network setup (Ubuntu's restricted
/// unprivileged profile) is reported as unavailable instead of failing later.
fn bwrap_probe_args() -> Vec<&'static str> {
    vec![
        "--unshare-all",
        "--unshare-user",
        "--disable-userns",
        "--assert-userns-disabled",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--",
        "/bin/true",
    ]
}

/// A launcher must be a root-owned regular file that only root can modify.
fn trusted_launcher(path: &Path) -> bool {
    use std::os::unix::fs::MetadataExt;
    std::fs::symlink_metadata(path)
        .is_ok_and(|m| m.file_type().is_file() && m.uid() == 0 && m.mode() & 0o022 == 0)
}

fn probe_ok(mut probe: Command) -> bool {
    probe.env_clear().env("PATH", "/usr/bin:/bin");
    super::command_process::run_bounded(probe, PROBE_TIMEOUT, 4096)
        .is_ok_and(|outcome| !outcome.timed_out && outcome.exit_code == Some(0))
}
