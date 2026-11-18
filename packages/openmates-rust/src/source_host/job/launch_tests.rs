//! Launch refusals and real confined runs (skipped, with a note on stderr,
//! where the machine has no sandbox tier).
use super::launch::{JobProcess, LaunchError, launch, launch_on};
use super::portable::Policy;
use super::portable::{Mode, PortableRequest, SourceAccess};
use super::wire::Approval;
use super::wire::RemoteCommandErrorCode;
use crate::source_host::command_sandbox::detect;
use crate::source_host::command_sandbox::{Sandbox, SandboxTier, Unavailable};
use crate::source_host::command_stream::{ExitStatusKind, StreamEvent};
use crate::source_host::reads::HostRoot;
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

struct Fixture {
    _root: tempfile::TempDir,
    _state: tempfile::TempDir,
    root: PathBuf,
    state: PathBuf,
}

fn fixture() -> Fixture {
    let root = tempfile::tempdir().expect("tempdir");
    let state = tempfile::tempdir().expect("tempdir");
    let f = Fixture {
        root: fs::canonicalize(root.path()).expect("canonical"),
        state: fs::canonicalize(state.path()).expect("canonical"),
        _root: root,
        _state: state,
    };
    fs::write(f.root.join("hello.txt"), "visible project file\n").expect("write");
    fs::write(f.root.join(".env"), "API_TOKEN=do-not-leak\n").expect("write");
    fs::create_dir(f.root.join("sub")).expect("mkdir");
    f
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

fn request(argv: &[&str], mutate: impl FnOnce(&mut Policy)) -> PortableRequest {
    let mut policy = Policy {
        argv: argv.iter().map(|a| (*a).to_owned()).collect(),
        cwd: ".".to_owned(),
        mode: Mode::Foreground,
        source_access: SourceAccess::ReadOnly,
        deadline_ms: 20_000,
        writable_profiles: Vec::new(),
        network_profile: None,
        credential_profiles: Vec::new(),
    };
    mutate(&mut policy);
    PortableRequest {
        execution_id: "exec-1".to_owned(),
        chat_id: "chat-1".to_owned(),
        project_id: "project-1".to_owned(),
        source_id: "source-1".to_owned(),
        policy,
        approval: Approval::OneRun,
    }
}

fn tier() -> Option<Sandbox> {
    match detect() {
        Ok(sandbox) => Some(sandbox),
        other => {
            eprintln!("skipping confined run: no sandbox tier on this host ({other:?})");
            None
        }
    }
}

/// Collected output and final status of a job.
fn finish(job: &JobProcess) -> (String, ExitStatusKind) {
    let mut text = String::new();
    loop {
        match job.stream.events().recv_timeout(Duration::from_secs(30)) {
            Ok(StreamEvent::Output { text: t, .. }) => text.push_str(&t),
            Ok(StreamEvent::OutputTruncated { .. }) => {}
            Ok(StreamEvent::Exit { status }) => return (text, status),
            Err(e) => panic!("job did not finish: {e}"),
        }
    }
}

fn run(
    f: &Fixture,
    sandbox: &Sandbox,
    script: &str,
    access: SourceAccess,
) -> (String, ExitStatusKind) {
    let req = request(&["/bin/sh", "-c", script], |p| p.source_access = access);
    let job = launch_on(&f.host(), &req, sandbox, false).expect("launch");
    finish(&job)
}

fn refused(f: &Fixture, req: &PortableRequest) -> LaunchError {
    let sandbox = Sandbox {
        tier: SandboxTier::Bubblewrap,
        executable: PathBuf::from("/nonexistent"),
    };
    match launch_on(&f.host(), req, &sandbox, false) {
        Ok(_) => panic!("launch must be refused"),
        Err(e) => e,
    }
}

// contract-test: supporting surface=cli assertions=code-run.remote.sandbox-tiers
#[test]
fn unsupported_resources_are_refused_with_their_codes() {
    let f = fixture();
    let cases: [(Box<dyn FnOnce(&mut Policy)>, RemoteCommandErrorCode); 4] = [
        (
            Box::new(|p| {
                p.mode = Mode::Background;
                p.source_access = SourceAccess::ReadWrite;
            }),
            RemoteCommandErrorCode::InvalidRequest,
        ),
        (
            Box::new(|p| p.writable_profiles = vec!["cache".into()]),
            RemoteCommandErrorCode::ResourceNotGranted,
        ),
        (
            Box::new(|p| p.network_profile = Some("registry".into())),
            RemoteCommandErrorCode::NetworkProfileUnavailable,
        ),
        (
            Box::new(|p| p.credential_profiles = vec!["token".into()]),
            RemoteCommandErrorCode::CredentialUnavailable,
        ),
    ];
    for (mutate, code) in cases {
        let error = refused(&f, &request(&["/bin/true"], mutate));
        assert_eq!(error.code, code, "{error}");
    }
}

// contract-test: supporting surface=cli assertions=code-run.remote.confinement
#[test]
fn a_cwd_outside_the_root_or_private_is_refused() {
    let f = fixture();
    fs::create_dir(f.root.join(".ssh")).expect("mkdir");
    for cwd in [
        "../elsewhere",
        "/etc",
        "sub/../../x",
        ".ssh",
        "hello.txt",
        "missing",
    ] {
        let error = refused(&f, &request(&["/bin/true"], |p| p.cwd = cwd.to_owned()));
        assert_eq!(error.code, RemoteCommandErrorCode::InvalidRequest, "{cwd}");
    }
    let escape = tempfile::tempdir().expect("tempdir");
    std::os::unix::fs::symlink(escape.path(), f.root.join("link")).expect("symlink");
    let error = refused(&f, &request(&["/bin/true"], |p| p.cwd = "link".to_owned()));
    assert_eq!(error.code, RemoteCommandErrorCode::InvalidRequest);
}

// contract-test: supporting surface=cli assertions=code-run.remote.sandbox-tiers
#[test]
fn a_missing_sandbox_tier_maps_to_confinement_unavailable() {
    let unavailable = Unavailable::ConfinementUnavailable;
    assert_eq!(unavailable.code(), "confinement_unavailable");
    if detect().is_err() {
        let f = fixture();
        let error = launch(&f.host(), &request(&["/bin/true"], |_| {}), false)
            .err()
            .expect("refused");
        assert!(matches!(
            error.code,
            RemoteCommandErrorCode::ConfinementUnavailable
                | RemoteCommandErrorCode::UnsupportedPlatform
        ));
    }
}

// contract-test: supporting surface=cli assertions=code-run.remote.confinement
#[test]
fn a_command_runs_and_streams_output_in_the_root() {
    let Some(sandbox) = tier() else { return };
    let f = fixture();
    let (out, status) = run(
        &f,
        &sandbox,
        "echo ok; cat hello.txt; pwd",
        SourceAccess::ReadOnly,
    );
    assert_eq!(status, ExitStatusKind::Succeeded, "{out}");
    assert!(out.contains("ok"), "{out}");
    assert!(out.contains("visible project file"), "{out}");
    assert!(out.contains(&f.root.display().to_string()), "{out}");
}

// contract-test: supporting surface=cli assertions=code-run.remote.confinement
#[test]
fn read_only_source_blocks_writes_and_read_write_allows_them() {
    let Some(sandbox) = tier() else { return };
    let f = fixture();
    let (_, status) = run(&f, &sandbox, "echo x > new.txt", SourceAccess::ReadOnly);
    assert!(
        matches!(status, ExitStatusKind::Failed { .. }),
        "{status:?}"
    );
    assert!(!f.root.join("new.txt").exists());
    let (_, status) = run(&f, &sandbox, "echo x > new.txt", SourceAccess::ReadWrite);
    assert_eq!(status, ExitStatusKind::Succeeded);
    assert!(f.root.join("new.txt").exists());
}

// contract-test: supporting surface=cli assertions=code-run.remote.private-path-deny
#[test]
fn private_paths_and_host_environment_are_hidden() {
    let Some(sandbox) = tier() else { return };
    let f = fixture();
    // SAFETY-free probe: the host process variable must not reach the job.
    let (out, status) = run(
        &f,
        &sandbox,
        "cat .env 2>&1; echo \"home=$HOME user=${USER:-unset}\"",
        SourceAccess::ReadOnly,
    );
    assert_eq!(status, ExitStatusKind::Succeeded, "{out}");
    assert!(!out.contains("do-not-leak"), "{out}");
    assert!(out.contains("user=unset"), "{out}");
}

// contract-test: supporting surface=cli assertions=code-run.remote.confinement
#[test]
fn stop_terminates_the_job_and_a_short_deadline_times_out() {
    let Some(sandbox) = tier() else { return };
    let f = fixture();
    let req = request(&["/bin/sh", "-c", "sleep 30"], |_| {});
    let job = launch_on(&f.host(), &req, &sandbox, false).expect("launch");
    job.stream.stop();
    assert_eq!(finish(&job).1, ExitStatusKind::Stopped);
    let req = request(&["/bin/sh", "-c", "sleep 30"], |p| p.deadline_ms = 300);
    let job = launch_on(&f.host(), &req, &sandbox, false).expect("launch");
    assert_eq!(finish(&job).1, ExitStatusKind::TimedOut);
}
