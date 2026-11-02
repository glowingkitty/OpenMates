//! `openmates signup`: the npm CLI's handleSignup + runSecuritySetup over the
//! shared Rust signup operations. Passwords only come from hidden prompts or
//! OPENMATES_CLI_SIGNUP_PASSWORD; codes from prompts or the
//! OPENMATES_CLI_SIGNUP_EMAIL_CODE / OPENMATES_CLI_SIGNUP_TOTP_CODE overrides.
//! Credentials are persisted as soon as the account exists and again at the end.
use super::{CliError, CliOutput, Invocation, handlers};
use crate::{client::Client, error::Error, runtime_store::RuntimeStore};
use openmates_sdk::crypto::signup::{SignupAccount, SignupError};
use serde_json::{Value, json};
use std::io::{IsTerminal, Write};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

const FLAGS: &[&str] = &[
    "email",
    "username",
    "invite-code",
    "language",
    "skip-2fa",
    "skip-recovery-key",
    "yes",
    "provider",
    "backup-codes-output",
    "recovery-key-output",
    "force",
    "gift-card-code",
];

/// Where prompts, secrets shown once, and answers flow. The terminal in
/// production; scripted in tests so no real account or terminal is needed.
pub(crate) trait Terminal {
    fn print(&mut self, text: &str) -> Result<(), CliError>;
    async fn line(&mut self, question: &str) -> Result<String, CliError>;
    async fn secret(&mut self, question: &str) -> Result<Zeroizing<String>, CliError>;
    fn env(&self, name: &str) -> Option<Zeroizing<String>>;
}

fn signup_error(error: SignupError) -> CliError {
    match error {
        SignupError::Rejected(message) => CliError::Contract {
            code: "command_failed",
            message,
        },
        SignupError::Core(error) => CliError::Client(error),
    }
}

/// Legacy writeSecretFile: refuses to overwrite without --force, mode 0600.
fn write_secret_file(path: &str, content: &str, force: bool) -> Result<String, CliError> {
    let target = std::path::Path::new(path);
    if target.exists() && !force {
        return Err(CliError::Invalid(format!(
            "{path} already exists. Use --force to overwrite."
        )));
    }
    if let Some(parent) = target.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent).map_err(|_| Error::Io)?;
    }
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(target).map_err(|_| Error::Io)?;
    file.write_all(content.as_bytes()).map_err(|_| Error::Io)?;
    Ok(path.to_owned())
}

/// Small terminal QR code (half-block cells, two quiet modules).
fn qr_text(uri: &str) -> Option<String> {
    let code = qrcode::QrCode::new(uri.as_bytes()).ok()?;
    let side = code.width() as isize;
    let dark = |x: isize, y: isize| {
        x >= 0
            && y >= 0
            && x < side
            && y < side
            && code[(x as usize, y as usize)] == qrcode::Color::Dark
    };
    let mut out = String::new();
    for y in (-2..side + 2).step_by(2) {
        for x in -2..side + 2 {
            out.push(match (dark(x, y), dark(x, y + 1)) {
                (true, true) => '█',
                (true, false) => '▀',
                (false, true) => '▄',
                _ => ' ',
            });
        }
        out.push('\n');
    }
    Some(out)
}

/// Legacy confirmOrExit. `false` means the caller must stop with "Aborted.".
async fn confirmed(terminal: &mut impl Terminal, question: &str) -> Result<bool, CliError> {
    Ok(terminal.line(question).await?.trim().to_lowercase() == "y")
}

struct Security {
    backup_codes_path: Option<String>,
    recovery_key_path: Option<String>,
}

/// runSecuritySetup. `Ok(None)` is a user abort (exit 0, account kept).
async fn security_setup(
    i: &Invocation,
    client: &mut Client,
    terminal: &mut impl Terminal,
) -> Result<Option<Security>, CliError> {
    let yes = i.boolean("yes");
    let force = i.boolean("force");
    let mut result = Security {
        backup_codes_path: None,
        recovery_key_path: None,
    };
    if i.boolean("skip-2fa") {
        if !yes
            && !confirmed(
                terminal,
                "Skip 2FA setup? This weakens account protection. [y/N] ",
            )
            .await?
        {
            return Ok(None);
        }
    } else {
        let setup = client.start_totp_setup().await.map_err(signup_error)?;
        if let Some(qr) = setup["otpauth_url"].as_str().and_then(qr_text) {
            terminal.print(&qr)?;
        }
        if let Some(secret) = setup["secret"].as_str() {
            terminal.print(&format!("Manual TOTP secret: {secret}\n"))?;
        }
        let code = match terminal.env("OPENMATES_CLI_SIGNUP_TOTP_CODE") {
            Some(code) => code,
            None => Zeroizing::new(
                terminal
                    .line("Enter current 2FA code: ")
                    .await?
                    .trim()
                    .to_owned(),
            ),
        };
        client
            .verify_totp_setup(&code)
            .await
            .map_err(signup_error)?;
        let provider = i.text("provider").unwrap_or("Authenticator app");
        client
            .set_totp_provider(provider)
            .await
            .map_err(signup_error)?;
        let codes = client.request_backup_codes().await.map_err(signup_error)?;
        let joined = Zeroizing::new(
            codes
                .iter()
                .map(|c| c.as_str())
                .collect::<Vec<_>>()
                .join("\n"),
        );
        if let Some(path) = i.text("backup-codes-output") {
            result.backup_codes_path = Some(write_secret_file(
                path,
                &format!("{}\n", joined.as_str()),
                force,
            )?);
            client
                .confirm_backup_codes_stored()
                .await
                .map_err(signup_error)?;
        } else if yes {
            client
                .confirm_backup_codes_stored()
                .await
                .map_err(signup_error)?;
        } else {
            let mut shown = Zeroizing::new("Backup codes:\n".to_owned());
            for code in &codes {
                shown.push_str(&format!("  {}\n", code.as_str()));
            }
            terminal.print(&shown)?;
            if !confirmed(
                terminal,
                "I stored these backup codes safely. Continue? [y/N] ",
            )
            .await?
            {
                return Ok(None);
            }
            client
                .confirm_backup_codes_stored()
                .await
                .map_err(signup_error)?;
        }
    }
    if i.boolean("skip-recovery-key") {
        if !yes
            && !confirmed(
                terminal,
                "Skip recovery-key setup? You may lose access to encrypted data. [y/N] ",
            )
            .await?
        {
            return Ok(None);
        }
    } else {
        let recovery = client
            .create_and_confirm_recovery_key()
            .await
            .map_err(signup_error)?;
        if let Some(path) = i.text("recovery-key-output") {
            result.recovery_key_path = Some(write_secret_file(
                path,
                &format!("{}\n", recovery.recovery_key.as_str()),
                force,
            )?);
        } else {
            terminal.print(&format!(
                "Recovery key: {}\n",
                recovery.recovery_key.as_str()
            ))?;
            if !yes
                && !confirmed(
                    terminal,
                    "I stored this recovery key safely. Continue? [y/N] ",
                )
                .await?
            {
                return Ok(None);
            }
        }
    }
    Ok(Some(result))
}

/// Persist the Client's current credentials (begin + publish, as after pairing).
pub(crate) async fn persist(
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    cancel: &CancellationToken,
) -> Result<(), CliError> {
    let session = client.clone_session().ok_or(Error::Authentication)?;
    store
        .begin_session_cancellable(session, cancel.clone())
        .await?;
    crate::session_runtime::persist(client, store, passphrase).await?;
    Ok(())
}

/// The signup flow with an explicit terminal and credential sink.
pub(crate) async fn run<T: Terminal, S: AsyncFnMut(&mut Client) -> Result<(), CliError>>(
    i: &Invocation,
    client: &mut Client,
    terminal: &mut T,
    mut save: S,
) -> Result<CliOutput, CliError> {
    if i.has("password") {
        return Err(CliError::Invalid(
            "Passwords must be entered through hidden prompts, not command-line flags.".into(),
        ));
    }
    handlers::flags(i, FLAGS)?;
    let email = match i.text("email") {
        Some(email) => email.to_owned(),
        None => terminal.line("Email: ").await?.trim().to_owned(),
    };
    let username = match i.text("username") {
        Some(username) => username.to_owned(),
        None => terminal.line("Username: ").await?.trim().to_owned(),
    };
    let invite = i.text("invite-code").unwrap_or("");
    let language = i.text("language").unwrap_or("en");
    let password = match terminal.env("OPENMATES_CLI_SIGNUP_PASSWORD") {
        Some(password) => password,
        None => {
            let password = terminal.secret("Password: ").await?;
            let confirmation = terminal.secret("Confirm password: ").await?;
            if password != confirmation {
                return Err(CliError::Invalid("Passwords do not match.".into()));
            }
            password
        }
    };
    client
        .request_signup_email_code(&email, invite, language)
        .await
        .map_err(signup_error)?;
    let email_code = match terminal.env("OPENMATES_CLI_SIGNUP_EMAIL_CODE") {
        Some(code) => code,
        None => Zeroizing::new(
            terminal
                .line("Email verification code: ")
                .await?
                .trim()
                .to_owned(),
        ),
    };
    let verification = client
        .verify_signup_email_code(&email, &username, invite, &email_code, language)
        .await
        .map_err(signup_error)?;
    let created = client
        .setup_password_account(
            SignupAccount {
                email: &email,
                username: &username,
                password: &password,
                invite_code: invite,
                language,
            },
            verification["signup_transaction_token"].as_str(),
        )
        .await
        .map_err(signup_error)?;
    drop(password);
    // The account exists now; keep its credentials even if a later step fails.
    save(client).await?;
    let Some(security) = security_setup(i, client, terminal).await? else {
        save(client).await?;
        return Ok(CliOutput {
            stdout: "Aborted.\n".into(),
            stderr: String::new(),
            exit_code: 0,
        });
    };
    let gift_card = match i.text("gift-card-code") {
        Some(code) => client.account().redeem_gift_card(code).await?,
        None => Value::Null,
    };
    // Security setup can rotate the refresh cookie; persist the final jar.
    save(client).await?;
    if i.boolean("json") {
        return CliOutput::json(&json!({"success":true,"user":created["user"],
            "backup_codes_path":security.backup_codes_path,"recovery_key_path":security.recovery_key_path,
            "gift_card":gift_card}));
    }
    let mut stdout = "\x1b[32m✓\x1b[0m Account created and CLI session saved.\n".to_owned();
    if let Some(path) = &security.backup_codes_path {
        stdout.push_str(&format!("Backup codes saved to {path}\n"));
    }
    if let Some(path) = &security.recovery_key_path {
        stdout.push_str(&format!("Recovery key saved to {path}\n"));
    }
    stdout.push_str("Buy credits or redeem a gift card:\n  openmates settings billing buy-credits bank-transfer --credits 110000\n  openmates settings billing gift-card redeem <CODE>\n");
    Ok(CliOutput {
        stdout,
        stderr: String::new(),
        exit_code: 0,
    })
}

/// The process terminal: prompts on stdout like the legacy readline prompts;
/// hidden input only when stdin is a terminal (else one plain line, as npm).
struct ProcessTerminal {
    cancel: CancellationToken,
}
impl Terminal for ProcessTerminal {
    fn print(&mut self, text: &str) -> Result<(), CliError> {
        let mut stdout = std::io::stdout();
        stdout
            .write_all(text.as_bytes())
            .and_then(|()| stdout.flush())
            .map_err(|_| Error::Io.into())
    }
    async fn line(&mut self, question: &str) -> Result<String, CliError> {
        self.print(question)?;
        let cancel = self.cancel.clone();
        let read = tokio::task::spawn_blocking(|| {
            let mut line = String::new();
            std::io::stdin().read_line(&mut line).map(|_| line)
        });
        tokio::select! {
            _ = cancel.cancelled() => Err(Error::Cancelled.into()),
            line = read => Ok(line.map_err(|_| Error::Io)?.map_err(|_| Error::Io)?
                .trim_end_matches(['\r', '\n']).to_owned()),
        }
    }
    async fn secret(&mut self, question: &str) -> Result<Zeroizing<String>, CliError> {
        if !std::io::stdin().is_terminal() {
            return Ok(Zeroizing::new(self.line(question).await?.trim().to_owned()));
        }
        self.print(question)?;
        let cancel = self.cancel.clone();
        tokio::task::spawn_blocking(move || -> Result<Zeroizing<String>, Error> {
            use crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
            struct Raw(bool);
            impl Drop for Raw {
                fn drop(&mut self) {
                    if !self.0 {
                        let _ = crossterm::terminal::disable_raw_mode();
                    }
                }
            }
            let was_raw = crossterm::terminal::is_raw_mode_enabled().map_err(|_| Error::Io)?;
            crossterm::terminal::enable_raw_mode().map_err(|_| Error::Io)?;
            let _guard = Raw(was_raw);
            let mut value = Zeroizing::new(String::new());
            loop {
                if cancel.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                if !event::poll(std::time::Duration::from_millis(50)).map_err(|_| Error::Io)? {
                    continue;
                }
                if let Event::Key(key) = event::read().map_err(|_| Error::Io)? {
                    if key.kind == KeyEventKind::Release {
                        continue;
                    }
                    match key.code {
                        KeyCode::Enter => {
                            print!("\r\n");
                            return Ok(value);
                        }
                        KeyCode::Char('c' | 'd')
                            if key.modifiers.contains(KeyModifiers::CONTROL) =>
                        {
                            return Err(Error::Cancelled);
                        }
                        KeyCode::Backspace => {
                            value.pop();
                        }
                        KeyCode::Char(c) if !c.is_control() && value.len() < 4096 => value.push(c),
                        _ => {}
                    }
                }
            }
        })
        .await
        .map_err(|_| Error::Io)?
        .map_err(CliError::from)
    }
    fn env(&self, name: &str) -> Option<Zeroizing<String>> {
        std::env::var(name).ok().map(Zeroizing::new)
    }
}

/// Application entry: a fresh, credential-free profile and its runtime store.
pub async fn execute(
    i: &Invocation,
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    cancel: &CancellationToken,
) -> Result<CliOutput, CliError> {
    if client.session().is_some() {
        return Err(CliError::Invalid(
            "Log out of this native profile before creating another account; existing credentials were preserved.".into(),
        ));
    }
    let mut terminal = ProcessTerminal {
        cancel: cancel.clone(),
    };
    run(i, client, &mut terminal, async |client: &mut Client| {
        persist(client, store, passphrase.clone(), cancel).await
    })
    .await
}

#[cfg(test)]
#[path = "signup_tests.rs"]
mod tests;
