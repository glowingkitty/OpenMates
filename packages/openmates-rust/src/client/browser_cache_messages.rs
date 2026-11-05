//! Bounded authoritative incoming cache subsets.
#[path="browser_owned_message_read.rs"]
mod owned_read;
#[doc(hidden)]
pub use owned_read::BrowserProfileCacheReadiness;
#[doc(hidden)]
pub use owned_read::OwnedBrowserProfileCacheAbsence;
#[doc(hidden)]
pub use owned_read::{OriginalHintRefreshAdmission,OriginalHintRefreshBatch,OriginalHintRowSeed,OriginalHintRowMetadataAdmission,OriginalHintRowMetadataPublication,OriginalHintMetadataApplied,OriginalHintDraftInventoryPrerequisite,OriginalHintDraftInventoryTicket,UntrustedDraftInventoryPageData,UntrustedDraftInventoryRereadData,OwnedOriginalHintWindowPreparation,OwnedOriginalHintWindowCompletion,OriginalHintWindowBatch,OwnedBrowserReadDriver,OwnedBrowserReadStep,OwnedBrowserReadPhase,OwnedBrowserReadIO,OwnedBrowserReadPublication,OwnedBrowserMetadataContinuation,OwnedBrowserReadControl,OwnedBrowserMetadataPublication,OriginalHintRecoveryHandoff,OwnedBrowserReadTerminalObserver,OwnedBrowserReadTerminal,BrowserOriginalHintRecoveryDriver,BrowserOriginalHintRecoveryStep,BrowserOriginalHintRecoveryApply,BrowserOriginalHintRecoveryIo,BrowserOriginalHintRecoveryResume,BrowserOriginalHintRecoveryControl,BrowserOriginalHintRecoveryAdoption,BrowserOriginalHintRecoveryProgress,BrowserOriginalHintRecoveryPendingPersistence,BrowserOriginalHintRecoveryDeferred,BrowserOriginalHintRecoveryCheckpointPreparation,BrowserOriginalHintRecoveryCheckpointCrypto,BrowserOriginalHintRecoveryCheckpointWrite,BrowserOriginalHintRecoveryPersistenceFailure};
#[path="browser_cache_header.rs"]
mod header;
#[path="browser_assistant_candidate_policy.rs"]
mod candidate_policy;
#[path="browser_recovered_reply_policy.rs"]
pub(in crate::client) mod recovered_reply_policy;
#[path="browser_cache_replacement.rs"]
mod replacement;
pub use replacement::BrowserCandidateFailures;
use super::super::message_policy;
use super::*;
use crate::client::local_cached_read::wire;
// Rust-only, nonserializable and noncloneable. The original scope remains owned
// until the retained publication is discarded; no counts/JSON can construct it.
pub(crate) struct BrowserRetainedMessageCache {
    fence: Fence,
    monitor_context: Option<crate::client::monitor::BrowserMonitorReadContext>,
    owner: String,
    chat: String,
    data: RetainedData,
}
struct RetainedData {
    plan: Plain<Value>,
    readback: Plain<Value>,
    dispositions: Plain<Vec<Value>>,
    summary: Zeroizing<String>,
    key: Key,
}
impl BrowserRetainedMessageCache {
    pub(crate) fn ensure_current(&self, client: &Client) -> Result<()> {
        if let Some(context)=&self.monitor_context {context.ensure_current(client,&self.owner,&self.chat)?;}
        client.metadata_cache_check(&self.fence, &self.owner, &self.chat,
            BrowserMetadataCacheMode::PersistCurrent)
    }
}
// A borrowed, revalidated view never transfers ownership of ciphertext or key.
// Projection runs under the original fences both before and after the callback.
pub(crate) struct BrowserRetainedMessageReadback<'a> {
    token: &'a BrowserRetainedMessageCache,
    client: &'a Client,
}
impl BrowserRetainedMessageReadback<'_> {
    pub(crate) fn with_rows(&self, project: impl FnOnce(&Value, &[Value], &Key, &[Value]) -> Result<Plain<Value>>) -> Result<Plain<Value>> {
        self.token.ensure_current(self.client)?;
        let rows = self.token.data.readback["rows"].as_array().ok_or(Error::Protocol)?;
        let result = project(&self.token.data.readback["metadata"], rows,
            &self.token.data.key, &self.token.data.dispositions)?;
        self.token.ensure_current(self.client)?;
        Ok(result)
    }
    pub(crate) fn ensure_current(&self) -> Result<()> { self.token.ensure_current(self.client) }
}
const MESSAGE_FIELDS: &[&str] = &[
    "id",
    "message_id",
    "client_message_id",
    "chat_id",
    "created_at",
    "role",
    "status",
    "key_version",
    "has_thinking",
    "thinking_token_count",
    "queue_revision",
    "queue_mode",
    "queue_dispatch_status",
    "queue_dispatch_mode",
    "queue_dispatch_task_id",
    "encrypted_content",
    "encrypted_sender_name",
    "encrypted_category",
    "encrypted_model_name",
    "encrypted_thinking_content",
    "encrypted_thinking_signature",
    "encrypted_pii_mappings",
    "pending_encrypted_embed_bundle_v1",
    "pending_encrypted_turn_preflight_v1",
    "pending_turn_preflight_v1",
];
const ENCRYPTED: &[&str] = &[
    "encrypted_content",
    "encrypted_sender_name",
    "encrypted_category",
    "encrypted_model_name",
    "encrypted_thinking_content",
    "encrypted_thinking_signature",
    "encrypted_pii_mappings",
];
const CLEAR: &[&str] = &[
    "content",
    "sender_name",
    "category",
    "model_name",
    "thinking_content",
    "thinking_signature",
    "pii_mappings",
];
const WRITES: &[&str] = &[
    "encrypted_content",
    "encrypted_sender_name",
    "encrypted_category",
    "encrypted_model_name",
    "encrypted_thinking_content",
    "encrypted_thinking_signature",
    "encrypted_pii_mappings",
    "status",
    "key_version",
    "has_thinking",
    "thinking_token_count",
    "queue_revision",
];
fn unsupported(reason: &'static str) -> Error {
    Error::Unavailable {
        code: "browser_message_cache_subset_unsupported",
        reason,
    }
}
fn call_nonempty(row: &Value) -> Result<bool> {
    match row.get("call_persistence_v1") {
        None | Some(Value::Null) => Ok(false),
        Some(Value::Object(value)) => match value.get("entries") {
            None => Ok(false),
            Some(Value::Array(entries)) => Ok(!entries.is_empty()),
            _ => Err(unsupported(
                "MALFORMED_CALL_JOURNAL_REQUIRES_OWNED_RECOVERY",
            )),
        },
        _ => Err(unsupported(
            "MALFORMED_CALL_JOURNAL_REQUIRES_OWNED_RECOVERY",
        )),
    }
}
fn no_plaintext(row: &Value) -> bool {
    CLEAR
        .iter()
        .all(|field| row.get(*field).is_none_or(Value::is_null))
}
fn row_projection(row: &Value, chat: &str) -> Result<Plain<Value>> {
    if !row.is_object() || row["chat_id"].as_str() != Some(chat) {
        return Err(Error::Forbidden);
    }
    wire::storage_id(required(row, "message_id")?)?;
    for field in ["id", "client_message_id"] {
        if let Some(value) = row.get(field).filter(|v| !v.is_null()) {
            let value = value.as_str().ok_or(Error::Protocol)?;
            if !value.is_empty() {
                wire::storage_id(value)?;
            }
        }
    }
    safe_number(&row["created_at"])?;
    if !matches!(row["role"].as_str(), Some("user" | "assistant" | "system")) {
        return Err(unsupported("UNSUPPORTED_MESSAGE_ROLE"));
    }
    let mut out = Plain::new(json!({}));
    for field in MESSAGE_FIELDS {
        if let Some(value) = row.get(*field) {
            out[*field] = value.clone();
        }
    }
    for field in ENCRYPTED.iter().copied().chain([
        "status",
        "queue_mode",
        "queue_dispatch_status",
        "queue_dispatch_mode",
        "queue_dispatch_task_id",
        "pending_encrypted_embed_bundle_v1",
        "pending_encrypted_turn_preflight_v1",
    ]) {
        if out
            .get(field)
            .filter(|v| !v.is_null())
            .is_some_and(|v| !v.is_string())
        {
            return Err(Error::Protocol);
        }
    }
    for field in [
        "key_version",
        "thinking_token_count",
        "queue_revision",
        "pending_turn_preflight_v1",
    ] {
        if let Some(value) = out.get(field).filter(|v| !v.is_null()) {
            safe_number(value)?;
        }
    }
    if out
        .get("has_thinking")
        .filter(|v| !v.is_null())
        .is_some_and(|v| !v.is_boolean())
    {
        return Err(Error::Protocol);
    }
    Ok(out)
}
fn row_predicate(row: &Value, chat: &str) -> Result<Plain<Value>> {
    let fields = row_projection(row, chat)?;
    let nonempty = call_nonempty(row)?;
    Ok(Plain::new(
        json!({"fields":&*fields,"callJournalPresent":row.get("call_persistence_v1").is_some(),"callEntriesNonempty":nonempty,"callJournalShapeValid":true,"plaintextAbsentOrNull":no_plaintext(row),"largePayloadAbsent":row.get("large_payload").is_none_or(Value::is_null)}),
    ))
}
fn logical_local(row: &Value) -> Result<&str> {
    Ok(row["client_message_id"]
        .as_str()
        .filter(|v| !v.is_empty())
        .unwrap_or(required(row, "message_id")?))
}
fn incoming(raw: &Value, chat: &str) -> Result<Plain<Value>> {
    if raw
        .get("large_payload")
        .is_some_and(|value| !value.is_null())
    {
        return Err(unsupported(
            "EXACT_LARGE_PAYLOAD_CACHE_POLICY_REMAINS_REQUIRED",
        ));
    }
    if !no_plaintext(raw) {
        return Err(unsupported(
            "PLAINTEXT_OR_LOCAL_SEND_INPUT_REQUIRES_SEPARATE_POLICY",
        ));
    }
    for field in [
        "queue_mode",
        "queue_dispatch_status",
        "queue_dispatch_mode",
        "queue_dispatch_task_id",
    ] {
        if raw
            .get(field)
            .filter(|v| !v.is_null())
            .is_some_and(|v| v.as_str() != Some(""))
        {
            return Err(unsupported(
                "QUEUE_DISPATCH_RECEIPT_CONTEXT_REMAINS_REQUIRED",
            ));
        }
    }
    let physical = raw["message_id"]
        .as_str()
        .filter(|v| !v.is_empty())
        .or_else(|| raw["id"].as_str().filter(|v| !v.is_empty()))
        .ok_or(Error::Protocol)?;
    // Physical addressing follows maintained prepareMessagesForStorage; logical
    // client/message/id selection is independently validated, never normalized.
    let logical = crate::client::message_window::server_message_id(raw)?;
    let mut projected = Plain::new(json!({"chat_id":chat,"message_id":physical}));
    for field in MESSAGE_FIELDS {
        if let Some(value) = raw.get(*field) {
            projected[*field] = value.clone();
        }
    }
    projected["message_id"] = json!(physical);
    let status = match raw.get("status") {
        None | Some(Value::Null) => "delivered",
        Some(Value::String(value)) if value.is_empty() => "delivered",
        Some(Value::String(value)) => value,
        _ => return Err(Error::Protocol),
    };
    if !matches!(status, "synced" | "delivered") {
        return Err(unsupported(
            "LOCAL_SEND_TERMINAL_AND_RECOVERY_STATUS_REMAINS_REQUIRED",
        ));
    }
    projected["status"] = json!(status);
    for field in [
        "pending_encrypted_embed_bundle_v1",
        "pending_encrypted_turn_preflight_v1",
        "pending_turn_preflight_v1",
    ] {
        projected.as_object_mut().unwrap().remove(field);
    }
    let projected = row_projection(&projected, chat)?;
    if logical_local(&projected)? != logical {
        return Err(unsupported(
            "PHYSICAL_LOGICAL_ALIAS_REPAIR_REMAINS_REQUIRED",
        ));
    }
    Ok(projected)
}
fn decrypted_existing(row: &Value, key: &[u8; 32]) -> Result<Plain<Value>> {
    if !no_plaintext(row) {
        return Err(unsupported(
            "LEGACY_PLAINTEXT_STORAGE_REPAIR_REMAINS_REQUIRED",
        ));
    }
    let mut value = Plain::new(json!({}));
    for field in MESSAGE_FIELDS.iter().chain(CLEAR.iter()) {
        if let Some(v) = row.get(*field) {
            value[*field] = v.clone();
        }
    }
    for (cipher, clear) in ENCRYPTED.iter().zip(CLEAR.iter()) {
        if row
            .get(*cipher)
            .and_then(Value::as_str)
            .is_some_and(|v| !v.is_empty())
        {
            let plain = Zeroizing::new(sync::decrypt_optional(row, cipher, key)?);
            if plain.is_empty() {
                return Err(unsupported(
                    "EMPTY_OR_FAILED_DECRYPTION_CONTEXT_REMAINS_REQUIRED",
                ));
            }
            if *cipher == "encrypted_pii_mappings" {
                let _parsed = Plain::new(serde_json::from_str::<Value>(&plain)?);
            } else {
                value[*clear] = json!(&**plain);
            }
            // Maintained getMessage removes successful ciphers BEFORE hasNewEncryptedFields.
            value.as_object_mut().unwrap().remove(*cipher);
        }
    }
    Ok(value)
}
// The original read_message_page already authenticated content/sender/thinking
// and user PII from this same response. Validate only fields it did not decode;
// do not decrypt those already-validated source bodies a second time.
fn validate_remaining_incoming(row: &Value, key: &[u8; 32]) -> Result<()> {
    for field in [
        "encrypted_category",
        "encrypted_model_name",
        "encrypted_thinking_signature",
    ] {
        let _plain = Zeroizing::new(sync::decrypt_optional(row, field, key)?);
    }
    if row["role"] != "user"
        && row
            .get("encrypted_pii_mappings")
            .and_then(Value::as_str)
            .is_some_and(|v| !v.is_empty())
    {
        let plain = Zeroizing::new(sync::decrypt_optional(row, "encrypted_pii_mappings", key)?);
        let _parsed = Plain::new(serde_json::from_str::<Value>(&plain)?);
    }
    Ok(())
}
fn message_patch(old: &Value, new: &Value, chat: &str, key: &[u8; 32]) -> Result<Plain<Value>> {
    let before = row_projection(old, chat)?;
    if required(&before, "message_id")? != required(new, "message_id")?
        || logical_local(&before)? != logical_local(new)?
        || before["role"] != new["role"]
        || before["created_at"] != new["created_at"]
    {
        return Err(unsupported(
            "EXISTING_PHYSICAL_LOGICAL_IDENTITY_REPAIR_REMAINS_REQUIRED",
        ));
    }
    for field in ["id", "client_message_id"] {
        if let (Some(old), Some(new)) = (
            before.get(field).filter(|v| !v.is_null()),
            new.get(field).filter(|v| !v.is_null()),
        ) {
            if old != new {
                return Err(Error::Conflict);
            }
        }
    }
    let mut patch = Plain::new(json!({"messageId":before["message_id"],"set":{},"remove":[]}));
    // Raw same-ID transaction veto wins over any decrypted/status decision.
    if call_nonempty(old)? || message_policy::has_newer_stored_revision(&before, new)? {
        return Ok(patch);
    }
    if old
        .get("large_payload")
        .is_some_and(|value| !value.is_null())
    {
        return Err(unsupported(
            "EXACT_LARGE_PAYLOAD_CACHE_POLICY_REMAINS_REQUIRED",
        ));
    }
    if !matches!(before["status"].as_str(), Some("synced" | "delivered")) {
        return Err(unsupported(
            "LOCAL_SEND_TERMINAL_AND_RECOVERY_STATUS_REMAINS_REQUIRED",
        ));
    }
    for field in [
        "queue_mode",
        "queue_dispatch_status",
        "queue_dispatch_mode",
        "queue_dispatch_task_id",
    ] {
        if before
            .get(field)
            .filter(|v| !v.is_null())
            .is_some_and(|v| v.as_str() != Some(""))
        {
            return Err(unsupported(
                "QUEUE_DISPATCH_RECEIPT_CONTEXT_REMAINS_REQUIRED",
            ));
        }
    }
    if before.get("queue_revision").is_some_and(|v| !v.is_null())
        && new.get("queue_revision").is_none_or(Value::is_null)
    {
        return Err(unsupported("MISSING_AUTHORITATIVE_QUEUE_REVISION"));
    }
    if before["key_version"].as_u64().is_some()
        && new.get("key_version").is_some_and(Value::is_null)
    {
        return Err(unsupported("NULL_CANNOT_CLEAR_A_KNOWN_MESSAGE_KEY_VERSION"));
    }
    if before["key_version"]
        .as_u64()
        .zip(new["key_version"].as_u64())
        .is_some_and(|(old, new)| new < old)
    {
        return Err(unsupported("KEY_ROTATION_POLICY_REMAINS_REQUIRED"));
    }
    let semantic = decrypted_existing(old, key)?;
    // Validate incoming crypto, but compare the original raw incoming shape.
    validate_remaining_incoming(new, key)?;
    if !message_policy::should_update_message(&semantic, new)?
        && !message_policy::has_new_encrypted_fields(&semantic, new)?
    {
        return Ok(patch);
    }
    for field in WRITES {
        if let Some(value) = new.get(*field) {
            patch["set"][*field] = value.clone();
        }
    }
    if old
        .get("pending_encrypted_turn_preflight_v1")
        .is_some_and(Value::is_string)
    {
        patch["set"]["pending_turn_preflight_v1"] = json!(1);
    } else {
        patch["remove"] = json!(["pending_turn_preflight_v1"]);
    }
    Ok(patch)
}
fn packet_source_stamp(metadata: &Value, rows: &[Value]) -> Result<String> {
    if crate::client::monitor::cached_view::bounded_bytes(&(metadata, rows), 256 * 1024).is_none() {
        return Err(Error::Protocol);
    }
    let encoded = Zeroizing::new(serde_json::to_string(&(metadata, rows))?);
    Ok(sha256(&encoded))
}
impl Client {
    pub(in crate::client) fn browser_message_cache_metadata_guard(
        &self,
        row: &Value,
        id: &str,
    ) -> Result<()> {
        let owner = self
            .browser_authority
            .as_ref()
            .ok_or(Error::Forbidden)?
            .principal
            .as_str();
        self.metadata_cache_scope(owner, id, BrowserMetadataCacheMode::PersistCurrent)?;
        let _closed = projection(row, id, owner, false)?;
        Ok(())
    }
    async fn message_cache_io<F, Fut>(
        &self,
        fence: &Fence,
        owner: &str,
        chat: &str,
        plan: &Value,
        io: &mut F,
    ) -> Result<Plain<Value>>
    where
        F: FnMut(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
        let mut check=||self.metadata_cache_check(fence,owner,chat,BrowserMetadataCacheMode::PersistCurrent);
        execute_message_cache_io(plan,&mut check,io).await
    }
    /// Explicit one existing bounded read, then same-IDB CAS for existing physical
    /// rows. Never a background read, insert, full history or native durability ACK.
    pub async fn browser_authoritative_message_cache_json<F, Fut>(
        &mut self,
        owner: &str,
        chat: &str,
        options: crate::client::message_window::MessageWindowOptions,
        host_scope: BrowserMetadataCacheScope,
        include_private_output: bool,
        mut io: F,
    ) -> Result<String>
    where
        F: FnMut(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
        let token = self.browser_prepare_retained_message_cache(owner, chat, options,
            host_scope, include_private_output, io).await?;
        token.ensure_current(self)?;
        let mut output = Zeroizing::new(token.data.summary.to_string());
        local_json::validate(&output)?;
        token.ensure_current(self)?;
        Ok(std::mem::take(&mut *output))
    }
    pub(crate) async fn browser_prepare_retained_message_cache<F, Fut>(
        &mut self, owner: &str, chat: &str,
        options: crate::client::message_window::MessageWindowOptions,
        host_scope: BrowserMetadataCacheScope, include_private_output: bool, mut io: F,
    ) -> Result<BrowserRetainedMessageCache>
    where F: FnMut(String) -> Fut, Fut: Future<Output = Result<String>>,
    {
        self.browser_prepare_message_cache_mode(owner,chat,options,host_scope,include_private_output,false,false,None,io).await
    }
    /// Additional incoming-user insertion subset. Assistant cross-ID duplicate
    /// policy and missing chat-header insertion remain explicit required work.
    pub(crate) async fn browser_prepare_retained_user_message_cache<F,Fut>(
        &mut self,owner:&str,chat:&str,
        options:crate::client::message_window::MessageWindowOptions,
        host_scope:BrowserMetadataCacheScope,include_private_output:bool,io:F,
    )->Result<BrowserRetainedMessageCache>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        self.browser_prepare_message_cache_mode(owner,chat,options,host_scope,include_private_output,true,false,None,io).await
    }
    /// Missing incoming assistant insertion only when the explicit atomic
    /// no-cross-ID-cipher-duplicate predicate holds. Matching candidates refuse.
    pub(crate) async fn browser_prepare_retained_incoming_message_cache<F,Fut>(
        &mut self,owner:&str,chat:&str,
        options:crate::client::message_window::MessageWindowOptions,
        host_scope:BrowserMetadataCacheScope,include_private_output:bool,io:F,
    )->Result<BrowserRetainedMessageCache>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        self.browser_prepare_message_cache_mode(owner,chat,options,host_scope,include_private_output,true,true,None,io).await
    }
    /// Exact metadata-only header defaults, with an explicit captured clock.
    /// Server messages_v is inventory only; content coverage remains unknown.
    pub(crate) async fn browser_prepare_retained_cold_message_cache<F,Fut>(
        &mut self,owner:&str,chat:&str,
        options:crate::client::message_window::MessageWindowOptions,
        host_scope:BrowserMetadataCacheScope,now_seconds:u64,include_private_output:bool,io:F,
    )->Result<BrowserRetainedMessageCache>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        if now_seconds>MAX_SAFE {return Err(Error::Protocol)}
        self.browser_prepare_message_cache_mode(owner,chat,options,host_scope,include_private_output,true,true,Some(now_seconds),io).await
    }
    async fn browser_prepare_message_cache_mode<F,Fut>(
        &mut self,owner:&str,chat:&str,
        options:crate::client::message_window::MessageWindowOptions,
        host_scope:BrowserMetadataCacheScope,include_private_output:bool,
        allow_user_insert:bool,allow_assistant_insert:bool,header_clock:Option<u64>,mut io:F,
    )->Result<BrowserRetainedMessageCache>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        if !include_private_output {
            return Err(Error::Invalid(
                "Explicit private output consent is required.",
            ));
        }
        if host_scope.lifecycle_generation == 0
            || host_scope.lifecycle_generation > MAX_SAFE
            || host_scope.workspace_epoch > MAX_SAFE
        {
            return Err(Error::Protocol);
        }
        self.metadata_cache_scope(owner, chat, BrowserMetadataCacheMode::PersistCurrent)?;
        self.verify_private_operation()?;
        let fence = Fence {
            parent: self.operation_parent.clone(),
            private_gate: self.options.private_operation_gate.clone(),
            scope: AsyncCryptoScope::begin(self)?,
            epoch: self.fresh_auth.operation_epoch(),
            binding: Zeroizing::new(self.fresh_auth_binding()?),
            source_stamp: source_stamp(self, chat)?,
            revision: self.credential_revision,
        };
        self.metadata_cache_check(
            &fence,
            owner,
            chat,
            BrowserMetadataCacheMode::PersistCurrent,
        )?;
        let mut page = Plain::new(self.read_browser_cache_message_page(chat, options).await?);
        self.metadata_cache_check(
            &fence,
            owner,
            chat,
            BrowserMetadataCacheMode::PersistCurrent,
        )?;
        let raw = page.incoming.take().ok_or(Error::Protocol)?;
        let data = self.cache_browser_incoming_page_retained(owner, chat, host_scope, &fence, raw, allow_user_insert, allow_assistant_insert, header_clock, &mut io).await?;
        self.metadata_cache_check(&fence, owner, chat, BrowserMetadataCacheMode::PersistCurrent)?;
        Ok(BrowserRetainedMessageCache { fence, monitor_context:None, owner: owner.into(), chat: chat.into(), data })
    }
    pub(in crate::client) fn browser_apply_owned_metadata_transition(&self,token:&mut BrowserRetainedMessageCache,transition:BrowserMetadataOwnedTransition)->Result<()> {
        token.ensure_current(self)?;
        let after=transition.consume(self,&token.owner,&token.chat,&token.data.readback["metadata"])?;
        let projected=projection(&after,&token.chat,&token.owner,true)?;
        // Advance ONLY the exact physical header through our proven own CAS.
        // Original monitor/key/request fences and every expected message row stay owned.
        token.data.plan["expectedMetadata"]=(*projected).clone();
        token.data.readback["metadata"]=(*after).clone();
        token.ensure_current(self)
    }
    pub(crate) async fn browser_revalidate_retained_message_cache<'a, F, Fut>(
        &'a self, token: &'a BrowserRetainedMessageCache, io: &mut F,
    ) -> Result<BrowserRetainedMessageReadback<'a>>
    where F: FnMut(String) -> Fut, Fut: Future<Output = Result<String>>,
    {
        token.ensure_current(self)?;
        let actual = self.message_cache_io(&token.fence, &token.owner, &token.chat,
            &token.data.plan, io).await?;
        // Full physical rows, not only policy predicates: any post-commit local
        // journal, extension, cipher or alias mutation invalidates this token.
        if !actual["before"].is_null()
            || actual["metadata"] != token.data.readback["metadata"]
            || actual["rows"] != token.data.readback["rows"] {
            return Err(Error::Conflict);
        }
        token.ensure_current(self)?;
        Ok(BrowserRetainedMessageReadback { token, client: self })
    }
    #[cfg(test)]
    async fn cache_browser_incoming_page<F, Fut>(
        &self, owner: &str, chat: &str, host_scope: BrowserMetadataCacheScope,
        fence: &Fence, raw: crate::client::message_window::BrowserIncomingMessagePage,
        io: &mut F,
    ) -> Result<String>
    where F: FnMut(String) -> Fut, Fut: Future<Output = Result<String>>,
    {
        let data = self.cache_browser_incoming_page_retained(owner, chat, host_scope, fence, raw, false, false, None, io).await?;
        self.metadata_cache_check(fence, owner, chat, BrowserMetadataCacheMode::PersistCurrent)?;
        Ok(data.summary.to_string())
    }
    async fn cache_browser_incoming_page_retained<F, Fut>(
        &self,
        owner: &str,
        chat: &str,
        host_scope: BrowserMetadataCacheScope,
        fence: &Fence,
        raw: crate::client::message_window::BrowserIncomingMessagePage,
        allow_user_insert: bool,
        allow_assistant_insert: bool,
        header_clock: Option<u64>,
        io: &mut F,
    ) -> Result<RetainedData>
    where
        F: FnMut(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
        let mut check=||self.metadata_cache_check(fence,owner,chat,BrowserMetadataCacheMode::PersistCurrent);
        let unwrap_key=|normal_meta:Plain<Value>|async move {
            let master=self.master_capability()?;
            self.chat_key_with_capability_from(&normal_meta,&master,&[]).await
        };
        drive_incoming_cache_policy(owner,chat,host_scope,raw,allow_user_insert,
            allow_assistant_insert,header_clock,&mut check,unwrap_key,io).await
    }

}
async fn execute_message_cache_io<F,Fut,C>(plan:&Value,check:&mut C,io:&mut F)->Result<Plain<Value>>
where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>>,C:FnMut()->Result<()> {
    execute_message_cache_io_budget(plan,check,io,CacheIoBudget::Metadata).await
}
async fn execute_message_cache_io_budget<F,Fut,C>(plan:&Value,check:&mut C,io:&mut F,budget:CacheIoBudget)->Result<Plain<Value>>
where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>>,C:FnMut()->Result<()> {
        check()?;
        let encoded = Zeroizing::new(serde_json::to_string(plan)?);
        budget.validate(&encoded)?;
        let result = io(encoded.to_string()).await.map(Zeroizing::new);
        check()?;
        let encoded = result?;
        budget.validate(&encoded)?;
        let value = Plain::new(serde_json::from_str::<Value>(&encoded)?);
        if !closed(
            &value,
            &[
                "version",
                "kind",
                "operationId",
                "databaseVersion",
                "transactionCommitted",
                "credentialAcknowledged",
                "crossDatabaseAssociationProven",
                "metadata",
                "rows",
                "before",
            ],
        ) || value["version"] != 1
            || value["kind"] != plan["kind"]
            || value["operationId"] != plan["operationId"]
            || value["transactionCommitted"] != true
            || value["credentialAcknowledged"] != false
            || value["crossDatabaseAssociationProven"] != false
            || safe_number(&value["databaseVersion"])? == 0
        {
            return Err(Error::Protocol);
        }
        if plan["databaseVersion"]
            .as_u64()
            .is_some_and(|v| value["databaseVersion"].as_u64() != Some(v))
        {
            return Err(Error::Conflict);
        }
        if value["rows"].as_array().ok_or(Error::Protocol)?.len()
            != plan["messageIds"].as_array().ok_or(Error::Protocol)?.len()
        {
            return Err(Error::Protocol);
        }
        Ok(value)
}
async fn drive_incoming_cache_policy<F,Fut,C,U,UFut>(
    owner:&str,chat:&str,host_scope:BrowserMetadataCacheScope,
    raw:crate::client::message_window::BrowserIncomingMessagePage,
    allow_user_insert:bool,allow_assistant_insert:bool,header_clock:Option<u64>,
    check:&mut C,mut unwrap_key:U,io:&mut F,
)->Result<RetainedData>
where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>>,
    C:FnMut()->Result<()>,U:FnMut(Plain<Value>)->UFut,UFut:Future<Output=Result<Key>> {
    drive_incoming_cache_policy_budget(owner,chat,host_scope,raw,allow_user_insert,allow_assistant_insert,header_clock,check,unwrap_key,io,CacheIoBudget::Metadata).await
}
async fn drive_incoming_cache_policy_budget<F,Fut,C,U,UFut>(
    owner:&str,chat:&str,host_scope:BrowserMetadataCacheScope,
    raw:crate::client::message_window::BrowserIncomingMessagePage,
    allow_user_insert:bool,allow_assistant_insert:bool,header_clock:Option<u64>,
    check:&mut C,mut unwrap_key:U,io:&mut F,budget:CacheIoBudget,
)->Result<RetainedData>
where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>>,
    C:FnMut()->Result<()>,U:FnMut(Plain<Value>)->UFut,UFut:Future<Output=Result<Key>> {
        check()?;
        let initial_source = packet_source_stamp(&raw.metadata, &raw.messages)?;
        let source_meta = normalized(&raw.metadata, chat, owner, false)?;
        let mut rows = Plain::new(Vec::<Value>::new());
        for row in raw.messages.iter() {
            rows.push(incoming(row, chat)?.into_inner());
        }
        if rows.is_empty() && header_clock.is_none() {
            return Err(unsupported(
                "EMPTY_AND_NEW_ROW_INSERTION_SUBSET_REMAINS_REQUIRED",
            ));
        }
        if rows.len() > crate::client::message_window::MAX_MESSAGES {
            return Err(Error::Protocol);
        }
        rows.sort_by(|a, b| wire::idb_key_cmp(text(a, "message_id"), text(b, "message_id")));
        let ids = rows
            .iter()
            .map(|row| required(row, "message_id").map(str::to_owned))
            .collect::<Result<Vec<_>>>()?;
        if ids.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(Error::Protocol);
        }
        let operation = uuid::Uuid::new_v4().to_string();
        let mut plan = Plain::new(
            json!({"version":1,"kind":if header_clock.is_some() {"capture_cold_incoming_insert"} else if allow_assistant_insert {"capture_incoming_insert"} else if allow_user_insert {"capture_user_insert"} else {"capture"},"operationId":operation,"scope":host_scope,"owner":owner,"chatId":chat,"database":"chats_db","stores":["chats","messages"],"databaseVersion":null,"messageIds":ids,"metadataFields":PREDICATES,"messageFields":MESSAGE_FIELDS,"expectedMetadata":null,"expectedRows":null,"patches":null}),
        );
        if allow_assistant_insert {
            plan["assistantDuplicateAbsence"]=json!(rows.iter().filter(|row| row["role"]=="assistant").map(|row|
                json!({"messageId":row["message_id"],"encryptedContent":row["encrypted_content"],"createdAt":row["created_at"],"role":"assistant","timeThresholdExclusive":60})).collect::<Vec<_>>());
        }
        let proposed_header=if let Some(now)=header_clock {
            let value=header::build(&raw.metadata,None,now)?;
            header::validate_create(&value,chat,owner)?;
            if value["is_anonymous"]==true || value["is_shared"]==true {return Err(unsupported("ANONYMOUS_SHARED_HEADER_POLICY_REMAINS_REQUIRED"));}
            // Source wrapping/owner/opaque capability was authenticated by the
            // SAME page read. Reuse its derived key, never unwrap/export again.
            for field in super::CIPHERS {let _plain=Zeroizing::new(sync::decrypt_optional(&value,field,&raw.key)?);}
            Some(value)
        } else {None};
        if let Some(value)=&proposed_header {plan["metadataInsert"]=json!(&**value);}
        let capture = execute_message_cache_io_budget(&plan,check,io,budget).await?;
        if !capture["before"].is_null() {
            return Err(Error::Protocol);
        }
        let header_missing=capture["metadata"].is_null();
        let effective=if header_missing {&**proposed_header.as_ref().ok_or(unsupported("MISSING_CHAT_HEADER_INSERTION_REQUIRES_EXPLICIT_MODE"))?} else {&capture["metadata"]};
        let old_meta = projection(effective, chat, owner, true)?;
        check()?;
        let key=if header_missing {raw.key.clone()} else {
            unwrap_key(normalized(&old_meta,chat,owner,false)?).await?
        };
        check()?;
        if key.as_ref() != raw.key.as_ref() {
            return Err(unsupported(
                "KEY_ROTATION_AND_WRAPPER_POLICY_REMAINS_REQUIRED",
            ));
        }
        // Same original metadata/key response; no normalized omission grants a clear.
        if required(&source_meta, "id")? != chat {
            return Err(Error::Forbidden);
        }
        let mut expected = Plain::new(Vec::<Value>::new());
        let mut patches = Plain::new(Vec::<Value>::new());
        let mut updated = 0usize;
        let mut inserted = 0usize;
        let mut dispositions = Plain::new(Vec::new());
        for (offset, new) in rows.iter().enumerate() {
            let old = &capture["rows"][offset];
            if old.is_null() {
                if !allow_user_insert { return Err(unsupported("NEW_AUTHORITATIVE_ROW_INSERTION_REMAINS_REQUIRED")); }
                // Maintained isContentDuplicate immediately returns false for
                // different physical user IDs. Do not extend this to assistants.
                if new["role"] != "user" && !(allow_assistant_insert && new["role"]=="assistant") { return Err(unsupported("ASSISTANT_CROSS_ID_DUPLICATE_POLICY_REMAINS_REQUIRED")); }
                validate_remaining_incoming(new,&key)?;
                let mut insert=Plain::new(json!({}));
                for field in ["id","message_id","client_message_id","chat_id","created_at","role"].iter().chain(WRITES.iter()) {
                    if let Some(value)=new.get(*field) { insert[*field]=value.clone(); }
                }
                row_projection(&insert,chat)?;
                expected.push(Value::Null);
                patches.push(json!({"messageId":new["message_id"],"insert":&*insert}));
                dispositions.push(json!({"messageId":new["message_id"],"disposition":"inserted","canonicalIncomingDurablyAcknowledged":false}));
                inserted+=1; updated+=1; continue;
            }
            if old["message_id"] != plan["messageIds"][offset] {
                return Err(Error::Conflict);
            }
            expected.push(row_predicate(old, chat)?.into_inner());
            let patch = message_patch(old, new, chat, &key)?;
            if !patch["set"].as_object().unwrap().is_empty()
                || !patch["remove"].as_array().unwrap().is_empty()
            {
                updated += 1;
            }
            dispositions.push(json!({"messageId":old["message_id"],
                "disposition":if patch["set"].as_object().unwrap().is_empty() && patch["remove"].as_array().unwrap().is_empty() {"retained"} else {"merged"},
                "canonicalIncomingDurablyAcknowledged":false}));
            patches.push(patch.into_inner());
        }
        plan["kind"] = json!(if header_clock.is_some() {"compare_and_patch_cold_incoming_insert"} else if allow_assistant_insert {"compare_and_patch_incoming_insert"} else if allow_user_insert {"compare_and_patch_user_insert"} else {"compare_and_patch"});
        plan["databaseVersion"] = capture["databaseVersion"].clone();
        plan["expectedMetadata"] = if header_missing {Value::Null} else {old_meta.clone()};
        plan["expectedRows"] = json!(&*expected);
        plan["patches"] = json!(&*patches);
        let committed = execute_message_cache_io_budget(&plan,check,io,budget).await?;
        if header_missing && committed["metadata"]!=**proposed_header.as_ref().ok_or(Error::Protocol)? {return Err(Error::Protocol);}
        if *projection(&committed["metadata"], chat, owner, true)? != *old_meta {
            return Err(Error::Conflict);
        }
        let before = committed["before"].as_array().ok_or(Error::Protocol)?;
        if before.len() != rows.len() {
            return Err(Error::Protocol);
        }
        let mut after_predicates = Plain::new(Vec::<Value>::new());
        for (index, old) in before.iter().enumerate() {
            if old.is_null() {
                if !expected[index].is_null() || !allow_user_insert { return Err(Error::Conflict); }
                let after=Plain::new(patches[index]["insert"].clone());
                if *after != committed["rows"][index] { return Err(Error::Protocol); }
                after_predicates.push(row_predicate(&after,chat)?.into_inner());
                continue;
            }
            if expected[index].is_null() || *row_predicate(old, chat)? != expected[index] {
                return Err(Error::Conflict);
            }
            let mut after = Plain::new(old.clone());
            for (field, value) in patches[index]["set"].as_object().ok_or(Error::Protocol)? {
                after[field] = value.clone();
            }
            for field in patches[index]["remove"].as_array().ok_or(Error::Protocol)? {
                after
                    .as_object_mut()
                    .ok_or(Error::Protocol)?
                    .remove(field.as_str().ok_or(Error::Protocol)?);
            }
            if *after != committed["rows"][index] {
                return Err(Error::Protocol);
            }
            after_predicates.push(row_predicate(&after, chat)?.into_inner());
        }
        plan["kind"] = json!(if rows.is_empty(){"readback_metadata_only"}else{"readback"});
        plan.as_object_mut().ok_or(Error::Protocol)?.remove("assistantDuplicateAbsence");
        plan.as_object_mut().ok_or(Error::Protocol)?.remove("metadataInsert");
        plan["expectedMetadata"]=old_meta.clone();
        plan["expectedRows"] = json!(&*after_predicates);
        plan["patches"] = Value::Null;
        let readback = execute_message_cache_io_budget(&plan,check,io,budget).await?;
        if !readback["before"].is_null()
            || *projection(&readback["metadata"], chat, owner, true)? != *old_meta
        {
            return Err(Error::Conflict);
        }
        for (index, row) in readback["rows"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .enumerate()
        {
            if *row_predicate(row, chat)? != after_predicates[index] {
                return Err(Error::Conflict);
            }
            dispositions[index]["incomingSuppliedWriteFieldsMatch"] = json!(WRITES.iter()
                .filter_map(|field| rows[index].get(*field).map(|value| (*field, value)))
                .all(|(field, value)| row.get(field) == Some(value)));
        }
        if packet_source_stamp(&raw.metadata, &raw.messages)? != initial_source {
            return Err(Error::Cancelled);
        }
        let mut output=Zeroizing::new(json!({"source":"browser_message_cache","cached":true,"fresh":false,"readOnly":true,"historyComplete":false,"rowsConsidered":rows.len(),"rowsUpdated":updated,"rowsRetained":rows.len()-updated,"messagesVersionAdvanced":false,"windowCoverageChanged":false,"credentialAcknowledged":false,"nativeDurabilityAcknowledged":false}).to_string());
        if allow_user_insert {
            let mut value=Plain::new(serde_json::from_str::<Value>(&output)?);
            value["rowsInserted"]=json!(inserted);
            if header_clock.is_some(){value["metadataHeaderInserted"]=json!(header_missing);value["contentCoverage"]=json!("unknown");value["messagesVersionMeaning"]=json!("metadata_inventory_only");}
            *output=serde_json::to_string(&*value)?;
        }
        local_json::validate(&output)?;
        check()?;
        Ok(RetainedData { plan, readback, dispositions, summary: output, key: raw.key })
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "browser_cache_messages_tests.rs"]
mod tests;

#[cfg(target_arch="wasm32")]
#[doc(hidden)]
pub use owned_read::{BrowserOriginalHintRecoveryCheckpointReadiness,BrowserOriginalHintRecoveryCheckpointRead,BrowserOriginalHintRecoveryCheckpointReadResult,BrowserOriginalHintRecoveryCheckpointNativeWrite,BrowserOriginalHintRecoveryCheckpointNativeWriteResult,BrowserOriginalHintRecoveryCheckpointReadbackCrypto,BrowserOriginalHintRecoveryCheckpointVerified,BrowserOriginalHintRecoveryCheckpointDurable};

#[cfg(target_arch="wasm32")]
#[doc(hidden)]
pub use owned_read::OriginalPhysicalDraftInventory;

#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
#[path="browser_metadata_bootstrap.rs"]
mod metadata_bootstrap;
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use metadata_bootstrap::{BrowserMetadataBootstrap,MetadataOpaqueStored,MetadataNativeIoTicket,close_native_metadata_io_only,CapturedInitialSyncStore,BoundInitialSyncStore,StartupMetadataStoreDriver,StartupMetadataStored,StartupMetadataNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use metadata_bootstrap::{BrowserMetadataRecoveryFinalize,BrowserMetadataRecoveryLocalStored,BrowserMetadataRecoveryNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use metadata_bootstrap::{BrowserMainMetadataStore,BrowserMainMetadataStored,BrowserMainMetadataNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use metadata_bootstrap::{BrowserRecoveredReplyStore,BrowserRecoveredReplyControl,BrowserRecoveredReplyStored,BrowserRecoveredReplyNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use metadata_bootstrap::{BrowserMainCodeEmbedStore,BrowserMainCodeEmbedControl,BrowserMainCodeEmbedStored,BrowserMainCodeEmbedNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(in crate::client) use metadata_bootstrap::MetadataRecoveryPhysicalProof;

#[cfg(any(test,all(target_arch="wasm32",feature="browser-metadata-prototype")))]
#[path="browser_metadata_bootstrap_policy.rs"]
mod metadata_bootstrap_policy;
