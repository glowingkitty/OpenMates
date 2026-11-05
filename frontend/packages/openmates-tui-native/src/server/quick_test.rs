//! Paid, explicitly confirmed application checks for one self-host installation.
use super::*;
use openmates_sdk::{
    Client,
    model::{Mutation, Workspace},
};
use tokio_util::sync::CancellationToken;
const PROMPT: &str = "Reply with exactly: server quick test passed";
const EXPECTED: &str = "server quick test passed";
fn origin(raw: &str) -> Result<String> {
    let url = url::Url::parse(raw).map_err(|_| Error::Invalid("Self-host API URL is invalid."))?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(Error::Invalid("Self-host API URL is invalid."));
    }
    Ok(url.origin().ascii_serialization())
}
fn eligible(expected: &str, session: Option<&crate::storage::Session>) -> Result<()> {
    let session = session.ok_or(Error::Authentication)?;
    if session.is_expired() {
        return Err(Error::Expired);
    }
    if origin(&session.api_url)? != origin(expected)? {
        return Err(Error::Invalid(
            "Sign in to the selected self-host instance before running its quick test.",
        ));
    }
    Ok(())
}
trait Checks {
    async fn create(&mut self, id: &str, cancel: CancellationToken) -> Result<()>;
    async fn reload(&mut self, id: &str) -> Result<()>;
    async fn skill(&mut self, app: &str, skill: &str, input: Value) -> Result<Value>;
    async fn cleanup(&mut self, id: &str, cancel: CancellationToken) -> Result<()>;
}
struct Native<'a>(&'a mut Client);
impl Checks for Native<'_> {
    async fn create(&mut self, id: &str, cancel: CancellationToken) -> Result<()> {
        self.0.save_draft(Some(id), PROMPT).await?;
        let (sender, mut receiver) = tokio::sync::mpsc::channel(64);
        let drain = tokio::spawn(async move { while receiver.recv().await.is_some() {} });
        let result = self.0.send_message(Some(id), PROMPT, sender, cancel).await;
        drain.abort();
        let chat = result?;
        if chat.id != id
            || !chat.messages.iter().any(|m| {
                m.role == "assistant"
                    && !m.id.is_empty()
                    && m.content.trim().eq_ignore_ascii_case(EXPECTED)
            })
        {
            return Err(Error::Protocol);
        }
        Ok(())
    }
    async fn reload(&mut self, id: &str) -> Result<()> {
        let chat = self.0.open_chat(id).await?;
        if chat.id != id
            || !chat.messages.iter().any(|m| m.role == "user")
            || !chat.messages.iter().any(|m| m.role == "assistant")
        {
            return Err(Error::Protocol);
        }
        Ok(())
    }
    async fn skill(&mut self, app: &str, skill: &str, input: Value) -> Result<Value> {
        let item = self
            .0
            .mutate(Mutation::Create {
                workspace: Workspace::Apps,
                fields: json!({"app":app,"skill":skill,"input":input}),
            })
            .await?
            .ok_or(Error::Protocol)?;
        Ok(item.fields["content"].clone())
    }
    async fn cleanup(&mut self, id: &str, cancel: CancellationToken) -> Result<()> {
        // Cleanup is the only operation allowed after caller cancellation.
        // PersonalScope restores the supplied caller token even on future drop.
        self.0.set_operation_cancel(cancel);
        self.0
            .mutate(Mutation::Delete {
                workspace: Workspace::Chats,
                id: id.into(),
            })
            .await?;
        Ok(())
    }
}
fn math(value: &Value) -> bool {
    match value {
        Value::Number(n) => n.as_i64() == Some(4),
        Value::String(s) => s == "4",
        Value::Array(a) => a.iter().any(math),
        Value::Object(o) => o.values().any(math),
        _ => false,
    }
}
fn web(value: &Value) -> bool {
    match value {
        Value::Array(a) => a.iter().any(web),
        Value::Object(o) => {
            o.get("results").and_then(Value::as_array).is_some_and(|a| {
                a.iter()
                    .any(|v| v["title"].is_string() && v["url"].is_string())
            }) || o.values().any(web)
        }
        _ => false,
    }
}
fn check(
    checks: &mut Vec<Value>,
    id: &str,
    started: std::time::Instant,
    passed: bool,
    reason: &str,
) {
    let mut check = json!({"id":id,"status":if passed{"passed"}else{"failed"},"duration_ms":started.elapsed().as_millis().min(u64::MAX as u128)as u64});
    if !passed {
        check["sanitized_reason"] = json!(reason)
    }
    checks.push(check);
}
async fn bounded<T>(
    future: impl std::future::Future<Output = Result<T>>,
    cancel: &CancellationToken,
    seconds: u64,
) -> Result<T> {
    tokio::select! {biased;_ = cancel.cancelled()=>Err(Error::Cancelled),result=tokio::time::timeout(std::time::Duration::from_secs(seconds),future)=>result.unwrap_or(Err(Error::Offline))}
}
async fn run(client: &mut impl Checks, cancel: &CancellationToken, id: &str) -> Result<Value> {
    let mut checks = vec![json!({"id":"account.session","status":"passed","duration_ms":0})];
    let may_exist = !cancel.is_cancelled();
    let start = std::time::Instant::now();
    let send_cancel = cancel.child_token();
    let result = bounded(client.create(id, send_cancel.clone()), cancel, 120).await;
    send_cancel.cancel();
    check(
        &mut checks,
        "chat.create",
        start,
        result.is_ok(),
        if cancel.is_cancelled() {
            "cancelled"
        } else {
            "chat_create_failed"
        },
    );
    let start = std::time::Instant::now();
    let result = bounded(client.reload(id), cancel, 60).await;
    check(
        &mut checks,
        "chat.reload",
        start,
        result.is_ok(),
        if cancel.is_cancelled() {
            "cancelled"
        } else {
            "chat_reload_failed"
        },
    );
    let start = std::time::Instant::now();
    let mut result = bounded(
        client.skill(
            "math",
            "calculate",
            json!({"expression":"2 + 2","title":"Server quick test"}),
        ),
        cancel,
        60,
    )
    .await;
    check(
        &mut checks,
        "app.math.calculate",
        start,
        matches!(&result,Ok(value)if math(value)),
        if cancel.is_cancelled() {
            "cancelled"
        } else {
            "math_calculate_failed"
        },
    );
    if let Ok(value) = &mut result {
        local_models::erase(value)
    }
    let start = std::time::Instant::now();
    let mut result = bounded(
        client.skill(
            "web",
            "search",
            json!({"requests":[{"id":"quick","query":"site:openmates.org OpenMates","count":1}]}),
        ),
        cancel,
        60,
    )
    .await;
    check(
        &mut checks,
        "app.web.search",
        start,
        matches!(&result,Ok(value)if web(value)),
        if cancel.is_cancelled() {
            "cancelled"
        } else {
            "web_search_failed"
        },
    );
    if let Ok(value) = &mut result {
        local_models::erase(value)
    }
    let start = std::time::Instant::now();
    let cleanup_cancel = CancellationToken::new();
    let cleaned = if may_exist {
        bounded(
            client.cleanup(id, cleanup_cancel.clone()),
            &cleanup_cancel,
            5,
        )
        .await
        .is_ok()
    } else {
        true
    };
    cleanup_cancel.cancel();
    check(
        &mut checks,
        "chat.cleanup",
        start,
        cleaned,
        "chat_cleanup_failed",
    );
    let mut outcome = json!({"status":if checks.iter().all(|c|c["status"]=="passed"){"passed"}else{"failed"},"cancelled":cancel.is_cancelled(),"completed_at":notifications::timestamp()?,"cleanupPending":!cleaned,"checks":checks});
    if !cleaned {
        outcome["chatId"] = json!(id)
    }
    Ok(outcome)
}
struct PersonalScope<'a> {
    client: &'a mut Client,
    team: Option<String>,
    caller: CancellationToken,
    restored: bool,
    pending_chat: Option<String>,
}
impl<'a> PersonalScope<'a> {
    fn new(client: &'a mut Client, caller: &CancellationToken) -> Result<Self> {
        let team = client.session().and_then(|s| s.active_team_id.clone());
        // set_team cancels the SDK's prior operation token. Protect the caller
        // with a child for this synchronous context transition, then rebind it.
        client.set_operation_cancel(caller.child_token());
        let selected = client.set_team(None);
        client.set_operation_cancel(caller.clone());
        selected?;
        Ok(Self {
            client,
            team,
            caller: caller.clone(),
            restored: false,
            pending_chat: None,
        })
    }
    fn restore(&mut self) -> Result<()> {
        self.client.set_operation_cancel(self.caller.child_token());
        let result = self.client.set_team(self.team.as_deref());
        self.client.set_operation_cancel(self.caller.clone());
        self.restored = true;
        result
    }
}
impl Drop for PersonalScope<'_> {
    fn drop(&mut self) {
        if !self.restored {
            let _ = self.restore();
        }
        if let Some(id) = &self.pending_chat {
            eprintln!("Quick test cleanup pending for temporary chat {id}.");
        }
    }
}
/// The application supplies explicit credentials. The SDK never inherits them
/// from CLI storage, and host management itself remains authentication-free.
async fn acquire(
    flags: &BTreeMap<String, Value>,
    state_dir: &Path,
) -> Result<(Configuration, fs::Lock)> {
    validate_options("test", &[], flags)?;
    if !(boolean(flags, "quick") || boolean(flags, "quick-test")) {
        return Err(Error::Invalid(
            "Use server test --quick --confirm-spend-credits.",
        ));
    }
    if !boolean(flags, "confirm-spend-credits") || boolean(flags, "skip-quick-test") {
        return Err(Error::Invalid(
            "Authenticated quick tests require --confirm-spend-credits.",
        ));
    }
    let flags = SecretFlags(flags.clone());
    let state = state_dir.to_path_buf();
    let acquired = tokio::task::spawn_blocking(move || {
        let saved = config(&state)?;
        let selected = text(&flags, "path")
            .map(normalized_path)
            .transpose()?
            .or_else(|| saved.as_ref().map(|c| c.install_path.clone()))
            .unwrap_or(std::env::current_dir()?);
        let _scope = if saved.as_ref().is_some_and(|c| {
            c.install_path == selected && c.source_strategy.as_deref() == Some("working_tree")
        }) {
            Some(fs::source_scope(&selected)?)
        } else {
            None
        };
        let c = installation(&flags, &state)?;
        overlay::supported_action(&c, "test")?;
        let lock = fs::Lock::acquire(&c.install_path)?;
        Ok::<_, Error>((c, lock))
    })
    .await
    .map_err(|_| Error::Io)??;
    Ok(acquired)
}
fn non_core(c: &Configuration) -> Option<Value> {
    (c.server_role!="core").then(||json!({"command":"test","role":c.server_role,"quickTest":{"status":"not_run","reason":"non_core_role","checks":[]}}))
}
/// Resolve role and explicit spending policy before the application unlocks
/// credentials. The authenticated helper acquires and verifies the target again.
pub async fn quick_test_preflight(
    flags: &BTreeMap<String, Value>,
    state_dir: &Path,
) -> Result<Option<Value>> {
    let (c, _lock) = acquire(flags, state_dir).await?;
    Ok(non_core(&c))
}
pub async fn quick_test(
    client: &mut Client,
    flags: &BTreeMap<String, Value>,
    state_dir: &Path,
    cancel: &CancellationToken,
) -> Result<Value> {
    let (c, _lock) = acquire(flags, state_dir).await?;
    if let Some(outcome) = non_core(&c) {
        return Ok(outcome);
    }
    eligible(
        c.api_url.as_deref().unwrap_or("http://127.0.0.1:8000"),
        client.session(),
    )?;
    if cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    let mut scope = PersonalScope::new(client, cancel)?;
    let id = uuid::Uuid::new_v4().to_string();
    scope.pending_chat = Some(id.clone());
    let outcome = run(&mut Native(scope.client), cancel, &id).await?;
    if outcome["cleanupPending"] == false {
        scope.pending_chat = None;
    }
    scope.restore()?;
    Ok(json!({"command":"test","role":c.server_role,"quickTest":outcome}))
}
#[cfg(test)]
mod tests {
    use super::*;
    struct Fake {
        calls: Vec<String>,
        fail_create: bool,
        fail_cleanup: bool,
        id: Option<String>,
        cancel_after_create: Option<CancellationToken>,
    }
    impl Checks for Fake {
        async fn create(&mut self, id: &str, _cancel: CancellationToken) -> Result<()> {
            assert!(uuid::Uuid::parse_str(id).is_ok());
            self.id = Some(id.into());
            self.calls.push("create".into());
            if let Some(cancel) = &self.cancel_after_create {
                cancel.cancel();
            }
            if self.fail_create {
                Err(Error::Offline)
            } else {
                Ok(())
            }
        }
        async fn reload(&mut self, id: &str) -> Result<()> {
            assert_eq!(self.id.as_deref(), Some(id));
            self.calls.push("reload".into());
            Ok(())
        }
        async fn skill(&mut self, app: &str, skill: &str, input: Value) -> Result<Value> {
            self.calls.push(format!("{app}.{skill}"));
            match (app, skill) {
                ("math", "calculate") => {
                    assert_eq!(input["expression"], "2 + 2");
                    Ok(json!({"answer":4}))
                }
                ("web", "search") => {
                    assert_eq!(input["requests"][0]["count"], 1);
                    assert_eq!(
                        input["requests"][0]["query"],
                        "site:openmates.org OpenMates"
                    );
                    Ok(json!({"results":[{"title":"fixture","url":"https://example.invalid"}]}))
                }
                _ => panic!("unexpected skill"),
            }
        }
        async fn cleanup(&mut self, id: &str, cancel: CancellationToken) -> Result<()> {
            assert!(!cancel.is_cancelled());
            assert_eq!(self.id.as_deref(), Some(id));
            self.calls.push("cleanup".into());
            if self.fail_cleanup {
                Err(Error::Offline)
            } else {
                Ok(())
            }
        }
    }
    #[tokio::test]
    async fn scripted_checks_always_attempt_cleanup_and_report_only_sanitized_failures() {
        for fail_create in [false, true] {
            let mut fake = Fake {
                calls: vec![],
                fail_create,
                fail_cleanup: false,
                id: None,
                cancel_after_create: None,
            };
            let result = run(
                &mut fake,
                &CancellationToken::new(),
                &uuid::Uuid::new_v4().to_string(),
            )
            .await
            .unwrap();
            assert_eq!(
                result["status"],
                if fail_create { "failed" } else { "passed" }
            );
            assert_eq!(
                fake.calls,
                vec![
                    "create",
                    "reload",
                    "math.calculate",
                    "web.search",
                    "cleanup"
                ]
            );
            assert!(!result.to_string().contains("example.invalid"));
            assert_eq!(result["checks"].as_array().unwrap().len(), 6);
        }
        let mut fake = Fake {
            calls: vec![],
            fail_create: false,
            fail_cleanup: true,
            id: None,
            cancel_after_create: None,
        };
        let result = run(
            &mut fake,
            &CancellationToken::new(),
            &uuid::Uuid::new_v4().to_string(),
        )
        .await
        .unwrap();
        assert_eq!(result["status"], "failed");
        assert_eq!(
            result["checks"][5]["sanitized_reason"],
            "chat_cleanup_failed"
        );
        assert_eq!(result["cleanupPending"], true);
        assert_eq!(result["chatId"].as_str(), fake.id.as_deref());
    }
    #[tokio::test]
    async fn cancellation_stops_paid_checks_and_uses_fresh_bounded_cleanup() {
        let cancel = CancellationToken::new();
        let mut fake = Fake {
            calls: vec![],
            fail_create: false,
            fail_cleanup: false,
            id: None,
            cancel_after_create: Some(cancel.clone()),
        };
        let result = run(&mut fake, &cancel, &uuid::Uuid::new_v4().to_string())
            .await
            .unwrap();
        assert_eq!(fake.calls, vec!["create", "cleanup"]);
        assert_eq!(result["cancelled"], true);
        assert_eq!(result["cleanupPending"], false);
        let mut untouched = Fake {
            calls: vec![],
            fail_create: false,
            fail_cleanup: false,
            id: None,
            cancel_after_create: None,
        };
        run(&mut untouched, &cancel, &uuid::Uuid::new_v4().to_string())
            .await
            .unwrap();
        assert!(untouched.calls.is_empty());
    }
    #[tokio::test]
    async fn dropping_personal_future_restores_original_team_and_caller_token() {
        let team = uuid::Uuid::new_v4().to_string();
        let caller = CancellationToken::new();
        let session = crate::storage::Session {
            api_url: "https://selfhost.example.invalid".into(),
            session_id: "fixture".into(),
            cookies: BTreeMap::new(),
            ws_token: None,
            master_key: Zeroizing::new([0; 32]),
            hashed_email: String::new(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 0,
            paired_session_expires_at: None,
            active_team_id: Some(team.clone()),
        };
        let mut client = Client::new("https://selfhost.example.invalid", Some(session)).unwrap();
        client.set_operation_cancel(caller.clone());
        let mut future = Box::pin(async {
            let _scope = PersonalScope::new(&mut client, &caller).unwrap();
            std::future::pending::<()>().await;
        });
        tokio::select! {biased;_=future.as_mut()=>panic!("fixture should remain pending"),_=tokio::task::yield_now()=>{}}
        drop(future);
        assert_eq!(
            client.session().unwrap().active_team_id.as_deref(),
            Some(team.as_str())
        );
        assert!(!caller.is_cancelled());
        client.set_team(None).unwrap();
        assert!(
            !caller.is_cancelled(),
            "SDK context transitions own only child tokens"
        );
        drop(client);
        assert!(!caller.is_cancelled());
    }
    #[test]
    fn target_and_spend_consent_fail_before_paid_calls() {
        let mut session = crate::storage::Session {
            api_url: "https://selfhost.example.invalid".into(),
            session_id: "fixture".into(),
            cookies: BTreeMap::new(),
            ws_token: None,
            master_key: Zeroizing::new([0; 32]),
            hashed_email: String::new(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 0,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        assert!(eligible("https://selfhost.example.invalid:443", Some(&session)).is_ok());
        assert!(eligible("https://cloud.example.invalid", Some(&session)).is_err());
        session.paired_session_expires_at = Some(1);
        assert!(matches!(
            eligible("https://selfhost.example.invalid", Some(&session)),
            Err(Error::Expired)
        ));
        assert!(eligible("http://127.0.0.1:8000", None).is_err());
        assert!(origin("https://user:key@example.org").is_err());
        assert_eq!(
            origin("https://example.org:443/v1").unwrap(),
            "https://example.org"
        );
        assert!(
            validate_options(
                "test",
                &[],
                &Flags::from([
                    ("quick".into(), json!(true)),
                    ("confirm-spend-credits".into(), json!(true))
                ])
            )
            .is_ok()
        );
        assert!(
            validate_options("test", &[], &Flags::from([("quick".into(), json!("true"))])).is_err()
        );
    }
    #[tokio::test]
    async fn missing_spend_consent_never_reads_host_state_or_uses_client() {
        let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
        assert!(
            matches!(quick_test(&mut client,&Flags::from([("quick".into(),json!(true))]),Path::new("/does-not-exist-fixture"), &CancellationToken::new()).await,Err(Error::Invalid(message))if message.contains("confirm-spend-credits"))
        );
    }
    #[tokio::test]
    async fn shared_preflight_returns_noncore_before_any_credential_requirement() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let state = dir.path().join("native-state");
        let mut c = super::super::tests::c();
        c.install_path = dir.path().join("install");
        fs::write(
            &c.install_path.join(".env"),
            b"SERVER_ENVIRONMENT=development\n",
            0o600,
        )
        .unwrap();
        fs::write(
            &c.install_path.join(marker("core", "image")),
            b"services: {}\n",
            0o600,
        )
        .unwrap();
        save_config(&state, &c).unwrap();
        let flags = Flags::from([
            ("quick".into(), json!(true)),
            ("confirm-spend-credits".into(), json!(true)),
        ]);
        assert!(
            quick_test_preflight(&flags, &state)
                .await
                .unwrap()
                .is_none()
        );
        c.server_role = "upload".into();
        fs::write(
            &c.install_path.join(marker("upload", "image")),
            b"services: {}\n",
            0o600,
        )
        .unwrap();
        save_config(&state, &c).unwrap();
        let result = quick_test_preflight(&flags, &state).await.unwrap().unwrap();
        assert_eq!(result["quickTest"]["reason"], "non_core_role");
        let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
        assert_eq!(
            quick_test(&mut client, &flags, &state, &CancellationToken::new())
                .await
                .unwrap(),
            result
        );
    }
}
