//! Sandbox profile generation for both tiers (bubblewrap argv, Seatbelt SBPL) from fixed plans.
use super::command_sandbox::{
    ConfinementPlan, GitAccess, MaskedPath, SandboxTier, SystemPath, Unavailable, bwrap_argv,
    seatbelt_profile,
};
use std::ffi::OsString;
use std::path::PathBuf;

fn plan() -> ConfinementPlan {
    ConfinementPlan {
        root: PathBuf::from("/home/dev/.openmates/worktrees/src/chat"),
        cwd: PathBuf::from("/home/dev/.openmates/worktrees/src/chat/app"),
        git: GitAccess {
            read_only: vec![PathBuf::from("/home/dev/repo/.git")],
            writable: vec![
                PathBuf::from("/home/dev/repo/.git/worktrees/chat"),
                PathBuf::from("/home/dev/repo/.git/objects"),
                PathBuf::from("/home/dev/repo/.git/refs/openmates/chats"),
            ],
        },
        masked: vec![
            MaskedPath {
                path: PathBuf::from("/home/dev/.openmates/worktrees/src/chat/.env"),
                directory: false,
            },
            MaskedPath {
                path: PathBuf::from("/home/dev/.openmates/worktrees/src/chat/secrets"),
                directory: true,
            },
            MaskedPath {
                path: PathBuf::from("/home/dev/repo/.git/config"),
                directory: false,
            },
        ],
        system: vec![
            SystemPath {
                path: PathBuf::from("/usr"),
                link: None,
            },
            SystemPath {
                path: PathBuf::from("/bin"),
                link: Some(PathBuf::from("usr/bin")),
            },
        ],
        scratch: PathBuf::from("/private/var/folders/xy/openmates-command-1"),
    }
}

fn strings(args: &[OsString]) -> Vec<String> {
    args.iter()
        .map(|a| a.to_string_lossy().into_owned())
        .collect()
}

fn position(args: &[String], window: &[&str]) -> usize {
    args.windows(window.len())
        .position(|w| w.iter().zip(window).all(|(a, b)| a == b))
        .unwrap_or_else(|| panic!("missing {window:?} in {args:?}"))
}

// contract-test: supporting surface=cli assertions=code-run.remote.confinement,code-run.remote.resource-profiles
#[test]
fn bwrap_isolates_namespaces_and_never_shares_network() {
    let args = strings(&bwrap_argv(&plan(), &["cargo".into(), "test".into()]));
    for flag in [
        "--unshare-all",
        "--unshare-user",
        "--disable-userns",
        "--die-with-parent",
        "--new-session",
    ] {
        assert!(args.contains(&flag.to_owned()), "{flag}");
    }
    assert!(!args.iter().any(|a| a == "--share-net"));
    position(&args, &["--cap-drop", "ALL"]);
    // The command follows `--` verbatim, never through a shell.
    let tail = position(&args, &["--", "cargo", "test"]);
    assert_eq!(tail + 3, args.len());
}

// contract-test: supporting surface=cli assertions=code-run.remote.confinement
#[test]
fn bwrap_binds_system_read_only_and_only_the_root_read_write() {
    let args = strings(&bwrap_argv(&plan(), &["true".into()]));
    position(&args, &["--ro-bind", "/usr", "/usr"]);
    position(&args, &["--symlink", "usr/bin", "/bin"]);
    let root = "/home/dev/.openmates/worktrees/src/chat";
    position(&args, &["--bind", root, root]);
    position(&args, &["--tmpfs", "/tmp"]);
    position(
        &args,
        &["--chdir", "/home/dev/.openmates/worktrees/src/chat/app"],
    );
    // Nothing else of the home directory is mounted.
    let binds: Vec<&String> = args
        .windows(2)
        .filter(|w| w[0] == "--bind")
        .map(|w| &w[1])
        .collect();
    assert_eq!(binds.len(), 4, "root plus three Git admin paths: {binds:?}");
    assert!(
        binds
            .iter()
            .all(|b| b.starts_with(root) || b.starts_with("/home/dev/repo/.git/"))
    );
}

// contract-test: supporting surface=cli assertions=code-run.remote.confinement,code-run.remote.private-path-deny
#[test]
fn bwrap_masks_come_after_every_bind_that_could_expose_them() {
    let args = strings(&bwrap_argv(&plan(), &["true".into()]));
    let common = position(
        &args,
        &["--ro-bind", "/home/dev/repo/.git", "/home/dev/repo/.git"],
    );
    let objects = position(&args, &["--bind", "/home/dev/repo/.git/objects"]);
    let root_bind = position(
        &args,
        &["--bind", "/home/dev/.openmates/worktrees/src/chat"],
    );
    let env = position(
        &args,
        &[
            "--ro-bind",
            "/dev/null",
            "/home/dev/.openmates/worktrees/src/chat/.env",
        ],
    );
    let secrets = position(
        &args,
        &["--tmpfs", "/home/dev/.openmates/worktrees/src/chat/secrets"],
    );
    position(
        &args,
        &[
            "--remount-ro",
            "/home/dev/.openmates/worktrees/src/chat/secrets",
        ],
    );
    let config = position(
        &args,
        &["--ro-bind", "/dev/null", "/home/dev/repo/.git/config"],
    );
    assert!(common < objects);
    for mask in [env, secrets, config] {
        assert!(mask > root_bind && mask > objects && mask > common);
    }
}

// contract-test: supporting surface=cli assertions=code-run.remote.confinement,code-run.remote.private-path-deny,code-run.remote.resource-profiles
#[test]
fn seatbelt_profile_denies_by_default_and_masks_last() {
    let profile = seatbelt_profile(&plan()).expect("plain paths quote");
    assert!(profile.starts_with("(version 1)\n(deny default)\n"));
    assert!(profile.contains("(allow file-read* (subpath \"/usr\"))"));
    assert!(profile.contains(concat!(
        "(allow file-read* file-write* (subpath \"/home/dev/.openmates/worktrees/src/chat\") ",
        "(subpath \"/private/var/folders/xy/openmates-command-1\"))"
    )));
    assert!(profile.contains("(allow file-read* (subpath \"/home/dev/repo/.git\"))"));
    assert!(
        profile
            .contains("(allow file-read* file-write* (subpath \"/home/dev/repo/.git/objects\"))")
    );
    let env = profile
        .find("(deny file-read* file-write* (literal \"/home/dev/.openmates/worktrees/src/chat/.env\"))")
        .expect("env mask");
    let secrets = profile
        .find("(deny file-read* file-write* (subpath \"/home/dev/.openmates/worktrees/src/chat/secrets\"))")
        .expect("dir mask");
    let last_allow = profile.rfind("(allow ").expect("allows");
    assert!(
        env > last_allow && secrets > last_allow,
        "last matching rule wins"
    );
    assert!(profile.trim_end().ends_with("(deny network*)"));
    // No home-wide or root-wide read grant.
    assert!(!profile.contains("(subpath \"/\")"));
    assert!(!profile.contains("(subpath \"/home/dev\")"));
}

#[test]
fn seatbelt_profile_escapes_quotes_and_refuses_control_characters() {
    let mut quoted = plan();
    quoted.root = PathBuf::from("/Users/dev/My \"App\"\\x");
    let profile = seatbelt_profile(&quoted).expect("quotes escape");
    assert!(profile.contains("(subpath \"/Users/dev/My \\\"App\\\"\\\\x\")"));
    let mut broken = plan();
    broken.masked.push(MaskedPath {
        path: PathBuf::from("/Users/dev/a\nb"),
        directory: false,
    });
    assert!(seatbelt_profile(&broken).is_err());
}

#[test]
fn tier_and_refusal_codes_are_stable() {
    assert_eq!(SandboxTier::Bubblewrap.as_str(), "bubblewrap");
    assert_eq!(
        SandboxTier::BubblewrapAppArmor.as_str(),
        "bubblewrap_apparmor"
    );
    assert_eq!(SandboxTier::Seatbelt.as_str(), "seatbelt");
    assert_eq!(
        Unavailable::ConfinementUnavailable.code(),
        "confinement_unavailable"
    );
    assert_eq!(
        Unavailable::UnsupportedPlatform.code(),
        "unsupported_platform"
    );
}
