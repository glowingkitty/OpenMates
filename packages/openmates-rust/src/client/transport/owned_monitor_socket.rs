//! Actual passive monitor transport, using a same-phase real auth receipt.
//! General socket/auth/recovery entrypoints and their policies stay unchanged.
use super::*;
use std::sync::{Arc,Mutex};
use crate::client::owned_operation::OwnedOperationScope;
pub(in crate::client) struct PreparedOwnedMonitorSocket {
    scope:Arc<OwnedOperationScope>,connection:PreparedSocketConnection,prepared_cancel:CancellationToken,monitor_cancel:CancellationToken,retirement:Arc<Mutex<Option<Socket>>>,connect_deadline:Option<crate::platform::time::Instant>,
}
pub(in crate::client) struct UnannouncedOwnedMonitorSocket {
    scope:Arc<OwnedOperationScope>,socket:Socket,lifecycle:Value,prepared_cancel:CancellationToken,monitor_cancel:CancellationToken,retirement:Arc<Mutex<Option<Socket>>>,
}
pub(in crate::client) fn prepare_owned_passive_monitor_socket(client:&mut Client,scope:Arc<OwnedOperationScope>,receipt:auth::OwnedSessionValidationReceipt,monitor_cancel:CancellationToken,retirement:Arc<Mutex<Option<Socket>>>)->Result<PreparedOwnedMonitorSocket>{
    scope.check(client)?;receipt.check_original(client,&scope)?;client.check_active_owned_socket_start()?;
    if client.monitor_cancel.as_ref()!=Some(&monitor_cancel)||monitor_cancel.is_cancelled(){return Err(Error::Cancelled)}
    let connection=client.prepare_socket_connection(false,false,false,SocketSelectionPolicy::Passive,None)?;
    scope.check(client)?;
    Ok(PreparedOwnedMonitorSocket{scope,connection,prepared_cancel:client.browser_prepared_transport_cancel.clone(),monitor_cancel,retirement,connect_deadline:None})
}
/// A separate fresh saved-read passive socket. The exact original auth receipt
/// and owned child are mandatory; this NEVER reads/replaces a monitor slot.
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
pub(in crate::client) fn prepare_owned_saved_embed_socket(client:&mut Client,scope:Arc<OwnedOperationScope>,receipt:auth::OwnedSessionValidationReceipt,read_cancel:CancellationToken,retirement:Arc<Mutex<Option<Socket>>>,deadline:crate::platform::time::Instant)->Result<PreparedOwnedMonitorSocket>{
    scope.check(client)?;receipt.check_original(client,&scope)?;client.check_active_owned_socket_start()?;
    if read_cancel.is_cancelled(){return Err(Error::Cancelled)}
    let connection=client.prepare_socket_connection(false,false,false,SocketSelectionPolicy::Passive,None)?;
    scope.check(client)?;
    Ok(PreparedOwnedMonitorSocket{scope,connection,prepared_cancel:client.browser_prepared_transport_cancel.clone(),monitor_cancel:read_cancel,retirement,connect_deadline:Some(deadline)})
}
fn negative(scope:&OwnedOperationScope,prepared:&CancellationToken,monitor:&CancellationToken)->Result<()>{
    scope.observer().check_release()?;if prepared.is_cancelled()||monitor.is_cancelled(){return Err(Error::Cancelled)}scope.observer().check_original_negative()
}
async fn retire(mut socket:Socket,retirement:&Arc<Mutex<Option<Socket>>>)->Result<()>{
    if socket.close(None).await.is_err(){*retirement.lock().map_err(|_|Error::Protocol)?=Some(socket);return Err(Error::Offline)}Ok(())
}
pub(in crate::client) async fn connect_owned_passive_monitor_socket(prepared:PreparedOwnedMonitorSocket)->Result<UnannouncedOwnedMonitorSocket>{
    negative(&prepared.scope,&prepared.prepared_cancel,&prepared.monitor_cancel)?;
    // Do not drop a started native handshake when a local cancellation arrives.
    // The existing bounded connect returns first, then its SAME socket closes.
    let connection=connect_socket_stream(prepared.connection.request,prepared.connection.config,prepared.connection.inventory_network);
    let socket=match prepared.connect_deadline{None=>connection.await?,Some(deadline)=>crate::platform::time::timeout_at(deadline,connection).await.map_err(|_|Error::Offline)??};
    if let Err(error)=negative(&prepared.scope,&prepared.prepared_cancel,&prepared.monitor_cancel){let _=retire(socket,&prepared.retirement).await;return Err(error)}
    Ok(UnannouncedOwnedMonitorSocket{scope:prepared.scope,socket,lifecycle:prepared.connection.lifecycle,prepared_cancel:prepared.prepared_cancel,monitor_cancel:prepared.monitor_cancel,retirement:prepared.retirement})
}
impl UnannouncedOwnedMonitorSocket {
    pub(in crate::client) fn check(&self,client:&Client)->Result<()>{self.scope.check(client)?;negative(&self.scope,&self.prepared_cancel,&self.monitor_cancel)}
    pub(in crate::client) async fn retire(self)->Result<()>{retire(self.socket,&self.retirement).await}
}
pub(in crate::client) async fn announce_owned_passive_monitor_socket(mut original:UnannouncedOwnedMonitorSocket)->Result<Socket>{
    if let Err(error)=negative(&original.scope,&original.prepared_cancel,&original.monitor_cancel){let _=retire(original.socket,&original.retirement).await;return Err(error)}
    let result=send(&mut original.socket,"native_client_lifecycle",std::mem::take(&mut original.lifecycle)).await;
    if let Err(error)=result.and_then(|_|negative(&original.scope,&original.prepared_cancel,&original.monitor_cancel)){let _=retire(original.socket,&original.retirement).await;return Err(error)}
    Ok(original.socket)
}
