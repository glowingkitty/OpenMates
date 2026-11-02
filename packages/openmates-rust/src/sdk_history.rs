//! Owner-scoped workspace change history. Entries contain opaque encrypted refs:
//! this facade never unwraps keys, decrypts snapshots or selects another owner.
use crate::{Client, Error, OpenMates, Result};
use reqwest::Method;
use serde_json::{Value, json};

/// Optional server filters. Omitted limit retains the server's default (50).
/// Signed integer limits are passed through, preserving server clamp semantics.
#[derive(Clone, Debug, Default)]
pub struct HistoryListOptions {
    pub object_type: Option<String>,
    pub object_id: Option<String>,
    pub limit: Option<i64>,
}

/// Request-local CLI compatibility evidence. Never contains a URL, body,
/// header or credential; source retains the ordinary typed SDK failure.
#[doc(hidden)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct HistoryRequestError {
    pub source: Error,
    pub http_status: Option<u16>,
}
impl From<Error> for HistoryRequestError {
    fn from(source: Error) -> Self {
        Self { source, http_status: None }
    }
}

enum Backend<'a> {
    ApiKey(&'a mut OpenMates),
    Cookie(&'a mut Client),
}
/// Global history for the explicitly supplied API-key or cookie-session client.
/// Team selection is not an ownership credential and is never added to this API.
pub struct History<'a> {
    backend: Backend<'a>,
}
impl Client {
    pub fn history(&mut self) -> History<'_> {
        History {
            backend: Backend::Cookie(self),
        }
    }
}
impl<'a> History<'a> {
    pub(crate) fn api_key(client: &'a mut OpenMates) -> Self {
        Self {
            backend: Backend::ApiKey(client),
        }
    }
    async fn request_observed(&mut self, method: Method, path: &str, body: Option<Value>)
        -> std::result::Result<Value, HistoryRequestError>
    {
        let mut http_status = None;
        let result = match &mut self.backend {
            Backend::ApiKey(client) => {
                client.verify_private_operation().map_err(HistoryRequestError::from)?;
                client.task_request_observed(method, path, body, false, None, Some(&mut http_status)).await
            }
            Backend::Cookie(client) => {
                client.verify_private_operation().map_err(HistoryRequestError::from)?;
                client.require_session().map_err(HistoryRequestError::from)?;
                client.request_task_headers_observed(method, path, body, None, None, None, &mut http_status).await
            }
        };
        result.map_err(|source| HistoryRequestError { source, http_status })
    }
    /// Return change-set rows unchanged, including metadata and extension fields.
    pub async fn list(&mut self, options: HistoryListOptions) -> Result<Vec<Value>> {
        self.list_for_cli(options, None).await.map_err(|error| error.source)
    }
    /// Preserve the installed CLI's Number-to-query coercion without changing
    /// the supported SDK integer option. Query values are always form encoded.
    #[doc(hidden)]
    pub async fn list_for_cli(&mut self, options: HistoryListOptions, limit_query: Option<&str>)
        -> std::result::Result<Vec<Value>, HistoryRequestError>
    {
        let path = match limit_query {
            Some(value) => list_path_with_limit(&options, Some(value)),
            None => list_path(&options),
        };
        let response = self.request_observed(Method::GET, &path, None).await?;
        list_rows(response).map_err(HistoryRequestError::from)
    }
    /// Return the full change set and opaque encrypted entry refs unchanged.
    pub async fn show(&mut self, change_set_id: &str) -> Result<Value> {
        self.show_for_cli(change_set_id).await.map_err(|error| error.source)
    }
    #[doc(hidden)]
    pub async fn show_for_cli(&mut self, change_set_id: &str)
        -> std::result::Result<Value, HistoryRequestError>
    {
        let path = format!("/v1/workspace/history/{}", path_segment(change_set_id)?);
        let response = self.request_observed(Method::GET, &path, None).await?;
        object_response(response).map_err(HistoryRequestError::from)
    }
    /// Ask the server to create a compensating change set. No replay/retry occurs:
    /// an ambiguous failure is returned to the caller, never resubmitted locally.
    pub async fn undo(&mut self, change_set_id: &str) -> Result<Value> {
        self.undo_for_cli(change_set_id).await.map_err(|error| error.source)
    }
    #[doc(hidden)]
    pub async fn undo_for_cli(&mut self, change_set_id: &str)
        -> std::result::Result<Value, HistoryRequestError>
    {
        let path = format!("/v1/workspace/history/{}/undo", path_segment(change_set_id)?);
        let response = self.request_observed(Method::POST, &path, Some(json!({}))).await?;
        object_response(response).map_err(HistoryRequestError::from)
    }
}

fn list_path(options: &HistoryListOptions) -> String {
    list_path_with_limit(options, None)
}
fn list_path_with_limit(options: &HistoryListOptions, limit_query: Option<&str>) -> String {
    let mut query = url::form_urlencoded::Serializer::new(String::new());
    if let Some(value) = options.object_type.as_deref().filter(|v| !v.is_empty()) {
        query.append_pair("object_type", value);
    }
    if let Some(value) = options.object_id.as_deref().filter(|v| !v.is_empty()) {
        query.append_pair("object_id", value);
    }
    if let Some(value) = limit_query {
        query.append_pair("limit", value);
    } else if let Some(value) = options.limit {
        query.append_pair("limit", &value.to_string());
    }
    let query = query.finish();
    format!(
        "/v1/workspace/history{}{}",
        if query.is_empty() { "" } else { "?" },
        query
    )
}
fn path_segment(id: &str) -> Result<String> {
    // No UUID assumption: canonical change-set IDs are chg_<hex>. Dot segments
    // must fail before URL normalization can reinterpret the owning endpoint.
    if id.is_empty() || matches!(id, "." | "..") || id.chars().any(char::is_control) {
        return Err(Error::Invalid("Supply a nonempty workspace change-set ID."));
    }
    let mut result = String::with_capacity(id.len());
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    for byte in id.bytes() {
        if byte.is_ascii_alphanumeric() || b"-._~".contains(&byte) {
            result.push(char::from(byte));
        } else {
            result.push('%');
            result.push(char::from(HEX[(byte >> 4) as usize]));
            result.push(char::from(HEX[(byte & 15) as usize]));
        }
    }
    Ok(result)
}
fn object_response(value: Value) -> Result<Value> {
    if value.is_object() {
        Ok(value)
    } else {
        Err(Error::Protocol)
    }
}
fn list_rows(response: Value) -> Result<Vec<Value>> {
    let response = object_response(response)?;
    match response.get("change_sets") {
        None | Some(Value::Null) => Ok(vec![]),
        Some(Value::Array(rows)) if rows.iter().all(Value::is_object) => Ok(rows.clone()),
        _ => Err(Error::Protocol),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ApiKey, ClientOptions, SdkCredentials, SdkOptions};
    #[test]
    fn default_query_and_server_owned_integer_limits() {
        assert_eq!(
            list_path(&HistoryListOptions::default()),
            "/v1/workspace/history"
        );
        for limit in [0, -2, 1000, i64::MAX] {
            assert_eq!(
                list_path(&HistoryListOptions {
                    limit: Some(limit),
                    ..Default::default()
                }),
                format!("/v1/workspace/history?limit={limit}")
            );
        }
        assert_eq!(
            list_path(&HistoryListOptions {
                object_type: Some("task".into()),
                object_id: Some("a /?#+%界".into()),
                limit: Some(5)
            }),
            "/v1/workspace/history?object_type=task&object_id=a+%2F%3F%23%2B%25%E7%95%8C&limit=5"
        );
    }
    #[test]
    fn ids_are_segments_not_form_fields_or_uuids() {
        assert_eq!(path_segment("chg_abc123").unwrap(), "chg_abc123");
        assert_eq!(
            path_segment("a /?#+%界").unwrap(),
            "a%20%2F%3F%23%2B%25%E7%95%8C"
        );
        for id in ["", ".", "..", "x\ny", "x\0y"] {
            assert!(path_segment(id).is_err());
        }
    }
    #[test]
    fn full_opaque_rows_and_unknown_fields_survive_without_key_access() {
        let row = json!({"change_set_id":"chg_1","hashed_user_id":"opaque-owner","unknown":{"CamelCase":[null,false,1]},"encrypted_before_ref":"opaque:not-decrypted"});
        assert_eq!(
            list_rows(json!({"change_sets":[row.clone()]})).unwrap(),
            vec![row.clone()]
        );
        assert_eq!(object_response(row.clone()).unwrap(), row);
        assert!(list_rows(json!({"change_sets":["invalid"]})).is_err());
        assert!(object_response(json!([])).is_err());
        assert!(list_rows(json!({"change_sets":{}})).is_err());
        assert_eq!(list_rows(json!({})).unwrap(), Vec::<Value>::new());
    }
    fn client(credentials: SdkCredentials) -> OpenMates {
        OpenMates::new(SdkOptions {
            api_url: "http://127.0.0.1:1".into(),
            credentials,
            device_id: "history-test-device".into(),
            client_options: ClientOptions::default(),
        })
        .unwrap()
    }
    #[tokio::test]
    async fn anonymous_invalid_and_cancelled_calls_fail_before_transport() {
        let mut anonymous = client(SdkCredentials::Anonymous {
            anonymous_id: "history-anonymous".into(),
        });
        assert_eq!(
            anonymous.history().list(Default::default()).await,
            Err(Error::Authentication)
        );
        let mut api = client(SdkCredentials::ApiKey(
            ApiKey::new("sk-api-historyfixture.localSetupSuffix").unwrap(),
        ));
        assert!(matches!(
            api.history().undo("..").await,
            Err(Error::Invalid(_))
        ));
        let cancel = tokio_util::sync::CancellationToken::new();
        cancel.cancel();
        api.set_operation_cancel(cancel);
        assert_eq!(
            api.history().list(Default::default()).await,
            Err(Error::Cancelled)
        );
    }
    #[test]
    fn legacy_numeric_queries_are_encoded_without_changing_typed_integer_options() {
        for (value, expected) in [
            ("1000000000000000100", "1000000000000000100"),
            ("1e+21", "1e%2B21"), ("1.5", "1.5"),
            ("Infinity", "Infinity"), ("-Infinity", "-Infinity"),
        ] {
            assert_eq!(list_path_with_limit(&HistoryListOptions::default(), Some(value)),
                format!("/v1/workspace/history?limit={expected}"));
        }
        assert_eq!(list_path_with_limit(&HistoryListOptions {
            object_type: Some("task\nplan".into()), object_id: Some("a\nb".into()), limit: None,
        }, None), "/v1/workspace/history?object_type=task%0Aplan&object_id=a%0Ab");
        assert_eq!(list_path(&HistoryListOptions { limit: Some(i64::MAX), ..Default::default() }),
            "/v1/workspace/history?limit=9223372036854775807");
    }
    // Local transport unit fixtures only; this code is not executed by the
    // private authoring workflow. No external API/account/inference is used.
    async fn history_peer(status: u16, body: &str) -> (String, tokio::task::JoinHandle<String>) {
        history_peer_declared(status, body, None).await
    }
    async fn history_peer_declared(status: u16, body: &str, declared: Option<usize>) -> (String, tokio::task::JoinHandle<String>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let body = body.to_owned();
        let peer = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut bytes = vec![];
            let mut buffer = [0u8; 1024];
            loop {
                let count = stream.read(&mut buffer).await.unwrap();
                assert!(count > 0);
                bytes.extend_from_slice(&buffer[..count]);
                if bytes.windows(4).any(|window| window == b"\r\n\r\n") { break; }
                assert!(bytes.len() < 16 * 1024);
            }
            let request = String::from_utf8(bytes).unwrap();
            stream.write_all(format!("HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", declared.unwrap_or(body.len())).as_bytes()).await.unwrap();
            request.lines().next().unwrap().to_owned()
        });
        (url, peer)
    }
    fn history_api(api_url: String) -> OpenMates {
        OpenMates::new(SdkOptions { api_url,
            credentials: SdkCredentials::ApiKey(ApiKey::new("sk-api-historyfixture.localSetupSuffix").unwrap()),
            device_id: "history-test-device".into(), client_options: ClientOptions::default(),
        }).unwrap()
    }
    fn history_cookie(api_url: &str) -> Client {
        let session = crate::Session {
            api_url: api_url.into(), session_id: "history-session".into(),
            cookies: [("auth_refresh_token".into(), "synthetic-cookie".into())].into(),
            ws_token: None, master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "synthetic".into(), user_email_salt: String::new(),
            email_encryption_key: None, created_at: 0, paired_session_expires_at: None, active_team_id: None,
        };
        Client::new(api_url, Some(session)).unwrap()
    }
    #[tokio::test]
    async fn parallel_history_failures_keep_request_local_status_and_never_return_private_bodies() {
        let (api_url, api_peer) = history_peer(404, r#"{"detail":"PRIVATE_BODY_MUST_NOT_ESCAPE"}"#).await;
        let (cookie_url, cookie_peer) = history_peer(409, r#"{"detail":"PRIVATE_BODY_MUST_NOT_ESCAPE"}"#).await;
        let mut api = history_api(api_url);
        let mut cookie = history_cookie(&cookie_url);
        let mut api_history = api.history();
        let mut cookie_history = cookie.history();
        let (api_result, cookie_result) = tokio::join!(api_history.show_for_cli("chg_missing"), cookie_history.undo_for_cli("chg_conflict"));
        let api_error = api_result.unwrap_err();
        let cookie_error = cookie_result.unwrap_err();
        assert_eq!(api_error.http_status, Some(404));
        assert_eq!(cookie_error.http_status, Some(409));
        assert_eq!(cookie_error.source, Error::Conflict);
        assert!(!format!("{api_error:?}{cookie_error:?}").contains("PRIVATE_BODY"));
        assert_eq!(api_peer.await.unwrap(), "GET /v1/workspace/history/chg_missing HTTP/1.1");
        assert_eq!(cookie_peer.await.unwrap(), "POST /v1/workspace/history/chg_conflict/undo HTTP/1.1");
        // No second transport exists. A local path denial/cancellation cannot
        // inherit either prior request's numeric status or retry its operation.
        let invalid = api.history().show_for_cli("..").await.unwrap_err();
        assert_eq!(invalid.http_status, None);
        let cancel = tokio_util::sync::CancellationToken::new(); cancel.cancel();
        api.set_operation_cancel(cancel);
        let cancelled = api.history().undo_for_cli("chg_conflict").await.unwrap_err();
        assert_eq!(cancelled, HistoryRequestError { source: Error::Cancelled, http_status: None });
    }
    #[tokio::test]
    async fn owner_expiry_and_closed_principal_denial_revoke_cookie_session_without_http_override() {
        for (status, body) in [(401, "{}"), (403, r#"{"detail":{"error":"session_principal_mismatch"}}"#)] {
            let (url, peer) = history_peer(status, body).await;
            let mut cookie = history_cookie(&url);
            let error = cookie.history().show_for_cli("chg_missing").await.unwrap_err();
            assert_eq!(error, HistoryRequestError { source: Error::Expired, http_status: Some(status) });
            assert!(cookie.session().is_none());
            assert_eq!(peer.await.unwrap(), "GET /v1/workspace/history/chg_missing HTTP/1.1");
        }
    }
    #[tokio::test]
    async fn typed_sdk_error_contract_and_fractional_query_use_same_single_guarded_request() {
        let (url, peer) = history_peer(422, r#"{"detail":"PRIVATE_BODY_MUST_NOT_ESCAPE"}"#).await;
        let mut api = history_api(url);
        let error = api.history().list_for_cli(Default::default(), Some("1.5")).await.unwrap_err();
        assert_eq!(error.http_status, Some(422));
        assert_eq!(error.source, Error::Invalid("The server rejected the requested operation."));
        assert_eq!(peer.await.unwrap(), "GET /v1/workspace/history?limit=1.5 HTTP/1.1");
        let (url, peer) = history_peer(404, "{}").await;
        let mut api = history_api(url);
        assert_eq!(api.history().show("chg_missing").await.unwrap_err(), Error::Invalid("The requested item is unavailable."));
        peer.await.unwrap();
    }

    #[tokio::test]
    async fn non_success_headers_survive_body_transport_failure_but_success_does_not_fake_http_denial() {
        for status in [200, 429, 503] {
            let (url, peer) = history_peer_declared(status, "{", Some(200)).await;
            let mut api = history_api(url);
            let error = api.history().show_for_cli("chg_missing").await.unwrap_err();
            assert_eq!(error.source, Error::Offline);
            assert_eq!(error.http_status, (status != 200).then_some(status));
            peer.await.unwrap();
            let (url, peer) = history_peer_declared(status, "{", Some(200)).await;
            let mut cookie = history_cookie(&url);
            let error = cookie.history().show_for_cli("chg_missing").await.unwrap_err();
            assert_eq!(error.source, Error::Offline);
            assert_eq!(error.http_status, (status != 200).then_some(status));
            peer.await.unwrap();
        }
    }
    #[tokio::test]
    async fn optional_transport_status_slot_resets_before_local_cancellation() {
        let cancel = tokio_util::sync::CancellationToken::new(); cancel.cancel();
        let mut api = history_api("http://127.0.0.1:1".into());
        api.set_operation_cancel(cancel.clone());
        let mut status = Some(503);
        assert_eq!(api.task_request_observed(Method::GET, "/v1/workspace/history", None, false, None, Some(&mut status)).await, Err(Error::Cancelled));
        assert_eq!(status, None);
        let mut cookie = history_cookie("http://127.0.0.1:1");
        cookie.set_operation_cancel(cancel);
        status = Some(429);
        assert_eq!(cookie.request_task_headers_observed(Method::GET, "/v1/workspace/history", None, None, None, None, &mut status).await, Err(Error::Cancelled));
        assert_eq!(status, None);
    }

}
