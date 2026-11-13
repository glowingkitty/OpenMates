//! Routed loopback API for the send and login tests: each connection carries one request, a test closure picks the reply from the request line and JSON body, and every request line is recorded.
use crate::view_window_tests::{read_request, respond};
use serde_json::Value;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::AsyncWriteExt;

/// How the loopback API answers one request.
pub(crate) enum Reply {
    /// `200` with this JSON body.
    Json(Value),
    /// `200` with this JSON body and a refresh-token cookie.
    JsonWithCookie(Value),
    /// This HTTP status with this JSON body (typed server refusals).
    Status(u16, Value),
    /// Close without an answer (the server is "offline" for it).
    Close,
    /// Hold the connection this long, then close without an answer.
    Hang(Duration),
}

/// A running loopback API.
pub(crate) struct LoopbackApi {
    /// `http://127.0.0.1:<port>`.
    pub(crate) url: String,
    /// Request lines in arrival order (`POST /v1/auth/login HTTP/1.1`).
    pub(crate) requests: Arc<Mutex<Vec<String>>>,
}

impl LoopbackApi {
    /// How many recorded request lines start with `prefix`.
    pub(crate) fn count(&self, prefix: &str) -> usize {
        self.requests
            .lock()
            .unwrap()
            .iter()
            .filter(|line| line.starts_with(prefix))
            .count()
    }
}

/// Serve `route(request line, JSON body or Null)` on a loopback port.
pub(crate) async fn serve<F>(route: F) -> LoopbackApi
where
    F: Fn(&str, &Value) -> Reply + Send + Sync + 'static,
{
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let requests = Arc::new(Mutex::new(Vec::new()));
    let (route, log) = (Arc::new(route), requests.clone());
    tokio::spawn(async move {
        while let Ok((mut stream, _)) = listener.accept().await {
            let (route, log) = (route.clone(), log.clone());
            tokio::spawn(async move {
                let raw = read_request(&mut stream).await;
                let line = raw.lines().next().unwrap_or_default().to_owned();
                let body = raw
                    .split_once("\r\n\r\n")
                    .and_then(|(_, body)| serde_json::from_str(body).ok())
                    .unwrap_or(Value::Null);
                log.lock().unwrap().push(line.clone());
                let reply = match route(&line, &body) {
                    Reply::Json(value) => respond(&value),
                    Reply::JsonWithCookie(value) => respond(&value).replacen(
                        "\r\n",
                        "\r\nSet-Cookie: auth_refresh_token=synthetic-refresh; Path=/\r\n",
                        1,
                    ),
                    Reply::Status(status, value) => respond(&value)
                        .replacen("200 OK", &format!("{status} Refused"), 1),
                    Reply::Close => return,
                    Reply::Hang(duration) => {
                        tokio::time::sleep(duration).await;
                        return;
                    }
                };
                let _ = stream.write_all(reply.as_bytes()).await;
            });
        }
    });
    LoopbackApi { url, requests }
}
