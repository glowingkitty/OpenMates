//! `run_command`: proposal validation and digest, process bounds, confinement plans, and real bubblewrap runs when the host allows them.
use super::command_process::run_bounded;
use super::command_sandbox::{BWRAP_HOME, MaskedPath, Sandbox, SandboxTier, detect};
use super::command_scope::{PlanInputs, plan};
use super::commands::{
    CommandProposal, DEFAULT_OUTPUT_BYTES, digest, launch_command, run, validate,
};
use super::reads::HostRoot;
use super::worktrees::WorktreeArea;
use hmac::{Hmac, Mac};
use serde_json::{Value, json};
use sha2::Sha256;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

const KEY: [u8; 32] = [7; 32];
const CHAT: &str = "0b7e2c1a-4f4e-4b8e-9a51-2f7d0d3c9e11";

fn proposal(argv: &[&str], timeout_ms: u64) -> CommandProposal {
    validate(&json!({"operation_id": "op-1", "argv": argv, "timeout_ms": timeout_ms}))
        .expect("valid proposal")
}

struct Fixture {
    _root: tempfile::TempDir,
    _state: tempfile::TempDir,
    _outside: tempfile::TempDir,
    root: PathBuf,
    state: PathBuf,
    outside: PathBuf,
}

impl Fixture {
    fn host(&self) -> HostRoot {
        HostRoot {
            root: self.root.clone(),
            state_dir: self.state.clone(),
            policy_source: None,
        }
    }
}

fn fixture() -> Fixture {
    let root = tempfile::tempdir().expect("tempdir");
    let state = tempfile::tempdir().expect("tempdir");
    let outside = tempfile::tempdir().expect("tempdir");
    let canonical = |d: &tempfile::TempDir| fs::canonicalize(d.path()).expect("canonical");
    let fixture = Fixture {
        root: canonical(&root),
        state: canonical(&state),
        outside: canonical(&outside),
        _root: root,
        _state: state,
        _outside: outside,
    };
    fs::write(fixture.root.join("hello.txt"), "visible project file\n").expect("write");
    fs::write(fixture.root.join(".env"), "API_TOKEN=do-not-leak\n").expect("write");
    fs::create_dir(fixture.root.join(".ssh")).expect("mkdir");
    fs::write(fixture.root.join(".ssh/id_ed25519"), "private key bytes\n").expect("write");
    fs::write(fixture.outside.join("outside.txt"), "outside secret\n").expect("write");
    fixture
}

fn git(dir: &Path, args: &[&str]) {
    let out = Command::new("git")
        .args(["-c", "user.name=Test", "-c", "user.email=test@example.org"])
        .args(["-c", "commit.gpgsign=false", "-C"])
        .arg(dir)
        .args(args)
        .output()
        .expect("git runs");
    assert!(
        out.status.success(),
        "git {args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
}

// --- proposal --------------------------------------------------------------

// contract-test: supporting surface=cli assertions=code-run.remote.explicit-approval
#[test]
fn validates_an_argv_proposal_and_refuses_shell_strings_and_unknown_fields() {
    let ok = proposal(&["cargo", "test", "--", "--nocapture"], 1000);
    assert_eq!(ok.cwd, ".");
    assert_eq!(ok.max_output_bytes, None);
    for bad in [
        json!({"operation_id": "op", "argv": "cargo test", "timeout_ms": 1000}),
        json!({"operation_id": "op", "argv": [], "timeout_ms": 1000}),
        json!({"operation_id": "op", "argv": [""], "timeout_ms": 1000}),
        json!({"operation_id": "op", "argv": ["-x"], "timeout_ms": 1000}),
        json!({"operation_id": "op", "argv": ["a\u{0}b"], "timeout_ms": 1000}),
        json!({"operation_id": "op", "argv": ["ls"], "timeout_ms": 10}),
        json!({"operation_id": "op", "argv": ["ls"], "timeout_ms": 1000, "cwd": "../x"}),
        json!({"operation_id": "op", "argv": ["ls"], "timeout_ms": 1000, "cwd": "/etc"}),
        json!({"operation_id": "op", "argv": ["ls"], "timeout_ms": 1000, "network": true}),
        json!({"operation_id": "op", "argv": ["ls"], "timeout_ms": 1000, "env": {"A": "1"}}),
        json!({"operation_id": "op", "argv": ["ls"], "timeout_ms": 1000, "max_output_bytes": 1}),
        json!({"operation_id": "bad id", "argv": ["ls"], "timeout_ms": 1000}),
    ] {
        let error = validate(&bad).expect_err(&bad.to_string());
        assert_eq!(error.code, "invalid_request", "{bad}");
    }
}

// contract-test: supporting surface=cli assertions=code-run.remote.explicit-approval
#[test]
fn digest_is_the_keyed_hmac_of_the_exact_proposal() {
    let p = proposal(&["npm", "test"], 5000);
    let message = json!([
        "openmates-remote-command-proposal-v1",
        "project-1",
        CHAT,
        "run_command",
        "op-1",
        ["npm", "test"],
        ".",
        5000,
        Value::Null,
    ])
    .to_string();
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(&KEY).expect("key");
    mac.update(message.as_bytes());
    let expected: String = mac
        .finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    assert_eq!(
        digest(&KEY, "project-1", CHAT, &p).expect("digest"),
        expected
    );
    let changed = proposal(&["npm", "test", "--watch"], 5000);
    assert_ne!(
        digest(&KEY, "project-1", CHAT, &changed).expect("digest"),
        expected
    );
    assert!(digest(&KEY, "", CHAT, &p).is_err());
}

// --- process bounds (unconfined /bin/sh, so they run on every host) -------

// contract-test: supporting surface=cli assertions=code-run.remote.managed-jobs
#[test]
fn output_beyond_the_cap_is_truncated_with_a_marker() {
    let mut command = Command::new("/bin/sh");
    command.args(["-c", "head -c 50000 /dev/zero | tr '\\000' a; echo err >&2"]);
    let outcome = run_bounded(command, Duration::from_secs(20), 1024).expect("runs");
    assert_eq!(outcome.exit_code, Some(0));
    assert_eq!(outcome.stdout.bytes.len(), 1024);
    assert_eq!(outcome.stdout.total, 50_000);
    assert!(outcome.stdout.truncated());
    assert!(
        outcome
            .stdout
            .text()
            .ends_with("[openmates: output truncated, 48976 more bytes]")
    );
    assert_eq!(outcome.stderr.text(), "err\n");
    assert!(!outcome.timed_out);
}

// contract-test: supporting surface=cli assertions=code-run.remote.managed-jobs
#[test]
fn timeout_kills_the_whole_process_group() {
    let mut command = Command::new("/bin/sh");
    command.args(["-c", "sleep 30 & echo $!; wait"]);
    let outcome = run_bounded(command, Duration::from_millis(300), 4096).expect("runs");
    assert!(outcome.timed_out);
    assert_eq!(outcome.exit_code, None);
    assert_eq!(outcome.signal, Some(9));
    assert!(outcome.duration < Duration::from_secs(10));
    let child: u32 = outcome
        .stdout
        .text()
        .trim()
        .parse()
        .expect("background pid");
    // Gone, or a zombie waiting for its new parent to reap it. SIGKILL is
    // delivered asynchronously: on a loaded host the descendant can still read
    // as sleeping for a moment after `run_bounded` returned, so allow it a
    // bounded few seconds (far below its own 30 s sleep) to finish dying.
    let running = || {
        fs::read_to_string(format!("/proc/{child}/stat"))
            .ok()
            .as_deref()
            .and_then(|stat| stat.rsplit_once(") "))
            .is_some_and(|(_, rest)| !rest.starts_with('Z'))
    };
    let settle = std::time::Instant::now() + Duration::from_secs(5);
    while running() && std::time::Instant::now() < settle {
        std::thread::sleep(Duration::from_millis(20));
    }
    let running = running();
    if cfg!(target_os = "linux") {
        assert!(
            !running,
            "background descendant {child} survived the timeout"
        );
    }
}

#[test]
fn exit_codes_are_reported() {
    let mut command = Command::new("/bin/sh");
    command.args(["-c", "exit 3"]);
    let outcome = run_bounded(command, Duration::from_secs(10), 1024).expect("runs");
    assert_eq!(
        (outcome.exit_code, outcome.signal, outcome.timed_out),
        (Some(3), None, false)
    );
}

// --- confinement plan -----------------------------------------------------

// contract-test: supporting surface=cli assertions=code-run.remote.private-path-deny
#[test]
fn plan_masks_private_paths_hard_link_aliases_and_git_config() {
    let f = fixture();
    git(&f.root, &["init", "-q", "-b", "dev"]);
    fs::hard_link(f.root.join(".env"), f.root.join("innocent.txt")).expect("link");
    let built = plan(
        &f.host(),
        PlanInputs {
            root: &f.root,
            cwd: &f.root,
            worktree: false,
            system: Vec::new(),
            scratch: PathBuf::from(BWRAP_HOME),
        },
    )
    .expect("plan");
    let has =
        |path: PathBuf, directory: bool| built.masked.contains(&MaskedPath { path, directory });
    assert!(has(f.root.join(".env"), false));
    assert!(has(f.root.join("innocent.txt"), false), "hard-link alias");
    assert!(has(f.root.join(".ssh"), true));
    assert!(has(f.root.join(".git/config"), false));
    assert!(
        !built
            .masked
            .iter()
            .any(|m| m.path == f.root.join("hello.txt"))
    );
    assert!(
        !built
            .masked
            .iter()
            .any(|m| m.path == f.root.join(".ssh/id_ed25519")),
        "covered by the directory mask"
    );
    assert!(
        built.git.read_only.is_empty() && built.git.writable.is_empty(),
        "the Git dir is inside the root"
    );
}

// contract-test: supporting surface=cli assertions=code-run.remote.confinement,projects.sources.chat-worktrees
#[test]
fn worktree_plan_grants_only_the_git_admin_paths_a_commit_needs() {
    let f = fixture();
    git(&f.root, &["init", "-q", "-b", "dev"]);
    git(&f.root, &["add", "hello.txt"]);
    git(&f.root, &["commit", "-q", "-m", "initial"]);
    let worktree = WorktreeArea::new(&f.state)
        .ensure(&f.root, "src_alpha", CHAT, None, 0)
        .expect("ensure")
        .expect("git source");
    let host = HostRoot {
        root: worktree.root.clone(),
        state_dir: f.state.clone(),
        policy_source: Some(f.root.clone()),
    };
    let root = host.canonical().expect("canonical");
    let built = plan(
        &host,
        PlanInputs {
            root: &root,
            cwd: &root,
            worktree: true,
            system: Vec::new(),
            scratch: PathBuf::from(BWRAP_HOME),
        },
    )
    .expect("plan");
    let common = f.root.join(".git");
    assert_eq!(built.git.read_only, vec![common.clone()]);
    assert!(
        built
            .git
            .writable
            .contains(&common.join("worktrees").join(CHAT))
    );
    assert!(built.git.writable.contains(&common.join("objects")));
    assert!(
        built
            .git
            .writable
            .contains(&common.join("refs/openmates/chats"))
    );
    assert!(
        !built
            .git
            .writable
            .iter()
            .any(|p| p.starts_with(common.join("refs/heads")))
    );
    assert!(built.masked.contains(&MaskedPath {
        path: common.join("config"),
        directory: false
    }));
    // The worktree's state file sits next to (not inside) the bound root.
    assert!(!root.join(format!("{CHAT}.state.json")).exists());
}

// contract-test: supporting surface=cli assertions=code-run.remote.resource-profiles
#[test]
fn launch_environment_is_an_explicit_allowlist() {
    let f = fixture();
    let sandbox = Sandbox {
        tier: SandboxTier::Bubblewrap,
        executable: PathBuf::from("/usr/bin/bwrap"),
    };
    let built = plan(
        &f.host(),
        PlanInputs {
            root: &f.root,
            cwd: &f.root,
            worktree: false,
            system: Vec::new(),
            scratch: PathBuf::from(BWRAP_HOME),
        },
    )
    .expect("plan");
    let command = launch_command(&sandbox, &built, &["env".into()]).expect("command");
    let mut names: Vec<String> = command
        .get_envs()
        .map(|(k, _)| k.to_string_lossy().into_owned())
        .collect();
    names.sort();
    assert_eq!(
        names,
        [
            "CI",
            "GIT_CONFIG_NOSYSTEM",
            "GIT_TERMINAL_PROMPT",
            "HOME",
            "LANG",
            "LC_ALL",
            "NO_COLOR",
            "PATH",
            "TMPDIR"
        ]
    );
    let home = command
        .get_envs()
        .find(|(k, _)| *k == "HOME")
        .and_then(|(_, v)| v);
    assert_eq!(home, Some(std::ffi::OsStr::new(BWRAP_HOME)));
}

// --- real bubblewrap runs (skipped where the kernel blocks user namespaces) --

fn bubblewrap() -> Option<Sandbox> {
    match detect() {
        Ok(sandbox) if sandbox.tier != SandboxTier::Seatbelt => Some(sandbox),
        other => {
            eprintln!("skipping confined run: no bubblewrap tier on this host ({other:?})");
            None
        }
    }
}

fn confined(f: &Fixture, sandbox: &Sandbox, script: &str, timeout_ms: u64) -> Value {
    run(
        &f.host(),
        &proposal(&["/bin/sh", "-c", script], timeout_ms),
        sandbox,
        false,
    )
    .expect("run")
}

// contract-test: direct surface=cli assertions=code-run.remote.confinement,code-run.remote.private-path-deny
#[test]
fn confined_command_sees_the_root_but_not_outside_files_or_private_paths() {
    let Some(sandbox) = bubblewrap() else { return };
    let f = fixture();
    let seen = confined(&f, &sandbox, "pwd; cat hello.txt", 20_000);
    assert_eq!(seen["exit_code"], 0, "{seen}");
    assert_eq!(
        seen["stdout"],
        format!("{}\nvisible project file\n", f.root.display())
    );
    assert_eq!(seen["sandbox"], sandbox.tier.as_str());
    let outside = confined(
        &f,
        &sandbox,
        &format!("cat {}/outside.txt", f.outside.display()),
        20_000,
    );
    assert_ne!(outside["exit_code"], 0, "{outside}");
    assert!(
        !outside["stdout"]
            .as_str()
            .unwrap_or("")
            .contains("outside secret")
    );
    let env = confined(&f, &sandbox, "cat .env; ls .ssh", 20_000);
    assert!(
        !env["stdout"].as_str().unwrap_or("").contains("do-not-leak"),
        "{env}"
    );
    assert!(
        !env["stdout"].as_str().unwrap_or("").contains("id_ed25519"),
        "{env}"
    );
    let home = confined(&f, &sandbox, "ls /home /root 2>&1; echo $HOME", 20_000);
    assert!(
        home["stdout"]
            .as_str()
            .unwrap_or("")
            .ends_with(&format!("{BWRAP_HOME}\n")),
        "{home}"
    );
}

// contract-test: direct surface=cli assertions=code-run.remote.confinement
#[test]
fn confined_command_writes_only_inside_the_root() {
    let Some(sandbox) = bubblewrap() else { return };
    let f = fixture();
    let inside = confined(&f, &sandbox, "echo built > out.txt", 20_000);
    assert_eq!(inside["exit_code"], 0, "{inside}");
    assert_eq!(
        fs::read_to_string(f.root.join("out.txt")).expect("written"),
        "built\n"
    );
    let target = f.outside.join("escaped.txt");
    let outside = confined(
        &f,
        &sandbox,
        &format!("echo x > {}", target.display()),
        20_000,
    );
    assert_ne!(outside["exit_code"], 0, "{outside}");
    assert!(!target.exists());
    let env = confined(&f, &sandbox, "echo overwritten > .env", 20_000);
    assert_ne!(env["exit_code"], 0, "{env}");
    assert_eq!(
        fs::read_to_string(f.root.join(".env")).expect("env"),
        "API_TOKEN=do-not-leak\n"
    );
}

// contract-test: direct surface=cli assertions=code-run.remote.managed-jobs,code-run.remote.resource-profiles
#[test]
fn confined_command_is_killed_at_the_deadline_and_capped_and_offline() {
    let Some(sandbox) = bubblewrap() else { return };
    let f = fixture();
    let slow = confined(&f, &sandbox, "sleep 30", 500);
    assert_eq!(slow["timed_out"], true, "{slow}");
    assert!(slow["duration_ms"].as_u64().expect("duration") < 10_000);
    let loud = run(
        &f.host(),
        &validate(&json!({
            "operation_id": "op-2",
            "argv": ["/bin/sh", "-c", "head -c 200000 /dev/zero | tr '\\000' a"],
            "timeout_ms": 20_000,
            "max_output_bytes": 1024,
        }))
        .expect("valid"),
        &sandbox,
        false,
    )
    .expect("run");
    assert_eq!(loud["stdout_truncated"], true);
    assert!(loud["stdout"].as_str().expect("text").len() < DEFAULT_OUTPUT_BYTES);
    // A private network namespace: loopback only, so nothing is reachable.
    let net = confined(
        &f,
        &sandbox,
        "tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' '",
        20_000,
    );
    assert_eq!(net["stdout"], "lo\n", "{net}");
}
