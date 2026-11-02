//! ONE maintained Master -> original cached Chat -> parent selection engine.
//! The owned adapter only changes Client/IO scheduling, never wrapper policy.
use super::*;
use crate::client::embed_version::VersionReadScope;
use crate::crypto::master::MasterCapability;
use std::{future::Future,pin::Pin};
use zeroize::Zeroizing;
#[cfg(not(target_arch="wasm32"))]pub(in crate::client) type PhaseFuture<'a,T>=Pin<Box<dyn Future<Output=Result<T>>+Send+'a>>;
#[cfg(target_arch="wasm32")]pub(in crate::client) type PhaseFuture<'a,T>=Pin<Box<dyn Future<Output=Result<T>>+'a>>;
#[cfg(not(target_arch="wasm32"))]pub(in crate::client) trait Platform:Send+Sync{}
#[cfg(not(target_arch="wasm32"))]impl<T:Send+Sync> Platform for T{}
#[cfg(target_arch="wasm32")]pub(in crate::client) trait Platform{}
#[cfg(target_arch="wasm32")]impl<T> Platform for T{}
pub(in crate::client) struct Candidate<'a> {pub(in crate::client) parent:&'a str,pub(in crate::client) master:Option<&'a Value>,pub(in crate::client) chat:Option<&'a Value>}
pub(in crate::client) fn candidate<'a>(client:Option<&'a Client>,wanted:&str,staged:&'a BTreeMap<String,Value>,keys:&'a [Value],cached:bool)->Result<Candidate<'a>>{
 let row=staged.get(wanted).or_else(||cached.then(||client.and_then(|c|c.embeds.get(wanted))).flatten()).ok_or(Error::Forbidden)?;
 let hash=sha256(wanted);let cached_keys=client.map(|c|c.embed_keys.as_slice()).unwrap_or(&[]);
 let find=|kind:&str|keys.iter().chain(cached_keys.iter().filter(|_|cached)).find(|w|text(w,"hashed_embed_id")==hash&&text(w,"key_type")==kind);
 Ok(Candidate{parent:text(row,"parent_embed_id"),master:find("master"),chat:find("chat")})
}
pub(in crate::client) trait Phases:Platform {
 fn check(&self)->PhaseFuture<'_,()>;
 fn master(&self)->PhaseFuture<'_,MasterCapability>;
 fn candidate<'a>(&'a self,wanted:&str,staged:&'a BTreeMap<String,Value>,keys:&'a [Value],cached:bool)->Result<Candidate<'a>>;
 fn wrapper<'a>(&'a self,row:&'a Value)->PhaseFuture<'a,()>;
 fn decrypt<'a>(&'a self,master:&'a MasterCapability,cipher:&'a str)->PhaseFuture<'a,Zeroizing<Vec<u8>>>;
 fn chat<'a>(&'a self,wrapper:&'a Value,master:&'a MasterCapability)->PhaseFuture<'a,Option<Key>>;
}
pub(in crate::client) async fn select<P:Phases>(phases:&P,id:&str,staged:&BTreeMap<String,Value>,keys:&[Value],cached:bool)->Result<Key>{
 let master=phases.master().await?;let mut wanted=id.to_owned();let mut seen=std::collections::HashSet::new();
 while seen.insert(wanted.clone())&&seen.len()<=8 {
  phases.check().await?;let row=phases.candidate(&wanted,staged,keys,cached)?;
  if let Some(wrapper)=&row.master {
   phases.wrapper(wrapper).await?;phases.check().await?;
   let decoded=phases.decrypt(&master,required(wrapper,"encrypted_embed_key")?).await;
   phases.check().await?;phases.wrapper(wrapper).await?;
   match decoded{Ok(bytes)=>return key_from_bytes(&bytes),Err(Error::Crypto)=>{},Err(error)=>return Err(error)}
  }
  let mut missing_chat=false;
  if let Some(wrapper)=&row.chat {phases.wrapper(wrapper).await?;match phases.chat(wrapper,&master).await?{Some(key)=>return Ok(key),None=>missing_chat=true}}
  if row.parent.is_empty(){return Err(if missing_chat{Error::Unavailable{code:"cookie_embed_version_key_cache_unavailable",reason:"CHAT_WRAPPER_REQUIRES_ORIGINAL_PERSONAL_CHAT_CACHE"}}else{Error::Forbidden})}wanted=row.parent.to_owned();
 }
 Err(Error::Crypto)
}
pub(super) struct Borrowed<'a>{pub(super) client:&'a Client,pub(super) scope:&'a VersionReadScope}
impl Phases for Borrowed<'_> {
 fn check(&self)->PhaseFuture<'_,()>{Box::pin(async move{self.scope.check(self.client)})}
 fn master(&self)->PhaseFuture<'_,MasterCapability>{Box::pin(async move{self.client.master_capability()})}
 fn candidate<'a>(&'a self,wanted:&str,staged:&'a BTreeMap<String,Value>,keys:&'a [Value],cached:bool)->Result<Candidate<'a>>{candidate(Some(self.client),wanted,staged,keys,cached)}
 fn wrapper<'a>(&'a self,row:&'a Value)->PhaseFuture<'a,()>{Box::pin(async move{self.scope.wrapper(row)})}
 fn decrypt<'a>(&'a self,master:&'a MasterCapability,cipher:&'a str)->PhaseFuture<'a,Zeroizing<Vec<u8>>>{Box::pin(self.scope.run_io(master.decrypt_bytes(cipher)))}
 fn chat<'a>(&'a self,wrapper:&'a Value,master:&'a MasterCapability)->PhaseFuture<'a,Option<Key>>{Box::pin(async move{
  let chat_hash=required(wrapper,"hashed_chat_id")?;
  let Some((chat_id,chat))=self.client.chats.iter().find(|(id,_)|sha256(id)==chat_hash)else{return Ok(None)};
  self.scope.check_chat(self.client,chat_id)?;
  if text(chat,"chat_visibility")=="direct"{self.client.native_master_key()?;}else{
   let chat_id=required(chat,"id")?;
   if let Some(selected)=self.client.wrappers.iter().chain(chat["chat_key_wrappers"].as_array().into_iter().flatten()).find(|w|text(w,"hashed_chat_id")==sha256(chat_id)&&text(w,"key_type")=="master"){self.scope.wrapper(selected)?;}
  }
  self.scope.check_chat(self.client,chat_id)?;let chat_key=self.scope.run_io(self.client.chat_key_with_capability(chat,master)).await?;
  self.scope.check_chat(self.client,chat_id)?;self.scope.wrapper(wrapper)?;
  let bytes=crypto::server_fields::decrypt_bytes(required(wrapper,"encrypted_embed_key")?,&chat_key,&[])?;self.scope.check(self.client)?;key_from_bytes(&bytes).map(Some)
 })}
}
