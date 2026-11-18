//! Event queue tests: sequencing, renumbering, sealing vector, model text.

use super::events::*;
use super::wire::{EventStatus, LeaseIdentity};
use crate::crypto;
use serde_json::{Value, json};

const KEY: [u8; 32] = [7u8; 32];

fn lease() -> LeaseIdentity {
    LeaseIdentity {
        execution_id: "e1".into(),
        project_id: "p1".into(),
        source_id: "s1".into(),
        source_session_id: "session-1".into(),
        team_id: None,
        lease_token: "t".repeat(16),
        lease_generation: 1,
    }
}

fn queue() -> ExecutionEvents {
    let mut q = ExecutionEvents::new("e1", -1, 0);
    q.apply_lease(lease(), -1);
    q
}

fn open(frame: &Value) -> Value {
    let sealed = frame["encrypted_event"].as_str().unwrap();
    serde_json::from_str(&crypto::decrypt_combined(sealed, &KEY).unwrap()).unwrap()
}

#[test]
fn sealed_event_opens_with_origin_decrypt_and_matches_envelope() {
    let mut q = queue();
    q.push_output(1, Stream::Stdout, "hi\n", EventStatus::Running);
    let out = q.next_frame(&KEY).unwrap().unwrap();
    assert_eq!(
        (out.frame, out.ack, out.sequence),
        ("remote_command_event", "remote_command_event_ack", 0)
    );
    // Same checks the origin performs in client/remote_command_jobs.rs.
    let body = open(&out.payload);
    assert_eq!(body["execution_id"], "e1");
    assert_eq!(body["sequence"], out.payload["sequence"]);
    assert_eq!(body["event_kind"], out.payload["event_kind"]);
    assert_eq!(body["status"], out.payload["status"]);
    assert_eq!(
        (body["text"].as_str(), body["trusted"].clone()),
        (Some("hi\n"), json!(false))
    );
    assert!(
        crypto::decrypt_combined(out.payload["encrypted_event"].as_str().unwrap(), &[8u8; 32])
            .is_err()
    );
}

#[test]
fn sequences_are_strict_and_retries_resend_identical_bytes() {
    let mut q = queue();
    q.push_status(EventStatus::Running, json!({"status":"running"}));
    q.push_output(1, Stream::Stdout, "a", EventStatus::Running);
    let first = q.next_frame(&KEY).unwrap().unwrap();
    let retry = q.next_frame(&KEY).unwrap().unwrap();
    assert_eq!(first, retry);
    assert!(q.acknowledge(-1, 1).is_err());
    q.acknowledge(0, 1).unwrap();
    assert_eq!(q.next_frame(&KEY).unwrap().unwrap().sequence, 1);
}

#[test]
fn renewed_lease_drops_acked_and_renumbers_unacked() {
    let mut q = queue();
    q.push_output(1, Stream::Stdout, "a", EventStatus::Running);
    q.push_output(2, Stream::Stdout, "b", EventStatus::Running);
    q.next_frame(&KEY).unwrap();
    // Server already has sequence 0 (ack was lost): only "b" remains, as 1.
    q.apply_lease(lease(), 0);
    assert_eq!(q.pending_len(), 1);
    let out = q.next_frame(&KEY).unwrap().unwrap();
    assert_eq!(out.sequence, 1);
    assert_eq!(open(&out.payload)["text"], "b");
}

#[test]
fn terminal_is_a_completion_with_model_text_and_ends_the_queue() {
    let mut q = queue();
    q.push_output(1, Stream::Stdout, "out", EventStatus::Running);
    q.push_output(2, Stream::Stderr, "err", EventStatus::Running);
    q.push_terminal(EventStatus::Failed, json!({"status":"failed"}), false);
    q.push_output(3, Stream::Stdout, "late", EventStatus::Running);
    assert_eq!(q.pending_len(), 3);
    for expected in 0..2 {
        assert_eq!(q.next_frame(&KEY).unwrap().unwrap().sequence, expected);
        q.acknowledge(expected, 1).unwrap();
    }
    let out = q.next_frame(&KEY).unwrap().unwrap();
    assert_eq!(
        (out.frame, out.ack),
        (
            "remote_command_source_completion",
            "remote_command_source_completion_ack"
        )
    );
    assert_eq!(out.payload["status"], "failed");
    assert_eq!(out.payload["model_text"], "[stdout] out\n[stderr] err");
    assert_eq!(open(&out.payload)["output_selection"]["coverage"], "full");
    q.acknowledge(2, 2).unwrap();
    assert!(q.is_completed() && q.lease().is_none());
}

#[test]
fn excerpt_is_capped_marked_and_gap_means_upstream_truncated() {
    let mut q = queue();
    let chunk = "x".repeat(200 * 1024);
    for i in 1..=4 {
        q.push_output(i, Stream::Stdout, &chunk, EventStatus::Running);
    }
    let text = q.completion_model_text(EventStatus::Succeeded);
    assert!(text.starts_with("[OpenMates output excerpt is incomplete]\n"));
    assert!(text.len() <= 512 * 1024);

    let mut q = queue();
    assert_eq!(
        q.completion_model_text(EventStatus::Stopped),
        "Command stopped."
    );
    q.push_output(1, Stream::Stdout, "a", EventStatus::Running);
    q.push_output(5, Stream::Stdout, "b", EventStatus::Running); // gap
    q.push_truncated(262_144, EventStatus::Running);
    q.push_terminal(EventStatus::Succeeded, json!({}), false);
    assert!(
        q.completion_model_text(EventStatus::Succeeded)
            .starts_with("[OpenMates")
    );
}

#[test]
fn heartbeat_is_due_only_when_idle_running_and_leased() {
    let mut q = queue();
    assert!(!q.heartbeat_due(29_999) && q.heartbeat_due(30_000));
    q.push_status(EventStatus::Running, json!({}));
    assert!(!q.heartbeat_due(60_000));
    q.clear_lease();
    assert!(q.next_frame(&KEY).unwrap().is_none());
}

#[test]
fn sealed_event_uses_the_web_embed_envelope_the_browser_opens() {
    use base64::Engine as _;
    let mut q = queue();
    q.push_output(1, Stream::Stdout, "ok\n", EventStatus::Running);
    let out = q.next_frame(&KEY).unwrap().unwrap();
    let sealed = out.payload["encrypted_event"].as_str().unwrap();
    let raw = base64::engine::general_purpose::STANDARD
        .decode(sealed)
        .unwrap();
    // `decryptWithEmbedKey` (MetadataEncryptor.ts) reads iv = bytes[0..12] and
    // the AES-GCM ciphertext+tag after it, with no `OM` marker or fingerprint.
    let plain = crypto::decrypt_aead(&raw[12..], &KEY, &raw[..12], &[]).unwrap();
    let event: Value = serde_json::from_slice(&plain).unwrap();
    assert_eq!(event["text"], "ok\n");
    assert_eq!(event["sequence"], 0);
}
