//! Shared original recovery metadata native IO; no DTO constructor or ACK.
use super::*;
use crate::client::BrowserOriginalHintRecoveryProgress;
use crate::crypto::master::MasterCapability;
use std::{rc::Rc,cell::RefCell};
pub(super) async fn io(store:&BoundInitialSyncStore,progress:&Rc<BrowserOriginalHintRecoveryProgress>,master:&MasterCapability,expected:&Value,source:&Value,observations:&RefCell<Vec<Rc<Plain<Value>>>>,change:Option<(&Value,&Value)>)->Result<Rc<Plain<Value>>>{
    let negative=||{store.original.check()?;progress.metadata_finalize_negative()?;master.ensure_current()};
    negative()?;let original=&store.original;let chat=progress.metadata_finalize_chat();let operation=uuid::Uuid::new_v4().to_string();
    let mut effect=Plain::new(json!({"kind":"openmates-metadata-native-io-v1","op_id":operation,"owner_id":original.owner.as_str(),"chat_id":chat,"operation":if change.is_some(){"compare_store"}else{"read"}}));
    if let Some((before,after))=change{effect["expected_db_version"]=before["db_version"].clone();effect["before"]=before["record"].clone();effect["after"]=after.clone();}
    let ticket=Arc::new(MetadataNativeIoTicket{original:original.clone(),operation:Zeroizing::new(operation),effect,dispatched:AtomicBool::new(false),source:None,recovery_source:Some(progress.clone()),embed_source:None});
    let actual=original.context.start(ticket.clone())?.drive().await?;
    let encoded=Zeroizing::new(actual.consume_for(&original.context,&ticket)?);negative()?;
    if encoded.len()>MAX_PACKET{return Err(Error::Protocol)}
    let frame=Plain::new(serde_json::from_str::<Value>(&encoded)?);let keys=["kind","op_id","owner_id","chat_id","db_version","record"];
    if !frame.as_object().is_some_and(|o|o.len()==keys.len()&&keys.iter().all(|k|o.contains_key(*k)))||frame["kind"]!="openmates-metadata-native-result-v1"||frame["op_id"].as_str()!=Some(ticket.operation_id())||frame["owner_id"].as_str()!=Some(original.owner.as_str())||frame["chat_id"].as_str()!=Some(chat)||!frame["db_version"].as_u64().is_some_and(|v|v>0&&v<=9_007_199_254_740_991)||!frame["record"].is_object(){return Err(Error::Protocol)}
    let mut observations=observations.borrow_mut();
    let previous=observations.iter().map(|v|&***v).collect::<Vec<&Value>>();
    if crate::client::monitor::cached_view::bounded_bytes(&(expected,source,previous,&*frame),crate::client::transport::MAX_BODY).is_none(){return Err(Error::Protocol)}
    // All completed actual envelopes stay owned even on a later CAS/journal/
    // cancellation failure. Rc aliases do not copy their unknown fields.
    let frame=Rc::new(frame);observations.push(frame.clone());Ok(frame)
}
