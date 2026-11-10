//! Per-request dispatch for the filesystem host (npm
//! `handleLiveRemoteAccessRequest` / `executeRemoteAccessOperation` in
//! `remoteAccess.ts`).
//!
//! Wire contract, unchanged from npm so either host serves the same requester:
//! - the frame's `encrypted_envelope` is a legacy AES-GCM combined blob under the
//!   Project key holding the bootstrap `{requesting_client_id,
//!   requester_handshake, operation, arguments, ignored_read_grant?,
//!   ignored_read_context?}` or a `routing_discovery` probe;
//! - a discovery probe is answered with the Project-key encrypted
//!   `{"type":"routing_discovery_result","nonce":...}`;
//! - every other answer is `{"source_handshake":..., "envelope":...}` where the
//!   envelope seals `{"ok":true,"result":...}` or `{"ok":false,"error":code}`
//!   with the authenticated remote-access session key;
//! - an invalid or mismatched bootstrap is dropped without any completion so
//!   no plaintext diagnostic reaches the relay.

use super::reads::{self, HostRoot};
use super::writes::{self, Mutation, WriteRequest};
use super::{HostError, HostResult, search};
use crate::client::{
    Client, SourceHostAdapter, SourceHostOperation, SourceHostRequest, SourceHostSession,
};
use crate::error::Result;
use crate::remote_access_crypto::Handshake;
use crate::work::ProjectSourceCapability;
use hmac::{Hmac, Mac};
use reqwest::Method;
use serde_json::{Value, json};
use sha2::Sha256;
use tokio_util::sync::CancellationToken;

const IGNORED_GRANT_LIFETIME_MS: u64 = 5 * 60 * 1000;

/// Implementation evidence for the Rust filesystem host. `copy_entries` and
/// `move_entries` are claimed because the shared binding requires the whole
/// `write_request` family, but they answer `unsupported_operation` until the
/// transfer slice lands (an unclaimed operation would close the session).
pub struct FilesystemSourceAdapter;

impl SourceHostAdapter for FilesystemSourceAdapter {
    fn implemented_capabilities(&self) -> Vec<ProjectSourceCapability> {
        vec![
            ProjectSourceCapability::Read,
            ProjectSourceCapability::Search,
            ProjectSourceCapability::WriteRequest,
        ]
    }
    fn supports_operation(&self, _operation: SourceHostOperation) -> bool {
        true
    }
}

/// One live source the host serves.
#[derive(Clone, Debug)]
pub(crate) struct HostedSource {
    pub(crate) project_id: String,
    pub(crate) source_id: String,
    pub(crate) team_id: Option<String>,
    pub(crate) root: HostRoot,
}

fn operation_name(operation: SourceHostOperation) -> &'static str {
    match operation {
        SourceHostOperation::List => "list",
        SourceHostOperation::Search => "search",
        SourceHostOperation::ReadText => "read_text",
        SourceHostOperation::ReadImageChunk => "read_image_chunk",
        SourceHostOperation::ReadFileChunk => "read_file_chunk",
        SourceHostOperation::CreateFile => "create_file",
        SourceHostOperation::UpdateFile => "update_file",
        SourceHostOperation::CopyEntries => "copy_entries",
        SourceHostOperation::MoveEntries => "move_entries",
    }
}

/// What happened to one request (for local lifecycle output only).
pub(crate) enum Handled {
    /// A sealed answer (success or error code) was completed.
    Answered(String),
    /// A routing discovery probe was answered.
    Discovery,
    /// The bootstrap was invalid; the request was dropped without completion.
    Dropped,
}

/// Decrypt, execute and complete one request.
///
/// # Errors
/// Session-level failures (`Cancelled`, `Expired`, `Offline`, transport
/// errors). Operation failures are sealed into the answer instead.
pub(crate) async fn handle(
    client: &mut Client,
    host: &mut SourceHostSession,
    request: SourceHostRequest,
    sources: &[HostedSource],
    cancel: &CancellationToken,
) -> Result<Handled> {
    let frame = request.provisional_envelope()?;
    let Some(source) = sources
        .iter()
        .find(|s| s.project_id == frame.project_id && s.source_id == frame.source_id)
        .cloned()
    else {
        host.abandon(request);
        return Ok(Handled::Dropped);
    };
    let key = host.request_key(&request)?;
    let Ok(text) = crate::crypto::decrypt_combined(&frame.encrypted_envelope, &key) else {
        host.abandon(request);
        return Ok(Handled::Dropped);
    };
    let Ok(bootstrap) = serde_json::from_str::<Value>(&text) else {
        host.abandon(request);
        return Ok(Handled::Dropped);
    };
    let client_id = frame.requesting_client_id.clone();
    if bootstrap["type"] == "routing_discovery"
        && bootstrap["requesting_client_id"] == client_id.as_str()
        && bootstrap["nonce"].as_str().is_some_and(|n| !n.is_empty())
    {
        let reply = json!({"type": "routing_discovery_result", "nonce": bootstrap["nonce"]});
        let sealed = crate::work::legacy_encrypt(reply.to_string().as_bytes(), &key)?;
        host.complete(request, sealed, cancel).await?;
        return Ok(Handled::Discovery);
    }
    let operation = operation_name(frame.operation);
    if bootstrap["requesting_client_id"] != client_id.as_str()
        || bootstrap["operation"] != operation
        || !bootstrap["arguments"].is_object()
        || bootstrap["requester_handshake"].is_null()
        || (source.team_id.is_some()
            && frame.routing_identity.as_ref().map(|r| r.context_type.as_str()) != Some("team"))
    {
        host.abandon(request);
        return Ok(Handled::Dropped);
    }
    let Ok(requester) = Handshake::from_json(bootstrap["requester_handshake"].to_string().as_bytes())
    else {
        host.abandon(request);
        return Ok(Handled::Dropped);
    };
    let state = host.source_handshake(&request)?;
    let source_handshake = state.handshake()?;
    let Ok(mut crypto) = state.finish(&requester) else {
        // A requester handshake that fails authentication is a forged or stale
        // request: fail closed without diagnostics.
        host.abandon(request);
        return Ok(Handled::Dropped);
    };
    let context = RequestContext {
        project_id: frame.project_id.clone(),
        source_id: frame.source_id.clone(),
        request_id: frame.request_id.clone(),
        chat_id: frame.chat_id.clone(),
        operation_id: frame.operation_id.clone(),
        proposal_digest: frame.proposal_digest.clone(),
        source_session_id: frame.source_session_id.clone(),
    };
    let outcome = execute(client, &source, &context, frame.operation, &bootstrap, &key).await;
    let response = match outcome {
        Ok(result) => reads::serialize_success(result),
        Err(error) => json!({"ok": false, "error": error.code}).to_string(),
    };
    let code = serde_json::from_str::<Value>(&response)
        .ok()
        .and_then(|v| v["error"].as_str().map(str::to_owned))
        .unwrap_or_else(|| "ok".to_owned());
    let envelope = crypto.seal(response.as_bytes())?;
    let payload = json!({"source_handshake": source_handshake, "envelope": envelope}).to_string();
    host.complete(request, payload, cancel).await?;
    Ok(Handled::Answered(format!("{operation} {code}")))
}

struct RequestContext {
    project_id: String,
    source_id: String,
    request_id: String,
    chat_id: Option<String>,
    operation_id: Option<String>,
    proposal_digest: Option<String>,
    source_session_id: String,
}

async fn execute(
    client: &mut Client,
    source: &HostedSource,
    context: &RequestContext,
    operation: SourceHostOperation,
    bootstrap: &Value,
    key: &[u8; 32],
) -> HostResult<Value> {
    let args = bootstrap["arguments"].clone();
    match operation {
        SourceHostOperation::CreateFile | SourceHostOperation::UpdateFile => {
            write(client, source, context, operation, &args, key).await
        }
        SourceHostOperation::CopyEntries | SourceHostOperation::MoveEntries => {
            Err(HostError::failed("unsupported_operation"))
        }
        SourceHostOperation::Search => {
            if args["include_content"] == true {
                require_read_and_search(client, source).await?;
            }
            blocking(source.root.clone(), move |root| search::search(&root, &args)).await
        }
        SourceHostOperation::List => blocking(source.root.clone(), move |root| reads::list(&root, &args)).await,
        SourceHostOperation::ReadText => {
            let requested = args["path"].as_str().unwrap_or(".").to_owned();
            let approved = ignored_read_approved(key, bootstrap, context, &requested);
            blocking(source.root.clone(), move |root| reads::read_text(&root, &args, approved)).await
        }
        SourceHostOperation::ReadImageChunk => {
            blocking(source.root.clone(), move |root| reads::read_image_chunk(&root, &args)).await
        }
        SourceHostOperation::ReadFileChunk => {
            blocking(source.root.clone(), move |root| reads::read_file_chunk(&root, &args)).await
        }
    }
}

/// Filesystem work runs off the async worker so the socket stays responsive.
async fn blocking<F>(root: HostRoot, work: F) -> HostResult<Value>
where
    F: FnOnce(HostRoot) -> HostResult<Value> + Send + 'static,
{
    tokio::task::spawn_blocking(move || work(root))
        .await
        .map_err(|_| HostError::failed("Host operation was interrupted"))?
}

fn source_route(source: &HostedSource, suffix: &str) -> String {
    let base = format!(
        "/v1/projects/{}/sources{suffix}",
        url::form_urlencoded::byte_serialize(source.project_id.as_bytes()).collect::<String>()
    );
    crate::work::path(&base, source.team_id.as_deref(), &[])
}

/// npm: content attachment needs current `read` and `search` capabilities.
async fn require_read_and_search(client: &mut Client, source: &HostedSource) -> HostResult<()> {
    let denied = || HostError::new("source_capability_denied", "source_capability_denied");
    let response = client
        .request(Method::GET, &source_route(source, ""), None)
        .await
        .map_err(|_| denied())?;
    let allowed = response["sources"].as_array().is_some_and(|rows| {
        rows.iter().any(|row| {
            row["source_id"] == source.source_id.as_str()
                && row["capabilities"].as_array().is_some_and(|caps| {
                    caps.iter().any(|c| c == "read") && caps.iter().any(|c| c == "search")
                })
        })
    });
    if allowed { Ok(()) } else { Err(denied()) }
}

/// npm `verifyProjectIgnoredReadGrant` for the exact requested path.
fn ignored_read_approved(key: &[u8; 32], bootstrap: &Value, context: &RequestContext, path: &str) -> bool {
    let grant = &bootstrap["ignored_read_grant"];
    let scope = &bootstrap["ignored_read_context"];
    let (Some(chat), Some(operation)) = (scope["chatId"].as_str(), scope["operationId"].as_str()) else {
        return false;
    };
    let expected = [
        ("projectId", context.project_id.as_str()),
        ("sourceId", context.source_id.as_str()),
        ("requestId", context.request_id.as_str()),
        ("chatId", chat),
        ("operationId", operation),
        ("path", path),
    ];
    let valid_path = |p: &str| {
        !p.is_empty()
            && p.encode_utf16().count() <= 4096
            && !p.contains('\\')
            && !p.starts_with('/')
            && !(p.as_bytes().get(1) == Some(&b':') && p.as_bytes()[0].is_ascii_alphabetic())
            && !p.chars().any(|c| (c as u32) < 32 || c as u32 == 127)
            && p.split('/').all(|part| !part.is_empty() && part != "." && part != "..")
    };
    let ids_ok = expected[..5]
        .iter()
        .all(|(_, v)| !v.is_empty() && v.encode_utf16().count() <= 128);
    let now = crate::client::now_ms();
    let Some(expires) = grant["expiresAt"].as_u64() else {
        return false;
    };
    let Some(signature) = grant["signature"]
        .as_str()
        .filter(|s| s.len() == 64 && s.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)))
    else {
        return false;
    };
    if grant["version"] != 1
        || !ids_ok
        || !valid_path(path)
        || expires <= now
        || expires > now + IGNORED_GRANT_LIFETIME_MS
        || expected.iter().any(|(k, v)| grant[*k] != *v)
    {
        return false;
    }
    let material = json!([
        "openmates-ignored-read-v1",
        context.project_id,
        context.source_id,
        context.request_id,
        chat,
        operation,
        path,
        expires,
    ])
    .to_string();
    let Ok(bytes) = (0..32)
        .map(|i| u8::from_str_radix(&signature[i * 2..i * 2 + 2], 16))
        .collect::<std::result::Result<Vec<u8>, _>>()
    else {
        return false;
    };
    let Ok(mut mac) = <Hmac<Sha256> as Mac>::new_from_slice(key) else {
        return false;
    };
    mac.update(material.as_bytes());
    mac.verify_slice(&bytes).is_ok()
}

fn denied() -> HostError {
    HostError::new("write_authorization_denied", "write_authorization_denied")
}

/// npm write branch: digest check, then authorization before and under the locks.
async fn write(
    client: &mut Client,
    source: &HostedSource,
    context: &RequestContext,
    operation: SourceHostOperation,
    args: &Value,
    key: &[u8; 32],
) -> HostResult<Value> {
    let mutation: Mutation = writes::validate(&args["mutation"])?;
    let chat_id = args["chat_id"].as_str().ok_or_else(denied)?;
    let expected_op = operation_name(operation);
    if Some(chat_id) != context.chat_id.as_deref()
        || mutation.operation() != expected_op
        || Some(mutation.operation_id.as_str()) != context.operation_id.as_deref()
        || Some(writes::digest(key, &context.project_id, chat_id, &mutation)?)
            != context.proposal_digest
    {
        return Err(denied());
    }
    let route = source_route(
        source,
        &format!(
            "/{}/requests/{}/authorize-write",
            url::form_urlencoded::byte_serialize(source.source_id.as_bytes()).collect::<String>(),
            url::form_urlencoded::byte_serialize(context.request_id.as_bytes()).collect::<String>()
        ),
    );
    let body = json!({"source_session_id": context.source_session_id});
    let initial = authorize(client, &route, &body).await?;
    let scope = initial["authorization_scope"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(denied)?
        .to_owned();
    let mut authority = BackendWriteAuthority {
        client,
        route,
        body,
        scope: scope.clone(),
        operation_id: mutation.operation_id.clone(),
    };
    writes::execute(
        WriteRequest {
            root: &source.root.root,
            state_dir: &source.root.state_dir,
            mutation: &mutation,
            scope: &scope,
            journal_root: None,
        },
        &mut authority,
    )
    .await
}

/// Fresh backend re-authorization with an unchanged scope and operation.
struct BackendWriteAuthority<'a> {
    client: &'a mut Client,
    route: String,
    body: Value,
    scope: String,
    operation_id: String,
}

impl writes::WriteAuthority for BackendWriteAuthority<'_> {
    async fn authorize(&mut self) -> HostResult<()> {
        let current = authorize(self.client, &self.route, &self.body).await?;
        if current["authorization_scope"] != self.scope.as_str()
            || current["operation_id"] != self.operation_id.as_str()
        {
            return Err(denied());
        }
        Ok(())
    }
}

async fn authorize(client: &mut Client, route: &str, body: &Value) -> HostResult<Value> {
    let response = client
        .request(Method::POST, route, Some(body.clone()))
        .await
        .map_err(|_| denied())?;
    if response["authorized"] != true {
        return Err(denied());
    }
    Ok(response)
}
