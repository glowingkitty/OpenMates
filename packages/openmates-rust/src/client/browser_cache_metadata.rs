//! Inactive metadata-only browser cache transaction. Existing chats_db/chats only.
//! No native Session, credential ACK, key export, message write or schema upgrade.
use super::*;
use crate::client::{plaintext::Plain, sync_capability::AsyncCryptoScope};
use std::{future::Future, sync::Arc};
use zeroize::Zeroizing;

/// Existing browser cache metadata only; neither mode grants canonical history.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum BrowserMetadataCacheMode {
    Restore,
    PersistCurrent,
}
/// Host lifecycle correlation only; never owner/key/transaction authority.
#[derive(serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BrowserMetadataCacheScope {
    lifecycle_generation: u64,
    workspace_epoch: u64,
}
// These fields alone can be written. Omitted server fields are preserved.
// Drafts, messages_v, coverage, key wrappers/versions and all local flags are NOT writes.
const CIPHERS: &[&str] = &[
    "encrypted_title",
    "encrypted_chat_summary",
    "encrypted_share_cta_text",
    "encrypted_chat_tags",
    "encrypted_follow_up_request_suggestions",
    "encrypted_suggested_followup_message",
    "encrypted_icon",
    "encrypted_category",
    "encrypted_active_focus_id",
    "encrypted_focus_phase_state",
    "encrypted_auto_speak_response",
];
const VERSIONS: &[&str] = &["title_v", "metadata_v"];
const PREDICATES: &[&str] = &[
    "id",
    "chat_id",
    "user_id",
    "team_id",
    "hashed_team_id",
    "chat_visibility",
    "encrypted_chat_key",
    "key_version",
    "key_fingerprint",
    "title_v",
    "metadata_v",
    "messages_v",
    "created_at",
    "updated_at",
    "last_edited_overall_timestamp",
    "pinned",
    "encrypted_title",
    "encrypted_chat_summary",
    "encrypted_share_cta_text",
    "encrypted_chat_tags",
    "encrypted_follow_up_request_suggestions",
    "encrypted_suggested_followup_message",
    "encrypted_icon",
    "encrypted_category",
    "encrypted_active_focus_id",
    "encrypted_focus_phase_state",
    "encrypted_auto_speak_response",
];
const MAX_SAFE: u64 = 9_007_199_254_740_991;
struct Fence {
    parent: CancellationToken,
    private_gate: Option<Arc<dyn Fn() -> Result<()> + Send + Sync>>,
    scope: AsyncCryptoScope,
    epoch: u64,
    binding: Zeroizing<[u8; 32]>,
    source_stamp: String,
    revision: u64,
}
/// Nonserializable one-operation receipt for an actual same-row metadata CAS.
/// Its original fence and exact full pre/post images cannot be supplied by JS.
pub(in crate::client) struct BrowserMetadataOwnedTransition {
    fence: Fence, owner: String, chat: String,
    before: Plain<Value>, after: Plain<Value>, patch: Plain<Value>,
}
impl BrowserMetadataOwnedTransition {
    pub(in crate::client) fn consume(self, client:&Client, owner:&str, chat:&str, expected_before:&Value)->Result<Plain<Value>> {
        client.metadata_cache_check(&self.fence,&self.owner,&self.chat,BrowserMetadataCacheMode::PersistCurrent)?;
        if self.owner!=owner||self.chat!=chat||*self.before!=*expected_before{return Err(Error::Conflict)}
        let fields=self.patch.as_object().ok_or(Error::Protocol)?;
        if fields.keys().any(|field|!CIPHERS.contains(&field.as_str())&&!VERSIONS.contains(&field.as_str())){return Err(Error::Protocol)}
        let mut expected=Plain::new((*self.before).clone());
        for(field,value)in fields {expected[field]=value.clone();}
        if *expected!=*self.after{return Err(Error::Conflict)}
        client.metadata_cache_check(&self.fence,&self.owner,&self.chat,BrowserMetadataCacheMode::PersistCurrent)?;
        Ok(self.after)
    }
}
fn source_stamp(client: &Client, id: &str) -> Result<String> {
    if crate::client::monitor::cached_view::bounded_bytes(&client.chats.get(id), 256 * 1024)
        .is_none()
    {
        return Err(Error::Protocol);
    }
    let encoded = Zeroizing::new(serde_json::to_string(&client.chats.get(id))?);
    Ok(sha256(&encoded))
}
fn closed(value: &Value, fields: &[&str]) -> bool {
    value
        .as_object()
        .is_some_and(|o| o.len() == fields.len() && fields.iter().all(|k| o.contains_key(*k)))
}
fn safe_number(value: &Value) -> Result<u64> {
    value
        .as_u64()
        .filter(|n| *n <= MAX_SAFE)
        .ok_or(Error::Protocol)
}
fn projection(raw: &Value, id: &str, owner: &str, physical: bool) -> Result<Plain<Value>> {
    let object = raw.as_object().ok_or(Error::Protocol)?;
    if physical && raw["chat_id"].as_str() != Some(id) {
        return Err(Error::Forbidden);
    }
    if raw.get("id").is_some_and(|v| v.as_str() != Some(id)) {
        return Err(Error::Forbidden);
    }
    if raw.get("chat_id").is_some_and(|v| v.as_str() != Some(id)) {
        return Err(Error::Forbidden);
    }
    if raw
        .get("user_id")
        .filter(|v| !v.is_null())
        .is_some_and(|v| v.as_str() != Some(owner))
    {
        return Err(Error::Forbidden);
    }
    for field in ["team_id", "hashed_team_id"] {
        if raw
            .get(field)
            .is_some_and(|v| !v.is_null() && v.as_str() != Some(""))
        {
            return Err(Error::Unavailable {
                code: "browser_metadata_cache_scope_unsupported",
                reason: "TEAM_DIRECT_CACHE_POLICY_REMAINS_REQUIRED",
            });
        }
    }
    if raw
        .get("chat_visibility")
        .filter(|v| !v.is_null())
        .is_some_and(|v| !matches!(v.as_str(), Some("" | "personal")))
    {
        return Err(Error::Unavailable {
            code: "browser_metadata_cache_scope_unsupported",
            reason: "TEAM_DIRECT_CACHE_POLICY_REMAINS_REQUIRED",
        });
    }
    let mut out = Plain::new(Value::Object(serde_json::Map::new()));
    for field in PREDICATES {
        if let Some(value) = object.get(*field) {
            out[*field] = value.clone();
        }
    }
    for field in CIPHERS
        .iter()
        .copied()
        .chain(std::iter::once("encrypted_chat_key"))
    {
        if out
            .get(field)
            .filter(|v| !v.is_null())
            .is_some_and(|v| !v.is_string())
        {
            return Err(Error::Protocol);
        }
    }
    if text(&out, "encrypted_chat_key").is_empty() {
        return Err(Error::Unavailable {
            code: "browser_metadata_cache_draft_unsupported",
            reason: "DRAFT_AND_KEY_ROTATION_POLICY_REMAINS_REQUIRED",
        });
    }
    for field in [
        "title_v",
        "metadata_v",
        "messages_v",
        "created_at",
        "updated_at",
        "last_edited_overall_timestamp",
        "key_version",
    ] {
        if let Some(value) = out.get(field).filter(|v| !v.is_null()) {
            safe_number(value)?;
        }
    }
    if out
        .get("key_fingerprint")
        .filter(|v| !v.is_null())
        .is_some_and(|v| !v.as_str().is_some_and(|s| s.len() <= 64))
    {
        return Err(Error::Protocol);
    }
    if out
        .get("pinned")
        .filter(|v| !v.is_null())
        .is_some_and(|v| !v.is_boolean())
    {
        return Err(Error::Protocol);
    }
    Ok(out)
}
fn normalized(raw: &Value, id: &str, owner: &str, physical: bool) -> Result<Plain<Value>> {
    let mut row = projection(raw, id, owner, physical)?;
    row["id"] = json!(id);
    row["chat_id"] = json!(id);
    Ok(row)
}
fn version(row: &Value) -> u64 {
    row["metadata_v"]
        .as_u64()
        .unwrap_or(0)
        .max(row["title_v"].as_u64().unwrap_or(0))
}
fn patch(desired: &Value, old: &Value) -> Result<Plain<Value>> {
    if version(desired) < version(old) {
        return Err(Error::Conflict);
    }
    // Counters are independent clocks: a large/newer title revision must
    // never mask a metadata rollback, nor the reverse. Null/omitted counters
    // are not written; retain the existing aggregate stale-envelope floor.
    for field in VERSIONS {
        if let Some(value) = desired.get(*field).filter(|value| !value.is_null()) {
            if safe_number(value)? < old[*field].as_u64().unwrap_or(0) {
                return Err(Error::Conflict);
            }
        }
    }
    let mut next = Plain::new(json!({}));
    for field in CIPHERS.iter().chain(VERSIONS.iter()) {
        if let Some(value) = desired
            .get(*field)
            .filter(|value| !VERSIONS.contains(field) || !value.is_null())
        {
            next[*field] = value.clone();
        }
    }
    Ok(next)
}
impl Client {
    fn metadata_cache_scope(
        &self,
        principal: &str,
        id: &str,
        mode: BrowserMetadataCacheMode,
    ) -> Result<()> {
        if !uuid::Uuid::parse_str(principal).is_ok_and(|v| v.to_string() == principal)
            || !uuid::Uuid::parse_str(id).is_ok_and(|v| v.to_string() == id)
            || self.browser_credentials.is_none()
            || !self
                .browser_authority
                .as_ref()
                .is_some_and(|a| a.principal == principal)
            || self.user["id"].as_str() != Some(principal)
        {
            return Err(Error::Forbidden);
        }
        self.require_credentials()?;
        if self.team()?.is_some() {
            return Err(Error::Unavailable {
                code: "browser_metadata_cache_scope_unsupported",
                reason: "TEAM_DIRECT_CACHE_POLICY_REMAINS_REQUIRED",
            });
        }
        if mode == BrowserMetadataCacheMode::PersistCurrent {
            if self.is_local_browser_profile() {
                return Err(Error::Unavailable {
                    code: "browser_offline_read_only",
                    reason: "LOCAL_PROFILE_CACHE_WRITES_ARE_NOT_ADMITTED",
                });
            }
            self.require_browser_owner_guards()?;
        }
        Ok(())
    }
    fn metadata_cache_lifetime(
        &self,
        fence: &Fence,
        principal: &str,
        id: &str,
        mode: BrowserMetadataCacheMode,
    ) -> Result<()> {
        self.verify_private_operation()?;
        if let Some(gate) = &fence.private_gate {
            gate()?;
        }
        let same_gate = match (&fence.private_gate, &self.options.private_operation_gate) {
            (None, None) => true,
            (Some(old), Some(current)) => Arc::ptr_eq(old, current),
            _ => false,
        };
        self.metadata_cache_scope(principal, id, mode)?;
        fence.scope.check_chat(self, id)?;
        if !same_gate
            || fence.parent.is_cancelled()
            || fence.parent != self.operation_parent
            || self.fresh_auth.operation_epoch() != fence.epoch
            || self.fresh_auth_binding()? != *fence.binding
            || self.credential_revision != fence.revision
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    fn metadata_cache_check(
        &self,
        fence: &Fence,
        principal: &str,
        id: &str,
        mode: BrowserMetadataCacheMode,
    ) -> Result<()> {
        self.metadata_cache_lifetime(fence, principal, id, mode)?;
        if source_stamp(self, id)? != fence.source_stamp {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    async fn metadata_cache_io<F, Fut>(
        &self,
        fence: &Fence,
        principal: &str,
        id: &str,
        mode: BrowserMetadataCacheMode,
        plan: &Value,
        io: &mut F,
    ) -> Result<Plain<Value>>
    where
        F: FnMut(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
        let mut check=||self.metadata_cache_check(fence,principal,id,mode);
        execute_metadata_cache_io(plan,&mut check,io).await
    }
    async fn validate_metadata_cache_row(
        &self,
        fence: &Fence,
        principal: &str,
        id: &str,
        mode: BrowserMetadataCacheMode,
        row: &Value,
    ) -> Result<Key> {
        self.metadata_cache_check(fence, principal, id, mode)?;
        let master = self.master_capability()?;
        let key = self
            .chat_key_with_capability_from(row, &master, &[])
            .await?;
        self.metadata_cache_check(fence, principal, id, mode)?;
        validate_metadata_cipher_fields(row,&key)?;
        self.metadata_cache_check(fence, principal, id, mode)?;
        Ok(key)
    }
    /// Required-partial browser metadata persistence/restore. The callback executes
    /// exact plans in existing chats_db/chats and resolves only after transaction
    /// complete/abort. It must hold the captured host profile/lifecycle and abort
    /// on invalidation. No callback label can supply Rust owner/key authority.
    /// This does not restore native snapshots or enable monitor/credential ACKs.
    pub async fn browser_metadata_cache_json<F,Fut>(&mut self,principal:&str,id:&str,mode:BrowserMetadataCacheMode,host_scope:BrowserMetadataCacheScope,include_private_output:bool,io:F)->Result<String>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        self.browser_metadata_cache_inner(principal,id,mode,host_scope,include_private_output,false,io).await.map(|(output,_)|output)
    }
    pub(in crate::client) async fn browser_metadata_cache_with_owned_transition<F,Fut>(&mut self,principal:&str,id:&str,host_scope:BrowserMetadataCacheScope,include_private_output:bool,io:F)->Result<(String,BrowserMetadataOwnedTransition)>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        let (output,transition)=self.browser_metadata_cache_inner(principal,id,BrowserMetadataCacheMode::PersistCurrent,host_scope,include_private_output,true,io).await?;
        Ok((output,transition.ok_or(Error::Protocol)?))
    }
    async fn browser_metadata_cache_inner<F, Fut>(
        &mut self,
        principal: &str,
        id: &str,
        mode: BrowserMetadataCacheMode,
        host_scope: BrowserMetadataCacheScope,
        include_private_output: bool,
        retain_transition: bool,
        mut io: F,
    ) -> Result<(String,Option<BrowserMetadataOwnedTransition>)>
    where
        F: FnMut(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
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
        self.metadata_cache_scope(principal, id, mode)?;
        self.verify_private_operation()?;
        let fence = Fence {
            parent: self.operation_parent.clone(),
            private_gate: self.options.private_operation_gate.clone(),
            scope: AsyncCryptoScope::begin(self)?,
            epoch: self.fresh_auth.operation_epoch(),
            binding: Zeroizing::new(self.fresh_auth_binding()?),
            source_stamp: source_stamp(self, id)?,
            revision: self.credential_revision,
        };
        self.metadata_cache_check(&fence, principal, id, mode)?;
        let operation = uuid::Uuid::new_v4().to_string();
        let mut plan = Plain::new(
            json!({"version":1,"kind":"capture","operationId":operation,"scope":host_scope,"owner":principal,"chatId":id,"database":"chats_db","store":"chats","databaseVersion":null,"compareFields":PREDICATES,"expected":null,"patch":null}),
        );
        let captured = self
            .metadata_cache_io(&fence, principal, id, mode, &plan, &mut io)
            .await?;
        if !captured["before"].is_null() {
            return Err(Error::Protocol);
        }
        let old = projection(&captured["record"], id, principal, true)?;
        let old_normalized = normalized(&old, id, principal, false)?;
        let old_key = self
            .validate_metadata_cache_row(&fence, principal, id, mode, &old_normalized)
            .await?;
        let mut effective = Plain::new(old_normalized.clone());
        let mut transition_data=None;
        if mode == BrowserMetadataCacheMode::PersistCurrent {
            let desired = normalized(
                self.chats.get(id).ok_or(Error::Unavailable {
                    code: "browser_metadata_cache_missing_source",
                    reason: "NO_ADMITTED_SELECTED_METADATA",
                })?,
                id,
                principal,
                false,
            )?;
            let mut check=||self.metadata_cache_check(&fence,principal,id,mode);
            let this=&*self;let original=&fence;
            let validate_row=move|row:Plain<Value>|async move {
                this.validate_metadata_cache_row(original,principal,id,mode,&row).await
            };
            let persisted=drive_metadata_persist_policy(principal,id,&desired,&old_key,
                &captured,&old,&mut plan,retain_transition,&mut check,validate_row,&mut io).await?;
            effective=persisted.effective;transition_data=persisted.transition_data;
        } else if let Some(current) = self.chats.get(id) {
            if *normalized(current, id, principal, false)? != *old_normalized {
                return Err(Error::Conflict);
            }
        }
        self.validate_metadata_cache_row(&fence, principal, id, mode, &effective)
            .await?;
        let item = Plain::new(self.chat_item(&effective, &old_key)?);
        let output = Plain::new(
            json!({"source":"browser_metadata_cache","cached":true,"fresh":false,"readOnly":true,"historyComplete":false,"messagesPersisted":false,"credentialAcknowledged":false,"nativeDurabilityAcknowledged":false,"metadataOnly":true,"chat":&*item}),
        );
        let mut encoded = Zeroizing::new(serde_json::to_string(&*output)?);
        local_json::validate(&encoded)?;
        self.metadata_cache_check(&fence, principal, id, mode)?;
        // Restore only the selected closed ciphertext metadata, never history/windows
        // or a cache freshness/permission/recovery proof. All awaits are already over.
        let inserted = mode == BrowserMetadataCacheMode::Restore && !self.chats.contains_key(id);
        if inserted {
            self.chat_list_freshness.invalidate();
            self.invalidate_chat_inventory_proofs();
            self.insert_chat_row(id.into(), effective.into_inner());
        }
        let final_check = self.metadata_cache_lifetime(&fence, principal, id, mode);
        if let Err(error) = final_check {
            if inserted {
                if let Some(mut row) = self.remove_chat_row(id) {
                    crate::model::zeroize_json(&mut row);
                }
            }
            return Err(error);
        }
        let transition=transition_data.map(|(before,after,patch)|BrowserMetadataOwnedTransition {
            fence,owner:principal.into(),chat:id.into(),before,after,patch});
        Ok((std::mem::take(&mut *encoded),transition))
    }
}

fn validate_metadata_cipher_fields(row:&Value,key:&Key)->Result<()> {
    for field in CIPHERS {
        let _plain=Zeroizing::new(sync::decrypt_optional(row,field,key)?);
    }
    Ok(())
}
// Shared closed transport parser. Callback results remain untrusted rich frames;
// actual native Host transaction authority/drain is independently required.
async fn execute_metadata_cache_io<F,Fut,C>(plan:&Value,check:&mut C,io:&mut F)->Result<Plain<Value>>
where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>>,C:FnMut()->Result<()> {
    execute_metadata_cache_io_budget(plan,check,io,CacheIoBudget::Metadata).await
}
async fn execute_metadata_cache_io_budget<F,Fut,C>(plan:&Value,check:&mut C,io:&mut F,budget:CacheIoBudget)->Result<Plain<Value>>
where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>>,C:FnMut()->Result<()> {
        check()?;
        let request = Zeroizing::new(serde_json::to_string(plan)?);
        local_json::validate(&request)?;
        // The host receives only closed ciphertext/selectors, never a master resource.
        // Own the returned rich frame before checking any post-await fence.
        let result = io(request.to_string()).await.map(Zeroizing::new);
        check()?;
        let encoded = result?;
        budget.validate(&encoded)?;
        let frame = Plain::new(serde_json::from_str::<Value>(&encoded)?);
        if !closed(
            &frame,
            &[
                "version",
                "kind",
                "operationId",
                "databaseVersion",
                "transactionCommitted",
                "credentialAcknowledged",
                "crossDatabaseAssociationProven",
                "record",
                "before",
            ],
        ) || frame["version"] != 1
            || frame["kind"] != plan["kind"]
            || frame["operationId"] != plan["operationId"]
            || frame["transactionCommitted"] != true
            || frame["credentialAcknowledged"] != false
            || frame["crossDatabaseAssociationProven"] != false
            || safe_number(&frame["databaseVersion"])? == 0
        {
            return Err(Error::Protocol);
        }
        if plan["databaseVersion"]
            .as_u64()
            .is_some_and(|v| Some(v) != frame["databaseVersion"].as_u64())
        {
            return Err(Error::Conflict);
        }
        Ok(frame)
}
struct MetadataPersistData {
    effective:Plain<Value>,
    transition_data:Option<(Plain<Value>,Plain<Value>,Plain<Value>)>,
    readback:Plain<Value>,
}
// The same per-row PersistCurrent branch, independent of a Client borrow. Key
// validation remains opaque and original-owner guarded through its typed port.
async fn drive_metadata_persist_policy<F,Fut,C,U,UFut>(
    principal:&str,id:&str,desired:&Value,old_key:&Key,captured:&Value,
    old:&Value,plan:&mut Plain<Value>,retain_transition:bool,
    check:&mut C,mut validate_row:U,io:&mut F,
)->Result<MetadataPersistData>
where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>>,C:FnMut()->Result<()>,
    U:FnMut(Plain<Value>)->UFut,UFut:Future<Output=Result<Key>> {
    drive_metadata_persist_policy_budget(principal,id,desired,old_key,captured,old,plan,retain_transition,check,validate_row,io,CacheIoBudget::Metadata).await
}
async fn drive_metadata_persist_policy_budget<F,Fut,C,U,UFut>(
    principal:&str,id:&str,desired:&Value,old_key:&Key,captured:&Value,
    old:&Value,plan:&mut Plain<Value>,retain_transition:bool,
    check:&mut C,mut validate_row:U,io:&mut F,budget:CacheIoBudget,
)->Result<MetadataPersistData>
where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>>,C:FnMut()->Result<()>,
    U:FnMut(Plain<Value>)->UFut,UFut:Future<Output=Result<Key>> {
    let mut transition_data=None;
            let desired_key = validate_row(Plain::new(desired.clone())).await?;
            if desired_key.as_ref() != old_key.as_ref() {
                return Err(Error::Unavailable {
                    code: "browser_metadata_cache_key_rotation_unsupported",
                    reason: "KEY_ROTATION_AND_MESSAGE_MERGE_POLICY_REMAINS_REQUIRED",
                });
            }
            let updates = patch(&desired, &old)?;
            plan["kind"] = json!("compare_and_patch");
            plan["databaseVersion"] = captured["databaseVersion"].clone();
            plan["expected"] = old.clone();
            plan["patch"] = updates.clone();
            let committed = execute_metadata_cache_io_budget(plan,check,io,budget).await?;
            let before = projection(&committed["before"], id, principal, true)?;
            if *before != *old {
                return Err(Error::Conflict);
            }
            // Validate the ENTIRE raw pre/post image: every unowned/local extension must
            // survive unchanged, without ever returning it in a persisted projection.
            let mut expected = Plain::new(committed["before"].clone());
            for (field, value) in updates.as_object().unwrap() {
                expected[field] = value.clone();
            }
            if *expected != committed["record"] {
                return Err(Error::Protocol);
            }
            let after = projection(&committed["record"], id, principal, true)?;
            plan["kind"] = json!("readback");
            plan["expected"] = after.clone();
            plan["patch"] = Value::Null;
            let readback = execute_metadata_cache_io_budget(plan,check,io,budget).await?;
            if !readback["before"].is_null()
                || *projection(&readback["record"], id, principal, true)? != *after
            {
                return Err(Error::Conflict);
            }
            if retain_transition {
                // A receipt requires the ENTIRE owned postimage on physical reread.
                // The public metadata-only API keeps its existing projected semantics.
                if readback["record"]!=committed["record"] {return Err(Error::Conflict)}
                transition_data=Some((Plain::new(committed["before"].clone()),Plain::new(committed["record"].clone()),Plain::new((*updates).clone())));
            }
            let effective = normalized(&after, id, principal, false)?;
            Ok(MetadataPersistData{effective,transition_data,readback})
}
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "browser_cache_metadata_tests.rs"]
mod tests;

// Phase B shares ONLY the original scoped metadata/key/lifecycle fences.
#[path="browser_cache_messages.rs"]
mod messages;
pub(in crate::client) use messages::recovered_reply_policy;

pub(crate) use messages::{BrowserRetainedMessageCache, BrowserRetainedMessageReadback};

#[path = "browser_cache_restore.rs"]
mod cache_restore;

#[path = "browser_retained_view.rs"]
mod retained_view;

pub use messages::BrowserCandidateFailures;
#[doc(hidden)]
pub use messages::BrowserProfileCacheReadiness;
#[doc(hidden)]
pub use messages::OwnedBrowserProfileCacheAbsence;
#[doc(hidden)]
pub use messages::{OriginalHintRefreshAdmission,OriginalHintRefreshBatch,OriginalHintRowSeed,OriginalHintRowMetadataAdmission,OriginalHintRowMetadataPublication,OriginalHintMetadataApplied,OriginalHintDraftInventoryPrerequisite,OriginalHintDraftInventoryTicket,UntrustedDraftInventoryPageData,UntrustedDraftInventoryRereadData,OwnedOriginalHintWindowPreparation,OwnedOriginalHintWindowCompletion,OriginalHintWindowBatch,OwnedBrowserReadDriver,OwnedBrowserReadStep,OwnedBrowserReadPhase,OwnedBrowserReadIO,OwnedBrowserReadPublication,OwnedBrowserMetadataContinuation,OwnedBrowserReadControl,OwnedBrowserMetadataPublication,OriginalHintRecoveryHandoff,OwnedBrowserReadTerminalObserver,OwnedBrowserReadTerminal,BrowserOriginalHintRecoveryDriver,BrowserOriginalHintRecoveryStep,BrowserOriginalHintRecoveryApply,BrowserOriginalHintRecoveryIo,BrowserOriginalHintRecoveryResume,BrowserOriginalHintRecoveryControl,BrowserOriginalHintRecoveryAdoption,BrowserOriginalHintRecoveryProgress,BrowserOriginalHintRecoveryPendingPersistence,BrowserOriginalHintRecoveryDeferred,BrowserOriginalHintRecoveryCheckpointPreparation,BrowserOriginalHintRecoveryCheckpointCrypto,BrowserOriginalHintRecoveryCheckpointWrite,BrowserOriginalHintRecoveryPersistenceFailure};

pub use retained_view::BrowserRetainedCachePublication;

#[cfg(target_arch="wasm32")]
#[doc(hidden)]
pub use messages::{BrowserOriginalHintRecoveryCheckpointReadiness,BrowserOriginalHintRecoveryCheckpointRead,BrowserOriginalHintRecoveryCheckpointReadResult,BrowserOriginalHintRecoveryCheckpointNativeWrite,BrowserOriginalHintRecoveryCheckpointNativeWriteResult,BrowserOriginalHintRecoveryCheckpointReadbackCrypto,BrowserOriginalHintRecoveryCheckpointVerified,BrowserOriginalHintRecoveryCheckpointDurable};

#[cfg(target_arch="wasm32")]
#[doc(hidden)]
pub use messages::OriginalPhysicalDraftInventory;

#[derive(Clone,Copy)]
enum CacheIoBudget {Metadata,OriginalPhysicalDraft}
impl CacheIoBudget {
    fn validate(self,encoded:&str)->Result<()>{match self{Self::Metadata=>local_json::validate(encoded),Self::OriginalPhysicalDraft=>local_json::validate_original_physical_draft(encoded)}}
}

#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use messages::{BrowserMetadataBootstrap,MetadataOpaqueStored,MetadataNativeIoTicket,close_native_metadata_io_only,CapturedInitialSyncStore,BoundInitialSyncStore,StartupMetadataStoreDriver,StartupMetadataStored,StartupMetadataNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use messages::{BrowserMetadataRecoveryFinalize,BrowserMetadataRecoveryLocalStored,BrowserMetadataRecoveryNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use messages::{BrowserRecoveredReplyStore,BrowserRecoveredReplyControl,BrowserRecoveredReplyStored,BrowserRecoveredReplyNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use messages::{BrowserMainCodeEmbedStore,BrowserMainCodeEmbedControl,BrowserMainCodeEmbedStored,BrowserMainCodeEmbedNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(in crate::client) use messages::MetadataRecoveryPhysicalProof;
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use messages::{BrowserMainMetadataStore,BrowserMainMetadataStored,BrowserMainMetadataNativeTerminal};
