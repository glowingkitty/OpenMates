//! The `openmates-sandbox-host serve` daemon: a small HTTP/1.1 JSON server
//! around [`ProjectTree`]. One shared state behind a mutex, bearer token on
//! every endpoint, no request body ever logged. Mirrors the contract in
//! `docs/plans/hosted-project-sandbox/contracts.md` section 2.
use std::sync::Arc;
use tokio::net::TcpListener;

mod handlers;
mod http;
mod owner;
#[cfg(test)]
mod tests;

pub use handlers::{Host, HostConfig};
pub use owner::{RunUser, make_non_dumpable};

/// Largest accepted request body (sync-in batches).
pub const MAX_BODY: usize = 64 * 1024 * 1024;

/// Serves `host` on `listener` until the process ends.
pub async fn serve(listener: TcpListener, host: Arc<Host>) {
    loop {
        let Ok((stream, _)) = listener.accept().await else {
            continue;
        };
        let host = Arc::clone(&host);
        tokio::spawn(async move {
            let _ = tokio::time::timeout(
                std::time::Duration::from_secs(600),
                connection(stream, host),
            )
            .await;
        });
    }
}

async fn connection(mut stream: tokio::net::TcpStream, host: Arc<Host>) {
    use http::{ReadError, read_body, read_head, write_json};
    use serde_json::json;
    let head = match read_head(&mut stream).await {
        Ok(head) => head,
        Err(error) => {
            let (status, code) = match error {
                ReadError::Bad(code) => (400, code),
                ReadError::TooLarge => (413, "too_large"),
                ReadError::Io => return,
            };
            return write_json(&mut stream, status, &json!({"error": code})).await;
        }
    };
    // Authorise before reading the body so an unauthenticated peer cannot make us buffer it.
    if !host.authorized(head.bearer.as_deref()) {
        return write_json(&mut stream, 401, &json!({"error": "unauthorized"})).await;
    }
    let (method, path) = (head.method.clone(), head.path.clone());
    let body = match read_body(&mut stream, head, MAX_BODY).await {
        Ok(body) => body,
        Err(ReadError::TooLarge) => {
            return write_json(&mut stream, 413, &json!({"error": "too_large"})).await;
        }
        Err(ReadError::Bad(code)) => {
            return write_json(&mut stream, 400, &json!({"error": code})).await;
        }
        Err(ReadError::Io) => return,
    };
    let worker = Arc::clone(&host);
    let reply = tokio::task::spawn_blocking(move || worker.handle(&method, &path, &body)).await;
    match reply {
        Ok((status, value)) => write_json(&mut stream, status, &value).await,
        Err(_) => write_json(&mut stream, 500, &json!({"error": "internal"})).await,
    }
}
