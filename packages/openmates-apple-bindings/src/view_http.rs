//! Authenticated HTTP passthrough on `ViewModelCore` for Swift features that
//! are not migrated yet (settings, embeds, projects ...): Swift hands over a
//! relative API request, the core performs it with its own session
//! (`Client::prepare_shell_http` / `finish_shell_http`: cookies, rotation,
//! 401 handling) and returns status, selected headers and body. The actor
//! lock is held only to prepare and to finish, not while on the network.
//! Temporary transport, no feature logic: plan `apple-client-core-migration`
//! step A6 deletes it with the last un-migrated Swift caller. Spec `client-core`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::{Shared, ViewModelCore};
use openmates_sdk::{
    client::{ShellHttpRequest, ShellHttpResponse},
    error::{Error, Result},
    view_model::ViewHost,
};
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

/// One name/value pair (query parameter or header).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct HttpFieldRecord {
    /// Name (headers: case-insensitive).
    pub name: String,
    /// Value.
    pub value: String,
}

/// A request relative to the configured API origin.
#[derive(Clone, PartialEq, Eq, uniffi::Record)]
pub struct HttpRequestRecord {
    /// `GET`, `POST`, `PUT`, `PATCH` or `DELETE`.
    pub method: String,
    /// API path starting with `/v1/`, without query; absolute URLs and other
    /// hosts are refused.
    pub path: String,
    /// Query parameters (encoded by the core), at most 64.
    pub query: Vec<HttpFieldRecord>,
    /// At most 16 of `Accept`, `Accept-Language`, `Cache-Control`,
    /// `Content-Type`, `Idempotency-Key`, `If-Match`, `If-None-Match`,
    /// `Pragma`. Cookies, origin and client headers are the core's.
    pub headers: Vec<HttpFieldRecord>,
    /// Body bytes (not for `GET`), at most 16 MiB; zeroized after sending.
    pub body: Option<Vec<u8>>,
}

/// The server's answer for any status the core does not own (it owns 401,
/// redirects and an expected-principal 403).
#[derive(Clone, PartialEq, Eq, uniffi::Record)]
pub struct HttpResponseRecord {
    /// HTTP status code; non-2xx statuses are returned, not thrown.
    pub status: u16,
    /// `Cache-Control`, `Content-Disposition`, `Content-Language`,
    /// `Content-Type`, `ETag`, `Last-Modified`, `Retry-After` (lower-case).
    pub headers: Vec<HttpFieldRecord>,
    /// Body bytes, at most 16 MiB.
    pub body: Vec<u8>,
}

impl Shared {
    async fn http_request(
        &self,
        request: ShellHttpRequest,
        cancel: CancellationToken,
    ) -> Result<ShellHttpResponse> {
        let prepared = {
            let mut host = self.host.lock().await;
            let host = host.as_mut().ok_or(Error::Authentication)?;
            host.core_mut().client_mut().prepare_shell_http(request)?
        };
        let sent = prepared.send(&cancel).await;
        let mut guard = self.host.lock().await;
        // Signed out meanwhile: the response belongs to no session any more.
        let host = guard.as_mut().ok_or(Error::Authentication)?;
        let finished = host.core_mut().client_mut().finish_shell_http(sent);
        let finished = match finished {
            // Rotated cookies are durable (Keychain acknowledged) before the
            // response is handed out, as after every core command.
            Ok(response) if response.credentials_changed => {
                host.core_mut().persist().await.map(|()| response)
            }
            other => other,
        };
        self.settle_auth(&mut guard, finished).await
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// Perform `request` with the core's session and return the response.
    /// Several requests may run at once; each waits for a running command
    /// (for example a send) only to prepare and to finish. A rotated cookie
    /// is stored through the Keychain before this returns. A 401 signs the
    /// profile out (wipe, `Session(Expired)` event). Not covered: uploads to
    /// the upload host, multipart helpers and streaming responses.
    ///
    /// # Errors
    /// `Authentication` while signed out (also when signed out during the
    /// request); `Expired` when the server rejected the session;
    /// `Invalid` for a malformed method, path, query, header or body;
    /// `Forbidden` for a core-owned auth route (`/v1/auth/session`, `login`,
    /// `logout`) or a redirect; `Offline` without a response; `Protocol` for
    /// an oversized response; `Cancelled` when `cancellation` fired or the
    /// session changed meanwhile; `Locked` when a rotated cookie could not be
    /// stored.
    pub async fn http_request(
        &self,
        request: HttpRequestRecord,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<HttpResponseRecord, CoreError> {
        let HttpRequestRecord {
            method,
            path,
            query,
            headers,
            body,
        } = request;
        let pairs = |fields: Vec<HttpFieldRecord>| -> Vec<(String, String)> {
            fields.into_iter().map(|f| (f.name, f.value)).collect()
        };
        let request = ShellHttpRequest {
            method,
            path,
            query: pairs(query),
            headers: pairs(headers),
            body: body.map(Zeroizing::new),
        };
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        let mut response = self
            .run(async move { shared.http_request(request, token).await })
            .await?;
        Ok(HttpResponseRecord {
            status: response.status,
            headers: std::mem::take(&mut response.headers)
                .into_iter()
                .map(|(name, value)| HttpFieldRecord { name, value })
                .collect(),
            // Swift owns the bytes from here; the core copy is zeroized.
            body: response.body.to_vec(),
        })
    }
}
