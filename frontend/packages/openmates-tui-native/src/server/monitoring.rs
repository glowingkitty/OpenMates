//! Durable per-check incidents, independent watchdog and systemd unit planning.
use super::*;
#[derive(Default, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Check {
    #[serde(default)]
    consecutive_failures: u64,
    #[serde(default)]
    incident_open: bool,
    #[serde(default)]
    incident_opened_at: Option<String>,
    #[serde(default)]
    last_check_at: Option<String>,
    #[serde(default)]
    last_success_at: Option<String>,
    #[serde(default)]
    last_failure_class: Option<String>,
}
#[derive(Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct State {
    #[serde(flatten)]
    aggregate: Check,
    #[serde(default)]
    last_notification_at: Option<String>,
    #[serde(default)]
    last_heartbeat_at: Option<String>,
    #[serde(default)]
    checks: BTreeMap<String, Check>,
    #[serde(default)]
    pending_notifications: Vec<Value>,
}
fn path(c: &Configuration) -> PathBuf {
    c.install_path
        .join(format!(".openmates/runtime-health/{}.json", c.server_role))
}
fn read(c: &Configuration) -> Result<State> {
    let path = path(c);
    if !path.try_exists()? {
        return Ok(State::default());
    }
    Ok(serde_json::from_slice(&fs::read(&path, 1024 * 1024)?)?)
}
fn write(c: &Configuration, state: &State) -> Result<()> {
    fs::write(&path(c), &serde_json::to_vec_pretty(state)?, 0o600)
}
fn elapsed(stamp: Option<&str>, now_ms: u64) -> Option<u64> {
    let value =
        time::OffsetDateTime::parse(stamp?, &time::format_description::well_known::Rfc3339).ok()?;
    let millis = u64::try_from(value.unix_timestamp_nanos() / 1_000_000).ok()?;
    now_ms.checked_sub(millis)
}
fn evaluate(
    check: &mut Check,
    passed: bool,
    class: Option<&str>,
    timestamp: &str,
) -> Option<&'static str> {
    check.last_check_at = Some(timestamp.into());
    if passed {
        let was_open = check.incident_open;
        check.consecutive_failures = 0;
        check.incident_open = false;
        check.incident_opened_at = None;
        check.last_success_at = Some(timestamp.into());
        check.last_failure_class = None;
        return was_open.then_some("recovery");
    }
    check.consecutive_failures = check.consecutive_failures.saturating_add(1);
    check.last_failure_class = class.map(str::to_owned);
    let immediate = class.is_some_and(|c| {
        matches!(
            c,
            "credential" | "configuration" | "config" | "critical_availability"
        )
    });
    if !check.incident_open && (immediate || check.consecutive_failures >= 2) {
        check.incident_open = true;
        check.incident_opened_at = Some(timestamp.into());
        Some("incident")
    } else {
        None
    }
}
fn event(c: &Configuration, kind: &str, check: &str, timestamp: &str) -> Value {
    json!({"eventId":uuid::Uuid::new_v4().to_string(),"kind":kind,"occurredAt":timestamp,"environment":"self_host","deploymentMode":"self_host","role":c.server_role,"version":c.image_tag.as_deref().unwrap_or("source"),"checkIds":[check],"sanitizedReason":match kind{"recovery"=>"required_checks_recovered","stale"=>"runtime_verifier_stale","heartbeat"=>"daily_runtime_health_green",_=>"required_check_failed"}})
}
fn enqueue(state: &mut State, value: Value) -> Result<()> {
    if state
        .pending_notifications
        .iter()
        .any(|old| old["kind"] == value["kind"] && old["checkIds"] == value["checkIds"])
    {
        return Ok(());
    }
    if state.pending_notifications.len() >= 128 {
        return Err(Error::Invalid(
            "Monitoring notification journal is full; reconcile undelivered incidents.",
        ));
    }
    state.pending_notifications.push(value);
    Ok(())
}
fn flush(c: &Configuration, state: &mut State) -> Result<Vec<Value>> {
    let mut delivery = vec![];
    let mut retained = vec![];
    for event in &state.pending_notifications {
        let delivered = notifications::deliver(c, event, None)?;
        let accepted =
            !delivered.is_empty() && delivered.iter().any(|d| d["status"] == "delivered");
        if !accepted {
            retained.push(event.clone())
        } else {
            state.last_notification_at = event["occurredAt"].as_str().map(str::to_owned);
        }
        delivery.push(json!({"eventId":event["eventId"],"delivery":delivered}));
    }
    state.pending_notifications = retained;
    write(c, state)?;
    Ok(delivery)
}
pub(super) fn dispatch(c: &Configuration, event: Value) -> Result<Vec<Value>> {
    let mut state = read(c)?;
    enqueue(&mut state, event)?;
    write(c, &state)?;
    flush(c, &mut state)
}
fn persist(c: &Configuration, output: &Value) -> Result<Vec<Value>> {
    let timestamp = notifications::timestamp()?;
    let mut state = read(c)?;
    let was_stale = state.aggregate.last_failure_class.as_deref() == Some("stale");
    let checks = output["checks"].as_array().ok_or(Error::Protocol)?;
    for result in checks {
        let id = result["id"].as_str().ok_or(Error::Protocol)?;
        if id.len() > 128
            || !id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        {
            return Err(Error::Protocol);
        }
        let check = state.checks.entry(id.into()).or_default();
        let passed = result["status"] == "passed";
        let class = result["failureClass"].as_str();
        if let Some(kind) = evaluate(check, passed, class, &timestamp) {
            enqueue(&mut state, event(c, kind, id, &timestamp))?;
        }
    }
    state.aggregate.incident_open = state.checks.values().any(|c| c.incident_open);
    state.aggregate.consecutive_failures = state
        .checks
        .values()
        .map(|c| c.consecutive_failures)
        .max()
        .unwrap_or(0);
    state.aggregate.last_check_at = Some(timestamp.clone());
    if !state.aggregate.incident_open && output["status"] == "passed" {
        if was_stale {
            enqueue(
                &mut state,
                event(c, "recovery", "runtime.verifier", &timestamp),
            )?;
        }
        state.aggregate.last_success_at = Some(timestamp.clone());
        state.aggregate.last_failure_class = None;
        if state.last_heartbeat_at.is_none() {
            state.last_heartbeat_at = Some(timestamp.clone());
        }
    }
    if !state.aggregate.incident_open
        && elapsed(state.last_heartbeat_at.as_deref(), now())
            .is_some_and(|ms| ms >= 24 * 60 * 60 * 1000)
    {
        enqueue(
            &mut state,
            event(c, "heartbeat", "runtime.health", &timestamp),
        )?;
        state.last_heartbeat_at = Some(timestamp);
    }
    write(c, &state)?;
    fs::metrics(&c.install_path)?;
    let metric = format!(
        "openmates_runtime_health_passed{{role=\"{}\"}} {}\nopenmates_runtime_health_last_check_timestamp_seconds{{role=\"{}\"}} {}\n",
        c.server_role,
        u8::from(output["status"] == "passed"),
        c.server_role,
        now() / 1000
    );
    fs::write(
        &c.install_path.join(format!(
            ".openmates/runtime-health/metrics/{}-runtime.prom",
            c.server_role
        )),
        metric.as_bytes(),
        0o644,
    )?;
    flush(c, &mut state)
}
pub(super) fn verification(c: &Configuration) -> Result<Value> {
    let result = update::health(c).and_then(|_| update::verify_runtime(c));
    let mut output = match result {
        Ok(value) => value,
        Err(_) => {
            json!({"status":"failed","checks":[{"id":format!("{}.runtime_verifier_available",c.server_role),"status":"failed","required":true,"failureClass":"critical_availability","sanitized_reason":"runtime_verifier_unavailable"}]})
        }
    };
    if output["status"] == "passed" {
        output["checks"].as_array_mut().ok_or(Error::Protocol)?.push(json!({"id":format!("{}.runtime_verifier_available",c.server_role),"status":"passed","required":true}));
    }
    output["role"] = json!(c.server_role);
    output["completed_at"] = json!(now() / 1000);
    let delivery = persist(c, &output)?;
    output["notificationDelivery"] = json!(delivery);
    Ok(output)
}
fn watchdog(c: &Configuration) -> Result<Value> {
    let mut state = read(c)?;
    let timestamp = notifications::timestamp()?;
    let stale = elapsed(state.aggregate.last_check_at.as_deref(), now())
        .is_none_or(|elapsed| elapsed > 15 * 60 * 1000);
    let notification = if stale
        && !(state.aggregate.incident_open
            && state.aggregate.last_failure_class.as_deref() == Some("stale"))
    {
        state.aggregate.incident_open = true;
        state.aggregate.last_failure_class = Some("stale".into());
        state
            .aggregate
            .incident_opened_at
            .get_or_insert(timestamp.clone());
        let value = event(c, "stale", "runtime.verifier", &timestamp);
        enqueue(&mut state, value.clone())?;
        Some(value)
    } else {
        None
    };
    write(c, &state)?;
    let delivery = flush(c, &mut state)?;
    Ok(json!({"role":c.server_role,"notification":notification,"delivery":delivery,"state":state}))
}
pub(super) fn systemd_quote(path: &Path) -> Result<String> {
    let text = path.to_str().ok_or(Error::Io)?;
    if text.contains(['\n', '\r', '\0']) {
        return Err(Error::Invalid(
            "Systemd paths cannot contain control characters.",
        ));
    }
    Ok(format!(
        "\"{}\"",
        text.replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('%', "%%")
            .replace('$', "$$")
    ))
}
fn units(c: &Configuration, executable: &Path) -> Result<Vec<(String, String)>> {
    use std::os::unix::fs::MetadataExt;
    let owner = std::fs::metadata(&c.install_path)
        .map(|m| m.uid())
        .unwrap_or_else(|_| rustix::process::geteuid().as_raw());
    let executable = systemd_quote(executable)?;
    let working = systemd_quote(&c.install_path)?;
    let mut files = vec![];
    for watchdog in [false, true] {
        let kind = if watchdog {
            "runtime-watchdog"
        } else {
            "runtime-monitor"
        };
        let service = format!("openmates-{}-{kind}.service", c.server_role);
        let timer = format!("openmates-{}-{kind}.timer", c.server_role);
        let unit = format!(
            "[Unit]\nDescription=OpenMates {} {kind}\nAfter=docker.service network-online.target\nWants=network-online.target\n\n[Service]\nType=oneshot\nUser={owner}\nWorkingDirectory={working}\nExecStart={executable} server monitoring run --path {working} --role {}{}\n",
            c.server_role,
            c.server_role,
            if watchdog { " --watchdog" } else { "" }
        );
        let cadence = if watchdog {
            "OnBootSec=3min\nOnUnitActiveSec=5min"
        } else {
            "OnBootSec=2min\nOnUnitActiveSec=1min"
        };
        let schedule = format!(
            "[Unit]\nDescription=Schedule OpenMates {kind}\n\n[Timer]\n{cadence}\nPersistent=true\nUnit={service}\n\n[Install]\nWantedBy=timers.target\n"
        );
        files.extend([(service, unit), (timer, schedule)]);
    }
    Ok(files)
}
pub(super) fn execute(action: &str, c: &Configuration, flags: &Flags) -> Result<Value> {
    match action {
        "verify" | "monitoring run" if !boolean(flags, "watchdog") => {
            let output = verification(c)?;
            if output["status"] != "passed" {
                return Err(Error::Invalid(
                    "Runtime monitor found required check failures; durable incident state was saved.",
                ));
            }
            Ok(output)
        }
        "monitoring run" => watchdog(c),
        "monitoring status" => {
            let state = read(c)?;
            let stale = elapsed(state.aggregate.last_check_at.as_deref(), now())
                .is_none_or(|e| e > 15 * 60 * 1000);
            Ok(json!({"role":c.server_role,"state":state,"stale":stale}))
        }
        "monitoring install-service" => {
            let files = units(c, &std::env::current_exe()?)?;
            let payload = json!({"command":action,"status":"planned","role":c.server_role,"files":files.iter().map(|(name,content)|json!({"name":name,"content":content})).collect::<Vec<_>>()});
            if boolean(flags, "dry-run") || boolean(flags, "json") {
                return Ok(payload);
            }
            if !cfg!(target_os = "linux") {
                return Err(Error::Invalid(
                    "Runtime service installation requires Linux systemd.",
                ));
            }
            let _strict = fs::strict_scope();
            // A privileged persistent unit must never retain a replaceable
            // executable owned by an unprivileged checkout or group.
            fs::snapshot(&std::env::current_exe()?, 512 * 1024 * 1024)?;
            let target = Path::new("/etc/systemd/system");
            let _critical = operation::critical()?;
            for (name, content) in &files {
                fs::write(&target.join(name), content.as_bytes(), 0o644)?;
            }
            run_timeout(
                "systemctl",
                &["daemon-reload".into()],
                &c.install_path,
                None,
                std::time::Duration::from_secs(15),
            )?;
            let timers = files
                .iter()
                .filter(|(name, _)| name.ends_with(".timer"))
                .map(|(name, _)| name.clone())
                .collect::<Vec<_>>();
            let mut args = vec!["enable".into(), "--now".into()];
            args.extend(timers.clone());
            run_timeout(
                "systemctl",
                &args,
                &c.install_path,
                None,
                std::time::Duration::from_secs(15),
            )?;
            for timer in timers {
                run_timeout(
                    "systemctl",
                    &["restart".into(), timer.clone()],
                    &c.install_path,
                    None,
                    std::time::Duration::from_secs(15),
                )?;
                run_timeout(
                    "systemctl",
                    &["is-active".into(), "--quiet".into(), timer],
                    &c.install_path,
                    None,
                    std::time::Duration::from_secs(10),
                )?;
            }
            Ok(json!({"command":action,"status":"installed","role":c.server_role}))
        }
        _ => Err(Error::Invalid(
            "This monitoring action has not been ported to native Rust yet.",
        )),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn incident_threshold_recovery_and_immediate_failure_are_deterministic() {
        let mut check = Check::default();
        assert_eq!(
            evaluate(&mut check, false, Some("availability"), "one"),
            None
        );
        assert_eq!(
            evaluate(&mut check, false, Some("availability"), "two"),
            Some("incident")
        );
        assert_eq!(
            evaluate(&mut check, false, Some("availability"), "three"),
            None
        );
        assert_eq!(evaluate(&mut check, true, None, "four"), Some("recovery"));
        assert!(!check.incident_open);
        assert_eq!(
            evaluate(&mut check, false, Some("credential"), "five"),
            Some("incident")
        );
    }
    #[test]
    fn systemd_units_quote_paths_and_pin_install_context() {
        let mut c = super::super::tests::c();
        c.install_path = "/srv/open mates/%user".into();
        let files = units(&c, Path::new("/opt/native/openmates")).unwrap();
        assert_eq!(files.len(), 4);
        assert!(
            files[0]
                .1
                .contains("--path \"/srv/open mates/%%user\" --role core")
        );
        assert!(files[2].1.contains("--watchdog"));
        assert!(systemd_quote(Path::new("/unsafe\npath")).is_err());
    }
    #[test]
    fn timestamps_and_journal_dedup_do_not_use_future_elapsed() {
        assert_eq!(elapsed(Some("1970-01-01T00:00:01Z"), 2000), Some(1000));
        assert_eq!(elapsed(Some("1970-01-01T00:00:03Z"), 2000), None);
        let mut state = State::default();
        enqueue(
            &mut state,
            json!({"kind":"incident","checkIds":["core.cache"]}),
        )
        .unwrap();
        enqueue(
            &mut state,
            json!({"kind":"incident","checkIds":["core.cache"]}),
        )
        .unwrap();
        assert_eq!(state.pending_notifications.len(), 1);
    }
    #[test]
    fn undelivered_incident_and_recovery_survive_atomic_state_reload() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = root.path().to_path_buf();
        fs::write(
            &root.path().join(".env"),
            b"SERVER_ENVIRONMENT=production\n",
            0o600,
        )
        .unwrap();
        let failed = json!({"status":"failed","checks":[{"id":"core.cache","status":"failed","required":true,"failureClass":"availability"}]});
        persist(&c, &failed).unwrap();
        assert!(!read(&c).unwrap().aggregate.incident_open);
        persist(&c, &failed).unwrap();
        let state = read(&c).unwrap();
        assert!(state.aggregate.incident_open);
        assert_eq!(state.pending_notifications.len(), 1);
        persist(&c,&json!({"status":"passed","checks":[{"id":"core.cache","status":"passed","required":true}]})).unwrap();
        let state = read(&c).unwrap();
        assert!(!state.aggregate.incident_open);
        assert_eq!(state.pending_notifications.len(), 2);
        assert_eq!(state.pending_notifications[1]["kind"], "recovery");
        assert_eq!(
            std::fs::metadata(path(&c)).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
}
