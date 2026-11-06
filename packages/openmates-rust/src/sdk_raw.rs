//! Authenticated raw GET for the explicit API-key SDK (invoice/credit-note PDFs and
//! usage exports). Child of `sdk` so it shares the private transport state; it
//! applies the same path, origin, bearer and size policy as `task_request`.
use super::*;
use crate::sdk_ops::{RawDownload, filename};

impl OpenMates {
    pub(crate) async fn raw_get(&self, path: &str) -> Result<RawDownload> {
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if !path.starts_with("/v1/") || path.contains(['\\', '#']) || path.contains("//") {
            return Err(Error::Forbidden);
        }
        let url = self.base.join(path).map_err(|_| Error::Protocol)?;
        if url.origin() != self.base.origin() {
            return Err(Error::Forbidden);
        }
        let SdkCredentials::ApiKey(key) = &self.credentials else {
            return Err(Error::Authentication);
        };
        let mut response = self
            .http
            .request(Method::GET, url)
            .header("X-OpenMates-SDK", self.options.identity.header())
            .header("X-OpenMates-Client-Capabilities", "agentic-storage-v2")
            .header("X-OpenMates-Device-Identity", &self.device_id)
            .header("Origin", &self.origin)
            .bearer_auth(key.bearer.as_str())
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
        let header = |name: &str| {
            response
                .headers()
                .get(name)
                .and_then(|v| v.to_str().ok())
                .map(str::to_owned)
        };
        let content_type =
            header("content-type").unwrap_or_else(|| "application/octet-stream".into());
        let filename = filename(header("content-disposition").as_deref());
        let mut data = vec![];
        while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
            if data.len() + chunk.len() > MAX_BODY {
                return Err(Error::Protocol);
            }
            data.extend_from_slice(&chunk);
        }
        Ok(RawDownload {
            content_type,
            filename,
            data,
        })
    }
}
