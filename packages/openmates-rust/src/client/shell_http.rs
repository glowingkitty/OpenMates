//! Authenticated HTTP passthrough for shell code that is not migrated yet:
//! a shell hands over method, API path, query, allow-listed headers and body
//! bytes; the core sends them with ITS session (cookies, expected principal),
//! applies rotated cookies to its own jar, and on a server rejection forgets
//! the session exactly as its own transport does (`transport.rs`
//! `finish_http_response`). Three phases (prepare with `&mut Client`, send
//! without it, finish with `&mut Client`) so several shell requests can be on
//! the network while the actor is free. Transport only, no feature logic.
//! Temporary: plan `apple-client-core-migration` step A6 deletes it once the
//! Apple shell features run in the core. Native only. Spec `client-core`.
use super::transport::{MAX_BODY, cookie_header};
use super::*;
use reqwest::header::{COOKIE, HeaderMap};
use zeroize::Zeroizing;

/// Largest accepted request body (the core's own response limit).
pub const SHELL_HTTP_MAX_REQUEST_BODY: usize = MAX_BODY;
/// Largest accepted response body; a longer one fails with `Protocol`.
pub const SHELL_HTTP_MAX_RESPONSE_BODY: usize = MAX_BODY;
/// Longest accepted API path (without query).
const MAX_PATH: usize = 2048;
/// Most query pairs, request headers, and the longest name/value.
const MAX_QUERY_PAIRS: usize = 64;
const MAX_HEADERS: usize = 16;
const MAX_NAME: usize = 256;
const MAX_VALUE: usize = 4096;

/// Request headers a shell may set. Everything authenticating or identifying
/// the request (`Cookie`, `Authorization`, `Origin`, `Host`, the
/// `X-OpenMates-*` client and principal headers) is set by the core only.
const REQUEST_HEADERS: [&str; 8] = [
    "accept",
    "accept-language",
    "cache-control",
    "content-type",
    "idempotency-key",
    "if-match",
    "if-none-match",
    "pragma",
];

/// Response headers handed back; `Set-Cookie` never leaves the core.
const RESPONSE_HEADERS: [&str; 7] = [
    "cache-control",
    "content-disposition",
    "content-language",
    "content-type",
    "etag",
    "last-modified",
    "retry-after",
];

/// Session-lifecycle routes the core alone calls; a shell request to them
/// would sign in, rotate or revoke the core's session behind its back.
fn core_owned_route(path: &str) -> bool {
    path == "/v1/auth/logout"
        || path == "/v1/auth/session"
        || path == "/v1/auth/login"
        || path.starts_with("/v1/auth/login/")
}

/// Password-migration routes: a 401 there answers a wrong or stale password
/// proof, not a dead session, so the session must survive it (the shell shows
/// the error and the user retries).
fn keeps_session_on_401(path: &str) -> bool {
    path.starts_with("/v1/auth/password-v2/")
}

/// One shell request. `body` is zeroized on drop (it may carry plaintext).
pub struct ShellHttpRequest {
    /// `GET`, `POST`, `PUT`, `PATCH` or `DELETE`.
    pub method: String,
    /// Absolute API path starting with `/v1/`, without query or fragment.
    pub path: String,
    /// Query pairs, percent-encoded by the core.
    pub query: Vec<(String, String)>,
    /// Allow-listed request headers (case-insensitive names).
    pub headers: Vec<(String, String)>,
    /// Request body; refused for `GET`.
    pub body: Option<Zeroizing<Vec<u8>>>,
}

/// The server's answer. Every status except 401, a redirect and an
/// expected-principal denial is returned as is; the body is zeroized on drop.
pub struct ShellHttpResponse {
    /// HTTP status code.
    pub status: u16,
    /// Allow-listed response headers, lower-case names, in arrival order.
    pub headers: Vec<(String, String)>,
    /// Response body (at most [`SHELL_HTTP_MAX_RESPONSE_BODY`] bytes).
    pub body: Zeroizing<Vec<u8>>,
    /// The response rotated the session's cookies: the shell persists the
    /// client's credentials before reporting success.
    pub credentials_changed: bool,
}

/// A request built from the current session; send it without the client.
pub struct PreparedShellHttp {
    request: crate::platform::http::RequestBuilder,
    binding: Binding,
    keeps_session_on_401: bool,
}

/// What the response was received for: the same session and generation
/// must still be current when it is finished (shared with `shell_upload`).
pub(super) struct Binding {
    generation: u64,
    session_id: Zeroizing<String>,
}

impl Binding {
    /// Binding to the client's current session and generation.
    ///
    /// # Errors
    /// `Authentication` without a session.
    pub(super) fn current(client: &Client) -> Result<Self> {
        Ok(Self {
            generation: client.generation,
            session_id: Zeroizing::new(client.require_session()?.session_id.clone()),
        })
    }

    /// The session and generation are still the ones prepared for.
    pub(super) fn is_current(&self, client: &Client) -> bool {
        client
            .session()
            .is_some_and(|session| session.session_id == *self.session_id)
            && client.generation == self.generation
    }
}

/// Status, headers and (bounded) body of one received response.
pub(super) struct Received {
    pub(super) status: u16,
    pub(super) headers: HeaderMap,
    pub(super) body: Result<Zeroizing<Vec<u8>>>,
}

/// The allow-listed response headers, lower-case names, in arrival order.
pub(super) fn response_headers(headers: &HeaderMap) -> Vec<(String, String)> {
    headers
        .iter()
        .filter(|(name, _)| RESPONSE_HEADERS.contains(&name.as_str()))
        .filter_map(|(name, value)| {
            Some((name.as_str().to_owned(), value.to_str().ok()?.to_owned()))
        })
        .collect()
}

/// A sent request; hand it back to [`Client::finish_shell_http`].
pub struct SentShellHttp {
    binding: Binding,
    received: Result<Received>,
    keeps_session_on_401: bool,
}

/// Empty, longer than `max` bytes or containing a control character.
pub(super) fn invalid_text(text: &str, max: usize) -> bool {
    text.is_empty() || text.len() > max || text.chars().any(char::is_control)
}

/// Checks the path shape: `/v1/...`, no query/fragment/backslash, no empty,
/// `.` or `..` segment (also percent-encoded), printable ASCII only.
fn checked_path(path: &str) -> Result<()> {
    let printable = path.bytes().all(|byte| byte.is_ascii_graphic());
    if !path.starts_with("/v1/") || path.len() > MAX_PATH || !printable {
        return Err(Error::Invalid("Supply an API path starting with /v1/."));
    }
    if path.contains(['?', '#', '\\']) {
        return Err(Error::Invalid("Pass the query separately; no fragment."));
    }
    let lowered = path.to_ascii_lowercase();
    let dot = |segment: &str| matches!(segment, "." | ".." | "%2e" | "%2e%2e" | ".%2e" | "%2e.");
    let segments: Vec<&str> = lowered[1..].split('/').collect();
    // An empty segment is allowed only as the trailing slash.
    let empty = segments[..segments.len() - 1].iter().any(|s| s.is_empty());
    if empty
        || segments.iter().any(|s| dot(s))
        || lowered.contains("%2f")
        || lowered.contains("%5c")
    {
        return Err(Error::Invalid("The API path has an invalid segment."));
    }
    Ok(())
}

fn checked_method(method: &str) -> Result<Method> {
    Ok(match method {
        "GET" => Method::GET,
        "POST" => Method::POST,
        "PUT" => Method::PUT,
        "PATCH" => Method::PATCH,
        "DELETE" => Method::DELETE,
        _ => return Err(Error::Invalid("Unsupported HTTP method.")),
    })
}

fn checked_headers(headers: &[(String, String)]) -> Result<Vec<(&'static str, &str)>> {
    if headers.len() > MAX_HEADERS {
        return Err(Error::Invalid("Too many request headers."));
    }
    headers
        .iter()
        .map(|(name, value)| {
            let lowered = name.to_ascii_lowercase();
            let name = REQUEST_HEADERS
                .into_iter()
                .find(|allowed| *allowed == lowered)
                .ok_or(Error::Invalid(
                    "This request header is set by the core only.",
                ))?;
            if invalid_text(value, MAX_VALUE) || !value.is_ascii() {
                return Err(Error::Invalid("Invalid request header value."));
            }
            Ok((name, value.as_str()))
        })
        .collect()
}

impl Client {
    /// Build `request` with this client's session: the URL is joined to the
    /// configured API origin only, the core sets cookies, `Origin`, client
    /// identity and expected principal, and a write invalidates the chat-list
    /// freshness proof as every core write does.
    ///
    /// # Errors
    /// `Authentication` without a session, `Expired` for a lapsed pairing,
    /// `Forbidden` for browser credentials, a core-owned auth route or another
    /// origin, `Invalid` for a malformed method, path, query, header or a
    /// body on `GET` or over [`SHELL_HTTP_MAX_REQUEST_BODY`], `Protocol` for
    /// unusable stored cookies.
    pub fn prepare_shell_http(&mut self, request: ShellHttpRequest) -> Result<PreparedShellHttp> {
        if self.browser_cookies() {
            return Err(Error::Forbidden);
        }
        let binding = Binding::current(self)?;
        let method = checked_method(&request.method)?;
        checked_path(&request.path)?;
        if core_owned_route(&request.path) {
            return Err(Error::Forbidden);
        }
        if request.query.len() > MAX_QUERY_PAIRS
            || request
                .query
                .iter()
                .any(|(name, value)| invalid_text(name, MAX_NAME) || value.len() > MAX_VALUE)
        {
            return Err(Error::Invalid("Invalid query parameters."));
        }
        let headers = checked_headers(&request.headers)?;
        match &request.body {
            Some(_) if method == Method::GET => {
                return Err(Error::Invalid("A GET request has no body."));
            }
            Some(body) if body.len() > SHELL_HTTP_MAX_REQUEST_BODY => {
                return Err(Error::Invalid("The request body is too large."));
            }
            _ => {}
        }
        // `url` refuses another origin; the joined path must still be the
        // checked one (no normalization moved it).
        let mut url = self.url(&request.path)?;
        if url.path() != request.path {
            return Err(Error::Forbidden);
        }
        if !request.query.is_empty() {
            url.query_pairs_mut().extend_pairs(&request.query);
        }
        self.invalidate_chat_inventory_proofs();
        if method != Method::GET {
            // The server effect of a shell write is unknown to the core.
            self.chat_list_freshness.invalidate();
        }
        let mut builder = self
            .http
            .request(method, url)
            .header("X-OpenMates-SDK", self.options.identity.header())
            .header("Origin", self.app_url());
        if !headers.iter().any(|(name, _)| *name == "accept") {
            builder = builder.header("Accept", "application/json");
        }
        for (name, value) in headers {
            builder = builder.header(name, value);
        }
        if let Some(expected) = self.expected_request_principal()? {
            builder = builder.header("X-OpenMates-Expected-Principal", expected);
        }
        let cookies = Zeroizing::new(cookie_header(&self.cookies)?);
        if !cookies.is_empty() {
            builder = builder.header(COOKIE, cookies.as_str());
        }
        if let Some(body) = request.body {
            builder = builder.body(body.to_vec());
        }
        Ok(PreparedShellHttp {
            request: builder,
            binding,
            keeps_session_on_401: keeps_session_on_401(&request.path),
        })
    }

    /// Apply the outcome of `sent` to this client: a 401 or an
    /// expected-principal 403 forgets the session (`Expired`, as the core's
    /// own requests; a 401 on a `/v1/auth/password-v2/` route is returned as a
    /// response and keeps the session); otherwise rotated cookies are merged into the client's
    /// jar (also when the body then failed) and the response is returned.
    ///
    /// # Errors
    /// `Cancelled` when the session or generation changed since prepare (the
    /// response is dropped, its cookies are not applied) or when the send was
    /// cancelled; `Offline` without a response or for a broken body;
    /// `Expired` for a rejected session; `Forbidden` for a redirect;
    /// `Protocol` for an oversized body or malformed cookies.
    pub fn finish_shell_http(&mut self, sent: SentShellHttp) -> Result<ShellHttpResponse> {
        let SentShellHttp {
            binding,
            received,
            keeps_session_on_401,
        } = sent;
        if !binding.is_current(self) {
            return Err(Error::Cancelled);
        }
        let received = received?;
        let status = received.status;
        let redirect = (300..400).contains(&status);
        if status == 403 || redirect {
            self.chat_list_freshness.invalidate();
        }
        if status == 401 && !keeps_session_on_401 {
            self.forget_session();
            return Err(Error::Expired);
        }
        if redirect {
            return Err(Error::Forbidden);
        }
        let revision = self.credential_revision;
        self.apply_owned_response_cookies(&received.headers, binding.generation)?;
        let credentials_changed = self.credential_revision != revision;
        let body = received.body?;
        if status == 403 && super::browser::expected_principal_mismatch(&body) {
            // As the core transport: the whole owner is revoked.
            self.forget_session();
            return Err(Error::Expired);
        }
        let headers = response_headers(&received.headers);
        Ok(ShellHttpResponse {
            status,
            headers,
            body,
            credentials_changed,
        })
    }
}

impl PreparedShellHttp {
    /// Send the request and read the whole body. `cancel` stops waiting for
    /// headers or body; a response whose headers arrived keeps them, so a
    /// rotated cookie is still applied by the finish step.
    pub async fn send(self, cancel: &CancellationToken) -> SentShellHttp {
        let Self {
            request,
            binding,
            keeps_session_on_401,
        } = self;
        let received = tokio::select! {
            biased;
            () = cancel.cancelled() => Err(Error::Cancelled),
            response = request.send() => match response {
                Err(_) => Err(Error::Offline),
                Ok(response) => Ok(read(response, cancel).await),
            },
        };
        SentShellHttp {
            binding,
            received,
            keeps_session_on_401,
        }
    }
}

/// Read status, headers and the whole body (bounded by
/// [`SHELL_HTTP_MAX_RESPONSE_BODY`]); `cancel` stops the body read.
pub(super) async fn read(
    mut response: crate::platform::http::Response,
    cancel: &CancellationToken,
) -> Received {
    let status = response.status().as_u16();
    let headers = response.headers().clone();
    let body = async {
        if response
            .content_length()
            .is_some_and(|length| length > SHELL_HTTP_MAX_RESPONSE_BODY as u64)
        {
            return Err(Error::Protocol);
        }
        let mut bytes = Zeroizing::new(Vec::new());
        loop {
            let chunk = tokio::select! {
                biased;
                () = cancel.cancelled() => return Err(Error::Cancelled),
                chunk = response.chunk() => chunk.map_err(|_| Error::Offline)?,
            };
            let Some(chunk) = chunk else {
                return Ok(bytes);
            };
            if bytes.len() + chunk.len() > SHELL_HTTP_MAX_RESPONSE_BODY {
                return Err(Error::Protocol);
            }
            bytes.extend_from_slice(&chunk);
        }
    }
    .await;
    Received {
        status,
        headers,
        body,
    }
}

#[cfg(test)]
#[path = "shell_http_tests.rs"]
mod tests;
