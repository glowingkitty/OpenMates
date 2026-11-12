//! Requester side of the Project source remote-access protocol (npm
//! projectRequester.ts) for read-only file operations: list, search and
//! read_text. The request envelope is encrypted with the Project key; the
//! source answers through an authenticated X25519 session bound to the exact
//! requester identity, request ID and direction. The relay sees ciphertext only.
use super::*;
use crate::remote_access_crypto::{
    ContextType, Envelope, Handshake, HandshakeState, Identity, Role,
};

const PROTOCOL_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(45);
const POLL_INTERVAL: std::time::Duration = std::time::Duration::from_millis(250);
const MAX_RESULT_BYTES: usize = 200 * 1024;

/// A read-only source operation.
#[derive(Clone)]
pub enum ProjectFileOperation {
    List {
        path: String,
        depth: u32,
    },
    Search {
        query: String,
        include_content: bool,
    },
    ReadText {
        path: String,
    },
}
impl ProjectFileOperation {
    fn wire(&self) -> (&'static str, Value) {
        match self {
            Self::List { path, depth } => ("list", json!({"path":path,"depth":depth})),
            Self::Search {
                query,
                include_content,
            } => (
                "search",
                json!({"query":query,"target":"files","mode":"literal","path":".","include_content":include_content}),
            ),
            Self::ReadText { path } => ("read_text", json!({"path":path})),
        }
    }
}
/// A typed protocol failure (npm ProjectRequesterError code + message), or a
/// core transport/crypto error.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ProjectRequesterError {
    Core(Error),
    Remote { code: String, message: String },
}
impl std::fmt::Display for ProjectRequesterError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Core(error) => std::fmt::Display::fmt(error, f),
            Self::Remote { message, .. } => f.write_str(message),
        }
    }
}
impl std::error::Error for ProjectRequesterError {}
impl From<Error> for ProjectRequesterError {
    fn from(error: Error) -> Self {
        Self::Core(error)
    }
}
fn remote(code: &str, message: &str) -> ProjectRequesterError {
    ProjectRequesterError::Remote {
        code: code.into(),
        message: message.into(),
    }
}
/// npm remoteErrorMessage.
pub fn remote_error_message(code: &str) -> String {
    match code {
        "protected_path" => "The requested path is protected or ignored.".into(),
        "unsupported_file" => "The requested file is binary or invalid UTF-8.".into(),
        "invalid_path" => "The requested path is invalid, unavailable, or a symbolic link.".into(),
        "search_query_required" => "A search query is required.".into(),
        "operation_failed" => "The Project source operation failed.".into(),
        "ignored_path_requires_approval" => "This ignored file requires explicit approval.".into(),
        other => format!("The Project source rejected the request ({other})."),
    }
}
/// npm safeRelativeProjectPath.
pub fn safe_relative_path(value: &str) -> std::result::Result<String, ProjectRequesterError> {
    let normalized = value.replace('\\', "/");
    if normalized.is_empty() || normalized.starts_with('/') || normalized.contains('\0') {
        return Err(remote(
            "invalid_path",
            "Project file paths must be source-relative.",
        ));
    }
    if normalized.split('/').any(|part| part == "..") {
        return Err(remote(
            "invalid_path",
            "Project file paths cannot traverse outside the source.",
        ));
    }
    Ok(normalized)
}
/// npm selectProjectSource without the interactive prompt.
pub fn select_source(
    sources: &[Value],
    requested: Option<&str>,
) -> std::result::Result<Value, ProjectRequesterError> {
    if let Some(requested) = requested {
        return sources
            .iter()
            .find(|s| s["source_id"] == requested)
            .cloned()
            .ok_or_else(|| ProjectRequesterError::Remote {
                code: "source_not_found".into(),
                message: format!("Project source '{requested}' was not found."),
            });
    }
    let eligible = sources
        .iter()
        .filter(|s| s["status"] == "connected")
        .collect::<Vec<_>>();
    match eligible.as_slice() {
        [one] => Ok((*one).clone()),
        [] => Err(remote(
            "source_offline",
            "No online Project source is available.",
        )),
        _ => Err(remote(
            "source_selection_required",
            "Multiple online Project sources require --source <source-id>.",
        )),
    }
}
/// The relay request body; write-class calls also bind chat, operation id and
/// proposal digest so the backend can match the stored approval.
fn request_body(
    request_id: &str,
    client_id: &str,
    sealed: (&str, u64, &str),
    chat: Option<&str>,
    approval: &Option<(String, String)>,
) -> Value {
    let (operation, key_epoch, envelope) = sealed;
    let mut body = json!({"request_id":request_id,"requesting_client_id":client_id,
        "operation":operation,"key_epoch":key_epoch,"encrypted_envelope":envelope});
    // A chat id alone lets the relay resolve the chat worktree for reads.
    if let Some(chat) = chat {
        body["chat_id"] = json!(chat);
    }
    if let Some((operation_id, digest)) = approval {
        body["operation_id"] = json!(operation_id);
        body["proposal_digest"] = json!(digest);
    }
    body
}
fn object(text: &str) -> std::result::Result<Value, ProjectRequesterError> {
    serde_json::from_str::<Value>(text)
        .ok()
        .filter(Value::is_object)
        .ok_or_else(|| {
            remote(
                "invalid_remote_payload",
                "The Project source returned an invalid payload.",
            )
        })
}

impl Projects<'_> {
    async fn requester_owner(&mut self) -> Result<String> {
        match &mut self.backend {
            Backend::ApiKey(_) => Err(Error::Unavailable {
                code: "project_remote_access_unavailable",
                reason: "PROJECT_REMOTE_ACCESS_REQUIRES_COOKIE_SESSION",
            }),
            Backend::Cookie(client) => {
                client.validate_session().await?;
                client.user()["id"]
                    .as_str()
                    .or(client.user()["user_id"].as_str())
                    .filter(|v| !v.is_empty())
                    .map(str::to_owned)
                    .ok_or(Error::Authentication)
            }
        }
    }
    fn source_route(
        &self,
        project: &str,
        source: &str,
        tail: &str,
        params: &[(String, String)],
    ) -> Result<String> {
        let source = super::sources::source_patch_segment(source)?;
        Ok(self.path(
            &format!("/v1/projects/{project}/sources/{source}/requests{tail}"),
            params,
        ))
    }
    async fn poll_result(
        &mut self,
        project: &str,
        source: &str,
        request: &str,
        client_id: &str,
        timeout: std::time::Duration,
    ) -> std::result::Result<Value, ProjectRequesterError> {
        let route = self.source_route(
            project,
            source,
            &format!("/{request}"),
            &[("requesting_client_id".into(), client_id.into())],
        )?;
        let deadline = crate::platform::time::Instant::now() + timeout;
        while crate::platform::time::Instant::now() < deadline {
            if self.operation_cancel.is_cancelled() {
                return Err(Error::Cancelled.into());
            }
            match self.backend.request(Method::GET, &route, None, None).await {
                Ok(result) => return Ok(result),
                // The relay answers 404 (request_not_found) until the source replies.
                Err(Error::Invalid("The requested item is unavailable.")) => {}
                Err(error) => return Err(error.into()),
            }
            crate::platform::time::sleep(POLL_INTERVAL).await;
        }
        Err(remote(
            "protocol_timeout",
            "The Project source did not respond before the protocol timeout.",
        ))
    }
    /// One read-only file operation on a connected Project source. Returns
    /// `{project_id, source_id, result}`.
    pub async fn source_file_operation(
        &mut self,
        selector: &str,
        requested_source: Option<&str>,
        operation: ProjectFileOperation,
    ) -> std::result::Result<Value, ProjectRequesterError> {
        self.source_file_operation_with_timeout(
            selector,
            requested_source,
            operation,
            PROTOCOL_TIMEOUT,
        )
        .await
    }
    pub(crate) async fn source_file_operation_with_timeout(
        &mut self,
        selector: &str,
        requested_source: Option<&str>,
        operation: ProjectFileOperation,
        timeout: std::time::Duration,
    ) -> std::result::Result<Value, ProjectRequesterError> {
        if let ProjectFileOperation::Search { query, .. } = &operation
            && query.len() > 256
        {
            return Err(remote("query_too_large", "Search query exceeds 256 bytes."));
        }
        let (name, arguments) = operation.wire();
        let capability = matches!(
            operation,
            ProjectFileOperation::Search {
                include_content: true,
                ..
            }
        )
        .then_some("read");
        let call = super::remote_ops::WireCall {
            name,
            arguments,
            capability,
            chat: None,
            write: None,
        };
        let (project_id, source_id, result) = self
            .source_call(selector, requested_source, call, timeout)
            .await?;
        Ok(json!({"project_id":project_id,"source_id":source_id,"result":result}))
    }
    /// The shared encrypted requester transport: resolve the Project and
    /// source, optionally store the write approval, send one sealed request
    /// and open the sealed answer. Returns `(project_id, source_id, result)`.
    pub(super) async fn source_call(
        &mut self,
        selector: &str,
        requested_source: Option<&str>,
        call: super::remote_ops::WireCall,
        timeout: std::time::Duration,
    ) -> std::result::Result<(String, String, Value), ProjectRequesterError> {
        self.scope()?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let sources = self.list_sources_raw(&project_id).await?;
        let source = select_source(&sources, requested_source)?;
        let source_id = string(&source, "source_id")?.to_owned();
        if source["status"] != "connected" {
            return Err(remote(
                "source_offline",
                "The selected Project source is offline.",
            ));
        }
        if let Some(capability) = call.capability
            && source["capabilities"]
                .as_array()
                .is_some_and(|caps| !caps.iter().any(|c| c == capability))
        {
            return Err(remote(
                "source_capability_denied",
                "This Project source does not allow this operation.",
            ));
        }
        let mut approval = None;
        if let Some((chat, proposal)) = &call.write {
            let digest = proposal.digest(&project.key, &project_id, chat)?;
            let route = self.path(&format!("/v1/projects/{project_id}/write-approvals"), &[]);
            self.backend
                .request(
                    Method::POST,
                    &route,
                    Some(
                        json!({"chat_id":chat,"operation_id":proposal.operation_id(),"proposal_digest":digest}),
                    ),
                    None,
                )
                .await?;
            approval = Some((proposal.operation_id().to_owned(), digest));
        }
        let mut session_id = source["source_session_id"]
            .as_str()
            .filter(|s| !s.is_empty())
            .map(str::to_owned);
        let mut key_epoch = source["key_epoch"].as_u64();
        let mut routing = None;
        if session_id.is_none() || key_epoch.is_none() {
            let (session, epoch, identity) = self
                .discover_routing(&project_id, &source_id, &project.key, timeout)
                .await?;
            session_id = Some(session);
            key_epoch = Some(epoch);
            routing = Some(identity);
        }
        let (session_id, key_epoch) = (
            session_id.ok_or(Error::Protocol)?,
            key_epoch.ok_or(Error::Protocol)?,
        );
        let client_id = uuid::Uuid::new_v4().to_string();
        let request_id = uuid::Uuid::new_v4().to_string();
        let identity = match routing {
            Some(r) => Identity {
                owner_id: string(&r, "context_id_hash")?.into(),
                context_type: Some(ContextType::Team),
                context_id: Some(string(&r, "context_id_hash")?.into()),
                project_id: project_id.clone(),
                source_id: source_id.clone(),
                source_session_id: session_id.clone(),
                requesting_client_id: client_id.clone(),
                host_member_id: Some(string(&r, "host_member_hash")?.into()),
                host_device_id: Some(string(&r, "host_device_fingerprint_hash")?.into()),
                requester_member_id: Some(string(&r, "requester_member_hash")?.into()),
                requester_device_id: Some(string(&r, "requester_device_fingerprint_hash")?.into()),
                key_epoch,
            },
            None => Identity {
                owner_id: self.requester_owner().await?,
                context_type: None,
                context_id: None,
                project_id: project_id.clone(),
                source_id: source_id.clone(),
                source_session_id: session_id.clone(),
                requesting_client_id: client_id.clone(),
                host_member_id: None,
                host_device_id: None,
                requester_member_id: None,
                requester_device_id: None,
                key_epoch,
            },
        };
        let requester = HandshakeState::new(&project.key, identity, Role::Requester)?;
        let (name, arguments) = (call.name, call.arguments);
        let envelope = crate::work::teams::legacy_encrypt(
            json!({"requesting_client_id":client_id,"requester_handshake":requester.handshake(),
                "operation":name,"arguments":arguments})
            .to_string()
            .as_bytes(),
            &project.key,
        )?;
        let route = self.source_route(&project_id, &source_id, "", &[])?;
        let created = self
            .backend
            .request(
                Method::POST,
                &route,
                Some(request_body(
                    &request_id,
                    &client_id,
                    (name, key_epoch, &envelope),
                    call.chat.as_deref(),
                    &approval,
                )),
                None,
            )
            .await?;
        if created["source_session_id"] != session_id.as_str() || created["key_epoch"] != key_epoch
        {
            return Err(remote(
                "source_session_changed",
                "The Project source session changed. Retry the request.",
            ));
        }
        let result = self
            .poll_result(&project_id, &source_id, &request_id, &client_id, timeout)
            .await?;
        let payload = object(result["encrypted_envelope"].as_str().unwrap_or(""))?;
        let invalid = || {
            remote(
                "invalid_encrypted_result",
                "The Project source returned an invalid encrypted result.",
            )
        };
        let handshake = Handshake::from_json(payload["source_handshake"].to_string().as_bytes())
            .map_err(|_| invalid())?;
        let sealed = Envelope::from_json(payload["envelope"].to_string().as_bytes())
            .map_err(|_| invalid())?;
        let mut session = requester.finish(&handshake)?;
        let plaintext = session.open(&request_id, &sealed)?;
        if plaintext.len() > MAX_RESULT_BYTES {
            return Err(remote(
                "result_too_large",
                "The encrypted Project source result exceeded the byte limit.",
            ));
        }
        let text = std::str::from_utf8(&plaintext).map_err(|_| {
            remote(
                "invalid_remote_payload",
                "The Project source returned an invalid payload.",
            )
        })?;
        let response = object(text)?;
        if response["ok"] != true {
            let code = response["error"].as_str().unwrap_or("operation_failed");
            return Err(ProjectRequesterError::Remote {
                code: code.into(),
                message: remote_error_message(code),
            });
        }
        Ok((project_id, source_id, response["result"].clone()))
    }
    async fn discover_routing(
        &mut self,
        project: &str,
        source: &str,
        key: &[u8; 32],
        timeout: std::time::Duration,
    ) -> std::result::Result<(String, u64, Value), ProjectRequesterError> {
        let request_id = uuid::Uuid::new_v4().to_string();
        let client_id = uuid::Uuid::new_v4().to_string();
        let nonce = uuid::Uuid::new_v4().to_string();
        let envelope = crate::work::teams::legacy_encrypt(
            json!({"type":"routing_discovery","requesting_client_id":client_id,"nonce":nonce})
                .to_string()
                .as_bytes(),
            key,
        )?;
        let route = self.source_route(project, source, "", &[])?;
        let created = self
            .backend
            .request(
                Method::POST,
                &route,
                Some(
                    json!({"request_id":request_id,"requesting_client_id":client_id,
                    "operation":"list","key_epoch":1,"encrypted_envelope":envelope}),
                ),
                None,
            )
            .await?;
        let routing = created["routing_identity"].clone();
        let session = created["source_session_id"]
            .as_str()
            .filter(|s| !s.is_empty());
        let epoch = created["key_epoch"].as_u64().filter(|e| *e > 0);
        let (Some(session), Some(epoch)) = (session, epoch) else {
            return Err(remote(
                "routing_identity_unavailable",
                "The Team source routing identity is unavailable.",
            ));
        };
        if routing["context_type"] != "team" {
            return Err(remote(
                "routing_identity_unavailable",
                "The Team source routing identity is unavailable.",
            ));
        }
        let session = session.to_owned();
        let result = self
            .poll_result(project, source, &request_id, &client_id, timeout)
            .await?;
        let discovery =
            crypto::decrypt_combined(result["encrypted_envelope"].as_str().unwrap_or(""), key)
                .ok()
                .and_then(|text| serde_json::from_str::<Value>(&text).ok())
                .unwrap_or(Value::Null);
        if discovery["type"] != "routing_discovery_result" || discovery["nonce"] != nonce.as_str() {
            return Err(remote(
                "routing_identity_invalid",
                "The Team source routing discovery response was invalid.",
            ));
        }
        Ok((session, epoch, routing))
    }
}

#[cfg(test)]
#[path = "remote_files_tests.rs"]
pub(super) mod tests;
