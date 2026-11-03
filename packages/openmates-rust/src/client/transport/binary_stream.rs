//! Non-JSON authenticated transport: binary GET downloads and SSE streams.
//! Both reuse the ordinary pre-send fences and credential headers
//! (`prepare_http_request`) and the unchanged post-send status, cookie
//! rotation, owner and generation fences. Only the Accept header and body
//! decoding differ. Mirrors npm `OpenMatesHttpClient.getBinary`/`streamSse`.
use super::*;
use zeroize::Zeroizing;

/// Error bodies are never surfaced; read only enough for the owner check.
const MAX_ERROR_BODY: usize = 4096;
/// One SSE event may not grow the pending buffer past this bound.
pub const MAX_SSE_EVENT: usize = 1024 * 1024;
/// npm SSE reads have no deadline; reqwest needs an explicit long one.
const SSE_TIMEOUT: Duration = Duration::from_secs(30 * 24 * 60 * 60);

/// A completed binary GET. Non-success statuses carry no body.
pub struct BinaryResponse {
    pub status: u16,
    pub content_type: Option<String>,
    pub content_disposition: Option<String>,
    pub data: Zeroizing<Vec<u8>>,
}
impl BinaryResponse {
    pub fn ok(&self) -> bool {
        (200..300).contains(&self.status)
    }
}

/// npm `SseMessage`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SseMessage {
    pub id: Option<String>,
    pub event: Option<String>,
    pub data: String,
}

/// npm `parseSseMessage` for one raw event block (split on "\n\n").
pub fn parse_sse_message(raw: &str) -> Option<SseMessage> {
    let mut message = SseMessage {
        id: None,
        event: None,
        data: String::new(),
    };
    for line in raw.split('\n') {
        if line.is_empty() || line.starts_with(':') {
            continue;
        }
        let (field, value) = match line.find(':') {
            Some(index) => {
                let value = &line[index + 1..];
                (&line[..index], value.strip_prefix(' ').unwrap_or(value))
            }
            None => (line, ""),
        };
        match field {
            "id" => message.id = Some(value.to_owned()),
            "event" => message.event = Some(value.to_owned()),
            "data" => {
                if !message.data.is_empty() {
                    message.data.push('\n');
                }
                message.data.push_str(value);
            }
            _ => {}
        }
    }
    (!message.data.is_empty()).then_some(message)
}

/// Incremental npm SSE framing: events end at the first "\n\n"; a trailing
/// partial event at end of stream is discarded like the npm generator.
#[derive(Default)]
pub struct SseParser {
    buffer: Vec<u8>,
    ready: std::collections::VecDeque<SseMessage>,
}
impl SseParser {
    pub fn push(&mut self, chunk: &[u8]) -> Result<()> {
        self.buffer.extend_from_slice(chunk);
        while let Some(index) = self.buffer.windows(2).position(|w| w == b"\n\n") {
            let raw: Vec<u8> = self.buffer.drain(..index + 2).collect();
            if let Some(message) = parse_sse_message(&String::from_utf8_lossy(&raw[..index])) {
                self.ready.push_back(message);
            }
        }
        if self.buffer.len() > MAX_SSE_EVENT {
            return Err(Error::Protocol);
        }
        Ok(())
    }
    pub fn pop(&mut self) -> Option<SseMessage> {
        self.ready.pop_front()
    }
}

/// An open SSE response. It owns only the response body and the operation
/// cancellation token; credentials were applied when the stream opened.
pub struct SseStream {
    response: crate::platform::http::Response,
    parser: SseParser,
    cancel: CancellationToken,
    done: bool,
}
impl SseStream {
    /// The next event, or `None` when the server ends the stream.
    pub async fn next(&mut self) -> Result<Option<SseMessage>> {
        loop {
            if let Some(message) = self.parser.pop() {
                return Ok(Some(message));
            }
            if self.done {
                return Ok(None);
            }
            let chunk = tokio::select! {
                _ = self.cancel.cancelled() => return Err(Error::Cancelled),
                chunk = self.response.chunk() => chunk.map_err(|_| Error::Offline)?,
            };
            match chunk {
                Some(chunk) => self.parser.push(&chunk)?,
                None => self.done = true,
            }
        }
    }
}

/// `Ok(stream)` for a 2xx response, else the HTTP status (npm reports
/// "SSE request failed with HTTP <status>").
pub enum SseOpen {
    Stream(SseStream),
    Status(u16),
}

fn header_text(
    response: &crate::platform::http::Response,
    name: reqwest::header::HeaderName,
) -> Option<String> {
    response
        .headers()
        .get(name)
        .and_then(|v| v.to_str().ok())
        .map(str::to_owned)
}

impl Client {
    /// Ordinary credentials with a caller Accept value replacing the JSON one.
    fn prepare_accepting(
        &mut self,
        path: &str,
        accept: &'static str,
        timeout: Option<Duration>,
    ) -> Result<(
        crate::platform::http::RequestBuilder,
        u64,
        Option<super::super::monitor::MonitorReadOrigin>,
    )> {
        let (request, generation, monitor_origin) =
            self.prepare_http_request(Method::GET, path, None, None, None, None, None)?;
        let (http, built) = request.build_split();
        let mut built = built.map_err(|_| Error::Protocol)?;
        built.headers_mut().insert(
            reqwest::header::ACCEPT,
            reqwest::header::HeaderValue::from_static(accept),
        );
        if let Some(timeout) = timeout {
            *built.timeout_mut() = Some(timeout);
        }
        Ok((
            reqwest::RequestBuilder::from_parts(http, built),
            generation,
            monitor_origin,
        ))
    }

    /// The unchanged ordinary status/cookie/owner fences before any body is
    /// trusted. `Ok(true)` means a success status whose body may be read.
    async fn admit_non_json(
        &mut self,
        path: &str,
        response: &mut crate::platform::http::Response,
        generation: u64,
        monitor_origin: Option<super::super::monitor::MonitorReadOrigin>,
    ) -> Result<bool> {
        let status = response.status();
        let unavailable = self
            .url(path)
            .and_then(|url| self.request_route_path(&url))
            .is_ok_and(|route| cache_namespace_unavailable(status.as_u16(), &route));
        if status.as_u16() == 403 || unavailable || status.is_redirection() {
            self.chat_list_freshness.invalidate();
        }
        if status.as_u16() == 401 {
            self.note_monitor_http_denial(401, monitor_origin)?;
            self.forget_session();
            return Err(Error::Expired);
        }
        let monitor_denied =
            status.as_u16() == 403 && self.note_monitor_http_denial(403, monitor_origin)?;
        if status.is_redirection() {
            return Err(Error::Forbidden);
        }
        self.apply_owned_response_cookies(response.headers(), generation)?;
        if status.is_success() {
            return Ok(true);
        }
        let mut bytes = Zeroizing::new(Vec::new());
        while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
            if bytes.len() + chunk.len() > MAX_ERROR_BODY {
                break;
            }
            bytes.extend_from_slice(&chunk);
        }
        if self.generation != generation {
            return Err(Error::Cancelled);
        }
        if status.as_u16() == 403 && super::super::browser::expected_principal_mismatch(&bytes) {
            self.forget_session();
            return Err(Error::Expired);
        }
        if monitor_denied {
            return Err(Error::Forbidden);
        }
        Ok(false)
    }

    /// npm `getBinary`: authenticated GET returning raw bytes (bounded by the
    /// ordinary 16 MiB body limit) plus content headers.
    pub async fn get_binary(&mut self, path: &str, accept: &'static str) -> Result<BinaryResponse> {
        self.require_session()?;
        let (request, generation, monitor_origin) = self.prepare_accepting(path, accept, None)?;
        let mut response = request.send().await.map_err(|_| Error::Offline)?;
        let status = response.status().as_u16();
        let content_type = header_text(&response, reqwest::header::CONTENT_TYPE);
        let content_disposition = header_text(&response, reqwest::header::CONTENT_DISPOSITION);
        let readable = self
            .admit_non_json(path, &mut response, generation, monitor_origin)
            .await?;
        let mut data = Zeroizing::new(Vec::new());
        if readable {
            if response
                .content_length()
                .is_some_and(|n| n > MAX_BODY as u64)
            {
                return Err(Error::Protocol);
            }
            while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
                if data.len() + chunk.len() > MAX_BODY {
                    return Err(Error::Protocol);
                }
                data.extend_from_slice(&chunk);
            }
            if self.generation != generation {
                return Err(Error::Cancelled);
            }
        }
        Ok(BinaryResponse {
            status,
            content_type,
            content_disposition,
            data,
        })
    }

    /// npm `streamSse`: authenticated `text/event-stream` GET.
    pub async fn open_sse(&mut self, path: &str) -> Result<SseOpen> {
        self.require_session()?;
        let (request, generation, monitor_origin) =
            self.prepare_accepting(path, "text/event-stream", Some(SSE_TIMEOUT))?;
        let mut response = request.send().await.map_err(|_| Error::Offline)?;
        let status = response.status().as_u16();
        if !self
            .admit_non_json(path, &mut response, generation, monitor_origin)
            .await?
        {
            return Ok(SseOpen::Status(status));
        }
        Ok(SseOpen::Stream(SseStream {
            response,
            parser: SseParser::default(),
            cancel: self.operation_cancel.clone(),
            done: false,
        }))
    }
}

#[cfg(test)]
#[path = "binary_stream_tests.rs"]
mod tests;
