//! Deterministic link machine scenarios (fake clock, fake sockets).
use super::machine_harness::*;
use super::*;

fn has(commands: &[Command], wanted: &Command) -> bool {
    commands.contains(wanted)
}

#[test]
fn first_connect_uses_the_sign_in_token_and_starts_heartbeat() {
    let mut h = Harness::new();
    let out = h.sign_in(true);
    assert_eq!(statuses(&out), vec![LinkStatus::Connecting]);
    assert_eq!(opens(&out), 1);
    assert!(h.refreshes.is_empty(), "first attempt after sign-in uses the issued token");
    let out = h.open_last();
    let socket = h.last();
    assert_eq!(events(&out), vec![LinkEvent::Open]);
    assert_eq!(statuses(&out), vec![LinkStatus::Connected]);
    assert_eq!(delays(&out, TimerKind::Ping), vec![25_000]);
    assert!(has(&out, &Command::Settle(Ok(()))));
    assert_eq!(h.socket(socket).sent, vec!["lifecycle:open:false"]);
    assert_eq!(h.machine.open_socket(), Some(socket));
}

#[test]
fn missing_token_refreshes_before_opening() {
    let mut h = Harness::new();
    let out = h.sign_in(false);
    assert_eq!(refresh_reasons(&out), vec![RefreshReason::MissingToken]);
    assert_eq!(opens(&out), 0);
    let out = h.answer_refresh(RefreshOutcome::Ready, true);
    assert_eq!(opens(&out), 1);
}

#[test]
fn backoff_doubles_to_the_cap_then_periodic_retry_and_every_reconnect_refreshes_the_token() {
    let mut h = Harness::connected();
    let mut all = h.close_last(1000, "", true);
    assert_eq!(events(&all), vec![LinkEvent::Close(1000)]);
    for _ in 0..10 {
        all.extend(h.advance(5_000));
        all.extend(h.fail_attempt());
    }
    assert_eq!(delays(&all, TimerKind::Backoff), vec![1_000, 2_000, 4_000, 5_000, 5_000, 5_000, 5_000, 5_000, 5_000, 5_000]);
    // Owner consistency: a reconnect never reuses the previous query token.
    assert_eq!(refresh_reasons(&all), vec![RefreshReason::Reconnect; 10]);
    assert!(events(&all).contains(&LinkEvent::ConnectionFailedReconnect));
    assert_eq!(h.machine.status(), LinkStatus::Error);
    assert_eq!(h.machine.error(), Some("Max reconnect attempts reached. Will keep retrying."));
    assert_eq!(delays(&all, TimerKind::Periodic), vec![30_000]);
    let quiet = h.advance(29_999);
    assert!(quiet.is_empty());
    let out = h.advance(1);
    assert_eq!(statuses(&out), vec![LinkStatus::Connecting], "periodic retry resets the attempt counter");
    assert_eq!(refresh_reasons(&out), vec![RefreshReason::Reconnect]);
    h.answer_refresh(RefreshOutcome::Ready, true);
    let out = h.open_last();
    assert_eq!(statuses(&out), vec![LinkStatus::Connected]);
    assert_eq!(h.machine.attempts(), 0);
}

#[test]
fn heartbeat_pong_keeps_the_socket_and_a_missing_pong_detaches_and_reconnects() {
    let mut h = Harness::connected();
    let socket = h.last();
    h.advance(25_000);
    assert_eq!(h.socket(socket).sent[1..], ["lifecycle:heartbeat:false".to_string(), "ping".into()]);
    assert!(h.frame(socket, FrameKind::Pong).0);
    assert!(h.advance(10_000).iter().all(|c| !matches!(c, Command::Close { .. })));
    h.advance(15_000);
    let out = h.advance(10_000);
    assert_eq!(h.socket(socket).state, SocketState::Closed { code: 1000, reason: "Pong timeout - client initiated close".into() });
    assert_eq!(events(&out), vec![LinkEvent::Close(1000)]);
    assert_eq!(statuses(&out), vec![LinkStatus::Reconnecting]);
    assert_eq!(delays(&out, TimerKind::Backoff), vec![1_000]);
    assert!(h.feed(Input::Closed { socket, code: 1006, reason: "", was_clean: false }).is_empty(), "late close of a detached socket is ignored");
}

#[test]
fn recent_data_or_reported_activity_suppresses_the_pong_timeout() {
    for activity in [true, false] {
        let mut h = Harness::connected();
        let socket = h.last();
        h.advance(30_000);
        if activity {
            h.feed(Input::DataActivity);
        } else {
            assert!(h.frame(socket, FrameKind::Data).0);
        }
        h.advance(5_000);
        assert_eq!(h.socket(socket).state, SocketState::Open);
        assert_eq!(h.machine.open_socket(), Some(socket));
    }
}

#[test]
fn repeated_abnormal_closures_check_the_session_and_a_signed_out_answer_is_terminal() {
    let mut h = Harness::connected();
    h.close_last(1006, "", false);
    let mut all = Vec::new();
    for _ in 0..3 {
        all.extend(h.advance(5_000));
        all.extend(h.answer_refresh(RefreshOutcome::Ready, true));
        all.extend(h.close_last(1006, "", false));
    }
    assert_eq!(refresh_reasons(&all).last(), Some(&RefreshReason::AbnormalClosures));
    let out = h.answer_refresh(RefreshOutcome::SignedOut, false);
    assert_eq!(h.machine.error(), Some("Authentication failed. Please log in again."));
    assert_eq!(events(&out), vec![LinkEvent::AuthError(Some("Session expired or invalid token".into()))]);
    for input in [Input::Online, Input::NetworkChanged, Input::Resumed(ResumeSource::PageShow)] {
        assert_eq!(opens(&h.feed(input)), 0, "auth failure is sticky against automatic events");
    }
    assert_eq!(opens(&h.advance(120_000)), 0);
    let out = h.feed(Input::Retry);
    assert_eq!(refresh_reasons(&out), vec![RefreshReason::MissingToken], "explicit retry leaves the auth failure");
}

#[test]
fn auth_related_abnormal_close_refreshes_once_and_reuses_that_token() {
    let mut h = Harness::connected();
    let out = h.close_last(1006, "403 Forbidden", false);
    assert_eq!(refresh_reasons(&out), vec![RefreshReason::AuthRelatedClose]);
    let out = h.answer_refresh(RefreshOutcome::Ready, true);
    assert_eq!(delays(&out, TimerKind::Backoff), vec![1_000]);
    let out = h.advance(1_000);
    assert_eq!(opens(&out), 1);
    assert!(refresh_reasons(&out).is_empty());
}

#[test]
fn policy_close_refreshes_the_ws_token_once_then_a_second_policy_close_is_terminal() {
    let mut h = Harness::connected();
    let out = h.close_last(1008, "", true);
    assert_eq!(events(&out), vec![LinkEvent::Close(1008)]);
    assert_eq!(refresh_reasons(&out), vec![RefreshReason::PolicyClose]);
    let out = h.answer_refresh(RefreshOutcome::Ready, true);
    assert_eq!(opens(&out), 1, "fresh token reconnects without backoff");
    assert!(delays(&out, TimerKind::Backoff).is_empty());
    h.open_last();
    let out = h.close_last(1008, "", true);
    assert!(refresh_reasons(&out).is_empty());
    assert_eq!(h.machine.error(), Some("Connection closed due to policy violation."));
    assert!(events(&out).contains(&LinkEvent::AuthError(Some("policy_violation".into()))));
    assert_eq!(opens(&h.feed(Input::Online)), 0);
}

#[test]
fn a_healthy_pong_restores_the_policy_retry() {
    let mut h = Harness::connected();
    h.close_last(1008, "", true);
    h.answer_refresh(RefreshOutcome::Ready, true);
    h.open_last();
    let socket = h.last();
    h.frame(socket, FrameKind::Pong);
    let out = h.close_last(1008, "", true);
    assert_eq!(refresh_reasons(&out), vec![RefreshReason::PolicyClose]);
}

#[test]
fn policy_close_requiring_reauth_never_reconnects() {
    for (reason, kind) in [("2FA required", ReAuthKind::TwoFactor), ("Passkey required", ReAuthKind::Passkey)] {
        let mut h = Harness::connected();
        let out = h.close_last(1008, reason, true);
        assert!(refresh_reasons(&out).is_empty());
        assert!(events(&out).contains(&LinkEvent::ReAuthRequired(kind)));
        assert_eq!(h.machine.error(), Some(reason));
        assert_eq!(opens(&h.feed(Input::Online)), 0);
        assert_eq!(opens(&h.advance(60_000)), 0);
    }
}

#[test]
fn principal_mismatch_is_terminal_until_sign_out() {
    let mut h = Harness::connected();
    h.close_last(1000, "", true);
    h.advance(1_000);
    let out = h.answer_refresh(RefreshOutcome::PrincipalMismatch, true);
    assert_eq!(opens(&out), 0);
    assert_eq!(h.machine.error(), Some("session_principal_mismatch"));
    assert!(events(&out).contains(&LinkEvent::AuthError(Some("session_principal_mismatch".into()))));
    assert!(h.machine.owner_mismatch());
    let mut all = Vec::new();
    for input in [
        Input::Online,
        Input::NetworkChanged,
        Input::Resumed(ResumeSource::VisibilityChange),
        Input::Retry,
        Input::ForceReconnect("stalled"),
        Input::Session { authenticated: true, logging_out: false, has_token: true },
    ] {
        all.extend(h.feed(input));
    }
    assert_eq!(h.feed(Input::Connect), vec![Command::Settle(Err(Refusal::OwnerMismatch))]);
    all.extend(h.advance(600_000));
    assert_eq!(opens(&all), 0);
    assert!(refresh_reasons(&all).is_empty());
    let out = h.feed(Input::Session { authenticated: false, logging_out: false, has_token: false });
    assert_eq!(statuses(&out), vec![LinkStatus::Disconnected]);
    let out = h.sign_in(true);
    assert_eq!(opens(&out), 1, "a new sign-in starts a new link");
}

#[test]
fn force_reconnect_detaches_the_old_socket_and_ignores_its_events() {
    let mut h = Harness::connected();
    let old = h.last();
    let out = h.feed(Input::ForceReconnect("receipt timeout"));
    assert!(has(&out, &Command::Close { socket: old, code: 1000, reason: "receipt timeout".into() }));
    assert_eq!(statuses(&out), vec![LinkStatus::Reconnecting, LinkStatus::Connecting]);
    h.answer_refresh(RefreshOutcome::Ready, true);
    let new = h.last();
    assert_ne!(old, new);
    assert!(h.feed(Input::Closed { socket: old, code: 1006, reason: "", was_clean: false }).is_empty());
    assert_eq!(h.feed(Input::Opened(old)), vec![Command::Close { socket: old, code: 1000, reason: "Superseded by new connection attempt".into() }]);
    assert!(!h.frame(old, FrameKind::Data).0);
    h.open_last();
    assert_eq!(h.machine.open_socket(), Some(new));
    let long = "x".repeat(300);
    let out = h.feed(Input::ForceReconnect(&long));
    assert!(out.iter().any(|c| matches!(c, Command::Close { reason, .. } if reason.len() == 120)));
}

#[test]
fn online_or_resume_during_backoff_reconnects_at_once_with_reset_attempts() {
    for input in [Input::Online, Input::NetworkChanged, Input::Resumed(ResumeSource::PageShow)] {
        let mut h = Harness::connected();
        h.close_last(1000, "", true);
        h.advance(1_000);
        h.fail_attempt();
        assert_eq!(h.machine.attempts(), 2);
        let out = h.feed(input);
        assert_eq!(h.machine.attempts(), 0);
        assert!(statuses(&out).contains(&LinkStatus::Connecting));
        assert_eq!(refresh_reasons(&out), vec![RefreshReason::Reconnect]);
        // The superseded backoff timer later fires and is ignored.
        h.answer_refresh(RefreshOutcome::Ready, true);
        h.open_last();
        assert_eq!(opens(&h.advance(10_000)), 0);
    }
}

#[test]
fn resume_on_a_live_socket_sends_a_liveness_ping_with_pong_deadline() {
    let mut h = Harness::connected();
    let socket = h.last();
    let out = h.feed(Input::Resumed(ResumeSource::VisibilityChange));
    assert_eq!(events(&out), vec![LinkEvent::Resuming]);
    assert_eq!(h.socket(socket).sent.last().map(String::as_str), Some("ping"));
    assert_eq!(delays(&out, TimerKind::Pong), vec![10_000]);
    h.advance(10_000);
    assert!(matches!(h.socket(socket).state, SocketState::Closed { .. }), "dead socket after wake is replaced");
}

#[test]
fn network_change_before_any_session_is_ignored() {
    let mut h = Harness::new();
    assert!(h.feed(Input::NetworkChanged).is_empty());
    assert!(h.feed(Input::Online).is_empty());
    assert!(h.feed(Input::Resumed(ResumeSource::PageShow)).is_empty());
}

#[test]
fn disconnect_rejects_the_pending_attempt_and_ignores_its_refresh() {
    let mut h = Harness::new();
    h.sign_in(false);
    let out = h.feed(Input::Disconnect);
    assert!(has(&out, &Command::Settle(Err(Refusal::ManualDisconnect))));
    assert_eq!(statuses(&out), vec![LinkStatus::Disconnected]);
    assert!(h.answer_refresh(RefreshOutcome::Ready, true).is_empty());
}

#[test]
fn sign_out_closes_the_open_socket() {
    let mut h = Harness::connected();
    let socket = h.last();
    let out = h.feed(Input::Session { authenticated: false, logging_out: false, has_token: false });
    assert!(has(&out, &Command::Close { socket, code: 1000, reason: "Client initiated disconnect".into() }));
    assert_eq!(statuses(&out), vec![LinkStatus::Disconnected]);
    assert_eq!(opens(&h.advance(120_000)), 0);
}

#[test]
fn logout_in_progress_refuses_to_connect() {
    let mut h = Harness::new();
    let out = h.feed(Input::Session { authenticated: true, logging_out: true, has_token: true });
    assert_eq!(out, vec![Command::Settle(Err(Refusal::LogoutInProgress))]);
    assert_eq!(h.feed(Input::Connect), vec![Command::Settle(Err(Refusal::LogoutInProgress))]);
}

#[test]
fn server_auth_error_frame_closes_with_policy_code_and_is_not_dispatched() {
    let mut h = Harness::connected();
    let socket = h.last();
    let (admitted, out) = h.frame(socket, FrameKind::AuthError("Session expired"));
    assert!(!admitted);
    assert!(has(&out, &Command::Close { socket, code: 1008, reason: "Authentication failed".into() }));
    assert_eq!(h.machine.error(), Some("Session expired"));
    assert_eq!(events(&out), vec![LinkEvent::AuthError(Some("Session expired".into()))]);
    assert!(h.feed(Input::Closed { socket, code: 1008, reason: "", was_clean: true }).is_empty());
    assert_eq!(opens(&h.feed(Input::Online)), 0);
}

#[test]
fn server_restarting_frame_is_dispatched_and_announced() {
    let mut h = Harness::connected();
    let (admitted, out) = h.frame(h.last(), FrameKind::ServerRestarting);
    assert!(admitted);
    assert_eq!(events(&out), vec![LinkEvent::ServerRestarting]);
}

#[test]
fn foreground_changes_are_sent_only_on_an_open_socket_and_seed_the_open_lifecycle() {
    let mut h = Harness::new();
    h.sign_in(true);
    let out = h.feed(Input::Foreground { foreground: true, source: LifecycleSource::Focus });
    assert!(out.is_empty());
    h.open_last();
    let socket = h.last();
    h.feed(Input::Foreground { foreground: false, source: LifecycleSource::Blur });
    assert_eq!(h.socket(socket).sent, vec!["lifecycle:open:true", "lifecycle:blur:false"]);
}

#[test]
fn every_connect_caller_is_settled_exactly_once() {
    let mut h = Harness::new();
    h.sign_in(true);
    assert!(h.feed(Input::Connect).is_empty(), "joins the running attempt");
    let socket = h.last();
    let out = h.feed(Input::Errored(socket));
    assert_eq!(out, vec![Command::Emit(LinkEvent::Error), Command::Settle(Err(Refusal::SocketError))]);
    assert!(h.feed(Input::Connect).is_empty());
    let out = h.close_last(1006, "", false);
    let settles: Vec<_> = out.iter().filter(|c| matches!(c, Command::Settle(_))).collect();
    assert_eq!(settles, vec![&Command::Settle(Err(Refusal::Closed(1006)))]);
    h.advance(1_000);
    h.answer_refresh(RefreshOutcome::Ready, true);
    let out = h.open_last();
    assert!(has(&out, &Command::Settle(Ok(()))));
    assert_eq!(h.feed(Input::Connect), vec![Command::Settle(Ok(()))]);
}

#[test]
fn connect_during_backoff_starts_an_attempt_immediately() {
    let mut h = Harness::connected();
    h.close_last(1000, "", true);
    let out = h.feed(Input::Connect);
    assert_eq!(refresh_reasons(&out), vec![RefreshReason::Reconnect]);
    h.answer_refresh(RefreshOutcome::Ready, true);
    h.open_last();
    assert_eq!(opens(&h.advance(5_000)), 0, "the replaced backoff timer is inert");
}
