//! Private native continuation of ONE genuine selected Cookie read. Not OMCR2
//! output identity/coverage, server ACK or a transcript-derived embed grant.
use super::*;
use crate::crypto::master::MasterCapability;
use crate::client::main_code_embed_policy as policy;
impl SavedEmbedRead {
 pub(in crate::client) fn main_native_negative(&self)->Result<()>{self.scope.check_original_negative()}
 pub(in crate::client) fn check_main_native(&self,client:&Client,owner:&str,chat:&str,message:&str)->Result<()>{
  self.check(client)?;
  policy::source(&self.native_source,owner,chat,message)?;
  if self.source.hash!=sha256(chat)||!self.value["parent_embed_id"].is_null(){return Err(Error::Forbidden)}
  self.main_native_negative()
 }
 pub(in crate::client) fn main_native_identity(&self)->Result<(&str,&Value)>{
  self.main_native_negative()?;Ok((required(&self.value,"embed_id")?,&self.native_source))
 }
 pub(in crate::client) fn main_native_bytes(&self)->Result<usize>{self.main_native_negative()?;crate::client::monitor::cached_view::bounded_bytes(&(&*self.native_source,&*self.value),2*MAX_BYTES).ok_or(Error::Protocol)}
 pub(in crate::client) async fn plan_main_native(&self,owner:&str,chat:&str,message:&str,chat_key:&[u8;32],master:&MasterCapability,before:&Value)->Result<Plain<Value>>{
  self.main_native_negative()?;let source=policy::source(&self.native_source,owner,chat,message)?;
  let id=required(&self.native_source,"embed_id")?;
  let expected=crypto::derive_embed_key(chat_key,id)?;
  if expected.as_ref()!=self._key.as_ref(){return Err(Error::Crypto)}
  let kind=Zeroizing::new(crypto::decrypt_combined(required(&self.native_source,"type")?,&self._key)?);
  if kind.as_str()!="code"{return Err(unavailable("NATIVE_MAIN_ROOT_CODE_EMBED_ONLY"))}
  let mut canonical=std::collections::BTreeMap::new();
  for row in self.native_source["embed_keys"].as_array().ok_or(Error::Protocol)?{
   self.verify_main_native_wrapper(row,owner,chat,id,chat_key,master).await?;
   canonical.insert(policy::key_id(row)?,row);
  }
  let mut stored=std::collections::BTreeMap::new();
  for row in before["observation"]["keys"].as_array().ok_or(Error::Protocol)?{
   self.verify_main_native_wrapper(row,owner,chat,id,chat_key,master).await?;
   let storage=required(row,"id")?;
   if storage!=policy::key_id(row)?{return Err(Error::Conflict)}
   if stored.insert(storage.to_owned(),row.clone()).is_some(){return Err(Error::Protocol)}
  }
  for row in before["observation"]["key_targets"].as_array().ok_or(Error::Protocol)?.iter().filter(|v|!v.is_null()){
   self.verify_main_native_wrapper(row,owner,chat,id,chat_key,master).await?;
   if stored.get(required(row,"id")?)!=Some(row){return Err(Error::Conflict)}
  }
  let mut kinds=std::collections::BTreeSet::new();
  for (storage,row) in canonical{
   kinds.insert(required(row,"key_type")?.to_owned());
   if !stored.contains_key(&storage){let mut row=(*row).clone();row["id"]=json!(storage);policy::bound(&row)?;stored.insert(storage,row);}
  }
  if kinds!=["chat".to_owned(),"master".to_owned()].into_iter().collect::<std::collections::BTreeSet<_>>(){return Err(Error::Forbidden)}
  let keys=stored.into_values().collect::<Vec<_>>();
  let mut record=policy::merge(&source,&before["observation"]["record"],owner,chat,message)?;
  for field in ["app_id","skill_id"]{if let Some(value)=self.value["content"].get(field){if !value.is_string(){return Err(Error::Protocol)}record[field]=value.clone();}}
  let after=Plain::new(json!({"record":&*record,"keys":keys}));policy::bound(&*after)?;self.main_native_negative()?;Ok(after)
 }
 async fn verify_main_native_wrapper(&self,row:&Value,owner:&str,chat:&str,id:&str,chat_key:&[u8;32],master:&MasterCapability)->Result<()>{
  policy::wrapper(row,owner,chat,id)?;self.scope.wrapper(row)?;self.main_native_negative()?;
  let wrapped=required(row,"encrypted_embed_key")?;
  let key=if row["key_type"]=="master"{master.decrypt_bytes(wrapped).await?}else{crypto::decrypt_bytes(wrapped,chat_key)?};
  self.main_native_negative()?;if key.as_slice()!=self._key.as_ref(){return Err(Error::Crypto)}Ok(())
 }
}
