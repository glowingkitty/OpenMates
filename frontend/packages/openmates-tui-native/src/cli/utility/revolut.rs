//! `connect-account revolut-business|revolut` without an action (npm
//! handleRevolutBusinessConnect default branch): generate the Revolut API
//! certificate with the system `openssl` tool (as the npm CLI does), show the
//! setup values and, with a ClientID and callback code, exchange the code
//! server-side and store the encrypted connected account. Exchange and
//! storage run through the shared SDK.
use super::super::{CliError, CliOutput, Invocation, handlers};
use crate::{cli::signup::Terminal, client::Client};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

const DOCS_URL: &str = "https://developer.revolut.com/docs/guides/manage-accounts/get-started/make-your-first-api-request#generate-a-private-and-a-public-certificate";
const DEFAULT_TITLE: &str = "OpenMates FinanceApp";
const FLAGS: &[&str] = &[
    "output",
    "overwrite",
    "production",
    "title",
    "redirect-uri",
    "client-id",
    "code",
];

pub(super) fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "connect-account revolut-business" | "connect-account revolut"
    )
}
fn fail(message: impl Into<String>) -> CliError {
    CliError::Invalid(message.into())
}
pub(super) fn default_redirect(production: bool) -> &'static str {
    if production {
        "https://openmates.org/oauth/revolut-business/callback"
    } else {
        "https://app.dev.openmates.org/oauth/revolut-business/callback"
    }
}
/// npm escapeOpenSslSubjectValue.
pub(super) fn subject(title: &str) -> String {
    let mut out = String::from("/CN=");
    for c in title.chars() {
        match c {
            '\\' | '/' => {
                out.push('\\');
                out.push(c);
            }
            '\n' => out.push(' '),
            other => out.push(other),
        }
    }
    out
}
/// npm parseConfiguredIpList (deduplicated, sorted).
pub(super) fn configured_ips(raw: &str) -> Vec<String> {
    let mut ips = raw
        .replace(';', ",")
        .split(',')
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .map(str::to_owned)
        .collect::<Vec<_>>();
    ips.sort();
    ips.dedup();
    ips
}
struct Certificate {
    environment: &'static str,
    title: String,
    redirect_uri: String,
    private_key_path: PathBuf,
    public_certificate_path: PathBuf,
    public_certificate_pem: String,
}
fn openssl(args: &[&std::ffi::OsStr]) -> Result<(), CliError> {
    let status = std::process::Command::new("openssl")
        .args(args)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map_err(|e| {
            fail(format!(
                "Failed to generate Revolut Business certificate with openssl: {e}"
            ))
        })?;
    if !status.success() {
        return Err(fail(format!(
            "Failed to generate Revolut Business certificate with openssl: Command failed: openssl {}",
            args.iter()
                .map(|a| a.to_string_lossy())
                .collect::<Vec<_>>()
                .join(" ")
        )));
    }
    Ok(())
}
#[cfg(unix)]
fn private(path: &Path, mode: u32) -> Result<(), CliError> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))
        .map_err(|_| fail("Could not restrict Revolut certificate permissions."))
}
#[cfg(not(unix))]
fn private(_: &Path, _: u32) -> Result<(), CliError> {
    Ok(())
}
fn generate(i: &Invocation) -> Result<Certificate, CliError> {
    let production = i.boolean("production");
    let environment = if production { "production" } else { "sandbox" };
    let output_dir = match i.text("output").filter(|v| !v.is_empty()) {
        Some(dir) => std::path::absolute(dir).map_err(|_| fail("Invalid --output directory."))?,
        None => directories::BaseDirs::new()
            .ok_or_else(|| fail("Could not resolve the home directory."))?
            .home_dir()
            .join(".openmates/revolut-business")
            .join(environment),
    };
    let title = i.text("title").unwrap_or(DEFAULT_TITLE).trim().to_owned();
    let redirect_uri = i
        .text("redirect-uri")
        .unwrap_or(default_redirect(production))
        .trim()
        .to_owned();
    if title.is_empty() {
        return Err(fail("Revolut certificate title must not be empty."));
    }
    if !redirect_uri.starts_with("https://") {
        return Err(fail("Revolut OAuth redirect URI must start with https://."));
    }
    std::fs::create_dir_all(&output_dir)
        .map_err(|_| fail("Could not create the Revolut certificate directory."))?;
    private(&output_dir, 0o700)?;
    let private_key_path = output_dir.join("privatecert.pem");
    let public_certificate_path = output_dir.join("publiccert.cer");
    if !i.boolean("overwrite") && (private_key_path.exists() || public_certificate_path.exists()) {
        return Err(fail(format!(
            "Revolut certificate files already exist in {}. Re-run with --overwrite to replace them.",
            output_dir.display()
        )));
    }
    openssl(&[
        "genrsa".as_ref(),
        "-out".as_ref(),
        private_key_path.as_os_str(),
        "2048".as_ref(),
    ])?;
    private(&private_key_path, 0o600)?;
    let subject = subject(&title);
    openssl(&[
        "req".as_ref(),
        "-new".as_ref(),
        "-x509".as_ref(),
        "-key".as_ref(),
        private_key_path.as_os_str(),
        "-out".as_ref(),
        public_certificate_path.as_os_str(),
        "-days".as_ref(),
        "1825".as_ref(),
        "-subj".as_ref(),
        subject.as_ref(),
    ])?;
    let public_certificate_pem = std::fs::read_to_string(&public_certificate_path)
        .map_err(|_| fail("Could not read the generated Revolut certificate."))?
        .trim()
        .to_owned();
    Ok(Certificate {
        environment,
        title,
        redirect_uri,
        private_key_path,
        public_certificate_path,
        public_certificate_pem,
    })
}
async fn egress(client: &mut Client) -> (Vec<String>, String) {
    let configured =
        configured_ips(&std::env::var("REVOLUT_BUSINESS_SERVER_EGRESS_IPS").unwrap_or_default());
    if !configured.is_empty() {
        return (configured, "configured".into());
    }
    match client.account().revolut_business_server_egress_ip().await {
        Some(payload) => (
            payload["ip_addresses"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .filter(|v| !v.trim().is_empty())
                .map(str::to_owned)
                .collect(),
            payload["source"].as_str().unwrap_or("api").to_owned(),
        ),
        None => (vec![], "unavailable".into()),
    }
}
pub(super) fn certificate_text(
    title: &str,
    redirect: &str,
    ips: &[String],
    pem: &str,
    key: &Path,
) -> String {
    let whitelist = if ips.is_empty() {
        "Production IP whitelist: unavailable - open the OpenMates web setup or check the API server egress IP.".to_owned()
    } else {
        format!("Production IP whitelist: {}", ips.join(", "))
    };
    format!(
        "Revolut Business certificate generated.\n\nPaste these values into Revolut Business API certificate setup:\nCertificate title: {title}\nOAuth redirect URI: {redirect}\n{whitelist}\nX509 public key:\n{pem}\n\nPrivate key saved locally: {}\nDo not upload or share the private key outside OpenMates. It will be encrypted before storage.\nRevolut rejects account reads with HTTP 403 until the OpenMates server IP is whitelisted.\nManual setup docs: {DOCS_URL}\n",
        key.display()
    )
}
pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    handlers::flags(i, FLAGS)?;
    let cert = generate(i)?;
    let (ips, source) = egress(client).await;
    if i.boolean("json") {
        return CliOutput::json(&json!({
            "provider_id": "revolut_business", "environment": cert.environment,
            "certificate_title": cert.title, "oauth_redirect_uri": cert.redirect_uri,
            "server_egress_ip_addresses": ips, "server_egress_ip_source": source,
            "public_certificate_pem": cert.public_certificate_pem,
            "public_certificate_path": cert.public_certificate_path.display().to_string(),
            "private_key_path": cert.private_key_path.display().to_string(), "docs_url": DOCS_URL,
        }));
    }
    let mut out = certificate_text(
        &cert.title,
        &cert.redirect_uri,
        &ips,
        &cert.public_certificate_pem,
        &cert.private_key_path,
    );
    let provided_id = i.text("client-id").unwrap_or("").trim().to_owned();
    let provided_code = i.text("code").unwrap_or("").trim().to_owned();
    use std::io::IsTerminal;
    if !std::io::stdin().is_terminal() && (provided_id.is_empty() || provided_code.is_empty()) {
        out.push_str("Run this command in an interactive terminal after saving the certificate in Revolut to finish setup.");
        return Ok(CliOutput::text(out));
    }
    let mut terminal =
        crate::cli::signup::process_terminal(tokio_util::sync::CancellationToken::new());
    out.push_str("\nIn Revolut, save the certificate and click Enable. The browser will return to OpenMates with a short code.\n");
    terminal.print(&out)?;
    let client_id = if provided_id.is_empty() {
        terminal
            .line("ClientID from Revolut certificate details: ")
            .await?
    } else {
        provided_id
    };
    if client_id.trim().is_empty() {
        return Err(fail("ClientID is required to connect Revolut Business."));
    }
    let code = if provided_code.is_empty() {
        terminal.line("Code from OpenMates callback page: ").await?
    } else {
        provided_code
    };
    if code.trim().is_empty() {
        return Err(fail(
            "Authorization code is required to connect Revolut Business.",
        ));
    }
    let pem = zeroize::Zeroizing::new(
        std::fs::read_to_string(&cert.private_key_path)
            .map_err(|_| fail("Could not read the Revolut private key."))?,
    );
    let mut account = client.account();
    let setup = account
        .exchange_revolut_business_setup_code(
            client_id.trim(),
            code.trim(),
            &pem,
            cert.environment == "production",
            &cert.redirect_uri,
        )
        .await?;
    let trimmed = |v: &Value| {
        v.as_str()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
    };
    let label =
        trimmed(&setup["account_hint"]["label"]).unwrap_or_else(|| "Revolut Business".into());
    let account_ref =
        trimmed(&setup["account_hint"]["account_ref"]).unwrap_or_else(|| "revolut_business".into());
    let created_at = time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc3339)
        .unwrap_or_default();
    let stored = account
        .store_validated_connected_account(&json!({
            "version": 1, "provider_id": "revolut_business", "app_id": "finance", "label": label,
            "account_ref": account_ref, "capabilities": ["read"], "runtime_modes": {"read": "server"},
            "refresh_token_bundle": setup["refresh_token_bundle"], "created_at": created_at,
        }))
        .await?;
    let field = |key: &str| stored[key].as_str().unwrap_or_default().to_owned();
    Ok(CliOutput::text(format!(
        "\nRevolut Business connected.\nConnected account: {}\nProvider: {}\nApp: {}\nAccount: {}",
        field("id"),
        field("provider_id"),
        field("app_id"),
        field("label")
    )))
}
