//! Original-monitor-only matching candidate preparation and atomic replacement.
use super::*;
use crate::client::monitor::BrowserMonitorReadContext;
/// Rust-only state. Never serialized, constructed by a host or used as authority.
pub struct BrowserCandidateFailures {
 owner:String,chat:String,scope:AsyncCryptoScope,epoch:u64,binding:Zeroizing<[u8;32]>,
 policy:candidate_policy::KeyFailures,
}
impl BrowserCandidateFailures {
 /// Restricts retained cache lifetime only; never authorization or freshness.
 pub fn is_current(&self,client:&Client)->bool {
  self.scope.check_chat(client,&self.chat).is_ok()&&self.epoch==client.fresh_auth.operation_epoch()
   &&client.fresh_auth_binding().is_ok_and(|v|v==*self.binding)
 }

 pub(in crate::client) fn retained_semantic(&mut self,c:&Client,owner:&str,chat:&str,key:&Key,row:&Value)->Result<Plain<Value>> {
  if !self.reusable(c,owner,chat,key){return Err(Error::Cancelled)}
  let closed=Plain::new(wire::decode_projection(row)?);
  let output=self.policy.project(&closed,chat,candidate_policy::ReadMode::Connected)?;
  if !self.reusable(c,owner,chat,key){return Err(Error::Cancelled)}Ok(output)
 }

 fn reusable(&self,c:&Client,owner:&str,chat:&str,key:&Key)->bool {
  self.owner==owner&&self.chat==chat&&self.scope.check_chat(c,chat).is_ok()
   &&self.epoch==c.fresh_auth.operation_epoch()
   &&c.fresh_auth_binding().is_ok_and(|v|v==*self.binding)&&self.policy.same_key(key)
 }
}
const DELETE_FIELDS:&[&str]=&["id","message_id","client_message_id","chat_id","created_at","role","status","key_version","has_thinking","thinking_token_count","queue_revision","encrypted_content","encrypted_sender_name","encrypted_category","encrypted_model_name","encrypted_thinking_content","encrypted_thinking_signature","encrypted_pii_mappings"];
fn deletion_guard(old:&Value,new:&Value,chat:&str,key:&Key)->Result<()> {
 row_projection(old,chat)?;
 if !old.as_object().is_some_and(|o|o.keys().all(|k|DELETE_FIELDS.contains(&k.as_str())))
  ||!matches!(old["status"].as_str(),Some("synced"|"delivered"))||!no_plaintext(old)||call_nonempty(old)?||message_policy::has_newer_stored_revision(old,new)? {
  return Err(unsupported("PROTECTED_LOCAL_UNKNOWN_DUPLICATE_REPLACEMENT_REQUIRES_OWNED_RECOVERY"));
 }
 if old["key_version"].as_u64().is_some_and(|v|new["key_version"].as_u64().is_none_or(|n|n<v))
  ||old["queue_revision"].as_u64().is_some_and(|v|new["queue_revision"].as_u64().is_none_or(|n|n<v)) {
  return Err(unsupported("DUPLICATE_VERSION_AUTHORITY_REQUIRES_OWNED_RECOVERY"));
 }
 // Independent original-key ownership/authentication check, never fresh
 // admission and never a failure-cache result authorizing a destructive write.
 for field in ENCRYPTED {
  if old.get(*field).and_then(Value::as_str).is_some_and(|v|!v.is_empty()) {
   let plain=Zeroizing::new(candidate_policy::browser_decrypt(old,field,key)?);
   if *field=="encrypted_pii_mappings" {let _parsed=Plain::new(serde_json::from_str::<Value>(&plain)?);}
  }
 }
 Ok(())
}
impl Client {
 fn replacement_check(&self,ctx:&BrowserMonitorReadContext,fence:&Fence,owner:&str,chat:&str)->Result<()> {
  ctx.ensure_current(self,owner,chat)?;
  self.metadata_cache_check(fence,owner,chat,BrowserMetadataCacheMode::PersistCurrent)
 }
 async fn replacement_io<F,Fut>(&self,ctx:&BrowserMonitorReadContext,fence:&Fence,owner:&str,chat:&str,plan:&Value,io:&mut F)->Result<Plain<Value>>
 where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
  self.replacement_check(ctx,fence,owner,chat)?;
  let encoded=Zeroizing::new(serde_json::to_string(plan)?);local_json::validate(&encoded)?;
  let result=io(encoded.to_string()).await.map(Zeroizing::new);
  self.replacement_check(ctx,fence,owner,chat)?;
  let result=result?;local_json::validate(&result)?;let value=Plain::new(serde_json::from_str::<Value>(&result)?);
  if !closed(&value,&["version","kind","operationId","databaseVersion","transactionCommitted","credentialAcknowledged","crossDatabaseAssociationProven","metadata","rows","before","candidates","beforeCandidates","deleted"])
   ||value["version"]!=1||value["kind"]!=plan["kind"]||value["operationId"]!=plan["operationId"]
   ||value["transactionCommitted"]!=true||value["credentialAcknowledged"]!=false||value["crossDatabaseAssociationProven"]!=false
   ||safe_number(&value["databaseVersion"])?==0||plan["databaseVersion"].as_u64().is_some_and(|v|value["databaseVersion"].as_u64()!=Some(v))
   ||value["rows"].as_array().ok_or(Error::Protocol)?.len()!=plan["messageIds"].as_array().ok_or(Error::Protocol)?.len() {
   return Err(Error::Protocol)
  }
  Ok(value)
 }
 /// Matching duplicate decisions require a same-Rust-monitor read context.
 /// Generic HTTP first-page cache APIs never acquire this deletion authority.
 pub(crate) async fn browser_prepare_retained_monitor_message_cache<F,Fut>(
  &mut self,ctx:BrowserMonitorReadContext,failures:&mut Option<BrowserCandidateFailures>,
  owner:&str,chat:&str,options:crate::client::message_window::MessageWindowOptions,
  host_scope:BrowserMetadataCacheScope,now_seconds:u64,include_private_output:bool,mut io:F,
 )->Result<BrowserRetainedMessageCache>
 where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
  if !include_private_output{return Err(Error::Invalid("Explicit private output consent is required."))}
  if now_seconds>MAX_SAFE||host_scope.lifecycle_generation==0||host_scope.lifecycle_generation>MAX_SAFE||host_scope.workspace_epoch>MAX_SAFE{return Err(Error::Protocol)}
  ctx.ensure_current(self,owner,chat)?;
  self.metadata_cache_scope(owner,chat,BrowserMetadataCacheMode::PersistCurrent)?;self.verify_private_operation()?;
  let fence=Fence{parent:self.operation_parent.clone(),private_gate:self.options.private_operation_gate.clone(),scope:AsyncCryptoScope::begin(self)?,epoch:self.fresh_auth.operation_epoch(),binding:Zeroizing::new(self.fresh_auth_binding()?),source_stamp:source_stamp(self,chat)?,revision:self.credential_revision};
  self.replacement_check(&ctx,&fence,owner,chat)?;
  let mut page=Plain::new(self.read_browser_cache_message_page(chat,options).await?);
  self.replacement_check(&ctx,&fence,owner,chat)?;
  let raw=page.incoming.take().ok_or(Error::Protocol)?;
  if !failures.as_ref().is_some_and(|s|s.reusable(self,owner,chat,&raw.key)) {
   *failures=Some(BrowserCandidateFailures{owner:owner.into(),chat:chat.into(),scope:AsyncCryptoScope::begin(self)?,epoch:fence.epoch,binding:Zeroizing::new(*fence.binding),policy:candidate_policy::KeyFailures::new(&raw.key)});
  }
  let data=self.cache_monitor_candidates(&ctx,&fence,failures.as_mut().ok_or(Error::Protocol)?,owner,chat,host_scope,now_seconds,raw,&mut io).await?;
  self.replacement_check(&ctx,&fence,owner,chat)?;
  Ok(BrowserRetainedMessageCache{fence,monitor_context:Some(ctx),owner:owner.into(),chat:chat.into(),data})
 }
 async fn cache_monitor_candidates<F,Fut>(&self,ctx:&BrowserMonitorReadContext,fence:&Fence,failures:&mut BrowserCandidateFailures,owner:&str,chat:&str,host:BrowserMetadataCacheScope,now_seconds:u64,raw:crate::client::message_window::BrowserIncomingMessagePage,io:&mut F)->Result<RetainedData>
 where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
  self.replacement_check(ctx,fence,owner,chat)?;
  if !failures.reusable(self,owner,chat,&raw.key){return Err(Error::Cancelled)}
  let source=packet_source_stamp(&raw.metadata,&raw.messages)?;
  normalized(&raw.metadata,chat,owner,false)?;
  let mut rows=Plain::new(Vec::new());for row in raw.messages.iter(){rows.push(incoming(row,chat)?.into_inner());}
  if rows.len()>crate::client::message_window::MAX_MESSAGES{return Err(Error::Protocol)}
  rows.sort_by(|a,b|wire::idb_key_cmp(text(a,"message_id"),text(b,"message_id")));
  let ids=rows.iter().map(|r|required(r,"message_id").map(str::to_owned)).collect::<Result<Vec<_>>>()?;
  if ids.windows(2).any(|p|p[0]==p[1]){return Err(Error::Protocol)}
  let queries=Plain::new(rows.iter().filter(|r|r["role"]=="assistant").map(|r|json!({"messageId":r["message_id"],"encryptedContent":r["encrypted_content"],"createdAt":r["created_at"]})).collect::<Vec<_>>());
  let mut plan=Plain::new(json!({"version":1,"kind":"capture_monitor_candidates","operationId":uuid::Uuid::new_v4().to_string(),"scope":host,"owner":owner,"chatId":chat,"database":"chats_db","stores":["chats","messages"],"databaseVersion":null,"messageIds":ids,"metadataFields":PREDICATES,"messageFields":MESSAGE_FIELDS,"candidateQueries":&*queries,"metadataInsert":null,"expectedMetadata":null,"expectedRows":null,"expectedCandidates":null,"patches":null,"candidateDeletes":null}));
  let proposed_header=header::build(&raw.metadata,None,now_seconds)?;header::validate_create(&proposed_header,chat,owner)?;
  for field in super::super::CIPHERS {let _plain=Zeroizing::new(sync::decrypt_optional(&proposed_header,field,&raw.key)?);}
  plan["metadataInsert"]=json!(&*proposed_header);
  let capture=self.replacement_io(ctx,fence,owner,chat,&plan,io).await?;
  if !capture["before"].is_null()||!capture["beforeCandidates"].is_null()||capture["deleted"]!=json!([]){return Err(Error::Protocol)}
  let header_missing=capture["metadata"].is_null();
  let effective=if header_missing{&*proposed_header}else{&capture["metadata"]};
  let meta=projection(effective,chat,owner,true)?;
  let old_key=if header_missing{raw.key.clone()}else{let normal=normalized(&meta,chat,owner,false)?;let master=self.master_capability()?;self.chat_key_with_capability_from(&normal,&master,&[]).await?};
  self.replacement_check(ctx,fence,owner,chat)?;
  if old_key.as_ref()!=raw.key.as_ref(){return Err(unsupported("DUPLICATE_KEY_ROTATION_REQUIRES_OWNED_RECOVERY"))}
  let candidates=capture["candidates"].as_array().ok_or(Error::Protocol)?;
  if candidates.len()!=queries.len(){return Err(Error::Protocol)}
  let mut expected_candidates=Plain::new(Vec::new());
  for (query,frame) in queries.iter().zip(candidates){
   if !closed(frame,&["messageId","rows"])||frame["messageId"]!=query["messageId"]{return Err(Error::Protocol)}
   let set=frame["rows"].as_array().ok_or(Error::Protocol)?;if !capture["rows"][ids.iter().position(|id|Some(id.as_str())==query["messageId"].as_str()).ok_or(Error::Protocol)?].is_null()&&!set.is_empty(){return Err(Error::Protocol)}let mut predicates=Plain::new(Vec::new());let mut last:Option<(u64,&str)>=None;
   for row in set {
    let id=required(row,"message_id")?;let created=safe_number(&row["created_at"])?;
    if row["chat_id"]!=chat||row["role"]!="assistant"||row["message_id"]==query["messageId"]||row["encrypted_content"]!=query["encryptedContent"]||created.abs_diff(safe_number(&query["createdAt"])?)>=60{return Err(Error::Protocol)}
    if let Some((time,prior))=last {if created<time||created==time&&wire::idb_key_cmp(prior,id)!=std::cmp::Ordering::Less{return Err(Error::Protocol)}}last=Some((created,id));
    predicates.push(row_predicate(row,chat)?.into_inner());
   }
   expected_candidates.push(json!({"messageId":frame["messageId"],"rows":&*predicates}));
  }
  let mut expected=Plain::new(Vec::new());let mut patches=Plain::new(Vec::new());let mut selected=std::collections::BTreeMap::<String,Value>::new();let mut deletes=std::collections::BTreeSet::<String>::new();let mut delete_targets=std::collections::BTreeMap::<String,String>::new();let mut updated=0usize;
  for (offset,new) in rows.iter().enumerate(){
   let old=&capture["rows"][offset];
   if !old.is_null(){
    if old["message_id"]!=new["message_id"]{return Err(Error::Conflict)}expected.push(row_predicate(old,chat)?.into_inner());
    let patch=message_patch(old,new,chat,&raw.key)?;let changed=!patch["set"].as_object().ok_or(Error::Protocol)?.is_empty()||!patch["remove"].as_array().ok_or(Error::Protocol)?.is_empty();if changed{updated+=1}
    patches.push(patch.into_inner());if selected.insert(required(new,"message_id")?.into(),json!({"messageId":new["message_id"],"incomingPhysicalMessageId":new["message_id"],"disposition":if changed{"merged"}else{"retained"},"canonicalIncomingDurablyAcknowledged":false})).is_some(){return Err(unsupported("MULTIPLE_SOURCE_ROWS_SELECT_ONE_PHYSICAL_CANDIDATE"))}continue;
   }
   expected.push(Value::Null);validate_remaining_incoming(new,&raw.key)?;
   let frame=candidates.iter().find(|f|f["messageId"]==new["message_id"]);let mut semantic=Plain::new(Vec::new());
   if let Some(frame)=frame {for row in frame["rows"].as_array().ok_or(Error::Protocol)?{
    self.replacement_check(ctx,fence,owner,chat)?;
    semantic.push(failures.policy.project(row,chat,candidate_policy::ReadMode::Connected)?.into_inner());
    self.replacement_check(ctx,fence,owner,chat)?;
   }}
   let decision=candidate_policy::select(&semantic,new)?;
   let (actual,disposition)=match decision {
    candidate_policy::Selection::Retain(index)=>{
     let old=&frame.ok_or(Error::Protocol)?["rows"][index];let actual=required(old,"message_id")?.to_owned();
     if ids.contains(&actual){return Err(unsupported("RETAINED_DUPLICATE_IS_ANOTHER_INCOMING_PHYSICAL_TARGET"))}
     patches.push(json!({"messageId":new["message_id"],"retainCandidateId":actual}));(actual,"retained")
    },
    candidate_policy::Selection::NoDuplicate|candidate_policy::Selection::Replace(_)=>{
     if let candidate_policy::Selection::Replace(index)=decision {let old=&frame.ok_or(Error::Protocol)?["rows"][index];deletion_guard(old,new,chat,&raw.key)?;let id=required(old,"message_id")?.to_owned();if ids.contains(&id)||!deletes.insert(id.clone()){return Err(unsupported("CONFLICTING_DUPLICATE_MUTATIONS_REQUIRE_OWNED_RECOVERY"))}delete_targets.insert(id,required(new,"message_id")?.into());}
     let mut insert=Plain::new(json!({}));for field in DELETE_FIELDS {if let Some(v)=new.get(*field){insert[*field]=v.clone();}}
     row_projection(&insert,chat)?;patches.push(json!({"messageId":new["message_id"],"insert":&*insert}));updated+=1;
     (required(new,"message_id")?.to_owned(),if matches!(decision,candidate_policy::Selection::Replace(_)){"replaced"}else{"inserted"})
    }
   };
   if selected.insert(actual.clone(),json!({"messageId":actual,"incomingPhysicalMessageId":new["message_id"],"disposition":disposition,"canonicalIncomingDurablyAcknowledged":false})).is_some(){return Err(unsupported("MULTIPLE_SOURCE_ROWS_SELECT_ONE_PHYSICAL_CANDIDATE"))}
  }
  if selected.keys().any(|id|deletes.contains(id)){return Err(unsupported("RETAINED_CANDIDATE_CANNOT_ALSO_BE_DELETED"))}
  plan["kind"]=json!("compare_and_replace_monitor_candidates");plan["databaseVersion"]=capture["databaseVersion"].clone();plan["expectedMetadata"]=if header_missing{Value::Null}else{meta.clone()};plan["expectedRows"]=json!(&*expected);plan["expectedCandidates"]=json!(&*expected_candidates);plan["patches"]=json!(&*patches);plan["candidateDeletes"]=json!(delete_targets.iter().map(|(message_id,replacement)|json!({"messageId":message_id,"replacementMessageId":replacement})).collect::<Vec<_>>());
  let committed=self.replacement_io(ctx,fence,owner,chat,&plan,io).await?;
  if header_missing&&committed["metadata"]!=*proposed_header{return Err(Error::Protocol)}
  if *projection(&committed["metadata"],chat,owner,true)?!=*meta||committed["deleted"]!=plan["candidateDeletes"]||committed["before"].as_array().ok_or(Error::Protocol)?.len()!=rows.len(){return Err(Error::Protocol)}
  // Validate every declared target effect against actual before/after readback.
  for (index,patch) in patches.iter().enumerate(){let before=&committed["before"][index];let after=&committed["rows"][index];
   if expected[index].is_null(){if !before.is_null(){return Err(Error::Conflict)}if patch.get("retainCandidateId").is_some(){if !after.is_null(){return Err(Error::Protocol)}}else if after!=&patch["insert"]{return Err(Error::Protocol)}}else{if *row_predicate(before,chat)?!=expected[index]{return Err(Error::Conflict)}let mut wanted=Plain::new(before.clone());for(k,v)in patch["set"].as_object().ok_or(Error::Protocol)?{wanted[k]=v.clone();}for field in patch["remove"].as_array().ok_or(Error::Protocol)?{wanted.as_object_mut().unwrap().remove(field.as_str().ok_or(Error::Protocol)?);}if &*wanted!=after{return Err(Error::Protocol)}}
  }
  // Verify actual in-transaction candidate preimages, then reproduce all
  // after-set effects. Unknown/local retained fields must survive byte-for-byte.
  let before_candidates=committed["beforeCandidates"].as_array().ok_or(Error::Protocol)?;
  let actual_candidates=committed["candidates"].as_array().ok_or(Error::Protocol)?;
  if before_candidates.len()!=candidates.len()||actual_candidates.len()!=candidates.len(){return Err(Error::Protocol)}
  let mut universe=Plain::new(json!({}));
  for (frame,expected) in before_candidates.iter().zip(expected_candidates.iter()) {
   if !closed(frame,&["messageId","rows"])||frame["messageId"]!=expected["messageId"]{return Err(Error::Protocol)}
   let set=frame["rows"].as_array().ok_or(Error::Protocol)?;let predicates=expected["rows"].as_array().ok_or(Error::Protocol)?;
   if set.len()!=predicates.len(){return Err(Error::Conflict)}
   for(row,predicate)in set.iter().zip(predicates){if *row_predicate(row,chat)?!=*predicate{return Err(Error::Conflict)}let id=required(row,"message_id")?;if let Some(target)=delete_targets.get(id){let new=rows.iter().find(|r|r["message_id"].as_str()==Some(target.as_str())).ok_or(Error::Protocol)?;deletion_guard(row,new,chat,&raw.key)?;}if let Some(prior)=universe.as_object_mut().ok_or(Error::Protocol)?.insert(id.into(),row.clone()){if prior!=*row{return Err(Error::Protocol)}}}
  }
  for row in committed["rows"].as_array().unwrap().iter().filter(|v|!v.is_null()){universe.as_object_mut().ok_or(Error::Protocol)?.insert(required(row,"message_id")?.into(),row.clone());}
  for id in &deletes {universe.as_object_mut().ok_or(Error::Protocol)?.remove(id);}
  for (query,actual) in queries.iter().zip(actual_candidates) {
   if !closed(actual,&["messageId","rows"])||actual["messageId"]!=query["messageId"]{return Err(Error::Protocol)}
   let active=capture["rows"][ids.iter().position(|id|Some(id.as_str())==query["messageId"].as_str()).ok_or(Error::Protocol)?].is_null();
   let mut wanted=Plain::new(universe.as_object().ok_or(Error::Protocol)?.values().filter(|r|active&&r["chat_id"]==chat&&r["role"]=="assistant"&&r["message_id"]!=query["messageId"]&&r["encrypted_content"]==query["encryptedContent"]&&r["created_at"].as_u64().zip(query["createdAt"].as_u64()).is_some_and(|(a,b)|a.abs_diff(b)<60)).cloned().collect::<Vec<_>>());
   wanted.sort_by(|a,b|a["created_at"].as_u64().cmp(&b["created_at"].as_u64()).then_with(||wire::idb_key_cmp(text(a,"message_id"),text(b,"message_id"))));
   if actual["rows"]!=json!(&*wanted){return Err(Error::Protocol)}
  }
  let mut final_rows=Plain::new(Vec::new());let mut dispositions=Plain::new(Vec::new());let mut final_ids=selected.keys().cloned().collect::<Vec<_>>();final_ids.sort_by(|a,b|wire::idb_key_cmp(a,b));
  for id in &final_ids {let actual=committed["rows"].as_array().unwrap().iter().chain(actual_candidates.iter().filter_map(|f|f["rows"].as_array()).flatten()).find(|r|r["message_id"].as_str()==Some(id.as_str())).ok_or(Error::Protocol)?;
   final_rows.push(row_predicate(actual,chat)?.into_inner());let mut disposition=Plain::new(selected.get(id).ok_or(Error::Protocol)?.clone());
   let source=rows.iter().find(|row|row["message_id"]==disposition["incomingPhysicalMessageId"]).ok_or(Error::Protocol)?;
   disposition["incomingSuppliedWriteFieldsMatch"]=json!(WRITES.iter().filter_map(|field|source.get(*field).map(|v|(*field,v))).all(|(field,value)|actual.get(field)==Some(value)));
   dispositions.push(disposition.into_inner());
  }
  let read_plan=Plain::new(json!({"version":1,"kind":if final_ids.is_empty(){"readback_metadata_only"}else{"readback"},"operationId":plan["operationId"],"scope":host,"owner":owner,"chatId":chat,"database":"chats_db","stores":["chats","messages"],"databaseVersion":capture["databaseVersion"],"messageIds":final_ids,"metadataFields":PREDICATES,"messageFields":MESSAGE_FIELDS,"expectedMetadata":&*meta,"expectedRows":&*final_rows,"patches":null}));
  self.replacement_check(ctx,fence,owner,chat)?;let readback=self.message_cache_io(fence,owner,chat,&read_plan,io).await?;self.replacement_check(ctx,fence,owner,chat)?;
  if !readback["before"].is_null()||*projection(&readback["metadata"],chat,owner,true)?!=*meta{return Err(Error::Conflict)}
  for(index,row)in readback["rows"].as_array().ok_or(Error::Protocol)?.iter().enumerate(){if *row_predicate(row,chat)?!=final_rows[index]{return Err(Error::Conflict)}}
  if packet_source_stamp(&raw.metadata,&raw.messages)?!=source{return Err(Error::Cancelled)}
  let summary=Zeroizing::new(json!({"source":"browser_message_cache","cached":true,"fresh":false,"readOnly":true,"historyComplete":false,"contentCoverage":"unknown","metadataHeaderInserted":header_missing,"messagesVersionMeaning":"metadata_inventory_only","rowsConsidered":rows.len(),"rowsUpdated":updated,"rowsRetained":rows.len()-updated,"messagesVersionAdvanced":false,"windowCoverageChanged":false,"credentialAcknowledged":false,"nativeDurabilityAcknowledged":false}).to_string());local_json::validate(&summary)?;
  self.replacement_check(ctx,fence,owner,chat)?;
  Ok(RetainedData{plan:read_plan,readback,dispositions,summary,key:raw.key})
 }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_cache_replacement_tests.rs"]
mod tests;
