// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;
use openmates_sdk::client::{SendConsentPolicy, SendOutcome};
use serde_json::json;
const CHAT: &str = "11111111-1111-4111-8111-111111111111";
const PROJECT: &str = "22222222-2222-4222-8222-222222222222";
fn invocation(extra: &[(&str, Value)]) -> Invocation {
    let mut flags = std::collections::BTreeMap::from([
        ("goal".into(), json!("  private durable goal  ")),
        ("project".into(), json!("project-selector")),
        ("json".into(), json!(true)),
    ]);
    flags.extend(extra.iter().map(|(k, v)| ((*k).into(), v.clone())));
    Invocation {
        path: vec!["chat".into()],
        positionals: vec![],
        flags,
    }
}
fn outcome(status: &str) -> SendOutcome {
    serde_json::from_value(json!({"status":status,"chatId":CHAT,"messageId":null,
        "userMessageId":"user-id","assistant":"","category":null,"modelName":null,"mateName":null,
        "followUpSuggestions":[],"taskProposals":[],"taskUpdateProposals":[],"taskEvents":[],
        "pendingTaskUpdateJobs":[{"job_id":"pending"}],"subChatEvents":[],"appSettingsMemoryRequests":[],
        "tokenUsage":null,"promptBudget":null})).unwrap()
}
struct PlanAckGate {
    entered: tokio::sync::oneshot::Sender<()>,
    acknowledgement: tokio::sync::oneshot::Receiver<()>,
}
#[derive(Default)]
struct Fake {
    calls: Vec<&'static str>,
    sent: Option<Invocation>,
    plan: Option<PlanCreate>,
    status: Option<&'static str>,
    denied: bool,
    reject_project: bool,
    plan_failure: bool,
    send_failure: bool,
    final_content: bool,
    cancel_after_send: Option<CancellationToken>,
    plan_ack_gate: Option<PlanAckGate>,
}
impl Backend for Fake {
    fn admission(&self) -> Result<(), Error> {
        if self.denied {
            Err(Error::Authentication)
        } else {
            Ok(())
        }
    }
    async fn project(&mut self, _: &str) -> Result<String, Error> {
        self.calls.push("project");
        if self.reject_project {
            Err(Error::Forbidden)
        } else {
            Ok(PROJECT.into())
        }
    }
    async fn send(
        &mut self,
        i: &Invocation,
        _: CancellationToken,
    ) -> Result<send::ObservedSend, CliError> {
        self.calls.push("send");
        self.sent = Some(Invocation {
            path: i.path.clone(),
            positionals: i.positionals.clone(),
            flags: i.flags.clone(),
        });
        if self.send_failure {
            return Err(CliError::PendingTurn {
                chat_id: CHAT.into(),
                message_id: "human".into(),
                admitted: false,
                source: Error::Cancelled,
            });
        }
        if let Some(c) = &self.cancel_after_send {
            c.cancel();
        }
        let mut observed = outcome(self.status.unwrap_or("completed"));
        if self.final_content {
            observed.message_id = Some("assistant".into());
            observed.assistant = "private final fallback response".into();
        }
        Ok(send::ObservedSend::synthetic(observed))
    }
    async fn plan(&mut self, input: PlanCreate) -> Result<Value, Error> {
        self.calls.push("plan");
        self.plan = Some(input);
        if let Some(gate) = self.plan_ack_gate.take() {
            let _ = gate.entered.send(());
            gate.acknowledgement.await.map_err(|_| Error::Offline)?;
        }
        if self.plan_failure {
            Err(Error::Offline)
        } else {
            Ok(
                json!({"plan_id":"plan","short_id":"PLAN-1","status":"draft","goal":"private durable goal"}),
            )
        }
    }
}
#[tokio::test]
async fn goal_defaults_and_overrides_are_one_send_then_one_plan_and_one_json_object() {
    for (message, title, status) in [
        (None, None, None),
        (Some("  custom message  "), Some(" title "), Some("active")),
        (Some("  "), Some("  "), None),
    ] {
        let mut i = invocation(&[]);
        for (key, value) in [("message", message), ("title", title), ("status", status)] {
            if let Some(value) = value {
                i.flags.insert(key.into(), json!(value));
            }
        }
        let mut backend = Fake::default();
        let output = execute_backend(&i, &mut backend, CancellationToken::new())
            .await
            .unwrap_or_else(|e| panic!("{e}"));
        assert_eq!(backend.calls, ["project", "send", "plan"]);
        let sent = backend.sent.as_ref().unwrap();
        assert_eq!(sent.command_path(), "chats new");
        assert_eq!(
            sent.positionals,
            [message
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .unwrap_or("private durable goal")]
        );
        assert!(!sent.has("goal") && !sent.has("project") && !sent.has("chat"));
        let plan = backend.plan.as_ref().unwrap();
        assert_eq!(plan.goal, "private durable goal");
        assert_eq!(
            plan.title,
            title
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .unwrap_or("private durable goal")
        );
        assert_eq!(plan.status.as_deref(), status);
        assert_eq!(plan.primary_chat_id.as_deref(), Some(CHAT));
        assert_eq!(plan.linked_project_ids, [PROJECT]);
        let mut expected =
            send::outcome_json(&outcome("completed")).unwrap_or_else(|e| panic!("{e}"));
        expected["chat_id"] = json!(CHAT);
        expected["plan"] = json!({"plan_id":"plan","short_id":"PLAN-1","status":"draft","goal":"private durable goal"});
        assert_eq!(
            serde_json::from_str::<Value>(&output.stdout).unwrap(),
            expected
        );
        assert!(output.stderr.is_empty());
    }
}
#[tokio::test]
async fn invalid_admission_and_project_failures_never_send() {
    for flags in [
        vec![("goal", json!(" "))],
        vec![("project", json!(""))],
        vec![("api-key", json!("never-log-this-key"))],
        vec![("accept-task-proposals", json!(true))],
        vec![("status", json!("invalid-private-status"))],
        vec![("personal", json!(true)), ("team", json!("team"))],
        vec![("response-timeout-seconds", json!("0"))],
    ] {
        let i = invocation(&flags);
        let mut backend = Fake::default();
        let result = execute_backend(&i, &mut backend, CancellationToken::new()).await;
        assert!(result.is_err());
        assert!(backend.calls.is_empty());
        if let Err(e) = result {
            assert!(!e.to_string().contains("never-log-this-key"));
            assert!(!e.to_string().contains("invalid-private-status"));
        }
    }
    for denied in [false, true] {
        let mut backend = Fake {
            denied,
            reject_project: true,
            ..Default::default()
        };
        assert!(
            execute_backend(&invocation(&[]), &mut backend, CancellationToken::new())
                .await
                .is_err()
        );
        assert!(!backend.calls.contains(&"send"));
    }
    let mut plain = invocation(&[]);
    plain.flags.remove("goal");
    plain.positionals.push("hello".into());
    assert!(!supported(&plain));
    assert!(arguments(&plain).is_err());
}
#[tokio::test]
async fn queued_and_waiting_saved_chats_attach_plan_without_another_send() {
    for status in ["queued", "waiting_for_user"] {
        let mut backend = Fake {
            status: Some(status),
            ..Default::default()
        };
        let output = execute_backend(&invocation(&[]), &mut backend, CancellationToken::new())
            .await
            .unwrap_or_else(|e| panic!("{e}"));
        assert_eq!(backend.calls, ["project", "send", "plan"]);
        let value: Value = serde_json::from_str(&output.stdout).unwrap();
        assert_eq!(value["status"], status);
        assert_eq!(value["chat_id"], CHAT);
        assert!(value["plan"].is_object());
        assert_eq!(
            value["pendingTaskUpdateJobs"],
            json!([{"job_id":"pending"}])
        );
    }
}
#[tokio::test]
async fn plan_failure_and_cancel_preserve_known_chat_and_never_repeat_send() {
    for cancel_after_send in [false, true] {
        let cancel = CancellationToken::new();
        let mut backend = Fake {
            plan_failure: true,
            cancel_after_send: cancel_after_send.then(|| cancel.clone()),
            ..Default::default()
        };
        let error = match execute_backend(&invocation(&[]), &mut backend, cancel).await {
            Err(e) => e,
            Ok(_) => panic!("expected recovery"),
        };
        assert_eq!(backend.calls.iter().filter(|v| **v == "send").count(), 1);
        assert_eq!(
            backend.calls.iter().filter(|v| **v == "plan").count(),
            usize::from(!cancel_after_send)
        );
        assert_eq!(error.structured_error()["error"]["chat_id"], CHAT);
        assert_eq!(error.structured_error()["error"]["recovery_required"], true);
        if cancel_after_send {
            assert_eq!(error.exit_code(), 130);
        }
        assert!(!error.to_string().contains("private durable goal"));
    }
    let mut backend = Fake {
        send_failure: true,
        ..Default::default()
    };
    let error =
        match execute_backend(&invocation(&[]), &mut backend, CancellationToken::new()).await {
            Err(e) => e,
            Ok(_) => panic!("expected pending"),
        };
    assert!(matches!(
        error,
        CliError::PendingTurn {
            admitted: false,
            ..
        }
    ));
    assert_eq!(error.exit_code(), 130);
    assert_eq!(backend.calls, ["project", "send"]);
}
#[test]
fn privacy_consent_timeout_and_ignored_summary_reuse_normal_saved_send_options() {
    let args = arguments(&invocation(&[
        ("auto-approve", json!(true)),
        ("auto-approve-memories", json!(true)),
        ("no-pii-detection", json!(true)),
        ("response-timeout-seconds", json!("12")),
        ("summary", json!("ignored-summary")),
        ("accept-task-proposals", json!(false)),
    ]))
    .unwrap_or_else(|e| panic!("{e}"));
    let options = send::saved_options_for_test(&args.send).unwrap_or_else(|e| panic!("{e}"));
    assert!(!options.incognito && !options.pii_detection && options.task_update_jobs);
    assert_eq!(options.response_timeout_ms, Some(12000));
    assert!(
        options.sub_chat_consent == SendConsentPolicy::ApproveRequested
            && options.memory_consent == SendConsentPolicy::ApproveRequested
    );
    assert!(!args.send.has("summary"));
    assert_eq!(args.send.positionals, ["private durable goal"]);
}
#[test]
fn paired_cookie_and_team_scope_are_checked_before_goal_chat_inference() {
    let mut missing = Client::new("http://127.0.0.1:1", None).unwrap();
    assert!(matches!(
        Cookie(&mut missing).admission(),
        Err(Error::Authentication)
    ));
    for (team, expiry) in [(None, Some(1)), (Some("team".into()), None), (None, None)] {
        let session = openmates_sdk::Session {
            api_url: "http://127.0.0.1:1".into(),
            session_id: "synthetic".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: expiry,
            active_team_id: team.clone(),
        };
        if expiry.is_some() {
            assert!(matches!(
                Client::new("http://127.0.0.1:1", Some(session)),
                Err(Error::Expired)
            ));
            continue;
        }
        let mut client = Client::new("http://127.0.0.1:1", Some(session)).unwrap();
        let result = Cookie(&mut client).admission();
        if team.is_some() {
            assert!(matches!(
                result,
                Err(Error::Unavailable {
                    code: "team_plan_keys_unavailable",
                    ..
                })
            ));
        } else {
            assert!(result.is_ok());
        }
    }
}
#[tokio::test]
async fn cancelled_preflight_never_resolves_projects_and_aliases_deduplicate_before_plan() {
    let cancel = CancellationToken::new();
    cancel.cancel();
    let mut backend = Fake::default();
    let result = execute_backend(&invocation(&[]), &mut backend, cancel).await;
    assert!(matches!(result, Err(CliError::Client(Error::Cancelled))));
    assert!(backend.calls.is_empty());
    let mut backend = Fake::default();
    let result = execute_backend(
        &invocation(&[
            ("project", json!(["first", "alias"])),
            ("projects", json!("third, first")),
        ]),
        &mut backend,
        CancellationToken::new(),
    )
    .await;
    assert!(result.is_ok());
    assert_eq!(
        backend.calls,
        ["project", "project", "project", "send", "plan"]
    );
    assert_eq!(backend.plan.as_ref().unwrap().linked_project_ids, [PROJECT]);
}
#[test]
fn valid_interactive_question_keeps_legacy_waiting_envelope_and_human_continuation_is_safe() {
    let mut waiting = outcome("waiting_for_user");
    waiting.message_id = Some("assistant".into());
    waiting.assistant =
        "```interactive_question\n{\"id\":\"q\",\"type\":\"rating\",\"question\":\"Rate\"}\n```"
            .into();
    let output = json_result(&waiting, json!({"plan_id":"plan"})).unwrap_or_else(|e| panic!("{e}"));
    let value: Value = serde_json::from_str(&output.stdout).unwrap();
    assert_eq!(
        value,
        json!({"status":"waiting_for_user","chat_id":CHAT,"message_id":"assistant","parent_id":CHAT,"question":{"id":"q","type":"rating","question":"Rate"},"plan":{"plan_id":"plan"}})
    );
}
#[test]
fn parser_dispatch_requires_goal_and_keeps_positional_chat_refused() {
    let parsed = super::super::parse_from([
        "openmates",
        "chat",
        "--goal",
        "goal",
        "--project",
        "project",
        "--summary",
        "ignored",
        "--personal",
        "--json",
    ])
    .unwrap_or_else(|e| panic!("{e}"));
    let i = parsed.invocation.unwrap();
    assert!(supported(&i));
    assert!(arguments(&i).is_ok());
    assert!(super::super::requirements(&i).authenticated);
    assert!(super::super::execute_public(&i).is_none());
    let plain = Invocation {
        path: vec!["chat".into()],
        positionals: vec!["hello".into()],
        flags: Default::default(),
    };
    assert!(matches!(
        super::super::execute_public(&plain),
        Some(Err(CliError::Unsupported { .. }))
    ));
}
#[tokio::test]
async fn human_output_preserves_chat_footer_and_adds_plan_and_history_continuation() {
    let mut backend = Fake::default();
    let output = execute_backend(
        &invocation(&[("json", json!(false))]),
        &mut backend,
        CancellationToken::new(),
    )
    .await
    .unwrap_or_else(|e| panic!("{e}"));
    assert!(output.stdout.contains(&format!("Chat: {CHAT}")));
    assert!(output.stdout.contains("Plan attached: PLAN-1 (draft)"));
    assert!(output.stdout.contains("openmates plans show PLAN-1"));
    assert!(
        output
            .stdout
            .contains("openmates chats send --chat 11111111")
    );
    assert!(!output.stdout.contains("private durable goal"));
    assert!(output.stderr.is_empty());
}

#[tokio::test]
async fn cancel_while_plan_acknowledgement_is_gated_returns_known_chat_without_retry() {
    let (entered_tx, entered_rx) = tokio::sync::oneshot::channel();
    let (ack_tx, ack_rx) = tokio::sync::oneshot::channel();
    let cancel = CancellationToken::new();
    let mut backend = Fake {
        plan_ack_gate: Some(PlanAckGate {
            entered: entered_tx,
            acknowledgement: ack_rx,
        }),
        ..Default::default()
    };
    let i = invocation(&[]);
    let error = {
        let operation = execute_backend(&i, &mut backend, cancel.clone());
        tokio::pin!(operation);
        // Poll the real orchestration through send and into the pending Plan
        // acknowledgement. No sleeps or simulated cancellation result oracle.
        tokio::time::timeout(std::time::Duration::from_secs(1), async {
            tokio::select! {
                result = &mut operation => panic!("goal returned before gated Plan acknowledgement: {}", result.is_ok()),
                entered = entered_rx => entered.expect("Plan mutation entered"),
            }
        }).await.expect("Plan mutation starts within bound");
        assert!(
            !ack_tx.is_closed(),
            "Plan ACK remains pending before cancellation"
        );
        cancel.cancel();
        match tokio::time::timeout(std::time::Duration::from_millis(250), &mut operation)
            .await
            .expect("local cancellation returns before outer two-second grace")
        {
            Err(error) => error,
            Ok(_) => panic!("cancelled pending Plan cannot return success"),
        }
    };
    assert_eq!(error.exit_code(), 130);
    assert!(
        matches!(&error, CliError::RecoveryRequired { chat_id: Some(id), source: Error::Cancelled } if id == CHAT)
    );
    let value = error.structured_error();
    assert_eq!(value["error"]["chat_id"], CHAT);
    assert_eq!(value["error"]["recovery_required"], true);
    assert!(!error.to_string().contains("private durable goal"));
    assert_eq!(backend.calls, ["project", "send", "plan"]);
    assert_eq!(
        backend.plan.as_ref().unwrap().primary_chat_id.as_deref(),
        Some(CHAT)
    );
    assert!(
        ack_tx.is_closed(),
        "pending request future dropped; remote acceptance remains uncertain"
    );
    // ack_tx was never released: completion did not depend on server ACK, and
    // the adapter never attempted another send or Plan mutation.
}

#[tokio::test]
async fn final_writer_failure_after_plan_preserves_saved_chat_recovery() {
    struct BrokenWriter;
    impl std::io::Write for BrokenWriter {
        fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
            Err(std::io::ErrorKind::BrokenPipe.into())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Err(std::io::ErrorKind::BrokenPipe.into())
        }
    }
    let mut backend = Fake {
        final_content: true,
        ..Default::default()
    };
    let i = invocation(&[("json", json!(false))]);
    let error = match execute_with_writer(
        &i,
        &mut backend,
        CancellationToken::new(),
        &mut BrokenWriter,
    )
    .await
    {
        Err(error) => error,
        Ok(_) => panic!("failed final terminal write must not report success"),
    };
    assert!(
        matches!(&error, CliError::RecoveryRequired { chat_id: Some(id), source: Error::Io } if id == CHAT)
    );
    assert_eq!(error.structured_error()["error"]["chat_id"], CHAT);
    assert_eq!(error.structured_error()["error"]["recovery_required"], true);
    assert_eq!(backend.calls, ["project", "send", "plan"]);
    assert!(
        !error
            .to_string()
            .contains("private final fallback response")
    );
}
