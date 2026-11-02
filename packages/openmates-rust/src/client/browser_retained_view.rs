//! Explicit selected cached projection from B's actual physical readback token.
//! No canonical incoming-window, complete-history, cursor, version or native ACK.
//! Rust/WASM UNRUN. Native canonical saved read/export remains unchanged.
use super::*;
use crate::client::local_cached_read::wire;
use crate::client::plaintext::replace_text;

pub(super) fn retained_projection(client:&Client,owner:&str,id:&str,metadata:&Value,rows:&[Value],
    key:&Key,dispositions:&[Value],kind:Option<&str>,mut failures:Option<&mut BrowserCandidateFailures>)->Result<Plain<Value>> {
    if rows.len()>crate::client::message_window::MAX_MESSAGES||rows.len()!=dispositions.len() {
        return Err(Error::Protocol);
    }
    let metadata=normalized(metadata,id,owner,true)?;
    let mut positions=Vec::with_capacity(rows.len());
    for (index,row) in rows.iter().enumerate() {
        let (at,physical)=wire::position(row)?;positions.push((at,physical.to_owned(),index));
    }
    positions.sort_by(|a,b|wire::position_cmp((a.0,&a.1),(b.0,&b.1)));
    let mut sorted=Plain::new(Vec::<Value>::new());
    for (_,_,index) in positions {sorted.push(rows[index].clone());}
    let normalized_rows=Plain::new(wire::message_rows(&sorted,id)?);
    let mut item=Plain::new(client.chat_item(&metadata,key)?);
    let mut chat=Plain::new(Chat {id:id.into(),title:std::mem::take(&mut item.title),
        category:std::mem::take(&mut item.category),messages:vec![]});
    let chat_metadata=Plain::new(crate::client::saved_chat_read::metadata::chat(&metadata,id,key)?);
    let mut message_metadata=Plain::new(Vec::<Value>::new());
    let mut mappings=Plain::new(BTreeMap::<String,Vec<Value>>::new());
    let mut seen=std::collections::HashSet::new();
    for row in normalized_rows.iter() {
        // Retained physical rows may be newer/protected/local. Ignore every
        // plaintext extension; only the maintained closed ciphertext decoder
        // and exact logical/storage alias policy can yield a public Message.
        if row.get("large_payload").is_some_and(|value|!value.is_null()) {
            return Err(Error::Unavailable {code:"browser_retained_exact_payload_required",
                reason:"RETAINED_LARGE_PAYLOAD_REQUIRES_EXACT_OWNED_READ"});
        }
        let closed=wire::decode_projection(row)?;
        if let Some(state)=failures.as_deref_mut() {
            let semantic=state.retained_semantic(client,owner,id,key,row)?;
            let logical=["client_message_id","message_id","id"].into_iter().map(|f|text(&closed,f)).find(|v|!v.is_empty()).ok_or(Error::Protocol)?;
            if !seen.insert(logical.to_owned()){return Err(Error::Protocol)}
            let message=Plain::new(Message{id:logical.into(),role:required(&closed,"role")?.into(),content:text(&semantic,"content").into(),sender:text(&semantic,"sender_name").into(),thinking:text(&semantic,"thinking_content").into(),..Default::default()});
            let mut scalar=Plain::new(row.clone());for field in ["encrypted_sender_name","encrypted_category","encrypted_model_name","encrypted_thinking_signature"]{scalar.as_object_mut().ok_or(Error::Protocol)?.remove(field);}
            let scalar_metadata=Plain::new(crate::client::saved_chat_read::metadata::message(&scalar,&message,id,key)?);
            let mut public=Plain::new(serde_json::to_value(&*scalar_metadata)?);
            if public["storageId"].is_null(){public["storageId"]=json!(wire::position(row)?.1);}
            for (target,source) in [("senderName","sender_name"),("category","category"),("modelName","model_name"),("thinkingSignature","thinking_signature")] {
                if semantic.get(source).and_then(Value::as_str).is_some_and(|v|v.len()>64*1024){return Err(Error::Protocol)}
                public[target]=semantic.get(source).filter(|v|v.is_string()).cloned().unwrap_or(Value::Null);
            }
            if semantic["has_thinking"].is_boolean(){public["hasThinking"]=semantic["has_thinking"].clone();}
            if let Some(values)=semantic.get("pii_mappings"){let values=values.as_array().ok_or(Error::Protocol)?;mappings.insert(message.id.clone(),values.clone());}
            message_metadata.push(public.into_inner());chat.messages.push(message.into_inner());
        } else {
            let (raw,message)=crate::client::sync::decode_chat_message(&closed,id,key,&mut seen)?;
            let raw=Plain::new(raw);let message=Plain::new(message);
            let encoded=Zeroizing::new(crate::client::sync::decrypt_optional(&raw,"encrypted_pii_mappings",key)?);
            let values=Plain::new(if encoded.is_empty(){vec![]}else{serde_json::from_str::<Vec<Value>>(&encoded)?});
            if raw.get("encrypted_pii_mappings").is_some(){mappings.insert(message.id.clone(),values.into_inner());}
            let mut public=Plain::new(crate::client::saved_chat_read::metadata::message(row,&message,id,key)?);
            if public.storage_id.is_none(){public.storage_id=Some(wire::position(row)?.1.to_owned());}
            message_metadata.push(serde_json::to_value(&*public)?);chat.messages.push(message.into_inner());
        }
    }
    // Identical maintained page-local PII interpretation: user-row mappings
    // in this retained page only, never account-wide restoration material.
    let page_mappings=Plain::new(chat.messages.iter().filter(|message|message.role=="user")
        .filter_map(|message|mappings.get(&message.id)).flatten().cloned().collect::<Vec<Value>>());
    for message in &mut chat.messages {
        let content=crate::privacy::restore_page(&message.content,&page_mappings)?;replace_text(&mut message.content,content);
        let thinking=crate::privacy::restore_page(&message.thinking,&page_mappings)?;replace_text(&mut message.thinking,thinking);
    }
    let mut exact_dispositions=Plain::new(Vec::new());
    for row in sorted.iter(){let physical=wire::position(row)?.1;let disposition=dispositions.iter().find(|d|d["messageId"].as_str()==Some(physical)).ok_or(Error::Protocol)?;
        if kind.is_some(){let incoming=disposition.get("incomingPhysicalMessageId").and_then(Value::as_str).unwrap_or(physical);
            exact_dispositions.push(json!({"messageId":physical,"storedPhysicalMessageId":physical,"incomingPhysicalMessageId":incoming,"disposition":disposition["disposition"],"incomingSuppliedWriteFieldsMatch":disposition["incomingSuppliedWriteFieldsMatch"],"canonicalIncomingDurablyAcknowledged":false}));
        }else{exact_dispositions.push(disposition.clone());}
    }
    let mut output=Plain::new(json!({"source":"browser_retained_message_cache","readOnly":true,"cached":true,"fresh":false,
        "historyComplete":false,"coverage":"retained_rows_only","chat":&*chat,"chatMetadata":&*chat_metadata,
        "messageMetadata":&*message_metadata,"piiMappingsByMessageId":&*mappings,"piiRestoration":"page_local",
        "pagesRead":0,"hasMoreBefore":null,"hasMoreAfter":null,"startCursor":null,"endCursor":null,
        "anchorFound":false,"checkpointPresentation":null,"rowDispositions":&*exact_dispositions,
        "messagesVersionAdvanced":false,"windowCoverageChanged":false,"canonicalIncomingDurablyAcknowledged":false,
        "credentialAcknowledged":false,"nativeDurabilityAcknowledged":false,"crossDatabaseAssociationProven":false,
        "inventoryComplete":false,"recoveryProof":false}));
    if let Some(kind)=kind {output["cacheReadKind"]=json!(kind);output["contentCoverage"]=json!("unknown");}
    if crate::client::monitor::cached_view::bounded_bytes(&*output,256*1024).is_none(){return Err(Error::Protocol);}
    Ok(output)
}
/// Sealed cached output retains its ORIGINAL request/master/monitor fences until release.
pub struct BrowserRetainedCachePublication {token:BrowserRetainedMessageCache,output:Zeroizing<String>}
impl Client {
    /// One original bounded authoritative read + actual existing-row transaction,
    /// followed by SAME physical-row readback immediately before cached projection.
    /// The result reflects retained/local store state, not the incoming canonical
    /// window. This method cannot mint native durability or FreshChatInventory.
    pub async fn browser_retained_saved_chat_with_io_json<F,Fut>(&mut self,owner:&str,id:&str,
        options:crate::client::message_window::MessageWindowOptions,host_scope:BrowserMetadataCacheScope,
        include_private_output:bool,mut io:F)->Result<Zeroizing<String>>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        let token=self.browser_prepare_retained_message_cache(owner,id,options,host_scope,
            include_private_output,&mut io).await?;
        token.ensure_current(self)?;
        let view=self.browser_revalidate_retained_message_cache(&token,&mut io).await?;
        let output=view.with_rows(|metadata,rows,key,dispositions|
            retained_projection(self,owner,id,metadata,rows,key,dispositions,None,None))?;
        let encoded=Zeroizing::new(serde_json::to_string(&*output)?);local_json::validate(&encoded)?;
        view.ensure_current()?;token.ensure_current(self)?;
        Ok(encoded)
    }
    pub async fn prepare_browser_cold_retained_saved_chat_with_io<F,Fut>(&mut self,owner:&str,id:&str,options:crate::client::message_window::MessageWindowOptions,host_scope:BrowserMetadataCacheScope,now_seconds:u64,include_private_output:bool,mut io:F)->Result<BrowserRetainedCachePublication>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        let token=self.browser_prepare_retained_cold_message_cache(owner,id,options,host_scope,now_seconds,include_private_output,&mut io).await?;
        let view=self.browser_revalidate_retained_message_cache(&token,&mut io).await?;
        let output=view.with_rows(|metadata,rows,key,dispositions|retained_projection(self,owner,id,metadata,rows,key,dispositions,Some("cold"),None))?;
        let encoded=Zeroizing::new(serde_json::to_string(&*output)?);local_json::validate(&encoded)?;view.ensure_current()?;token.ensure_current(self)?;drop(view);Ok(BrowserRetainedCachePublication{token,output:encoded})
    }
    pub async fn prepare_browser_monitored_retained_saved_chat_with_io<F,Fut>(&mut self,monitor:&crate::client::monitor::ChatMonitor,failures:&mut Option<BrowserCandidateFailures>,owner:&str,id:&str,options:crate::client::message_window::MessageWindowOptions,host_scope:BrowserMetadataCacheScope,now_seconds:u64,include_private_output:bool,mut io:F)->Result<BrowserRetainedCachePublication>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        let context=self.browser_monitor_read_context(monitor,owner,id)?;
        let token=self.browser_prepare_retained_monitor_message_cache(context,failures,owner,id,options,host_scope,now_seconds,include_private_output,&mut io).await?;
        self.browser_finish_retained_monitor_cache(token,failures,owner,id,&mut io).await
    }
    pub(crate) async fn browser_finish_retained_monitor_cache<F,Fut>(&self,token:BrowserRetainedMessageCache,failures:&mut Option<BrowserCandidateFailures>,owner:&str,id:&str,mut io:F)->Result<BrowserRetainedCachePublication>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        let view=self.browser_revalidate_retained_message_cache(&token,&mut io).await?;
        let output=view.with_rows(|metadata,rows,key,dispositions|retained_projection(self,owner,id,metadata,rows,key,dispositions,Some("monitor"),Some(failures.as_mut().ok_or(Error::Protocol)?)))?;
        let encoded=Zeroizing::new(serde_json::to_string(&*output)?);local_json::validate(&encoded)?;view.ensure_current()?;token.ensure_current(self)?;drop(view);Ok(BrowserRetainedCachePublication{token,output:encoded})
    }

    pub(crate) fn browser_borrow_retained_cache_publication<'a>(&self,publication:&'a BrowserRetainedCachePublication)->Result<&'a str> {
        publication.token.ensure_current(self)?;Ok(&publication.output)
    }
    pub fn browser_retained_cache_publication_json(&self,publication:BrowserRetainedCachePublication,include_private_output:bool)->Result<Zeroizing<String>> {
        if !include_private_output{return Err(Error::Invalid("Explicit private output consent is required."))}
        publication.token.ensure_current(self)?;Ok(publication.output)
    }

}
#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_retained_view_tests.rs"]
mod tests;
