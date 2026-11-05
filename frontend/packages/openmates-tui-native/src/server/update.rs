use super::*;
use std::time::Duration;
const CONSUMERS: &[&str] = &["api", "task-worker", "task-scheduler"];
const INSPECT_STATE: &str = r#"{"status":{{json .State.Status}},"exitCode":{{json .State.ExitCode}},"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},"image":{{json .Config.Image}}}"#;
struct Plan {
    prepared: Vec<String>,
    started: Vec<String>,
    setup: bool,
    filtered: bool,
    reuse: bool,
}
fn plan(c: &Configuration, flags: &Flags) -> Result<Plan> {
    let selected = services(c, flags)?;
    let filtered = flags.contains_key("services")
        || flags.contains_key("exclude")
        || c.default_services.as_ref().is_some_and(|v| !v.is_empty());
    let reuse = boolean(flags, "reuse-completed-setup");
    if reuse {
        let tag = text(flags, "image-tag").unwrap_or("");
        if c.server_role != "core"
            || c.install_mode != "image"
            || !flags.contains_key("services")
            || flags.contains_key("exclude")
            || selected.is_empty()
            || selected
                .iter()
                .any(|s| s != "api" && s != "prometheus" && !s.ends_with("-worker"))
            || !tag
                .strip_prefix("sha-")
                .is_some_and(|s| s.len() == 40 && s.bytes().all(|b| b.is_ascii_hexdigit()))
        {
            return Err(Error::Invalid(
                "--reuse-completed-setup requires core image mode, explicit api/worker/prometheus services, no exclude, and an immutable --image-tag sha-<40 hex characters>.",
            ));
        }
    }
    let setup = c.server_role == "core"
        && (reuse
            || !filtered
            || selected.iter().any(|s| {
                matches!(s.as_str(), "cms" | "cms-setup" | "api" | "task-scheduler")
                    || s.ends_with("-worker")
            }));
    let mut started = selected.clone();
    let mut prepared = selected;
    if setup && filtered {
        for service in CONSUMERS {
            if !started.iter().any(|s| s == service) {
                started.push((*service).into());
            }
            if !prepared.iter().any(|s| s == service) {
                prepared.push((*service).into());
            }
        }
        for service in if reuse {
            &[][..]
        } else {
            &["cms", "cms-setup"][..]
        } {
            if !prepared.iter().any(|s| s == service) {
                prepared.push((*service).into());
            }
        }
        started.retain(|s| s != "cms-setup");
    }
    Ok(Plan {
        prepared,
        started,
        setup,
        filtered,
        reuse,
    })
}
fn status_path(c: &Configuration) -> PathBuf {
    c.install_path
        .join(format!(".openmates/{}-update-status.json", c.server_role))
}
fn status(c: &Configuration, value: &Value) -> Result<()> {
    let mut value = value.clone();
    value["role"] = json!(c.server_role);
    value["updated_at"] = json!(now());
    fs::write(&status_path(c), &serde_json::to_vec_pretty(&value)?, 0o600)
}
fn step(c: &Configuration, target: &str, stage: &str) -> Result<()> {
    status(
        c,
        &json!({"status":"in_progress","updateMode":c.install_mode,"targetImageTag":target,"step":stage}),
    )
}
fn request_json(url: &str) -> Result<Value> {
    tokio::runtime::Handle::current().block_on(async {
        let response = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(15))
            .build()?
            .get(url)
            .header("user-agent", "OpenMates-Rust")
            .send()
            .await?;
        if !response.status().is_success() {
            return Err(Error::Offline);
        }
        let mut response = response;
        let mut bytes = Zeroizing::new(Vec::new());
        while let Some(chunk) = response.chunk().await? {
            if bytes.len() + chunk.len() > 1024 * 1024 {
                return Err(Error::Protocol);
            }
            bytes.extend_from_slice(&chunk);
        }
        Ok(serde_json::from_slice(&bytes)?)
    })
}
pub(super) fn resolve_tag(tag: &str) -> Result<String> {
    if tag != "stable" {
        return Ok(tag.into());
    }
    let result =
        request_json("https://api.github.com/repos/glowingkitty/OpenMates/releases/latest")?;
    let tag = result["tag_name"]
        .as_str()
        .filter(|s| s.starts_with('v'))
        .ok_or(Error::Protocol)?;
    image_tag(&Flags::from([("image-tag".into(), json!(tag))]), None)
}
fn health_targets(role: &str) -> (&'static str, Option<&'static str>) {
    match role {
        "core" => (
            "http://127.0.0.1:8000/v1/health",
            Some("http://127.0.0.1:5173"),
        ),
        "preview" => ("http://127.0.0.1:8080/health", None),
        _ => ("http://127.0.0.1:8000/health", None),
    }
}
async fn healthy_at(client: &reqwest::Client, api: &str, web: Option<&str>) -> bool {
    let api = client
        .get(api)
        .send()
        .await
        .is_ok_and(|r| r.status().is_success());
    let web = match web {
        Some(url) => client
            .get(url)
            .send()
            .await
            .is_ok_and(|r| r.status().is_success()),
        None => true,
    };
    api && web
}
pub(super) fn health(c: &Configuration) -> Result<()> {
    let content = env(&c.install_path)?;
    // Only local bound health endpoints are contacted by host management. A
    // remote VITE_API_URL is a client default, not evidence of local runtime.
    // Core /health is a compatibility redirect. Request the canonical path
    // directly while retaining the no-redirect policy and 2xx requirement.
    let (api, web) = health_targets(&c.server_role);
    let _ = content;
    let deadline = std::time::Instant::now() + Duration::from_secs(180);
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(5))
        .build()?;
    loop {
        operation::check()?;
        let passed = tokio::runtime::Handle::current().block_on(healthy_at(&client, api, web));
        if passed {
            return Ok(());
        }
        if std::time::Instant::now() >= deadline {
            return Err(Error::Invalid(
                "Updated containers did not pass local health checks; inspect server logs.",
            ));
        }
        std::thread::sleep(Duration::from_secs(2));
    }
}
fn inspect_container(c: &Configuration, service: &str, stopped: bool) -> Result<Value> {
    let mut args = vec!["ps".into()];
    if stopped {
        args.push("-a".into());
    }
    args.extend(["-q".into(), service.into()]);
    let ids = docker(c, args)?;
    let ids = std::str::from_utf8(&ids)
        .map_err(|_| Error::Protocol)?
        .split_whitespace()
        .collect::<Vec<_>>();
    if ids.len() != 1 || !ids[0].bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(Error::Invalid(
            "Runtime container was not uniquely identified; email consumers remain stopped.",
        ));
    }
    let result = run(
        "docker",
        &[
            "inspect".into(),
            "--format".into(),
            INSPECT_STATE.into(),
            ids[0].into(),
        ],
        &c.install_path,
        None,
    )?;
    Ok(serde_json::from_slice(&result)?)
}
fn setup_valid(c: &Configuration, target: &str, info: &Value) -> Result<()> {
    if info["status"] != "exited" || info["exitCode"] != 0 {
        return Err(Error::Invalid(
            "Target setup did not exit successfully; email consumers remain stopped.",
        ));
    }
    if c.install_mode == "image"
        && info["image"].as_str()
            != Some(&format!(
                "ghcr.io/glowingkitty/openmates-cms-setup:{target}"
            ))
    {
        return Err(Error::Invalid(
            "Target setup image did not match; email consumers remain stopped.",
        ));
    }
    Ok(())
}
fn verify_setup(c: &Configuration, target: &str) -> Result<()> {
    setup_valid(c, target, &inspect_container(c, "cms-setup", true)?)
}
fn verify_reuse(c: &Configuration, target: &str) -> Result<()> {
    verify_setup(c, target)?;
    for service in ["cms", "cms-database", "cache", "vault"] {
        let state = inspect_container(c, service, false)?;
        if state["status"] != "running"
            || (!state["health"].is_null() && state["health"] != "healthy")
        {
            return Err(Error::Invalid(
                "Completed setup reuse requires running, healthy CMS, database, cache and Vault dependencies.",
            ));
        }
    }
    Ok(())
}
fn stage_setup(c: &Configuration, target: &str, plan: &Plan) -> Result<()> {
    if !plan.setup {
        return Ok(());
    }
    step(c, target, "stop-email-consumers")?;
    docker(
        c,
        std::iter::once("stop".into()).chain(CONSUMERS.iter().map(|s| (*s).into())),
    )?;
    if plan.reuse {
        return verify_reuse(c, target);
    }
    step(c, target, "stage-cms")?;
    docker(
        c,
        ["up".into(), "-d".into(), "--no-deps".into(), "cms".into()],
    )?;
    step(c, target, "cms-setup")?;
    docker(
        c,
        [
            "up".into(),
            "--no-deps".into(),
            "--force-recreate".into(),
            "--exit-code-from".into(),
            "cms-setup".into(),
            "cms-setup".into(),
        ],
    )?;
    verify_setup(c, target)
}
/// Only code-owned identifiers and error categories enter a verification
/// receipt. Tool arguments, replies and error messages may contain secrets.
pub(super) struct Verification<'a> {
    checks: Vec<Value>,
    report: &'a mut dyn FnMut(&Value) -> Result<()>,
}
impl<'a> Verification<'a> {
    fn new(report: &'a mut dyn FnMut(&Value) -> Result<()>) -> Self {
        Self {
            checks: vec![],
            report,
        }
    }
    pub(super) fn check<T>(
        &mut self,
        id: &'static str,
        run: impl FnOnce() -> Result<T>,
    ) -> Result<T> {
        (self.report)(&json!({"status":"in_progress","checks":self.checks,"currentCheck":id}))?;
        match run() {
            Ok(value) => {
                self.checks
                    .push(json!({"id":id,"status":"passed","required":true}));
                (self.report)(
                    &json!({"status":"in_progress","checks":self.checks,"currentCheck":null}),
                )?;
                Ok(value)
            }
            Err(error) => {
                let kind = verification_failure(error);
                self.checks
                    .push(json!({"id":id,"status":"failed","required":true,"failureKind":kind}));
                (self.report)(
                    &json!({"status":if error==Error::Cancelled{"cancelled"}else{"failed"},"checks":self.checks,"currentCheck":id,"failureKind":kind}),
                )?;
                Err(error)
            }
        }
    }
    fn finish(self) -> Result<Value> {
        let value = json!({"status":"passed","checks":self.checks});
        (self.report)(&value)?;
        Ok(value)
    }
}
fn verification_failure(error: Error) -> &'static str {
    match error {
        Error::Invalid("System operation failed. Inspect server status and logs.") => {
            "subprocess_nonzero"
        }
        Error::Invalid("Required system tool could not be started.") => "subprocess_start_failed",
        Error::Invalid(
            "System operation exceeded its deadline."
            | "Provider-free worker runtime probe exceeded its deadline.",
        ) => "deadline_exceeded",
        Error::Invalid("System output exceeded the safe response limit.") => {
            "output_limit_exceeded"
        }
        Error::Invalid("System tool left descendants holding inherited output pipes.") => {
            "subprocess_pipe_open"
        }
        Error::Cancelled => "cancelled",
        Error::Io => "local_io_failed",
        Error::Protocol => "invalid_response",
        Error::Offline => "unavailable",
        _ => "validation_failed",
    }
}
pub(super) fn verify_runtime(c: &Configuration) -> Result<Value> {
    verify_runtime_reported(c, &mut |_| Ok(()))
}
fn verify_runtime_recorded(c: &Configuration) -> Result<Value> {
    verify_runtime_reported(c, &mut |verification| {
        let mut receipt: Value = serde_json::from_slice(&fs::read(&status_path(c), 1024 * 1024)?)?;
        receipt["runtimeVerification"] = verification.clone();
        status(c, &receipt)
    })
}
fn verify_runtime_reported(
    c: &Configuration,
    report: &mut dyn FnMut(&Value) -> Result<()>,
) -> Result<Value> {
    let mut verification = Verification::new(report);
    verification.check("compose.required_services", || {
        let state = lifecycle("status", c, &Flags::new())?;
        let containers = state["containers"].as_array().ok_or(Error::Protocol)?;
        let required = match c.server_role.as_str() {
            "core" => vec![
                "api",
                "cms",
                "cms-database",
                "cache",
                "vault",
                "task-worker",
                "task-scheduler",
            ],
            "upload" => vec!["app-uploads", "clamav", "vault"],
            _ => vec!["preview"],
        };
        for service in required {
            if !containers.iter().any(|v| {
                v["Service"].as_str() == Some(service)
                    && v["State"]
                        .as_str()
                        .is_some_and(|s| s.eq_ignore_ascii_case("running"))
            }) {
                return Err(Error::Invalid(
                    "A required runtime container is not running.",
                ));
            }
        }
        Ok(())
    })?;
    if c.server_role == "core" {
        let content = verification.check("core.configuration", || env(&c.install_path))?;
        let user = env_get(&content, "DATABASE_USERNAME").unwrap_or("directus");
        let db = env_get(&content, "DATABASE_NAME").unwrap_or("directus");
        verification.check("core.database", || {
            let result = docker(
                c,
                [
                    "exec".into(),
                    "-T".into(),
                    "cms-database".into(),
                    "psql".into(),
                    "-qAt".into(),
                    "-U".into(),
                    user.into(),
                    "--dbname".into(),
                    db.into(),
                    "-c".into(),
                    "SELECT 1".into(),
                ],
            )?;
            if result.trim_ascii() != b"1" {
                return Err(Error::Invalid("Database verification failed."));
            }
            Ok(())
        })?;
        verification.check("core.cms_cache_consistency", || {
        let ids = docker(c, ["ps".into(), "-q".into(), "cms".into()])?;
        let id = std::str::from_utf8(&ids)
            .map_err(|_| Error::Protocol)?
            .trim();
        if id.is_empty() || id.contains(char::is_whitespace) {
            return Err(Error::Protocol);
        }
        let flags=run("docker",&["inspect".into(),"--format".into(),"{{range .Config.Env}}{{if eq . \"CACHE_SKIP_ALLOWED=true\"}}skip,{{end}}{{if eq . \"CACHE_AUTO_PURGE=true\"}}purge,{{end}}{{end}}".into(),id.into()],&c.install_path,None)?;
        if !flags.split(|b| *b == b',').any(|s| s == b"skip")
            || !flags.split(|b| *b == b',').any(|s| s == b"purge")
        {
            return Err(Error::Invalid(
                "CMS cache consistency configuration is missing.",
            ));
        }
        Ok(())
        })?;
        verification.check("core.cache", || {
            let mut args = compose(c);
            args.extend([
                "exec".into(),
                "-T".into(),
                "cache".into(),
                "redis-cli".into(),
                "--pipe".into(),
            ]);
            let password = env_get(&content, "DRAGONFLY_PASSWORD")
                .ok_or(Error::Invalid("Cache password is missing."))?;
            let input = Zeroizing::new(format!(
                "*2\r\n$4\r\nAUTH\r\n${}\r\n{}\r\n*1\r\n$4\r\nPING\r\n",
                password.len(),
                password
            ));
            run("docker", &args, &c.install_path, Some(input.as_bytes()))?;
            Ok(())
        })?;
        verification.check("core.vault", || {
            let vault = docker(
                c,
                [
                    "exec".into(),
                    "-T".into(),
                    "vault".into(),
                    "vault".into(),
                    "status".into(),
                    "-address=http://127.0.0.1:8200".into(),
                    "-format=json".into(),
                ],
            )?;
            let vault: Value = serde_json::from_slice(&vault)?;
            if vault["initialized"] != true || vault["sealed"] != false {
                return Err(Error::Invalid("Vault is sealed or uninitialized."));
            }
            Ok(())
        })?;
    }
    probes::verify(c, &mut verification)?;
    verification.finish()
}
pub(super) fn provenance(c: &Configuration, target: &str) -> Result<String> {
    if c.install_mode == "source" {
        let revision = run(
            "git",
            &["rev-parse".into(), "HEAD".into()],
            &c.install_path,
            None,
        )?;
        let value = std::str::from_utf8(&revision)
            .map_err(|_| Error::Protocol)?
            .trim();
        if value.len() != 40 || !value.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err(Error::Invalid("Source provenance could not be verified."));
        }
        let remote = run(
            "git",
            &["remote".into(), "get-url".into(), "origin".into()],
            &c.install_path,
            None,
        )?;
        let remote = std::str::from_utf8(&remote)
            .map_err(|_| Error::Protocol)?
            .trim();
        if !matches!(
            remote,
            "https://github.com/glowingkitty/OpenMates.git"
                | "https://github.com/glowingkitty/OpenMates"
                | "git@github.com:glowingkitty/OpenMates.git"
        ) {
            return Err(Error::Invalid(
                "Source provenance is not the public OpenMates repository.",
            ));
        }
        return Ok(value.into());
    }
    let image = format!("ghcr.io/glowingkitty/openmates-api:{target}");
    let data = run(
        "docker",
        &[
            "image".into(),
            "inspect".into(),
            "--format".into(),
            "{{json .Config.Labels}}".into(),
            image,
        ],
        &c.install_path,
        None,
    )?;
    let labels: Value = serde_json::from_slice(&data)?;
    let revision = labels["org.opencontainers.image.revision"]
        .as_str()
        .ok_or(Error::Protocol)?;
    if labels["org.opencontainers.image.source"] != "https://github.com/glowingkitty/OpenMates"
        || labels["org.opencontainers.image.version"].as_str() != Some(target)
        || revision.len() != 40
        || !revision.bytes().all(|b| b.is_ascii_hexdigit())
    {
        return Err(Error::Invalid(
            "Installed image provenance could not be verified.",
        ));
    }
    Ok(revision.into())
}
fn email(c: &Configuration, target: &str, revision: &str, previous: &Value) -> Result<Value> {
    // Delivery identity has its own journal: updating general progress must
    // never erase an ambiguous provider request after process interruption.
    let journal = c
        .install_path
        .join(format!(".openmates/{}-update-delivery.json", c.server_role));
    let journal_state = if journal.try_exists()? {
        serde_json::from_slice::<Value>(&fs::read(&journal, 128 * 1024)?)?
    } else {
        previous.clone()
    };
    let previous = &journal_state;
    let content = env(&c.install_path)?;
    let value = |key: &str| {
        std::env::var(key)
            .ok()
            .or_else(|| env_get(&content, key).map(str::to_owned))
            .filter(|v| !v.trim().is_empty() && v != "IMPORTED_TO_VAULT")
    };
    let to = value("OPENMATES_RUNTIME_HEALTH_EMAIL_TO").or_else(|| value("ADMIN_NOTIFY_EMAIL"));
    let key = Zeroizing::new(
        value("OPENMATES_RUNTIME_HEALTH_BREVO_API_KEY")
            .or_else(|| value("BREVO_API_KEY"))
            .unwrap_or_default(),
    );
    let Some(to) = to.filter(|_| !key.is_empty()) else {
        return Ok(
            json!({"status":"unavailable","attempts":0,"sanitizedReason":"email_not_configured"}),
        );
    };
    if previous["completionEmailDelivery"]["status"] == "accepted"
        && previous["installedVersion"] == target
        && previous["updateMode"] == c.install_mode
    {
        return Ok(
            json!({"status":"accepted","attempts":previous["completionEmailDelivery"]["attempts"],"sanitizedReason":"unchanged_version_already_notified"}),
        );
    }
    // One idempotency identity survives interruption and retries. An unknown
    // old pending identity is kept blocked, never silently sent a second time.
    let pending_at = if previous["installedVersion"] == target
        && previous["completionEmailDelivery"]["status"] == "pending"
    {
        previous["completionEmailPendingAt"].as_u64().unwrap_or(0)
    } else {
        now()
    };
    let id = if previous["installedVersion"] == target
        && previous["completionEmailDelivery"]["status"] == "pending"
    {
        let age = now().saturating_sub(previous["completionEmailPendingAt"].as_u64().unwrap_or(0));
        if age >= 30 * 60 * 1000 {
            return Ok(
                json!({"status":"unavailable","attempts":previous["completionEmailDelivery"]["attempts"],"sanitizedReason":"pending_delivery_requires_reconciliation"}),
            );
        }
        previous["completionEmailDeliveryId"]
            .as_str()
            .and_then(|s| uuid::Uuid::parse_str(s).ok())
            .ok_or(Error::Protocol)?
            .to_string()
    } else {
        uuid::Uuid::new_v4().to_string()
    };
    let from = value("OPENMATES_RUNTIME_HEALTH_EMAIL_FROM")
        .or_else(|| value("EMAIL_SENDER_EMAIL"))
        .unwrap_or_else(|| "noreply@openmates.org".into());
    let source = format!("https://github.com/glowingkitty/OpenMates/commit/{revision}");
    let body = json!({"sender":{"email":from},"to":[{"email":to}],"subject":format!("OpenMates {} update completed: {target}",c.server_role),"textContent":format!("OpenMates server update completed.\nRole: {}\nVersion: {target}\nSource: {source}\n",c.server_role),"headers":{"idempotencyKey":id}});
    let prior = if previous["installedVersion"] == target {
        previous["completionEmailDelivery"]["attempts"]
            .as_u64()
            .unwrap_or(0)
    } else {
        0
    };
    for attempt in prior + 1..=3 {
        let pending = json!({"status":"in_progress","step":"completion-email","updateMode":c.install_mode,"installedVersion":target,"targetImageTag":target,"runtimeCompletedAt":now(),"completionEmailPendingAt":pending_at,"completionEmailDeliveryId":id,"completionEmailDelivery":{"status":"pending","attempts":attempt}});
        fs::write(&journal, &serde_json::to_vec_pretty(&pending)?, 0o600)?;
        status(c, &pending)?;
        let accepted = tokio::runtime::Handle::current()
            .block_on(async {
                let client = reqwest::Client::builder()
                    .redirect(reqwest::redirect::Policy::none())
                    .timeout(Duration::from_secs(10))
                    .build()?;
                let mut response = client
                    .post("https://api.brevo.com/v3/smtp/email")
                    .header("api-key", key.as_str())
                    .json(&body)
                    .send()
                    .await?;
                let code = response.status();
                let mut bytes = Zeroizing::new(Vec::new());
                while let Some(chunk) = response.chunk().await? {
                    if bytes.len() + chunk.len() > 64 * 1024 {
                        return Err(Error::Protocol);
                    }
                    bytes.extend_from_slice(&chunk);
                }
                let result: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
                Ok::<bool, Error>(brevo::accepted(code.as_u16(), &result, &body))
            })
            .unwrap_or(false);
        if accepted {
            let mut accepted = pending;
            accepted["completionEmailDelivery"]["status"] = json!("accepted");
            fs::write(&journal, &serde_json::to_vec_pretty(&accepted)?, 0o600)?;
            return Ok(json!({"status":"accepted","attempts":attempt,"deliveryId":id}));
        }
        if attempt < 3 {
            std::thread::sleep(Duration::from_millis(250 * (1 << (attempt - 1))));
        }
    }
    Ok(
        json!({"status":"failed","attempts":prior.max(3),"sanitizedReason":"delivery_failed","deliveryId":id}),
    )
}
pub(super) fn execute(
    action: &str,
    c: &Configuration,
    flags: &Flags,
    state: &Path,
) -> Result<Value> {
    if action == "update status" {
        let path = status_path(c);
        return if path.try_exists()? {
            Ok(serde_json::from_slice(&fs::read(&path, 1024 * 1024)?)?)
        } else {
            Ok(json!({"role":c.server_role,"status":"unknown"}))
        };
    }
    if boolean(flags, "continuous") {
        return Err(Error::Invalid(
            "Continuous updates require the native application continuous runner.",
        ));
    }
    if c.install_mode == "source"
        && (flags.contains_key("image-tag") || flags.contains_key("channel"))
    {
        return Err(Error::Invalid(
            "--image-tag and --channel only apply to image-mode installs. Source-mode installs update from Git.",
        ));
    }
    let plan = plan(c, flags)?;
    let content = env(&c.install_path)?;
    let target = if c.install_mode == "image" {
        image_tag(
            flags,
            c.image_tag
                .as_deref()
                .or_else(|| env_get(&content, "OPENMATES_IMAGE_TAG")),
        )?
    } else {
        "source".into()
    };
    let mut out = json!({"command":"update","status":"planned","path":c.install_path,"role":c.server_role,"mode":c.install_mode,"targetImageTag":if c.install_mode=="image"{json!(target)}else{Value::Null},"dryRun":boolean(flags,"dry-run"),"selectedServices":if plan.filtered{json!(plan.started)}else{json!("all")},"preparedServices":plan.prepared,"reuseCompletedSetup":plan.reuse,"coreSetupGate":{"required":plan.setup,"stopServices":if plan.setup{CONSUMERS}else{&[]},"setupService":"cms-setup","failurePolicy":"keep-email-consumers-stopped"},"steps":["backup","prepare","stop-email-consumers","cms-setup","up","health-check","runtime-verification","completion-email"]});
    let preflight = configuration::preflight(c)?;
    out["missingRequiredEnvKeys"] = preflight["missingRequiredEnvKeys"].clone();
    out["secretPreflight"] = preflight["secretPreflight"].clone();
    out["blocked"] = preflight["blocked"].clone();
    if boolean(flags, "dry-run") {
        return Ok(out);
    }
    if preflight["blocked"] == true && !boolean(flags, "yes") {
        return Err(Error::Invalid(
            "Required runtime or imported Vault secret checks failed. Review server preflight before using --yes.",
        ));
    }
    let previous = if status_path(c).try_exists()? {
        serde_json::from_slice::<Value>(&fs::read(&status_path(c), 1024 * 1024)?)?
    } else {
        json!({})
    };
    let target = if c.install_mode == "image" {
        resolve_tag(&target)?
    } else {
        target
    };
    if plan.reuse {
        verify_reuse(c, &target)?;
    }
    step(c, &target, "backup")?;
    if c.server_role != "preview" && !boolean(flags, "skip-backup") {
        backup::create(c, &Flags::new())?;
    }
    let result = (|| {
        if c.install_mode == "image" {
            image_files(&c.install_path, &c.server_role)?;
            write_environment(&c.install_path, Some(&target), false)?;
            if std::env::var("OPENMATES_SKIP_IMAGE_PULL").as_deref() != Ok("1") {
                step(c, &target, "pull")?;
                docker(
                    c,
                    std::iter::once("pull".into()).chain(plan.prepared.clone()),
                )?;
            }
        } else {
            if c.source_strategy.as_deref() != Some("working_tree") {
                let dirty = run(
                    "git",
                    &["status".into(), "--porcelain".into()],
                    &c.install_path,
                    None,
                )?;
                if !dirty.is_empty() {
                    return Err(Error::Invalid(
                        "Managed source checkout contains changes; preserve them before update.",
                    ));
                }
                run(
                    "git",
                    &["pull".into(), "--ff-only".into()],
                    &c.install_path,
                    None,
                )?;
            }
            step(c, &target, "build")?;
            docker(
                c,
                std::iter::once("build".into()).chain(plan.prepared.clone()),
            )?;
        }
        {
            let _critical = operation::critical()?;
            stage_setup(c, &target, &plan)?;
            step(c, &target, "up")?;
            let mut up = vec!["up".into(), "-d".into()];
            if plan.reuse {
                up.push("--no-deps".into());
            }
            up.extend(plan.started.clone());
            docker(c, up)?;
        }
        operation::check()?;
        step(c, &target, "health-check")?;
        health(c)?;
        step(c, &target, "caddy-update")?;
        caddy::release(c, flags)?;
        step(c, &target, "runtime-verification")?;
        let runtime = verify_runtime_recorded(c)?;
        if std::env::var("OPENMATES_SKIP_RUNTIME_MONITORING").as_deref() != Ok("1") {
            step(c, &target, "monitoring-service")?;
            monitoring::execute("monitoring install-service", c, &Flags::new())?;
        }
        // Refresh an already-configured host reporter and record running image
        // digests for it; an unconfigured reporter is never installed here.
        step(c, &target, "host-reporter")?;
        let host_reporter = host_reporter::after_update(c)?;
        let revision = provenance(c, &target)?;
        let installed = if c.install_mode == "image" {
            target.clone()
        } else {
            revision.clone()
        };
        let mut saved = c.clone();
        if c.install_mode == "image" {
            saved.image_tag = Some(target.clone());
        }
        save_config(state, &saved)?;
        let delivery = email(c, &installed, &revision, &previous)?;
        let accepted = delivery["status"] == "accepted";
        status(
            c,
            &json!({"status":if accepted{"success"}else{"degraded"},"step":if accepted{"complete"}else{"completion-email"},"updateMode":c.install_mode,"targetImageTag":target,"installedVersion":installed,"runtimeCompletedAt":now(),"runtimeVerification":runtime,"completionEmailDelivery":delivery}),
        )?;
        if !accepted {
            return Err(Error::Invalid(
                "Server update completed but the admin completion email was not accepted; updated containers remain running.",
            ));
        }
        Ok(
            json!({"command":"update","status":"success","mode":c.install_mode,"targetImageTag":target,"runtimeVerification":runtime,"hostReporter":host_reporter,"completionEmailDelivery":delivery}),
        )
    })();
    if result.is_err() {
        let current: Value = serde_json::from_slice(&fs::read(&status_path(c), 1024 * 1024)?)?;
        if current["status"] == "in_progress" {
            let mut failed = current;
            failed["status"] = json!(if matches!(result, Err(Error::Cancelled)) {
                "cancelled"
            } else {
                "degraded"
            });
            status(c, &failed)?;
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn selfhost_contract_update_plan_keeps_setup_gate_shape_and_top_level_reuse_flag() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = root.path().into();
        write_environment(root.path(), Some("fixture-tag"), false).unwrap();
        for reuse in [false, true] {
            let mut flags = Flags::from([
                ("dry-run".into(), json!(true)),
                ("services".into(), json!("api")),
                ("image-tag".into(), json!(format!("sha-{}", "a".repeat(40)))),
            ]);
            if reuse {
                flags.insert("reuse-completed-setup".into(), json!(true));
            }
            let output = fake::with(vec![], || {
                execute("update", &c, &flags, root.path()).unwrap()
            });
            assert_eq!(
                output["coreSetupGate"],
                json!({"required":true,
                "stopServices":["api","task-worker","task-scheduler"],
                "setupService":"cms-setup","failurePolicy":"keep-email-consumers-stopped"})
            );
            assert_eq!(output["reuseCompletedSetup"], reuse);
            assert_eq!(
                output["selectedServices"],
                json!(["api", "task-worker", "task-scheduler"])
            );
            assert_eq!(output["blocked"], false);
        }
    }
    fn verification_calls(c: &Configuration) -> Vec<fake::Call> {
        let rows: Vec<Value> = [
            "api",
            "cms",
            "cms-database",
            "cache",
            "vault",
            "task-worker",
            "task-scheduler",
        ]
        .into_iter()
        .map(|service| json!({"Service":service,"State":"running"}))
        .collect();
        let command = |suffix: &[&str], output: Vec<u8>| {
            let mut args = compose(c);
            args.extend(suffix.iter().map(|s| (*s).into()));
            fake::Call {
                program: "docker",
                args,
                output: Ok(output),
            }
        };
        vec![
            command(&["ps", "--format", "json"], serde_json::to_vec(&rows).unwrap()),
            command(&["exec", "-T", "cms-database", "psql", "-qAt", "-U", "directus", "--dbname", "directus", "-c", "SELECT 1"], b"1\n".to_vec()),
            command(&["ps", "-q", "cms"], b"fixture-cms-id\n".to_vec()),
            fake::Call { program: "docker", args: vec!["inspect".into(), "--format".into(), "{{range .Config.Env}}{{if eq . \"CACHE_SKIP_ALLOWED=true\"}}skip,{{end}}{{if eq . \"CACHE_AUTO_PURGE=true\"}}purge,{{end}}{{end}}".into(), "fixture-cms-id".into()], output: Ok(b"skip,purge,".to_vec()) },
            command(&["exec", "-T", "cache", "redis-cli", "--pipe"], b"fixture-tool-output-secret".to_vec()),
            command(&["exec", "-T", "vault", "vault", "status", "-address=http://127.0.0.1:8200", "-format=json"], br#"{"initialized":true,"sealed":false}"#.to_vec()),
            command(&["exec", "-T", "cache", "redis-cli", "--csv", "--version"], b"redis-cli 6.0.16\n".to_vec()),
            command(&["exec", "-T", "cache", "redis-cli", "--csv"], vec![]),
        ]
    }
    #[test]
    fn runtime_verification_nonzero_tools_preserve_exact_check_and_prior_passes() {
        use std::os::unix::fs::PermissionsExt;
        let cases: &[(&str, &[&str])] = &[
            ("compose.required_services", &[]),
            (
                "core.database",
                &["compose.required_services", "core.configuration"],
            ),
            (
                "core.cms_cache_consistency",
                &[
                    "compose.required_services",
                    "core.configuration",
                    "core.database",
                ],
            ),
            (
                "core.cms_cache_consistency",
                &[
                    "compose.required_services",
                    "core.configuration",
                    "core.database",
                ],
            ),
            (
                "core.cache",
                &[
                    "compose.required_services",
                    "core.configuration",
                    "core.database",
                    "core.cms_cache_consistency",
                ],
            ),
            (
                "core.vault",
                &[
                    "compose.required_services",
                    "core.configuration",
                    "core.database",
                    "core.cms_cache_consistency",
                    "core.cache",
                ],
            ),
            (
                "core.redis_cli_capability",
                &[
                    "compose.required_services",
                    "core.configuration",
                    "core.database",
                    "core.cms_cache_consistency",
                    "core.cache",
                    "core.vault",
                ],
            ),
            (
                "core.worker_queue",
                &[
                    "compose.required_services",
                    "core.configuration",
                    "core.database",
                    "core.cms_cache_consistency",
                    "core.cache",
                    "core.vault",
                    "core.redis_cli_capability",
                ],
            ),
        ];
        for (index, (failed, passed)) in cases.iter().enumerate() {
            let root = tempfile::Builder::new()
                .permissions(std::fs::Permissions::from_mode(0o700))
                .tempdir()
                .unwrap();
            let mut c = super::super::tests::c();
            c.install_path = root.path().into();
            fs::write(&c.install_path.join(".env"), b"DATABASE_USERNAME=directus\nDATABASE_NAME=directus\nDRAGONFLY_PASSWORD=fixture-stdin-secret\n", 0o600).unwrap();
            step(&c, "fixture-target", "runtime-verification").unwrap();
            let mut calls = verification_calls(&c);
            calls.truncate(index + 1);
            calls[index].output = Err(Error::Invalid(
                "System operation failed. Inspect server status and logs.",
            ));
            fake::with(calls, || {
                assert_eq!(
                    verify_runtime_recorded(&c),
                    Err(Error::Invalid(
                        "System operation failed. Inspect server status and logs."
                    ))
                );
            });
            let bytes = fs::read(&status_path(&c), 1024 * 1024).unwrap();
            let receipt: Value = serde_json::from_slice(&bytes).unwrap();
            assert_eq!(receipt["step"], "runtime-verification");
            assert_eq!(receipt["targetImageTag"], "fixture-target");
            let verification = &receipt["runtimeVerification"];
            assert_eq!(verification["status"], "failed");
            assert_eq!(verification["currentCheck"], *failed);
            assert_eq!(verification["failureKind"], "subprocess_nonzero");
            let checks = verification["checks"].as_array().unwrap();
            assert_eq!(checks.len(), passed.len() + 1);
            for (check, id) in checks.iter().zip(*passed) {
                assert_eq!(check, &json!({"id":id,"status":"passed","required":true}));
            }
            assert_eq!(
                checks.last().unwrap(),
                &json!({"id":failed,"status":"failed","required":true,"failureKind":"subprocess_nonzero"})
            );
            let text = std::str::from_utf8(&bytes).unwrap();
            for secret in [
                "fixture-stdin-secret",
                "fixture-tool-output-secret",
                "fixture-cms-id",
                "SELECT 1",
                "System operation failed",
                root.path().to_str().unwrap(),
            ] {
                assert!(!text.contains(secret));
            }
            assert_eq!(
                std::fs::metadata(status_path(&c))
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o600
            );
        }
    }
    #[test]
    fn runtime_verification_categories_and_cancellation_never_copy_error_text() {
        for (error, kind) in [
            (
                Error::Invalid("fixture-secret-from-error"),
                "validation_failed",
            ),
            (
                Error::Invalid("System operation exceeded its deadline."),
                "deadline_exceeded",
            ),
            (Error::Protocol, "invalid_response"),
            (Error::Io, "local_io_failed"),
            (Error::Cancelled, "cancelled"),
        ] {
            let mut reports = vec![];
            let mut report = |value: &Value| {
                reports.push(value.clone());
                Ok(())
            };
            let mut verification = Verification::new(&mut report);
            verification.check("core.database", || Ok(())).unwrap();
            assert_eq!(
                verification.check("core.cache", || Err::<(), _>(error)),
                Err(error)
            );
            let last = reports.last().unwrap();
            assert_eq!(last["failureKind"], kind);
            assert_eq!(last["checks"][0]["status"], "passed");
            assert_eq!(
                last["status"],
                if error == Error::Cancelled {
                    "cancelled"
                } else {
                    "failed"
                }
            );
            assert!(
                !serde_json::to_string(&reports)
                    .unwrap()
                    .contains("fixture-secret")
            );
        }
    }
    #[test]
    fn runtime_verification_receipt_failure_stops_before_tool_execution() {
        let c = super::super::tests::c();
        fake::with(vec![], || {
            assert_eq!(
                verify_runtime_reported(&c, &mut |_| Err(Error::Io)),
                Err(Error::Io)
            );
        });
    }
    #[test]
    fn runtime_verification_read_only_caller_preserves_existing_update_receipt() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = root.path().into();
        c.server_role = "preview".into();
        step(&c, "fixture-target", "completion-email").unwrap();
        let before = fs::read(&status_path(&c), 1024 * 1024).unwrap();
        let mut args = compose(&c);
        args.extend(["ps".into(), "--format".into(), "json".into()]);
        fake::with(
            vec![fake::Call {
                program: "docker",
                args,
                output: Ok(br#"[{"Service":"preview","State":"running"}]"#.to_vec()),
            }],
            || {
                let result = verify_runtime(&c).unwrap();
                assert_eq!(
                    result,
                    json!({"status":"passed","checks":[{"id":"compose.required_services","status":"passed","required":true},{"id":"preview.renderer","status":"passed","required":true}]})
                );
            },
        );
        assert_eq!(fs::read(&status_path(&c), 1024 * 1024).unwrap(), before);
    }
    #[tokio::test]
    async fn image_compat_canonical_health_accepts_2xx_without_following_redirects() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let mut paths = vec![];
            for _ in 0..6 {
                let (mut stream, _) =
                    tokio::time::timeout(Duration::from_secs(2), listener.accept())
                        .await
                        .unwrap()
                        .unwrap();
                let mut request = [0u8; 2048];
                let size = tokio::time::timeout(Duration::from_secs(2), stream.read(&mut request))
                    .await
                    .unwrap()
                    .unwrap();
                let line = std::str::from_utf8(&request[..size])
                    .unwrap()
                    .lines()
                    .next()
                    .unwrap();
                let path = line.split_whitespace().nth(1).unwrap().to_owned();
                let response = match path.as_str() {
                    "/health" => {
                        "HTTP/1.1 301 Moved Permanently\r\nLocation: /v1/health\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    }
                    "/v1/health" | "/ready" => {
                        "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
                    }
                    "/unready" => {
                        "HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    }
                    _ => panic!("unexpected synthetic health path"),
                };
                paths.push(path);
                stream.write_all(response.as_bytes()).await.unwrap();
            }
            paths
        });
        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(2))
            .build()
            .unwrap();
        let core = health_targets("core");
        assert_eq!(
            core,
            (
                "http://127.0.0.1:8000/v1/health",
                Some("http://127.0.0.1:5173")
            )
        );
        assert_eq!(
            health_targets("upload"),
            ("http://127.0.0.1:8000/health", None)
        );
        assert_eq!(
            health_targets("preview"),
            ("http://127.0.0.1:8080/health", None)
        );
        let canonical = format!(
            "http://{address}{}",
            url::Url::parse(core.0).unwrap().path()
        );
        assert!(!healthy_at(&client, &format!("http://{address}/health"), None).await);
        assert!(healthy_at(&client, &canonical, None).await);
        assert!(
            !healthy_at(
                &client,
                &canonical,
                Some(&format!("http://{address}/unready"))
            )
            .await
        );
        assert!(
            healthy_at(
                &client,
                &canonical,
                Some(&format!("http://{address}/ready"))
            )
            .await
        );
        assert_eq!(
            server.await.unwrap(),
            vec![
                "/health",
                "/v1/health",
                "/v1/health",
                "/unready",
                "/v1/health",
                "/ready"
            ]
        );
    }
    #[test]
    fn completed_setup_reuse_requires_immutable_explicit_safe_scope() {
        let c = super::super::tests::c();
        let mut flags = Flags::from([
            ("reuse-completed-setup".into(), json!(true)),
            ("services".into(), json!("api,prometheus")),
            ("image-tag".into(), json!(format!("sha-{}", "a".repeat(40)))),
        ]);
        let p = plan(&c, &flags).unwrap();
        assert!(p.reuse && p.setup);
        assert!(!p.prepared.contains(&"cms".into()));
        assert!(!p.prepared.contains(&"cms-setup".into()));
        assert!(p.started.contains(&"task-scheduler".into()));
        flags.insert("image-tag".into(), json!("dev"));
        assert!(plan(&c, &flags).is_err());
        flags.insert("image-tag".into(), json!(format!("sha-{}", "a".repeat(40))));
        flags.insert("services".into(), json!("cms"));
        assert!(plan(&c, &flags).is_err());
        flags.insert("services".into(), json!("api"));
        flags.insert("exclude".into(), json!("webapp"));
        assert!(plan(&c, &flags).is_err());
    }
    fn reused_inspections(c: &Configuration, target: &str, unhealthy: bool) -> Vec<fake::Call> {
        let mut calls = vec![];
        for service in ["cms-setup", "cms", "cms-database", "cache", "vault"] {
            let mut args = compose(c);
            args.push("ps".into());
            if service == "cms-setup" {
                args.push("-a".into());
            }
            args.extend(["-q".into(), service.into()]);
            calls.push(fake::Call {
                program: "docker",
                args,
                output: Ok(b"abcdef\n".to_vec()),
            });
            let state = if service == "cms-setup" {
                json!({"status":"exited","exitCode":0,"health":null,"image":format!("ghcr.io/glowingkitty/openmates-cms-setup:{target}")})
            } else {
                json!({"status":"running","health":if unhealthy&&service=="cache"{"unhealthy"}else{"healthy"}})
            };
            calls.push(fake::Call {
                program: "docker",
                args: vec![
                    "inspect".into(),
                    "--format".into(),
                    INSPECT_STATE.into(),
                    "abcdef".into(),
                ],
                output: Ok(serde_json::to_vec(&state).unwrap()),
            });
            if unhealthy && service == "cache" {
                break;
            }
        }
        calls
    }
    #[test]
    fn reuse_verifies_fresh_dependency_health_and_never_restarts_setup() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = dir.path().into();
        let target = format!("sha-{}", "a".repeat(40));
        fake::with(reused_inspections(&c, &target, true), || {
            assert!(verify_reuse(&c, &target).is_err())
        });
        let p = plan(
            &c,
            &Flags::from([
                ("reuse-completed-setup".into(), json!(true)),
                ("services".into(), json!("api")),
                ("image-tag".into(), json!(target)),
            ]),
        )
        .unwrap();
        let mut stop = compose(&c);
        stop.extend(
            ["stop", "api", "task-worker", "task-scheduler"]
                .into_iter()
                .map(str::to_owned),
        );
        let mut calls = vec![fake::Call {
            program: "docker",
            args: stop,
            output: Ok(vec![]),
        }];
        calls.extend(reused_inspections(&c, &target, false));
        fake::with(calls, || stage_setup(&c, &target, &p).unwrap());
        assert!(
            setup_valid(
                &c,
                &target,
                &json!({"status":"exited","exitCode":0,"image":"other-tag"})
            )
            .is_err()
        );
        assert!(!INSPECT_STATE.contains(".Config.Env"));
    }
    #[test]
    fn partial_api_update_expands_email_cohort_and_setup() {
        let c = super::super::tests::c();
        let flags = Flags::from([("services".into(), json!("api"))]);
        let cohort = plan(&c, &flags).unwrap();
        assert!(cohort.setup);
        assert_eq!(cohort.started, vec!["api", "task-worker", "task-scheduler"]);
        assert_eq!(
            cohort.prepared,
            vec!["api", "task-worker", "task-scheduler", "cms", "cms-setup"]
        );
        let plan = plan(&c, &Flags::from([("services".into(), json!("webapp"))])).unwrap();
        assert!(!plan.setup);
        assert_eq!(plan.started, vec!["webapp"]);
    }
    #[test]
    fn failed_setup_keeps_target_api_and_email_consumers_stopped() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = root.path().to_path_buf();
        let plan = plan(&c, &Flags::from([("services".into(), json!("api"))])).unwrap();
        let commands = [
            vec!["stop", "api", "task-worker", "task-scheduler"],
            vec!["up", "-d", "--no-deps", "cms"],
            vec![
                "up",
                "--no-deps",
                "--force-recreate",
                "--exit-code-from",
                "cms-setup",
                "cms-setup",
            ],
        ];
        let calls = commands
            .into_iter()
            .enumerate()
            .map(|(index, command)| {
                let mut args = compose(&c);
                args.extend(command.into_iter().map(str::to_owned));
                super::super::fake::Call {
                    program: "docker",
                    args,
                    output: if index == 2 {
                        Err(Error::Io)
                    } else {
                        Ok(vec![])
                    },
                }
            })
            .collect();
        super::super::fake::with(calls, || {
            assert!(stage_setup(&c, "fixture", &plan).is_err())
        });
        let state: Value =
            serde_json::from_slice(&fs::read(&status_path(&c), 128 * 1024).unwrap()).unwrap();
        assert_eq!(state["step"], "cms-setup");
    }
    #[test]
    fn progress_writes_preserve_ambiguous_mail_delivery_identity() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = root.path().to_path_buf();
        let journal = root.path().join(".openmates/core-update-delivery.json");
        let identity = json!({"installedVersion":"fixture","updateMode":"image","completionEmailDeliveryId":uuid::Uuid::new_v4().to_string(),"completionEmailDelivery":{"status":"pending","attempts":1},"completionEmailPendingAt":now()});
        fs::write(&journal, &serde_json::to_vec(&identity).unwrap(), 0o600).unwrap();
        step(&c, "fixture", "backup").unwrap();
        let persisted: Value =
            serde_json::from_slice(&fs::read(&journal, 128 * 1024).unwrap()).unwrap();
        assert_eq!(persisted, identity);
    }
}
