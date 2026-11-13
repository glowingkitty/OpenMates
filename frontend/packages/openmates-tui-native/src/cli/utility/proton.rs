//! `connect-account proton [--write] [--json]`: connect a local Proton Mail
//! Bridge as a local-connector connected account (npm handleConnectAccount +
//! protonBridgeConnector parity). The Bridge process, loopback IMAP/SMTP and
//! hidden prompts are CLI adapters; registration, heartbeat and request
//! completion use the shared Rust account core. Provider credentials never
//! leave this process.
use super::super::{CliError, CliOutput, Invocation, handlers};
use crate::{cli::signup::Terminal, client::Client};
use serde_json::{Value, json};
use std::time::{Duration, Instant};

#[path = "proton/io.rs"]
mod io;
#[path = "proton/logic.rs"]
mod logic;
#[cfg(test)]
#[path = "proton/tests.rs"]
mod tests;

const FLAGS: &[&str] = &["write", "json"];
const SLICE: Duration = Duration::from_secs(1);

pub(super) fn supported(i: &Invocation) -> bool {
    i.command_path() == "connect-account proton"
}
fn fail(message: impl Into<String>) -> CliError {
    CliError::Invalid(logic::redact_secrets(&message.into()))
}
/// Runtime refusals (Bridge missing, unsupported host, declined write mode): npm throws a
/// plain `Error` for these, which it reports as `command_failed` with exit 1.
fn runtime_fail(message: impl Into<String>) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: logic::redact_secrets(&message.into()),
    }
}
fn platform() -> &'static str {
    match std::env::consts::OS {
        "macos" => "macos",
        "linux" => "linux",
        other => other,
    }
}
fn find_executable(name: &str) -> Option<String> {
    std::env::var("PATH").ok()?.split(':').find_map(|dir| {
        let candidate = format!("{dir}/{name}");
        (!dir.is_empty() && std::path::Path::new(&candidate).exists()).then_some(candidate)
    })
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    logic::reject_credential_flags(i.flags.keys().map(String::as_str))
        .map_err(CliError::Invalid)?;
    handlers::flags(i, FLAGS)?;
    if !i.positionals.is_empty() {
        return Err(fail(
            "connect-account proton takes no positional arguments.",
        ));
    }
    let write = i.boolean("write");
    let json_output = i.boolean("json");
    let mut terminal =
        crate::cli::signup::process_terminal(tokio_util::sync::CancellationToken::new());
    // JSON stdout stays machine-readable: progress text goes to stderr.
    let say = |text: String| {
        if json_output {
            eprintln!("{text}");
            Ok(())
        } else {
            println!("{text}");
            Ok::<(), CliError>(())
        }
    };
    say(logic::startup_message(write))?;
    if write {
        let answer = terminal
            .line("Type ENABLE WRITE to enable Proton write mode: ")
            .await?;
        if answer.trim() != "ENABLE WRITE" {
            return Err(runtime_fail(
                "Proton write mode was not enabled because confirmation was declined.",
            ));
        }
    }
    let command = logic::resolve_bridge_command(
        platform(),
        std::env::consts::ARCH,
        |p| std::path::Path::new(p).exists(),
        find_executable,
        find_executable("brew").is_some(),
    )
    .map_err(runtime_fail)?;
    if !command.should_start {
        return Err(runtime_fail(
            command
                .guidance
                .unwrap_or_else(|| "Proton Mail Bridge is not installed.".into()),
        ));
    }
    let bridge = io::Bridge::spawn(&command.command, &command.args).map_err(runtime_fail)?;
    let outcome = run(client, &mut terminal, &command, write, json_output).await;
    bridge.stop().await;
    let (session, capabilities) = outcome?;
    if json_output {
        return CliOutput::json(&json!({
            "connected_account_id": session.connected_account_id,
            "connector_session_id": session.connector_session_id,
            "capabilities": capabilities,
        }));
    }
    Ok(CliOutput::text(format!(
        "Proton Mail connector is online.\nConnected account: {}",
        session.connected_account_id
    )))
}

async fn credentials(
    terminal: &mut impl Terminal,
    command: &logic::BridgeCommand,
) -> Result<logic::Credentials, CliError> {
    let captured = io::capture_info(&command.command, &command.args).await;
    if let Ok(parsed) = captured.and_then(|t| logic::parse_bridge_info(&t)) {
        return Ok(parsed);
    }
    let host = terminal.line("Bridge IMAP host [127.0.0.1]: ").await?;
    let port = terminal.line("Bridge IMAP port: ").await?;
    let user = terminal.line("Bridge IMAP username: ").await?;
    let password = terminal.secret("Bridge IMAP password: ").await?;
    let info = format!(
        "IMAP\naddress: {}\nport: {}\nusername: {}\npassword: {}\n",
        Some(host.trim())
            .filter(|h| !h.is_empty())
            .unwrap_or("127.0.0.1"),
        port.trim(),
        user.trim(),
        password.as_str()
    );
    logic::parse_bridge_info(&info).map_err(fail)
}

async fn run(
    client: &mut Client,
    terminal: &mut impl Terminal,
    command: &logic::BridgeCommand,
    write: bool,
    json_output: bool,
) -> Result<(openmates_sdk::account::LocalConnectorSession, Vec<&'static str>), CliError> {
    let creds = credentials(terminal, command).await?;
    io::validate_imap(&creds).await.map_err(fail)?;
    let registration =
        logic::registration(&uuid::Uuid::new_v4().to_string(), &creds, write).map_err(fail)?;
    let capabilities: Vec<&'static str> = if write {
        vec!["read", "write"]
    } else {
        vec!["read"]
    };
    let mut account = client.account();
    let session = account.register_local_connector(&registration).await?;
    let result = serve(&mut account, &session, &creds, &capabilities, json_output).await;
    let _ = account
        .local_connector_heartbeat(
            &session,
            false,
            &capabilities,
            json!({"exit": "connector_stopped"}),
        )
        .await;
    result?;
    Ok((session, capabilities))
}

async fn serve(
    account: &mut openmates_sdk::account::Account<'_>,
    session: &openmates_sdk::account::LocalConnectorSession,
    creds: &logic::Credentials,
    capabilities: &[&'static str],
    json_output: bool,
) -> Result<(), CliError> {
    let interval = Duration::from_millis(
        session
            .heartbeat_interval_ms
            .unwrap_or(logic::DEFAULT_HEARTBEAT_MS),
    );
    let mut socket = account.open_local_connector_socket().await?;
    let mut queue = logic::SendQueue::new(Duration::from_secs(logic::WRITE_DELAY_SECONDS));
    let mut next_beat = Instant::now();
    let announce = format!(
        "Proton Mail connector is online. Connected account: {}",
        session.connected_account_id
    );
    if json_output {
        eprintln!("{announce}")
    } else {
        println!("{announce}")
    }
    let stop = tokio::signal::ctrl_c();
    tokio::pin!(stop);
    loop {
        if Instant::now() >= next_beat {
            account
                .local_connector_heartbeat(session, true, capabilities, json!({"imap": "ok"}))
                .await?;
            next_beat = Instant::now() + interval;
        }
        for (job, request_id, payload) in queue.take_due(Instant::now()) {
            match io::send_smtp(creds, &payload).await {
                Ok(mut receipt) => {
                    receipt["delayed_send_job_id"] = json!(job);
                    account
                        .complete_local_connector_request(session, &request_id, "ok", receipt, None)
                        .await?;
                }
                Err(message) => {
                    queue.mark_failed(&job);
                    let message = logic::redact_secrets(&message);
                    account
                        .complete_local_connector_request(
                            session,
                            &request_id,
                            "error",
                            json!({}),
                            Some(("smtp_delivery_failed", &message)),
                        )
                        .await?;
                }
            }
        }
        let request = tokio::select! {
            _ = &mut stop => break,
            next = socket.next_request(&session.connector_session_id, &session.connected_account_id, SLICE) => next?,
        };
        if let Some(request) = request {
            handle(account, session, creds, capabilities, &mut queue, &request).await?;
        }
    }
    queue.clear();
    socket.close().await;
    Ok(())
}

async fn handle(
    account: &mut openmates_sdk::account::Account<'_>,
    session: &openmates_sdk::account::LocalConnectorSession,
    creds: &logic::Credentials,
    capabilities: &[&'static str],
    queue: &mut logic::SendQueue,
    request: &Value,
) -> Result<(), CliError> {
    let request_id = request["request_id"].as_str().unwrap_or_default();
    let action = request["action"].as_str().unwrap_or_default();
    let arguments = if request["arguments"].is_object() {
        request["arguments"].clone()
    } else {
        json!({})
    };
    let (status, result, error): (&str, Value, Option<(&str, String)>) =
        if logic::contains_credential_key(&arguments) {
            (
                "error",
                json!({}),
                Some((
                    "credential_fields_not_allowed",
                    "Local connector request contained forbidden credential fields.".into(),
                )),
            )
        } else if action == "mail.search" {
            match io::search_imap(creds, &arguments).await {
                Ok(messages) => ("ok", json!({"messages": messages}), None),
                Err(message) => (
                    "error",
                    json!({}),
                    Some((
                        "local_connector_request_failed",
                        logic::redact_secrets(&message),
                    )),
                ),
            }
        } else if action == "mail.send" {
            if !capabilities.contains(&"write") {
                (
                    "error",
                    json!({}),
                    Some((
                        "write_not_enabled",
                        "Proton connector write mode is not enabled.".into(),
                    )),
                )
            } else {
                queue.queue(request_id, arguments, Instant::now());
                return Ok(());
            }
        } else {
            (
                "error",
                json!({}),
                Some((
                    "unsupported_action",
                    format!("Unsupported local connector action: {action}"),
                )),
            )
        };
    let error_ref = error.as_ref().map(|(c, m)| (*c, m.as_str()));
    account
        .complete_local_connector_request(session, request_id, status, result, error_ref)
        .await?;
    Ok(())
}
