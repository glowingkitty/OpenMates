//! cfgwasm-only actual original native port forwarding. All failures retain
//! exact Stage/carry; JSON/bools/hash/callback cannot construct success here.
use super::*;
use crate::platform::browser_recovery_port::{OriginalBrowserRecoveryPort,NativeRecoveryPortPending,NativeRecoveryPortDelivery};
impl OwnedBrowserMetadataContinuation {
    /// Exact same original body shared across bounded distinct recovery jobs.
    /// No copied metadata/manifest, new mode, hint ACK or durability is created.
    pub fn begin_shared_recovery_with_checkpoint_port(self:&Arc<Self>,client:&mut Client,job:&CompletionRecoveryJob,port:&OriginalBrowserRecoveryPort)->Result<BrowserOriginalHintRecoveryDriver>{
        self.check_original(client)?;if !self.metadata_committed{return Err(Error::Conflict)}port.check_original(client)?;
        let handoff=self.recovery_handoff(client,job)?;
        let inner=client.prepare_original_owned_recovery(handoff.clone(),None)?.with_checkpoint_port(client,port.clone())?.into_driver()?;
        Ok(BrowserOriginalHintRecoveryDriver{inner,remainder:Some(self.clone()),handoff,port_hold:Some(port.clone())})
    }
    pub fn begin_recovery_with_checkpoint_port(self,client:&mut Client,job:&CompletionRecoveryJob,saved:Option<CompletionRecoveryCheckpoint>,port:&OriginalBrowserRecoveryPort)->Result<BrowserOriginalHintRecoveryDriver>{
        self.check_original(client)?;if !self.metadata_committed{return Err(Error::Conflict)}port.check_original(client)?;
        let handoff=self.recovery_handoff(client,job)?;
        let inner=client.prepare_original_owned_recovery(handoff.clone(),saved)?.with_checkpoint_port(client,port.clone())?.into_driver()?;
        Ok(BrowserOriginalHintRecoveryDriver{inner,remainder:Some(Arc::new(self)),handoff,port_hold:Some(port.clone())})
    }
}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryCheckpointReadiness {prepared:BrowserOriginalHintRecoveryCheckpointPreparation,port:OriginalBrowserRecoveryPort,ready:Result<()>}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryCheckpointRead {prepared:BrowserOriginalHintRecoveryCheckpointPreparation,port:OriginalBrowserRecoveryPort,native:NativeRecoveryPortPending}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryCheckpointReadResult {prepared:BrowserOriginalHintRecoveryCheckpointPreparation,port:OriginalBrowserRecoveryPort,actual:Result<NativeRecoveryPortDelivery>}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryCheckpointNativeWrite {inner:recovery::OriginalRecoveryNativeWrite,carry:Carry}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryCheckpointNativeWriteResult {inner:recovery::OriginalRecoveryNativeWriteResult,carry:Carry}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryCheckpointReadbackCrypto {inner:recovery::OriginalRecoveryReadbackCrypto,carry:Carry}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryCheckpointVerified {inner:recovery::OriginalRecoveryVerifiedWrite,carry:Carry}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryCheckpointDurable {inner:recovery::OriginalHintRecoveryDurableReceipt,carry:Carry}
impl BrowserOriginalHintRecoveryCheckpointPreparation {
    /// Before post only: readiness can be cancelled safely. Ticket is captured
    /// in the previous actual Client phase; includes derived recovery child.
    pub async fn wait_ready(self,port:&OriginalBrowserRecoveryPort)->BrowserOriginalHintRecoveryCheckpointReadiness{
        let port=port.clone();let ready=tokio::select!{biased;_=self.ticket.cancelled()=>Err(Error::Cancelled),result=port.ready()=>result};
        BrowserOriginalHintRecoveryCheckpointReadiness{prepared:self,port,ready}
    }
}
impl BrowserOriginalHintRecoveryCheckpointReadiness {
    pub fn start(self,client:&Client)->Persist<BrowserOriginalHintRecoveryCheckpointRead>{
        let Self{mut prepared,port,ready}=self;
        if let Err(error)=ready{return Err(held(prepared.inner,error,prepared.carry))}
        let checked=(||{port.check_original(client)?;prepared.ticket.check_original(client)?;prepared.carry.handoff.check_root(client)?;port.check_negative()})();
        if let Err(error)=checked{return Err(held(prepared.inner,error,prepared.carry))}
        // Retain original actual port across every subsequent error/transfer,
        // including an uncertain post outcome. Never revoke a foreign peer.
        if prepared.carry.port_hold.is_none(){prepared.carry.port_hold=Some(port.clone());}
        let native=match port.start(client,prepared.ticket.clone()){Ok(value)=>value,Err(error)=>return Err(held(prepared.inner,error,prepared.carry))};
        Ok(BrowserOriginalHintRecoveryCheckpointRead{prepared,port,native})
    }
}
impl BrowserOriginalHintRecoveryCheckpointRead {
    /// Started IO is never select-dropped; even Err stays an opaque resource,
    /// not a terminal/drain fact. Page/native original port owns actual drain.
    pub async fn drive(self)->BrowserOriginalHintRecoveryCheckpointReadResult{
        let actual=self.native.drive().await;BrowserOriginalHintRecoveryCheckpointReadResult{prepared:self.prepared,port:self.port,actual}
    }
}
impl BrowserOriginalHintRecoveryCheckpointReadResult {
    pub fn into_crypto(self,client:&Client)->Persist<BrowserOriginalHintRecoveryCheckpointCrypto>{
        let Self{prepared,port,actual}=self;
        let checked=(||{port.check_original(client)?;prepared.ticket.check_original(client)?;prepared.carry.handoff.check_root(client)?;port.check_negative()})();
        if let Err(error)=checked{return Err(held(prepared.inner,error,prepared.carry))}
        let delivery=match actual{Ok(value)=>value,Err(error)=>return Err(held(prepared.inner,error,prepared.carry))};
        let data=match delivery.consume_for(&port,&prepared.ticket){Ok(value)=>value,Err(error)=>return Err(held(prepared.inner,error,prepared.carry))};
        let BrowserOriginalHintRecoveryCheckpointPreparation{inner,carry,..}=prepared;
        match inner.with_read_data(client,data){Ok(inner)=>Ok(BrowserOriginalHintRecoveryCheckpointCrypto{inner,carry}),Err(error)=>Err(failed(error,carry))}
    }
}
impl BrowserOriginalHintRecoveryCheckpointWrite {
    pub fn start_native(self,client:&Client,port:&OriginalBrowserRecoveryPort)->Persist<BrowserOriginalHintRecoveryCheckpointNativeWrite>{
        let Self{inner,carry}=self;match inner.start_native(client,port){Ok(inner)=>Ok(BrowserOriginalHintRecoveryCheckpointNativeWrite{inner,carry}),Err(error)=>Err(failed(error,carry))}
    }
}
impl BrowserOriginalHintRecoveryCheckpointNativeWrite {
    pub async fn drive(self)->BrowserOriginalHintRecoveryCheckpointNativeWriteResult{let inner=self.inner.drive().await;BrowserOriginalHintRecoveryCheckpointNativeWriteResult{inner,carry:self.carry}}
}
impl BrowserOriginalHintRecoveryCheckpointNativeWriteResult {
    pub fn readback(self,client:&Client)->Persist<BrowserOriginalHintRecoveryCheckpointReadbackCrypto>{
        let Self{inner,carry}=self;match inner.readback(client){Ok(inner)=>Ok(BrowserOriginalHintRecoveryCheckpointReadbackCrypto{inner,carry}),Err(error)=>Err(failed(error,carry))}
    }
}
impl BrowserOriginalHintRecoveryCheckpointReadbackCrypto {
    pub async fn drive(self)->Persist<BrowserOriginalHintRecoveryCheckpointVerified>{
        let Self{inner,carry}=self;match inner.drive().await{Ok(inner)=>Ok(BrowserOriginalHintRecoveryCheckpointVerified{inner,carry}),Err(error)=>Err(failed(error,carry))}
    }
}
impl BrowserOriginalHintRecoveryCheckpointVerified {
    pub fn finish(self,client:&Client)->Persist<BrowserOriginalHintRecoveryCheckpointDurable>{
        let Self{inner,carry}=self;match inner.finish(client){Ok(inner)=>Ok(BrowserOriginalHintRecoveryCheckpointDurable{inner,carry}),Err(error)=>Err(failed(error,carry))}
    }
}
impl BrowserOriginalHintRecoveryCheckpointDurable {
    pub fn into_driver(self,client:&Client)->Persist<BrowserOriginalHintRecoveryDriver>{
        let Self{inner,carry}=self;match inner.into_driver(client){
            Ok(inner)=>Ok(BrowserOriginalHintRecoveryDriver{inner,remainder:Some(carry.remainder),handoff:carry.handoff,port_hold:carry.port_hold}),
            Err(error)=>Err(failed(error,carry)),
        }
    }
}
