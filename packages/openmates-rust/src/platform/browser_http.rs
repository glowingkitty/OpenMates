//! Browser Fetch adapter. No cookie access, redirects, ambient credentials or
//! raw JavaScript error values cross this boundary. The owner is a worker.
use crate::error::{Error, Result};
use crate::platform::{require_http_budget, within_http_budget};
use futures_util::StreamExt;
use reqwest::{Method, StatusCode, header::HeaderMap};
use serde::Serialize;
use wasm_bindgen::{JsCast, JsValue};
use wasm_bindgen_futures::JsFuture;
use zeroize::Zeroizing;

#[derive(Clone)]
pub(crate) struct Client;
pub(crate) struct RequestBuilder {
    method: Method,
    url: url::Url,
    headers: HeaderMap,
    body: Option<Zeroizing<String>>,
    plaintext_body: Option<tungstenite::Bytes>,
    include: bool,
    no_store: bool,
    invalid: bool,
    timeout: std::time::Duration,
}
struct Abort(web_sys::AbortController);
impl Drop for Abort {
    fn drop(&mut self) {
        self.0.abort();
    }
}
pub(crate) struct Response {
    status: StatusCode,
    headers: HeaderMap,
    stream: Option<wasm_streams::readable::IntoStream<'static>>,
    _abort: Abort,
    deadline: crate::platform::time::Instant,
}
impl Client {
    pub(crate) fn request(&self, method: Method, url: url::Url) -> RequestBuilder {
        RequestBuilder {
            method,
            url,
            headers: HeaderMap::new(),
            body: None,
            plaintext_body: None,
            include: false,
            no_store: false,
            invalid: false,
            timeout: std::time::Duration::from_secs(60),
        }
    }
    pub(crate) fn get(&self, url: url::Url) -> RequestBuilder {
        self.request(Method::GET, url)
    }
    pub(crate) fn post(&self, url: url::Url) -> RequestBuilder {
        self.request(Method::POST, url)
    }
}
impl RequestBuilder {
    // Match reqwest's WASM builder operation without exposing cache policy to JS.
    pub(crate) fn fetch_cache_no_store(mut self) -> Self {
        self.no_store = true;
        self
    }
    pub(super) fn credentials(mut self, include: bool) -> Self {
        self.include = include;
        self
    }
    pub(crate) fn header(mut self, name: impl AsRef<str>, value: impl AsRef<str>) -> Self {
        // Origin is supplied exclusively by the browser. This value is always
        // a core-computed native compatibility header, never Fetch authority.
        if name.as_ref().eq_ignore_ascii_case("origin") {
            return self;
        }
        if name.as_ref().eq_ignore_ascii_case("cookie")
            || name.as_ref().eq_ignore_ascii_case("set-cookie")
        {
            self.invalid = true;
            return self;
        }
        match (
            reqwest::header::HeaderName::from_bytes(name.as_ref().as_bytes()),
            reqwest::header::HeaderValue::from_str(value.as_ref()),
        ) {
            (Ok(name), Ok(value)) => {
                self.headers.insert(name, value);
            }
            _ => self.invalid = true,
        }
        self
    }
    pub(crate) fn bearer_auth(self, token: &str) -> Self {
        self.header("Authorization", format!("Bearer {token}"))
    }
    // Like reqwest's per-request override, this budget covers headers AND the
    // entire streamed body. Response retains the same absolute deadline.
    pub(crate) fn timeout(mut self, timeout: std::time::Duration) -> Self {
        self.timeout = timeout;
        self
    }
    /// Retain the application cleanup owner until Fetch finishes or is cancelled.
    /// JavaScript/Fetch copies are browser-owned and cannot be wiped by Rust.
    pub(crate) fn body(mut self, value: tungstenite::Bytes) -> Self {
        self.body = None;
        self.plaintext_body = Some(value);
        self
    }
    pub(crate) fn json<T: Serialize + ?Sized>(mut self, value: &T) -> Self {
        self.plaintext_body = None;
        match serde_json::to_string(value) {
            Ok(value) => self.body = Some(Zeroizing::new(value)),
            Err(_) => self.invalid = true,
        }
        self.header("Content-Type", "application/json")
    }
    pub(crate) async fn send(self) -> Result<Response> {
        if self.invalid {
            return Err(Error::Forbidden);
        }
        let deadline = crate::platform::time::Instant::now()
            .checked_add(self.timeout)
            .ok_or(Error::Invalid("Invalid request timeout."))?;
        let abort = Abort(web_sys::AbortController::new().map_err(|_| Error::Offline)?);
        let init = web_sys::RequestInit::new();
        init.set_method(self.method.as_str());
        if self.no_store {
            init.set_cache(web_sys::RequestCache::NoStore);
        }
        init.set_redirect(web_sys::RequestRedirect::Error);
        init.set_credentials(if self.include {
            web_sys::RequestCredentials::Include
        } else {
            web_sys::RequestCredentials::Omit
        });
        init.set_signal(Some(&abort.0.signal()));
        let headers = web_sys::Headers::new().map_err(|_| Error::Protocol)?;
        for (name, value) in &self.headers {
            headers
                .set(name.as_str(), value.to_str().map_err(|_| Error::Protocol)?)
                .map_err(|_| Error::Protocol)?;
        }
        init.set_headers(headers.as_ref());
        if let Some(body) = &self.plaintext_body {
            let body = std::str::from_utf8(body).map_err(|_| Error::Protocol)?;
            init.set_body(&JsValue::from_str(body));
        } else if let Some(body) = &self.body {
            init.set_body(&JsValue::from_str(body));
        }
        let request = web_sys::Request::new_with_str_and_init(self.url.as_str(), &init)
            .map_err(|_| Error::Protocol)?;
        // Worker-global Fetch, with no Window or DOM dependency.
        let global = js_sys::global();
        let fetch = js_sys::Reflect::get(&global, &JsValue::from_str("fetch"))
            .map_err(|_| Error::Offline)?
            .dyn_into::<js_sys::Function>()
            .map_err(|_| Error::Offline)?;
        require_http_budget(crate::platform::time::Instant::now(), deadline, &|| {
            abort.0.abort()
        })?;
        let promise = fetch
            .call1(&global, request.as_ref())
            .map_err(|_| Error::Offline)?
            .dyn_into::<js_sys::Promise>()
            .map_err(|_| Error::Offline)?;
        let raw = within_http_budget(
            deadline,
            crate::platform::time::Instant::now,
            || abort.0.abort(),
            async {
                super::super::time::timeout_at(deadline, JsFuture::from(promise))
                    .await
                    .map_err(|_| Error::Offline)?
                    .map_err(|_| Error::Offline)
            },
        )
        .await?
        .dyn_into::<web_sys::Response>()
        .map_err(|_| Error::Protocol)?;
        let status = StatusCode::from_u16(raw.status()).map_err(|_| Error::Protocol)?;
        if status.is_redirection() {
            return Err(Error::Forbidden);
        }
        let mut response_headers = HeaderMap::new();
        let entries = js_sys::try_iter(raw.headers().as_ref())
            .map_err(|_| Error::Protocol)?
            .ok_or(Error::Protocol)?;
        for entry in entries {
            let entry = js_sys::Array::from(&entry.map_err(|_| Error::Protocol)?);
            let name = entry.get(0).as_string().ok_or(Error::Protocol)?;
            let value = entry.get(1).as_string().ok_or(Error::Protocol)?;
            // HttpOnly Cookie/Set-Cookie is never imported even on a faulty host.
            if name.eq_ignore_ascii_case("set-cookie") || name.eq_ignore_ascii_case("cookie") {
                return Err(Error::Forbidden);
            }
            response_headers.insert(
                reqwest::header::HeaderName::from_bytes(name.as_bytes())
                    .map_err(|_| Error::Protocol)?,
                reqwest::header::HeaderValue::from_str(&value).map_err(|_| Error::Protocol)?,
            );
        }
        let stream = raw
            .body()
            .map(|body| wasm_streams::ReadableStream::from_raw(body).into_stream());
        require_http_budget(crate::platform::time::Instant::now(), deadline, &|| {
            abort.0.abort()
        })?;
        Ok(Response {
            status,
            headers: response_headers,
            stream,
            _abort: abort,
            deadline,
        })
    }
}
impl Response {
    pub(crate) fn status(&self) -> StatusCode {
        self.status
    }
    pub(crate) fn headers(&self) -> &HeaderMap {
        &self.headers
    }
    pub(crate) fn content_length(&self) -> Option<u64> {
        self.headers
            .get("Content-Length")?
            .to_str()
            .ok()?
            .parse()
            .ok()
    }
    pub(crate) async fn chunk(&mut self) -> Result<Option<Vec<u8>>> {
        let deadline = self.deadline;
        let abort = &self._abort.0;
        require_http_budget(crate::platform::time::Instant::now(), deadline, &|| {
            abort.abort()
        })?;
        let Some(stream) = self.stream.as_mut() else {
            return Ok(None);
        };
        let next = within_http_budget(
            deadline,
            crate::platform::time::Instant::now,
            || abort.abort(),
            async {
                crate::platform::time::timeout_at(deadline, stream.next())
                    .await
                    .map_err(|_| Error::Offline)
            },
        )
        .await?;
        match next {
            None => Ok(None),
            Some(Ok(value)) if value.is_instance_of::<js_sys::Uint8Array>() => {
                let array = js_sys::Uint8Array::new(&value);
                // Bound before copying from JavaScript. Aggregate and protocol
                // limits remain checked by the same shared Client collectors.
                if array.length() > 16 * 1024 * 1024 {
                    return Err(Error::Protocol);
                }
                let bytes = array.to_vec();
                require_http_budget(crate::platform::time::Instant::now(), deadline, &|| {
                    abort.abort()
                })?;
                Ok(Some(bytes))
            }
            _ => Err(Error::Offline),
        }
    }
}
