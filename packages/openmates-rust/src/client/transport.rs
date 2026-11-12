mod owned_recovery_socket;
pub(super) use owned_recovery_socket::{OwnedRecoverySocketPreparation,PreparedOwnedRecoverySocket,OwnedUnannouncedRecoverySocket,PreparedOwnedRecoveryLifecycle,OwnedConnectedRecoverySocket,connect_owned_completion_recovery_socket,connect_owned_completion_recovery_socket_with_negative,drive_owned_completion_recovery_lifecycle,drive_owned_completion_recovery_lifecycle_with_negative};
mod owned_read;
pub(super) mod cookie_observation;
mod owned_monitor_socket;
mod remote_command_stop;
pub(crate) mod local_connector;
mod monitor_error_frames;
pub(super) use monitor_error_frames::{MonitorFrame, receive_monitor_frame};
#[cfg(not(target_arch = "wasm32"))] pub(super) mod binary_stream;
pub(super) use owned_monitor_socket::{PreparedOwnedMonitorSocket,UnannouncedOwnedMonitorSocket,prepare_owned_passive_monitor_socket,connect_owned_passive_monitor_socket,announce_owned_passive_monitor_socket};
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
pub(super) use owned_monitor_socket::prepare_owned_saved_embed_socket;
pub(super) use owned_read::{ActualCookieTransition,OwnedReadByteBudget,OwnedReadByteHold,OwnedReadRoute,PreparedOwnedRead,OwnedReadHeaders,OwnedReadBody,CompletedOwnedRead,send_owned_read_headers,drive_owned_read_body,drive_owned_read_body_with_budget};
use super::*;
use futures_util::{SinkExt, StreamExt};
use reqwest::header::{COOKIE, SET_COOKIE};
use tungstenite::{self, client::IntoClientRequest, protocol::WebSocketConfig};

/// A read whose pre-send fences already ran; see [`Client::prepare_read`].
pub(super) struct PreparedRead {
    request: crate::platform::http::RequestBuilder,
    path: String,
    generation: u64,
    monitor_origin: Option<super::monitor::MonitorReadOrigin>,
    metadata_not_found: bool,
}
/// Response headers received; body and every post-send fence are pending.
pub(super) struct SentRead {
    response: Result<crate::platform::http::Response>,
    path: String,
    generation: u64,
    monitor_origin: Option<super::monitor::MonitorReadOrigin>,
    metadata_not_found: bool,
}
impl PreparedRead {
    pub(super) async fn send(self) -> SentRead {
        let Self { request, path, generation, monitor_origin, metadata_not_found } = self;
        SentRead {
            response: request.send().await.map_err(|_| Error::Offline),
            path,
            generation,
            monitor_origin,
            metadata_not_found,
        }
    }
}
pub(super) const USER_AGENT: &str = "OpenMatesSDK/0.1 (Rust)";
pub(super) const MAX_BODY: usize = 16 * 1024 * 1024;
// A finite protocol marker, never an arbitrary caller-visible error string.
fn project_request_pending(status:u16,bytes:&[u8])->bool{
    #[derive(serde::Deserialize)]
    enum Marker{#[serde(rename="request_not_found")]Pending}
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Pending{#[serde(rename="detail")]_detail:Marker}
    status==404&&serde_json::from_slice::<Pending>(bytes).is_ok()
}

pub(in crate::client) fn browser_auth_read_policy(method:&Method,route:&str)->(bool,bool){
    let admission=*method==Method::POST&&matches!(route,"/v1/auth/lookup"|"/v1/auth/password-v2/challenge"|"/v1/auth/login"|"/v1/auth/session");
    (admission,admission||(*method==Method::POST&&route=="/v1/chats/metadata/batch"))
}
pub(in crate::client) fn cache_namespace_unavailable(status:u16,route:&str)->bool{
    matches!(status,404|410)&&(route=="/v1/chats"||route.starts_with("/v1/chats/")||route=="/v1/teams"||route.starts_with("/v1/teams/"))
}
// Closed normal browser auth operation only; generic/old restore retain60s.
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
pub(super) const NORMAL_BROWSER_SESSION_TIMEOUT:Duration=Duration::from_secs(10);
#[derive(Clone,Copy)]
pub(in crate::client) enum SessionRequestBudget {
    #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
    NormalBrowserCheck{deadline:crate::platform::time::Instant},
}
pub(in crate::client) fn session_request_budget_at(request:crate::platform::http::RequestBuilder,budget:Option<SessionRequestBudget>,now:crate::platform::time::Instant)->Result<crate::platform::http::RequestBuilder>{
    let _=now; // No deadline-bearing variant exists outside the opt-in build.
    Ok(match budget{None=>request,Some(budget)=>match budget{
        #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
        SessionRequestBudget::NormalBrowserCheck{deadline}=>{
            let remaining=deadline.checked_duration_since(now).filter(|left|!left.is_zero()).ok_or(Error::Offline)?;
            request.timeout(remaining.min(NORMAL_BROWSER_SESSION_TIMEOUT))
        },
    }})
}
/// No implicit sensitivity inference: only explicit plaintext operations use
/// these owners. They do not change credentials, protocol or view admission.
struct PlaintextJson {
    value: Value,
    #[cfg(test)]
    drop_probe: Option<std::sync::Arc<std::sync::atomic::AtomicBool>>,
}
impl PlaintextJson {
    fn new(value: Value) -> Self {
        Self {
            value,
            #[cfg(test)]
            drop_probe: None,
        }
    }
}
impl Drop for PlaintextJson {
    fn drop(&mut self) {
        crate::model::zeroize_json(&mut self.value);
        #[cfg(test)]
        if let Some(probe) = &self.drop_probe {
            assert!(self.value.is_null());
            probe.store(true, std::sync::atomic::Ordering::SeqCst);
        }
    }
}
enum RequestBody {
    Ordinary(Value),
    Plaintext(PlaintextJson),
}
impl RequestBody {
    fn value(&self) -> &Value {
        match self {
            Self::Ordinary(value) => value,
            Self::Plaintext(value) => &value.value,
        }
    }
}
struct PlaintextBytes {
    bytes: zeroize::Zeroizing<Vec<u8>>,
    #[cfg(test)]
    drop_probe: Option<std::sync::Arc<std::sync::Mutex<Vec<u8>>>>,
}
impl PlaintextBytes {
    fn serialize(value: &impl serde::Serialize) -> Result<Self> {
        // Count without storing content, then serialize into a fixed-size slice.
        // A growing Vec would free old plaintext allocations on reallocation.
        struct Count(usize);
        impl std::io::Write for Count {
            fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
                self.0 = self.0.checked_add(bytes.len())
                    .ok_or_else(|| std::io::Error::other("JSON body size overflow"))?;
                Ok(bytes.len())
            }
            fn flush(&mut self) -> std::io::Result<()> { Ok(()) }
        }
        let mut count = Count(0);
        serde_json::to_writer(&mut count, value).map_err(|_| Error::Protocol)?;
        let result = Self {
            bytes: zeroize::Zeroizing::new(vec![0; count.0]),
            #[cfg(test)]
            drop_probe: None,
        };
        result.write(value)
    }
    fn write(mut self, value: &impl serde::Serialize) -> Result<Self> {
        let expected = self.bytes.len();
        let mut cursor = std::io::Cursor::new(self.bytes.as_mut_slice());
        serde_json::to_writer(&mut cursor, value).map_err(|_| Error::Protocol)?;
        if cursor.position() != expected as u64 { return Err(Error::Protocol); }
        Ok(self)
    }
    fn owned(self, source: PlaintextJson) -> tungstenite::Bytes {
        struct Owner {
            serialized: PlaintextBytes,
            _source: PlaintextJson,
        }
        impl AsRef<[u8]> for Owner {
            fn as_ref(&self) -> &[u8] { &self.serialized.bytes }
        }
        // bytes 1.12 keeps this owner until the LAST clone/body/frame drops.
        // reqwest 0.12 Body and tungstenite 0.28 Utf8Bytes retain these Bytes.
        tungstenite::Bytes::from_owner(Owner { serialized: self, _source: source })
    }
}
impl Drop for PlaintextBytes {
    fn drop(&mut self) {
        use zeroize::Zeroize;
        self.bytes.as_mut_slice().zeroize();
        #[cfg(test)]
        if let Some(probe) = &self.drop_probe {
            *probe.lock().expect("drop observer") = self.bytes.to_vec();
        }
        // Zeroizing<Vec> additionally wipes spare capacity before deallocation.
    }
}
fn plaintext_request(
    request: crate::platform::http::RequestBuilder,
    source: PlaintextJson,
) -> Result<crate::platform::http::RequestBuilder> {
    let serialized = PlaintextBytes::serialize(&source.value)?;
    Ok(request.header("Content-Type", "application/json").body(serialized.owned(source)))
}
#[derive(Clone, Copy, PartialEq, Eq)]
enum SocketSelectionPolicy {
    AnnounceActiveChat,
    Passive,
}
struct SocketResource {
    inner:tokio::sync::Mutex<crate::platform::socket::Stream>,
    pending:std::sync::Mutex<std::collections::VecDeque<(String,Value)>>,
    receiving:std::sync::atomic::AtomicBool,
}
impl Drop for SocketResource {
    fn drop(&mut self){
        use zeroize::Zeroize;
        let pending=self.pending.get_mut().unwrap_or_else(std::sync::PoisonError::into_inner);
        for(mut kind,mut payload)in pending.drain(..){kind.zeroize();crate::model::zeroize_json(&mut payload);}
    }
}
pub(super) struct Socket {
    resource:std::sync::Arc<SocketResource>,
    inventory_network: Option<std::sync::Arc<std::sync::atomic::AtomicU64>>,
}
/// One actual receive owner, including the original pending frame queue. Drop
/// after read/cancellation happens before any owned Client phase can be awaited.
struct SocketReceiveOwner {resource:std::sync::Arc<SocketResource>}
impl Drop for SocketReceiveOwner {
    fn drop(&mut self){self.resource.receiving.store(false,std::sync::atomic::Ordering::Release);}
}
impl Socket {
    fn new(inner:crate::platform::socket::Stream,inventory_network:Option<std::sync::Arc<std::sync::atomic::AtomicU64>>)->Self{
        Self{resource:std::sync::Arc::new(SocketResource{inner:tokio::sync::Mutex::new(inner),pending:Default::default(),receiving:false.into()}),inventory_network}
    }
    /// Private phase ownership of this SAME socket and queue, never reconnect,
    /// auth, role selection or a second receive grant. The typed driver must
    /// yield its receive before a Client phase can use this original handle.
    pub(super) fn original_phase_handle(&self)->Self{
        Self{resource:self.resource.clone(),inventory_network:self.inventory_network.clone()}
    }
    pub(super) fn same_original_socket(&self,other:&Self)->bool{std::sync::Arc::ptr_eq(&self.resource,&other.resource)}
    fn own_receive(&self)->Result<SocketReceiveOwner>{
        self.resource.receiving.compare_exchange(false,true,std::sync::atomic::Ordering::AcqRel,std::sync::atomic::Ordering::Acquire).map_err(|_|Error::Conflict)?;
        Ok(SocketReceiveOwner{resource:self.resource.clone()})
    }
    fn pop_pending(&self)->Result<Option<(String,Value)>>{Ok(self.resource.pending.lock().map_err(|_|Error::Protocol)?.pop_front())}
    pub(super) async fn close(
        &mut self,
        frame: Option<tungstenite::protocol::CloseFrame>,
    ) -> std::result::Result<(), tungstenite::Error> {
        self.resource.inner.lock().await.close(frame).await
    }
}
pub(crate) fn validate_base(raw: &str) -> Result<url::Url> {
    let mut base = url::Url::parse(raw).map_err(|_| Error::Invalid("Invalid API URL."))?;
    // Canonicalize the literal localhost label without resolving DNS. All
    // network connections still use a literal loopback address for plain HTTP.
    if base.scheme() == "http" && base.host_str() == Some("localhost") {
        base.set_host(Some("127.0.0.1"))
            .map_err(|_| Error::Invalid("Invalid API URL."))?;
    }
    let loopback = base.host_str().is_some_and(|h| {
        h.parse::<std::net::IpAddr>().is_ok_and(|a| a.is_loopback()) || h == "[::1]"
    });
    if !(base.scheme() == "https" || (base.scheme() == "http" && loopback))
        || base.host_str().is_none()
        || !base.username().is_empty()
        || base.password().is_some()
        || base.query().is_some()
        || base.fragment().is_some()
        || !matches!(base.path(), "" | "/")
    {
        return Err(Error::Invalid(
            "API URL must use HTTPS (HTTP is allowed only for literal loopback).",
        ));
    }
    base.set_path("");
    Ok(base)
}
/// Browser cookies/WebSocket authority is the exact URL host, not the native
/// DNS-free loopback transport alias. Reuse every native security check first;
/// only restore the one literal hostname that native validation canonicalizes.
#[cfg(any(target_arch = "wasm32", test))]
pub(crate) fn validate_browser_base(raw: &str) -> Result<url::Url> {
    let mut base = validate_base(raw)?;
    let original = url::Url::parse(raw).map_err(|_| Error::Invalid("Invalid API URL."))?;
    if original.scheme() == "http" && original.host_str() == Some("localhost") {
        base.set_host(Some("localhost"))
            .map_err(|_| Error::Invalid("Invalid API URL."))?;
    }
    Ok(base)
}
pub(crate) fn validate_app_origin(raw: &str) -> Result<url::Url> {
    let mut url =
        url::Url::parse(raw).map_err(|_| Error::Invalid("Invalid application origin."))?;
    let local = url.host_str().is_some_and(|host| {
        host == "localhost"
            || host == "[::1]"
            || host
                .parse::<std::net::IpAddr>()
                .is_ok_and(|ip| ip.is_loopback())
    });
    if !(url.scheme() == "https" || (url.scheme() == "http" && local))
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || !matches!(url.path(), "" | "/")
    {
        return Err(Error::Invalid(
            "Application origin must use HTTPS, or HTTP on loopback, without credentials or paths.",
        ));
    }
    url.set_path("");
    Ok(url)
}
pub(super) fn cookie_header(cookies: &BTreeMap<String, String>) -> Result<String> {
    if cookies.iter().any(|(k, v)| {
        k.is_empty()
            || !k
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
            || v.bytes()
                .any(|b| b <= 32 || b >= 127 || b == b';' || b == b',')
    }) {
        return Err(Error::Protocol);
    }
    Ok(cookies
        .iter()
        .map(|(k, v)| format!("{k}={v}"))
        .collect::<Vec<_>>()
        .join("; "))
}
impl Client {
    pub(super) fn url(&self, path: &str) -> Result<url::Url> {
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if let Some(original)=&self.browser_normal_data_native{
            // This unadmitted internal Client can perform ONLY the fixed normal
            // read; no metadata/network/private operation can be derived later.
            if path!="/v1/auth/session"{return Err(Error::Forbidden)}
            original.check_client(self)?;return original.route(path)
        }
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if let Some(original)=&self.browser_configured_native{original.check_client(self)?;return original.route(path)}
        if !path.starts_with('/')
            || path.starts_with("//")
            || path.contains('\\')
            || path.contains('#')
        {
            return Err(Error::Protocol);
        }
        let url = self.base.join(path).map_err(|_| Error::Protocol)?;
        if url.origin() != self.base.origin() {
            return Err(Error::Forbidden);
        }
        Ok(url)
    }
    pub(in crate::client) fn request_route_path(&self,url:&url::Url)->Result<String>{
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if let Some(original)=&self.browser_normal_data_native{
            original.check_client(self)?;let path=original.logical_path(url)?;
            if path!="/v1/auth/session"{return Err(Error::Forbidden)}return Ok(path)
        }
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if let Some(original)=&self.browser_configured_native{original.check_client(self)?;return original.logical_path(url)}
        Ok(url.path().into())
    }
    fn allows_local_browser_auth_path(&self,path:&str)->Result<bool>{
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if let Some(original)=&self.browser_configured_native{
            original.check_client(self)?;return Ok(matches!(path,"/v1/auth/session"|"/v1/auth/logout"))
        }
        Ok(matches!(self.url(path)?.path(),"/v1/auth/session"|"/v1/auth/logout"))
    }
    pub(in crate::client) fn browser_transport_api_identity(&self)->String{
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if let Some(original)=&self.browser_configured_native{return original.api().trim_end_matches('/').into()}
        self.base.as_str().trim_end_matches('/').into()
    }
    pub(crate) async fn request(
        &mut self,
        method: Method,
        path: &str,
        body: Option<Value>,
    ) -> Result<Value> {
        self.request_with(method, path, body, None).await
    }
    /// Explicit application-owned plaintext transport. Guard construction is
    /// synchronous so dropping an unpolled future also wipes the input Value.
    pub(super) fn request_plaintext<'a>(
        &'a mut self,
        method: Method,
        path: &'a str,
        body: Value,
    ) -> impl std::future::Future<Output = Result<Value>> + 'a {
        let body = RequestBody::Plaintext(PlaintextJson::new(body));
        async move {
            self.request_task_headers_inner(
                method, path, Some(body), None, None, None, None, false, None, None,
            )
            .await?
            .ok_or(Error::Protocol)
        }
    }
    pub(super) async fn request_with(
        &mut self,
        method: Method,
        path: &str,
        body: Option<Value>,
        pair_secret: Option<&str>,
    ) -> Result<Value> {
        self.request_headers(method, path, body, pair_secret, None)
            .await
    }
    pub(super) async fn request_headers(
        &mut self,
        method: Method,
        path: &str,
        body: Option<Value>,
        pair_secret: Option<&str>,
        idempotency: Option<&str>,
    ) -> Result<Value> {
        self.request_task_headers(method, path, body, pair_secret, idempotency, None)
            .await
    }
    pub(crate) async fn request_task_headers(
        &mut self,
        method: Method,
        path: &str,
        body: Option<Value>,
        pair_secret: Option<&str>,
        idempotency: Option<&str>,
        task: Option<&crate::work::TaskHeaders>,
    ) -> Result<Value> {
        self.request_task_headers_inner(
            method,
            path,
            body.map(RequestBody::Ordinary),
            pair_secret,
            idempotency,
            task,
            None,
            false,
            None,
            None,
        )
        .await?
        .ok_or(Error::Protocol)
    }
    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn request_task_headers_observed(
        &mut self,
        method: Method,
        path: &str,
        body: Option<Value>,
        pair_secret: Option<&str>,
        idempotency: Option<&str>,
        task: Option<&crate::work::TaskHeaders>,
        http_failure_status: &mut Option<u16>,
    ) -> Result<Value> {
        *http_failure_status = None;
        self.request_task_headers_inner(
            method,
            path,
            body.map(RequestBody::Ordinary),
            pair_secret,
            idempotency,
            task,
            None,
            false,
            Some(http_failure_status),
            None,
        )
        .await?
        .ok_or(Error::Protocol)
    }
    /// A closed authenticated result GET. Only the server's exact pending
    /// response becomes None; all other failures retain the generic mapping.
    pub(crate) async fn project_workflow_result(&mut self, project:&str, source:&str, request:&str, requester:&str, team:Option<&str>)->Result<Option<Value>> {
        self.require_session()?;self.verify_private_operation()?;
        for value in [project,request,requester]{crate::work::uuid(value)?;}
        if let Some(team)=team{crate::work::uuid(team)?;}
        if source.is_empty()||source.len()>128||source.chars().any(char::is_control)||matches!(source,"."|".."){return Err(Error::Invalid("Supply an exact Project source ID."));}
        let path=crate::work::path(&format!("/v1/projects/{project}/sources/{}/requests/{request}",segment(source)),team,&[("requesting_client_id".into(),requester.into())]);
        let value=self.request_task_headers_inner_mode_observed(Method::GET,&path,None,None,None,None,None,false,None,None,None,None,None,None,true).await;
        // Cancellation is observed after the actual original response terminal.
        if self.operation_cancel.is_cancelled(){return Err(Error::Cancelled);}
        self.verify_private_operation()?;value
    }
    /// Closed auth-session read observes every received header status. Existing
    /// request_task_headers_observed remains non-success-only for CLI parity.
    pub(super) async fn auth_session_request_observed(&mut self,body:Value,status:&mut Option<u16>)->Result<Value>{
        *status=None;
        self.request_task_headers_inner(Method::POST,"/v1/auth/session",Some(RequestBody::Ordinary(body)),None,None,None,None,false,None,Some(status)).await?.ok_or(Error::Protocol)
    }
    /// SAME fixed normal protocol/transport, closed original pending context.
    /// Actual request budget covers headers AND the complete streamed body.
    #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
    pub(super) async fn normal_browser_session_request_observed(&mut self,body:Value,status:&mut Option<u16>,deadline:crate::platform::time::Instant)->Result<Value>{
        if !self.browser_transport||self.browser_authority.is_some()||self.browser_credentials.is_some()||self.session.is_some()
            ||!self.user.is_null(){return Err(Error::Forbidden)}
        *status=None;
        self.request_task_headers_inner_mode(Method::POST,"/v1/auth/session",Some(RequestBody::Ordinary(body)),None,None,None,None,false,None,Some(status),None,None,None,Some(SessionRequestBudget::NormalBrowserCheck{deadline})).await?.ok_or(Error::Protocol)
    }
    // Only this fixed metadata read preserves exact HTTP 404 as absence. Other
    // status codes retain their ordinary errors and credential-rotation rules.
    pub(super) async fn request_chat_metadata(&mut self, id: &str) -> Result<Option<Value>> {
        uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
        self.require_credentials()?;
        let path = self.scoped("/v1/chats/metadata/batch")?;
        self.request_task_headers_inner(
            Method::POST,
            &path,
            Some(RequestBody::Ordinary(json!({"chat_ids":[id]}))),
            None,
            None,
            None,
            None,
            true,
            None,
            None,
        )
        .await
    }
    /// The server's stored unread counter for one chat (`read_details` of the
    /// selected metadata row); `None` when the row carries no counter.
    pub(super) async fn request_chat_unread_count(&mut self, id: &str) -> Result<Option<u64>> {
        uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
        self.require_credentials()?;
        let path = self.scoped("/v1/chats/metadata/batch")?;
        let metadata = self
            .request_task_headers_inner(
                Method::POST,
                &path,
                Some(RequestBody::Ordinary(json!({"chat_ids":[id],"include_read_details":true}))),
                None,
                None,
                None,
                None,
                true,
                None,
                None,
            )
            .await?
            .ok_or(Error::Forbidden)?;
        let rows = metadata["chats"].as_array().ok_or(Error::Protocol)?;
        let row = rows.iter().find(|row| text(row, "id") == id).ok_or(Error::Forbidden)?;
        Ok(row["read_details"]["unread_count"].as_u64())
    }
    /// A fixed Task readback completes an already committed ciphertext write.
    /// It grants no permission to dispatch another mutation after cancellation.
    pub(super) async fn request_committed_task(
        &mut self,
        id: &str,
        wrappers: bool,
    ) -> Result<Value> {
        uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
        self.require_credentials()?;
        let path = self.scoped(&format!(
            "/v1/user-tasks/{id}{}",
            if wrappers { "/key-wrappers" } else { "" }
        ))?;
        self.request_task_headers_inner(Method::GET, &path, None, None, None, None, Some(id), false, None, None)
            .await?
            .ok_or(Error::Protocol)
    }
    /// Fixed legacy settings/reminders compatibility only. Normal auth,
    /// header/cookie, denial and body-limit paths remain shared and strict.
    pub(crate) async fn request_settings_reminders(&mut self, http_error: &mut Option<u16>) -> Result<crate::account::SettingsReadResponse> {
        *http_error = None;
        let mut root_keys = zeroize::Zeroizing::new(Vec::new());
        let value = self.request_task_headers_inner_mode(Method::GET, "/v1/settings/reminders", None,
            None, None, None, None, false, None, None, Some(http_error), Some(&mut root_keys), None,None)
            .await?.ok_or(Error::Protocol)?;
        Ok(crate::account::SettingsReadResponse::from_parts(value, root_keys))
    }
    #[allow(clippy::too_many_arguments)]
    async fn request_task_headers_inner(
        &mut self, method: Method, path: &str, body: Option<RequestBody>,
        pair_secret: Option<&str>, idempotency: Option<&str>,
        task: Option<&crate::work::TaskHeaders>, committed_task: Option<&str>,
        metadata_not_found: bool, http_failure_status: Option<&mut Option<u16>>,
        auth_response_status: Option<&mut Option<u16>>,
    ) -> Result<Option<Value>> {
        self.request_task_headers_inner_mode(method, path, body, pair_secret,
            idempotency, task, committed_task, metadata_not_found,
            http_failure_status, auth_response_status, None, None, None,None).await
    }
    /// Closed bounded version read: only a real 404, or version-one's exact
    /// snapshot_required 409, is absence. Generic request semantics are unchanged.
    pub(super) async fn request_embed_history(
        &mut self, embed: &str, chat: &str, version: u64,
    ) -> Result<Option<Value>> {
        if version == 0 { return Err(Error::Protocol); }
        self.require_credentials()?;
        let path = self.scoped(&format!(
            "/v1/embeds/{}/versions/{version}?capability=bounded-v1&chat_id={}",
            segment(embed), segment(chat),
        ))?;
        self.request_task_headers_inner_mode(Method::GET, &path, None, None,
            None, None, None, false, None, None, None, None, Some(version),None).await
    }
    #[allow(clippy::too_many_arguments)]
    async fn request_task_headers_inner_mode(
        &mut self,
        method: Method,
        path: &str,
        body: Option<RequestBody>,
        pair_secret: Option<&str>,
        idempotency: Option<&str>,
        task: Option<&crate::work::TaskHeaders>,
        committed_task: Option<&str>,
        metadata_not_found: bool,
        http_failure_status: Option<&mut Option<u16>>,
        auth_response_status: Option<&mut Option<u16>>,
        settings_http_error: Option<&mut Option<u16>>,
        settings_root_keys: Option<&mut zeroize::Zeroizing<Vec<String>>>,
        history_version: Option<u64>,
        session_budget:Option<SessionRequestBudget>,
    ) -> Result<Option<Value>> {
        self.request_task_headers_inner_mode_observed(method,path,body,pair_secret,idempotency,task,committed_task,metadata_not_found,http_failure_status,auth_response_status,settings_http_error,settings_root_keys,history_version,session_budget,false).await
    }
    #[allow(clippy::too_many_arguments)]
    async fn request_task_headers_inner_mode_observed(
        &mut self,
        method: Method,
        path: &str,
        body: Option<RequestBody>,
        pair_secret: Option<&str>,
        idempotency: Option<&str>,
        task: Option<&crate::work::TaskHeaders>,
        committed_task: Option<&str>,
        metadata_not_found: bool,
        http_failure_status: Option<&mut Option<u16>>,
        auth_response_status: Option<&mut Option<u16>>,
        settings_http_error: Option<&mut Option<u16>>,
        settings_root_keys: Option<&mut zeroize::Zeroizing<Vec<String>>>,
        history_version: Option<u64>,
        session_budget:Option<SessionRequestBudget>,
        project_result_pending:bool,
    ) -> Result<Option<Value>> {
        if session_budget.is_some()&&(method!=Method::POST||path!="/v1/auth/session"||body.is_none()
            ||pair_secret.is_some()||idempotency.is_some()||task.is_some()||committed_task.is_some()
            ||metadata_not_found||http_failure_status.is_some()||auth_response_status.is_none()
            ||settings_http_error.is_some()||settings_root_keys.is_some()||history_version.is_some()
            ||!self.browser_transport||self.browser_authority.is_some()||self.browser_credentials.is_some()||self.session.is_some()||!self.user.is_null()){
            return Err(Error::Forbidden)
        }
        self.in_flight_method = Some(method.as_str().to_owned());
        let settings_reminders = settings_http_error.is_some();
        if settings_reminders != settings_root_keys.is_some() { return Err(Error::Protocol); }
        if settings_reminders && (method != Method::GET || path != "/v1/settings/reminders" || body.is_some()
            || pair_secret.is_some() || idempotency.is_some() || task.is_some() || committed_task.is_some()
            || metadata_not_found || http_failure_status.is_some() || auth_response_status.is_some() || history_version.is_some()) {
            return Err(Error::Protocol);
        }
        let (req, generation, monitor_origin) = self.prepare_http_request(
            method, path, body, pair_secret, idempotency, task, committed_task,
        )?;
        let response = session_request_budget_at(req,session_budget,crate::platform::time::Instant::now())?.send().await.map_err(|_| Error::Offline);
        self.finish_http_response(path, response, generation, monitor_origin, metadata_not_found,
            http_failure_status, auth_response_status, settings_http_error, settings_root_keys,
            history_version, project_result_pending).await
    }
    fn is_metadata_batch_read(&self, path: &str) -> bool {
        self.url(path)
            .and_then(|url| self.request_route_path(&url))
            .is_ok_and(|route| route == "/v1/chats/metadata/batch")
    }
    /// Concurrent ordinary reads. Prepare runs every pre-send fence in call
    /// order with the current credentials; the caller may then await several
    /// [`PreparedRead::send`] futures together (no Client borrow), and MUST
    /// finish them in the same order through [`Client::finish_read`] so that
    /// status, credential-rotation, owner and generation fences still apply
    /// sequentially. Only plain cookie-authenticated GET/metadata reads.
    pub(super) fn prepare_read(
        &mut self,
        method: Method,
        path: &str,
        body: Option<Value>,
        metadata_not_found: bool,
    ) -> Result<PreparedRead> {
        if !(method == Method::GET && body.is_none()
            || method == Method::POST && body.is_some() && self.is_metadata_batch_read(path))
        {
            return Err(Error::Protocol);
        }
        let (request, generation, monitor_origin) = self.prepare_http_request(
            method, path, body.map(RequestBody::Ordinary), None, None, None, None,
        )?;
        Ok(PreparedRead {
            request,
            path: path.to_owned(),
            generation,
            monitor_origin,
            metadata_not_found,
        })
    }
    pub(super) async fn finish_read(&mut self, sent: SentRead) -> Result<Option<Value>> {
        let SentRead { response, path, generation, monitor_origin, metadata_not_found } = sent;
        self.finish_http_response(&path, response, generation, monitor_origin, metadata_not_found,
            None, None, None, None, None, false).await
    }
    /// Pre-send half of the ordinary transport: identical fences, freshness
    /// invalidation and credential/header construction. Sending needs no Client.
    #[allow(clippy::too_many_arguments)]
    fn prepare_http_request(
        &mut self,
        method: Method,
        path: &str,
        body: Option<RequestBody>,
        pair_secret: Option<&str>,
        idempotency: Option<&str>,
        task: Option<&crate::work::TaskHeaders>,
        committed_task: Option<&str>,
    ) -> Result<(crate::platform::http::RequestBuilder, u64, Option<super::monitor::MonitorReadOrigin>)> {
        // Any later transport operation makes a prior inventory proof stale,
        // including failed writes whose server outcome may be uncertain.
        self.check_browser_credential_deadline()?;
        if self.browser_local_read_only && !self.allows_local_browser_auth_path(path)? {
            return Err(Error::Unavailable{code:"browser_offline_read_only",reason:"LOCAL_PROFILE_DOES_NOT_GRANT_SERVER_OR_STREAM_AUTHORITY"});
        }
        self.invalidate_chat_inventory_proofs();
        // Session admission rotates credentials without changing canonical cache freshness.
        // The fixed metadata batch is a server read (no effects). Any ciphertext
        // it later stores remains bound by the list-input digest, and 403 or
        // redirect responses still revoke freshness below.
        if method != Method::GET
            && !(method == Method::POST
                && (path == "/v1/auth/session" || self.is_metadata_batch_read(path)))
        {
            self.chat_list_freshness.invalidate();
        }
        // Expected owner is a restricting assertion, never authentication. The
        // old server may ignore it: browser mutable effects require positive
        // support observed on the current fresh session response first.
        let request_path=self.request_route_path(&self.url(path)?)?;
        let(auth_admission,auth_read)=browser_auth_read_policy(&method,&request_path);
        if self.browser_cookies()&&self.browser_authority.is_none()&&!auth_admission{return Err(Error::Unavailable{code:"browser_owner_consistency_unsupported",reason:"BROWSER_OWNER_CONSISTENCY_REQUIRES_SERVER_CAPABILITIES"});}
        if !matches!(method,Method::GET|Method::HEAD|Method::OPTIONS)&&!auth_read {self.require_browser_owner_guards()?;}
        // These requests complete an already admitted operation or revoke its
        // credentials. Ordinary cancelled operations cannot admit new writes.
        let completion = method == Method::POST
            && matches!(path, "/v1/apps/workspace/results" | "/v1/auth/logout");
        let pair_rollback = method == Method::DELETE
            && path.starts_with("/v1/auth/pair/v2/")
            && pair_secret.is_some();
        let committed_read = committed_task.is_some_and(|id| {
            method == Method::GET
                && body.is_none()
                && self.url(path).and_then(|url|self.request_route_path(&url)).is_ok_and(|path| {
                    path == format!("/v1/user-tasks/{id}")
                        || path == format!("/v1/user-tasks/{id}/key-wrappers")
                })
        });
        if self.operation_cancel.is_cancelled() && !completion && !pair_rollback && !committed_read
        {
            return Err(Error::Cancelled);
        }
        let generation = self.generation;
        let monitor_origin = self.monitor_read_origin(&method, path, body.as_ref().map(RequestBody::value));
        let req = self
            .http
            .request(method, self.url(path)?)
            .header("X-OpenMates-SDK", self.options.identity.header())
            .header("Origin", self.app_url())
            .header("Accept", "application/json");
        let mut req = crate::platform::http::browser_credentials(req, self.browser_cookies());
        // This fixed admission proof must bypass the browser HTTP cache.
        #[cfg(target_arch = "wasm32")]
        if path == "/v1/auth/pair/v2/account-check" {
            req = req.fetch_cache_no_store();
        }
        if let Some(expected)=self.expected_request_principal()? {
            req=req.header("X-OpenMates-Expected-Principal",expected);
        }
        let cookies = zeroize::Zeroizing::new(cookie_header(&self.cookies)?);
        if !cookies.is_empty() {
            req = req.header(COOKIE, cookies.as_str())
        }
        if let Some(task) = task {
            for (name, value) in task.headers()? {
                req = req.header(name, value);
            }
        }
        if let Some(id) = idempotency {
            req = req.header("Idempotency-Key", id)
        }
        if let Some(secret) = pair_secret {
            req = req.header("X-OpenMates-Pair-Receiver", secret)
        }
        if let Some(body) = body {
            req = match body {
                RequestBody::Ordinary(value) => req.json(&value),
                RequestBody::Plaintext(value) => plaintext_request(req, value)?,
            };
        }
        Ok((req, generation, monitor_origin))
    }
    /// Post-send half: the unchanged status, credential-rotation, owner,
    /// body-limit and generation fences, applied in the caller's order.
    #[allow(clippy::too_many_arguments)]
    async fn finish_http_response(
        &mut self,
        path: &str,
        response: Result<crate::platform::http::Response>,
        generation: u64,
        monitor_origin: Option<super::monitor::MonitorReadOrigin>,
        metadata_not_found: bool,
        http_failure_status: Option<&mut Option<u16>>,
        auth_response_status: Option<&mut Option<u16>>,
        mut settings_http_error: Option<&mut Option<u16>>,
        mut settings_root_keys: Option<&mut zeroize::Zeroizing<Vec<String>>>,
        history_version: Option<u64>,
        project_result_pending: bool,
    ) -> Result<Option<Value>> {
        let settings_reminders = settings_root_keys.is_some();
        let mut response = response?;
        let status = response.status();
        if !status.is_success() && let Some(method) = self.in_flight_method.take() {
            self.last_http_failure = Some(HttpFailure { method, status: status.as_u16() });
        }
        if let Some(slot)=auth_response_status{*slot=Some(status.as_u16());}
        // Numeric response evidence is local to this request. Capture before
        // body reads so an HTTP denial cannot look like a no-response outage.
        // Typed expiry/cancel/owner/body guards below remain authoritative.
        if !status.is_success() && let Some(slot) = http_failure_status {
            *slot = Some(status.as_u16());
        }
        // A protected access denial invalidates cached freshness even when a
        // read did not change ciphertext. Preserve the existing error/session
        // semantics; an unrelated public 404 is not an auth failure.
        let cache_namespace_unavailable = self.url(path).and_then(|url|self.request_route_path(&url))
            .is_ok_and(|path|cache_namespace_unavailable(status.as_u16(),&path));
        if status.as_u16() == 403 { super::send::refusal_trace::note_http(403, path); }
        if status.as_u16() == 403 || cache_namespace_unavailable || status.is_redirection() {
            self.chat_list_freshness.invalidate();
        }
        if status.as_u16() == 401 && !path.starts_with("/v1/auth/login") {
            self.note_monitor_http_denial(401, monitor_origin)?;
            if let Some(slot) = settings_http_error.as_mut() { **slot = Some(401); }
            self.forget_session();
            return Err(Error::Expired);
        }
        let monitor_access_denied =
            status.as_u16() == 403 && self.note_monitor_http_denial(403, monitor_origin)?;
        if status.is_redirection() {
            return Err(Error::Forbidden);
        }
        self.apply_owned_response_cookies(response.headers(),generation)?;
        if status.as_u16()==403&&response.content_length().is_some_and(|n|n>4096){return Err(Error::Forbidden);}
        if response
            .content_length()
            .is_some_and(|n| n > MAX_BODY as u64)
        {
            return Err(Error::Protocol);
        }
        let mut bytes = zeroize::Zeroizing::new(Vec::new());
        while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
            if status.as_u16()==403&&bytes.len()+chunk.len()>4096{return Err(Error::Forbidden);}
            if bytes.len() + chunk.len() > MAX_BODY {
                return Err(Error::Protocol);
            }
            bytes.extend_from_slice(&chunk);
        }
        if self.generation != generation {
            return Err(Error::Cancelled);
        }
        // Closed-set link code only (P11); no raw body escapes the transport.
        self.project_item_error =
            super::project_item_error::classify(path, status.as_u16(), &bytes);
        self.embed_user_revision_refusal =
            super::embed_user_revision::refusal::classify(path, status.as_u16(), &bytes);
        self.image_enhance_refusal =
            super::image_enhance::refusal::classify(path, status.as_u16(), &bytes);
        if status.as_u16()==403&&super::browser::expected_principal_mismatch(&bytes){
            // This closed server denial revokes the entire current owner, not
            // merely one object ACL. Drop/zeroize credentials, cancel pending
            // operation/watch authority and invalidate all cached publication.
            self.forget_session();
            return Err(Error::Expired);
        }
        if monitor_access_denied {return Err(Error::Forbidden);}
        if metadata_not_found && status.as_u16() == 404 {
            return Ok(None);
        }
        // Classification is after the unchanged owner, cookie, body-limit and
        // generation fences. The borrowed diagnostic never escapes this read.
        if history_version.is_some() && status.as_u16() == 404 {
            return Ok(None);
        }
        if history_version == Some(1) && status.as_u16() == 409 {
            #[derive(serde::Deserialize)]
            struct MissingSnapshot<'a> { detail: &'a str }
            if serde_json::from_slice::<MissingSnapshot<'_>>(&bytes)
                .is_ok_and(|body| body.detail == "snapshot_required") {
                return Ok(None);
            }
        }
        // Closed original Project result GET only. No raw error body escapes,
        // and every existing caller passes false through the unchanged wrapper.
        if project_result_pending && project_request_pending(status.as_u16(), &bytes) {
            return Ok(None);
        }
        if !status.is_success() {
            if let Some(slot) = settings_http_error.as_mut() { **slot = Some(status.as_u16()); }
            return Err(match status.as_u16() {
                401 => Error::Expired,
                403 => Error::Forbidden,
                409 => Error::Conflict,
                400 | 422 => Error::Invalid("The server rejected the requested operation."),
                404 | 410 => Error::Invalid("The requested item is unavailable."),
                429 | 500..=599 => Error::Offline,
                _ => Error::Protocol,
            });
        }
        if bytes.is_empty() {
            Ok(Some(json!({})))
        } else if settings_reminders {
            // Legacy HttpClient JSON decoding defaults to {}. This fixed read
            // reaches here only AFTER all original auth/cookie/body/owner checks.
            let root_slot = settings_root_keys.as_mut().ok_or(Error::Protocol)?;
            let decoded = crate::account::SettingsReadResponse::decode_legacy(&bytes)?;
            let (value, keys) = decoded.into_parts();
            **root_slot = keys;
            Ok(Some(value))
        } else {
            serde_json::from_slice(&bytes)
                .map(Some)
                .map_err(|_| Error::Protocol)
        }
    }
    pub(crate) async fn public_workflow_projection(&self, template: &str) -> Result<Value> {
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let url = self.url(&format!(
            "/v1/workflows/template-projections/{}",
            segment(template)
        ))?;
        // A public projection read never attaches account credentials or rotates them.
        let mut response = self
            .http
            .get(url)
            .header("Accept", "application/json")
            .send()
            .await
            .map_err(|_| Error::Offline)?;
        if response.status().is_redirection() {
            return Err(Error::Forbidden);
        }
        if !response.status().is_success() {
            return Err(match response.status().as_u16() {
                404 | 410 => Error::Invalid("The requested template is unavailable."),
                429 | 500..=599 => Error::Offline,
                _ => Error::Forbidden,
            });
        }
        if response.content_length().is_some_and(|n| n > 1_048_576) {
            return Err(Error::Protocol);
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
            if bytes.len() + chunk.len() > 1_048_576 {
                return Err(Error::Protocol);
            }
            bytes.extend_from_slice(&chunk);
        }
        serde_json::from_slice(&bytes).map_err(|_| Error::Protocol)
    }
    pub(super) async fn workflow_run(&mut self, path: &str, id: &str) -> Result<Value> {
        self.request_headers(
            Method::POST,
            path,
            Some(json!({"mode":"manual","input":{}})),
            None,
            Some(id),
        )
        .await
    }
    pub(crate) fn app_url(&self) -> String {
        if let Some(app) = &self.options.app_url {
            return app.trim_end_matches('/').to_owned();
        }
        // Canonical local installations serve the application on 5173 even
        // when the API transport deliberately uses a literal loopback address.
        if self.base.host_str().is_some_and(|host| {
            host == "localhost"
                || host == "[::1]"
                || host
                    .parse::<std::net::IpAddr>()
                    .is_ok_and(|ip| ip.is_loopback())
        }) {
            return "http://localhost:5173".into();
        }
        let mut url = self.base.clone();
        if let Some(host) = url.host_str().map(str::to_owned)
            && let Some(rest) = host.strip_prefix("api.")
        {
            let _ = url.set_host(Some(&format!("app.{rest}")));
        }
        url.to_string().trim_end_matches('/').to_owned()
    }
    pub(super) async fn socket(&mut self) -> Result<Socket> {
        self.socket_with_task_jobs(true).await
    }
    pub(super) async fn socket_with_task_jobs(&mut self, task_jobs: bool) -> Result<Socket> {
        self.socket_mode(
            task_jobs,
            false,
            false,
            SocketSelectionPolicy::AnnounceActiveChat,
        )
        .await
    }
    pub(super) async fn ephemeral_socket(&mut self) -> Result<Socket> {
        self.socket_mode(
            false,
            true,
            false,
            SocketSelectionPolicy::AnnounceActiveChat,
        )
        .await
    }
    pub(super) async fn completion_recovery_socket(&mut self) -> Result<Socket> {
        if self
            .completion_recovery_mode
            .as_ref()
            .is_none_or(CancellationToken::is_cancelled)
        {
            return Err(Error::Unavailable {
                code: "completion_recovery_unavailable",
                reason: "COMPLETION_RECOVERY_REQUIRES_EXPLICIT_FOREGROUND",
            });
        }
        self.socket_mode(
            false,
            false,
            true,
            SocketSelectionPolicy::AnnounceActiveChat,
        )
        .await
    }
    pub(super) async fn completion_recovery_inventory_socket(
        &mut self,
        request_id: &str,
    ) -> Result<Socket> {
        if self
            .completion_recovery_mode
            .as_ref()
            .is_none_or(CancellationToken::is_cancelled)
        {
            return Err(Error::Unavailable {
                code: "completion_recovery_unavailable",
                reason: "COMPLETION_RECOVERY_REQUIRES_EXPLICIT_FOREGROUND",
            });
        }
        self.socket_mode_with_inventory_request(
            true,
            false,
            true,
            SocketSelectionPolicy::AnnounceActiveChat,
            Some(request_id),
        )
        .await
    }
    // Both the keyless monitor and its fresh ciphertext snapshot are passive:
    // no job capabilities and no durable active-chat announcement.
    pub(super) async fn passive_chat_monitor_socket(&mut self) -> Result<Socket> {
        self.socket_mode(false, false, false, SocketSelectionPolicy::Passive)
            .await
    }
    async fn socket_mode(
        &mut self,
        task_jobs: bool,
        ephemeral: bool,
        completion_recovery: bool,
        selection: SocketSelectionPolicy,
    ) -> Result<Socket> {
        self.socket_mode_with_inventory_request(
            task_jobs,
            ephemeral,
            completion_recovery,
            selection,
            None,
        )
        .await
    }
    fn prepare_socket_connection(&self,task_jobs:bool,ephemeral:bool,completion_recovery:bool,
        selection:SocketSelectionPolicy,inventory_request_id:Option<&str>)->Result<PreparedSocketConnection>{
        self.require_browser_owner_guards()?;
        let session = self.require_credentials()?;
        let mut url = self.url("/v1/ws")?;
        url.set_scheme(if self.base.scheme() == "https" {
            "wss"
        } else {
            "ws"
        })
        .map_err(|_| Error::Protocol)?;
        let mut capabilities = if ephemeral {
            String::new()
        } else if task_jobs {
            "canonical_embed_receipts_v1,typed_recovery_outputs_v2,agentic-storage-v2,task_update_jobs".into()
        } else {
            "canonical_embed_receipts_v1,typed_recovery_outputs_v2,agentic-storage-v2".into()
        };
        if !ephemeral {
            for extra in &self.extra_socket_capabilities {
                capabilities.push(',');
                capabilities.push_str(extra);
            }
            // architecture.sync@2: cold-start cursor, overview and delta feed.
            capabilities.push(',');
            capabilities.push_str(super::sync_feed::CAPABILITY);
        }
        if completion_recovery {
            capabilities.push_str(",chat_metadata_recovery");
            if task_jobs {
                capabilities.push_str(",task_update_jobs_inventory_v1");
            }
        }
        if let Some(request_id) = inventory_request_id {
            let parsed = uuid::Uuid::parse_str(request_id).map_err(|_| Error::Protocol)?;
            if !task_jobs
                || !completion_recovery
                || parsed.get_version_num() != 4
                || parsed.to_string() != request_id
            {
                return Err(Error::Protocol);
            }
            url.query_pairs_mut()
                .append_pair("inventory_request_id", request_id);
        }
        url.query_pairs_mut()
            .append_pair("client_capabilities", &capabilities)
            .append_pair("sessionId", &uuid::Uuid::new_v4().to_string())
            .append_pair(
                "token",
                session.ws_token.as_deref().ok_or(Error::Authentication)?,
            );
        let mut req = url
            .as_str()
            .into_client_request()
            .map_err(|_| Error::Protocol)?;
        req.headers_mut().insert(
            "User-Agent",
            USER_AGENT.parse().map_err(|_| Error::Protocol)?,
        );
        req.headers_mut().insert(
            "Cookie",
            cookie_header(&self.cookies)?
                .parse()
                .map_err(|_| Error::Protocol)?,
        );
        req.headers_mut().insert(
            "X-OpenMates-SDK",
            self.options
                .identity
                .header()
                .parse()
                .map_err(|_| Error::Protocol)?,
        );
        req.headers_mut().insert(
            "Origin",
            self.app_url().parse().map_err(|_| Error::Protocol)?,
        );
        let config = WebSocketConfig::default()
            .max_message_size(Some(MAX_BODY))
            .max_frame_size(Some(MAX_BODY));
        Ok(PreparedSocketConnection{request:req,config,lifecycle:self.lifecycle(),
            active_chat:(!ephemeral&&selection==SocketSelectionPolicy::AnnounceActiveChat).then(||self.active_chat.clone()).flatten(),
            inventory_network:self.inventory_network.clone()})
    }
    async fn socket_mode_with_inventory_request(
        &mut self,
        task_jobs: bool,
        ephemeral: bool,
        completion_recovery: bool,
        selection: SocketSelectionPolicy,
        inventory_request_id: Option<&str>,
    ) -> Result<Socket> {
        // Take once before bumping the network revision. Only the first explicit
        // foreground-recovery socket can consume actual same-operation auth.
        let fresh_auth = self.take_fresh_session_for_recovery(completion_recovery)?;
        self.invalidate_chat_inventory_proofs();
        self.chat_list_freshness.invalidate();
        if !fresh_auth {
            self.validate_session().await?;
        }
        // Validation preserves real received credential rotation even when a
        // local owned child stops during that existing await. Only this actual
        // issued scope may proceed to opening a socket; ordinary mode keeps its
        // original path and a cancelled child cannot retire a healthy peer.
        self.check_active_owned_socket_start()?;
        let prepared=self.prepare_socket_connection(task_jobs,ephemeral,completion_recovery,selection,inventory_request_id)?;
        connect_prepared_socket(prepared).await
    }
}
struct PreparedSocketConnection {
    request:tungstenite::http::Request<()>,config:WebSocketConfig,lifecycle:Value,
    active_chat:Option<String>,inventory_network:std::sync::Arc<std::sync::atomic::AtomicU64>,
}
async fn connect_socket_stream(request:tungstenite::http::Request<()>,config:WebSocketConfig,
    inventory_network:std::sync::Arc<std::sync::atomic::AtomicU64>)->Result<Socket>{
    let(inner,_)=crate::platform::time::timeout(Duration::from_secs(10),
        crate::platform::socket::connect(request,Some(config),false))
        .await.map_err(|_|Error::Offline)?.map_err(|_|Error::Authentication)?;
    Ok(Socket::new(inner,Some(inventory_network)))
}
async fn connect_prepared_socket(prepared:PreparedSocketConnection)->Result<Socket>{
    let mut ws=connect_socket_stream(prepared.request,prepared.config,prepared.inventory_network).await?;
    send(&mut ws,"native_client_lifecycle",prepared.lifecycle).await?;
    if let Some(chat)=prepared.active_chat{send(&mut ws,"set_active_chat",json!({"chat_id":chat})).await?;}
    Ok(ws)
}
/// Guarded sibling of `send`; ordinary/ciphertext callers retain their API.
/// This owns the JSON and its serialized source bytes, including unpolled,
/// cancelled and failed sends. Tungstenite/TLS and browser copies are outside
/// this application-allocation cleanup boundary.
pub(super) fn send_plaintext<'a>(
    ws: &'a mut Socket,
    kind: &'a str,
    payload: Value,
) -> impl std::future::Future<Output = Result<()>> + 'a {
    let payload = PlaintextJson::new(payload);
    async move {
        if let Some(network) = &ws.inventory_network {
            network.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        }
        let mut original=ws.resource.inner.lock().await;
        send_plaintext_message(&mut *original, kind, payload).await
    }
}
fn send_plaintext_message<'a, S>(
    sink: &'a mut S,
    kind: &'a str,
    mut payload: PlaintextJson,
) -> impl std::future::Future<Output = Result<()>> + 'a
where
    S: futures_util::Sink<tungstenite::Message, Error = tungstenite::Error> + Unpin + 'a,
{
    async move {
        // Match the existing Value envelope, including map-order behavior if a
        // downstream crate enables serde_json/preserve_order. No payload clone:
        // after the swap, assigning the envelope has no fallible intermediate.
        let mut envelope = json!({"type":kind,"payload":null});
        std::mem::swap(&mut envelope["payload"], &mut payload.value);
        payload.value = envelope;
        let serialized = PlaintextBytes::serialize(&payload.value)?;
        let text = tungstenite::Utf8Bytes::try_from(serialized.owned(payload))
            .map_err(|_| Error::Protocol)?;
        sink.send(tungstenite::Message::Text(text))
            .await
            .map_err(|_| Error::Offline)
    }
}
pub(super) async fn send(ws: &mut Socket, kind: &str, payload: Value) -> Result<()> {
    if let Some(network) = &ws.inventory_network {
        network.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    }
    ws.resource.inner.lock().await
        .send(tungstenite::Message::Text(
            json!({"type":kind,"payload":payload}).to_string().into(),
        ))
        .await
        .map_err(|_| Error::Offline)
}
/// `chat_turn_preflight_handler.py` rejects a durable preflight (for example a
/// CMS transaction failure) with this exact frame before anything is admitted.
/// The ambiguous "temporarily unavailable" variant stays a generic failure.
pub(super) fn is_turn_preflight_rejection(payload: &Value) -> bool {
    payload["turn_id"].is_string()
        && payload.get("message_id").is_none()
        && payload["code"].is_string()
        && payload["code"] != "durable_preflight_failed"
        && payload["message"] == "Encrypted chat preflight was rejected."
}
pub(super) async fn receive(ws: &mut Socket) -> Result<(String, Value)> {
    let _original_receive=ws.own_receive()?;
    if let Some(frame) = ws.pop_pending()? {
        return Ok(frame);
    }
    receive_raw(ws).await
}
async fn receive_raw(ws: &mut Socket) -> Result<(String, Value)> {
    receive_raw_mode(ws, false, false).await
}
// Only volatile collectors interpret sanitized, current-turn error codes.
pub(super) async fn receive_ephemeral(ws: &mut Socket) -> Result<(String, Value)> {
    let _original_receive=ws.own_receive()?;
    if let Some(frame) = ws.pop_pending()? {
        return Ok(frame);
    }
    receive_raw_mode(ws, true, false).await
}
/// Only the monitor admits the legacy canonical event envelope. Ordinary
/// request/ACK, send, recovery and task-only parsing remains unchanged.
/// The live monitor uses `receive_monitor_frame`; the native volatile
/// metadata reader is the remaining caller.
#[cfg(not(target_arch = "wasm32"))]
pub(super) async fn receive_monitor(ws: &mut Socket) -> Result<(String, Value)> {
    let _original_receive=ws.own_receive()?;
    if let Some(frame) = ws.pop_pending()? {
        return Ok(frame);
    }
    receive_raw_mode(ws, false, true).await
}
async fn receive_raw_mode(
    ws: &mut Socket,
    ephemeral: bool,
    monitor: bool,
) -> Result<(String, Value)> {
    receive_raw_policy(ws, ephemeral, monitor, ErrorAllowance::None).await
}
/// The only typed `error` frames a non-ephemeral waiter may receive as data.
/// Every other error frame remains a fatal protocol violation.
#[derive(Clone, Copy)]
enum ErrorAllowance<'a> {
    None,
    EmbedDiff,
    /// Another device of the same owner holds this exact job's lease.
    RecoveryClaim { job: &'a str, request: &'a str },
    /// The live monitor attributes every error frame itself
    /// (`transport/monitor_error_frames.rs`).
    Monitor,
}
impl ErrorAllowance<'_> {
    fn admits(self, payload: &Value) -> bool {
        match self {
            Self::None => false,
            Self::Monitor => true,
            Self::EmbedDiff => payload["code"] == "embed_diff_conflict"
                && payload["request_id"].is_string()
                && payload["embed_id"].is_string()
                && payload["version_number"].as_u64().is_some_and(|v| v > 0),
            Self::RecoveryClaim { job, request } => payload["code"] == "lease_conflict"
                && payload["job_id"] == job
                && payload["request_id"] == request,
        }
    }
}
/// Whether an `error` frame with `payload` is a fatal protocol violation for
/// this waiter (every error frame the waiter cannot receive as data).
fn rejects_error_frame(payload: &Value, ephemeral: bool, allowance: ErrorAllowance<'_>) -> bool {
    let task_error = payload["job_id"].is_string()
        && payload["request_id"].is_string()
        && matches!(
            payload["code"].as_str(),
            Some("TaskUpdateJobConflictError" | "TaskUpdateJobNotFoundError" | "ValueError" | "PermissionError")
        );
    !ephemeral && payload["code"] != "workflow_chat_delivery_rejected" && !task_error && !allowance.admits(payload)
}
async fn receive_raw_policy(
    ws: &mut Socket, ephemeral: bool, monitor: bool, allowance: ErrorAllowance<'_>,
) -> Result<(String, Value)> {
    loop {
        let next = {
            let mut original=ws.resource.inner.lock().await;
            crate::platform::time::timeout(Duration::from_secs(90),original.next()).await
                .map_err(|_|Error::Offline)?.ok_or(Error::Offline)?.map_err(|_|Error::Offline)?
        }; // No socket guard survives frame parsing or a Client phase callback.
        if let Some(network) = &ws.inventory_network {
            network.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        }
        match next {
            tungstenite::Message::Text(data) => {
                let frame: Value = serde_json::from_str(&data)?;
                if monitor && frame.get("type").is_none() {
                    let event = required(&frame, "event")?;
                    if matches!(event, "chat_title_updated" | "chat_draft_updated")
                        && frame["chat_id"]
                            .as_str()
                            .is_some_and(|id| uuid::Uuid::parse_str(id).is_ok())
                        && frame["data"].is_object()
                        && frame["versions"].is_object()
                    {
                        return Ok((event.to_owned(), frame));
                    }
                    return Err(Error::Protocol);
                }
                let kind = required(&frame, "type")?.to_owned();
                if kind == "force_logout" {
                    return Err(Error::Expired);
                }
                if kind == "error" && is_turn_preflight_rejection(&frame["payload"]) {
                    return Err(Error::Unavailable {
                        code: "chat_turn_rejected",
                        reason: "SERVER_REJECTED_TURN_BEFORE_ADMISSION",
                    });
                }
                if kind == "error" && rejects_error_frame(&frame["payload"], ephemeral, allowance) {
                    return Err(Error::Protocol);
                }
                return Ok((kind, frame.get("payload").cloned().unwrap_or(Value::Null)));
            }
            tungstenite::Message::Ping(data) => ws.resource.inner.lock().await
                .send(tungstenite::Message::Pong(data))
                .await
                .map_err(|_| Error::Offline)?,
            tungstenite::Message::Close(_) => return Err(Error::Offline),
            _ => {}
        }
    }
}
pub(super) async fn wait(ws: &mut Socket, kind: &str, field: &str, id: &str) -> Result<Value> {
    let matches = |k: &str, p: &Value| {
        let inner = p.get("payload").unwrap_or(p);
        k == kind && (field.is_empty() || text(p, field) == id || text(inner, field) == id)
    };
    Ok(wait_matching(ws, matches).await?.1)
}
/// The first frame whose type is one of `kinds` and whose `field` equals `id`
/// (a request that is answered by either a success or a rejection frame).
pub(super) async fn wait_any(
    ws: &mut Socket,
    kinds: &[&str],
    field: &str,
    id: &str,
) -> Result<(String, Value)> {
    let matches = |k: &str, p: &Value| {
        let inner = p.get("payload").unwrap_or(p);
        kinds.contains(&k) && (text(p, field) == id || text(inner, field) == id)
    };
    wait_matching(ws, matches).await
}
/// A matching error is returned to the closed embed-diff receipt validator.
/// Other requests retain normal pending-queue/receive ownership semantics.
pub(super) async fn wait_embed_diff_outcome(
    ws: &mut Socket, request: &str,
) -> Result<(String, Value)> {
    wait_matching_policy(ws, |kind, payload| {
        matches!(kind, "store_embed_diff_confirmed" | "error")
            && payload["request_id"] == request
    }, ErrorAllowance::EmbedDiff).await
}
/// Outcome of one `recovery_job_claim` request: the claimed frame, or this
/// request's exact `lease_conflict` rejection while another device of the same
/// owner holds the lease. Any other error frame stays a protocol failure.
pub(super) async fn wait_recovery_claim(
    ws: &mut Socket, job: &str, request: &str,
) -> Result<(String, Value)> {
    let allowance = ErrorAllowance::RecoveryClaim { job, request };
    wait_matching_policy(ws, |kind, payload| {
        let inner = payload.get("payload").unwrap_or(payload);
        (kind == "recovery_job_claimed" && (text(payload, "job_id") == job || text(inner, "job_id") == job))
            || (kind == "error" && allowance.admits(payload))
    }, allowance).await
}
pub(super) async fn wait_workflow(
    ws: &mut Socket,
    kind: &str,
    request: &str,
    delivery: &str,
) -> Result<Value> {
    let (received, value) = wait_matching(ws, |received, payload| {
        (received == kind
            || received == "error" && payload["code"] == "workflow_chat_delivery_rejected")
            && payload["request_id"] == request
    })
    .await?;
    if value["delivery_id"] != delivery {
        return Err(Error::Forbidden);
    }
    if received == "error" {
        return Err(match value["reason"].as_str() {
            Some("PermissionError") => Error::Forbidden,
            Some(
                "WorkflowChatDeliveryStateError"
                | "WorkflowChatDeliveryStaleClaimError"
                | "ValueError",
            ) => Error::Conflict,
            _ => Error::Protocol,
        });
    }
    Ok(value)
}
pub(super) async fn wait_task_job(
    ws: &mut Socket,
    kind: &str,
    request: &str,
    job: &str,
) -> Result<Value> {
    let (received, value) = wait_matching(ws, |received, payload| {
        (received == kind || received == "error") && payload["request_id"] == request
    })
    .await?;
    if value["job_id"] != job {
        return Err(Error::Forbidden);
    }
    if received == "error" {
        return Err(match value["code"].as_str() {
            Some("TaskUpdateJobConflictError" | "TaskUpdateJobNotFoundError") => Error::Conflict,
            Some("PermissionError") => Error::Forbidden,
            _ => Error::Protocol,
        });
    }
    Ok(value)
}
async fn wait_matching(
    ws: &mut Socket,
    matches: impl Fn(&str, &Value) -> bool,
) -> Result<(String, Value)> {
    wait_matching_policy(ws, matches, ErrorAllowance::None).await
}
async fn wait_matching_policy(
    ws: &mut Socket, matches: impl Fn(&str, &Value) -> bool, allowance: ErrorAllowance<'_>,
) -> Result<(String, Value)> {
    let _original_receive=ws.own_receive()?;
    {
        let mut pending=ws.resource.pending.lock().map_err(|_|Error::Protocol)?;
        if let Some(index)=pending.iter().position(|(kind,payload)|matches(kind,payload)) {
            return pending.remove(index).ok_or(Error::Protocol);
        }
    } // Never retain the pending queue guard across any await.
    let deadline = crate::platform::time::Instant::now() + Duration::from_secs(90);
    loop {
        let (k, p) = crate::platform::time::timeout_at(deadline, receive_raw_policy(ws, false, false, allowance))
            .await
            .map_err(|_| Error::Offline)??;
        if matches(&k, &p) {
            return Ok((k, p));
        }
        let mut pending=ws.resource.pending.lock().map_err(|_|Error::Protocol)?;
        let size=pending.iter().map(|(kind,payload)|kind.len()+payload.to_string().len()).sum::<usize>()+k.len()+p.to_string().len();
        if pending.len()>=256||size>16*1024*1024{return Err(Error::Protocol)}
        pending.push_back((k,p));
    }
}
#[cfg(test)]
pub(super) fn test_socket(inner: crate::platform::socket::Stream) -> Socket {
    Socket::new(inner,None)
}

#[cfg(test)]
mod tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=chats.message.identity-idempotent
    #[test]
    fn only_explicit_preflight_rejections_become_turn_rejected() {
        let rejected = json!({"code":"transaction_failed","message":"Encrypted chat preflight was rejected.","turn_id":"t"});
        assert!(is_turn_preflight_rejection(&rejected));
        // A temporary failure may follow a commit; saved-turn errors carry the message ID.
        let mut temporary = rejected.clone();
        temporary["code"] = json!("durable_preflight_failed");
        temporary["message"] = json!("Encrypted chat preflight is temporarily unavailable.");
        assert!(!is_turn_preflight_rejection(&temporary));
        let mut saved = rejected.clone();
        saved["message_id"] = json!("m");
        assert!(!is_turn_preflight_rejection(&saved));
        assert!(!is_turn_preflight_rejection(&json!({"code":"x","message":"Encrypted chat preflight was rejected."})));
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn origins() {
        assert_eq!(
            validate_base("http://localhost").unwrap().host_str(),
            Some("127.0.0.1")
        );
        assert!(validate_base("http://127.0.0.1:3000").is_ok());
        assert!(validate_base("http://[::1]:3000").is_ok());
        for bad in [
            "https://user:pass@example.com",
            "https://example.com/path",
            "https://example.com/?token=x",
            "http://example.com",
        ] {
            assert!(validate_base(bad).is_err());
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn cookies_reject_injection() {
        let cookies = BTreeMap::from([(
            "auth_refresh_token".into(),
            "secret\r\nHost: attacker".into(),
        )]);
        assert!(cookie_header(&cookies).is_err())
    }
}
#[cfg(test)]
mod boundary_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn redirects_are_rejected_without_following() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            use tokio::io::{AsyncReadExt, AsyncWriteExt};
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buffer = [0u8; 4096];
            let _ = socket.read(&mut buffer).await.unwrap();
            socket.write_all(b"HTTP/1.1 302 Found\r\nLocation: https://attacker.example/\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await.unwrap();
        });
        let mut client = Client::new(&format!("http://{addr}"), None).unwrap();
        assert!(matches!(
            client.request(Method::GET, "/test", None).await,
            Err(Error::Forbidden)
        ));
        server.await.unwrap();
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn path_cannot_replace_request_authority() {
        let client = Client::new("https://api.example.com", None).unwrap();
        for path in [
            "//attacker.example/test",
            "https://attacker.example/test",
            "/\\attacker.example/test",
            "/#fragment",
        ] {
            assert!(client.url(path).is_err());
        }
        assert!(client.url("/v1/chats?q=hello").is_ok());
    }
}
#[cfg(test)]
mod origin_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn localhost_is_canonicalized_without_dns_or_broad_http_permission() {
        assert_eq!(
            validate_base("http://localhost:8000").unwrap().host_str(),
            Some("127.0.0.1")
        );
        assert!(validate_base("http://localhost.attacker.invalid:8000").is_err());
        assert!(validate_base("http://127.0.0.1.attacker.invalid:8000").is_err());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn browser_cookie_and_websocket_origins_preserve_validated_localhost() {
        for raw in ["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000", "https://api.example.com"] {
            let browser = validate_browser_base(raw).unwrap();
            assert_eq!(browser.origin(), url::Url::parse(raw).unwrap().origin());
            let mut websocket = browser.clone();
            let scheme = if browser.scheme() == "https" { "wss" } else { "ws" };
            websocket.set_scheme(scheme).unwrap();
            assert_eq!(websocket.host_str(), browser.host_str());
        }
        assert_eq!(validate_browser_base("http://localhost:8000").unwrap().host_str(), Some("localhost"));
        assert_eq!(validate_base("http://localhost:8000").unwrap().host_str(), Some("127.0.0.1"));
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn browser_cookie_origin_does_not_bypass_native_url_security_checks() {
        for raw in ["http://localhost.attacker.invalid:8000", "http://127.0.0.1.attacker.invalid:8000", "http://example.com",
            "https://user:secret@example.com", "http://localhost:8000/path", "http://localhost:8000/?token=x",
            "http://localhost:8000/#fragment", "javascript:alert(1)"] {
            assert!(validate_base(raw).is_err());
            assert!(validate_browser_base(raw).is_err());
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn application_origin_matches_existing_auth_protocol_and_custom_configuration() {
        for api in ["http://127.0.0.1:8000", "http://[::1]:8000"] {
            assert_eq!(
                Client::new(api, None).unwrap().app_url(),
                "http://localhost:5173"
            );
        }
        assert_eq!(
            Client::new("https://api.dev.openmates.org", None)
                .unwrap()
                .app_url(),
            "https://app.dev.openmates.org"
        );
        let options = ClientOptions {
            app_url: Some("https://custom.example.org".into()),
            ..ClientOptions::default()
        };
        assert_eq!(
            Client::with_options("https://api.example.org", None, options)
                .unwrap()
                .app_url(),
            "https://custom.example.org"
        );
        for raw in [
            "http://evil.example.org",
            "https://user:secret@example.org",
            "https://app.example.org/path",
            "javascript:alert(1)",
            "https://app.example.org?token=secret",
        ] {
            assert!(validate_app_origin(raw).is_err());
        }
    }
}
#[cfg(test)]
mod rotation_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn logout_sends_origin_and_reports_remote_rejection_after_clearing_local_state() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            use tokio::io::{AsyncReadExt, AsyncWriteExt};
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut bytes = [0u8; 4096];
            let n = stream.read(&mut bytes).await.unwrap();
            let request = String::from_utf8_lossy(&bytes[..n]).to_lowercase();
            assert!(request.contains("origin: http://localhost:5173"));
            assert!(request.contains("cookie: auth_refresh_token=fixture"));
            stream
                .write_all(
                    b"HTTP/1.1 403 Forbidden\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}",
                )
                .await
                .unwrap();
        });
        let mut client = Client::new(&format!("http://{address}"), None).unwrap();
        client
            .cookies
            .insert("auth_refresh_token".into(), "fixture".into());
        client.history.insert(
            "old".into(),
            vec![json!({"encrypted_content":"ciphertext"})],
        );
        assert!(matches!(client.logout().await, Err(Error::Forbidden)));
        assert!(client.session().is_none());
        assert!(client.cookies.is_empty());
        assert!(client.history.is_empty());
        server.await.unwrap();
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn header_rotation_survives_truncated_body() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            use tokio::io::{AsyncReadExt, AsyncWriteExt};
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut request = [0u8; 1024];
            let _ = stream.read(&mut request).await.unwrap();
            stream.write_all(b"HTTP/1.1 200 OK\r\nSet-Cookie: auth_refresh_token=rotated; Path=/; HttpOnly\r\nContent-Length: 100\r\nConnection: close\r\n\r\n{}").await.unwrap();
        });
        let mut client = Client::new(&format!("http://{address}"), None).unwrap();
        client
            .cookies
            .insert("auth_refresh_token".into(), "previous".into());
        client.session = Some(Session {
            api_url: format!("http://{address}"),
            session_id: "fixture".into(),
            cookies: client.cookies.clone(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([1; 32]),
            hashed_email: "hash".into(),
            user_email_salt: "salt".into(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        });
        let (tx, mut events) = mpsc::unbounded_channel();
        client.set_credential_updates(tx);
        let _ = events.try_recv();
        assert!(client.request(Method::GET, "/fixture", None).await.is_err());
        assert_eq!(
            client.cookies.get("auth_refresh_token").map(String::as_str),
            Some("rotated")
        );
        let CredentialEvent::Updated(snapshot) = events.try_recv().unwrap() else {
            panic!("rotation snapshot")
        };
        assert_eq!(
            snapshot
                .session
                .cookies
                .get("auth_refresh_token")
                .map(String::as_str),
            Some("rotated")
        );
        server.await.unwrap();
    }
}

/// Prepared under Client authority, connected only after releasing the caller's lane.
/// Headers and token are deliberately neither Debug nor serializable.
pub(super) struct TaskSocketRequest {
    request: tungstenite::handshake::client::Request,
    identity: &'static str,
    inventory_network: std::sync::Arc<std::sync::atomic::AtomicU64>,
    authority: std::sync::Arc<project_task_watch::WatchAuthority>,
    expires_at: Option<u64>,
    prepared_cancel: CancellationToken,
}
fn prepared_socket_grant_current(authority:&project_task_watch::WatchAuthority,expires_at:Option<u64>,prepared_cancel:&CancellationToken)->Result<()> {
    if expires_at.is_some_and(|deadline|deadline<=now_ms()){return Err(Error::Expired);}
    if authority.cancel.is_cancelled()||prepared_cancel.is_cancelled(){return Err(Error::Cancelled);}
    Ok(())
}
impl Client {
    pub(super) fn prepare_task_socket(&self) -> Result<TaskSocketRequest> {
        if self.is_local_browser_profile(){return Err(Error::Unavailable{code:"browser_offline_read_only",reason:"LOCAL_PROFILE_DOES_NOT_GRANT_SERVER_OR_STREAM_AUTHORITY"});}
        self.require_browser_owner_guards()?;
        self.invalidate_chat_inventory_proofs();
        let session = self.require_credentials()?;
        let mut url = self.url("/v1/ws")?;
        url.set_scheme(if self.base.scheme() == "https" {
            "wss"
        } else {
            "ws"
        })
        .map_err(|_| Error::Protocol)?;
        url.query_pairs_mut()
            .append_pair("client_capabilities", "")
            .append_pair("sessionId", &uuid::Uuid::new_v4().to_string())
            .append_pair(
                "token",
                session.ws_token.as_deref().ok_or(Error::Authentication)?,
            );
        let mut request = url
            .as_str()
            .into_client_request()
            .map_err(|_| Error::Protocol)?;
        for (name, value) in [
            ("User-Agent", USER_AGENT.to_owned()),
            ("Cookie", cookie_header(&self.cookies)?),
            ("X-OpenMates-SDK", self.options.identity.header().to_owned()),
            ("Origin", self.app_url()),
        ] {
            request.headers_mut().insert(
                tungstenite::http::header::HeaderName::from_bytes(name.as_bytes())
                    .map_err(|_| Error::Protocol)?,
                value.parse().map_err(|_| Error::Protocol)?,
            );
        }
        Ok(TaskSocketRequest {
            request,
            identity: self.options.identity.header(),
            inventory_network: self.inventory_network.clone(),
            authority: self.task_watch_authority.clone(),
            expires_at: session.paired_session_expires_at,
            prepared_cancel: self.browser_prepared_transport_cancel.clone(),
        })
    }
}
pub(super) async fn connect_task_socket(prepared: TaskSocketRequest) -> Result<Socket> {
    prepared_socket_grant_current(&prepared.authority,prepared.expires_at,&prepared.prepared_cancel)?;
    prepared
        .inventory_network
        .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let config = WebSocketConfig::default()
        .max_message_size(Some(crate::project_task_sync::MAX_FRAME_BYTES))
        .max_frame_size(Some(crate::project_task_sync::MAX_FRAME_BYTES));
    let (inner, _) = crate::platform::time::timeout(
        Duration::from_secs(10),
        crate::platform::socket::connect(prepared.request, Some(config), false),
    )
    .await
    .map_err(|_| Error::Offline)?
    .map_err(|_| Error::Authentication)?;
    let mut socket=Socket::new(inner,Some(prepared.inventory_network));
    if let Err(error)=prepared_socket_grant_current(&prepared.authority,prepared.expires_at,&prepared.prepared_cancel){let _=socket.close(None).await;return Err(error);}
    // Task read-only transport never advertises a foreground host, active chat,
    // agentic storage, Task jobs or remote terminal execution/presence.
    send(
        &mut socket,
        "native_client_lifecycle",
        json!({"client_type":prepared.identity,
        "is_foreground":false,"interactive":false}),
    )
    .await?;
    if let Err(error)=prepared_socket_grant_current(&prepared.authority,prepared.expires_at,&prepared.prepared_cancel){let _=socket.close(None).await;return Err(error);}
    Ok(socket)
}

// Append-only private draft; no change to chat/task/watch receive semantics.
pub(super) struct SourceHostSocketRequest(TaskSocketRequest);
impl Client {
    pub(super) fn prepare_source_host_socket(&self) -> Result<SourceHostSocketRequest> {
        // Same Cookie/Origin/token/SDK header preparation, empty generic jobs.
        Ok(SourceHostSocketRequest(self.prepare_task_socket()?))
    }
}
pub(super) async fn connect_source_host_socket(
    prepared: SourceHostSocketRequest,
) -> Result<Socket> {
    prepared_socket_grant_current(&prepared.0.authority,prepared.0.expires_at,&prepared.0.prepared_cancel)?;
    prepared
        .0
        .inventory_network
        .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    // The lifecycle write is inside the same deadline as the WS handshake.
    crate::platform::time::timeout(Duration::from_secs(10), async {
        let config = WebSocketConfig::default()
            .max_message_size(Some(1024 * 1024))
            .max_frame_size(Some(1024 * 1024));
        let (inner, _) = crate::platform::socket::connect(prepared.0.request, Some(config), false)
            .await
            .map_err(|_| Error::Authentication)?;
        let mut socket=Socket::new(inner,Some(prepared.0.inventory_network));
        if let Err(error)=prepared_socket_grant_current(&prepared.0.authority,prepared.0.expires_at,&prepared.0.prepared_cancel){let _=socket.close(None).await;return Err(error);}
        send(
            &mut socket,
            "native_client_lifecycle",
            json!({"client_type":prepared.0.identity,"is_foreground":false,"interactive":false}),
        )
        .await?;
        if let Err(error)=prepared_socket_grant_current(&prepared.0.authority,prepared.0.expires_at,&prepared.0.prepared_cancel){let _=socket.close(None).await;return Err(error);}
        Ok(socket)
    })
    .await
    .map_err(|_| Error::Offline)?
}
#[cfg(test)]
pub(super) fn expire_prepared_socket_for_test(prepared:&mut TaskSocketRequest){prepared.expires_at=Some(0);}
#[cfg(test)]
pub(super) fn expire_prepared_source_socket_for_test(prepared:&mut SourceHostSocketRequest){prepared.0.expires_at=Some(0);}

pub(super) async fn receive_source_host(socket: &mut Socket) -> Result<(String, Value)> {
    // Mode preserves generic codes, but this surface returns only its own
    // bounded allowlist and converts every unknown error to Protocol.
    let (kind, payload) = receive_ephemeral(socket).await?;
    if kind == "error"
        && !matches!(
            payload["code"].as_str(),
            Some(
                "takeover_confirmation_required"
                    | "source_not_found"
                    | "source_host_mismatch"
                    | "source_capability_denied"
                    | "team_membership_required"
                    | "session_scope_mismatch"
                    | "heartbeat_too_early"
                    | "request_scope_mismatch"
                    | "request_already_completed"
                    | "invalid_source_binding"
                    | "source_bindings_required"
                    | "duplicate_source_binding"
                    | "invalid_source_capabilities"
                    | "source_offline"
                    | "source_session_changed"
                    | "bridge_busy"
                    | "payload_too_large"
                    | "encrypted_envelope_required"
            )
        )
    {
        return Err(Error::Protocol);
    }
    Ok((kind, payload))
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "transport_plaintext_tests.rs"]
mod plaintext_tests;

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "transport_owned_socket_tests.rs"]
mod owned_socket_tests;

#[cfg(not(target_arch="wasm32"))]
pub(super) mod ephemeral_metadata;

#[cfg(test)]
#[path="transport/project_workflow_result_tests.rs"]
mod project_workflow_result_tests;
