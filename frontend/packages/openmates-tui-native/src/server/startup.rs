//! CMS readiness includes migrations. Complete setup before asking Compose to
//! gate consumers on that readiness, as the native update transaction does.
use super::*;
use std::time::{Duration, Instant};
const STATE: &str = r#"{"status":{{json .State.Status}},"exitCode":{{json .State.ExitCode}},"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}}"#;
const HEALTH_DEADLINE: Duration = Duration::from_secs(180);
fn consumer(service: &str) -> bool {
    matches!(service, "api" | "webapp" | "task-scheduler") || service.ends_with("-worker")
}
struct Plan {
    selected: Vec<String>,
    prepared: Vec<String>,
    cms: bool,
    vault: bool,
}
impl Plan {
    fn new(c: &Configuration, selected: Vec<String>) -> Self {
        let consumer = selected.iter().any(|s| consumer(s));
        let cms = c.server_role == "core"
            && (consumer
                || selected
                    .iter()
                    .any(|s| matches!(s.as_str(), "cms" | "cms-setup")));
        let vault = cms
            && (consumer
                || selected
                    .iter()
                    .any(|s| matches!(s.as_str(), "vault" | "vault-setup")));
        let mut prepared = selected.clone();
        if cms {
            for service in ["cms", "cms-setup"] {
                if !prepared.iter().any(|s| s == service) {
                    prepared.push(service.into());
                }
            }
        }
        if vault && !prepared.iter().any(|s| s == "vault-setup") {
            prepared.push("vault-setup".into());
        }
        Self {
            selected,
            prepared,
            cms,
            vault,
        }
    }
}
struct Journal<'a> {
    config: &'a Configuration,
    phases: Vec<Value>,
}
impl Journal<'_> {
    fn save(&self, status: &str, phase: &str) -> Result<()> {
        fs::write(
            &self.config.install_path.join(format!(
                ".openmates/{}-start-status.json",
                self.config.server_role
            )),
            &serde_json::to_vec(
                &json!({"command":"start","status":status,"phase":phase,"mode":self.config.install_mode,"role":self.config.server_role,"updatedAt":now(),"phases":self.phases}),
            )?,
            0o600,
        )
    }
    fn phase<T>(&mut self, name: &str, work: impl FnOnce() -> Result<T>) -> Result<T> {
        if let Err(error) = operation::check() {
            self.save("cancelled", name)?;
            return Err(error);
        }
        self.save("in_progress", name)?;
        let started = now();
        let clock = Instant::now();
        let result = work();
        let status = match &result {
            Ok(_) => "passed",
            Err(Error::Cancelled) => "cancelled",
            Err(_) => "failed",
        };
        self.phases.push(json!({"phase":name,"status":status,"startedAt":started,"completedAt":now(),"durationMs":clock.elapsed().as_millis()}));
        self.save(
            if result.is_ok() {
                "in_progress"
            } else {
                status
            },
            name,
        )?;
        result
    }
}
fn remaining(deadline: Instant) -> Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|d| !d.is_zero())
        .ok_or(Error::Invalid("Server startup exceeded its deadline."))
}
fn runtime_docker(
    c: &Configuration,
    args: impl IntoIterator<Item = String>,
    deadline: Instant,
) -> Result<Zeroizing<Vec<u8>>> {
    let mut command = compose(c);
    command.extend(args);
    run_timeout(
        "docker",
        &command,
        &c.install_path,
        None,
        remaining(deadline)?,
    )
}
fn inspect(c: &Configuration, service: &str, deadline: Instant) -> Result<Value> {
    let ids = runtime_docker(c, ["ps".into(), "-aq".into(), service.into()], deadline)?;
    let id = std::str::from_utf8(&ids)
        .map_err(|_| Error::Protocol)?
        .trim();
    if !(12..=64).contains(&id.len()) || !id.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(Error::Protocol);
    }
    let bytes = run_timeout(
        "docker",
        &["inspect".into(), "--format".into(), STATE.into(), id.into()],
        &c.install_path,
        None,
        remaining(deadline)?,
    )?;
    Ok(serde_json::from_slice(&bytes)?)
}
fn setup(c: &Configuration, service: &str, deadline: Instant) -> Result<()> {
    runtime_docker(
        c,
        [
            "up".into(),
            "--no-deps".into(),
            "--force-recreate".into(),
            "--exit-code-from".into(),
            service.into(),
            service.into(),
        ],
        deadline,
    )?;
    let state = inspect(c, service, deadline)?;
    if state["status"] != "exited" || state["exitCode"] != 0 {
        return Err(Error::Invalid(
            "Setup did not exit successfully; consumers remain unstarted.",
        ));
    }
    Ok(())
}
fn runtime_rows(bytes: &[u8]) -> Result<Vec<Value>> {
    if bytes.trim_ascii().is_empty() {
        return Ok(vec![]);
    }
    let rows = match serde_json::from_slice::<Value>(bytes) {
        Ok(Value::Array(rows)) => rows,
        Ok(row @ Value::Object(_)) => vec![row],
        Ok(_) => return Err(Error::Protocol),
        Err(_) => std::str::from_utf8(bytes)
            .map_err(|_| Error::Protocol)?
            .lines()
            .filter(|line| !line.trim().is_empty())
            .map(serde_json::from_str)
            .collect::<std::result::Result<Vec<Value>, _>>()?,
    };
    if rows.len() > 128 {
        return Err(Error::Protocol);
    }
    let mut seen = std::collections::BTreeSet::new();
    for row in &rows {
        let name = row["Service"].as_str().ok_or(Error::Protocol)?;
        let known = CORE.contains(&name)
            || WORKERS.contains(&name)
            || matches!(
                name,
                "admin-sidecar"
                    | "webapp"
                    | "openobserve"
                    | "promtail"
                    | "prometheus"
                    | "cadvisor"
                    | "node-exporter"
                    | "alertmanager"
            );
        if !known
            || !seen.insert(name)
            || !matches!(
                row["State"].as_str(),
                Some(
                    "running"
                        | "paused"
                        | "restarting"
                        | "removing"
                        | "created"
                        | "exited"
                        | "dead"
                )
            )
        {
            return Err(Error::Protocol);
        }
    }
    Ok(rows)
}
fn bootstrap_required(rows: &[Value], vault: bool) -> Result<bool> {
    let active = |row: &Value| {
        matches!(
            row["State"].as_str(),
            Some("running" | "paused" | "restarting" | "removing")
        )
    };
    if rows.iter().any(|row| {
        matches!(row["Service"].as_str(), Some("cms-setup" | "vault-setup")) && active(row)
    }) {
        return Err(Error::Invalid(
            "A setup container is still active; let it finish before retrying startup.",
        ));
    }
    if !rows
        .iter()
        .any(|row| row["Service"].as_str().is_some_and(consumer) && active(row))
    {
        return Ok(true);
    }
    let unique = |service: &str| {
        let mut matches = rows.iter().filter(|row| row["Service"] == service);
        let found = matches.next();
        if matches.next().is_some() {
            None
        } else {
            found
        }
    };
    let healthy = |service: &str| {
        unique(service).is_some_and(|row| row["State"] == "running" && row["Health"] == "healthy")
    };
    let completed = |service: &str| {
        unique(service).is_some_and(|row| row["State"] == "exited" && row["ExitCode"] == 0)
    };
    if !healthy("cms")
        || !completed("cms-setup")
        || vault && (!healthy("vault") || !completed("vault-setup"))
    {
        return Err(Error::Invalid(
            "Live consumers have incomplete setup or unhealthy dependencies; inspect the runtime before an explicit update.",
        ));
    }
    Ok(false)
}
fn wait_cms(
    c: &Configuration,
    deadline: Duration,
    pause: Duration,
    runtime_deadline: Instant,
) -> Result<()> {
    wait_healthy(c, "cms", deadline, pause, runtime_deadline)
}
fn wait_healthy(
    c: &Configuration,
    service: &str,
    deadline: Duration,
    pause: Duration,
    runtime_deadline: Instant,
) -> Result<()> {
    let started = Instant::now();
    let health_deadline = (started + deadline).min(runtime_deadline);
    loop {
        operation::check()?;
        if Instant::now() >= health_deadline {
            return Err(Error::Invalid(
                "Dependency health did not pass after setup; consumers remain unstarted.",
            ));
        }
        let state = inspect(c, service, health_deadline)?;
        if state["status"] == "running" && state["health"] == "healthy" {
            return Ok(());
        }
        std::thread::sleep(pause.min(deadline.saturating_sub(started.elapsed())));
    }
}
pub(super) fn start(c: &Configuration, selected: Vec<String>) -> Result<()> {
    let plan = Plan::new(c, selected);
    let mut journal = Journal {
        config: c,
        phases: vec![],
    };
    journal.phase("prepare_bind_mounts", || bind_mounts::prepare(c))?;
    // Resume dependency-only/created-consumer projects after failed or cancelled
    // bootstrap. A verified live cohort keeps ordinary selected startup; never
    // force setup under live consumers or interrupt an active one-shot setup.
    let bootstrap = if plan.cms {
        journal.phase("inspect_existing_runtime", || {
            let ids = runtime_docker(
                c,
                ["ps".into(), "-a".into(), "--format".into(), "json".into()],
                Instant::now() + Duration::from_secs(15),
            )?;
            let mut rows = runtime_rows(&ids)?;
            let result = bootstrap_required(&rows, plan.vault);
            rows.iter_mut().for_each(local_models::erase);
            result
        })?
    } else {
        false
    };
    let prepared = if bootstrap {
        &plan.prepared
    } else {
        &plan.selected
    };
    if c.install_mode == "image" && std::env::var("OPENMATES_SKIP_IMAGE_PULL").as_deref() != Ok("1")
    {
        journal.phase("pull", || {
            docker(c, std::iter::once("pull".into()).chain(prepared.clone()))
        })?;
    }
    if c.install_mode == "source" {
        journal.phase("build", || {
            docker(c, std::iter::once("build".into()).chain(prepared.clone()))
        })?;
    }
    // Preserve the previous single Compose-up operation's thirty-minute
    // runtime budget across all setup commands rather than granting it anew.
    let deadline = Instant::now() + Duration::from_secs(30 * 60);
    if bootstrap {
        journal.phase("bootstrap_dependencies", || {
            let _critical = operation::critical()?;
            let args = vec![
                "up".into(),
                "-d".into(),
                "--wait".into(),
                "cms-database".into(),
                "cache".into(),
            ];
            runtime_docker(c, args, deadline)
        })?;
        if plan.vault {
            journal.phase("vault_setup", || {
                let _critical = operation::critical()?;
                // Vault's full health requires initialization/unsealing by
                // vault-setup. Its canonical setup dependency is only started.
                runtime_docker(
                    c,
                    ["up".into(), "-d".into(), "--no-deps".into(), "vault".into()],
                    deadline,
                )?;
                setup(c, "vault-setup", deadline)
            })?;
            journal.phase("vault_full_health", || {
                wait_healthy(
                    c,
                    "vault",
                    HEALTH_DEADLINE,
                    Duration::from_secs(2),
                    deadline,
                )
            })?;
        }
        journal.phase("cms_setup", || {
            // A setup transaction may finish its safe checkpoint on cancel;
            // the following phase observes cancellation before any consumers.
            let _critical = operation::critical()?;
            runtime_docker(
                c,
                ["up".into(), "-d".into(), "--no-deps".into(), "cms".into()],
                deadline,
            )?;
            setup(c, "cms-setup", deadline)
        })?;
        journal.phase("cms_full_health", || {
            wait_cms(c, HEALTH_DEADLINE, Duration::from_secs(2), deadline)
        })?;
    }
    journal.phase("start_selected_services", || {
        let _critical = operation::critical()?;
        // Completed one-shot services were already explicitly run above.
        // Preserve the caller's other targets; Compose retains their canonical
        // dependency/health conditions rather than bypassing them with no-deps.
        let selected = plan
            .selected
            .iter()
            .filter(|s| {
                !bootstrap
                    || (s.as_str() != "cms-setup" && (!plan.vault || s.as_str() != "vault-setup"))
            })
            .cloned()
            .collect::<Vec<_>>();
        if !selected.is_empty() {
            runtime_docker(
                c,
                ["up".into(), "-d".into()].into_iter().chain(selected),
                deadline,
            )?;
        }
        Ok(())
    })?;
    journal.save("success", "complete")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    fn fixture() -> (tempfile::TempDir, Configuration) {
        let dir = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = dir.path().into();
        (dir, c)
    }
    fn command(c: &Configuration, args: &[&str], output: Result<Vec<u8>>) -> fake::Call {
        let mut all = compose(c);
        all.extend(args.iter().map(|s| (*s).into()));
        fake::Call {
            program: "docker",
            args: all,
            output,
        }
    }
    fn state(c: &Configuration, service: &str, value: Value) -> Vec<fake::Call> {
        vec![
            command(c, &["ps", "-aq", service], Ok(b"0123456789ab\n".to_vec())),
            fake::Call {
                program: "docker",
                args: vec![
                    "inspect".into(),
                    "--format".into(),
                    STATE.into(),
                    "0123456789ab".into(),
                ],
                output: Ok(serde_json::to_vec(&value).unwrap()),
            },
        ]
    }
    fn prefix(c: &Configuration) -> Vec<fake::Call> {
        prefix_with_rows(c, json!([]))
    }
    fn prefix_with_rows(c: &Configuration, rows: Value) -> Vec<fake::Call> {
        let mut calls = vec![command(
            c,
            &["ps", "-a", "--format", "json"],
            Ok(serde_json::to_vec(&rows).unwrap()),
        )];
        if std::env::var("OPENMATES_SKIP_IMAGE_PULL").as_deref() != Ok("1") {
            calls.push(command(
                c,
                &["pull", "api", "cms", "cms-setup", "vault-setup"],
                Ok(vec![]),
            ));
        }
        calls.push(command(
            c,
            &["up", "-d", "--wait", "cms-database", "cache"],
            Ok(vec![]),
        ));
        calls.push(command(c, &["up", "-d", "--no-deps", "vault"], Ok(vec![])));
        calls.push(command(
            c,
            &[
                "up",
                "--no-deps",
                "--force-recreate",
                "--exit-code-from",
                "vault-setup",
                "vault-setup",
            ],
            Ok(vec![]),
        ));
        calls.extend(state(
            c,
            "vault-setup",
            json!({"status":"exited","exitCode":0}),
        ));
        calls.extend(state(
            c,
            "vault",
            json!({"status":"running","health":"healthy"}),
        ));
        calls.push(command(c, &["up", "-d", "--no-deps", "cms"], Ok(vec![])));
        calls
    }
    fn receipt(c: &Configuration) -> Value {
        serde_json::from_slice(
            &fs::read(
                &c.install_path.join(".openmates/core-start-status.json"),
                20000,
            )
            .unwrap(),
        )
        .unwrap()
    }
    #[test]
    fn scoped_start_finishes_setup_and_fresh_full_health_before_consumers() {
        let (_dir, c) = fixture();
        let mut calls = prefix(&c);
        calls.push(command(
            &c,
            &[
                "up",
                "--no-deps",
                "--force-recreate",
                "--exit-code-from",
                "cms-setup",
                "cms-setup",
            ],
            Ok(vec![]),
        ));
        calls.extend(state(
            &c,
            "cms-setup",
            json!({"status":"exited","exitCode":0}),
        ));
        calls.extend(state(
            &c,
            "cms",
            json!({"status":"running","health":"healthy"}),
        ));
        calls.push(command(&c, &["up", "-d", "api"], Ok(vec![])));
        fake::with(calls, || start(&c, vec!["api".into()]).unwrap());
        let saved = receipt(&c);
        assert_eq!(saved["status"], "success");
        let phases = saved["phases"].as_array().unwrap();
        let health = phases
            .iter()
            .position(|v| v["phase"] == "cms_full_health")
            .unwrap();
        let consumers = phases
            .iter()
            .position(|v| v["phase"] == "start_selected_services")
            .unwrap();
        assert!(health < consumers);
        assert_eq!(phases[health]["status"], "passed");
        assert!(!STATE.contains("Config.Env"));
    }
    #[test]
    fn failed_setup_does_not_request_any_consumer_start() {
        let (_dir, c) = fixture();
        let mut calls = prefix(&c);
        calls.push(command(
            &c,
            &[
                "up",
                "--no-deps",
                "--force-recreate",
                "--exit-code-from",
                "cms-setup",
                "cms-setup",
            ],
            Err(Error::Invalid("synthetic-setup-failure")),
        ));
        fake::with(calls, || assert!(start(&c, vec!["api".into()]).is_err()));
        let saved = receipt(&c);
        assert_eq!(saved["status"], "failed");
        assert_eq!(saved["phase"], "cms_setup");
        assert!(!saved.to_string().contains("synthetic-setup-failure"));
    }
    #[test]
    fn successful_compose_exit_requires_verified_setup_container_exit() {
        for invalid in [
            json!({"status":"exited","exitCode":1}),
            json!({"status":"running","exitCode":0}),
        ] {
            let (_dir, c) = fixture();
            let mut calls = prefix(&c);
            calls.push(command(
                &c,
                &[
                    "up",
                    "--no-deps",
                    "--force-recreate",
                    "--exit-code-from",
                    "cms-setup",
                    "cms-setup",
                ],
                Ok(vec![]),
            ));
            calls.extend(state(&c, "cms-setup", invalid));
            fake::with(calls, || assert!(start(&c, vec!["api".into()]).is_err()));
            assert_eq!(receipt(&c)["phase"], "cms_setup");
        }
    }
    #[test]
    fn readiness_can_recover_after_setup_but_never_accepts_unhealthy() {
        let (_dir, c) = fixture();
        let mut calls = state(&c, "cms", json!({"status":"running","health":"unhealthy"}));
        calls.extend(state(
            &c,
            "cms",
            json!({"status":"running","health":"healthy"}),
        ));
        fake::with(calls, || {
            wait_cms(
                &c,
                Duration::from_secs(1),
                Duration::ZERO,
                Instant::now() + Duration::from_secs(1),
            )
            .unwrap()
        });
        fake::with(vec![], || {
            assert!(
                wait_cms(
                    &c,
                    Duration::ZERO,
                    Duration::ZERO,
                    Instant::now() + Duration::from_secs(1)
                )
                .is_err()
            )
        });
        assert!(remaining(Instant::now() - Duration::from_secs(1)).is_err());
    }
    #[test]
    fn unrelated_service_scope_does_not_bootstrap_cms_or_add_consumers() {
        let (_dir, c) = fixture();
        let plan = Plan::new(&c, vec!["cache".into()]);
        assert!(!plan.cms);
        assert_eq!(plan.prepared, vec!["cache"]);
        let plan = Plan::new(&c, vec!["api".into()]);
        assert!(plan.cms && plan.vault);
        assert!(!plan.prepared.iter().any(|s| s == "task-worker"));
        let mut calls = vec![];
        if std::env::var("OPENMATES_SKIP_IMAGE_PULL").as_deref() != Ok("1") {
            calls.push(command(&c, &["pull", "cache"], Ok(vec![])));
        }
        calls.push(command(&c, &["up", "-d", "cache"], Ok(vec![])));
        fake::with(calls, || start(&c, vec!["cache".into()]).unwrap());
    }
    #[test]
    fn existing_runtime_preserves_selected_start_without_forced_migration() {
        let (_dir, c) = fixture();
        let mut calls = vec![command(
            &c,
            &["ps", "-a", "--format", "json"],
            Ok(serde_json::to_vec(&warm_rows()).unwrap()),
        )];
        if std::env::var("OPENMATES_SKIP_IMAGE_PULL").as_deref() != Ok("1") {
            calls.push(command(&c, &["pull", "api"], Ok(vec![])));
        }
        calls.push(command(&c, &["up", "-d", "api"], Ok(vec![])));
        fake::with(calls, || start(&c, vec!["api".into()]).unwrap());
        assert!(
            !receipt(&c)["phases"]
                .as_array()
                .unwrap()
                .iter()
                .any(|phase| phase["phase"] == "cms_setup")
        );
    }
    fn warm_rows() -> Value {
        json!([
            {"Service":"api","State":"running","Health":"healthy"},
            {"Service":"cms","State":"running","Health":"healthy"},
            {"Service":"cms-setup","State":"exited","ExitCode":0},
            {"Service":"vault","State":"running","Health":"healthy"},
            {"Service":"vault-setup","State":"exited","ExitCode":0}
        ])
    }
    fn completion(c: &Configuration) -> Vec<fake::Call> {
        let mut calls = vec![command(
            c,
            &[
                "up",
                "--no-deps",
                "--force-recreate",
                "--exit-code-from",
                "cms-setup",
                "cms-setup",
            ],
            Ok(vec![]),
        )];
        calls.extend(state(
            c,
            "cms-setup",
            json!({"status":"exited","exitCode":0}),
        ));
        calls.extend(state(
            c,
            "cms",
            json!({"status":"running","health":"healthy"}),
        ));
        calls.push(command(c, &["up", "-d", "api"], Ok(vec![])));
        calls
    }
    #[test]
    fn sealed_vault_and_partial_or_cancelled_projects_resume_before_consumers() {
        for prior in ["failed", "cancelled"] {
            let (_dir, c) = fixture();
            fs::write(
                &c.install_path.join(".openmates/core-start-status.json"),
                serde_json::to_string(&json!({"status":prior,"phase":"cms_setup"}))
                    .unwrap()
                    .as_bytes(),
                0o600,
            )
            .unwrap();
            // Realistic interrupted project: existing DB/cache, sealed Vault,
            // unhealthy CMS and created consumers do not constitute warm state.
            let rows = json!([
                {"Service":"cms-database","State":"running","Health":"healthy"},
                {"Service":"cache","State":"running","Health":"healthy"},
                {"Service":"vault","State":"running","Health":"unhealthy"},
                {"Service":"vault-setup","State":"exited","ExitCode":1},
                {"Service":"cms","State":"running","Health":"unhealthy"},
                {"Service":"cms-setup","State":"exited","ExitCode":1},
                {"Service":"api","State":"created"}
            ]);
            let mut calls = prefix_with_rows(&c, rows);
            calls.extend(completion(&c));
            fake::with(calls, || start(&c, vec!["api".into()]).unwrap());
            let saved = receipt(&c);
            let phases = saved["phases"].as_array().unwrap();
            let vault_setup = phases
                .iter()
                .position(|v| v["phase"] == "vault_setup")
                .unwrap();
            let vault_health = phases
                .iter()
                .position(|v| v["phase"] == "vault_full_health")
                .unwrap();
            assert!(vault_setup < vault_health);
            assert_eq!(saved["status"], "success");
        }
    }
    #[test]
    fn live_incomplete_or_active_setup_projects_refuse_before_prepare_or_migration() {
        let (_dir, c) = fixture();
        for status in ["paused", "running", "restarting"] {
            let rows = json!([{"Service":"cms-setup","State":status}]);
            fake::with(
                vec![command(
                    &c,
                    &["ps", "-a", "--format", "json"],
                    Ok(serde_json::to_vec(&rows).unwrap()),
                )],
                || assert!(start(&c, vec!["api".into()]).is_err()),
            );
        }
        for health in [Value::Null, json!(""), json!("unhealthy")] {
            let mut rows = warm_rows();
            rows[1]["Health"] = health;
            fake::with(
                vec![command(
                    &c,
                    &["ps", "-a", "--format", "json"],
                    Ok(serde_json::to_vec(&rows).unwrap()),
                )],
                || assert!(start(&c, vec!["api".into()]).is_err()),
            );
        }
    }
    #[test]
    fn runtime_metadata_accepts_compose_shapes_and_rejects_ambiguous_or_unknown_rows() {
        let rows = warm_rows();
        let array = serde_json::to_vec(&rows).unwrap();
        let lines = rows
            .as_array()
            .unwrap()
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n");
        assert_eq!(
            runtime_rows(&array).unwrap(),
            runtime_rows(lines.as_bytes()).unwrap()
        );
        for value in [
            json!([{"Service":"unknown","State":"running"}]),
            json!([{"Service":"api","State":"unknown"}]),
            json!([{"Service":"api","State":"running"},{"Service":"api","State":"exited"}]),
            json!([{"Service":"api"}]),
            json!(null),
        ] {
            assert!(runtime_rows(&serde_json::to_vec(&value).unwrap()).is_err());
        }
        let mut paused = warm_rows();
        paused[0]["State"] = json!("paused");
        paused[2]["ExitCode"] = json!(1);
        assert!(bootstrap_required(paused.as_array().unwrap(), true).is_err());
    }
    #[test]
    fn cancellation_finishes_setup_checkpoint_then_prevents_consumer_phase() {
        let (_dir, c) = fixture();
        let caller = tokio_util::sync::CancellationToken::new();
        let _scope = operation::Scope::new(&caller);
        let mut journal = Journal {
            config: &c,
            phases: vec![],
        };
        journal
            .phase("cms_setup", || {
                let _critical = operation::critical()?;
                caller.cancel();
                operation::check()?;
                Ok(())
            })
            .unwrap();
        assert_eq!(
            journal.phase("start_selected_services", || -> Result<()> {
                panic!("cancelled startup must not launch consumers")
            }),
            Err(Error::Cancelled)
        );
        assert_eq!(receipt(&c)["status"], "cancelled");
    }
}
