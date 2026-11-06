//! Explicit local Codex integration through the installed daemon's supported
//! control transport. No internal databases, daemon startup or prompt dispatch.
use super::{CliError, CliOutput};
use crate::error::Error;
use serde::{Deserialize, Serialize};
use std::{
    io::{self, IsTerminal},
    path::Path,
    process::Stdio,
    time::Duration,
};
use tokio::io::AsyncReadExt;
use tokio_util::sync::CancellationToken;
const TIMEOUT: Duration = Duration::from_secs(10);
#[derive(Serialize, Deserialize)]
pub(super) struct Connection {
    pub provider: String,
    pub id: String,
    pub title: String,
    pub status: String,
    pub url: String,
}
pub(super) fn assert_caller(thread_id: &str) -> Result<(), CliError> {
    valid_thread(thread_id)?;
    if std::env::var("CODEX_THREAD_ID").ok().as_deref() != Some(thread_id) {
        // npm throws a plain Error here: command_failed, exit 1.
        return Err(CliError::Contract { code: "command_failed", message: format!(
            "Only the owning Codex chat can claim a Task. Run this command inside Codex chat ID: {thread_id}. Ordinary CLI creation can omit --external-chat to leave the Task unlinked."
        ) });
    }
    Ok(())
}
const CLAUDE_SESSION_IDS: &str =
    "Claude Code external chat ids must be session UUIDs (CLAUDE_CODE_SESSION_ID).";
const CLAUDE_SESSION_TITLE: &str = "Claude Code session";
fn canonical_uuid(value: &str) -> bool {
    value.len() == 36 && uuid::Uuid::parse_str(value).is_ok()
}
/// Parse `--external-chat provider:id` exactly like the npm CLI: `codex` links
/// a Codex thread, `claude` links a Claude Code session (link-only context).
pub(super) fn parse_external(
    value: &str,
    title: &str,
) -> Result<openmates_sdk::work::ExternalChat, CliError> {
    let (provider, id) = value
        .split_once(':')
        .map(|(provider, id)| (provider.trim().to_ascii_lowercase(), id.trim()))
        .filter(|(_, id)| !id.is_empty() && !value.starts_with(':'))
        .ok_or_else(|| CliError::Invalid("--external-chat requires provider:id.".into()))?;
    match provider.as_str() {
        "codex" if !canonical_uuid(id) => Err(CliError::Invalid(
            "External chat must be codex:<thread-uuid>.".into(),
        )),
        "claude" if !canonical_uuid(id) => Err(CliError::Invalid(CLAUDE_SESSION_IDS.into())),
        "codex" | "claude" => Ok(openmates_sdk::work::ExternalChat {
            provider,
            id: id.into(),
            title: title.into(),
        }),
        _ => Err(CliError::Invalid(format!(
            "Unsupported external chat provider '{provider}'. Use codex or claude."
        ))),
    }
}
/// Claude Code exports its session UUID; only that session may link a Task to itself.
pub(super) fn assert_claude_caller(
    session_id: &str,
    current: Option<&str>,
) -> Result<(), CliError> {
    if !canonical_uuid(session_id) {
        return Err(CliError::Invalid(CLAUDE_SESSION_IDS.into()));
    }
    if current != Some(session_id) {
        return Err(CliError::Invalid(format!(
            "Only the owning Claude Code session can claim a Task. Run this command inside Claude Code session ID: {session_id} (CLAUDE_CODE_SESSION_ID). Ordinary CLI creation can omit --external-chat to leave the Task unlinked."
        )));
    }
    Ok(())
}
/// Claude Code is an external-chat provider only (never an assignee identity),
/// so linking leaves assignment unchanged and has no runtime title lookup.
fn claim_claude(
    external: &mut openmates_sdk::work::ExternalChat,
    current: Option<&str>,
) -> Result<(), CliError> {
    assert_claude_caller(&external.id, current)?;
    let title = external.title.trim();
    external.title = if title.is_empty() {
        CLAUDE_SESSION_TITLE.into()
    } else {
        title.into()
    };
    Ok(())
}
/// Verify the caller owns the external chat being linked and fill its title.
pub(super) async fn claim_external(
    external: &mut openmates_sdk::work::ExternalChat,
    cancel: &CancellationToken,
) -> Result<(), CliError> {
    if external.provider == "claude" {
        return claim_claude(
            external,
            std::env::var("CLAUDE_CODE_SESSION_ID").ok().as_deref(),
        );
    }
    assert_caller(&external.id)?;
    external.title = read(&external.id, cancel).await?.title;
    Ok(())
}
/// The external chat actually running this process; Codex keeps precedence.
fn current_caller(codex: Option<String>, claude: Option<String>) -> Option<(&'static str, String)> {
    codex
        .map(|id| ("codex", id))
        .or_else(|| claude.map(|id| ("claude", id)))
}
/// Owner-conflict text shared with the npm CLI's `taskOwnerConflict`.
fn owner_conflict(provider: &str, id: &str, title: Option<&str>) -> String {
    let title = serde_json::to_string(title.filter(|t| !t.is_empty()).unwrap_or("Untitled chat"))
        .unwrap_or_default();
    let location = match provider {
        "openmates" => format!("OpenMates chat ID: {id}. View: openmates chats show {id}"),
        "claude" => format!("Claude Code session ID: {id}"),
        _ => format!("Codex chat ID: {id}"),
    };
    format!(
        "Task is already linked to {title}. {location}. Release that link before claiming the task in another chat."
    )
}
fn release_conflict(
    task: &serde_json::Value,
    caller: Option<(&'static str, String)>,
) -> Result<(), CliError> {
    let external = &task["external_chat"];
    let Some((provider, id)) = caller else {
        return Ok(());
    };
    if (task["primary_chat_id"].is_null() && external.is_null())
        || (external["provider"] == provider && external["id"] == id.as_str())
    {
        return Ok(());
    }
    Err(CliError::Invalid(match task["primary_chat_id"].as_str() {
        Some(chat) => owner_conflict("openmates", chat, None),
        None => owner_conflict(
            external["provider"].as_str().unwrap_or("codex"),
            external["id"].as_str().unwrap_or(""),
            external["title"].as_str(),
        ),
    }))
}
/// A Claude Code session may only release its own link. Codex callers are
/// already enforced by the SDK owner headers, so this only reads the Task when
/// the process runs inside Claude Code.
pub(super) async fn guard_release(
    service: &mut openmates_sdk::work::Tasks<'_>,
    id: &str,
) -> Result<(), CliError> {
    let codex = std::env::var("CODEX_THREAD_ID").ok();
    let claude = std::env::var("CLAUDE_CODE_SESSION_ID").ok();
    if codex.is_some() || claude.is_none() {
        return Ok(());
    }
    release_conflict(&service.show(id).await?, current_caller(codex, claude))
}
/// Thread for `tasks connection`/`tasks resume`; those stay Codex-only.
pub(super) fn connection_thread(task: &serde_json::Value) -> Result<&str, CliError> {
    let external = &task["external_chat"];
    match external["provider"].as_str() {
        None => Err(CliError::Contract {
            code: "command_failed",
            message: "This Task has no external connection. Use tasks connect first.".into(),
        }),
        Some("claude") => Err(CliError::Invalid(format!(
            "This Task is linked to a Claude Code session. Tasks connect, connection and resume support Codex threads only; resume it in Claude Code with: claude --resume {}",
            external["id"].as_str().unwrap_or("")
        ))),
        Some("codex") => external["id"]
            .as_str()
            .ok_or(CliError::Client(Error::Protocol)),
        Some(_) => Err(CliError::Invalid(
            "Codex connection requires the codex provider.".into(),
        )),
    }
}
fn valid_thread(thread_id: &str) -> Result<(), CliError> {
    if uuid::Uuid::parse_str(thread_id).is_err() || thread_id.len() != 36 {
        return Err(CliError::Invalid(
            "Codex connection requires a valid thread UUID.".into(),
        ));
    }
    Ok(())
}
pub(super) async fn read(
    thread_id: &str,
    cancel: &CancellationToken,
) -> Result<Connection, CliError> {
    valid_thread(thread_id)?;
    let discover = async {
        let mut child=tokio::process::Command::new("codex").args(["app-server","daemon","version"]).stdin(Stdio::null()).stderr(Stdio::null()).stdout(Stdio::piped()).kill_on_drop(true).spawn().map_err(|_|CliError::Invalid("The installed Codex daemon is unavailable. Start Codex explicitly before connecting a Task.".into()))?;
        let mut bytes = vec![];
        child
            .stdout
            .take()
            .ok_or(CliError::Client(Error::Io))?
            .take(65537)
            .read_to_end(&mut bytes)
            .await
            .map_err(|_| CliError::Client(Error::Io))?;
        if bytes.len() > 65536 {
            return Err(CliError::Client(Error::Protocol));
        }
        let status = child
            .wait()
            .await
            .map_err(|_| CliError::Client(Error::Io))?;
        if !status.success() {
            return Err(CliError::Invalid("The installed Codex daemon is unavailable. Start Codex explicitly before connecting a Task.".into()));
        }
        let value: serde_json::Value =
            serde_json::from_slice(&bytes).map_err(|_| CliError::Client(Error::Protocol))?;
        let socket = value["socketPath"]
            .as_str()
            .filter(|socket| Path::new(socket).is_absolute() && !socket.contains(':'))
            .ok_or_else(|| {
                CliError::Invalid("Codex did not report an absolute local daemon socket.".into())
            })?;
        if value["status"] != "running" {
            return Err(CliError::Invalid(
                "Start Codex explicitly before connecting a Task.".into(),
            ));
        }
        read_socket(thread_id, socket).await
    };
    tokio::select! {_ = cancel.cancelled()=>Err(Error::Cancelled.into()),result=tokio::time::timeout(TIMEOUT,discover)=>result.unwrap_or_else(|_|Err(CliError::Invalid("Codex connection timed out.".into())))}
}
#[cfg(unix)]
async fn read_socket(thread_id: &str, socket: &str) -> Result<Connection, CliError> {
    use futures_util::{SinkExt, StreamExt};
    use serde_json::{Value, json};
    use tokio_tungstenite::tungstenite::{Message, protocol::WebSocketConfig};
    let stream = tokio::net::UnixStream::connect(socket)
        .await
        .map_err(|_| CliError::Invalid("Could not connect to the local Codex daemon.".into()))?;
    let config = WebSocketConfig::default()
        .max_message_size(Some(4 * 1024 * 1024))
        .max_frame_size(Some(4 * 1024 * 1024));
    let (mut ws, _) =
        tokio_tungstenite::client_async_with_config("ws://localhost/", stream, Some(config))
            .await
            .map_err(|_| CliError::Client(Error::Protocol))?;
    ws.send(Message::text(json!({"id":1,"method":"initialize","params":{"clientInfo":{"name":"openmates-tasks","version":"1.0.0"}}}).to_string())).await.map_err(|_|CliError::Client(Error::Io))?;
    let mut initialized = false;
    for _ in 0..512 {
        let message = ws
            .next()
            .await
            .ok_or(CliError::Client(Error::Offline))?
            .map_err(|_| CliError::Client(Error::Protocol))?;
        match message {
            Message::Text(text) => {
                let message: Value =
                    serde_json::from_str(&text).map_err(|_| CliError::Client(Error::Protocol))?;
                if message["id"] != 1 && message["id"] != 2 {
                    continue;
                }
                if message.get("error").is_some() {
                    return Err(CliError::Invalid(
                        "Codex rejected the thread metadata request.".into(),
                    ));
                }
                if message["id"] == 1 {
                    if initialized {
                        continue;
                    }
                    initialized = true;
                    ws.send(Message::text(json!({"method":"initialized"}).to_string()))
                        .await
                        .map_err(|_| CliError::Client(Error::Io))?;
                    ws.send(Message::text(json!({"id":2,"method":"thread/read","params":{"threadId":thread_id,"includeTurns":false}}).to_string())).await.map_err(|_|CliError::Client(Error::Io))?;
                } else {
                    let thread = &message["result"]["thread"];
                    if !initialized || thread["id"] != thread_id {
                        return Err(Error::Protocol.into());
                    }
                    let status = thread
                        .pointer("/status/type")
                        .and_then(Value::as_str)
                        .filter(|value| !value.is_empty())
                        .ok_or(CliError::Client(Error::Protocol))?;
                    let connection = Connection {
                        provider: "codex".into(),
                        id: thread_id.into(),
                        title: thread["name"].as_str().unwrap_or("").into(),
                        status: status.into(),
                        url: format!("codex://threads/{thread_id}"),
                    };
                    let _ = ws.close(None).await;
                    return Ok(connection);
                }
            }
            Message::Ping(bytes) => {
                ws.send(Message::Pong(bytes))
                    .await
                    .map_err(|_| CliError::Client(Error::Io))?;
            }
            Message::Close(_) => return Err(Error::Offline.into()),
            _ => {}
        }
    }
    Err(Error::Protocol.into())
}
#[cfg(not(unix))]
async fn read_socket(_thread_id: &str, _socket: &str) -> Result<Connection, CliError> {
    Err(CliError::Invalid(
        "The installed Codex Unix daemon connection is unavailable on this platform.".into(),
    ))
}
pub(super) async fn resume(
    thread_id: &str,
    cancel: &CancellationToken,
) -> Result<CliOutput, CliError> {
    valid_thread(thread_id)?;
    if !io::stdin().is_terminal() || !io::stdout().is_terminal() {
        return Err(CliError::Invalid(
            "Task resume requires an interactive terminal; status and connect never launch work."
                .into(),
        ));
    }
    read(thread_id, cancel).await?;
    let mut child = tokio::process::Command::new("codex")
        .args(["resume", thread_id])
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()
        .map_err(|_| CliError::Invalid("Could not open the installed Codex CLI.".into()))?;
    let status = tokio::select! {_ = cancel.cancelled()=>return Err(Error::Cancelled.into()),result=child.wait()=>result.map_err(|_|CliError::Client(Error::Io))?};
    if !status.success() {
        return Err(CliError::Invalid(
            "Codex resume exited unsuccessfully.".into(),
        ));
    }
    Ok(CliOutput {
        stdout: String::new(),
        stderr: String::new(),
        exit_code: 0,
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn thread_ids_cannot_be_executable_arguments_or_noncanonical_ids() {
        assert!(valid_thread("--help").is_err());
        assert!(valid_thread("00112233445566778899aabbccddeeff").is_err());
        assert!(valid_thread("00112233-4455-6677-8899-aabbccddeeff").is_ok());
    }
    const SESSION: &str = "00000000-0000-4000-8000-00000000c1a0";
    fn invalid(result: Result<impl Sized, CliError>) -> String {
        match result {
            Err(CliError::Invalid(message) | CliError::Contract { message, .. }) => message,
            _ => panic!("expected an input or command failure"),
        }
    }
    // contract-test: supporting surface=cli assertions=tasks.external-chat.encrypted-context
    #[test]
    fn external_chat_accepts_codex_and_claude_like_the_npm_cli() {
        let claude = parse_external(&format!(" Claude :{SESSION}"), "")
            .ok()
            .unwrap();
        assert_eq!(
            (claude.provider.as_str(), claude.id.as_str()),
            ("claude", SESSION)
        );
        let codex = parse_external("codex:00112233-4455-6677-8899-aabbccddeeff", "T")
            .ok()
            .unwrap();
        assert_eq!(
            (codex.provider.as_str(), codex.title.as_str()),
            ("codex", "T")
        );
        assert!(invalid(parse_external("claude:not-a-uuid", "")).contains("session UUIDs"));
        assert!(
            invalid(parse_external(
                &format!("claude:{}", SESSION.replace('-', "")),
                ""
            ))
            .contains("session UUIDs")
        );
        assert_eq!(
            invalid(parse_external(&format!("cursor:{SESSION}"), "")),
            "Unsupported external chat provider 'cursor'. Use codex or claude."
        );
        for missing in ["claude", "claude:", ":abc"] {
            assert_eq!(
                invalid(parse_external(missing, "")),
                "--external-chat requires provider:id."
            );
        }
    }
    // contract-test: supporting surface=cli assertions=tasks.conversation.single-owner-claim
    #[test]
    fn claude_links_require_the_owning_session_and_default_their_title() {
        let mut external = parse_external(&format!("claude:{SESSION}"), "  ")
            .ok()
            .unwrap();
        assert!(
            invalid(claim_claude(&mut external.clone(), None))
                .contains("Only the owning Claude Code session can claim a Task")
        );
        let other = "00000000-0000-4000-8000-00000000beef";
        assert!(invalid(claim_claude(&mut external.clone(), Some(other))).contains(SESSION));
        assert!(claim_claude(&mut external, Some(SESSION)).is_ok());
        assert_eq!(external.title, "Claude Code session");
        let mut titled = parse_external(&format!("claude:{SESSION}"), " Review ")
            .ok()
            .unwrap();
        assert!(claim_claude(&mut titled, Some(SESSION)).is_ok());
        assert_eq!(titled.title, "Review");
        assert!(
            invalid(assert_claude_caller("not-a-uuid", Some("not-a-uuid")))
                .contains("session UUIDs")
        );
    }
    // contract-test: supporting surface=cli assertions=tasks.conversation.single-owner-claim
    #[test]
    fn claude_sessions_release_only_their_own_links() {
        use serde_json::json;
        let caller = || current_caller(None, Some(SESSION.into()));
        let own = json!({"primary_chat_id":null,"external_chat":{"provider":"claude","id":SESSION,"title":"Mine"}});
        assert!(release_conflict(&own, caller()).is_ok());
        let unlinked = json!({"primary_chat_id":null,"external_chat":null});
        assert!(release_conflict(&unlinked, caller()).is_ok());
        let codex = json!({"primary_chat_id":null,"external_chat":{"provider":"codex","id":"t","title":"Worker"}});
        assert_eq!(
            invalid(release_conflict(&codex, caller())),
            "Task is already linked to \"Worker\". Codex chat ID: t. Release that link before claiming the task in another chat."
        );
        let other = json!({"primary_chat_id":null,"external_chat":{"provider":"claude","id":"x","title":""}});
        assert!(
            invalid(release_conflict(&other, caller()))
                .contains("\"Untitled chat\". Claude Code session ID: x.")
        );
        let native = json!({"primary_chat_id":"chat-1","external_chat":null});
        assert!(
            invalid(release_conflict(&native, caller()))
                .contains("OpenMates chat ID: chat-1. View: openmates chats show chat-1")
        );
        assert!(release_conflict(&codex, None).is_ok());
        assert_eq!(
            current_caller(Some("c".into()), Some("s".into()))
                .unwrap()
                .0,
            "codex"
        );
    }
    #[test]
    fn connection_and_resume_stay_codex_only() {
        use serde_json::json;
        let claude = json!({"external_chat":{"provider":"claude","id":SESSION}});
        assert!(
            invalid(connection_thread(&claude)).ends_with(&format!("claude --resume {SESSION}"))
        );
        assert_eq!(
            invalid(connection_thread(&json!({"external_chat":null}))),
            "This Task has no external connection. Use tasks connect first."
        );
        // npm exits 1 (command_failed) when the Task has no connection.
        assert!(matches!(
            connection_thread(&json!({"external_chat":null})),
            Err(CliError::Contract { code: "command_failed", .. })
        ));
        let codex = json!({"external_chat":{"provider":"codex","id":"thread"}});
        assert_eq!(connection_thread(&codex).ok(), Some("thread"));
    }
    #[cfg(unix)]
    #[tokio::test]
    async fn local_thread_metadata_uses_initialize_and_read_only() {
        use futures_util::{SinkExt, StreamExt};
        use serde_json::{Value, json};
        use tokio_tungstenite::tungstenite::Message;
        let directory = tempfile::tempdir().unwrap();
        let socket = directory.path().join("codex.sock");
        let listener = tokio::net::UnixListener::bind(&socket).unwrap();
        let peer = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
            let first = ws.next().await.unwrap().unwrap();
            let message: Value = serde_json::from_str(first.to_text().unwrap()).unwrap();
            assert_eq!(message["method"], "initialize");
            ws.send(Message::text(json!({"id":1,"result":{}}).to_string()))
                .await
                .unwrap();
            let initialized = ws.next().await.unwrap().unwrap();
            assert_eq!(
                serde_json::from_str::<Value>(initialized.to_text().unwrap()).unwrap()["method"],
                "initialized"
            );
            let request = ws.next().await.unwrap().unwrap();
            let request: Value = serde_json::from_str(request.to_text().unwrap()).unwrap();
            assert_eq!(request["method"], "thread/read");
            assert_eq!(request["params"]["includeTurns"], false);
            ws.send(Message::text(json!({"id":2,"result":{"thread":{"id":"00112233-4455-6677-8899-aabbccddeeff","name":"Synthetic title","status":{"type":"idle"}}}}).to_string())).await.unwrap();
            let _ = ws.next().await;
        });
        let value = read_socket(
            "00112233-4455-6677-8899-aabbccddeeff",
            socket.to_str().unwrap(),
        )
        .await
        .ok()
        .unwrap();
        assert_eq!(value.title, "Synthetic title");
        assert_eq!(value.status, "idle");
        peer.await.unwrap();
    }
}
