//! Same-original monitor acquisition. Actual auth/header/body, handshake,
//! lifecycle and Team IO never borrow a Client or browser auth lock.
use super::*;
use crate::client::owned_operation::{ActiveOwnedClient,OwnedOperationScope};
use crate::client::auth::{PreparedOwnedSessionValidation,OwnedSessionValidationHeaders,OwnedSessionValidationBody,CompletedOwnedSessionValidation};
use crate::client::transport::{PreparedOwnedMonitorSocket,UnannouncedOwnedMonitorSocket,OwnedReadRoute,PreparedOwnedRead,OwnedReadHeaders,OwnedReadBody,CompletedOwnedRead};
use std::{future::Future,pin::Pin,sync::atomic::{AtomicU64,Ordering}};
use tokio::sync::{mpsc,oneshot};

struct Context {
    original:Arc<OwnedOperationScope>,slot:CancellationToken,team:Option<String>,
    monitor:Mutex<Option<Arc<ChatMonitor>>>,socket:Arc<Mutex<Option<Socket>>>,
    errors:Mutex<Option<mpsc::Sender<Error>>>,pending:AtomicU64,
    returned:AtomicBool,abandoned:AtomicBool,retained:AtomicBool,
}
impl Context {
    fn negative(&self)->Result<()>{self.original.observer().check_release()?;if self.slot.is_cancelled(){return Err(Error::Cancelled)}self.original.observer().check_original_negative()}
    fn check(&self,c:&Client)->Result<()>{
        self.original.check(c)?;
        if c.monitor_cancel.as_ref()!=Some(&self.slot)||c.team()?.map(str::to_owned)!=self.team{return Err(Error::Cancelled)}
        if let Some(monitor)=&*self.monitor.lock().map_err(|_|Error::Protocol)?{c.check_chat_monitor_fence(&monitor.fence)?;}
        self.negative()
    }
    fn cancel(&self){self.slot.cancel();self.original.observer().cancel();if let Ok(monitor)=self.monitor.lock(){if let Some(monitor)=&*monitor{monitor.close();}}}
    async fn retire(&self)->Result<()>{
        self.cancel();let socket=self.socket.lock().map_err(|_|Error::Protocol)?.take();
        if let Some(mut socket)=socket{if socket.close(None).await.is_err(){self.abandoned.store(true,Ordering::Release);*self.socket.lock().map_err(|_|Error::Protocol)?=Some(socket);return Err(Error::Offline)}}
        Ok(())
    }
    fn terminal(&self)->bool{self.returned.load(Ordering::Acquire)&&self.pending.load(Ordering::Acquire)==0&&!self.abandoned.load(Ordering::Acquire)}
    fn spawn(&self,c:&Client)->Result<()>{
        self.check(c)?;
        let changes=Arc::new(Changes{send_lane:Some(c.scoped_send_gate.clone()),..Changes::default()});
        changes.pending.lock().map_err(|_|Error::Protocol)?.refresh=true;
        let mut socket_slot=self.socket.lock().map_err(|_|Error::Protocol)?;
        let socket=socket_slot.as_ref().ok_or(Error::Conflict)?;
        let(port,receiver)=actor::channel(socket);*changes.read_port.lock().map_err(|_|Error::Protocol)?=Some(port);
        let fence=Arc::new(MonitorFence{owner:c.task_watch_authority.clone(),generation:c.generation,team:self.team.clone(),
            expires_at:c.require_credentials()?.paired_session_expires_at,cancel:self.slot.clone(),alive:AtomicBool::new(true),denial:Mutex::new(None)});
        let mut monitor_slot=self.monitor.lock().map_err(|_|Error::Protocol)?;
        if monitor_slot.is_some(){return Err(Error::Conflict)}
        let errors=self.errors.lock().map_err(|_|Error::Protocol)?.take().ok_or(Error::Conflict)?;
        let socket=socket_slot.take().ok_or(Error::Conflict)?;
        let monitor=Arc::new(ChatMonitor{fence:fence.clone(),changes:changes.clone()});
        changes.wake.notify_one();*monitor_slot=Some(monitor);
        crate::platform::spawn(monitor_socket_mode(socket,self.slot.clone(),errors,self.team.as_deref().map(sha256),c.lifecycle(),Duration::from_secs(25),Some(changes),Some(fence),Some(receiver)));
        Ok(())
    }
}
enum Work {AuthPrepare,AuthHeaders(OwnedSessionValidationHeaders),AuthFinish(CompletedOwnedSessionValidation,bool),
    CheckConnected(UnannouncedOwnedMonitorSocket),Spawn,TeamPrepare,TeamHeaders(OwnedReadHeaders),TeamFinish(CompletedOwnedRead,bool),Check}
enum Resume {Auth(PreparedOwnedSessionValidation),AuthBody(OwnedSessionValidationBody),Socket(PreparedOwnedMonitorSocket),
    Connected(UnannouncedOwnedMonitorSocket,Result<()>),Read(PreparedOwnedRead),ReadBody(OwnedReadBody),Unit}
struct Pending {context:Arc<Context>,work:Option<Work>,reply:Option<oneshot::Sender<Result<Resume>>>}
impl Drop for Pending {fn drop(&mut self){if let Some(reply)=self.reply.take(){self.context.abandoned.store(true,Ordering::Release);self.context.cancel();self.context.pending.store(0,Ordering::Release);let _=reply.send(Err(Error::Cancelled));}}}
struct Channel {context:Arc<Context>,send:mpsc::UnboundedSender<Pending>}
impl Channel {
    async fn call(&self,work:Work)->Result<Resume>{
        self.context.pending.compare_exchange(0,1,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
        let(reply,receive)=oneshot::channel();self.send.send(Pending{context:self.context.clone(),work:Some(work),reply:Some(reply)}).map_err(|_|Error::Cancelled)?;
        receive.await.map_err(|_|Error::Cancelled)?
    }
    async fn auth(&self,open:bool)->Result<Option<PreparedOwnedMonitorSocket>>{
        let Resume::Auth(prepared)=self.call(Work::AuthPrepare).await?else{return Err(Error::Protocol)};
        let headers=crate::client::auth::send_owned_session_validation_headers(prepared).await;
        let Resume::AuthBody(body)=self.call(Work::AuthHeaders(headers)).await?else{return Err(Error::Protocol)};
        let completed=crate::client::auth::drive_owned_session_validation_body(body).await;
        match self.call(Work::AuthFinish(completed,open)).await?{Resume::Socket(socket)if open=>Ok(Some(socket)),Resume::Unit if !open=>Ok(None),_=>Err(Error::Protocol)}
    }
    async fn team(&self,deny:bool)->Result<()>{
        if self.context.team.is_none(){return Ok(())}
        let Resume::Read(prepared)=self.call(Work::TeamPrepare).await?else{return Err(Error::Protocol)};
        let request=self.context.original.request();
        let headers=transport::send_owned_read_headers(prepared,&request,||self.context.negative()).await?;
        let Resume::ReadBody(body)=self.call(Work::TeamHeaders(headers)).await?else{return Err(Error::Protocol)};
        let completed=transport::drive_owned_read_body(body,&request,||self.context.negative()).await?;
        let Resume::Unit=self.call(Work::TeamFinish(completed,deny)).await?else{return Err(Error::Protocol)};Ok(())
    }
}
async fn drive(channel:Channel)->Result<()>{
    let result=async {
        let prepared=channel.auth(true).await?.ok_or(Error::Protocol)?;
        let connected=transport::connect_owned_passive_monitor_socket(prepared).await?;
        let Resume::Connected(connected,checked)=channel.call(Work::CheckConnected(connected)).await?else{return Err(Error::Protocol)};
        if let Err(error)=checked{let _=connected.retire().await;return Err(error)}
        let socket=transport::announce_owned_passive_monitor_socket(connected).await?;
        *channel.context.socket.lock().map_err(|_|Error::Protocol)?=Some(socket);
        channel.team(false).await?;
        let Resume::Unit=channel.call(Work::Spawn).await?else{return Err(Error::Protocol)};
        // Preserve the binding's maintained second fresh session/Team validation.
        channel.auth(false).await?;channel.team(true).await?;
        let Resume::Unit=channel.call(Work::Check).await?else{return Err(Error::Protocol)};
        Ok(())
    }.await;
    if result.is_err()&&channel.context.retire().await.is_err(){channel.context.abandoned.store(true,Ordering::Release);}
    result
}
#[doc(hidden)]
pub struct OwnedChatMonitorStartApply {pending:Pending}
impl OwnedChatMonitorStartApply {
    pub fn apply(mut self,c:&mut Client)->Result<()>{
        let ctx=self.pending.context.clone();let work=self.pending.work.take().ok_or(Error::Conflict)?;
        let result=match work{
            // Matched actual auth control-plane bookkeeping precedes local
            // request cancellation, exactly as maintained owned validation.
            Work::AuthHeaders(headers)=>c.apply_owned_session_validation_headers(headers).map(Resume::AuthBody),
            Work::AuthFinish(completed,open)=>(||{
                let receipt=c.finish_owned_session_validation(completed)?;ctx.check(c)?;
                if open{Ok(Resume::Socket(transport::prepare_owned_passive_monitor_socket(c,ctx.original.clone(),receipt,ctx.slot.clone(),ctx.socket.clone())?))}else{Ok(Resume::Unit)}
            })(),
            Work::TeamHeaders(headers)=>c.apply_owned_read_headers(headers).and_then(|body|{ctx.check(c)?;Ok(Resume::ReadBody(body))}),
            Work::CheckConnected(connected)=>{let checked=ctx.check(c).and_then(|_|connected.check(c));Ok(Resume::Connected(connected,checked))},
            work=>(||{
                ctx.check(c)?;let mut active=ActiveOwnedClient::enter(c,&ctx.original)?;
                let result=match work{
                    Work::AuthPrepare=>Resume::Auth(active.prepare_owned_session_validation(ctx.original.clone())?),
                    Work::TeamPrepare=>Resume::Read(active.prepare_owned_read(OwnedReadRoute::CurrentTeam)?),
                    Work::TeamFinish(completed,deny)=>{
                        let result=active.finish_owned_read(completed).and_then(|value|{
                            if value.as_ref().is_some_and(|v|text(&v["team"],"team_id")==ctx.team.as_deref().unwrap_or("")){Ok(())}else{Err(Error::Forbidden)}
                        });
                        if deny {if let Err(error)=&result {if matches!(error,Error::Expired|Error::Forbidden){if let Some(monitor)=&*ctx.monitor.lock().map_err(|_|Error::Protocol)?{monitor.deny(if *error==Error::Expired{ChatMonitorAccessDenial::Expired}else{ChatMonitorAccessDenial::ScopeRevoked})?;}}}}
                        result?;Resume::Unit
                    },
                    Work::Spawn=>{ctx.spawn(&active)?;Resume::Unit},Work::Check=>Resume::Unit,
                    _=>return Err(Error::Protocol),
                };drop(active);ctx.check(c)?;Ok(result)
            })(),
        };
        let reply=self.pending.reply.take().ok_or(Error::Conflict)?;ctx.pending.store(0,Ordering::Release);
        reply.send(result).map_err(|_|Error::Cancelled)
    }
}
#[doc(hidden)]
pub enum OwnedChatMonitorStartStep {Apply(OwnedChatMonitorStartApply),Ready(OwnedChatMonitorReady)}
#[doc(hidden)]
pub struct OwnedChatMonitorStartControl {context:Arc<Context>}
impl OwnedChatMonitorStartControl {
    pub fn ensure_current(&self,c:&Client)->Result<()>{self.context.check(c)}
    pub fn cancel(&self){self.context.cancel()}
    pub async fn retire(&self)->Result<()>{let result=self.context.retire().await;if result.is_err(){self.context.abandoned.store(true,Ordering::Release)}result}
    pub fn terminal(&self)->Option<OwnedChatMonitorStartTerminal>{self.context.terminal().then(||OwnedChatMonitorStartTerminal{context:self.context.clone()})}
}
/// Only acquisition IO/steps have returned; the actual monitor actor/socket is
/// separately transferred or retired. No socket/native/global/full-hint ACK.
#[doc(hidden)]
pub struct OwnedChatMonitorStartTerminal {context:Arc<Context>}
impl OwnedChatMonitorStartTerminal {pub fn acquisition_io_quiescent(&self)->bool{self.context.terminal()}}
#[doc(hidden)]
pub struct PreparedOwnedChatMonitor {context:Arc<Context>,future:Pin<Box<dyn Future<Output=Result<()>>>>,pending:mpsc::UnboundedReceiver<Pending>,finished:bool}
impl PreparedOwnedChatMonitor {
    pub fn control(&self)->OwnedChatMonitorStartControl{OwnedChatMonitorStartControl{context:self.context.clone()}}
    pub async fn next(&mut self)->Result<OwnedChatMonitorStartStep>{
        if self.finished||self.context.pending.load(Ordering::Acquire)!=0{return Err(Error::Conflict)}
        tokio::select!{biased;
            result=&mut self.future=>{self.finished=true;self.context.returned.store(true,Ordering::Release);result?;self.context.negative()?;Ok(OwnedChatMonitorStartStep::Ready(OwnedChatMonitorReady{context:self.context.clone()}))},
            pending=self.pending.recv()=>{let pending=pending.ok_or(Error::Cancelled)?;Ok(OwnedChatMonitorStartStep::Apply(OwnedChatMonitorStartApply{pending}))},
        }
    }
}
impl Drop for PreparedOwnedChatMonitor {fn drop(&mut self){if !self.finished{self.context.abandoned.store(true,Ordering::Release);self.context.cancel();}}}
#[doc(hidden)]
pub struct OwnedChatMonitorReady {context:Arc<Context>}
impl OwnedChatMonitorReady {
    pub fn ensure_current(&self,c:&Client)->Result<()>{self.context.check(c)}
    pub fn retain(&mut self,c:&Client)->Result<Arc<ChatMonitor>>{
        self.context.check(c)?;let monitor=self.context.monitor.lock().map_err(|_|Error::Protocol)?.as_ref().cloned().ok_or(Error::Conflict)?;
        self.context.retained.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;Ok(monitor)
    }
}
impl Drop for OwnedChatMonitorReady {fn drop(&mut self){if !self.context.retained.load(Ordering::Acquire){self.context.cancel();}}}
impl Client {
    /// Actual original monitor intent; no network/auth lock across next().
    /// Only this monitor slot is replaced, never another owned B/parent token.
    #[doc(hidden)]
    pub fn prepare_owned_chat_monitor(&mut self,request:CancellationToken,errors:mpsc::Sender<Error>)->Result<PreparedOwnedChatMonitor>{
        let original=Arc::new(OwnedOperationScope::capture(self,request)?);self.require_browser_owner_guards()?;
        let team=self.team()?.map(str::to_owned);let slot=original.request().child_token();
        if let Some(previous)=self.monitor_cancel.replace(slot.clone()){previous.cancel();}
        self.invalidate_chat_inventory_proofs();self.chat_list_freshness.invalidate();
        let context=Arc::new(Context{original,slot,team,monitor:Mutex::new(None),socket:Arc::new(Mutex::new(None)),errors:Mutex::new(Some(errors)),
            pending:AtomicU64::new(0),returned:AtomicBool::new(false),abandoned:AtomicBool::new(false),retained:AtomicBool::new(false)});
        context.check(self)?;let(send,pending)=mpsc::unbounded_channel();let channel=Channel{context:context.clone(),send};
        Ok(PreparedOwnedChatMonitor{context,future:Box::pin(drive(channel)),pending,finished:false})
    }
}
#[cfg(all(test,not(target_arch="wasm32")))]
#[path="monitor_start_owned_tests.rs"]
mod tests;
