//! Job driver against a scripted server: discover, claim, revalidate, launch
//! of a real confined command (skipped with a stderr note without a sandbox
//! tier), sequenced events with acks, stop, and typed refusals.
use super::driver::{DriverSource, JobDriver};
use super::launch::detect_sandbox;
use super::portable::{Mode, Policy, PortableRequest, SourceAccess, canonical_request};
use super::transport::{ServerFrame, admit};
use super::wire::Approval;
use crate::crypto::{self, Key};
use crate::remote_command_review::request_digest;
use crate::source_host::reads::HostRoot;
use serde_json::{Value, json};
use std::path::PathBuf;
use std::time::Duration;
use zeroize::Zeroizing;

const EXECUTION: &str = "exec-1";

struct Harness {
    _root: tempfile::TempDir,
    _state: tempfile::TempDir,
    root: PathBuf,
    key: Key,
    driver: JobDriver,
    summary: Value,
    claim_payload: Value,
    log: Vec<(String, Value)>,
    now: u64,
}

fn summary(state: &str) -> Value {
    json!({
        "protocol_version": 1, "execution_id": EXECUTION, "chat_id": "chat-1",
        "project_id": "project-1", "source_id": "source-1", "state": state,
        "last_sequence": -1, "lease_expires_at": 0,
    })
}

impl Harness {
    /// `digest_override` replaces the claim's `request_digest` (tamper test).
    fn new(argv: &[&str], mode: Mode, digest_override: Option<&str>) -> Self {
        let root_dir = tempfile::tempdir().expect("tempdir");
        let state_dir = tempfile::tempdir().expect("tempdir");
        let root = std::fs::canonicalize(root_dir.path()).expect("canonical");
        let state = std::fs::canonicalize(state_dir.path()).expect("canonical");
        let key: Key = Zeroizing::new([7u8; 32]);
        let request = PortableRequest {
            execution_id: EXECUTION.into(),
            chat_id: "chat-1".into(),
            project_id: "project-1".into(),
            source_id: "source-1".into(),
            policy: Policy {
                argv: argv.iter().map(|a| (*a).to_owned()).collect(),
                cwd: ".".into(),
                mode,
                source_access: SourceAccess::ReadWrite,
                deadline_ms: 60_000,
                writable_profiles: Vec::new(),
                network_profile: None,
                credential_profiles: Vec::new(),
            },
            approval: Approval::OneRun,
        };
        let plaintext = canonical_request(&request);
        let digest = request_digest(&plaintext, &key[..]).expect("digest");
        let claim_payload = json!({
            "protocol_version": 1, "execution_id": EXECUTION, "chat_id": "chat-1",
            "project_id": "project-1", "source_id": "source-1", "state": "LEASED",
            "encrypted_request": crypto::encrypt_combined(&plaintext, &key).expect("seal"),
            "request_digest": digest_override.map_or(digest, str::to_owned),
            "approval": {"kind": "one_run"}, "key_epoch": 1,
            "lease_token": "lease-token-0123456789", "lease_generation": 1,
            "lease_expires_at": 4_000_000_000_i64, "last_sequence": -1, "launch_allowed": true,
        });
        let source = DriverSource {
            project_id: "project-1".into(),
            source_id: "source-1".into(),
            team_id: None,
            key_epoch: 1,
            key: key.clone(),
            host: HostRoot {
                root: root.clone(),
                state_dir: state,
                policy_source: None,
            },
            target_branch: None,
        };
        let mut driver = JobDriver::new("session-1", vec![source]);
        driver.on_connected();
        Self {
            _root: root_dir,
            _state: state_dir,
            root,
            key,
            driver,
            summary: summary("WAITING_FOR_EXECUTOR"),
            claim_payload,
            log: Vec::new(),
            now: 1_000,
        }
    }

    fn feed(&mut self, kind: &str, payload: &Value) {
        let frame = admit(kind, payload).expect("valid").expect("job frame");
        self.driver.handle_frame(frame);
    }

    /// One serve iteration: tick, send the outbox, answer like the server.
    fn step(&mut self) {
        self.now += 50;
        self.driver.tick(self.now);
        for (kind, payload) in self.driver.take_outbox() {
            self.log.push((kind.to_owned(), payload.clone()));
            match kind {
                "remote_command_discover" => {
                    let jobs = json!({"jobs": [self.summary.clone()]});
                    self.feed("remote_command_jobs", &jobs);
                }
                "remote_command_claim" => {
                    let claim = self.claim_payload.clone();
                    self.feed("remote_command_request", &claim);
                }
                "remote_command_revalidate" => {
                    let digest = self.claim_payload["request_digest"].clone();
                    let reply = json!({
                        "execution_id": EXECUTION, "request_digest": digest,
                        "authorized": true, "stop_requested": false,
                    });
                    self.feed("remote_command_authority", &reply);
                }
                "remote_command_event" | "remote_command_source_completion" => {
                    let mut ack = summary("RUNNING");
                    ack["last_sequence"] = payload["sequence"].clone();
                    let ack_kind = if kind == "remote_command_event" {
                        "remote_command_event_ack"
                    } else {
                        "remote_command_source_completion_ack"
                    };
                    self.feed(ack_kind, &ack);
                }
                _ => {}
            }
        }
        std::thread::sleep(Duration::from_millis(20));
    }

    fn run_until(&mut self, done: impl Fn(&Harness) -> bool) {
        for _ in 0..400 {
            if done(self) {
                return;
            }
            self.step();
        }
        panic!("condition not reached; frames: {:?}", self.kinds());
    }

    fn kinds(&self) -> Vec<String> {
        self.log.iter().map(|(k, _)| k.clone()).collect()
    }

    fn completion(&self) -> Option<&Value> {
        self.log
            .iter()
            .find(|(k, _)| k == "remote_command_source_completion")
            .map(|(_, p)| p)
    }

    /// Decrypted plaintexts of every event and the completion, in send order.
    fn plaintexts(&self) -> Vec<Value> {
        self.log
            .iter()
            .filter(|(k, _)| k == "remote_command_event" || k == "remote_command_source_completion")
            .map(|(_, p)| {
                let text = crypto::decrypt_combined(
                    p["encrypted_event"].as_str().expect("sealed"),
                    &self.key,
                )
                .expect("open");
                serde_json::from_str(&text).expect("json")
            })
            .collect()
    }
}

fn sandbox_or_skip() -> bool {
    if detect_sandbox().is_err() {
        eprintln!("skipped: no command sandbox tier on this machine");
        return false;
    }
    true
}

#[test]
fn runs_a_command_and_completes_with_consecutive_sequences() {
    if !sandbox_or_skip() {
        return;
    }
    let mut h = Harness::new(&["sh", "-c", "echo ok"], Mode::Foreground, None);
    h.run_until(|h| h.completion().is_some() && h.driver.active_len() == 0);
    let completion = h.completion().expect("completion");
    assert_eq!(completion["status"], "succeeded");
    assert!(
        completion["model_text"]
            .as_str()
            .expect("text")
            .contains("[stdout] ok")
    );
    let sequences: Vec<i64> = h
        .log
        .iter()
        .filter(|(k, _)| {
            k.starts_with("remote_command_event") || k == "remote_command_source_completion"
        })
        .map(|(_, p)| p["sequence"].as_i64().expect("sequence"))
        .collect();
    let expected: Vec<i64> = (0..sequences.len() as i64).collect();
    assert_eq!(sequences, expected, "sequences are consecutive from 0");
    let plain = h.plaintexts();
    assert_eq!(plain[0]["status"], "authorizing");
    assert!(plain.iter().any(
        |p| p["event_kind"] == "output" && p["text"].as_str().is_some_and(|t| t.contains("ok"))
    ));
    assert_eq!(plain.last().expect("terminal")["event_kind"], "terminal");
    let revalidations = h
        .kinds()
        .iter()
        .filter(|k| *k == "remote_command_revalidate")
        .count();
    assert_eq!(revalidations, 2);
}

#[test]
fn stop_request_terminates_a_running_command() {
    if !sandbox_or_skip() {
        return;
    }
    let mut h = Harness::new(&["sh", "-c", "sleep 30"], Mode::Foreground, None);
    h.run_until(|h| h.plaintexts().iter().any(|p| p["status"] == "running"));
    let stop = ServerFrame::StopRequested(
        super::wire::validate_summary(&summary("STOP_REQUESTED")).expect("summary"),
    );
    h.driver.handle_frame(stop);
    h.run_until(|h| h.completion().is_some());
    assert_eq!(h.completion().expect("completion")["status"], "stopped");
}

#[test]
fn bad_request_digest_is_refused_and_nothing_launches() {
    let mut h = Harness::new(
        &["sh", "-c", "touch marker"],
        Mode::Foreground,
        Some(&"A".repeat(43)),
    );
    h.run_until(|h| h.completion().is_some());
    assert_eq!(h.completion().expect("completion")["status"], "failed");
    let last = h.plaintexts().pop().expect("terminal");
    assert_eq!(last["job"]["error_code"], "invalid_request");
    assert!(!h.root.join("marker").exists());
    assert!(!h.kinds().contains(&"remote_command_revalidate".to_owned()));
}

#[test]
fn background_jobs_are_refused_with_a_typed_error() {
    let mut h = Harness::new(&["sh", "-c", "touch marker"], Mode::Background, None);
    h.run_until(|h| h.completion().is_some());
    assert_eq!(h.completion().expect("completion")["status"], "failed");
    let last = h.plaintexts().pop().expect("terminal");
    assert_eq!(last["job"]["error_code"], "invalid_request");
    assert!(
        last["job"]["error_message"]
            .as_str()
            .expect("message")
            .contains("Background")
    );
    assert!(!h.root.join("marker").exists());
}

#[test]
fn command_in_a_git_source_runs_in_the_chat_worktree_not_the_source_root() {
    if !sandbox_or_skip() {
        return;
    }
    let mut h = Harness::new(&["sh", "-c", "pwd; cat marker.txt"], Mode::Foreground, None);
    std::fs::write(h.root.join("marker.txt"), "committed\n").expect("marker");
    for args in [
        vec!["init", "-q", "-b", "main"],
        vec!["add", "marker.txt"],
        vec![
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.org",
            "commit",
            "-q",
            "-m",
            "first",
        ],
    ] {
        let status = std::process::Command::new("git")
            .args(&args)
            .current_dir(&h.root)
            .status()
            .expect("git");
        assert!(status.success(), "git {args:?}");
    }
    h.run_until(|h| h.completion().is_some() && h.driver.active_len() == 0);
    let completion = h.completion().expect("completion");
    assert_eq!(completion["status"], "succeeded");
    let text = completion["model_text"].as_str().expect("text").to_owned();
    let root = h.root.to_string_lossy().into_owned();
    let cwd = text
        .lines()
        .find_map(|line| line.strip_prefix("[stdout] "))
        .expect("pwd line");
    assert_ne!(
        cwd, root,
        "the command must not run in the live source root"
    );
    assert!(
        text.contains("committed"),
        "the worktree holds the committed files: {text}"
    );
}
