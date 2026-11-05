//! Inactive browser metadata monitor publication, separate from native ACKs.
//! Reuses actual monitor socket/coalescing/read audit and existing owned metadata
//! transaction IO. Selected windows are invalidated, never exported as complete.
//! Rust/WASM UNRUN; selected retained-row token integration is the next layer.
use super::*;
use std::future::Future;
use zeroize::Zeroizing;

struct BrowserMonitorFence {
    scope: CacheMonitorReadScope,
    monitor: Arc<MonitorFence>,
    principal: String,
    epoch: u64,
    binding: Zeroizing<[u8;32]>,
    revision: u64,
}
impl BrowserMonitorFence {
    fn capture(client:&Client, monitor:&ChatMonitor, principal:&str, selected:Option<&str>)->Result<Self> {
        browser_monitor_profile(client,principal)?;
        client.check_chat_monitor_fence(&monitor.fence)?;
        let captured=Self {scope:CacheMonitorReadScope::capture(client,selected)?,monitor:monitor.fence.clone(),
            principal:principal.into(),epoch:client.fresh_auth.operation_epoch(),
            binding:Zeroizing::new(client.fresh_auth_binding()?),revision:client.credential_revision};
        captured.check(client)?;Ok(captured)
    }
    fn check(&self, client:&Client)->Result<()> {
        browser_monitor_profile(client,&self.principal)?;
        self.scope.check(client)?;client.check_chat_monitor_fence(&self.monitor)?;
        let same_gate=match (&self.scope.private_gate,&client.options.private_operation_gate) {
            (None,None)=>true,(Some(old),Some(current))=>Arc::ptr_eq(old,current),_=>false,
        };
        if !same_gate||client.credential_revision!=self.revision
            ||client.fresh_auth.operation_epoch()!=self.epoch||client.fresh_auth_binding()?!=*self.binding {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}
fn browser_monitor_profile(client:&Client,principal:&str)->Result<()> {
    client.require_canonical_read_profile()?;client.require_browser_owner_guards()?;
    if client.browser_credentials.is_none()||client.user["id"].as_str()!=Some(principal)
        ||!client.browser_authority.as_ref().is_some_and(|a|a.principal==principal)
        ||!uuid::Uuid::parse_str(principal).is_ok_and(|v|v.to_string()==principal) {
        return Err(Error::Forbidden);
    }
    if client.chats.keys().any(|id|!client.task_watch_authority.cached_chat_allowed(id)) {
        return Err(Error::Forbidden);
    }
    if client.team()?.is_some()||client.chats.values().any(|row|text(row,"chat_visibility")=="direct") {
        return Err(Error::Unavailable {code:"browser_monitor_scope_unsupported",reason:"TEAM_DIRECT_BROWSER_MONITOR_POLICY_REMAINS_REQUIRED"});
    }
    Ok(())
}
fn retain_missing_wrappers(current:&mut Vec<Value>,prior:&[Value],id_field:&str) {
    for old in prior {
        // Keep new wrappers first. Append an old resource/type/context only if
        // the bounded response supplied no replacement for that exact selector.
        if !text(old,id_field).is_empty() && !current.iter().any(|new|
            text(new,id_field)==text(old,id_field)&&text(new,"key_type")==text(old,"key_type")
                &&text(new,"hashed_team_id")==text(old,"hashed_team_id")
                &&text(new,"hashed_chat_id")==text(old,"hashed_chat_id")) {
            current.push(old.clone());
        }
    }
}
fn snapshot_stamp(client:&Client)->Result<String> {
    let snapshot=Plain::new(client.ciphertext_snapshot());
    let encoded=Zeroizing::new(serde_json::to_string(&*snapshot)?);Ok(sha256(&encoded))
}
/// Nonserializable staged browser read, never FreshChatInventory or a permission.
/// A monitor read alone has not committed anything to IndexedDB.
pub struct BrowserMetadataMonitorRefresh {
    fence:BrowserMonitorFence,stamp:String,changed:Vec<String>,
    items:Plain<Vec<Item>>,selected_invalidated:Option<String>,
}
/// Queued projection remains sealed until the original Client rechecks it.
/// This is metadata-only and cannot authorize history, send or recovery.
pub struct BrowserMetadataMonitorPublication {
    fence:BrowserMonitorFence,stamp:String,output:Zeroizing<String>,
    selected_transition:Option<crate::client::browser::BrowserMetadataOwnedTransition>,
}
impl Client {
    /// Existing reconnect socket requests the normal bounded recent content.
    /// Retain all prior metadata (including pins/drafts and older/sub-chat rows)
    /// when absent from that bounded response; absence is NEVER deletion proof.
    /// Changed hints fetch metadata only; no full selected-history reader runs.
    pub async fn refresh_browser_chat_monitor_metadata(&mut self,principal:&str,
        monitor:&ChatMonitor,hint:&ChatInvalidation,selected:Option<&str>)
        ->Result<BrowserMetadataMonitorRefresh> {
        if !Arc::ptr_eq(&monitor.fence,&hint.fence)||hint.pending.chats.len()>MAX_HINTS {
            return Err(Error::Cancelled);
        }
        if let Some(id)=selected {
            if !uuid::Uuid::parse_str(id).is_ok_and(|v|v.to_string()==id) {return Err(Error::Protocol);}
        }
        let fence=BrowserMonitorFence::capture(self,monitor,principal,selected)?;
        let mut transaction=LiveReadTransaction::new(self,monitor.fence.clone())?;
        let result=async {
            let prior=Plain::new(transaction.chats.clone());
            let prior_order=transaction.current_chat_arrival_order().cloned();
            if hint.pending.refresh {
                // Existing read-only shared sync: no completion/recovery writes.
                // Its original 20-parent content budget is not expanded here.
                drop(Plain::new(transaction.sync_chats_for_monitor().await?));
                fence.check(&transaction)?;
                if let Some(backup)=transaction.backup.as_ref() {
                    let old_windows=backup.sync_message_windows.clone();
                    let old_embeds=backup.embeds.clone();
                    let old_wrappers=backup.wrappers.clone();
                    let old_embed_keys=backup.embed_keys.clone();
                    retain_missing_wrappers(&mut transaction.wrappers,&old_wrappers,"hashed_chat_id");
                    retain_missing_wrappers(&mut transaction.embed_keys,&old_embed_keys,"hashed_embed_id");
                    for (id,window) in old_windows {transaction.sync_message_windows.entry(id).or_insert(window);}
                    for (id,embed) in old_embeds {transaction.embeds.entry(id).or_insert(embed);}
                }
                if let Some(ids)=&prior_order {
                    for id in ids {if !transaction.chats.contains_key(id) {
                        if let Some(row)=prior.get(id) {transaction.insert_chat_row(id.clone(),row.clone());}
                    }}
                } else {
                    let missing=prior.iter().filter(|(id,_)|!transaction.chats.contains_key(*id))
                        .map(|(id,row)|(id.clone(),row.clone())).collect();
                    transaction.extend_chat_rows_without_arrival(missing);
                }
            }
            for id in &hint.pending.chats {
                fence.check(&transaction)?;
                if !uuid::Uuid::parse_str(id).is_ok_and(|v|v.to_string()==*id) {return Err(Error::Protocol);}
                fence.scope.crypto.check_chat(&transaction,id)?;
                let metadata=transaction.request_chat_metadata(id).await?;
                fence.check(&transaction)?;
                fence.scope.crypto.check_chat(&transaction,id)?;
                if let Some(response)=metadata {
                    let rows=response["chats"].as_array().ok_or(Error::Protocol)?;
                    if rows.len()!=1||text(&rows[0],"id")!=id {return Err(Error::Protocol);}
                    if let Some(floor)=hint.pending.versions.get(id) {
                        if !matches_revision_floor(&rows[0],floor)? {return Err(Error::Offline);}
                    }
                    transaction.insert_chat_row(id.clone(),rows[0].clone());
                } else {
                    // A cache tombstone needs its own real store deletion/readback
                    // policy. Preserve existing drafts and cache data until then;
                    // never claim a deletion was persisted or hide pending recovery.
                    return Err(Error::Unavailable {code:"browser_monitor_absence_unsettled",
                        reason:"EXACT_CACHE_TOMBSTONE_OR_DRAFT_RECONCILIATION_REMAINS_REQUIRED"});
                }
            }
            browser_monitor_profile(&transaction,principal)?;
            // Metadata/draft clocks remain monotone; messages_v is a count and
            // may rewind. No full-history/cursor/coverage proof is advanced here.
            for (id,old) in prior.iter() {
                if let Some(current)=transaction.chats.get(id) {
                    let floor=VersionFloor {messages_v:0,metadata_v:metadata_version(old)?,draft_v:data_version(old,"draft_v")?};
                    if !matches_revision_floor(current,&floor)? {return Err(Error::Offline);}
                }
            }
            fence.check(&transaction)?;
            let changed=transaction.chats.iter().filter(|(id,row)|prior.get(*id)!=Some(*row))
                .map(|(id,_)|id.clone()).collect::<Vec<_>>();
            if changed.len()>MAX_HINTS+20 {return Err(Error::Protocol);}
            let selected_invalidated=selected.filter(|id|hint.pending.refresh||hint.pending.chats.contains(*id)).map(str::to_owned);
            let items=Plain::new(transaction.render_chat_inventory_with_capability().await?);
            fence.check(&transaction)?;
            Ok(BrowserMetadataMonitorRefresh {stamp:snapshot_stamp(&transaction)?,fence,changed,items,selected_invalidated})
        }.await;
        if let Some(denial)=transaction.denied() {
            return Err(match denial {ChatMonitorAccessDenial::Expired=>Error::Expired,_=>Error::Forbidden});
        }
        if result.is_ok() {
            transaction.chat_list_freshness.invalidate();transaction.invalidate_chat_inventory_proofs();
            transaction.accept();
        }
        result
    }
    /// Calls the actual original metadata capture/CAS/readback operation rather
    /// than accepting foreign boolean/count receipts. A successful per-row call
    /// yields that actual stored Item; unrelated draft/local fields are preserved.
    /// Different rows are not an atomic inventory or a cross-database association.
    pub async fn commit_browser_chat_monitor_metadata<F,Fut>(&mut self,
        refresh:BrowserMetadataMonitorRefresh,host_scope:crate::client::BrowserMetadataCacheScope,
        include_private_output:bool,mut io:F)->Result<BrowserMetadataMonitorPublication>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        if !include_private_output {return Err(Error::Invalid("Explicit private output consent is required."));}
        refresh.fence.check(self)?;
        if snapshot_stamp(self)?!=refresh.stamp {return Err(Error::Cancelled);}
        let mut refresh=refresh;let mut persisted=0usize;let mut drafts=0usize;let mut selected_transition=None;
        for id in &refresh.changed {
            refresh.fence.check(self)?;
            if snapshot_stamp(self)?!=refresh.stamp {return Err(Error::Cancelled);}
            let row=self.chats.get(id).ok_or(Error::Cancelled)?;
            if super::super::sync::draft_only(row) {drafts+=1;continue;}
            // Scope cloning is correlation only, never key/owner/IO authority.
            let copied=serde_json::from_value(serde_json::to_value(&host_scope)?)?;
            let encoded=Zeroizing::new(if refresh.selected_invalidated.as_deref()==Some(id.as_str()) {
                let (output,transition)=self.browser_metadata_cache_with_owned_transition(&refresh.fence.principal,id,copied,true,&mut io).await?;
                selected_transition=Some(transition);output
            }else{self.browser_metadata_cache_json(&refresh.fence.principal,id,
                crate::client::BrowserMetadataCacheMode::PersistCurrent,copied,true,&mut io).await?});
            refresh.fence.check(self)?;
            if snapshot_stamp(self)?!=refresh.stamp {return Err(Error::Cancelled);}
            let mut actual=Plain::new(serde_json::from_str::<Value>(&encoded)?);
            let item=serde_json::from_value::<Item>(actual["chat"].take())?;
            if item.id!=*id {let _guard=Plain::new(item);return Err(Error::Protocol);}
            if let Some(prior)=refresh.items.iter_mut().find(|item|item.id==*id) {
                crate::client::sync_capability::wipe_item(prior);*prior=item;
            } else {let _guard=Plain::new(item);return Err(Error::Protocol);}
            persisted+=1;
        }
        let output=Plain::new(json!({"source":"browser_metadata_monitor","metadataOnly":true,
            "inventoryComplete":false,"historyComplete":false,"messagesVersionAdvanced":false,
            "canonicalIncomingWindow":false,"selectedWindowPublished":false,
            "credentialAcknowledged":false,"nativeDurabilityAcknowledged":false,
            "crossDatabaseAssociationProven":false,"recoveryProof":false,
            "metadataRowsPersisted":persisted,"draftRowsNotPersisted":drafts,
            "selectedChatInvalidated":refresh.selected_invalidated,"items":&*refresh.items}));
        if crate::client::monitor::cached_view::bounded_bytes(&*output,256*1024).is_none(){return Err(Error::Protocol);}
        let output=Zeroizing::new(serde_json::to_string(&*output)?);
        refresh.fence.check(self)?;
        if snapshot_stamp(self)?!=refresh.stamp {return Err(Error::Cancelled);}
        Ok(BrowserMetadataMonitorPublication {fence:refresh.fence,stamp:refresh.stamp,output,selected_transition})
    }
    /// Final original-client fence on delayed UI/worker release. No public
    /// serde/models accessor can release a queued browser plaintext projection.
    pub fn browser_chat_monitor_metadata_json(&self,publication:BrowserMetadataMonitorPublication,
        include_private_output:bool)->Result<Zeroizing<String>> {
        if !include_private_output {return Err(Error::Invalid("Explicit private output consent is required."));}
        publication.fence.check(self)?;
        if snapshot_stamp(self)?!=publication.stamp {return Err(Error::Cancelled);}
        Ok(publication.output)
    }
}
#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_monitor_tests.rs"]
mod tests;

/// Rust-owned observation of an ACTUAL active authenticated monitor socket.
/// No host status/boolean, JSON, credentials or ciphertext can construct this.
/// Standalone HTTP saved reads do not get this context. A reconnect needs a new
/// capability from its new socket; it cannot revive an old healthy observation.
/// Disconnected is unsupported by this narrow live capability, NOT equated to
/// the maintained TS websocketStatus.error/raw-ciphertext branch. Ordinary
/// disconnected decryption keeps its existing separate path; no false error or
/// raw-text fallback is synthesized here.
pub(in crate::client) struct BrowserMonitorReadContext {
    fence:BrowserMonitorFence,
    chat:String,
}
impl BrowserMonitorReadContext {
    pub(in crate::client) fn ensure_current(&self,client:&Client,owner:&str,chat:&str)->Result<()> {
        if self.chat!=chat||self.fence.principal!=owner{return Err(Error::Cancelled);}
        self.fence.check(client)?;
        self.fence.scope.crypto.check_chat(client,chat)
    }
}
impl Client {
    pub(in crate::client) fn browser_monitor_read_context(&self,monitor:&ChatMonitor,
        owner:&str,chat:&str)->Result<BrowserMonitorReadContext> {
        if !uuid::Uuid::parse_str(chat).is_ok_and(|v|v.to_string()==chat){return Err(Error::Protocol);}
        let context=BrowserMonitorReadContext {fence:BrowserMonitorFence::capture(self,monitor,owner,Some(chat))?,chat:chat.into()};
        context.ensure_current(self,owner,chat)?;Ok(context)
    }
}

/// Owned sibling-only original monitor observation. Ordinary monitor fences
/// retain their strict credential/global-child behavior above unchanged.
#[path="browser_monitor_later_recovery.rs"]
mod later_recovery;
pub(in crate::client) use later_recovery::{OriginalLaterRecoveryHint,MAX_LATER_RECOVERY_HINTS};
pub(in crate::client) struct BrowserOwnedMonitorReadContext {
    scope:Arc<crate::client::owned_operation::OwnedOperationScope>,
    monitor:Arc<ChatMonitor>,principal:String,chat:String,
    hint:Mutex<Option<ChatInvalidation>>,later_recovery:Mutex<Vec<Arc<OriginalLaterRecoveryHint>>>,
}
impl BrowserOwnedMonitorReadContext {
    // AFTER the outer original scope gate only: monitor lifetime restriction,
    // never caller callback, Client/row adoption or private-output authority.
    pub(in crate::client) fn check_original_negative(&self)->Result<()> {
        if !self.monitor.fence.valid(){return Err(Error::Cancelled)}
        Ok(())
    }
    pub(in crate::client) fn negative_check(&self)->Result<()> {
        self.scope.observer().check_release()?;
        if !self.monitor.fence.valid(){return Err(Error::Cancelled)}
        self.scope.observer().check_release()
    }
    pub(in crate::client) fn original_draft_working_set(&self)->Result<Vec<String>> {
        self.negative_check()?;let guard=self.hint.lock().map_err(|_|Error::Protocol)?;let hint=guard.as_ref().ok_or(Error::Cancelled)?;
        let mut rows=hint.pending.chats.clone();for(_,_,chat)in hint.recovery_manifest().identities(){rows.insert(chat.into());}
        rows.remove(&self.chat);let rows=rows.into_iter().take(20).collect();drop(guard);self.negative_check()?;Ok(rows)
    }
    pub(in crate::client) fn original_refresh_required(&self)->Result<bool>{
        self.negative_check()?;let guard=self.hint.lock().map_err(|_|Error::Protocol)?;
        let refresh=guard.as_ref().ok_or(Error::Cancelled)?.pending.refresh;drop(guard);self.negative_check()?;Ok(refresh)
    }
    pub(in crate::client) fn prepare_original_read(&self,client:&Client,request:crate::client::monitor::MonitorReadRequest)->Result<crate::client::monitor::PreparedMonitorRead>{
        self.check(client)?;client.prepare_monitor_read(&self.monitor,&self.scope,request)
    }
    pub(in crate::client) fn take_original_read(&self,client:&Client,receipt:crate::client::monitor::MonitorReadReceipt)->Result<crate::client::monitor::MonitorReadData>{
        self.check(client)?;let data=receipt.take(client,&self.monitor,&self.scope)?;self.check(client)?;Ok(data)
    }
    pub(in crate::client) fn recovery_manifest(&self)->Result<crate::client::monitor::RecoveryHintManifest>{
        self.negative_check()?;let guard=self.hint.lock().map_err(|_|Error::Protocol)?;
        let result=guard.as_ref().ok_or(Error::Cancelled)?.recovery_manifest();drop(guard);
        self.negative_check()?;Ok(result)
    }
    pub(in crate::client) fn check_metadata_floor(&self,row:&Value)->Result<()> {self.check_chat_metadata_floor(&self.chat,row)}
    pub(in crate::client) fn check_chat_metadata_floor(&self,chat:&str,row:&Value)->Result<()> {
        self.negative_check()?;
        let guard=self.hint.lock().map_err(|_|Error::Protocol)?;
        let hint=guard.as_ref().ok_or(Error::Cancelled)?;
        if let Some(floor)=hint.pending.versions.get(chat){
            // Same maintained metadata/draft floor policy; message counts may
            // rewind and never become a fabricated local messages_v write.
            if !matches_revision_floor(row,floor)?{return Err(Error::Offline)}
        }
        drop(guard);self.negative_check()
    }
    pub(in crate::client) async fn cancelled(&self){
        if self.negative_check().is_err(){return}
        tokio::select!{biased;_=self.scope.cancelled()=>{},_=self.monitor.fence.cancel.cancelled()=>{}}
    }
    pub(in crate::client) fn check(&self,client:&Client)->Result<()> {
        browser_monitor_profile(client,&self.principal)?;
        self.scope.check(client)?;self.scope.crypto.check_chat(client,&self.chat)?;
        let fence=&self.monitor.fence;
        if !fence.valid()||!Arc::ptr_eq(&fence.owner,&client.task_watch_authority)
            ||fence.generation!=client.generation||fence.team.as_deref()!=client.team()? {
            return Err(Error::Cancelled)
        }
        // No revision-number shortcut or new authority snapshot. Only the
        // ORIGINAL actual sibling's typed cookie lineage can explain drift.
        self.negative_check()
    }
}
impl Drop for BrowserOwnedMonitorReadContext {
    fn drop(&mut self){
        if let Ok(slot)=self.hint.get_mut(){if let Some(hint)=slot.take(){let _=self.monitor.requeue(hint);}}
    }
}
impl Client {
    pub(in crate::client) fn browser_owned_monitor_context(&self,
        scope:Arc<crate::client::owned_operation::OwnedOperationScope>,monitor:Arc<ChatMonitor>,
        owner:&str,chat:&str)->Result<Arc<BrowserOwnedMonitorReadContext>> {
        if !uuid::Uuid::parse_str(chat).is_ok_and(|id|id.to_string()==chat){return Err(Error::Protocol)}
        scope.check(self)?;scope.crypto.check_chat(self,chat)?;
        let hint=Some(monitor.take_pending()?.ok_or(Error::Conflict)?);
        let context=Arc::new(BrowserOwnedMonitorReadContext{scope,monitor,principal:owner.into(),chat:chat.into(),hint:Mutex::new(hint),later_recovery:Mutex::new(Vec::new())});
        context.check(self)?;
        Ok(context)
    }
    pub(in crate::client) fn browser_owned_monitor_read_context(&self,
        scope:Arc<crate::client::owned_operation::OwnedOperationScope>,monitor:Arc<ChatMonitor>,owner:&str,chat:&str,
    )->Result<Arc<BrowserOwnedMonitorReadContext>> {
        let context=self.browser_owned_monitor_context(scope,monitor,owner,chat)?;
        if context.hint.lock().map_err(|_|Error::Protocol)?.as_ref().is_some_and(|hint|!hint.pending.recovery.is_empty()){
            return Err(Error::Unavailable{code:"browser_incoming_recovery_pending",reason:"EXPLICIT_BROWSER_RECOVERY_OWNER_REMAINS_REQUIRED"})
        }
        Ok(context)
    }
    pub(in crate::client) fn browser_owned_monitor_original_hint_context(&self,
        scope:Arc<crate::client::owned_operation::OwnedOperationScope>,monitor:Arc<ChatMonitor>,owner:&str,chat:&str,
    )->Result<Arc<BrowserOwnedMonitorReadContext>> {
        self.browser_owned_monitor_context(scope,monitor,owner,chat)
    }
}

#[path="browser_incoming_sync.rs"]
mod incoming;
pub use incoming::BrowserIncomingCachePublication;

// Source-unit invalidation fixture only. Keyless data never grants read/write
// authority; the new driver still requires its actual admitted original scope.
#[cfg(test)]
impl Client {
    pub(in crate::client) fn browser_owned_hint_for_test(&self,monitor:&ChatMonitor,chats:&[&str],recovery:&[&str])->Result<()> {
        self.check_chat_monitor_fence(&monitor.fence)?;
        let mut pending=monitor.changes.pending.lock().map_err(|_|Error::Protocol)?;
        pending.refresh=true;
        for id in chats{pending.chats.insert((*id).into());}
        for id in recovery{pending.recovery.insert((*id).into());}
        drop(pending);monitor.changes.wake.notify_one();Ok(())
    }
    pub(in crate::client) fn browser_owned_pending_for_test(&self,monitor:&ChatMonitor)->Result<(bool,Vec<String>,Vec<String>)>{
        self.check_chat_monitor_fence(&monitor.fence)?;
        let pending=monitor.changes.pending.lock().map_err(|_|Error::Protocol)?;
        Ok((pending.refresh,pending.chats.iter().cloned().collect(),pending.recovery.iter().cloned().collect()))
    }
}

#[cfg(test)]
impl Client {
    pub(in crate::client) fn browser_owned_floor_for_test(&self,monitor:&ChatMonitor,chat:&str,metadata_v:u64,draft_v:u64)->Result<()> {
        self.check_chat_monitor_fence(&monitor.fence)?;
        monitor.changes.pending.lock().map_err(|_|Error::Protocol)?.versions.insert(chat.into(),VersionFloor{messages_v:0,metadata_v,draft_v});Ok(())
    }
}

// Opaque cached-row floor captured only from the actual original Client. Use
// maintained metadata/title fallback and active-draft/tombstone semantics;
// messages_v is a count and is deliberately not a monotonic version floor.
pub(in crate::client) struct BrowserOwnedMetadataFloor(VersionFloor);
impl BrowserOwnedMetadataFloor {
    pub(in crate::client) fn capture(client:&Client,chat:&str)->Result<Self> {
        let floor=if let Some(row)=client.chats.get(chat){
            VersionFloor{messages_v:0,metadata_v:metadata_version(row)?,draft_v:data_version(row,"draft_v")?}
        }else{VersionFloor::default()};Ok(Self(floor))
    }
    pub(in crate::client) fn check(&self,row:&Value)->Result<()> {
        if !matches_revision_floor(row,&self.0)?{return Err(Error::Offline)}Ok(())
    }
}

#[cfg(test)]
impl Client {
    pub(in crate::client) fn browser_owned_job_hint_for_test(&self,monitor:&ChatMonitor,metadata:bool,job:&str,chat:&str)->Result<()> {
        self.check_chat_monitor_fence(&monitor.fence)?;
        record_change(&monitor.changes,if metadata{"metadata_jobs_available"}else{"recovery_jobs_available"},&json!({"jobs":[{"job_id":job,"chat_id":chat}]}))
    }
}
