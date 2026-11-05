//! Provider-free Celery protocol probes. Rust creates the task envelopes and
//! verifies synthetic responses; no legacy verifier/application is executed.
use super::*;
use base64::{Engine, engine::general_purpose::STANDARD};
use std::time::{Duration, Instant};
fn quote(value: &str) -> Zeroizing<String> {
    let mut out = Zeroizing::new(String::from("\""));
    for byte in value.bytes() {
        const HEX: &[u8] = b"0123456789abcdef";
        out.push_str("\\x");
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 15) as usize] as char);
    }
    out.push('"');
    out
}
#[derive(Clone, Copy)]
enum Purpose {
    Cache,
    Broker,
    Results,
}
struct Target {
    options: Vec<String>,
    auth: Vec<Zeroizing<String>>,
    database: u32,
}
fn decoded(raw: &str) -> Result<Zeroizing<String>> {
    let mut bytes = Zeroizing::new(Vec::new());
    let raw = raw.as_bytes();
    let mut index = 0;
    while index < raw.len() {
        if raw[index] == b'%' {
            if index + 2 >= raw.len() {
                return Err(Error::Protocol);
            }
            let hex =
                std::str::from_utf8(&raw[index + 1..index + 3]).map_err(|_| Error::Protocol)?;
            bytes.push(u8::from_str_radix(hex, 16).map_err(|_| Error::Protocol)?);
            index += 3;
        } else {
            bytes.push(raw[index]);
            index += 1;
        }
    }
    Ok(Zeroizing::new(
        String::from_utf8(bytes.to_vec()).map_err(|_| Error::Protocol)?,
    ))
}
fn target(content: &str, purpose: Purpose) -> Result<Target> {
    let custom = match purpose {
        Purpose::Cache => None,
        Purpose::Broker => env_get(content, "CELERY_BROKER_URL"),
        Purpose::Results => env_get(content, "CELERY_RESULT_BACKEND"),
    };
    let Some(custom) = custom else {
        return Ok(Target {
            options: vec![],
            database: 0,
            auth: vec![Zeroizing::new(
                env_get(content, "DRAGONFLY_PASSWORD")
                    .ok_or(Error::Invalid("Runtime probe cache password is missing."))?
                    .into(),
            )],
        });
    };
    let url = url::Url::parse(custom)
        .map_err(|_| Error::Invalid("Configured Celery Redis URL is invalid."))?;
    if !matches!(url.scheme(), "redis" | "rediss")
        || url.host_str().is_none()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(Error::Invalid(
            "Native Celery probes require a redis/rediss URL without query or fragment; other broker transports are not supported yet.",
        ));
    }
    let db = url.path().trim_start_matches('/');
    let db = if db.is_empty() {
        0
    } else {
        db.parse::<u32>()
            .map_err(|_| Error::Invalid("Celery Redis database must be a nonnegative integer."))?
    };
    let host = url.host_str().ok_or(Error::Protocol)?;
    let mut options = vec![
        "-h".into(),
        host.into(),
        "-p".into(),
        url.port().unwrap_or(6379).to_string(),
    ];
    if url.scheme() == "rediss" {
        options.extend(["--tls".into(), "--sni".into(), host.into()]);
    }
    let mut auth = vec![];
    if let Some(password) = url.password() {
        if !url.username().is_empty() {
            auth.push(decoded(url.username())?);
        }
        auth.push(decoded(password)?);
    } else if !url.username().is_empty() {
        return Err(Error::Invalid(
            "Celery Redis ACL username requires an explicit password.",
        ));
    }
    Ok(Target {
        options,
        auth,
        database: db,
    })
}
type RedisInvocation<'a> =
    dyn FnMut(&[String], Option<&[operation::InputStage]>) -> Result<Zeroizing<Vec<u8>>> + 'a;
fn invoke_cli(
    c: &Configuration,
    args: &[String],
    stages: Option<&[operation::InputStage]>,
) -> Result<Zeroizing<Vec<u8>>> {
    match stages {
        Some(stages) => run_staged(
            "docker",
            args,
            &c.install_path,
            stages,
            Duration::from_secs(6),
        ),
        None => run_timeout(
            "docker",
            args,
            &c.install_path,
            None,
            Duration::from_secs(6),
        ),
    }
}
fn redis_stage<'a>(
    words: impl IntoIterator<Item = &'a str>,
    validate: fn(&[u8]) -> Result<()>,
) -> operation::InputStage {
    let mut input = Zeroizing::new(String::new());
    for word in words {
        if !input.is_empty() {
            input.push(' ');
        }
        input.push_str(&quote(word));
    }
    input.push('\n');
    operation::InputStage {
        input: Zeroizing::new(input.as_bytes().to_vec()),
        validate,
    }
}
fn csv_ok(line: &[u8]) -> Result<()> {
    if csv_scalar(line)?.as_str() == Some("OK") {
        Ok(())
    } else {
        Err(Error::Protocol)
    }
}
fn csv_integer(line: &[u8]) -> Result<()> {
    if csv_scalar(line)?.as_i64().is_some_and(|n| n >= 0) {
        Ok(())
    } else {
        Err(Error::Protocol)
    }
}
fn csv_get(line: &[u8]) -> Result<()> {
    let value = csv_scalar(line)?;
    if value.is_null() || value.is_string() {
        Ok(())
    } else {
        Err(Error::Protocol)
    }
}
struct RedisCli<'a> {
    c: &'a Configuration,
    content: Zeroizing<String>,
    invoke: &'a mut RedisInvocation<'a>,
}
impl<'a> RedisCli<'a> {
    fn prepare(c: &'a Configuration, invoke: &'a mut RedisInvocation<'a>) -> Result<Self> {
        let mut args = compose(c);
        // Option parsing accepts CSV before --version exits without connecting.
        // Unlike --help, Redis 6/7 version output uses stdout and exits zero.
        args.extend(["exec", "-T", "cache", "redis-cli", "--csv", "--version"].map(str::to_owned));
        let version = invoke(&args, None)?;
        if !canonical_cli_version(&version) {
            return Err(Error::Invalid(
                "Runtime probes require Redis CLI CSV scalar output support.",
            ));
        }
        Ok(Self {
            c,
            content: env(&c.install_path)?,
            invoke,
        })
    }
    fn query(&mut self, commands: &[Vec<String>], purpose: Purpose) -> Result<Vec<Value>> {
        if commands.is_empty() || commands.len() > 16 {
            return Err(Error::Protocol);
        }
        let bytes = commands
            .iter()
            .flatten()
            .try_fold(0usize, |sum, arg| sum.checked_add(arg.len()))
            .ok_or(Error::Protocol)?;
        if bytes > 1024 * 1024 {
            return Err(Error::Protocol);
        }
        for command in commands {
            match command.as_slice() {
                [name, key] if matches!(name.as_str(), "GET" | "DEL") && !key.is_empty() => {}
                [name, key, value]
                    if name == "LPUSH" && !key.is_empty() && value.len() <= 1024 * 1024 => {}
                _ => return Err(Error::Protocol),
            }
            if command.iter().any(|arg| arg.len() > 1024 * 1024) {
                return Err(Error::Protocol);
            }
        }
        let target = target(&self.content, purpose)?;
        let mut stages = vec![];
        if !target.auth.is_empty() {
            stages.push(redis_stage(
                std::iter::once("AUTH").chain(target.auth.iter().map(|s| s.as_str())),
                csv_ok,
            ));
        }
        // CLI -n selects during connect, before our stdin AUTH. Select only
        // after authentication so protected nonzero databases work too.
        if target.database != 0 {
            stages.push(redis_stage(
                ["SELECT", &target.database.to_string()],
                csv_ok,
            ));
        }
        for command in commands {
            stages.push(redis_stage(
                command.iter().map(String::as_str),
                if command[0] == "GET" {
                    csv_get
                } else {
                    csv_integer
                },
            ));
        }
        let mut args = compose(self.c);
        args.extend([
            "exec".into(),
            "-T".into(),
            "cache".into(),
            "redis-cli".into(),
            "--csv".into(),
        ]);
        args.extend(target.options);
        let result = (self.invoke)(&args, Some(&stages))?;
        if result.len() > 1024 * 1024 {
            return Err(Error::Protocol);
        }
        let output = result.strip_suffix(b"\n").ok_or(Error::Protocol)?;
        let authenticated = usize::from(!target.auth.is_empty());
        let prefix = authenticated + usize::from(target.database != 0);
        let mut replies = Vec::with_capacity(commands.len() + prefix);
        for line in output.split(|b| *b == b'\n') {
            if replies.len() >= commands.len() + prefix {
                return Err(Error::Protocol);
            }
            replies.push(csv_scalar(line)?);
        }
        if replies.len() != commands.len() + prefix
            || replies
                .iter()
                .take(prefix)
                .any(|reply| reply.as_str() != Some("OK"))
        {
            return Err(Error::Invalid(
                "Runtime cache command failed or returned an unexpected reply.",
            ));
        }
        let replies: Vec<Value> = replies.into_iter().skip(prefix).collect();
        for (command, reply) in commands.iter().zip(&replies) {
            let valid = match command[0].as_str() {
                "GET" => reply.is_null() || reply.is_string(),
                "LPUSH" | "DEL" => reply.as_i64().is_some_and(|n| n >= 0),
                _ => false,
            };
            if !valid {
                return Err(Error::Protocol);
            }
        }
        Ok(replies)
    }
}
fn canonical_cli_version(bytes: &[u8]) -> bool {
    if bytes.len() > 128 {
        return false;
    }
    let Ok(raw) = std::str::from_utf8(bytes) else {
        return false;
    };
    let Some(version) = raw
        .strip_prefix("redis-cli ")
        .and_then(|s| s.strip_suffix('\n'))
    else {
        return false;
    };
    let mut parts = version.split('.');
    (0..3).all(|_| {
        parts.next().is_some_and(|part| {
            !part.is_empty()
                && part.bytes().all(|b| b.is_ascii_digit())
                && part.parse::<u32>().is_ok_and(|n| n.to_string() == part)
        })
    }) && parts.next().is_none()
}
// Redis CLI CSV uses sdscatrepr's byte-oriented C escapes, not RFC CSV or JSON.
// Only the scalar reply types of our closed command set are accepted.
fn csv_scalar(line: &[u8]) -> Result<Value> {
    if line == b"NULL" {
        return Ok(Value::Null);
    }
    if line.first() != Some(&b'"') {
        let raw = std::str::from_utf8(line).map_err(|_| Error::Protocol)?;
        let integer = raw.parse::<i64>().map_err(|_| Error::Protocol)?;
        if integer.to_string() != raw {
            return Err(Error::Protocol);
        }
        return Ok(json!(integer));
    }
    if line.len() < 2 || line.last() != Some(&b'"') {
        return Err(Error::Protocol);
    }
    let mut decoded = Zeroizing::new(Vec::new());
    let mut index = 1;
    while index < line.len() - 1 {
        let byte = line[index];
        index += 1;
        if byte == b'\\' {
            let escaped = *line.get(index).ok_or(Error::Protocol)?;
            index += 1;
            decoded.push(match escaped {
                b'\\' => b'\\',
                b'"' => b'"',
                b'n' => b'\n',
                b'r' => b'\r',
                b't' => b'\t',
                b'a' => 7,
                b'b' => 8,
                b'x' => {
                    if index + 2 > line.len() - 1 {
                        return Err(Error::Protocol);
                    }
                    let hex = std::str::from_utf8(&line[index..index + 2])
                        .map_err(|_| Error::Protocol)?;
                    if !hex.bytes().all(|b| b.is_ascii_hexdigit()) {
                        return Err(Error::Protocol);
                    }
                    index += 2;
                    u8::from_str_radix(hex, 16).map_err(|_| Error::Protocol)?
                }
                _ => return Err(Error::Protocol),
            });
        } else if byte == b'"' || byte.is_ascii_control() {
            return Err(Error::Protocol);
        } else {
            decoded.push(byte);
        }
    }
    if index != line.len() - 1 {
        return Err(Error::Protocol);
    }
    Ok(json!(
        String::from_utf8(decoded.to_vec()).map_err(|_| Error::Protocol)?
    ))
}
fn message(task: &str, args: Value, id: &str, queue: &str) -> Result<String> {
    if !matches!(
        task,
        "runtime_health.worker_probe"
            | "runtime_health.chat_plumbing_probe"
            | "runtime_health.scheduler_heartbeat"
    ) {
        return Err(Error::Invalid(
            "Only provider-free runtime probe tasks are permitted.",
        ));
    }
    envelope(task, args, json!({}), id, queue)
}
fn envelope(task: &str, args: Value, kwargs: Value, id: &str, queue: &str) -> Result<String> {
    let body = STANDARD.encode(serde_json::to_vec(
        &json!([args,kwargs, {"callbacks":null,"errbacks":null,"chain":null,"chord":null}]),
    )?);
    Ok(json!({"body":body,"content-encoding":"utf-8","content-type":"application/json","headers":{"lang":"py","task":task,"id":id,"shadow":null,"eta":null,"expires":null,"group":null,"group_index":null,"retries":0,"timelimit":[null,null],"root_id":id,"parent_id":null,"argsrepr":"<native runtime probe>","kwargsrepr":"{}","origin":"native-runtime-verifier","ignore_result":false},"properties":{"correlation_id":id,"reply_to":uuid::Uuid::new_v4().to_string(),"delivery_mode":2,"delivery_info":{"exchange":"","routing_key":queue},"priority":0,"body_encoding":"base64","delivery_tag":uuid::Uuid::new_v4().to_string()}}).to_string())
}
fn task(redis: &mut RedisCli<'_>, name: &str, args: Value, queue: &str) -> Result<Value> {
    let id = uuid::Uuid::new_v4().to_string();
    let envelope = message(name, args, &id, queue)?;
    wait_task(redis, &id, envelope, queue, Duration::from_secs(12))
}
pub(super) fn operational(c: &Configuration, channels: &[String], test: bool) -> Result<Value> {
    if c.server_role != "core"
        || channels.is_empty()
        || channels
            .iter()
            .any(|s| !matches!(s.as_str(), "email" | "discord"))
    {
        return Err(Error::Invalid(
            "Operational digest requires a core install and email or discord channels.",
        ));
    }
    let id = uuid::Uuid::new_v4().to_string();
    let envelope = operational_envelope(channels, test, &id)?;
    let mut invoke =
        |args: &[String], stages: Option<&[operation::InputStage]>| invoke_cli(c, args, stages);
    let mut redis = RedisCli::prepare(c, &mut invoke)?;
    wait_task(&mut redis, &id, envelope, "email", Duration::from_secs(120))
}
fn operational_envelope(channels: &[String], test: bool, id: &str) -> Result<String> {
    envelope(
        "operational_monitoring.send_digest",
        json!([]),
        json!({"environment":"self_host","channels":channels,"test":test}),
        id,
        "email",
    )
}
fn wait_task(
    redis: &mut RedisCli<'_>,
    id: &str,
    envelope: String,
    queue: &str,
    deadline: Duration,
) -> Result<Value> {
    let key = format!("celery-task-meta-{id}");
    let pushed = redis.query(
        &[vec!["LPUSH".into(), queue.into(), envelope]],
        Purpose::Broker,
    )?;
    if !pushed[0].as_i64().is_some_and(|n| n > 0) {
        return Err(Error::Protocol);
    }
    let start = Instant::now();
    let result = (|| loop {
        let result = redis.query(&[vec!["GET".into(), key.clone()]], Purpose::Results)?;
        if let Some(text) = result[0].as_str() {
            let data: Value = serde_json::from_str(text)?;
            match data["status"].as_str() {
                Some("SUCCESS") => return Ok(data["result"].clone()),
                Some("FAILURE" | "REVOKED") => {
                    return Err(Error::Invalid("Provider-free worker runtime probe failed."));
                }
                _ => {}
            }
        }
        if start.elapsed() >= deadline {
            return Err(Error::Invalid(
                "Provider-free worker runtime probe exceeded its deadline.",
            ));
        }
        std::thread::sleep(Duration::from_millis(200));
    })();
    let cleanup = redis.query(&[vec!["DEL".into(), key]], Purpose::Results)?;
    if !cleanup[0].is_number() {
        return Err(Error::Protocol);
    }
    result
}
pub(super) fn verify(c: &Configuration, verification: &mut update::Verification<'_>) -> Result<()> {
    if c.server_role == "core" {
        let mut invoke =
            |args: &[String], stages: Option<&[operation::InputStage]>| invoke_cli(c, args, stages);
        let mut redis = verification.check("core.redis_cli_capability", || {
            RedisCli::prepare(c, &mut invoke)
        })?;
        verification.check("core.worker_queue", || {
            let probe = uuid::Uuid::new_v4().simple().to_string();
            let result = task(
                &mut redis,
                "runtime_health.worker_probe",
                json!([probe]),
                "app_ai",
            )?;
            if result["probe_id"] != probe {
                return Err(Error::Invalid("Worker probe identity did not match."));
            }
            Ok(())
        })?;
        verification.check("core.scheduler_freshness", || {
            let heartbeat = redis.query(
                &[vec![
                    "GET".into(),
                    "runtime_health:scheduler:last_seen".into(),
                ]],
                Purpose::Cache,
            )?;
            let stamp = heartbeat[0]
                .as_str()
                .and_then(|s| s.parse::<u64>().ok())
                .unwrap_or(0);
            let seconds = now() / 1000;
            if stamp > seconds + 60 || seconds.saturating_sub(stamp) > 15 * 60 {
                task(
                    &mut redis,
                    "runtime_health.scheduler_heartbeat",
                    json!([]),
                    "health_check",
                )?;
                let heartbeat = redis.query(
                    &[vec![
                        "GET".into(),
                        "runtime_health:scheduler:last_seen".into(),
                    ]],
                    Purpose::Cache,
                )?;
                let stamp = heartbeat[0]
                    .as_str()
                    .and_then(|s| s.parse::<u64>().ok())
                    .unwrap_or(0);
                if stamp > seconds + 60 || seconds.saturating_sub(stamp) > 15 * 60 {
                    return Err(Error::Invalid("Scheduler heartbeat is stale."));
                }
            }
            Ok(())
        })?;
        verification.check("core.chat_plumbing", || {
            let probe = uuid::Uuid::new_v4().simple().to_string();
            let result = task(
                &mut redis,
                "runtime_health.chat_plumbing_probe",
                json!([probe]),
                "app_ai",
            )?;
            if result["probe_id"] != probe
                || result["transport"] != "redis"
                || result["cleanup_status"] != "completed"
            {
                return Err(Error::Invalid(
                    "Chat plumbing runtime probe did not confirm cleanup.",
                ));
            }
            Ok(())
        })?;
    } else if c.server_role == "upload" {
        verification.check("upload.antivirus", || {
            let mut args = compose(c);
            args.extend([
                "exec".into(),
                "-T".into(),
                "clamav".into(),
                "clamdscan".into(),
                "--ping=1".into(),
            ]);
            run_timeout(
                "docker",
                &args,
                &c.install_path,
                None,
                Duration::from_secs(10),
            )?;
            Ok(())
        })?;
    } else {
        // Role health is the preview renderer's own health endpoint.
        verification.check("preview.renderer", || Ok(()))?;
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    fn configuration() -> (tempfile::TempDir, Configuration) {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = dir.path().into();
        fs::write(&c.install_path.join(".env"), b"DRAGONFLY_PASSWORD=cache-fixture\nCELERY_BROKER_URL=redis://acl:p%40ss%25word@broker.example.invalid:6380/2\nCELERY_RESULT_BACKEND=rediss://:result-fixture@results.example.invalid:6381/4\n", 0o600).unwrap();
        (dir, c)
    }
    fn input_commands(stages: &[operation::InputStage]) -> Vec<Vec<String>> {
        stages
            .iter()
            .flat_map(|stage| std::str::from_utf8(&stage.input).unwrap().lines())
            .map(|line| {
                line.split(' ')
                    .map(|token| {
                        if token == "AUTH" {
                            token.into()
                        } else {
                            csv_scalar(token.as_bytes())
                                .unwrap()
                                .as_str()
                                .unwrap()
                                .into()
                        }
                    })
                    .collect()
            })
            .collect()
    }
    // The shell is only a synthetic test child. Application dialogue, CSV
    // parsing, cancellation and command release all run through Rust below.
    const DIALOGUE_FIXTURE: &str = r#"
printf '%s\n' "$$" > "$PID_FILE"
current=0
database=0
while IFS= read -r line; do
  current=$((current + 1))
  printf '%s\n' "$line" >> "$COMMANDS"
  if [ "$current" -eq "$FAIL_STAGE" ]; then
    case "$REPLY_MODE" in
      error) printf 'ERROR,"denied"\n' ;;
      wrong) printf '"NO"\n' ;;
      extra) printf '"OK"\n"OK"\n' ;;
      partial) printf '"OK"\ntrailing' ;;
      missing) : ;;
      eof) exit 0 ;;
    esac
  elif [ "$current" -eq 1 ]; then
    printf '"OK"\n'
  elif [ "$current" -eq 2 ]; then
    database=2
    printf '"OK"\n'
  else
    printf 'mutation db=%s\n' "$database" >> "$MUTATIONS"
    printf '1\n'
  fi
done
"#;
    fn dialogue_query(
        c: &Configuration,
        mode: &str,
        failed: usize,
        timeout: Duration,
    ) -> Result<Vec<Value>> {
        let script = c.install_path.join("synthetic-redis-cli.sh");
        std::fs::write(&script, DIALOGUE_FIXTURE).unwrap();
        let mut invoke = |args: &[String], stages: Option<&[operation::InputStage]>| {
            if let Some(stages) = stages {
                let mut command = Command::new("/bin/sh");
                command
                    .arg(&script)
                    .env("PID_FILE", c.install_path.join("child-pid"))
                    .env("COMMANDS", c.install_path.join("received"))
                    .env("MUTATIONS", c.install_path.join("mutations"))
                    .env("FAIL_STAGE", failed.to_string())
                    .env("REPLY_MODE", mode);
                operation::test_staged(command, stages, timeout)
            } else {
                assert_eq!(&args[args.len() - 2..], ["--csv", "--version"]);
                Ok(Zeroizing::new(b"redis-cli 6.0.16\n".to_vec()))
            }
        };
        let mut redis = RedisCli::prepare(c, &mut invoke)?;
        // These are the actual production query stage constructors, including
        // AUTH and the selected nonzero database, not reconstructed stages.
        redis.query(
            &[
                vec![
                    "LPUSH".into(),
                    "fixture-queue".into(),
                    "fixture-value".into(),
                ],
                vec!["DEL".into(), "fixture-key".into()],
            ],
            Purpose::Broker,
        )
    }
    fn received(c: &Configuration) -> Vec<Vec<String>> {
        let raw = std::fs::read_to_string(c.install_path.join("received")).unwrap();
        raw.lines()
            .map(|line| {
                line.split(' ')
                    .map(|word| {
                        csv_scalar(word.as_bytes())
                            .unwrap()
                            .as_str()
                            .unwrap()
                            .into()
                    })
                    .collect()
            })
            .collect()
    }
    fn assert_child_reaped(c: &Configuration) {
        let pid = std::fs::read_to_string(c.install_path.join("child-pid"))
            .unwrap()
            .trim()
            .parse::<i32>()
            .unwrap();
        assert_eq!(
            rustix::process::test_kill_process(rustix::process::Pid::from_raw(pid).unwrap()),
            Err(rustix::io::Errno::SRCH)
        );
    }
    #[test]
    fn csv_actual_dialogue_never_releases_mutations_after_rejected_auth_or_select() {
        for failed in [1, 2] {
            for mode in ["error", "wrong", "extra", "partial", "missing", "eof"] {
                let (_dir, c) = configuration();
                let started = Instant::now();
                let result = dialogue_query(&c, mode, failed, Duration::from_millis(300));
                assert!(result.is_err(), "stage {failed}, {mode}");
                assert!(started.elapsed() < Duration::from_secs(3));
                let commands = received(&c);
                assert_eq!(commands.len(), failed, "later command was released: {mode}");
                assert_eq!(commands[0], ["AUTH", "acl", "p@ss%word"]);
                if failed == 2 {
                    assert_eq!(commands[1], ["SELECT", "2"]);
                }
                assert!(
                    !c.install_path.join("mutations").exists(),
                    "wrong-database side effect: {mode}"
                );
                assert_child_reaped(&c);
            }
        }
    }
    #[test]
    fn csv_actual_dialogue_success_waits_for_auth_and_nonzero_select_ack() {
        let (_dir, c) = configuration();
        assert_eq!(
            dialogue_query(&c, "good", 0, Duration::from_secs(3)).unwrap(),
            vec![json!(1), json!(1)]
        );
        assert_eq!(
            received(&c),
            [
                vec!["AUTH", "acl", "p@ss%word"],
                vec!["SELECT", "2"],
                vec!["LPUSH", "fixture-queue", "fixture-value"],
                vec!["DEL", "fixture-key"]
            ]
        );
        assert_eq!(
            std::fs::read_to_string(c.install_path.join("mutations")).unwrap(),
            "mutation db=2\nmutation db=2\n"
        );
        assert_child_reaped(&c);
    }
    #[test]
    fn csv_actual_dialogue_cancellation_reaps_child_before_mutations() {
        let (_dir, c) = configuration();
        let cancel = tokio_util::sync::CancellationToken::new();
        let _scope = operation::Scope::new(&cancel);
        let signal = cancel.clone();
        let record = c.install_path.join("received");
        let notifier = std::thread::spawn(move || {
            for _ in 0..200 {
                if std::fs::read_to_string(&record).is_ok_and(|s| s.lines().count() == 2) {
                    break;
                }
                std::thread::sleep(Duration::from_millis(5));
            }
            signal.cancel();
        });
        let started = Instant::now();
        let result = dialogue_query(&c, "missing", 2, Duration::from_secs(5));
        notifier.join().unwrap();
        assert_eq!(result, Err(Error::Cancelled));
        assert!(started.elapsed() < Duration::from_secs(3));
        assert_eq!(received(&c).len(), 2);
        assert!(!c.install_path.join("mutations").exists());
        assert_child_reaped(&c);
    }
    #[test]
    fn csv_legacy_cli_prepares_once_and_exercises_authenticated_task_round_trip() {
        let (_dir, c) = configuration();
        let id = "fixture-task-id";
        let probe = "Unicode é🦀 control\n\t\0 quote\" slash\\";
        let response = json!({"status":"SUCCESS","result":{"probe_id":probe}}).to_string();
        let response_csv = serde_json::to_string(&response).unwrap();
        let mut calls = 0;
        let mut invoke = |args: &[String],
                          input: Option<&[operation::InputStage]>|
         -> Result<Zeroizing<Vec<u8>>> {
            // A legacy client rejects JSON mode. Production must never try it
            // and must not recover from an arbitrary command failure.
            if args.iter().any(|s| s == "--json") {
                return Err(Error::Invalid(
                    "Legacy fixture rejects unsupported JSON output.",
                ));
            }
            let current = calls;
            calls += 1;
            let mut expected = compose(&c);
            if current == 0 {
                expected.extend(
                    ["exec", "-T", "cache", "redis-cli", "--csv", "--version"].map(str::to_owned),
                );
                assert_eq!(args, expected);
                assert!(input.is_none());
                return Ok(Zeroizing::new(b"redis-cli 6.0.16\n".to_vec()));
            }
            expected.extend(["exec", "-T", "cache", "redis-cli"].map(str::to_owned));
            expected.push("--csv".into());
            expected.extend(
                target(
                    &env(&c.install_path)?,
                    if current == 1 {
                        Purpose::Broker
                    } else {
                        Purpose::Results
                    },
                )?
                .options,
            );
            assert_eq!(args, expected);
            assert!(!args.join(" ").contains("p@ss%word"));
            assert!(!args.join(" ").contains("result-fixture"));
            let commands = input_commands(input.expect("zeroized stdin carries AUTH and commands"));
            assert_eq!(commands.len(), 3);
            assert_eq!(
                commands[0],
                if current == 1 {
                    vec!["AUTH", "acl", "p@ss%word"]
                } else {
                    vec!["AUTH", "result-fixture"]
                }
            );
            assert_eq!(
                commands[1],
                if current == 1 {
                    vec!["SELECT", "2"]
                } else {
                    vec!["SELECT", "4"]
                }
            );
            assert!(
                !args.iter().any(|s| s == "-n"),
                "database selection must follow stdin AUTH"
            );
            let result = match current {
                1 => {
                    assert_eq!(commands[2][..2], ["LPUSH", "app_ai"]);
                    let envelope: Value = serde_json::from_str(&commands[2][2]).unwrap();
                    assert_eq!(envelope["headers"]["task"], "runtime_health.worker_probe");
                    let body: Value = serde_json::from_slice(
                        &STANDARD.decode(envelope["body"].as_str().unwrap()).unwrap(),
                    )
                    .unwrap();
                    assert_eq!(body[0], json!([probe]));
                    "\"OK\"\n\"OK\"\n1\n".into()
                }
                2 | 3 => {
                    assert_eq!(commands[2], vec!["GET", "celery-task-meta-fixture-task-id"]);
                    if current == 2 {
                        "\"OK\"\n\"OK\"\nNULL\n".into()
                    } else {
                        format!("\"OK\"\n\"OK\"\n{response_csv}\n")
                    }
                }
                4 => {
                    assert_eq!(commands[2], vec!["DEL", "celery-task-meta-fixture-task-id"]);
                    "\"OK\"\n\"OK\"\n1\n".into()
                }
                _ => panic!("unexpected invocation; capability must be prepared once"),
            };
            Ok(Zeroizing::new(result.into_bytes()))
        };
        assert!(invoke(&["--json".into()], None).is_err());
        let mut redis = RedisCli::prepare(&c, &mut invoke).unwrap();
        let envelope =
            message("runtime_health.worker_probe", json!([probe]), id, "app_ai").unwrap();
        let result = wait_task(&mut redis, id, envelope, "app_ai", Duration::from_secs(2)).unwrap();
        assert_eq!(result, json!({"probe_id":probe}));
        assert_eq!(calls, 5);
    }
    #[test]
    fn csv_capability_is_required_before_authentication_or_mutation() {
        for version in [
            b"  --csv Output CSV.\n".to_vec(),
            b"redis-cli 6.0.16\nextra output\n".to_vec(),
            vec![0xff],
            vec![b'a'; 129],
        ] {
            let c = super::super::tests::c();
            let mut calls = 0;
            let mut invoke = |args: &[String], input: Option<&[operation::InputStage]>| {
                calls += 1;
                assert_eq!(&args[args.len() - 2..], ["--csv", "--version"]);
                assert!(
                    input.is_none(),
                    "unsupported capability must never send credentials"
                );
                Ok(Zeroizing::new(version.clone()))
            };
            assert!(RedisCli::prepare(&c, &mut invoke).is_err());
            assert_eq!(calls, 1);
        }
    }
    #[test]
    fn csv_version_capability_requires_canonical_output_and_successful_flag_parse() {
        for valid in [b"redis-cli 6.0.16\n".as_slice(), b"redis-cli 7.2.0\n"] {
            assert!(canonical_cli_version(valid));
        }
        for invalid in [
            b"redis-cli 6.0.16".as_slice(),
            b"redis-cli 06.0.16\n",
            b"redis-cli 6.0\n",
            b"redis-cli 6.0.16.extra\n",
            b"redis-cli 6.0.16 \n",
            b"other-cli 6.0.16\n",
            b"redis-cli 6.0.16\r\n",
            b"redis-cli 6.0.16\n\n",
        ] {
            assert!(!canonical_cli_version(invalid));
        }
        let c = super::super::tests::c();
        for error in [
            Error::Invalid("Legacy fixture rejects unsupported CSV flag."),
            Error::Io,
            Error::Cancelled,
        ] {
            let mut calls = 0;
            let mut invoke = |args: &[String], input: Option<&[operation::InputStage]>| {
                calls += 1;
                assert_eq!(&args[args.len() - 2..], ["--csv", "--version"]);
                assert!(input.is_none());
                Err(error)
            };
            assert!(matches!(RedisCli::prepare(&c, &mut invoke), Err(actual) if actual == error));
            assert_eq!(calls, 1);
        }
    }
    #[test]
    fn csv_scalar_decodes_redis_byte_escapes_and_rejects_other_protocols() {
        let pairs: &[(&[u8], Value)] = &[
            (b"\"OK\"", json!("OK")),
            (b"NULL", Value::Null),
            (b"0", json!(0)),
            (b"9223372036854775807", json!(i64::MAX)),
            (b"\"\"", json!("")),
            (
                br#""quote\" slash\\ nl\n cr\r tab\t bell\a back\b nul\x00 vertical\x0b form\x0c""#,
                json!(
                    "quote\" slash\\ nl\n cr\r tab\t bell\u{7} back\u{8} nul\0 vertical\u{b} form\u{c}"
                ),
            ),
            (br#""\xc3\xa9\xf0\x9f\xa6\x80""#, json!("é🦀")),
            ("\"é🦀\"".as_bytes(), json!("é🦀")),
            (b"\"NULL\"", json!("NULL")),
            (b"\"1,2\"", json!("1,2")),
        ];
        for (wire, expected) in pairs {
            assert_eq!(csv_scalar(wire).unwrap(), *expected);
        }
        let invalid: &[&[u8]] = &[
            b"",
            b"OK",
            b"ERROR,\"NOAUTH\"",
            b"1,2",
            b"\"one\",\"two\"",
            b"\"one\"garbage\"",
            b"\"missing",
            br#""unknown\u1234""#,
            br#""bad\xg0""#,
            br#""bad\x1""#,
            br#""bad\q""#,
            br#""\xff""#,
            b"\"raw\ncontrol\"",
            b"true",
            b"1.5",
            b"01",
            b"+1",
            b"-0",
            b"9223372036854775808",
            b"NULL ",
            b"\"raw\xff\"",
        ];
        for wire in invalid {
            assert_eq!(csv_scalar(wire), Err(Error::Protocol), "{wire:?}");
        }
    }
    #[test]
    fn csv_query_rejects_auth_type_reply_cardinality_and_command_mismatches() {
        let (_dir, c) = configuration();
        let cases: &[(&[&str], &[u8])] = &[
            (&["LPUSH", "q", "value"], b"\"NO\"\n1\n"),
            (&["LPUSH", "q", "value"], b"1\n1\n"),
            (&["LPUSH", "q", "value"], b"\"OK\"\n\"1\"\n"),
            (&["LPUSH", "q", "value"], b"\"OK\"\n-1\n"),
            (&["DEL", "key"], b"\"OK\"\nNULL\n"),
            (&["GET", "key"], b"\"OK\"\n1\n"),
            (&["GET", "key"], b"\"OK\"\nERROR,\"NOAUTH\"\n"),
            (&["GET", "key"], b"\"OK\"\nNULL"),
            (&["GET", "key"], b"\"OK\"\n"),
            (&["GET", "key"], b"\"OK\"\nNULL\n1\n"),
            (&["GET", "key"], b"\"OK\"\nNULL\n\n"),
        ];
        for (command, wire) in cases {
            let mut calls = 0;
            let mut invoke = |args: &[String], _input: Option<&[operation::InputStage]>| {
                calls += 1;
                Ok(Zeroizing::new(
                    if args.last().is_some_and(|s| s == "--version") {
                        b"redis-cli 6.0.16\n".to_vec()
                    } else {
                        wire.to_vec()
                    },
                ))
            };
            let mut redis = RedisCli::prepare(&c, &mut invoke).unwrap();
            assert!(
                redis
                    .query(
                        &[command.iter().map(|s| (*s).into()).collect()],
                        Purpose::Cache
                    )
                    .is_err()
            );
            assert_eq!(calls, 2);
        }
        let mut calls = 0;
        let mut invoke = |_args: &[String], input: Option<&[operation::InputStage]>| {
            calls += 1;
            assert!(input.is_none());
            Ok(Zeroizing::new(b"redis-cli 6.0.16\n".to_vec()))
        };
        let mut redis = RedisCli::prepare(&c, &mut invoke).unwrap();
        for command in [
            vec!["EVAL", "return 1", "0"],
            vec!["GET"],
            vec!["DEL", "a", "b"],
            vec!["GET", ""],
        ] {
            assert_eq!(
                redis.query(
                    &[command.into_iter().map(str::to_owned).collect()],
                    Purpose::Cache
                ),
                Err(Error::Protocol)
            );
        }
        assert_eq!(calls, 1);
    }
    #[test]
    fn csv_nonzero_database_requires_select_ok_after_optional_auth() {
        let (_dir, c) = configuration();
        let mut invoke = |args: &[String], input: Option<&[operation::InputStage]>| {
            if args.last().is_some_and(|s| s == "--version") {
                return Ok(Zeroizing::new(b"redis-cli 6.0.16\n".to_vec()));
            }
            let commands = input_commands(input.unwrap());
            assert_eq!(
                commands[..2],
                [vec!["AUTH", "acl", "p@ss%word"], vec!["SELECT", "2"]]
            );
            Ok(Zeroizing::new(b"\"OK\"\n\"NO\"\n1\n".to_vec()))
        };
        let mut redis = RedisCli::prepare(&c, &mut invoke).unwrap();
        assert!(
            redis
                .query(
                    &[vec!["LPUSH".into(), "q".into(), "value".into()]],
                    Purpose::Broker
                )
                .is_err()
        );
        let mut invoke = |args: &[String], input: Option<&[operation::InputStage]>| {
            if args.last().is_some_and(|s| s == "--version") {
                return Ok(Zeroizing::new(b"redis-cli 6.0.16\n".to_vec()));
            }
            assert_eq!(
                input_commands(input.unwrap()),
                [vec!["SELECT", "3"], vec!["GET", "key"]]
            );
            Ok(Zeroizing::new(b"\"OK\"\nNULL\n".to_vec()))
        };
        fs::write(
            &c.install_path.join(".env"),
            b"CELERY_RESULT_BACKEND=redis://results.example.invalid/3\n",
            0o600,
        )
        .unwrap();
        let mut redis = RedisCli::prepare(&c, &mut invoke).unwrap();
        assert_eq!(
            redis
                .query(&[vec!["GET".into(), "key".into()]], Purpose::Results)
                .unwrap(),
            vec![Value::Null]
        );
    }
    #[test]
    fn separate_redis_broker_and_result_database_credentials_never_enter_argv() {
        let env = "DRAGONFLY_PASSWORD=cache-fixture\nCELERY_BROKER_URL=redis://acl:p%40ss%25word@broker.example.invalid:6380/2\nCELERY_RESULT_BACKEND=rediss://:result-fixture@results.example.invalid:6381/4\n";
        let broker = target(env, Purpose::Broker).unwrap();
        assert_eq!(
            broker.options,
            vec!["-h", "broker.example.invalid", "-p", "6380"]
        );
        assert_eq!(broker.database, 2);
        assert_eq!(broker.auth[0].as_str(), "acl");
        assert_eq!(broker.auth[1].as_str(), "p@ss%word");
        assert!(!broker.options.join(" ").contains("p@ss"));
        let results = target(env, Purpose::Results).unwrap();
        assert_eq!(
            results.options,
            vec![
                "-h",
                "results.example.invalid",
                "-p",
                "6381",
                "--tls",
                "--sni",
                "results.example.invalid"
            ]
        );
        assert_eq!(results.database, 4);
        assert_eq!(results.auth[0].as_str(), "result-fixture");
        assert_eq!(
            target(env, Purpose::Cache).unwrap().auth[0].as_str(),
            "cache-fixture"
        );
        assert!(target("CELERY_BROKER_URL=amqp://host\n", Purpose::Broker).is_err());
        assert!(target("CELERY_BROKER_URL=redis://host/-1\n", Purpose::Broker).is_err());
        assert!(
            target(
                "CELERY_BROKER_URL=rediss://host/0?ssl_cert_reqs=none\n",
                Purpose::Broker
            )
            .is_err()
        );
    }
    #[test]
    fn operational_envelope_uses_existing_email_task_and_validated_keyword_arguments() {
        let id = uuid::Uuid::new_v4().to_string();
        let message: Value =
            serde_json::from_str(&operational_envelope(&["email".into()], true, &id).unwrap())
                .unwrap();
        assert_eq!(
            message["headers"]["task"],
            "operational_monitoring.send_digest"
        );
        assert_eq!(
            message["properties"]["delivery_info"]["routing_key"],
            "email"
        );
        let body: Value =
            serde_json::from_slice(&STANDARD.decode(message["body"].as_str().unwrap()).unwrap())
                .unwrap();
        assert_eq!(body[0], json!([]));
        assert_eq!(
            body[1],
            json!({"environment":"self_host","channels":["email"],"test":true})
        );
    }
    #[test]
    fn task_envelope_is_provider_free_correlated_and_binary_safe() {
        let encoded = message(
            "runtime_health.worker_probe",
            json!(["probe"]),
            "id",
            "app_ai",
        )
        .unwrap();
        let data: Value = serde_json::from_str(&encoded).unwrap();
        assert_eq!(data["headers"]["task"], "runtime_health.worker_probe");
        assert_eq!(data["properties"]["correlation_id"], "id");
        assert_eq!(data["properties"]["delivery_info"]["routing_key"], "app_ai");
        let body: Value =
            serde_json::from_slice(&STANDARD.decode(data["body"].as_str().unwrap()).unwrap())
                .unwrap();
        assert_eq!(body[0], json!(["probe"]));
        assert_eq!(body[1], json!({}));
        assert!(message("ai.generate", json!([]), "id", "app_ai").is_err());
        assert_eq!(quote("a\"\n").as_str(), "\"\\x61\\x22\\x0a\"");
    }
}
