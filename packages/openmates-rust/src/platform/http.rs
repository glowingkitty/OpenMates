//! Thin HTTP execution adapter. Protocol/auth decisions remain in Client.
use crate::error::{Error, Result};

#[cfg(not(target_arch = "wasm32"))]
pub(crate) use reqwest::{Client, RequestBuilder};
#[cfg(not(target_arch = "wasm32"))]
pub(crate) type Response = reqwest::Response;
#[cfg(target_arch = "wasm32")]
#[path = "browser_http.rs"]
mod browser;
#[cfg(target_arch = "wasm32")]
pub(crate) use browser::{Client, RequestBuilder, Response};

pub(crate) fn client() -> Result<Client> {
    #[cfg(not(target_arch = "wasm32"))]
    {
        reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(std::time::Duration::from_secs(10))
            .timeout(std::time::Duration::from_secs(60))
            .user_agent("OpenMatesSDK/0.1 (Rust)")
            .build()
            .map_err(|_| Error::Offline)
    }
    #[cfg(target_arch = "wasm32")]
    {
        Ok(Client)
    }
}

pub(crate) fn browser_credentials(request: RequestBuilder, include: bool) -> RequestBuilder {
    #[cfg(not(target_arch = "wasm32"))]
    {
        let _ = include;
        request
    }
    #[cfg(target_arch = "wasm32")]
    {
        request.credentials(include)
    }
}
