//! Existing Personal browser draft IO. Encryption/version/tombstone/queue policy
//! stays in shared Rust. JS executes closed same-store CAS plans only. No key
//! export/native fake Session/server-auth upgrade or new persistence schema.
use super::*;
use super::{
    credentials::MasterBinding,
    owned_operation::{ActiveOwnedClient, OwnedOperationScope},
};
use std::future::Future;
use zeroize::Zeroizing;
const MAX_SAFE: u64 = 9_007_199_254_740_991;
const MAX_PACKET: usize = 2 * 1024 * 1024;
pub(super) fn validate_draft_markdown(markdown: &str) -> Result<()> {
    if markdown.trim().is_empty() || markdown.len() > 1_000_000 {
        return Err(Error::Invalid("Enter a nonempty draft of at most 1 MB."));
    }
    Ok(())
}
const FIELDS: &[&str] = &[
    "chat_id",
    "id",
    "user_id",
    "owner_id",
    "team_id",
    "hashed_team_id",
    "chat_visibility",
    "encrypted_chat_key",
    "key_version",
    "key_fingerprint",
    "messages_v",
    "draft_v",
    "cleared_draft_v",
    "encrypted_draft_md",
    "encrypted_draft_preview",
    "updated_at",
];
/// Sealed, ORIGINAL local-profile draft purpose only. No serialization, Clone,
/// constructor or caller boolean can grant server/send or generic read access.
pub struct BrowserDraftAdmission {
    owner: String,
    chat: String,
    generation: u64,
    binding: MasterBinding,
    credential_context: String,
}
impl BrowserDraftAdmission {
    pub(in crate::client) fn check(&self, c: &Client) -> Result<()> {
        c.validate_browser_draft_local(&self.owner, &self.chat)?;
        if c.generation != self.generation || credential_context(c)? != self.credential_context {
            return Err(Error::Cancelled);
        }
        self.binding.check(c)
    }
}
fn credential_context(c: &Client) -> Result<String> {
    let s = c.require_credentials()?;
    Ok(sha256(&serde_json::to_string(&(
        s.api_url,
        s.session_id,
        s.hashed_email,
        s.active_team_id,
    ))?))
}
fn safe(v: &Value) -> Result<u64> {
    v.as_u64().filter(|n| *n <= MAX_SAFE).ok_or(Error::Protocol)
}
fn optional_u64(v: &Value) -> Result<u64> {
    if v.is_null() { Ok(0) } else { safe(v) }
}
fn projection(row: &Value) -> Result<Value> {
    let o = row.as_object().ok_or(Error::Protocol)?;
    Ok(Value::Object(FIELDS.iter().map(|field|((*field).into(),json!({"present":o.contains_key(*field),"value":o.get(*field).unwrap_or(&Value::Null)}))).collect()))
}
fn decoded_projection(v: &Value) -> Result<Value> {
    let o = v.as_object().ok_or(Error::Protocol)?;
    if o.len() != FIELDS.len() || FIELDS.iter().any(|f| !o.contains_key(*f)) {
        return Err(Error::Protocol);
    }
    let mut row = serde_json::Map::new();
    for field in FIELDS {
        let item = &v[*field];
        let p = item.as_object().ok_or(Error::Protocol)?;
        if p.len() != 2 || !p.contains_key("present") || !p.contains_key("value") {
            return Err(Error::Protocol);
        }
        match item["present"].as_bool() {
            Some(true) => {
                row.insert((*field).into(), item["value"].clone());
            }
            Some(false) if item["value"].is_null() => {}
            _ => return Err(Error::Protocol),
        }
    }
    Ok(Value::Object(row))
}
fn packet(encoded: String, kind: &str, operation: &str, id: &str) -> Result<Value> {
    if encoded.len() > MAX_PACKET {
        return Err(Error::Protocol);
    }
    let v: Value = serde_json::from_str(&encoded)?;
    let o = v.as_object().ok_or(Error::Protocol)?;
    if o.len() != 8
        || ![
            "version",
            "kind",
            "operationId",
            "chatId",
            "row",
            "queueMaximum",
            "change",
            "transactionCommitted",
        ]
        .iter()
        .all(|f| o.contains_key(*f))
        || v["version"] != 1
        || v["kind"] != kind
        || v["operationId"] != operation
        || v["chatId"] != id
        || v["transactionCommitted"] != true
    {
        return Err(Error::Protocol);
    }
    safe(&v["queueMaximum"])?;
    Ok(v)
}
fn receipt(id: &str, version: u64, synced: bool) -> Result<Zeroizing<String>> {
    Ok(Zeroizing::new(serde_json::to_string(
        &json!({"source":"browser_rust_draft","chatId":id,"version":version,"localSaved":true,"remoteSynced":synced,"pending":!synced,"credentialAcknowledged":false}),
    )?))
}
/// Actual local write + readback and exact encrypted queued intent. Only this
/// ORIGINAL resource can attempt remote synchronization or remove its intent.
pub struct BrowserDraftPublication {
    admission: BrowserDraftAdmission,
    operation: OwnedOperationScope,
    output: Zeroizing<String>,
}
impl BrowserDraftPublication {
    pub fn take(self, c: &Client) -> Result<Zeroizing<String>> {
        self.admission.check(c)?;
        self.operation.check(c)?;
        Ok(self.output)
    }
}
pub struct BrowserDraftControl {
    child: CancellationToken,
}
impl BrowserDraftControl {
    pub fn cancel(&self) {
        self.child.cancel();
    }
}
pub struct BrowserDraftWrite {
    admission: BrowserDraftAdmission,
    operation: OwnedOperationScope,
    operation_id: String,
    scope: Value,
    after: Value,
    patch: Value,
    change: Value,
    maximum: u64,
    version: u64,
}
impl BrowserDraftWrite {
    fn check(&self, c: &Client) -> Result<()> {
        self.admission.check(c)?;
        self.operation.check(c)
    }
    pub fn local_result(&self, c: &Client) -> Result<Zeroizing<String>> {
        self.check(c)?;
        receipt(&self.admission.chat, self.version, false)
    }
    fn publication(self, c: &Client, synced: bool) -> Result<BrowserDraftPublication> {
        self.check(c)?;
        let output = receipt(&self.admission.chat, self.version, synced)?;
        Ok(BrowserDraftPublication {
            admission: self.admission,
            operation: self.operation,
            output,
        })
    }
    pub fn control(&self) -> BrowserDraftControl {
        BrowserDraftControl {
            child: self.operation.child(),
        }
    }
    pub fn cancel(&self) {
        self.operation.child().cancel();
    }
    fn plan(&self, kind: &str) -> Value {
        json!({"version":1,"kind":kind,"operationId":self.operation_id,"owner":self.admission.owner,"chatId":self.admission.chat,"scope":self.scope,"expected":self.after,"queueMaximum":self.maximum,"patch":self.patch,"change":self.change})
    }
    pub async fn synchronize<F, Fut>(self, c: &mut Client, io: F) -> Result<BrowserDraftPublication>
    where
        F: Fn(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
        self.check(c)?;
        let mut active = ActiveOwnedClient::enter(c, &self.operation)?;
        let c = &mut *active;
        // A genuine local-profile capability never becomes server authority. Its
        // encrypted intent stays durable for later ORIGINAL authenticated recovery.
        if c.is_local_browser_profile() {
            return self.publication(c, false);
        }
        c.require_canonical_read_profile()?;
        let mut socket = match c.socket().await {
            Ok(socket) => socket,
            Err(Error::Offline) => {
                self.check(c)?;
                return self.publication(c, false);
            }
            Err(error) => return Err(error),
        };
        self.check(c)?;
        transport::send(&mut socket,"update_draft",json!({"chat_id":self.admission.chat,"encrypted_draft_md":self.patch["encrypted_draft_md"],"encrypted_draft_preview":self.patch["encrypted_draft_preview"],"draft_v":self.version})).await?;
        // Drain the already admitted mutation's receipt. Cancellation fences release;
        // it never deletes the durable encrypted intent on an uncertain transport.
        let result = transport::wait(
            &mut socket,
            "draft_update_receipt",
            "chat_id",
            &self.admission.chat,
        )
        .await;
        let _ = socket.close(None).await;
        self.check(c)?;
        let r = match result {
            Ok(r) => r,
            Err(Error::Offline) => return self.publication(c, false),
            Err(error) => return Err(error),
        };
        if r["success"] != true
            || r["superseded"] == true
            || r["draft_v"].as_u64() != Some(self.version)
        {
            return Err(Error::Conflict);
        }
        if ["team_id", "hashed_team_id"]
            .iter()
            .any(|field| r.get(*field).is_some_and(|v| !v.is_null() && v != ""))
        {
            return Err(Error::Forbidden);
        }
        let output = io(serde_json::to_string(&self.plan("ack_draft"))?).await?;
        self.check(c)?;
        let stored = packet(
            output,
            "ack_draft",
            &self.operation_id,
            &self.admission.chat,
        )?;
        if stored["row"] != self.after || !stored["change"].is_null() {
            return Err(Error::Conflict);
        }
        self.check(c)?;
        self.publication(c, true)
    }
}
impl Client {
    fn validate_browser_draft_local(&self, owner: &str, id: &str) -> Result<()> {
        self.require_credentials()?;
        self.verify_private_operation()?;
        if !uuid::Uuid::parse_str(owner).is_ok_and(|x| x.to_string() == owner)
            || !uuid::Uuid::parse_str(id).is_ok_and(|x| x.to_string() == id)
            || self.user["id"].as_str() != Some(owner)
            || !self
                .browser_authority
                .as_ref()
                .is_some_and(|a| a.principal == owner)
            || self.browser_credentials.is_none()
            || self.team()?.is_some()
            || self.is_ephemeral_chat(id)
        {
            return Err(Error::Forbidden);
        }
        if self.operation_parent.is_cancelled()
            || !self.task_watch_authority.cached_chat_allowed(id)
        {
            return Err(Error::Cancelled);
        }
        self.master_binding()?.ensure_resource_current()?;
        Ok(())
    }
    pub fn prepare_browser_draft_admission(
        &self,
        owner: &str,
        id: &str,
    ) -> Result<BrowserDraftAdmission> {
        self.validate_browser_draft_local(owner, id)?;
        Ok(BrowserDraftAdmission {
            owner: owner.into(),
            chat: id.into(),
            generation: self.generation,
            binding: self.master_binding()?,
            credential_context: credential_context(self)?,
        })
    }
    /// The same ciphertext helper is called by the ordinary native save_draft
    /// wrapper; wire framing and 200-scalar preview cannot drift by platform.
    pub(super) async fn encrypt_draft_fields(
        &self,
        markdown: &str,
        scope: &sync_capability::AsyncCryptoScope,
    ) -> Result<(String, String)> {
        let master = self.master_capability()?;
        let encrypted = master.encrypt_server_bytes(markdown.as_bytes()).await?;
        scope.check(self)?;
        let preview = Zeroizing::new(markdown.chars().take(200).collect::<String>());
        let preview = master.encrypt_server_bytes(preview.as_bytes()).await?;
        scope.check(self)?;
        Ok((encrypted, preview))
    }
    pub async fn prepare_browser_draft_with_io_json<F, Fut>(
        &mut self,
        owner: &str,
        id: &str,
        markdown: &str,
        scope_json: &str,
        now: u64,
        io: F,
    ) -> Result<BrowserDraftWrite>
    where
        F: Fn(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
        validate_draft_markdown(markdown)?;
        if now > MAX_SAFE || scope_json.len() > 256 {
            return Err(Error::Protocol);
        }
        let scope: Value = serde_json::from_str(scope_json)?;
        if scope.as_object().is_none_or(|o| o.len() != 2)
            || safe(&scope["lifecycleGeneration"])? == 0
        {
            return Err(Error::Protocol);
        }
        safe(&scope["workspaceEpoch"])?;
        let admission = self.prepare_browser_draft_admission(owner, id)?;
        let operation = OwnedOperationScope::capture_local_draft(self, &admission)?;
        let check = |c: &Client| -> Result<()> {
            admission.check(c)?;
            operation.check(c)
        };
        check(self)?;
        let operation_id = uuid::Uuid::new_v4().to_string();
        let capture = json!({"version":1,"kind":"capture_draft","operationId":operation_id,"owner":owner,"chatId":id,"scope":scope,"expected":null,"queueMaximum":null,"patch":null,"change":null});
        let observed = io(serde_json::to_string(&capture)?).await?;
        check(self)?;
        let observed = packet(observed, "capture_draft", &operation_id, id)?;
        let expected = observed["row"].clone();
        let mut row = decoded_projection(&expected)?;
        if row["chat_id"] != id {
            return Err(Error::Forbidden);
        }
        if row.get("id").is_none() {
            row["id"] = json!(id)
        }
        self.validate_draft_row_scope(&row, id)?;
        // Initial supported slice is an EXISTING saved Personal chat. Unsupported
        // draft-only/new/Team/Direct inputs retain the caller's editor document.
        if optional_u64(&row["messages_v"])? == 0 || !row["encrypted_chat_key"].is_string() {
            return Err(Error::Unavailable {
                code: "browser_draft_existing_personal_required",
                reason: "Existing saved Personal chat required.",
            });
        }
        let old = optional_u64(&row["draft_v"])?.max(optional_u64(&row["cleared_draft_v"])?);
        let version = old
            .checked_add(1)
            .filter(|n| *n <= MAX_SAFE)
            .ok_or(Error::Protocol)?;
        let maximum = safe(&observed["queueMaximum"])?;
        let order = maximum
            .checked_add(1)
            .filter(|n| *n <= MAX_SAFE)
            .ok_or(Error::Protocol)?;
        let (encrypted, preview) = {
            let active = ActiveOwnedClient::enter(self, &operation)?;
            active
                .encrypt_draft_fields(markdown, &operation.crypto)
                .await?
        };
        check(self)?;
        let updated = now.max(
            optional_u64(&row["updated_at"])?
                .checked_add(1)
                .filter(|n| *n <= MAX_SAFE)
                .ok_or(Error::Protocol)?,
        );
        let patch = json!({"encrypted_draft_md":encrypted,"encrypted_draft_preview":preview,"draft_v":version,"updated_at":updated});
        let change = json!({"change_id":uuid::Uuid::new_v4().to_string(),"chat_id":id,"type":"draft","value":encrypted,"encrypted_draft_preview":preview,"version_before_edit":old,"queue_order":order,"queue_token":uuid::Uuid::new_v4().to_string()});
        let mut after_row = decoded_projection(&expected)?;
        for (field, value) in patch.as_object().ok_or(Error::Protocol)? {
            after_row[field] = value.clone();
        }
        let after = projection(&after_row)?;
        let store = json!({"version":1,"kind":"store_draft","operationId":operation_id,"owner":owner,"chatId":id,"scope":scope,"expected":expected,"queueMaximum":maximum,"patch":patch,"change":change});
        let stored = io(serde_json::to_string(&store)?).await?;
        check(self)?;
        let stored = packet(stored, "store_draft", &operation_id, id)?;
        if stored["row"] != after || stored["change"] != change {
            return Err(Error::Conflict);
        }
        let resource = BrowserDraftWrite {
            admission,
            operation,
            operation_id,
            scope,
            after,
            patch,
            change,
            maximum,
            version,
        };
        resource.check(self)?;
        let readback = io(serde_json::to_string(&resource.plan("readback_draft"))?).await?;
        resource.check(self)?;
        let readback = packet(readback, "readback_draft", &resource.operation_id, id)?;
        if readback["row"] != resource.after || readback["change"] != resource.change {
            return Err(Error::Conflict);
        }
        resource.check(self)?;
        Ok(resource)
    }
    pub async fn restore_browser_draft_with_io_json<F, Fut>(
        &mut self,
        owner: &str,
        id: &str,
        scope_json: &str,
        io: F,
    ) -> Result<BrowserDraftPublication>
    where
        F: Fn(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
        let admission = self.prepare_browser_draft_admission(owner, id)?;
        let operation = OwnedOperationScope::capture_local_draft(self, &admission)?;
        let scope: Value = serde_json::from_str(scope_json)?;
        if scope_json.len() > 256
            || scope.as_object().is_none_or(|o| o.len() != 2)
            || safe(&scope["lifecycleGeneration"])? == 0
        {
            return Err(Error::Protocol);
        }
        safe(&scope["workspaceEpoch"])?;
        let operation_id = uuid::Uuid::new_v4().to_string();
        let plan = json!({"version":1,"kind":"capture_draft","operationId":operation_id,"owner":owner,"chatId":id,"scope":scope,"expected":null,"queueMaximum":null,"patch":null,"change":null});
        let observed = io(serde_json::to_string(&plan)?).await?;
        admission.check(self)?;
        operation.check(self)?;
        let observed = packet(observed, "capture_draft", &operation_id, id)?;
        let original_projection = observed["row"].clone();
        let mut row = decoded_projection(&original_projection)?;
        if row.get("id").is_none() {
            row["id"] = json!(id)
        }
        self.validate_draft_row_scope(&row, id)?;
        let version = optional_u64(&row["draft_v"])?;
        let cleared = optional_u64(&row["cleared_draft_v"])?;
        if row["encrypted_draft_md"].is_null() || (cleared > 0 && version <= cleared) {
            let output = Zeroizing::new(serde_json::to_string(
                &json!({"source":"browser_rust_draft","chatId":id,"version":version.max(cleared),"present":false,"markdown":"","preview":null,"localOnly":true,"credentialAcknowledged":false}),
            )?);
            let final_read = io(serde_json::to_string(&plan)?).await?;
            admission.check(self)?;
            operation.check(self)?;
            if packet(final_read, "capture_draft", &operation_id, id)?["row"] != original_projection
            {
                return Err(Error::Conflict);
            }
            admission.check(self)?;
            operation.check(self)?;
            return Ok(BrowserDraftPublication {
                admission,
                operation,
                output,
            });
        }
        let draft = {
            let active = ActiveOwnedClient::enter(self, &operation)?;
            active.decode_draft_row_with_capability(&row).await?
        };
        admission.check(self)?;
        operation.check(self)?;
        let mut draft = draft;
        let markdown = Zeroizing::new(std::mem::take(&mut draft.markdown));
        let preview = draft.preview.take().map(Zeroizing::new);
        let version = draft.encrypted.draft_v;
        let final_read = io(serde_json::to_string(&plan)?).await?;
        admission.check(self)?;
        operation.check(self)?;
        if packet(final_read, "capture_draft", &operation_id, id)?["row"] != original_projection {
            return Err(Error::Conflict);
        }
        let view = plaintext::Plain::new(
            json!({"source":"browser_rust_draft","chatId":id,"version":version,"present":true,"markdown":markdown.as_str(),"preview":preview.as_ref().map(|p|p.as_str()),"localOnly":true,"credentialAcknowledged":false}),
        );
        let output = Zeroizing::new(serde_json::to_string(&*view)?);
        admission.check(self)?;
        operation.check(self)?;
        Ok(BrowserDraftPublication {
            admission,
            operation,
            output,
        })
    }
}
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "browser_draft_tests.rs"]
mod tests;
