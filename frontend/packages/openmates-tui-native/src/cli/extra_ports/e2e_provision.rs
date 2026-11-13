//! `openmates e2e provision-auth-accounts` (npm handleE2E): create a reserved
//! dev E2E account through the normal signup flow with an auto-generated TOTP
//! code and write the credentials to an owner-only artifact file. It refuses
//! production API URLs and never echoes the generated secrets.
use super::super::signup::{self, Terminal};
use super::super::{CliError, CliOutput, Invocation, handlers};
use super::failed;
use crate::{client::Client, runtime_store::RuntimeStore};
use base64::Engine;
use hmac::{Hmac, Mac};
use rand::RngCore;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

pub(super) const COMMAND: &str = "e2e provision-auth-accounts";
const FLAGS: &[&str] = &[
    "slot",
    "artifact",
    "domain",
    "email",
    "username",
    "force",
    "backup-codes-output",
    "recovery-key-output",
    "password",
    "language",
    "provider",
    "gift-card-code",
    "skip-2fa",
    "skip-recovery-key",
];
const SLOTS: [u32; 7] = [14, 15, 16, 17, 18, 19, 20];

/// Reject production API URLs exactly like npm.
pub(super) fn guard_api_url(api: &str) -> Result<(), CliError> {
    if api.contains("api.openmates.org") && !api.contains("api.dev.openmates.org") {
        return Err(failed("E2E provisioning refuses production API URLs."));
    }
    Ok(())
}

/// npm `parseRequiredNumber` + the reserved-slot check.
pub(super) fn slot(value: Option<&str>) -> Result<u32, CliError> {
    let value = value.ok_or_else(|| failed("Missing --slot."))?;
    let parsed = value
        .trim()
        .parse::<f64>()
        .ok()
        .filter(|n| n.is_finite())
        .ok_or_else(|| failed(format!("Invalid --slot: {value}")))?;
    SLOTS
        .iter()
        .copied()
        .find(|slot| f64::from(*slot) == parsed)
        .ok_or_else(|| failed("Only reserved slots 14-20 are supported."))
}

fn decode_base32(input: &str) -> Vec<u8> {
    const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
    let mut bits = String::new();
    for byte in input.to_ascii_uppercase().bytes() {
        if let Some(value) = ALPHABET.iter().position(|c| *c == byte) {
            bits.push_str(&format!("{value:05b}"));
        }
    }
    bits.as_bytes()
        .chunks_exact(8)
        .filter_map(|chunk| u8::from_str_radix(std::str::from_utf8(chunk).ok()?, 2).ok())
        .collect()
}

/// RFC 6238 SHA-1, 30 s step, 6 digits (npm `generateTotpCode`).
pub(super) fn totp(secret: &str, unix_seconds: u64) -> Result<String, CliError> {
    let mut mac = Hmac::<sha1::Sha1>::new_from_slice(&decode_base32(secret))
        .map_err(|_| failed("Provisioning produced an invalid TOTP secret."))?;
    mac.update(&(unix_seconds / 30).to_be_bytes());
    let digest = mac.finalize().into_bytes();
    let offset = usize::from(digest[digest.len() - 1] & 0x0f);
    let code = u32::from_be_bytes([
        digest[offset],
        digest[offset + 1],
        digest[offset + 2],
        digest[offset + 3],
    ]) & 0x7fff_ffff;
    Ok(format!("{:06}", code % 1_000_000))
}

fn now_millis() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_millis())
}
/// Milliseconds to wait so the code is not generated at the TOTP rollover.
pub(super) fn safe_window_wait(now_ms: u128) -> u64 {
    let remaining = 30_000 - (now_ms % 30_000) as u64;
    if remaining < 2_000 { remaining + 50 } else { 0 }
}

/// npm `generateProvisioningPassword`.
fn provisioning_password() -> Zeroizing<String> {
    let mut bytes = [0u8; 18];
    rand::rngs::OsRng.fill_bytes(&mut bytes);
    Zeroizing::new(format!(
        "OM-{}-aA2#",
        base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes)
    ))
}

/// Signup terminal that answers the 2FA prompt itself and keeps secrets off
/// the screen; every other prompt is forwarded.
struct E2eTerminal<T: Terminal> {
    inner: T,
    password: Zeroizing<String>,
    otp_secret: Option<Zeroizing<String>>,
}
impl<T: Terminal> Terminal for E2eTerminal<T> {
    fn print(&mut self, text: &str) -> Result<(), CliError> {
        if let Some(secret) = text.strip_prefix("Manual TOTP secret: ") {
            self.otp_secret = Some(Zeroizing::new(secret.trim().to_owned()));
        }
        Ok(())
    }
    async fn line(&mut self, question: &str) -> Result<String, CliError> {
        if question.starts_with("Enter current 2FA code") {
            let secret = self
                .otp_secret
                .as_ref()
                .ok_or_else(|| failed("Provisioning did not create a TOTP secret."))?;
            let wait = safe_window_wait(now_millis());
            if wait > 0 {
                tokio::time::sleep(std::time::Duration::from_millis(wait)).await;
            }
            return totp(secret, (now_millis() / 1000) as u64);
        }
        self.inner.line(question).await
    }
    async fn secret(&mut self, question: &str) -> Result<Zeroizing<String>, CliError> {
        self.inner.secret(question).await
    }
    fn env(&self, name: &str) -> Option<Zeroizing<String>> {
        if name == "OPENMATES_CLI_SIGNUP_PASSWORD" {
            return Some(self.password.clone());
        }
        self.inner.env(name)
    }
}

/// Artifact body (npm `artifactBody`).
pub(super) fn artifact_body(
    slot: u32,
    email: &str,
    password: &str,
    otp_secret: &str,
    artifact: &str,
) -> String {
    [
        format!("OPENMATES_TEST_ACCOUNT_{slot}_EMAIL={email}"),
        format!("OPENMATES_TEST_ACCOUNT_{slot}_PASSWORD={password}"),
        format!("OPENMATES_TEST_ACCOUNT_{slot}_OTP_KEY={otp_secret}"),
        format!("# Backup codes: {artifact}.backup-codes"),
        format!("# Recovery key: {artifact}.recovery-key"),
        String::new(),
    ]
    .join("\n")
}

/// The signup invocation npm builds: the user's flags plus the generated ones.
fn signup_invocation(
    i: &Invocation,
    email: &str,
    username: &str,
    invite: &str,
    artifact: &str,
) -> Invocation {
    let mut flags: BTreeMap<String, Value> = i
        .flags
        .iter()
        .filter(|(key, _)| !["slot", "artifact", "domain", "force"].contains(&key.as_str()))
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect();
    let text = |key: &str, default: String| i.text(key).map_or(default, str::to_owned);
    flags.insert("email".into(), json!(email));
    flags.insert("username".into(), json!(username));
    flags.insert("invite-code".into(), json!(invite));
    flags.insert("yes".into(), json!(true));
    flags.insert("json".into(), json!(false));
    flags.insert(
        "backup-codes-output".into(),
        json!(text(
            "backup-codes-output",
            format!("{artifact}.backup-codes")
        )),
    );
    flags.insert(
        "recovery-key-output".into(),
        json!(text(
            "recovery-key-output",
            format!("{artifact}.recovery-key")
        )),
    );
    if i.boolean("force") {
        flags.insert("force".into(), json!(true));
    }
    Invocation {
        path: vec!["signup".into()],
        positionals: vec![],
        flags,
    }
}

pub(super) async fn execute(
    i: &Invocation,
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    api: &str,
    cancel: &CancellationToken,
) -> Result<CliOutput, CliError> {
    run(
        i,
        client,
        signup::process_terminal(cancel.clone()),
        api,
        async |client: &mut Client| {
            signup::persist(client, store, passphrase.clone(), cancel).await
        },
    )
    .await
}

/// The provisioning flow with an explicit terminal and credential sink.
pub(super) async fn run<T: Terminal, S: AsyncFnMut(&mut Client) -> Result<(), CliError>>(
    i: &Invocation,
    client: &mut Client,
    inner: T,
    api: &str,
    save: S,
) -> Result<CliOutput, CliError> {
    handlers::flags(i, FLAGS)?;
    guard_api_url(api)?;
    if i.has("password") {
        return Err(failed(
            "Use generated passwords or OPENMATES_CLI_SIGNUP_PASSWORD, not --password.",
        ));
    }
    let invite = inner
        .env("OPENMATES_CLI_SIGNUP_INVITE_CODE")
        .filter(|v| !v.is_empty())
        .ok_or_else(|| {
            failed("OPENMATES_CLI_SIGNUP_INVITE_CODE is required for E2E provisioning.")
        })?;
    let slot = slot(i.text("slot"))?;
    let artifact = i.text("artifact").map_or_else(
        || format!("test-results/credential-updates/slot-{slot}.env"),
        str::to_owned,
    );
    let domain = i.text("domain").map(str::to_owned).or_else(|| {
        inner
            .env("OPENMATES_CLI_E2E_EMAIL_DOMAIN")
            .map(|v| v.to_string())
    });
    let mut terminal = E2eTerminal {
        password: inner
            .env("OPENMATES_CLI_SIGNUP_PASSWORD")
            .unwrap_or_else(provisioning_password),
        inner,
        otp_secret: None,
    };
    let stamp = now_millis();
    let email = match (i.text("email"), domain) {
        (Some(email), _) => email.to_owned(),
        (None, Some(domain)) => format!("cli-e2e-slot-{slot}-{stamp}@{domain}"),
        (None, None) => terminal
            .line("E2E account email: ")
            .await?
            .trim()
            .to_owned(),
    };
    let username = i
        .text("username")
        .map_or_else(|| format!("cli_e2e_slot_{slot}_{stamp}"), str::to_owned);
    let signup_args = signup_invocation(i, &email, &username, invite.as_str(), &artifact);
    signup::run(&signup_args, client, &mut terminal, save).await?;
    let otp = terminal
        .otp_secret
        .take()
        .ok_or_else(|| failed("Provisioning did not create a TOTP secret."))?;
    let body = Zeroizing::new(artifact_body(
        slot,
        &email,
        &terminal.password,
        &otp,
        &artifact,
    ));
    let path = signup::write_secret_file(&artifact, &body, i.boolean("force"))?;
    if i.boolean("json") {
        return CliOutput::json(&json!({"success":true,"artifact":path,"slot":slot,"email":email}));
    }
    Ok(CliOutput::text(format!(
        "Provisioning artifact written to {path}. Upload secrets through the trusted manual process."
    )))
}

#[cfg(test)]
#[path = "e2e_provision_tests.rs"]
mod tests;
