// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity
//! Parsing, refusal mapping and formatting of `projects remote hosts|create`.
use super::*;
use openmates_sdk::work::RemoteOpCode;

fn invocation(args: &[&str]) -> Invocation {
    super::super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|error| panic!("{error}"))
        .invocation
        .unwrap()
}
fn create_error(args: &[&str]) -> String {
    match create_request(&invocation(args)) {
        Err(CliError::Contract { code, message }) => format!("{code}: {message}"),
        Err(_) => "other error".into(),
        Ok(_) => "ok".into(),
    }
}
fn out(result: Result<CliOutput, CliError>) -> CliOutput {
    match result {
        Ok(out) => out,
        Err(_) => panic!("unexpected CliError"),
    }
}

#[test]
fn create_parses_host_name_chat_and_context() {
    let i = invocation(&[
        "openmates",
        "projects",
        "remote",
        "create",
        "eng",
        "--chat",
        "c1",
        "--personal",
        "--host",
        "abc",
        "--name",
        "Kitchen renovation",
    ]);
    assert_eq!(i.command_path(), "projects remote create");
    assert!(supported(&i));
    let req = create_request(&i).ok().unwrap();
    assert_eq!(
        (req.project, req.chat, req.host, req.name),
        ("eng", "c1", Some("abc"), "Kitchen renovation")
    );
    assert_eq!(req.source, None);
    let hosts = invocation(&[
        "openmates",
        "projects",
        "remote",
        "hosts",
        "eng",
        "--personal",
    ]);
    assert_eq!(hosts.command_path(), "projects remote hosts");
    assert!(supported(&hosts));
}

#[test]
fn create_requires_context_chat_name_and_exactly_one_target() {
    let base = ["openmates", "projects", "remote", "create", "eng"];
    let with = |extra: &[&str]| create_error(&[&base[..], extra].concat());
    assert!(
        with(&["--chat", "c", "--host", "h", "--name", "N"])
            .starts_with("context_confirmation_required")
    );
    assert!(with(&["--personal", "--host", "h", "--name", "N"]).contains("--chat"));
    assert!(with(&["--personal", "--chat", "c", "--host", "h"]).contains("--name"));
    assert!(with(&["--personal", "--chat", "c", "--name", "N"]).contains("--host"));
    assert!(
        with(&[
            "--personal",
            "--chat",
            "c",
            "--name",
            "N",
            "--host",
            "h",
            "--source",
            "s"
        ])
        .contains("Use only one")
    );
    assert_eq!(
        with(&["--personal", "--chat", "c", "--name", "N", "--source", "s"]),
        "ok"
    );
}

#[test]
fn formats_hosts_and_created_folder() {
    assert_eq!(host_line("abc", &["a".into(), "b".into()]), "abc  a, b");
    assert_eq!(
        created_text(
            "kitchen-renovation",
            "/p/kitchen-renovation",
            "main",
            "0123456789abcdef"
        ),
        "Created kitchen-renovation at /p/kitchen-renovation (branch main, head 0123456789ab)."
    );
}

#[test]
fn refused_creation_prints_code_and_pending_placeholder_with_exit_125() {
    let error = || RemoteOpError::Host {
        code: RemoteOpCode::CreationNotConfigured,
        message: "not configured".into(),
    };
    let plain = out(creation_refusal(false, "src-1", error()));
    assert_eq!(plain.exit_code, 125);
    assert!(
        plain
            .stderr
            .starts_with("creation_not_configured: not configured\n")
    );
    assert!(plain.stderr.contains("--source src-1"));
    let json = out(creation_refusal(true, "src-1", error()));
    assert_eq!(json.exit_code, 125);
    assert!(json.stdout.contains("\"source_id\": \"src-1\""));
    assert!(
        json.stdout
            .contains("\"code\": \"creation_not_configured\"")
    );
}

#[test]
fn every_creation_code_has_a_stable_spelling() {
    for (code, name) in [
        (
            RemoteOpCode::CreationNotConfigured,
            "creation_not_configured",
        ),
        (RemoteOpCode::InvalidProjectName, "invalid_project_name"),
        (
            RemoteOpCode::CreationFolderUnavailable,
            "creation_folder_unavailable",
        ),
        (RemoteOpCode::TargetExists, "target_exists"),
        (
            RemoteOpCode::CreationCompletionFailed,
            "creation_completion_failed",
        ),
    ] {
        assert_eq!(code_name(&code), name);
    }
}
