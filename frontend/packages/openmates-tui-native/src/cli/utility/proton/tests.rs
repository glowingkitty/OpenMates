// contract-test-file: tooling
//! Fixture-only Proton Bridge connector tests: no real Bridge, no network.
use super::logic::*;
use serde_json::json;
use std::time::{Duration, Instant};

const INFO: &str = "Account: user@proton.me\nIMAP\n  Address: 127.0.0.1\n  Port: 1143\n  Username: user@proton.me\n  Password: bridge-pass-1\nSMTP\n  Address: 127.0.0.1\n  Port: 1025\n  Username: user@proton.me\n  Password: bridge-pass-2\n";

#[test]
fn parses_bridge_info_sections() {
    let c = parse_bridge_info(INFO).unwrap();
    assert_eq!((c.imap_host.as_str(), c.imap_port), ("127.0.0.1", 1143));
    assert_eq!(c.smtp_port, Some(1025));
    assert_eq!(c.smtp_password.as_deref(), Some("bridge-pass-2"));
    // npm parity: the shared "all" map keeps the last `address` line.
    assert_eq!(c.account_label.as_deref(), Some("127.0.0.1"));
}
#[test]
fn rejects_remote_hosts_and_missing_credentials() {
    let remote = INFO.replace("127.0.0.1", "mail.example.com");
    assert!(
        parse_bridge_info(&remote)
            .unwrap_err()
            .contains("must be localhost")
    );
    assert!(parse_bridge_info("IMAP\nPort: 1143\n").is_err());
}
#[test]
fn credential_flags_are_rejected_and_secrets_redacted() {
    assert!(reject_credential_flags(["write", "json"]).is_ok());
    let err = reject_credential_flags(["imap-password"]).unwrap_err();
    assert!(err.starts_with("--imap-password is not allowed"));
    assert_eq!(
        redact_secrets("password: hunter2, ok"),
        "password: <redacted>, ok"
    );
    assert!(contains_credential_key(
        &json!({"a": [{"Access_Token": "x"}]})
    ));
    assert!(!contains_credential_key(
        &json!({"query": "password reset"})
    ));
    assert!(
        format!("{:?}", parse_bridge_info(INFO).unwrap())
            .find("bridge-pass")
            .is_none()
    );
}
#[test]
fn resolves_bridge_commands_per_platform() {
    let none = |_: &str| None;
    let mac = resolve_bridge_command("macos", "aarch64", |_| true, none, false).unwrap();
    assert!(mac.should_start && mac.command == MACOS_BRIDGE);
    let arm = resolve_bridge_command("linux", "aarch64", |_| false, |_| Some("/x".into()), false)
        .unwrap();
    assert!(!arm.should_start && arm.guidance.unwrap().contains("not supported"));
    let linux = resolve_bridge_command(
        "linux",
        "x86_64",
        |_| false,
        |n| Some(format!("/usr/bin/{n}")),
        false,
    )
    .unwrap();
    assert!(linux.should_start && linux.command == "/usr/bin/protonmail-bridge");
    let missing = resolve_bridge_command("linux", "x86_64", |_| false, none, false).unwrap();
    assert!(!missing.should_start);
    assert!(resolve_bridge_command("windows", "x86_64", |_| false, none, false).is_err());
}
#[test]
fn registration_is_read_only_by_default_and_secret_free() {
    let c = parse_bridge_info(INFO).unwrap();
    let read = registration("inst", &c, false).unwrap();
    assert_eq!(read["capabilities"], json!(["read"]));
    assert!(read["metadata"].get("write_delay_seconds").is_none());
    let write = registration("inst", &c, true).unwrap();
    assert_eq!(write["metadata"]["write_delay_seconds"], 30);
    assert!(!write.to_string().contains("bridge-pass"));
}
#[test]
fn imap_search_command_and_parsing() {
    assert_eq!(
        search_command("hi \"x\"", "2025-01-30", "2025-02-28"),
        "SEARCH CHARSET UTF-8 ALL SINCE 30-Jan-2025 BEFORE 01-Mar-2025 TEXT \"hi \\\"x\\\"\""
    );
    assert_eq!(search_command("", "bad", ""), "SEARCH ALL");
    assert_eq!(
        parse_search_ids("* SEARCH 3 9 12\r\nA0003 OK done\r\n"),
        vec!["3", "9", "12"]
    );
    assert_eq!(clamp_limit(&json!(500)), 50);
    assert_eq!(clamp_limit(&json!(null)), 10);
    let c = parse_bridge_info(INFO).unwrap();
    let fetched = "* 3 FETCH (BODY[HEADER.FIELDS] {1}\r\nFrom: user@proton.me\r\nSubject: Hello bridge-pass-1\r\nDate: Mon\r\nMessage-ID: <a@b>\r\n\r\nBody text here\r\nA0004 OK\r\n";
    let m = parse_fetch(fetched, "3", &c);
    assert_eq!(m["from"], "<account>");
    assert_eq!(m["subject"], "Hello <redacted>");
    assert_eq!(m["snippet"], "Body text here");
}
#[test]
fn smtp_recipients_and_dot_stuffing() {
    assert_eq!(
        recipients(&json!(["a@b.co", "bad", " c@d.org "])),
        vec!["a@b.co", "c@d.org"]
    );
    let msg = smtp_message(
        "me@x.io",
        &["a@b.co".into()],
        "Hi\nthere",
        ".dot\nline",
        "<id>",
        "date",
    );
    assert!(msg.contains("Subject: Hi there"));
    assert!(msg.ends_with("\r\n\r\n..dot\r\nline"));
}
#[test]
fn delayed_send_queue_supports_undo_until_delivery() {
    let t0 = Instant::now();
    let mut q = SendQueue::new(Duration::from_secs(30));
    let kept = q.queue("r1", json!({"to": "a@b.co"}), t0);
    let undone = q.queue("r2", json!({"to": "c@d.co"}), t0);
    assert_eq!(q.undo(&undone), Ok(JobStatus::Cancelled));
    assert!(q.take_due(t0 + Duration::from_secs(29)).is_empty());
    let due = q.take_due(t0 + Duration::from_secs(30));
    assert_eq!(due.len(), 1);
    assert_eq!(
        (due[0].0.as_str(), due[0].1.as_str()),
        (kept.as_str(), "r1")
    );
    assert_eq!(q.undo(&kept), Ok(JobStatus::Delivered));
    assert!(q.undo("missing").is_err());
}
