//! Minimal HTTP/1.1 framing for the sandbox host daemon: one request per
//! connection (`Connection: close`), JSON bodies, `Content-Length` only.
//! Bodies are never logged. Owned by the sandbox host; no TS counterpart.
use serde_json::Value;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

const MAX_HEAD: usize = 32 * 1024;

/// Request line and the headers the daemon cares about.
pub(super) struct Head {
    pub(super) method: String,
    /// Path without query string.
    pub(super) path: String,
    /// Value after `Bearer ` of the `Authorization` header.
    pub(super) bearer: Option<String>,
    pub(super) content_length: usize,
    /// Body bytes that arrived together with the head.
    pub(super) leftover: Vec<u8>,
}

/// Why a request could not be read; maps to a status and error code.
pub(super) enum ReadError {
    Bad(&'static str),
    TooLarge,
    Io,
}

/// Reads and parses the request head (not the body).
pub(super) async fn read_head<S: AsyncRead + Unpin>(stream: &mut S) -> Result<Head, ReadError> {
    let mut buf = Vec::with_capacity(2048);
    let mut chunk = [0u8; 4096];
    loop {
        let mut headers = [httparse::EMPTY_HEADER; 48];
        let mut request = httparse::Request::new(&mut headers);
        match request.parse(&buf) {
            Ok(httparse::Status::Complete(end)) => {
                let mut bearer = None;
                let mut content_length = 0usize;
                for header in request.headers.iter() {
                    let name = header.name.to_ascii_lowercase();
                    let value = String::from_utf8_lossy(header.value).trim().to_owned();
                    match name.as_str() {
                        "authorization" => {
                            bearer = value.strip_prefix("Bearer ").map(str::to_owned);
                        }
                        "content-length" => {
                            content_length = value
                                .parse()
                                .map_err(|_| ReadError::Bad("bad_content_length"))?;
                        }
                        "transfer-encoding" => return Err(ReadError::Bad("unsupported_encoding")),
                        _ => {}
                    }
                }
                let path = request.path.unwrap_or("/");
                return Ok(Head {
                    method: request.method.unwrap_or("").to_owned(),
                    path: path.split('?').next().unwrap_or("/").to_owned(),
                    bearer,
                    content_length,
                    leftover: buf[end..].to_vec(),
                });
            }
            Ok(httparse::Status::Partial) => {}
            Err(_) => return Err(ReadError::Bad("bad_request")),
        }
        if buf.len() > MAX_HEAD {
            return Err(ReadError::TooLarge);
        }
        let n = stream.read(&mut chunk).await.map_err(|_| ReadError::Io)?;
        if n == 0 {
            return Err(ReadError::Io);
        }
        buf.extend_from_slice(&chunk[..n]);
    }
}

/// Reads the remaining body bytes announced by `Content-Length`.
pub(super) async fn read_body<S: AsyncRead + Unpin>(
    stream: &mut S,
    head: Head,
    max_body: usize,
) -> Result<Vec<u8>, ReadError> {
    if head.content_length > max_body {
        return Err(ReadError::TooLarge);
    }
    let mut body = head.leftover;
    body.truncate(head.content_length);
    let mut chunk = vec![0u8; 64 * 1024];
    while body.len() < head.content_length {
        let want = (head.content_length - body.len()).min(chunk.len());
        let n = stream
            .read(&mut chunk[..want])
            .await
            .map_err(|_| ReadError::Io)?;
        if n == 0 {
            return Err(ReadError::Io);
        }
        body.extend_from_slice(&chunk[..n]);
    }
    Ok(body)
}

/// Writes a JSON response and closes the exchange.
pub(super) async fn write_json<S: AsyncWrite + Unpin>(stream: &mut S, status: u16, body: &Value) {
    let payload = serde_json::to_vec(body).unwrap_or_else(|_| b"{}".to_vec());
    let reason = match status {
        200 => "OK",
        400 => "Bad Request",
        401 => "Unauthorized",
        404 => "Not Found",
        405 => "Method Not Allowed",
        409 => "Conflict",
        413 => "Payload Too Large",
        _ => "Internal Server Error",
    };
    let head = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        payload.len()
    );
    // A client that went away is not an error worth reporting.
    let _ = stream.write_all(head.as_bytes()).await;
    let _ = stream.write_all(&payload).await;
    let _ = stream.shutdown().await;
}
