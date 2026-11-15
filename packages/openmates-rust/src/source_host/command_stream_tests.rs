//! Streaming runner behaviour against real `/bin/sh -c` children: chunking,
//! truncation, stop, timeout, exit status, redaction and non-UTF-8 output.

use super::*;
use std::process::Command;

fn sh(script: &str) -> Command {
    let mut command = Command::new("/bin/sh");
    command.arg("-c").arg(script);
    command
}

/// Drain until `Exit`; returns (events before exit, exit status).
fn collect(stream: &CommandStream) -> (Vec<StreamEvent>, ExitStatusKind) {
    let mut events = Vec::new();
    loop {
        let event = stream
            .events()
            .recv_timeout(Duration::from_secs(30))
            .expect("event before timeout");
        match event {
            StreamEvent::Exit { status } => {
                assert!(
                    stream
                        .events()
                        .recv_timeout(Duration::from_millis(200))
                        .is_err(),
                    "nothing after Exit"
                );
                return (events, status);
            }
            other => events.push(other),
        }
    }
}

fn text_of(events: &[StreamEvent], which: StreamName) -> String {
    events
        .iter()
        .filter_map(|e| match e {
            StreamEvent::Output { stream, text } if *stream == which => Some(text.as_str()),
            _ => None,
        })
        .collect()
}

fn run(script: &str, secrets: &[String]) -> (Vec<StreamEvent>, ExitStatusKind) {
    let stream = spawn_streaming(sh(script), Duration::from_secs(10), secrets).unwrap();
    collect(&stream)
}

#[test]
fn streams_stdout_and_stderr_and_succeeds() {
    let (events, status) = run("echo out; echo err >&2", &[]);
    assert_eq!(status, ExitStatusKind::Succeeded);
    assert_eq!(text_of(&events, StreamName::Stdout), "out\n");
    assert_eq!(text_of(&events, StreamName::Stderr), "err\n");
}

#[test]
fn nonzero_exit_reports_code() {
    assert_eq!(run("exit 7", &[]).1, ExitStatusKind::Failed { code: Some(7) });
}

#[test]
fn rejects_out_of_range_deadlines() {
    for deadline in [
        Duration::from_millis(99),
        MAX_DEADLINE + Duration::from_secs(1),
    ] {
        assert!(matches!(
            spawn_streaming(sh("true"), deadline, &[]),
            Err(StreamError::InvalidDeadline)
        ));
    }
}

#[test]
fn chunks_never_exceed_16_kib_and_keep_all_text() {
    let (events, status) = run("head -c 100000 /dev/zero | tr '\\0' 'a'", &[]);
    assert_eq!(status, ExitStatusKind::Succeeded);
    for event in &events {
        if let StreamEvent::Output { text, .. } = event {
            assert!(text.len() <= MAX_OUTPUT_CHUNK_BYTES);
        }
    }
    assert_eq!(text_of(&events, StreamName::Stdout).len(), 100_000);
}

#[test]
fn truncation_event_fires_once_at_the_cap_and_process_finishes() {
    let stream = spawn_streaming_capped(
        sh("head -c 50000 /dev/zero | tr '\\0' 'a'"),
        Duration::from_secs(10),
        &[],
        20_000,
    )
    .unwrap();
    let (events, status) = collect(&stream);
    assert_eq!(status, ExitStatusKind::Succeeded);
    let marks: Vec<_> = events
        .iter()
        .filter(|e| matches!(e, StreamEvent::OutputTruncated { .. }))
        .collect();
    assert_eq!(
        marks,
        vec![&StreamEvent::OutputTruncated {
            retained_bytes: 20_000
        }]
    );
    assert_eq!(text_of(&events, StreamName::Stdout).len(), 20_000);
}

#[test]
fn stop_terminates_the_process_group() {
    let stream =
        spawn_streaming(sh("echo started; sleep 30"), Duration::from_secs(60), &[]).unwrap();
    let first = stream
        .events()
        .recv_timeout(Duration::from_secs(10))
        .unwrap();
    assert!(matches!(first, StreamEvent::Output { .. }));
    let began = Instant::now();
    stream.stop();
    let (_, status) = collect(&stream);
    assert_eq!(status, ExitStatusKind::Stopped);
    assert!(began.elapsed() < Duration::from_secs(10));
}

#[test]
fn stop_escalates_to_kill_when_term_is_ignored() {
    let stream = spawn_streaming(
        sh("trap '' TERM; echo ready; while :; do sleep 1; done"),
        Duration::from_secs(60),
        &[],
    )
    .unwrap();
    let _ready = stream
        .events()
        .recv_timeout(Duration::from_secs(10))
        .unwrap();
    stream.stop();
    assert_eq!(collect(&stream).1, ExitStatusKind::Stopped);
}

#[test]
fn deadline_times_out_a_long_command() {
    let stream = spawn_streaming(sh("sleep 30"), Duration::from_millis(300), &[]).unwrap();
    assert_eq!(collect(&stream).1, ExitStatusKind::TimedOut);
}

#[test]
fn redacts_secrets_in_output() {
    let secrets = vec!["s3cr3t-value".to_string()];
    let (events, _) = run("echo token=s3cr3t-value", &secrets);
    assert_eq!(
        text_of(&events, StreamName::Stdout),
        format!("token={REDACTION_MARKER}\n")
    );
}

#[test]
fn redacts_a_secret_split_across_reads() {
    let secrets = vec!["s3cr3t-value".to_string()];
    let (events, _) = run(
        "printf 'a s3cr3t'; sleep 0.3; printf -- '-value b'",
        &secrets,
    );
    assert_eq!(
        text_of(&events, StreamName::Stdout),
        format!("a {REDACTION_MARKER} b")
    );
}

#[test]
fn collector_holds_back_secret_prefix_until_resolved() {
    let secrets = vec!["abcdef".to_string()];
    let mut collector = Collector::new(&secrets);
    assert_eq!(collector.push(b"xx abc"), "xx ");
    // The completed secret straddles the tail boundary, so it stays held
    // back (same as npm) and is redacted on the next flush.
    assert_eq!(collector.push(b"def yy"), "");
    assert_eq!(collector.finish(), format!("{REDACTION_MARKER} yy"));
}

#[test]
fn invalid_utf8_becomes_replacement_characters() {
    let (events, _) = run("printf 'a\\377b\\n'", &[]);
    assert_eq!(text_of(&events, StreamName::Stdout), "a\u{fffd}b\n");
}

#[test]
fn multibyte_character_split_across_reads_stays_intact() {
    let (events, _) = run("printf '\\303'; sleep 0.3; printf '\\251\\n'", &[]);
    assert_eq!(text_of(&events, StreamName::Stdout), "\u{e9}\n");
}

#[test]
fn terminal_escapes_are_stripped() {
    let (events, _) = run("printf '\\033[31mred\\033[0m\\n'", &[]);
    assert_eq!(text_of(&events, StreamName::Stdout), "red\n");
}
