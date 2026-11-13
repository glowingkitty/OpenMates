// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity
//! Argument parsing, refusal mapping and output formatting of `projects remote`.
use super::*;
use openmates_sdk::work::GitChangedFile;

fn invocation(args: &[&str]) -> Invocation {
    super::super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|error| panic!("{error}"))
        .invocation
        .unwrap()
}
/// `CliError` has no `Debug`, so `unwrap` is unavailable on its results.
trait OkOrPanic<T> {
    fn ok_or_panic(self) -> T;
}
impl<T> OkOrPanic<T> for Result<T, CliError> {
    fn ok_or_panic(self) -> T {
        match self {
            Ok(value) => value,
            Err(_) => panic!("unexpected CliError"),
        }
    }
}
fn result(exit_code: Option<i32>) -> RemoteCommandResult {
    RemoteCommandResult {
        exit_code,
        signal: None,
        timed_out: false,
        duration_ms: 42,
        stdout: "out".into(),
        stderr: "err\n".into(),
        stdout_truncated: false,
        stderr_truncated: true,
        sandbox: "confined".into(),
        root: "/r".into(),
        cwd: ".".into(),
    }
}

#[test]
fn remote_commands_parse_with_flags_and_literal_command_after_double_dash() {
    let i = invocation(&[
        "openmates",
        "projects",
        "remote",
        "run",
        "eng",
        "--chat",
        "c1",
        "--cwd",
        "web",
        "--timeout-ms",
        "5000",
        "--personal",
        "--",
        "cargo",
        "test",
        "--lib",
    ]);
    assert_eq!(i.command_path(), "projects remote run");
    assert!(supported(&i));
    let request = request(&i, "run").ok_or_panic();
    assert_eq!((request.project, request.chat), ("eng", "c1"));
    let command = command(&i).ok_or_panic();
    assert_eq!(command.argv, ["cargo", "test", "--lib"]);
    assert_eq!(command.cwd.as_deref(), Some("web"));
    assert_eq!(command.timeout_ms, 5000);
    for (args, path) in [
        (vec!["status"], "projects remote git status"),
        (
            vec!["commit", "--message", "fix: x"],
            "projects remote git commit",
        ),
        (vec!["land"], "projects remote git land"),
    ] {
        let mut all = vec!["openmates", "projects", "remote", "git"];
        all.extend(&args);
        all.extend(["eng", "--chat", "c1", "--team", "acme", "--source", "s1"]);
        let i = invocation(&all);
        assert_eq!(i.command_path(), path);
        assert!(supported(&i));
    }
}

#[test]
fn remote_requests_reject_missing_inputs_before_any_network_use() {
    let missing = |args: &[&str], action: &str| match request(&invocation(args), action) {
        Err(CliError::Contract { code, .. }) => code,
        _ => panic!("expected contract error for {args:?}"),
    };
    assert_eq!(
        missing(
            &[
                "openmates",
                "projects",
                "remote",
                "git",
                "land",
                "eng",
                "--chat",
                "c"
            ],
            "git land"
        ),
        "context_confirmation_required"
    );
    assert_eq!(
        missing(
            &[
                "openmates",
                "projects",
                "remote",
                "git",
                "land",
                "eng",
                "--personal"
            ],
            "git land"
        ),
        "command_failed"
    );
    assert_eq!(
        missing(
            &[
                "openmates",
                "projects",
                "remote",
                "git",
                "land",
                "eng",
                "--chat",
                "c",
                "--personal",
                "--cwd",
                "x"
            ],
            "git land"
        ),
        "command_failed"
    );
    // The parser itself requires the command words, so build the bare form directly.
    let bare = Invocation {
        path: vec!["projects".into(), "remote".into(), "run".into()],
        positionals: vec!["eng".into()],
        flags: Default::default(),
    };
    assert!(matches!(command(&bare), Err(CliError::Contract { .. })));
    let bad = invocation(&[
        "openmates",
        "projects",
        "remote",
        "run",
        "eng",
        "--chat",
        "c",
        "--personal",
        "--timeout-ms",
        "soon",
        "--",
        "ls",
    ]);
    assert!(matches!(
        command(&bad),
        Err(CliError::Contract {
            code: "invalid_limit",
            ..
        })
    ));
}

#[test]
fn operation_ids_are_unique_and_valid() {
    let (a, b) = (operation_id(), operation_id());
    assert_ne!(a, b);
    assert!((1..=128).contains(&a.len()));
    assert!(
        a.bytes()
            .all(|c| c.is_ascii_alphanumeric() || b".:_-".contains(&c))
    );
}

#[test]
fn run_output_keeps_streams_and_maps_exit_codes() {
    let i = invocation(&[
        "openmates",
        "projects",
        "remote",
        "run",
        "eng",
        "--chat",
        "c",
        "--personal",
        "--",
        "ls",
    ]);
    let out = run_output(&i, &result(Some(3))).ok_or_panic();
    assert_eq!(out.exit_code, 3);
    assert_eq!(out.stdout, "out\n");
    assert_eq!(
        out.stderr,
        "err\nexit 3 in 42 ms, sandbox confined, stderr truncated\n"
    );
    let mut timed_out = result(None);
    timed_out.timed_out = true;
    assert_eq!(run_exit_code(&timed_out), EXIT_TIMED_OUT);
    let mut signalled = result(None);
    signalled.signal = Some(9);
    assert_eq!(run_exit_code(&signalled), 137);
}

#[test]
fn host_refusals_use_a_distinct_exit_code_and_stable_code() {
    let plain = invocation(&[
        "openmates",
        "projects",
        "remote",
        "git",
        "land",
        "eng",
        "--chat",
        "c",
        "--personal",
    ]);
    let out = refusal(
        &plain,
        RemoteOpError::Host {
            code: RemoteOpCode::WriteAuthorizationDenied,
            message: "denied".into(),
        },
    )
    .ok_or_panic();
    assert_eq!(out.exit_code, EXIT_REFUSED);
    assert_eq!(out.stderr, "write_authorization_denied: denied\n");
    let json = refusal_output(true, "no_worktree", "none").ok_or_panic();
    assert!(json.stdout.contains("\"code\": \"no_worktree\""));
    assert_eq!(json.exit_code, EXIT_REFUSED);
}

#[test]
fn git_formatting_lists_changes_and_land_conflicts_exit_nonzero() {
    let status = GitStatusResult {
        exists: true,
        head: Some("0123456789abcdef".into()),
        target_branch: Some("main".into()),
        ahead: 2,
        dirty: true,
        landed: false,
        changed_files: vec![GitChangedFile {
            path: "a.rs".into(),
            status: "M".into(),
        }],
        truncated: false,
    };
    assert_eq!(
        status_text(&status),
        "head 0123456789ab  target main  ahead 2  dirty\nM  a.rs"
    );
    let i = invocation(&[
        "openmates",
        "projects",
        "remote",
        "git",
        "land",
        "eng",
        "--chat",
        "c",
        "--personal",
    ]);
    let conflict = GitLandOutcome::Conflict {
        landed: false,
        code: "land_failed".into(),
        conflicting_paths: vec!["x.rs".into(), "y.rs".into()],
    };
    let out = land_output(&i, &conflict).ok_or_panic();
    assert_eq!(out.exit_code, 1);
    assert!(
        out.stdout
            .contains("Land conflict in 2 path(s):\n  x.rs\n  y.rs")
    );
    let landed = GitLandOutcome::Landed {
        landed: true,
        commit: "0123456789abcdef".into(),
        commits: 2,
        target_branch: "main".into(),
        checked_out: false,
    };
    let out = land_output(&i, &landed).ok_or_panic();
    assert_eq!(out.exit_code, 0);
    assert!(
        out.stdout
            .contains("Landed 2 commit(s) on main at 0123456789ab.")
    );
}
