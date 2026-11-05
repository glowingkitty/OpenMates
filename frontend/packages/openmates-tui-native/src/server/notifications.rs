//! Host notification delivery with bounded responses and pinned webhook DNS.
use super::*;
use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::{
    net::{IpAddr, SocketAddr},
    time::Duration,
};
pub(super) fn timestamp() -> Result<String> {
    time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc3339)
        .map_err(|_| Error::Io)
}
fn value(content: &str, key: &str) -> Option<Zeroizing<String>> {
    // Fixture tests never inspect or use notification credentials installed in
    // the execution host's environment.
    #[cfg(not(test))]
    let process = std::env::var(key).ok();
    #[cfg(test)]
    let process: Option<String> = None;
    process
        .or_else(|| env_get(content, key).map(str::to_owned))
        .filter(|s| !s.trim().is_empty() && s != "IMPORTED_TO_VAULT")
        .map(Zeroizing::new)
}
fn configured(content: &str, key: &str, fallback: &str) -> Option<Zeroizing<String>> {
    value(content, key).or_else(|| value(content, fallback))
}
fn public(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => {
            let b = ip.octets();
            !(ip.is_unspecified()
                || ip.is_loopback()
                || ip.is_private()
                || ip.is_link_local()
                || ip.is_multicast()
                || ip.is_broadcast()
                || b[0] == 0
                || b[0] >= 240
                || b[0] == 100 && (64..=127).contains(&b[1])
                || b[0] == 192 && b[1] == 0
                || b[0] == 198 && matches!(b[1], 18 | 19 | 51)
                || b[0] == 203 && b[1] == 0 && b[2] == 113)
        }
        IpAddr::V6(ip) => {
            if let Some(v4) = ip.to_ipv4_mapped() {
                return public(IpAddr::V4(v4));
            }
            let b = ip.octets();
            b[0] & 0xe0 == 0x20
                && b[..2] != [0x20, 0x02]
                && b[..2] != [0x3f, 0xff]
                && !(b[..2] == [0x20, 0x01] && u16::from_be_bytes([b[2], b[3]]) < 0x0200)
                && !(ip.is_unspecified()
                    || ip.is_loopback()
                    || ip.is_multicast()
                    || ip.is_unique_local()
                    || ip.is_unicast_link_local()
                    || b[..4] == [0x20, 0x01, 0x0d, 0xb8]
                    || b[..12] == [0; 12])
        }
    }
}
fn validate_url(raw: &str, addresses: &[SocketAddr], allow_fixture: bool) -> Result<url::Url> {
    let url =
        url::Url::parse(raw).map_err(|_| Error::Invalid("Notification destination is invalid."))?;
    let fixture = allow_fixture
        && url.scheme() == "http"
        && matches!(
            url.host_str(),
            Some("localhost" | "127.0.0.1" | "[::1]" | "::1")
        )
        && addresses.iter().all(|a| a.ip().is_loopback());
    if !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
        || addresses.is_empty()
        || (!fixture
            && (url.scheme() != "https"
                || url.port_or_known_default() != Some(443)
                || addresses.iter().any(|a| !public(a.ip()))))
    {
        return Err(Error::Invalid(
            "Notification webhook requires HTTPS and a public pinned destination.",
        ));
    }
    Ok(url)
}
struct PostResponse {
    status: u16,
    body: Value,
}
async fn post(
    url: &str,
    headers: &[(String, String)],
    body: &Value,
    allow_fixture: bool,
) -> Result<PostResponse> {
    let parsed = url::Url::parse(url).map_err(|_| Error::Protocol)?;
    let hostname = parsed.host_str().ok_or(Error::Protocol)?;
    let port = parsed.port_or_known_default().ok_or(Error::Protocol)?;
    let addresses = tokio::time::timeout(
        Duration::from_secs(5),
        tokio::net::lookup_host((hostname, port)),
    )
    .await
    .map_err(|_| Error::Offline)??
    .collect::<Vec<_>>();
    validate_url(url, &addresses, allow_fixture)?;
    let client = reqwest::Client::builder()
        .no_proxy()
        .resolve_to_addrs(hostname, &addresses)
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(10))
        .build()?;
    let mut request = client.post(url).json(body);
    for (key, value) in headers {
        request = request.header(key, value);
    }
    let mut response = request.send().await?;
    let status = response.status();
    let mut bytes = Zeroizing::new(Vec::new());
    while let Some(chunk) = response.chunk().await? {
        if bytes.len() + chunk.len() > 64 * 1024 {
            return Err(Error::Protocol);
        }
        bytes.extend_from_slice(&chunk);
    }
    let result = if bytes.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&bytes).unwrap_or(Value::Null)
    };
    let brevo = parsed.host_str() == Some("api.brevo.com")
        && parsed.path() == "/v3/smtp/email"
        && super::brevo::accepted(status.as_u16(), &result, body);
    if !status.is_success() && !brevo {
        return Err(Error::Offline);
    }
    Ok(PostResponse {
        status: status.as_u16(),
        body: result,
    })
}
pub(super) fn deliver(
    c: &Configuration,
    event: &Value,
    requested: Option<&str>,
) -> Result<Vec<Value>> {
    let content = env(&c.install_path)?;
    let mut deliveries = vec![];
    let to = configured(
        &content,
        "OPENMATES_RUNTIME_HEALTH_EMAIL_TO",
        "ADMIN_NOTIFY_EMAIL",
    );
    let api_key = configured(
        &content,
        "OPENMATES_RUNTIME_HEALTH_BREVO_API_KEY",
        "BREVO_API_KEY",
    );
    let from = configured(
        &content,
        "OPENMATES_RUNTIME_HEALTH_EMAIL_FROM",
        "EMAIL_SENDER_EMAIL",
    )
    .unwrap_or_else(|| Zeroizing::new("noreply@openmates.org".into()));
    let discord = configured(
        &content,
        "DISCORD_WEBHOOK_OPERATIONAL_MONITORING_SELF_HOST",
        "OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_SELF_HOST",
    )
    .or_else(|| value(&content, "OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL"));
    let webhook = value(&content, "OPENMATES_RUNTIME_HEALTH_WEBHOOK_URL");
    let secret = value(&content, "OPENMATES_RUNTIME_HEALTH_WEBHOOK_SECRET");
    let requested = requested.map(|s| s.split(',').map(str::trim).collect::<Vec<_>>());
    if requested.as_ref().is_some_and(|v| {
        v.iter()
            .any(|s| !matches!(*s, "all" | "email" | "discord" | "webhook"))
    }) {
        return Err(Error::Invalid(
            "Notification channels must be email, discord, webhook or all.",
        ));
    }
    for channel in ["email", "discord", "webhook"] {
        if requested
            .as_ref()
            .is_some_and(|v| !v.contains(&"all") && !v.contains(&channel))
        {
            continue;
        }
        let available = match channel {
            "email" => to.is_some() && api_key.is_some(),
            "discord" => discord.is_some(),
            _ => webhook.is_some() && secret.is_some(),
        };
        if !available {
            continue;
        }
        let mut accepted = false;
        let mut attempts = 0;
        for attempt in 1..=3 {
            attempts = attempt;
            let outcome=tokio::runtime::Handle::current().block_on(async{
                let subject=format!("[SELF_HOST] OpenMates {} {}",c.server_role,event["kind"].as_str().unwrap_or("runtime"));
                match channel{
                    "email"=>{let body=json!({"sender":{"email":from.as_str()},"to":[{"email":to.as_ref().unwrap().as_str()}],"subject":subject,"textContent":serde_json::to_string_pretty(event)?,"headers":{"idempotencyKey":event["eventId"]}});let result=post("https://api.brevo.com/v3/smtp/email",&[("api-key".into(),api_key.as_ref().unwrap().to_string())],&body,false).await?;if !brevo::accepted(result.status,&result.body,&body){return Err(Error::Protocol)}Ok(())},
                    "discord"=>{let raw=discord.as_ref().unwrap();let url=url::Url::parse(raw).map_err(|_|Error::Protocol)?;if !matches!(url.host_str(),Some("discord.com"|"discordapp.com"))||!url.path().starts_with("/api/webhooks/"){return Err(Error::Invalid("Discord operational webhook must use the official webhook endpoint."));}post(raw,&[],&json!({"content":format!("{subject}\n{}",serde_json::to_string(event)?)}),false).await?;Ok(())},
                    _=>{let timestamp=timestamp()?;let id=event["eventId"].as_str().ok_or(Error::Protocol)?;let body=serde_json::to_string(event)?;let canonical=Zeroizing::new(format!("{timestamp}.{id}.{body}"));let mut mac=<Hmac<Sha256>as Mac>::new_from_slice(secret.as_ref().unwrap().as_bytes()).map_err(|_|Error::Crypto)?;mac.update(canonical.as_bytes());let signature=format!("sha256={:x}",mac.finalize().into_bytes());let fixture=env_get(&content,"SERVER_ENVIRONMENT")==Some("development")&&env_get(&content,"OPENMATES_RUNTIME_HEALTH_ALLOW_LOCAL_WEBHOOK_FIXTURE")==Some("true");post(webhook.as_ref().unwrap(),&[("X-OpenMates-Timestamp".into(),timestamp),("X-OpenMates-Event-Id".into(),id.into()),("X-OpenMates-Signature".into(),signature)],event,fixture).await?;Ok(())}
                }
            });
            if outcome.is_ok() {
                accepted = true;
                break;
            }
            if attempt < 3 {
                std::thread::sleep(Duration::from_millis(250 * (1 << (attempt - 1))));
            }
        }
        deliveries.push(json!({"channel":channel,"status":if accepted{"delivered"}else{"exhausted"},"attempts":attempts,"sanitizedReason":if accepted{Value::Null}else{json!("delivery_failed")}}));
    }
    Ok(deliveries)
}
pub(super) fn test(c: &Configuration, flags: &Flags) -> Result<Value> {
    let content = env(&c.install_path)?;
    let kind = text(flags, "event-kind").unwrap_or("delivery_test");
    if !matches!(kind, "delivery_test" | "incident" | "critical" | "recovery") {
        return Err(Error::Invalid("Notification test event kind is invalid."));
    }
    if kind != "delivery_test" && env_get(&content, "SERVER_ENVIRONMENT") != Some("development") {
        return Err(Error::Invalid(
            "Synthetic notification incidents are restricted to development.",
        ));
    }
    let channel = text(flags, "channel").unwrap_or("all");
    if !matches!(channel, "email" | "discord" | "webhook" | "all") {
        return Err(Error::Invalid(
            "Notification channel must be email, discord, webhook or all.",
        ));
    }
    let event = json!({"eventId":uuid::Uuid::new_v4().to_string(),"kind":kind,"occurredAt":timestamp()?,"environment":"self_host","deploymentMode":"self_host","serverName":env_get(&content,"OPENMATES_RUNTIME_SERVER_NAME").unwrap_or("self_host"),"role":c.server_role,"version":c.image_tag.as_deref().unwrap_or("source"),"checkIds":[if kind=="delivery_test"{"monitor"}else{"core.object_storage"}],"sanitizedReason":if kind=="delivery_test"{"operator_requested_delivery_test"}else if kind=="recovery"{"storage_available"}else{"storage_unavailable"}});
    let deliveries = deliver(c, &event, Some(channel))?;
    if deliveries
        .iter()
        .any(|delivery| delivery["status"] == "exhausted")
    {
        return Err(Error::Invalid(
            "One or more notification delivery tests failed.",
        ));
    }
    Ok(
        json!({"command":"notifications test","role":c.server_role,"eventKind":kind,"configured":!deliveries.is_empty(),"deliveries":deliveries}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn webhook_validation_blocks_rebinding_private_and_credential_urls() {
        let public_addr: SocketAddr = "8.8.8.8:443".parse().unwrap();
        let private: SocketAddr = "127.0.0.1:443".parse().unwrap();
        assert!(validate_url("https://hooks.example/path", &[public_addr], false).is_ok());
        assert!(
            validate_url("https://hooks.example/path", &[public_addr, private], false).is_err()
        );
        assert!(
            validate_url(
                "https://user:secret@hooks.example/path",
                &[public_addr],
                false
            )
            .is_err()
        );
        assert!(
            validate_url(
                "http://127.0.0.1:8123/hook",
                &["127.0.0.1:8123".parse().unwrap()],
                false
            )
            .is_err()
        );
        assert!(
            validate_url(
                "http://127.0.0.1:8123/hook",
                &["127.0.0.1:8123".parse().unwrap()],
                true
            )
            .is_ok()
        );
        for ip in [
            "::1",
            "::ffff:127.0.0.1",
            "fc00::1",
            "2001:db8::1",
            "169.254.169.254",
            "198.18.0.1",
            "64:ff9b::7f00:1",
            "2002:7f00:1::",
            "fec0::1",
        ] {
            assert!(!public(ip.parse().unwrap()));
        }
    }
    #[test]
    fn unconfigured_delivery_test_reports_configuration_and_synthetic_incidents_are_development_only()
     {
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
        let result = super::test(&c, &Flags::new()).unwrap();
        assert_eq!(result["configured"], false);
        assert_eq!(result["deliveries"], json!([]));
        assert!(super::test(&c, &Flags::from([("event-kind".into(), json!("critical"))])).is_err());
    }
}
