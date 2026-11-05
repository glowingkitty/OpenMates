//! Original-monitor incoming update transaction. Keyless hints are invalidations,
//! never incoming ciphertext durability, inventory, deletion or recovery proof.
use super::*;
use crate::client::{BrowserCandidateFailures,BrowserRetainedCachePublication};
use crate::client::message_window::MessageWindowOptions;
use crate::client::BrowserMetadataCacheScope;

struct PendingIncoming {
    monitor:Arc<ChatMonitor>,
    hint:Option<ChatInvalidation>,
}
impl Drop for PendingIncoming {
    fn drop(&mut self){if let Some(hint)=self.hint.take(){let _=self.monitor.requeue(hint);}}
}
/// Sealed metadata + actual retained selected rows under one original socket.
/// Drop/cancellation requeues only the original unfinished invalidation.
pub struct BrowserIncomingCachePublication {
    work:PendingIncoming,
    metadata:BrowserMetadataMonitorPublication,
    selected:Option<BrowserRetainedCachePublication>,
}
impl Client {
    /// Explicit inactive browser cache loop step. Never starts recovery, inference
    /// or a replacement socket. A new socket requires a new explicit monitor.
    pub async fn prepare_browser_incoming_cache_update<F,Fut>(&mut self,
        monitor:Arc<ChatMonitor>,failures:&mut BTreeMap<String,Option<BrowserCandidateFailures>>,
        owner:&str,selected:&str,options:MessageWindowOptions,host:BrowserMetadataCacheScope,
        now_seconds:u64,include_private_output:bool,mut io:F)->Result<BrowserIncomingCachePublication>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        if !include_private_output{return Err(Error::Invalid("Explicit private output consent is required."))}
        let original=BrowserMonitorFence::capture(self,&monitor,owner,Some(selected))?;
        let hint=monitor.take_pending()?.ok_or(Error::Conflict)?;
        let work=PendingIncoming{monitor,hint:Some(hint)};
        let hint=work.hint.as_ref().ok_or(Error::Conflict)?;
        // Recovery offers remain pending and never become read/write permission.
        // They need the existing explicit foreground recovery owner/protocol.
        if !hint.pending.recovery.is_empty(){return Err(Error::Unavailable {
            code:"browser_incoming_recovery_pending",reason:"EXPLICIT_BROWSER_RECOVERY_OWNER_REMAINS_REQUIRED"})}
        let selected_changed=hint.pending.refresh||hint.pending.chats.contains(selected);
        let refresh=self.refresh_browser_chat_monitor_metadata(owner,&work.monitor,hint,Some(selected)).await?;
        original.check(self)?;
        // Prepare messages BEFORE metadata persistence so an actually absent
        // selected header can be created by the original authenticated response.
        let mut selected_token=None;
        if selected_changed {
            let context=self.browser_monitor_read_context(&work.monitor,owner,selected)?;
            let slot=failures.entry(selected.into()).or_insert(None);
            let copied=serde_json::from_value(serde_json::to_value(&host)?)?;
            selected_token=Some(self.browser_prepare_retained_monitor_message_cache(context,slot,
                owner,selected,options,copied,now_seconds,true,&mut io).await?);
            original.check(self)?;
        }
        let mut metadata=self.commit_browser_chat_monitor_metadata(refresh,host,true,&mut io).await?;
        original.check(self)?;
        // Re-read the actual retained physical header/rows AFTER the last
        // metadata transaction. Protected/newer local rows remain the UI source.
        let selected=if let Some(mut token)=selected_token {
            if let Some(transition)=metadata.selected_transition.take(){
                self.browser_apply_owned_metadata_transition(&mut token,transition)?;
            }
            let slot=failures.get_mut(selected).ok_or(Error::Protocol)?;
            Some(self.browser_finish_retained_monitor_cache(token,slot,owner,selected,&mut io).await?)
        }else{None};
        original.check(self)?;
        Ok(BrowserIncomingCachePublication{work,metadata,selected})
    }
    /// Final borrowed original proof checks surround encoding; no consuming
    /// accessor releases an intermediate projection before the last fence.
    pub fn browser_incoming_cache_publication_json(&self,mut publication:BrowserIncomingCachePublication,
        include_private_output:bool)->Result<Zeroizing<String>> {
        if !include_private_output{return Err(Error::Invalid("Explicit private output consent is required."))}
        let check=|client:&Client,p:&BrowserIncomingCachePublication|->Result<()> {
            p.metadata.fence.check(client)?;
            if snapshot_stamp(client)?!=p.metadata.stamp{return Err(Error::Cancelled)}
            if let Some(selected)=&p.selected {client.browser_borrow_retained_cache_publication(selected)?;}
            Ok(())
        };
        check(self,&publication)?;
        let metadata=Plain::new(serde_json::from_str::<Value>(&publication.metadata.output)?);
        let selected=Plain::new(match &publication.selected {
            Some(selected)=>serde_json::from_str::<Value>(self.browser_borrow_retained_cache_publication(selected)?)?,
            None=>Value::Null,
        });
        let output=Plain::new(json!({"source":"browser_incoming_cache_sync","readOnly":true,
            "metadata":&*metadata,"selected":&*selected,"canonicalIncomingDurablyAcknowledged":false,
            "historyComplete":false,"inventoryComplete":false,"recoveryProof":false,
            "credentialAcknowledged":false,"nativeDurabilityAcknowledged":false}));
        if crate::client::monitor::cached_view::bounded_bytes(&*output,256*1024).is_none(){return Err(Error::Protocol)}
        let encoded=Zeroizing::new(serde_json::to_string(&*output)?);crate::client::browser::validate_local_json(&encoded)?;
        check(self,&publication)?;
        // Only successful final release consumes this exact hint. Dropped or
        // failed stages requeue it under the same original monitor fence.
        publication.work.hint.take();
        Ok(encoded)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn monitor(c:&Client)->Arc<ChatMonitor>{
        Arc::new(ChatMonitor{changes:Arc::new(Changes::default()),fence:Arc::new(MonitorFence{
            owner:c.task_watch_authority.clone(),generation:c.generation,team:None,expires_at:None,
            cancel:c.operation_cancel.child_token(),alive:AtomicBool::new(true),denial:Mutex::new(None)})})
    }
    #[test]
    fn unfinished_work_requeues_same_hint_without_losing_newer_pending(){
        let c=Client::new("http://127.0.0.1:9",None).unwrap();let m=monitor(&c);
        {let mut p=m.changes.pending.lock().unwrap();p.refresh=true;p.chats.insert("first".into());}
        let work=PendingIncoming{monitor:m.clone(),hint:m.take_pending().unwrap()};
        {let mut p=m.changes.pending.lock().unwrap();p.refresh=true;p.chats.insert("later".into());}
        drop(work);let hint=m.take_pending().unwrap().unwrap();
        assert!(hint.pending.chats.contains("first"));assert!(hint.pending.chats.contains("later"));
    }
    #[test]
    fn dropped_cancelled_a_never_requeues_into_b(){
        let c=Client::new("http://127.0.0.1:9",None).unwrap();let a=monitor(&c);let b=monitor(&c);
        a.changes.pending.lock().unwrap().refresh=true;
        let work=PendingIncoming{monitor:a.clone(),hint:a.take_pending().unwrap()};
        a.close();drop(work);assert!(b.take_pending().unwrap().is_none());
    }
}
