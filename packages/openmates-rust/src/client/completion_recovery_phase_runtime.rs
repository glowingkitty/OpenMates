//! Typed recovery operations. Borrowed compatibility uses the exact maintained
//! Client helpers; the owned implementation must never await those helpers in
//! an Apply phase. No foreign constructor, URL callback or DTO authority.
use super::*;
use std::{future::Future,pin::Pin};
#[cfg(not(target_arch="wasm32"))]
pub(super) type RecoveryFuture<'a,T>=Pin<Box<dyn Future<Output=Result<T>>+Send+'a>>;
#[cfg(target_arch="wasm32")]
pub(super) type RecoveryFuture<'a,T>=Pin<Box<dyn Future<Output=Result<T>>+'a>>;
#[cfg(not(target_arch="wasm32"))]
pub(super) trait RecoveryPlatform:Send{}
#[cfg(not(target_arch="wasm32"))]
impl<T:Send> RecoveryPlatform for T{}
#[cfg(target_arch="wasm32")]
pub(super) trait RecoveryPlatform{}
#[cfg(target_arch="wasm32")]
impl<T> RecoveryPlatform for T{}
pub(super) enum RecoveryCrypto {
    Borrowed(AsyncCryptoScope),
    Owned(Arc<super::super::owned_operation::OwnedOperationScope>),
}
pub(super) enum RecoveryConnected {
    Borrowed(Option<Socket>),
    Owned(Option<super::super::transport::OwnedConnectedRecoverySocket>),
}
impl RecoveryConnected {
    pub(super) fn socket(&mut self)->Result<&mut Socket>{match self{
        Self::Borrowed(socket)=>socket.as_mut().ok_or(Error::Cancelled),
        Self::Owned(socket)=>Ok(socket.as_mut().ok_or(Error::Cancelled)?.socket()),
    }}
}
pub(super) trait RecoveryChecks:RecoveryPlatform {
    fn check_fence<'a>(&'a mut self,fence:&'a RecoveryFence)->RecoveryFuture<'a,()>;
    fn scope_check<'a>(&'a mut self,scope:&'a RecoveryCrypto)->RecoveryFuture<'a,()>;
    fn scope_chat<'a>(&'a mut self,scope:&'a RecoveryCrypto,chat:&'a str)->RecoveryFuture<'a,()>;
}
pub(super) enum MainPersistAttempt { Persisted(Value), VersionConflict }
pub(super) trait RecoveryPhases:RecoveryChecks {
    fn saved_checkpoint<'a>(&'a mut self,_job:&'a CompletionRecoveryJob,saved:Option<CompletionRecoveryCheckpoint>,_fence:&'a RecoveryFence)->RecoveryFuture<'a,Option<CompletionRecoveryCheckpoint>>{Box::pin(async move{Ok(saved)})}
    fn fence<'a>(&'a mut self,cancel:&'a CancellationToken)->RecoveryFuture<'a,RecoveryFence>;
    fn validate<'a>(&'a mut self,fence:&'a RecoveryFence)->RecoveryFuture<'a,()>;
    fn begin_scope(&mut self)->RecoveryFuture<'_,RecoveryCrypto>;
    fn capture<'a>(&'a mut self,kind:&'a str,payload:&'a Value)->RecoveryFuture<'a,()>;
    fn connect_socket<'a>(&'a mut self,fence:&'a RecoveryFence)->RecoveryFuture<'a,RecoveryConnected>;
    fn check_connected<'a>(&'a mut self,connected:&'a mut RecoveryConnected)->RecoveryFuture<'a,()>;
    fn finish_connected<'a>(&'a mut self,connected:RecoveryConnected)->RecoveryFuture<'a,Socket>;
    fn check_owner<'a>(&'a mut self,checkpoint:&'a CompletionRecoveryCheckpoint,fence:&'a RecoveryFence)->RecoveryFuture<'a,()>;
    fn team(&mut self)->RecoveryFuture<'_,Option<String>>;
    fn owner(&mut self)->RecoveryFuture<'_,String>;
    fn observed_created_at<'a>(&'a mut self,job:&'a CompletionRecoveryJob)->RecoveryFuture<'a,Option<u64>>;
    fn api_url(&mut self)->RecoveryFuture<'_,String>;
    fn metadata<'a>(&'a mut self,chat:&'a str,fence:&'a RecoveryFence)->RecoveryFuture<'a,Option<Value>>;
    fn require_native_master(&mut self)->RecoveryFuture<'_,()>;
    fn load_direct_identity(&mut self)->RecoveryFuture<'_,()>;
    fn direct_chat_key<'a>(&'a mut self,row:&'a Value)->RecoveryFuture<'a,Key>;
    fn master(&mut self)->RecoveryFuture<'_,MasterCapability>;
    fn team_wrapping<'a>(&'a mut self,team:&'a str)->RecoveryFuture<'a,Value>;
    fn cache_team<'a>(&'a mut self,team:String,key:Key,encrypted:String)->RecoveryFuture<'a,()>;
    fn unwrap_key<'a>(&'a mut self,encrypted:&'a str,wrapping:&'a MasterCapability,fence:&'a RecoveryFence,scope:&'a RecoveryCrypto,id:&'a str)->RecoveryFuture<'a,Key>;
    fn unwrap_selected_key<'a>(&'a mut self,encrypted:&'a str,wrapping:&'a MasterCapability,fence:&'a RecoveryFence,scope:&'a RecoveryCrypto,id:&'a str,wrapper:&'a Value,team:bool)->RecoveryFuture<'a,Key>;
    fn cache_key_row<'a>(&'a mut self,id:String,row:Value,selected:Option<phase_key::SelectedRecoveryWrapper>)->RecoveryFuture<'a,()>;
    fn current_key<'a>(&'a mut self,chat:&'a str,fence:&'a RecoveryFence)->RecoveryFuture<'a,(Value,Key)>;
    fn reconcile<'a>(&'a mut self,job:&'a CompletionRecoveryJob,key:&'a [u8;32],fence:&'a RecoveryFence)->RecoveryFuture<'a,Option<CompletionRecoveryReceipt>>;
    fn canonical<'a>(&'a mut self,job:&'a CompletionRecoveryJob)->RecoveryFuture<'a,Option<Value>>;
    fn foreground_socket<'a>(&'a mut self,fence:&'a RecoveryFence)->RecoveryFuture<'a,Socket>;
    fn exchange<'a>(&'a mut self,socket:&'a mut Socket,kind:&'a str,payload:Value,reply:&'a str,job:&'a str,fence:&'a RecoveryFence)->RecoveryFuture<'a,Value>;
    fn persist_main<'a>(&'a mut self,socket:&'a mut Socket,payload:Value,job:&'a str,fence:&'a RecoveryFence)->RecoveryFuture<'a,MainPersistAttempt>;
    fn retain_stage<'a>(&'a mut self,fence:&'a mut RecoveryFence,cancel:&'a CancellationToken)->RecoveryFuture<'a,()>;
    fn insert_row<'a>(&'a mut self,chat:String,row:Value)->RecoveryFuture<'a,()>;
}
pub(super) struct BorrowedRecoveryPhases<'a>{pub(super) client:&'a mut Client}
impl RecoveryChecks for BorrowedRecoveryPhases<'_> {
    fn check_fence<'a>(&'a mut self,fence:&'a RecoveryFence)->RecoveryFuture<'a,()>{Box::pin(async move{fence.check_client(self.client)})}
    fn scope_check<'a>(&'a mut self,scope:&'a RecoveryCrypto)->RecoveryFuture<'a,()>{Box::pin(async move{match scope{RecoveryCrypto::Borrowed(original)=>original.check(self.client),RecoveryCrypto::Owned(_)=>Err(Error::Cancelled)}})}
    fn scope_chat<'a>(&'a mut self,scope:&'a RecoveryCrypto,chat:&'a str)->RecoveryFuture<'a,()>{Box::pin(async move{match scope{RecoveryCrypto::Borrowed(original)=>original.check_chat(self.client,chat),RecoveryCrypto::Owned(_)=>Err(Error::Cancelled)}})}
}
impl RecoveryPhases for BorrowedRecoveryPhases<'_> {
    fn fence<'a>(&'a mut self,cancel:&'a CancellationToken)->RecoveryFuture<'a,RecoveryFence>{Box::pin(async move{self.client.recovery_fence(cancel)})}
    fn validate<'a>(&'a mut self,_fence:&'a RecoveryFence)->RecoveryFuture<'a,()>{Box::pin(self.client.validate_session())}

    fn begin_scope(&mut self)->RecoveryFuture<'_,RecoveryCrypto>{Box::pin(async move{AsyncCryptoScope::begin(self.client).map(RecoveryCrypto::Borrowed)})}

    fn capture<'a>(&'a mut self,kind:&'a str,payload:&'a Value)->RecoveryFuture<'a,()>{Box::pin(async move{capture(kind,payload,&mut self.client.completion_recovery_jobs,&mut self.client.metadata_recovery_jobs).map(|_|())})}
    fn connect_socket<'a>(&'a mut self,_fence:&'a RecoveryFence)->RecoveryFuture<'a,RecoveryConnected>{Box::pin(async move{self.client.completion_recovery_socket().await.map(|v|RecoveryConnected::Borrowed(Some(v)))})}
    fn check_connected<'a>(&'a mut self,connected:&'a mut RecoveryConnected)->RecoveryFuture<'a,()>{Box::pin(async move{match connected{RecoveryConnected::Borrowed(Some(_))=>Ok(()),_=>Err(Error::Cancelled)}})}
    fn finish_connected<'a>(&'a mut self,connected:RecoveryConnected)->RecoveryFuture<'a,Socket>{Box::pin(async move{match connected{RecoveryConnected::Borrowed(Some(socket))=>Ok(socket),_=>Err(Error::Cancelled)}})}

    fn check_owner<'a>(&'a mut self,checkpoint:&'a CompletionRecoveryCheckpoint,fence:&'a RecoveryFence)->RecoveryFuture<'a,()>{Box::pin(async move{self.client.check_recovery_owner(checkpoint,fence)})}
    fn team(&mut self)->RecoveryFuture<'_,Option<String>>{Box::pin(async move{self.client.team().map(|v|v.map(str::to_owned))})}
    fn owner(&mut self)->RecoveryFuture<'_,String>{Box::pin(async move{owner(self.client)})}
    fn observed_created_at<'a>(&'a mut self,job:&'a CompletionRecoveryJob)->RecoveryFuture<'a,Option<u64>>{Box::pin(async move{observed_job_created_at(self.client,job)})}
    fn api_url(&mut self)->RecoveryFuture<'_,String>{Box::pin(async move{Ok(self.client.base.as_str().trim_end_matches('/').into())})}
    fn metadata<'a>(&'a mut self,chat:&'a str,_fence:&'a RecoveryFence)->RecoveryFuture<'a,Option<Value>>{Box::pin(self.client.request_chat_metadata(chat))}
    fn require_native_master(&mut self)->RecoveryFuture<'_,()>{Box::pin(async move{self.client.native_master_key().map(|_|())})}
    fn load_direct_identity(&mut self)->RecoveryFuture<'_,()>{Box::pin(self.client.load_direct_identity())}
    fn direct_chat_key<'a>(&'a mut self,row:&'a Value)->RecoveryFuture<'a,Key>{Box::pin(async move{self.client.direct_chat_key(row)})}
    fn master(&mut self)->RecoveryFuture<'_,MasterCapability>{Box::pin(async move{self.client.master_capability()})}
    fn team_wrapping<'a>(&'a mut self,team:&'a str)->RecoveryFuture<'a,Value>{Box::pin(async move{self.client.request(Method::GET,&format!("/v1/teams/{}",segment(team)),None).await})}
    fn cache_team<'a>(&'a mut self,team:String,key:Key,encrypted:String)->RecoveryFuture<'a,()>{Box::pin(async move{self.client.team_key=Some((team.clone(),key));self.client.team_wrapped_key=Some((team,encrypted));Ok(())})}
    fn unwrap_key<'a>(&'a mut self,encrypted:&'a str,wrapping:&'a MasterCapability,fence:&'a RecoveryFence,scope:&'a RecoveryCrypto,id:&'a str)->RecoveryFuture<'a,Key>{Box::pin(phase_key::unwrap_key(self,encrypted,wrapping,fence,scope,id))}
    fn unwrap_selected_key<'a>(&'a mut self,encrypted:&'a str,wrapping:&'a MasterCapability,fence:&'a RecoveryFence,scope:&'a RecoveryCrypto,id:&'a str,wrapper:&'a Value,team:bool)->RecoveryFuture<'a,Key>{Box::pin(phase_key::unwrap_selected_key(self,encrypted,wrapping,fence,scope,id,wrapper,team))}
    fn cache_key_row<'a>(&'a mut self,id:String,row:Value,_selected:Option<phase_key::SelectedRecoveryWrapper>)->RecoveryFuture<'a,()>{Box::pin(async move{
        self.client.wrappers.retain(|wrapper|text(wrapper,"hashed_chat_id")!=sha256(&id));
        self.client.wrappers.extend(row["chat_key_wrappers"].as_array().into_iter().flatten().cloned());
        self.client.insert_chat_row(id,row);Ok(())
    })}
    fn current_key<'a>(&'a mut self,chat:&'a str,fence:&'a RecoveryFence)->RecoveryFuture<'a,(Value,Key)>{Box::pin(self.client.recovery_current_key(chat,fence))}
    fn reconcile<'a>(&'a mut self,job:&'a CompletionRecoveryJob,key:&'a [u8;32],fence:&'a RecoveryFence)->RecoveryFuture<'a,Option<CompletionRecoveryReceipt>>{Box::pin(self.client.reconcile_main(job,key,fence))}
    fn canonical<'a>(&'a mut self,job:&'a CompletionRecoveryJob)->RecoveryFuture<'a,Option<Value>>{Box::pin(async move{self.client.canonical_main_candidate(job)})}
    fn foreground_socket<'a>(&'a mut self,fence:&'a RecoveryFence)->RecoveryFuture<'a,Socket>{Box::pin(self.client.recovery_foreground_socket(fence))}
    fn exchange<'a>(&'a mut self,socket:&'a mut Socket,kind:&'a str,payload:Value,reply:&'a str,job:&'a str,fence:&'a RecoveryFence)->RecoveryFuture<'a,Value>{Box::pin(self.client.recovery_exchange(socket,kind,payload,reply,job,fence))}
    fn persist_main<'a>(&'a mut self,socket:&'a mut Socket,payload:Value,job:&'a str,fence:&'a RecoveryFence)->RecoveryFuture<'a,MainPersistAttempt>{Box::pin(phase_io::persist_main(self,socket,payload,job,fence))}
    fn retain_stage<'a>(&'a mut self,fence:&'a mut RecoveryFence,cancel:&'a CancellationToken)->RecoveryFuture<'a,()>{Box::pin(async move{fence.operation=cancel.clone();Ok(())})}
    fn insert_row<'a>(&'a mut self,chat:String,row:Value)->RecoveryFuture<'a,()>{Box::pin(async move{self.client.insert_chat_row(chat,row);Ok(())})}
}
