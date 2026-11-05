//! Explicit API-key documentation facade matching the npm/Python SDK namespace.
//! The cookie/public client docs use /v1/docs and raw Markdown, a different API.
//! Reuse their slug safety policy and the existing SDK JSON/error/header transport.
use crate::{Error, OpenMates, Result};
use reqwest::Method;
use serde_json::Value;

pub struct Docs<'a> { client: &'a OpenMates }
impl<'a> Docs<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self { Self { client } }
    async fn get(&self, path: &str) -> Result<Value> {
        self.client.task_request(Method::GET, path, None, false, None).await
    }
    /// Preserve the complete server JSON envelope, including future fields.
    pub async fn list(&self) -> Result<Value> { self.get("/v1/sdk/docs").await }
    /// Server owns query semantics, including empty/whitespace search terms.
    pub async fn search(&self, query: &str) -> Result<Value> {
        let query = url::form_urlencoded::Serializer::new(String::new()).append_pair("q",query).finish();
        self.get(&format!("/v1/sdk/docs/search?{query}")).await
    }
    pub async fn show(&self, slug: &str) -> Result<Value> { self.get(&resource_path(slug,false)?).await }
    pub async fn download(&self, slug: &str) -> Result<Value> { self.get(&resource_path(slug,true)?).await }
}
fn resource_path(slug:&str, download:bool)->Result<String> {
    crate::client::validate_doc_slug(slug)?;
    let encoded=url::form_urlencoded::byte_serialize(slug.as_bytes()).collect::<String>().replace('+',"%20");
    Ok(format!("/v1/sdk/docs/{encoded}{}",if download {"/download"}else{""}))
}
#[cfg(test)]
mod tests {
 use super::*;
 use crate::{ApiKey,ClientOptions,SdkCredentials,SdkOptions};
 #[test] fn shared_slug_policy_and_single_segment_encoding() {
  assert_eq!(resource_path("guide/first page?#+%界",false).unwrap(),"/v1/sdk/docs/guide%2Ffirst%20page%3F%23%2B%25%E7%95%8C");
  assert_eq!(resource_path("guide/start",true).unwrap(),"/v1/sdk/docs/guide%2Fstart/download");
  for slug in ["","..","a/../b","/absolute","a//b","a\\b","x:y","a\n"] {assert!(matches!(resource_path(slug,false),Err(Error::Invalid(_))));}
 }
 fn client(credentials:SdkCredentials)->OpenMates {OpenMates::new(SdkOptions{api_url:"http://127.0.0.1:1".into(),credentials,device_id:"synthetic-docs-device".into(),client_options:ClientOptions::default()}).unwrap()}
 #[tokio::test] async fn anonymous_and_cancelled_never_start_public_or_session_fallback() {
  let anonymous=client(SdkCredentials::Anonymous{anonymous_id:"synthetic-docs-anon".into()});
  assert_eq!(anonymous.docs().list().await,Err(Error::Authentication));
  assert_eq!(anonymous.docs().show("guide/start").await,Err(Error::Authentication));
  let mut api=client(SdkCredentials::ApiKey(ApiKey::new("sk-api-docsOwnerA.localSetupSuffix").unwrap()));
  let cancel=tokio_util::sync::CancellationToken::new();cancel.cancel();api.set_operation_cancel(cancel);
  assert_eq!(api.docs().list().await,Err(Error::Cancelled));
  assert_eq!(api.docs().search("").await,Err(Error::Cancelled));
 }
}
