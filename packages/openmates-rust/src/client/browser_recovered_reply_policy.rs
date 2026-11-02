//! Pure maintained recovered-reply storage policy. No authority or receipt.
use super::*;

pub(in crate::client) fn check_planned_row(row:&Value)->Result<()>{
    crate::client::monitor::cached_view::bounded_bytes(row,crate::client::transport::MAX_BODY).ok_or(Error::Protocol).map(|_|())
}

fn open(row:&Value,key:&[u8;32])->Result<Plain<Value>>{
    row_projection(row,required(row,"chat_id")?)?;
    if !no_plaintext(row){return Err(unsupported("LEGACY_PLAINTEXT_RECOVERY_REPAIR_REMAINS_REQUIRED"))}
    let mut value=Plain::new(row.clone());
    for (cipher,clear) in ENCRYPTED.iter().zip(CLEAR.iter()){
        if row.get(*cipher).is_some_and(|v|!v.is_null()){
            let ciphertext=row[*cipher].as_str().ok_or(Error::Protocol)?;
            if !ciphertext.is_empty(){
                let plain=Zeroizing::new(sync::decrypt_optional(row,cipher,key)?);
                if *clear=="pii_mappings"{value[*clear]=serde_json::from_str(&plain)?;}else{value[*clear]=json!(plain.as_str());}
            }
        }
        value.as_object_mut().ok_or(Error::Protocol)?.remove(*cipher);
    }
    Ok(value)
}
/// Same selected-assistant cross-ID duplicate predicate used by saveMessage.
/// A positive duplicate requires the maintained alias-repair producer; never
/// delete another row or silently declare the canonical reply durable.
fn duplicate(old:&Value,new:&Value)->Result<bool>{
    message_policy::is_content_duplicate(old,new)
}
pub(in crate::client) fn source(raw:&Value,chat:&str,message:&str)->Result<Plain<Value>>{
    check_planned_row(raw)?;
    if !uuid::Uuid::parse_str(message).is_ok_and(|id|id.to_string()==message){return Err(unsupported("RECOVERED_REPLY_NATIVE_CANONICAL_UUID_REQUIRED"))}
    let mut value=incoming(raw,chat)?;
    if required(&value,"message_id")?!=message||logical_local(&value)?!=message||value["role"]!="assistant"{
        return Err(unsupported("RECOVERED_ASSISTANT_PHYSICAL_ALIAS_REPAIR_REMAINS_REQUIRED"))
    }
    required(&value,"encrypted_content")?;
    if !value["created_at"].as_u64().is_some_and(|at|at<=9_007_199_254_740_931){return Err(Error::Protocol)}
    // Actual Main recovery server commit is separately required by the driver.
    value["status"]=json!("synced");Ok(value)
}
pub(in crate::client) fn prepare(canonical:&Value,physical:&Value,candidates:&[Value],chat:&str,message:&str,key:&[u8;32])->Result<Plain<Value>>{
    if !physical.is_null(){check_planned_row(physical)?;}
    let new=source(canonical,chat,message)?;let semantic_new=open(&new,key)?;
    let mut after=if physical.is_null(){
        for raw in candidates{
            if raw["chat_id"].as_str()!=Some(chat)||raw["role"]!="assistant"||raw["message_id"].as_str()==Some(message){return Err(Error::Protocol)}
            let old=open(raw,key)?;
            if duplicate(&old,&semantic_new)?{return Err(unsupported("RECOVERY_CROSS_ID_DUPLICATE_REPAIR_REMAINS_REQUIRED"))}
        }
        Plain::new(json!({"message_id":message,"chat_id":chat,"role":"assistant","created_at":new["created_at"]}))
    }else{
        row_projection(physical,chat)?;
        if required(physical,"message_id")?!=message||logical_local(physical)?!=message||physical["role"]!="assistant"{return Err(Error::Forbidden)}
        if call_nonempty(physical)?||message_policy::has_newer_stored_revision(physical,&new)?{return Err(Error::Conflict)}
        if physical.get("queue_revision").is_some_and(|v|!v.is_null())&&new.get("queue_revision").is_none_or(Value::is_null){return Err(Error::Conflict)}
        if physical.get("large_payload").is_some_and(|v|!v.is_null()){return Err(unsupported("RECOVERY_LARGE_PAYLOAD_STORE_REMAINS_REQUIRED"))}
        if physical["key_version"].as_u64().zip(new["key_version"].as_u64()).is_some_and(|(a,b)|a>b){return Err(Error::Conflict)}
        let semantic_old=open(physical,key)?;
        if !message_policy::should_update_message(&semantic_old,&semantic_new)?
            &&!message_policy::has_new_encrypted_fields(&semantic_old,&new)?{
            if !body_matches(physical,&new,key)?{return Err(Error::Conflict)}
            return Ok(Plain::new(physical.clone()));
        }
        // Preserve unknown local fields, linked user ID, actual prior timestamp,
        // and the current raw pending journals exactly. No draft/chat writes.
        Plain::new(physical.clone())
    };
    for name in WRITES{
        if let Some(value)=new.get(*name){after[*name]=value.clone();}
    }
    if !physical.is_null()&&physical["created_at"].as_u64()==Some(0){after["created_at"]=new["created_at"].clone();}
    for name in ["id","client_message_id"]{
        if physical.is_null(){if let Some(value)=new.get(name){after[name]=value.clone();}}
    }
    if after.get("pending_encrypted_turn_preflight_v1").is_some_and(Value::is_string){after["pending_turn_preflight_v1"]=json!(1);}
    else{after.as_object_mut().ok_or(Error::Protocol)?.remove("pending_turn_preflight_v1");}
    check_planned_row(&after)?;
    if !body_matches(&after,&new,key)?{return Err(Error::Conflict)}Ok(after)
}
pub(in crate::client) fn body_matches(actual:&Value,canonical:&Value,key:&[u8;32])->Result<bool>{
    let a=open(actual,key)?;let b=open(canonical,key)?;
    if actual["message_id"]!=canonical["message_id"]||actual["chat_id"]!=canonical["chat_id"]||actual["role"]!="assistant"{return Ok(false)}
    Ok(ENCRYPTED.iter().zip(CLEAR.iter()).all(|(cipher,clear)|canonical.get(*cipher).is_none_or(|_|a.get(*clear)==b.get(*clear)))
        &&["has_thinking","thinking_token_count"].iter().all(|name|canonical.get(*name).is_none_or(|value|actual.get(*name)==Some(value))))
}
pub(in crate::client) fn physical_matches(before:&Value,written:&Value,reread:&Value,expected:&Value)->Result<()>{
    if before["db_version"]!=written["db_version"]||written["db_version"]!=reread["db_version"]
        ||written["observation"]!=reread["observation"]||reread["observation"]["record"]!=*expected
        ||before["observation"]["metadata"]!=reread["observation"]["metadata"]
        ||reread["observation"]["record"].is_null(){return Err(Error::Conflict)}Ok(())
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_recovered_reply_policy_tests.rs"]
mod tests;
