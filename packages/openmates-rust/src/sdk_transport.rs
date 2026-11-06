//! Explicit API-key HTTP transport for the Rust SDK (npm `request/get/put/patch/delete`,
//! `getPublic`, `getRaw`, `webOrigin`). Requests reuse the exact credential,
//! origin, size and error policy of the other facades.
//! Credentials are never read from CLI state; anonymous callers get a typed error.
use crate::{Error, OpenMates, Result, sdk::SdkCredentials};
use reqwest::Method;
use serde_json::{Value, json};

const MAX_BODY: usize = 16 * 1024 * 1024;

/// Binary response from an authenticated GET (invoice PDFs, icon SVGs, exports).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RawResponse {
    pub content_type: String,
    pub filename: Option<String>,
    pub data: Vec<u8>,
}

/// npm `withQuery`: skips absent values, repeats keys for lists, keeps order.
pub fn with_query(path: &str, query: &[(&str, Option<String>)]) -> String {
    let mut params = url::form_urlencoded::Serializer::new(String::new());
    for (key, value) in query {
        if let Some(value) = value {
            params.append_pair(key, value);
        }
    }
    let serialized = params.finish();
    if serialized.is_empty() {
        path.to_owned()
    } else {
        format!("{path}?{serialized}")
    }
}

/// npm `extractFilename`: `filename*=UTF-8''` (percent-decoded) before `filename=`.
pub fn filename_from_disposition(header: &str) -> Option<String> {
    let encoded = regex::Regex::new(r"filename\*=UTF-8''([^;]+)").expect("static expression");
    if let Some(found) = encoded.captures(header).and_then(|c| c.get(1)) {
        let bytes = found.as_str().as_bytes();
        let mut out = Vec::with_capacity(bytes.len());
        let mut i = 0;
        while i < bytes.len() {
            if bytes[i] == b'%' {
                let hex = std::str::from_utf8(bytes.get(i + 1..i + 3)?).ok()?;
                out.push(u8::from_str_radix(hex, 16).ok()?);
                i += 3;
            } else {
                out.push(bytes[i]);
                i += 1;
            }
        }
        return String::from_utf8(out).ok();
    }
    let plain = regex::Regex::new(r#"filename="?([^";]+)"?"#).expect("static expression");
    plain
        .captures(header)
        .and_then(|c| c.get(1))
        .map(|m| m.as_str().to_owned())
}

impl OpenMates {
    fn require_api_key(&self) -> Result<()> {
        if self.is_anonymous() {
            Err(Error::Authentication)
        } else {
            Ok(())
        }
    }
    /// POST (the npm default for `request`) with the API-key bearer.
    pub async fn request_json(
        &self,
        method: Method,
        path: &str,
        body: Option<Value>,
    ) -> Result<Value> {
        self.require_api_key()?;
        self.task_request(method, path, body, false, None).await
    }
    pub async fn get(&self, path: &str) -> Result<Value> {
        self.request_json(Method::GET, path, None).await
    }
    pub async fn post(&self, path: &str, body: Value) -> Result<Value> {
        self.request_json(Method::POST, path, Some(body)).await
    }
    pub async fn put(&self, path: &str, body: Value) -> Result<Value> {
        self.request_json(Method::PUT, path, Some(body)).await
    }
    pub async fn patch(&self, path: &str, body: Value) -> Result<Value> {
        self.request_json(Method::PATCH, path, Some(body)).await
    }
    pub async fn delete(&self, path: &str) -> Result<Value> {
        self.request_json(Method::DELETE, path, None).await
    }
    /// Unauthenticated GET for public catalogue routes. No credential is attached.
    pub async fn get_public(&self, path: &str) -> Result<Value> {
        let (_, bytes) = self.send_raw(path, false).await?;
        if bytes.is_empty() {
            return Ok(json!({}));
        }
        Ok(serde_json::from_slice(&bytes)?)
    }
    /// Authenticated binary GET with content type and optional download filename.
    pub async fn get_raw(&self, path: &str) -> Result<RawResponse> {
        self.require_api_key()?;
        let (headers, data) = self.send_raw(path, true).await?;
        Ok(RawResponse {
            content_type: headers
                .0
                .unwrap_or_else(|| "application/octet-stream".into()),
            filename: headers.1.as_deref().and_then(filename_from_disposition),
            data,
        })
    }
    /// First-party web origin used for share and review links.
    pub fn web_origin(&self) -> &str {
        self.origin_str()
    }
    async fn send_raw(
        &self,
        path: &str,
        authenticated: bool,
    ) -> Result<((Option<String>, Option<String>), Vec<u8>)> {
        let mut response = self
            .get_request(path, authenticated)?
            .send()
            .await
            .map_err(|_| Error::Offline)?;
        let status = response.status();
        if status.is_redirection() {
            return Err(Error::Forbidden);
        }
        if !status.is_success() {
            return Err(match status.as_u16() {
                409 => Error::Conflict,
                400 | 422 => Error::Invalid("The server rejected the requested operation."),
                404 | 410 => Error::Invalid("The requested item is unavailable."),
                401 => Error::Authentication,
                403 => Error::Forbidden,
                429 | 500..=599 => Error::Offline,
                _ => Error::Protocol,
            });
        }
        if response
            .content_length()
            .is_some_and(|n| n > MAX_BODY as u64)
        {
            return Err(Error::Protocol);
        }
        let text = |name: &str| {
            response
                .headers()
                .get(name)
                .and_then(|v| v.to_str().ok())
                .map(str::to_owned)
        };
        let meta = (text("content-type"), text("content-disposition"));
        let mut bytes = vec![];
        while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
            if bytes.len() + chunk.len() > MAX_BODY {
                return Err(Error::Protocol);
            }
            bytes.extend_from_slice(&chunk);
        }
        Ok((meta, bytes))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ApiKey, ClientOptions, SdkOptions};
    use tokio_util::sync::CancellationToken;
    fn client(credentials: SdkCredentials) -> OpenMates {
        OpenMates::new(SdkOptions {
            api_url: "http://127.0.0.1:1".into(),
            credentials,
            device_id: "synthetic-transport-device".into(),
            client_options: ClientOptions::default(),
        })
        .unwrap()
    }
    #[test]
    fn query_matches_npm_with_query() {
        assert_eq!(with_query("/v1/x", &[("a", None), ("b", None)]), "/v1/x");
        assert_eq!(
            with_query(
                "/v1/x",
                &[("lang", Some("de".into())), ("q", Some("a b&c".into()))]
            ),
            "/v1/x?lang=de&q=a+b%26c"
        );
    }
    #[test]
    fn filename_extraction() {
        assert_eq!(
            filename_from_disposition("attachment; filename=\"inv.pdf\""),
            Some("inv.pdf".into())
        );
        assert_eq!(
            filename_from_disposition("attachment; filename=plain.csv; size=2"),
            Some("plain.csv".into())
        );
        assert_eq!(filename_from_disposition("inline"), None);
        assert_eq!(
            filename_from_disposition("attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf"),
            Some("r\u{e9}sum\u{e9}.pdf".into())
        );
    }
    #[tokio::test]
    async fn anonymous_and_cancelled_never_fall_back_and_paths_are_confined() {
        let anon = client(SdkCredentials::Anonymous {
            anonymous_id: "synthetic-transport-anon".into(),
        });
        assert_eq!(anon.get("/v1/sdk/x").await, Err(Error::Authentication));
        assert_eq!(anon.get_raw("/v1/sdk/x").await, Err(Error::Authentication));
        let mut api = client(SdkCredentials::ApiKey(
            ApiKey::new("sk-api-transportOwnerA.localSetupSuffix").unwrap(),
        ));
        assert_eq!(
            api.get("https://evil.example/v1/x").await,
            Err(Error::Forbidden)
        );
        assert_eq!(api.get_public("/v1/a//b").await, Err(Error::Forbidden));
        assert_eq!(api.web_origin(), "http://localhost:5173");
        let cancel = CancellationToken::new();
        cancel.cancel();
        api.set_operation_cancel(cancel);
        assert_eq!(api.put("/v1/sdk/x", json!({})).await, Err(Error::Cancelled));
        assert_eq!(api.get_raw("/v1/sdk/x").await, Err(Error::Cancelled));
    }
}
