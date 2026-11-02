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
        return Err(CliError::Invalid("Only the owning Codex chat can claim a Task. Run the command inside that Codex chat, or omit --external-chat to leave the Task unlinked.".into()));
    }
    Ok(())
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
