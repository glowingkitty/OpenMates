//! Host-side operational-report freshness and durable notification transfer.
use super::*;
#[derive(Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct State {
    #[serde(default)]
    incident_open: bool,
    #[serde(default)]
    incident_opened_at: Option<String>,
    #[serde(default)]
    monitoring_started_at: Option<String>,
    #[serde(default)]
    last_accepted_report_at: Option<String>,
    #[serde(default)]
    pending_event: Option<Value>,
}
fn path(c: &Configuration) -> PathBuf {
    c.install_path.join(format!(
        ".openmates/runtime-health/{}-operational-report.json",
        c.server_role
    ))
}
fn read(c: &Configuration) -> Result<State> {
    let path = path(c);
    if path.try_exists()? {
        Ok(serde_json::from_slice(&fs::read(&path, 1024 * 1024)?)?)
    } else {
        Ok(State::default())
    }
}
fn write(c: &Configuration, state: &State) -> Result<()> {
    fs::write(&path(c), &serde_json::to_vec_pretty(state)?, 0o600)
}
fn evaluate(state: &mut State, timestamp: &str, now: u64) -> Option<Value> {
    let start = state
        .monitoring_started_at
        .get_or_insert_with(|| timestamp.into());
    let selected = state.last_accepted_report_at.as_deref().unwrap_or(start);
    let elapsed =
        time::OffsetDateTime::parse(selected, &time::format_description::well_known::Rfc3339)
            .ok()
            .and_then(|v| u64::try_from(v.unix_timestamp_nanos() / 1_000_000).ok())
            .and_then(|v| now.checked_sub(v));
    let stale = elapsed.is_none_or(|duration| duration > 26 * 60 * 60 * 1000);
    if stale && !state.incident_open {
        state.incident_open = true;
        state.incident_opened_at = Some(timestamp.into());
        Some(json!({"type":"operational_report_stale","reason":"daily_report_stale"}))
    } else if !stale && state.incident_open {
        state.incident_open = false;
        state.incident_opened_at = None;
        Some(json!({"type":"operational_report_recovered","reason":"daily_report_fresh"}))
    } else {
        None
    }
}
fn notification(c: &Configuration, event: &Value, timestamp: &str) -> Value {
    json!({"eventId":uuid::Uuid::new_v4().to_string(),"kind":if event["type"]=="operational_report_recovered"{"recovery"}else{"stale"},"occurredAt":timestamp,"environment":"self_host","deploymentMode":"self_host","role":c.server_role,"checkIds":["operational.report"],"sanitizedReason":event["reason"]})
}
fn completed(c: &Configuration, result: &Value, channels: &[String]) -> Result<Value> {
    let id = result["report_id"]
        .as_str()
        .filter(|s| {
            !s.is_empty()
                && s.len() <= 160
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
        })
        .ok_or(Error::Protocol)?;
    let hash = result["report_sha256"]
        .as_str()
        .filter(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
        .ok_or(Error::Protocol)?;
    if result["environment"] != "self_host" {
        return Err(Error::Protocol);
    }
    let raw = result["receipts"].as_array().ok_or(Error::Protocol)?;
    let mut receipts = vec![];
    let mut seen = std::collections::BTreeSet::new();
    for receipt in raw {
        let channel = receipt["channel"]
            .as_str()
            .filter(|s| channels.iter().any(|c| c == s))
            .ok_or(Error::Protocol)?;
        let state = receipt["state"]
            .as_str()
            .filter(|s| matches!(*s, "queued" | "accepted" | "failed" | "unavailable"))
            .ok_or(Error::Protocol)?;
        let at = receipt["occurred_at"].as_str().ok_or(Error::Protocol)?;
        time::OffsetDateTime::parse(at, &time::format_description::well_known::Rfc3339)
            .map_err(|_| Error::Protocol)?;
        let attempts = receipt["attempt_count"]
            .as_u64()
            .filter(|n| *n <= 10)
            .ok_or(Error::Protocol)?;
        if !seen.insert(channel.to_owned())
            || receipt["environment"] != "self_host"
            || receipt["report_id"] != id
            || receipt["report_sha256"] != hash
        {
            return Err(Error::Protocol);
        }
        let mut output = json!({"environment":"self_host","reportId":id,"reportSha256":hash,"channel":channel,"state":state,"attemptCount":attempts,"occurredAt":at});
        if let Some(reason) = receipt["sanitized_failure_class"].as_str() {
            output["sanitizedFailureClass"] = json!(match reason {
                "missing_admin_email"
                | "missing_discord_webhook"
                | "email_delivery_failed"
                | "discord_delivery_failed" => reason,
                _ => "delivery_failed",
            });
        }
        if let Some(source) = receipt["destination_source"].as_str() {
            output["destinationSource"] = json!(match source {
                "canonical"
                | "missing"
                | "self_host_specific"
                | "self_host_fallback"
                | "prod_smoke_fallback"
                | "dev_smoke_fallback" => source,
                _ => "configured",
            });
        }
        if let Some(fallback) = receipt["fallback_used"].as_bool() {
            output["fallbackUsed"] = json!(fallback);
        }
        receipts.push(output);
    }
    if seen != channels.iter().cloned().collect() {
        return Err(Error::Protocol);
    }
    let all = receipts.iter().all(|r| r["state"] == "accepted");
    let any = receipts.iter().any(|r| r["state"] == "accepted");
    let delivery = if all {
        "accepted"
    } else if any {
        "partial_failure"
    } else {
        "failed"
    };
    if result["delivery_state"] != delivery {
        return Err(Error::Protocol);
    }
    let timestamp = notifications::timestamp()?;
    let receipt_path = c.install_path.join(format!(
        ".openmates/runtime-health/receipts/{}.jsonl",
        &timestamp[..7]
    ));
    let mut lines = if receipt_path.try_exists()? {
        fs::private_read(&receipt_path, 16 * 1024 * 1024)?
    } else {
        vec![]
    };
    for receipt in &receipts {
        serde_json::to_writer(&mut lines, receipt)?;
        lines.push(b'\n');
    }
    fs::write(&receipt_path, &lines, 0o600)?;
    if all {
        let mut state = read(c)?;
        state.incident_open = false;
        state.incident_opened_at = None;
        state.last_accepted_report_at = Some(timestamp);
        write(c, &state)?;
        fs::write(&c.install_path.join(".openmates/runtime-health/metrics/operational-report.prom"),format!("operational_report_last_success_timestamp_seconds{{environment=\"self_host\"}} {}\n",now()/1000).as_bytes(),0o600)?;
    }
    let output = json!({"command":"monitoring digest","status":if all{"success"}else{"degraded"},"reportId":id,"reportSha256":hash,"deliveryState":delivery,"receipts":receipts});
    fs::write(
        &c.install_path.join(format!(
            ".openmates/runtime-health/{}-operational-report-delivery.json",
            c.server_role
        )),
        &serde_json::to_vec_pretty(&output)?,
        0o600,
    )?;
    Ok(output)
}
pub(super) fn digest(c: &Configuration, flags: &Flags) -> Result<Value> {
    let mut channels = text(flags, "channel")
        .unwrap_or("email,discord")
        .split(',')
        .map(str::trim)
        .map(str::to_owned)
        .collect::<Vec<_>>();
    channels.sort();
    channels.dedup();
    if channels.is_empty()
        || channels
            .iter()
            .any(|s| !matches!(s.as_str(), "email" | "discord"))
    {
        return Err(Error::Invalid(
            "Operational digest channels must be email or discord.",
        ));
    }
    let mut result = probes::operational(c, &channels, boolean(flags, "test"))?;
    let output = completed(c, &result, &channels);
    local_models::erase(&mut result);
    output
}
pub(super) fn watchdog(c: &Configuration) -> Result<Value> {
    let mut state = read(c)?;
    let mut delivery = vec![];
    if let Some(pending) = state.pending_event.take() {
        delivery.extend(monitoring::dispatch(c, pending.clone())?);
        write(c, &state)?;
    }
    let timestamp = notifications::timestamp()?;
    let event = evaluate(&mut state, &timestamp, now());
    if let Some(event) = &event {
        state.pending_event = Some(notification(c, event, &timestamp));
    }
    write(c, &state)?;
    if let Some(pending) = state.pending_event.take() {
        delivery.extend(monitoring::dispatch(c, pending)?);
        write(c, &state)?;
    }
    Ok(
        json!({"command":"monitoring report-watchdog","event":event,"delivery":delivery,"state":state}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    fn report(state: &str) -> Value {
        let hash = "a".repeat(64);
        let id = "operational-self_host-fixture";
        json!({"report_id":id,"report_sha256":hash,"environment":"self_host","delivery_state":if state=="accepted"{"accepted"}else{"failed"},"snapshot":{"private":"never projected"},"receipts":[{"environment":"self_host","report_id":id,"report_sha256":hash,"channel":"email","state":state,"attempt_count":1,"occurred_at":"2025-01-01T00:00:00Z","recipient_email":"synthetic-private@example.invalid","sanitized_failure_class":if state=="accepted"{Value::Null}else{json!("unexpected-secret-text")}}]})
    }
    fn fixture() -> (tempfile::TempDir, Configuration) {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = dir.path().into();
        fs::write(
            &c.install_path.join(".env"),
            b"DRAGONFLY_PASSWORD=fixture\n",
            0o600,
        )
        .unwrap();
        (dir, c)
    }
    #[test]
    fn native_digest_dispatch_records_only_redacted_receipts_and_verified_acceptance() {
        let (_dir, c) = fixture();
        let raw = report("accepted");
        let mut args = compose(&c);
        args.extend(
            ["exec", "-T", "cache", "redis-cli", "--csv"]
                .into_iter()
                .map(str::to_owned),
        );
        let call = |output| fake::Call {
            program: "docker",
            args: args.clone(),
            output: Ok(output),
        };
        let result = serde_json::to_string(&json!({"status":"SUCCESS","result":raw})).unwrap();
        let poll = format!("\"OK\"\n{}\n", serde_json::to_string(&result).unwrap()).into_bytes();
        let output = fake::with(
            vec![
                fake::Call {
                    program: "docker",
                    args: {
                        let mut args = compose(&c);
                        args.extend(
                            ["exec", "-T", "cache", "redis-cli", "--csv", "--version"]
                                .map(str::to_owned),
                        );
                        args
                    },
                    output: Ok(b"redis-cli 6.0.16\n".to_vec()),
                },
                call(b"\"OK\"\n1\n".to_vec()),
                call(poll),
                call(b"\"OK\"\n1\n".to_vec()),
            ],
            || {
                digest(
                    &c,
                    &Flags::from([
                        ("channel".into(), json!("email")),
                        ("test".into(), json!(true)),
                    ]),
                )
                .unwrap()
            },
        );
        assert_eq!(output["deliveryState"], "accepted");
        assert!(!output.to_string().contains("synthetic-private"));
        assert!(!output.to_string().contains("snapshot"));
        assert!(read(&c).unwrap().last_accepted_report_at.is_some());
        let failed = completed(&c, &report("failed"), &["email".into()]).unwrap();
        assert_eq!(failed["status"], "degraded");
        assert_eq!(
            failed["receipts"][0]["sanitizedFailureClass"],
            "delivery_failed"
        );
        assert!(completed(&c, &raw, &["email".into(), "discord".into()]).is_err());
        fake::with(vec![], || {
            assert!(digest(&c, &Flags::from([("channel".into(), json!("webhook"))])).is_err())
        });
    }
    #[test]
    fn report_freshness_initializes_then_opens_once_and_recovers() {
        let mut state = State::default();
        let initial = "2025-01-01T00:00:00Z";
        let first = 1735689600000;
        assert!(evaluate(&mut state, initial, first).is_none());
        assert_eq!(
            evaluate(
                &mut state,
                "2025-01-02T03:00:00Z",
                first + 27 * 60 * 60 * 1000
            )
            .unwrap()["type"],
            "operational_report_stale"
        );
        assert!(
            evaluate(
                &mut state,
                "2025-01-02T04:00:00Z",
                first + 28 * 60 * 60 * 1000
            )
            .is_none()
        );
        state.last_accepted_report_at = Some("2025-01-02T04:00:00Z".into());
        assert_eq!(
            evaluate(
                &mut state,
                "2025-01-02T04:00:01Z",
                first + 28 * 60 * 60 * 1000 + 1000
            )
            .unwrap()["type"],
            "operational_report_recovered"
        );
        state.last_accepted_report_at = Some("2099-01-01T00:00:00Z".into());
        assert!(evaluate(&mut state, initial, first).is_some());
    }
    #[test]
    fn stale_report_event_is_transferred_to_durable_native_outbox_without_credentials() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = dir.path().into();
        fs::write(
            &c.install_path.join(".env"),
            b"SERVER_ENVIRONMENT=development\n",
            0o600,
        )
        .unwrap();
        write(
            &c,
            &State {
                monitoring_started_at: Some("2020-01-01T00:00:00Z".into()),
                ..State::default()
            },
        )
        .unwrap();
        let output = watchdog(&c).unwrap();
        assert_eq!(output["event"]["type"], "operational_report_stale");
        assert!(read(&c).unwrap().pending_event.is_none());
        let journal: Value = serde_json::from_slice(
            &fs::read(
                &c.install_path.join(".openmates/runtime-health/core.json"),
                1024 * 1024,
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(
            journal["pendingNotifications"][0]["checkIds"][0],
            "operational.report"
        );
        assert!(watchdog(&c).unwrap()["event"].is_null());
    }
}
