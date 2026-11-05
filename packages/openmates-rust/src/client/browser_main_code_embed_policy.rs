//! Narrow pure deployed code-embed row/key policy. Values are DATA, never proof.
use super::*;
use super::plaintext::Plain;
pub(in crate::client) fn bound(v:&impl serde::Serialize)->Result<()>{crate::client::monitor::cached_view::bounded_bytes(v,crate::client::transport::MAX_BODY).ok_or(Error::Protocol).map(|_|())}
pub(in crate::client) fn source(raw:&Value,owner:&str,chat:&str,message:&str)->Result<Plain<Value>>{
 bound(raw)?;let id=required(raw,"embed_id")?;
 if !uuid::Uuid::parse_str(id).is_ok_and(|v|v.to_string()==id)||raw["user_id"].as_str()!=Some(owner)
  ||![chat,sha256(chat).as_str()].contains(&required(raw,"chat_id")?)||![message,sha256(message).as_str()].contains(&required(raw,"message_id")?)
  ||raw["already_encrypted"]!=true||raw["encryption_mode"]!="client"||raw["status"]!="finished"
  ||raw["version_number"]!=json!(1)||raw.get("parent_embed_id").is_some_and(|v|!v.is_null())
  ||raw.get("embed_ids").is_some_and(|v|!v.is_null()&&!v.as_array().is_some_and(Vec::is_empty))
  ||raw["embed_keys_has_more_after"]!=false{return Err(Error::Forbidden)}
 for field in ["content","type"]{required(raw,field)?;}
 for field in ["is_private","is_shared"]{if raw.get(field).is_some_and(|v|!v.is_null()&&!v.is_boolean()){return Err(Error::Protocol)}}
 let created=raw["createdAt"].as_u64().ok_or(Error::Protocol)?;let updated=raw["updatedAt"].as_u64().ok_or(Error::Protocol)?;
 if created>9_007_199_254_740_991||updated>9_007_199_254_740_991{return Err(Error::Protocol)}
 let mut entry=Plain::new(json!({"contentRef":format!("embed:{id}"),"type":"code","createdAt":created,"updatedAt":updated,
  "embed_id":id,"encrypted_content":raw["content"],"encrypted_type":raw["type"],"encrypted_text_preview":raw["encrypted_text_preview"],
  "status":"finished","hashed_chat_id":sha256(chat),"hashed_message_id":sha256(message),"hashed_user_id":sha256(owner),
  "version_number":1,"is_private":raw["is_private"].as_bool().unwrap_or(false),"is_shared":raw["is_shared"].as_bool().unwrap_or(false),"encryption_mode":"client"}));
 for field in ["embed_ids","parent_embed_id","file_path","content_hash","text_length_chars"]{if let Some(value)=raw.get(field){
  if !value.is_null()&&match field{"embed_ids"=>!value.as_array().is_some_and(Vec::is_empty),"parent_embed_id"=>true,"text_length_chars"=>!value.as_u64().is_some_and(|n|n<=9_007_199_254_740_991),_=>!value.as_str().is_some_and(|s|s.len()<=4096)}{return Err(Error::Protocol)}
  entry[field]=value.clone();
 }}
 bound(&*entry)?;Ok(entry)
}
pub(in crate::client) fn wrapper(row:&Value,owner:&str,chat:&str,id:&str)->Result<()>{
 bound(row)?;
 if row["hashed_embed_id"].as_str()!=Some(sha256(id).as_str())||row["hashed_user_id"].as_str()!=Some(sha256(owner).as_str())
  ||["hashed_team_id","hashed_project_id"].iter().any(|f|row.get(*f).is_some_and(|v|!v.is_null())){return Err(Error::Forbidden)}
 match row["key_type"].as_str(){Some("master") if row.get("hashed_chat_id").is_none_or(Value::is_null)=>{},Some("chat") if row["hashed_chat_id"].as_str()==Some(sha256(chat).as_str())=>{},_=>return Err(Error::Forbidden)}
 required(row,"encrypted_embed_key")?;Ok(())
}
pub(in crate::client) fn key_id(row:&Value)->Result<String>{Ok(format!("{}:{}:{}",required(row,"hashed_embed_id")?,required(row,"key_type")?,row["hashed_chat_id"].as_str().unwrap_or("null")))}
pub(in crate::client) fn merge(source:&Value,before:&Value,owner:&str,chat:&str,message:&str)->Result<Plain<Value>>{
 let mut after=if before.is_null(){Plain::new(json!({}))}else{
  bound(before)?;
  if before["contentRef"]!=source["contentRef"]||before["embed_id"]!=source["embed_id"]||before["hashed_chat_id"].as_str()!=Some(sha256(chat).as_str())
   ||before["hashed_message_id"].as_str()!=Some(sha256(message).as_str())||before["hashed_user_id"].as_str()!=Some(sha256(owner).as_str())
   ||before["version_number"].as_u64().is_some_and(|v|v>1)||before["updatedAt"].as_u64().zip(source["updatedAt"].as_u64()).is_some_and(|(a,b)|a>b)
   ||before.get("data").is_some_and(|v|!v.is_null())||before.get("parent_embed_id").is_some_and(|v|!v.is_null())
   ||before.get("encryption_mode").is_some_and(|v|v!="client")
   ||!["processing","finished"].contains(&before["status"].as_str().unwrap_or("")){return Err(Error::Conflict)}
  Plain::new(before.clone())
 };
 for (name,value) in source.as_object().ok_or(Error::Protocol)?{after[name]=value.clone();}
 bound(&*after)?;Ok(after)
}
pub(in crate::client) fn verify_physical(before:&Value,written:&Value,reread:&Value,after:&Value)->Result<()>{
 if before["db_version"]!=written["db_version"]||written["db_version"]!=reread["db_version"]||written["observation"]!=reread["observation"]
  ||reread["observation"]["metadata"]!=before["observation"]["metadata"]||reread["observation"]["record"]!=after["record"]
  ||reread["observation"]["keys"]!=after["keys"]||after["record"].is_null(){return Err(Error::Conflict)}
 let keys=after["keys"].as_array().ok_or(Error::Protocol)?;let targets=reread["observation"]["key_targets"].as_array().ok_or(Error::Protocol)?;
 if keys.len()!=2||targets.len()!=2||targets.iter().any(|v|!keys.contains(v)){return Err(Error::Conflict)}Ok(())
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_main_code_embed_policy_tests.rs"]
mod tests;
