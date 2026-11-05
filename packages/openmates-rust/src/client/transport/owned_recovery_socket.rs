//! Fixed owned foreground recovery socket phases. Normal actual auth is
//! mandatory here. Existing borrowed native fresh-handoff behavior stays exact.
//! Socket transport alone proves no lifecycle ACK, claim or durable result.
use super::*;
use std::sync::Arc;
pub(in crate::client) struct OwnedRecoverySocketPreparation {scope:Arc<owned_operation::OwnedOperationScope>,mode:CancellationToken}
pub(in crate::client) struct PreparedOwnedRecoverySocket {original:OwnedRecoverySocketPreparation,connection:PreparedSocketConnection,prepared_cancel:CancellationToken}
pub(in crate::client) struct OwnedUnannouncedRecoverySocket {
    original:OwnedRecoverySocketPreparation,socket:Socket,prepared_cancel:CancellationToken,lifecycle:Value,active_chat:Option<String>,
}
pub(in crate::client) struct PreparedOwnedRecoveryLifecycle {original:OwnedUnannouncedRecoverySocket}
pub(in crate::client) struct OwnedConnectedRecoverySocket {original:OwnedRecoverySocketPreparation,socket:Socket}
fn explicit_foreground(client:&Client)->Result<CancellationToken>{
    client.completion_recovery_mode.as_ref().filter(|mode|!mode.is_cancelled()).cloned()
        .ok_or(Error::Unavailable{code:"completion_recovery_unavailable",reason:"COMPLETION_RECOVERY_REQUIRES_EXPLICIT_FOREGROUND"})
}
impl OwnedRecoverySocketPreparation {
    /// Data only: prepare ALWAYS requires the actual opaque auth receipt.
    pub(in crate::client) fn needs_validation(&self)->bool{true}
    fn check(&self,client:&Client)->Result<()>{
        self.scope.check(client)?;
        let actual=explicit_foreground(client)?;
        if self.mode!=actual||self.mode.is_cancelled(){return Err(Error::Cancelled)}
        self.scope.observer().check_original_negative()?;
        if self.mode.is_cancelled(){return Err(Error::Cancelled)}
        Ok(())
    }
    pub(in crate::client) fn prepare(self,client:&mut Client,validation:Option<auth::OwnedSessionValidationReceipt>)->Result<PreparedOwnedRecoverySocket>{
        self.check(client)?;
        validation.ok_or(Error::Cancelled)?.check_original(client,&self.scope)?;
        self.check(client)?;client.check_active_owned_socket_start()?;
        let connection=client.prepare_socket_connection(false,false,true,SocketSelectionPolicy::AnnounceActiveChat,None)?;
        self.check(client)?;let prepared_cancel=client.browser_prepared_transport_cancel.clone();
        Ok(PreparedOwnedRecoverySocket{original:self,connection,prepared_cancel})
    }
}
impl Client {
    pub(in crate::client) fn begin_owned_completion_recovery_socket(&mut self,scope:Arc<owned_operation::OwnedOperationScope>)->Result<OwnedRecoverySocketPreparation>{
        scope.check(self)?;let mode=explicit_foreground(self)?;
        // Consume/discard the existing one-use native optimization exactly at
        // socket preparation. This NEW detached path always validates normally;
        // browser_authority never qualified the old matcher. Borrowed native
        // callers still take their unchanged skip-auth path in socket_mode.
        self.discard_fresh_handoff_for_owned_normal_auth();
        self.invalidate_chat_inventory_proofs();self.chat_list_freshness.invalidate();
        let prepared=OwnedRecoverySocketPreparation{scope,mode};prepared.check(self)?;Ok(prepared)
    }
}
struct SocketConnectFence {scope:Arc<owned_operation::OwnedOperationScope>,mode:CancellationToken,prepared_cancel:CancellationToken}
impl SocketConnectFence {
    fn check(&self)->Result<()>{self.check_with_negative(&||Ok(()))}
    fn check_with_negative(&self,additional:&impl Fn()->Result<()>)->Result<()>{
        self.scope.observer().check_release()?;
        // Exact narrower recovery request/mode/lease negatives after the last
        // original caller callback; no new positive authority is introduced.
        additional()?;
        if self.mode.is_cancelled()||self.prepared_cancel.is_cancelled(){return Err(Error::Cancelled)}
        self.scope.observer().check_original_negative()
    }
    async fn run_with_negative<T>(&self,future:impl std::future::Future<Output=Result<T>>,additional:&impl Fn()->Result<()>)->Result<T>{
        self.check_with_negative(additional)?;
        let value=tokio::select!{biased;
            _=self.mode.cancelled()=>return Err(Error::Cancelled),
            _=self.prepared_cancel.cancelled()=>return Err(Error::Cancelled),
            _=self.scope.cancelled()=>return Err(Error::Cancelled),
            result=future=>result?,
        };
        self.check_with_negative(additional)?;Ok(value)
    }
}
pub(in crate::client) async fn connect_owned_completion_recovery_socket(prepared:PreparedOwnedRecoverySocket)->Result<OwnedUnannouncedRecoverySocket>{
    connect_owned_completion_recovery_socket_with_negative(prepared,||Ok(())).await
}
pub(in crate::client) async fn connect_owned_completion_recovery_socket_with_negative(prepared:PreparedOwnedRecoverySocket,additional:impl Fn()->Result<()>)->Result<OwnedUnannouncedRecoverySocket>{
    let negative=SocketConnectFence{scope:prepared.original.scope.clone(),mode:prepared.original.mode.clone(),prepared_cancel:prepared.prepared_cancel.clone()};
    let socket=negative.run_with_negative(connect_socket_stream(prepared.connection.request,prepared.connection.config,prepared.connection.inventory_network),&additional).await?;
    Ok(OwnedUnannouncedRecoverySocket{original:prepared.original,socket,prepared_cancel:prepared.prepared_cancel,lifecycle:prepared.connection.lifecycle,active_chat:prepared.connection.active_chat})
}
impl OwnedUnannouncedRecoverySocket {
    /// Short SAME Client phase after actual connect, before lifecycle effects.
    pub(in crate::client) fn prepare_lifecycle(self,client:&Client)->Result<PreparedOwnedRecoveryLifecycle>{
        self.original.check(client)?;
        if self.prepared_cancel.is_cancelled(){return Err(Error::Cancelled)}
        Ok(PreparedOwnedRecoveryLifecycle{original:self})
    }
}
pub(in crate::client) async fn drive_owned_completion_recovery_lifecycle(prepared:PreparedOwnedRecoveryLifecycle)->Result<OwnedConnectedRecoverySocket>{
    drive_owned_completion_recovery_lifecycle_with_negative(prepared,||Ok(())).await
}
pub(in crate::client) async fn drive_owned_completion_recovery_lifecycle_with_negative(prepared:PreparedOwnedRecoveryLifecycle,additional:impl Fn()->Result<()>)->Result<OwnedConnectedRecoverySocket>{
    let mut resource=prepared.original;
    let negative=SocketConnectFence{scope:resource.original.scope.clone(),mode:resource.original.mode.clone(),prepared_cancel:resource.prepared_cancel};
    negative.run_with_negative(send(&mut resource.socket,"native_client_lifecycle",resource.lifecycle),&additional).await?;
    if let Some(chat)=resource.active_chat{negative.run_with_negative(send(&mut resource.socket,"set_active_chat",json!({"chat_id":chat})),&additional).await?;}
    negative.check_with_negative(&additional)?;Ok(OwnedConnectedRecoverySocket{original:resource.original,socket:resource.socket})
}
impl OwnedConnectedRecoverySocket {
    pub(in crate::client) fn socket(&mut self)->&mut Socket{&mut self.socket}
    pub(in crate::client) fn check_original(&self,client:&Client)->Result<()>{self.original.check(client)}
    /// Caller owes actual bounded lifecycle ACK/capture/full checks. This method
    /// itself grants neither ACK nor any recovery/durability result.
    pub(in crate::client) fn into_socket(self,client:&Client)->Result<Socket>{self.original.check(client)?;Ok(self.socket)}
}
#[cfg(all(test,not(target_arch="wasm32")))]
#[path="owned_recovery_socket_tests.rs"]
mod tests;
