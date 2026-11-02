//! One outstanding typed saved-send Client phase. No JSON/foreign constructor,
//! arbitrary endpoint/callback, replacement Client or socket receive owner.
use super::*;
use super::super::send::{prepared_transport::PreparedTurnTransport,prepared_turn::PreparedTurnContext};
use super::super::send::turn_runtime::{SavedTurnClientPhases,TurnPhaseFuture};
use tokio::sync::oneshot;
#[path="owned_saved_send_catalogue.rs"]
mod catalogue;
use catalogue::{CatalogueRoute,CatalogueWrappingPlan,TeamCacheStamp};
#[path="owned_saved_send_version.rs"]
mod version;
use version::{VersionStamp,PreparedVersionKey,CompletedVersionKey};
use super::super::transport::{PreparedOwnedRead,OwnedReadHeaders,OwnedReadBody,CompletedOwnedRead};
use crate::crypto::master::MasterCapability;
const MAX_PHASE_BYTES:usize=MAX_SCOPED_SAVED_SEND_QUARANTINE_BYTES;
// Await local close completion of the SAME original stream. Browser close now
// waits for its actual onclose/known CLOSED state; neither port claims a remote
// cancel/admission acknowledgement or saved-turn settlement from local close.
// A peer that already closed the stream has released it as well.
#[cfg(not(target_arch="wasm32"))]
async fn close_original_socket(socket:&mut Socket)->bool {
    matches!(socket.close(None).await,Ok(())|Err(tungstenite::Error::ConnectionClosed|tungstenite::Error::AlreadyClosed))
}
#[cfg(target_arch="wasm32")]
async fn close_original_socket(socket:&mut Socket)->bool {socket.close(None).await.is_ok()}
fn bound<T:serde::Serialize+?Sized>(value:&T)->Result<()> {scoped_serialized_size(value,MAX_PHASE_BYTES).map(|_|())}
fn focus_row_stamp(client:&Client,chat:&str)->Result<Option<String>> {
    let Some(row)=client.chats.get(chat) else{return Ok(None)};bound(row)?;
    let encoded=zeroize::Zeroizing::new(serde_json::to_string(row)?);Ok(Some(sha256(&encoded)))
}
struct PreparedBundle {transport:PreparedTurnTransport,context:PreparedTurnContext}
enum Call {
    Prepare {text:Arc<Plain<String>>,options:Arc<SendOptions>,updates:mpsc::Sender<StreamUpdate>},
    Check,
    FocusBegin {socket:Socket,chat:String},
    FocusCommit {chat:String,stamp:Option<String>,update:super::super::focus::FocusPersistenceUpdate,previous:Plain<Value>},
    CataloguePrepare(CatalogueRoute),
    CatalogueHeaders(OwnedReadHeaders),
    CatalogueBody(CompletedOwnedRead),
    CatalogueWrapping,
    CatalogueProjectCipher(Plain<Value>),
    CatalogueTeamKey {team:String,expected:TeamCacheStamp,wrapped:zeroize::Zeroizing<String>,key:Key},
    Subchat {socket:Socket,event:Plain<Value>,chat:String,task:String,updates:mpsc::Sender<StreamUpdate>,policy:SendConsentPolicy},
    Memory {socket:Socket,event:Plain<Value>,chat:String,message:String,key:Key,memories:Plain<Vec<Value>>,updates:mpsc::Sender<StreamUpdate>,policy:SendConsentPolicy},
    Replay {socket:Socket,outputs:Plain<BTreeMap<String,Value>>,root:Option<(String,Key)>},
    Artifacts {socket:Socket,chat:String,message:String,key:Key,task:String,embeds:Plain<BTreeMap<String,Value>>,checkpoints:Plain<Vec<Value>>},
    CanonicalOpen {chat:String},
    Tasks {socket:Socket,observed:Plain<SendObservations>,chat:String,message:String,key:Key,options:Arc<SendOptions>},
    Owner,
    VersionBegin(String),
    VersionKey {chat:String,stamp:VersionStamp,detail:Plain<Value>,wrapping:MasterCapability},
    VersionCommit {chat:String,key:Key,minimum:u64,completed:CompletedVersionKey},
    Withdraw {socket:Socket,chat:String,task:String},
}
enum Reply {
    Prepared(Box<PreparedBundle>),Unit,
    Focus {result:Result<()>,previous:Plain<Value>},
    FocusBoundary {stamp:Option<String>,team:Result<Option<String>>},
    CataloguePrepared(PreparedOwnedRead),CatalogueBody(OwnedReadBody),CatalogueValue(Plain<Value>),
    CatalogueWrapping(CatalogueWrappingPlan),CatalogueCipher {detail:Plain<Value>,cipher:zeroize::Zeroizing<String>},
    CatalogueTeamWrapping(MasterCapability),Frames(Plain<Vec<(String,Value)>>),
    Memory(Plain<(Vec<(String,Value)>,SendMemoryRequest)>),
    Count(usize),Items(Plain<Vec<Item>>),Chat(Plain<Chat>),
    Tasks {result:Result<()>,observed:Plain<SendObservations>},
    Owner(Plain<String>),Version(u64),VersionStamp(VersionStamp),VersionKey(PreparedVersionKey),
}
struct Envelope {
    context:Arc<OwnedSendContext>,call:Option<Call>,reply:Option<oneshot::Sender<Result<Reply>>>,
    completed:Arc<std::sync::atomic::AtomicBool>,
}
impl Drop for Envelope {
    fn drop(&mut self){
        if let Some(reply)=self.reply.take(){self.context.admission.scope.child().cancel();let _=reply.send(Err(Error::Cancelled));}
        // Scheduling observation of this exact owned phase's real drop/reply.
        // It never mints terminal, parent continuation, auth or IO-drain proof.
        self.completed.store(true,std::sync::atomic::Ordering::Release);
    }
}
/// Issued only by the actual driver after receiving its own typed command. An
/// abandoned step refuses that original future; it cannot settle/rearm anything.
#[doc(hidden)]
pub struct OwnedClientPhase {context:Arc<OwnedSendContext>,sequence:u64,envelope:Option<Envelope>}
/// Produced only by actual Client apply. Context/sequence and reply channel are
/// one-use Rust ownership, never supplied by caller status, JSON or an ACK bool.
#[doc(hidden)]
pub struct OwnedSavedSendResume {
    context:Arc<OwnedSendContext>,sequence:u64,envelope:Option<Envelope>,result:Option<Result<Reply>>,negative_withdrawal:bool,
}
// A started Client future must actually RETURN. Drop/cancel cannot settle it.
struct OwnedApplyLifetime {context:Arc<OwnedSendContext>,returned:bool}
impl OwnedApplyLifetime {
    fn start(context:Arc<OwnedSendContext>)->Self{context.apply_active.fetch_add(1,std::sync::atomic::Ordering::AcqRel);Self{context,returned:false}}
    fn returned(mut self){self.returned=true;}
}
impl Drop for OwnedApplyLifetime {
    fn drop(&mut self){if !self.returned{self.context.apply_abandoned.store(true,std::sync::atomic::Ordering::Release);}self.context.apply_active.fetch_sub(1,std::sync::atomic::Ordering::AcqRel);}
}
struct OwnedTurnPhases {context:Arc<OwnedSendContext>,sender:mpsc::Sender<Envelope>}
impl OwnedTurnPhases {
    async fn exchange(&self,call:Call)->Result<Reply>{
        let(reply,receive)=oneshot::channel();
        self.sender.send(Envelope{context:self.context.clone(),call:Some(call),reply:Some(reply),completed:Arc::new(false.into())}).await.map_err(|_|Error::Cancelled)?;
        receive.await.map_err(|_|Error::Cancelled)?
    }
    async fn check_now(&self)->Result<()> {match self.exchange(Call::Check).await?{Reply::Unit=>Ok(()),_=>Err(Error::Protocol)}}
    async fn deliver(&self,updates:&mpsc::Sender<StreamUpdate>,cancel:&CancellationToken,update:StreamUpdate)->Result<()> {
        let update=Plain::new(update);let guard=self.context.guard();
        let marker=matches!(&*update,StreamUpdate::Started{..}|StreamUpdate::Submitted{..}|StreamUpdate::Admitted{..}|StreamUpdate::Status(_));
        if !marker&&cancel.is_cancelled(){return Err(Error::Cancelled)}guard.check_release()?;
        match updates.try_reserve(){
            Ok(permit)=>{if !marker&&cancel.is_cancelled(){return Err(Error::Cancelled)}guard.check_release()?;permit.send(update.into_inner());return Ok(())},
            Err(tokio::sync::mpsc::error::TrySendError::Closed(_))=>{if cancel.is_cancelled(){return Err(Error::Cancelled)}return guard.check_release()},
            Err(tokio::sync::mpsc::error::TrySendError::Full(_))=>{},
        }
        // No Client/socket guard is held while the actual bounded host queue
        // waits. Only original negative resources wake/refuse this publication.
        let permit=tokio::select!{biased;
            _=self.context.admission.scope.cancelled()=>return Err(Error::Cancelled),
            _=cancel.cancelled()=>return Err(Error::Cancelled),
            permit=updates.reserve()=>permit,
        };
        if !marker&&cancel.is_cancelled(){return Err(Error::Cancelled)}guard.check_release()?;
        if let Ok(permit)=permit{permit.send(update.into_inner());}Ok(())
    }
}

impl OwnedTurnPhases {
    fn original_args(&self,scope:&super::super::sync_capability::AsyncCryptoScope,chat:&str,generation:u64)->Result<()> {
        if !std::ptr::eq(scope,&self.context.admission.scope.crypto)||generation!=self.context.generation{return Err(Error::Cancelled)}
        self.chat(chat)
    }
    fn chat(&self,chat:&str)->Result<()> {
        if self.context.admission.chat.as_deref().is_some_and(|expected|expected!=chat){return Err(Error::Cancelled)}
        let observation=self.context.observation.lock().map_err(|_|Error::Cancelled)?;
        if !observation.identity.as_ref().is_some_and(|actual|actual.chat_id()==chat){return Err(Error::Cancelled)}Ok(())
    }
    fn socket(&self,socket:&Socket)->Result<Socket>{self.context.check_socket(socket)?;Ok(socket.original_phase_handle())}
}
impl SavedTurnClientPhases for OwnedTurnPhases {
    fn check<'a>(&'a mut self,scope:&'a super::super::sync_capability::AsyncCryptoScope,chat:&'a str,generation:u64)->TurnPhaseFuture<'a,()>{
        Box::pin(async move{self.original_args(scope,chat,generation)?;self.check_now().await})
    }
    fn deliver_update<'a>(&'a mut self,scope:&'a super::super::sync_capability::AsyncCryptoScope,chat:&'a str,updates:&'a mpsc::Sender<StreamUpdate>,cancel:&'a CancellationToken,update:StreamUpdate)->TurnPhaseFuture<'a,()>{
        Box::pin(async move{self.original_args(scope,chat,self.context.generation)?;self.deliver(updates,cancel,update).await})
    }
    fn persist_focus_event<'a>(&'a mut self,ws:&'a mut Socket,kind:&'a str,event:&'a Value,chat:&'a str,key:&'a [u8;32],previous:&'a mut Value)->TurnPhaseFuture<'a,()>{
        Box::pin(async move{
            self.chat(chat)?;bound(&(event,&*previous))?;let socket=self.socket(ws)?;
            let(stamp,team)=match self.exchange(Call::FocusBegin{socket,chat:chat.into()}).await?{
                Reply::FocusBoundary{stamp,team}=>(stamp,team),_=>return Err(Error::Protocol),
            };
            // Defer the pure Team lookup Result until this selected kind needs
            // it; activation never consumes it. The shared plan preserves the
            // SAME lazy policy as the compatibility wrapper. The
            // original A previous scratch is reset before activation encryption
            // exactly as before; no Client/receive lock spans wire/ACK awaits.
            let mut plan=super::super::focus::FocusPersistencePlan::prepare(kind,event,chat,key,previous)?;
            while let Some(effect)=plan.next_effect(key,||team.clone())?{
                self.check_now().await?;self.context.guard().check_release()?;
                let(kind,payload,ack)=effect.into_wire();
                tokio::select!{biased;
                    _=self.context.admission.scope.cancelled()=>return Err(Error::Cancelled),
                    result=super::super::transport::send(ws,kind,payload)=>result?,
                }
                self.context.guard().check_release()?;
                if let Some(ack)=ack {
                    let(kind,field,value)=ack.wire_parts();
                    tokio::select!{biased;
                        _=self.context.admission.scope.cancelled()=>return Err(Error::Cancelled),
                        result=super::super::transport::wait(ws,kind,field,value)=>{drop(Plain::new(result?));},
                    }
                    self.context.guard().check_release()?;
                }
                self.check_now().await?;
            }
            let update=plan.into_update()?;let old=Plain::new(std::mem::take(previous));
            match self.exchange(Call::FocusCommit{chat:chat.into(),stamp,update,previous:old}).await?{
                Reply::Focus{result,previous:after}=>{previous.wipe();*previous=after.into_inner();result},_=>Err(Error::Protocol)
            }
        })
    }
    fn project_routing_catalog<'a>(&'a mut self,id:&'a str)->TurnPhaseFuture<'a,Vec<Value>>{
        Box::pin(async move{self.owned_project_catalogue(id).await})
    }
    fn subchat_consent<'a>(&'a mut self,ws:&'a mut Socket,event:&'a Value,chat:&'a str,task:&'a str,updates:&'a mpsc::Sender<StreamUpdate>,_cancel:&'a CancellationToken,policy:SendConsentPolicy)->TurnPhaseFuture<'a,Vec<(String,Value)>>{
        Box::pin(async move{self.chat(chat)?;bound(event)?;let socket=self.socket(ws)?;
            match self.exchange(Call::Subchat{socket,event:Plain::new(event.clone()),chat:chat.into(),task:task.into(),updates:updates.clone(),policy}).await?{Reply::Frames(frames)=>Ok(frames.into_inner()),_=>Err(Error::Protocol)}})
    }
    fn memory_consent<'a>(&'a mut self,ws:&'a mut Socket,event:&'a Value,chat:&'a str,message:&'a str,key:&'a [u8;32],memories:&'a [Value],updates:&'a mpsc::Sender<StreamUpdate>,_cancel:&'a CancellationToken,policy:SendConsentPolicy)->TurnPhaseFuture<'a,(Vec<(String,Value)>,SendMemoryRequest)>{
        Box::pin(async move{self.chat(chat)?;bound(&(event,memories))?;let socket=self.socket(ws)?;
            match self.exchange(Call::Memory{socket,event:Plain::new(event.clone()),chat:chat.into(),message:message.into(),key:zeroize::Zeroizing::new(*key),memories:Plain::new(memories.to_vec()),updates:updates.clone(),policy}).await?{Reply::Memory(value)=>Ok(value.into_inner()),_=>Err(Error::Protocol)}})
    }
    fn replay_outputs<'a>(&'a mut self,ws:&'a mut Socket,outputs:&'a BTreeMap<String,Value>,hint:Option<(&'a str,&'a [u8;32])>)->TurnPhaseFuture<'a,usize>{
        Box::pin(async move{bound(outputs)?;let socket=self.socket(ws)?;let root=match hint{Some((chat,key))=>{self.chat(chat)?;Some((chat.into(),zeroize::Zeroizing::new(*key)))},None=>None};
            match self.exchange(Call::Replay{socket,outputs:Plain::new(outputs.clone()),root}).await?{Reply::Count(count)=>Ok(count),_=>Err(Error::Protocol)}})
    }
    fn persist_stream_artifacts<'a>(&'a mut self,ws:&'a mut Socket,chat:&'a str,message:&'a str,key:&'a [u8;32],task:&'a str,embeds:&'a BTreeMap<String,Value>,checkpoints:&'a [Value])->TurnPhaseFuture<'a,Vec<Item>>{
        Box::pin(async move{self.chat(chat)?;bound(&(embeds,checkpoints))?;let socket=self.socket(ws)?;
            match self.exchange(Call::Artifacts{socket,chat:chat.into(),message:message.into(),key:zeroize::Zeroizing::new(*key),task:task.into(),embeds:Plain::new(embeds.clone()),checkpoints:Plain::new(checkpoints.to_vec())}).await?{Reply::Items(items)=>Ok(items.into_inner()),_=>Err(Error::Protocol)}})
    }
    fn open_chat_live<'a>(&'a mut self,id:&'a str)->TurnPhaseFuture<'a,Chat>{
        Box::pin(async move{self.chat(id)?;match self.exchange(Call::CanonicalOpen{chat:id.into()}).await?{Reply::Chat(chat)=>Ok(chat.into_inner()),_=>Err(Error::Protocol)}})
    }
    fn finish_task_jobs<'a>(&'a mut self,ws:&'a mut Socket,observed:&'a mut SendObservations,id:&'a str,message:&'a str,key:&'a [u8;32],_cancel:&'a CancellationToken,options:&'a SendOptions)->TurnPhaseFuture<'a,()>{
        Box::pin(async move{self.chat(id)?;let socket=self.socket(ws)?;let old=Plain::new(std::mem::take(observed));
            match self.exchange(Call::Tasks{socket,observed:old,chat:id.into(),message:message.into(),key:zeroize::Zeroizing::new(*key),options:Arc::new(options.clone())}).await?{
                Reply::Tasks{result,observed:after}=>{observed.wipe();*observed=after.into_inner();result},_=>Err(Error::Protocol)
            }
        })
    }
    fn owner_id(&mut self)->TurnPhaseFuture<'_,String>{Box::pin(async move{match self.exchange(Call::Owner).await?{Reply::Owner(owner)=>Ok(owner.into_inner()),_=>Err(Error::Protocol)}})}
    fn current_messages_version<'a>(&'a mut self,id:&'a str,key:&'a [u8;32],minimum:u64)->TurnPhaseFuture<'a,u64>{
        Box::pin(async move{self.chat(id)?;self.owned_current_messages_version(id,key,minimum).await})
    }
}

impl Client {
    /// Consume only an actual original opaque phase. Socket reads have already
    /// yielded their receive/queue guards before this method may be awaited.
    #[doc(hidden)]
    pub async fn apply_owned_saved_send_step(&mut self,mut step:OwnedClientPhase)->Result<OwnedSavedSendResume>{
        let context=step.context.clone();
        let negative=matches!(step.envelope.as_ref().and_then(|v|v.call.as_ref()),Some(Call::Withdraw{..}));
        let received_headers=matches!(step.envelope.as_ref().and_then(|v|v.call.as_ref()),Some(Call::CatalogueHeaders(_)));
        if !negative&&!received_headers{context.check_active_phase(self)?;}
        let mut envelope=step.envelope.take().ok_or(Error::Cancelled)?;
        if !Arc::ptr_eq(&envelope.context,&context){return Err(Error::Cancelled)}
        let call=envelope.call.take().ok_or(Error::Cancelled)?;
        let lifetime=OwnedApplyLifetime::start(context.clone());
        let returned=async {
        let result=if let Call::Withdraw{mut socket,chat,task}=call {
            context.check_socket(&socket)?;
            let same_chat=context.observation.lock().map_err(|_|Error::Cancelled)?.identity.as_ref().is_some_and(|id|id.chat_id()==chat);
            // Fixed authenticated negative request only. It grants no new read,
            // send, retry, rearm, or remote-cancel/settlement acknowledgement.
            if same_chat&&!task.is_empty()&&context.check_client(self,true).is_ok()
                &&self.task_watch_authority.cached_chat_allowed(&chat){
                let _=super::super::transport::send(&mut socket,"cancel_ai_task",json!({"task_id":task,"chat_id":chat})).await;
            }
            Ok(Reply::Unit)
        }else if let Call::CatalogueHeaders(headers)=call {
            // This opaque actual response already arrived. Retain matched real
            // credentials before refusing ONLY local A request/child stop; no
            // body/read/crypto/output authority is granted by this exception.
            context.root_fields(self)?;
            context.admission.scope.crypto.check_dispatched_credential_observation(self)?;
            let body=self.apply_owned_read_headers(headers)?;
            context.check_active_phase(self)?;
            Ok(Reply::CatalogueBody(body))
        }else{
            let scope=context.admission.scope.clone();
            let mut active=super::super::owned_operation::ActiveOwnedClient::enter(self,&scope)?;
            let result=async {
                match call {
                    Call::Prepare{text,options,updates}=>{
                        if active.scoped_send_quarantine.len()>=MAX_SCOPED_SAVED_SEND_QUARANTINES||active.scoped_send_quarantine_bytes>=MAX_SCOPED_SAVED_SEND_QUARANTINE_BYTES{return Err(Error::Conflict)}
                        let child=context.admission.scope.child();
                        if child.is_cancelled()||context.admission.request.is_cancelled(){return Err(Error::Cancelled)}
                        options.validate()?;
                        active.validate_saved_send_request(context.admission.chat.as_deref(),&text,&options,&child)?;
                        // This helper may create a socket before returning Err.
                        // Without an owned returned Socket there is no negative
                        // resource-completion witness, even if no socket was
                        // registered in this context. Keep that case held.
                        context.transport_resources_tracked.store(false,std::sync::atomic::Ordering::Release);
                        let mut transport=active.prepare_saved_turn_transport(context.admission.chat.as_deref(),&text,&options,&child).await?;
                        if context.socket.set(transport.ws.original_phase_handle()).is_err(){let _=transport.ws.close(None).await;return Err(Error::Cancelled)}
                        context.transport_resources_tracked.store(true,std::sync::atomic::Ordering::Release);
                        let team=std::mem::take(&mut *transport.team_preparation);
                        let prepared=active.prepare_turn_on_socket(&mut transport.ws,&transport.id,&transport.turn,&transport.message,
                            &text,&transport.key,&transport.wrapped,transport.baseline,transport.new_chat,&transport.existing,&transport.chat,
                            &updates,&child,transport.generation,team,&options,&context.admission.scope.crypto).await;
                        match prepared {
                            Ok(context)=>Ok(Reply::Prepared(Box::new(PreparedBundle{transport,context}))),
                            Err(error)=>{
                                if close_original_socket(&mut transport.ws).await{context.socket_returned.store(true,std::sync::atomic::Ordering::Release);}
                                Err(error)
                            },
                        }
                    },
                    Call::Check=>Ok(Reply::Unit),
                    Call::FocusBegin{socket,chat}=>{
                        context.check_socket(&socket)?;
                        if !context.observation.lock().map_err(|_|Error::Cancelled)?.identity.as_ref().is_some_and(|id|id.chat_id()==chat){return Err(Error::Cancelled)}
                        Ok(Reply::FocusBoundary{stamp:focus_row_stamp(&active,&chat)?,team:active.team().map(|team|team.map(str::to_owned))})
                    },
                    Call::FocusCommit{chat,stamp,update,mut previous}=>{
                        if !context.observation.lock().map_err(|_|Error::Cancelled)?.identity.as_ref().is_some_and(|id|id.chat_id()==chat){return Err(Error::Cancelled)}
                        // Exact A row only. B mutations never invalidate or roll
                        // back A; an intervening A mutation refuses this patch.
                        let result=if focus_row_stamp(&active,&chat)?!=stamp{Err(Error::Conflict)}
                            else{update.apply_to_chats(&chat,&mut active.chats,&mut previous)};
                        Ok(Reply::Focus{result,previous})
                    },
                    Call::CataloguePrepare(route)=>Ok(Reply::CataloguePrepared(catalogue::prepare_read(&mut active,route)?)),
                    Call::CatalogueBody(completed)=>Ok(Reply::CatalogueValue(Plain::new(active.finish_owned_read(completed)?.ok_or(Error::Protocol)?))),
                    Call::CatalogueWrapping=>Ok(Reply::CatalogueWrapping(catalogue::prepare_wrapping(&active)?)),
                    Call::CatalogueProjectCipher(detail)=>{
                        let cipher=zeroize::Zeroizing::new(active.object_key_ciphertext(Workspace::Projects,&detail["project"])?.to_owned());
                        Ok(Reply::CatalogueCipher{detail,cipher})
                    },
                    Call::CatalogueTeamKey{team,expected,wrapped,key}=>Ok(Reply::CatalogueTeamWrapping(catalogue::apply_team_key(&mut active,team,expected,wrapped,key)?)),
                    Call::CatalogueHeaders(_)=>Err(Error::Protocol),
                    Call::Subchat{mut socket,event,chat,task,updates,policy}=>{
                        context.check_socket(&socket)?;let child=context.admission.scope.child();
                        Ok(Reply::Frames(Plain::new(active.subchat_consent(&mut socket,&event,&chat,&task,&updates,&child,policy).await?)))
                    },
                    Call::Memory{mut socket,event,chat,message,key,memories,updates,policy}=>{
                        context.check_socket(&socket)?;let child=context.admission.scope.child();
                        Ok(Reply::Memory(Plain::new(active.memory_consent(&mut socket,&event,&chat,&message,&key,&memories,&updates,&child,policy).await?)))
                    },
                    Call::Replay{mut socket,outputs,root}=>{
                        context.check_socket(&socket)?;let hint=root.as_ref().map(|(chat,key)|(chat.as_str(),&**key));
                        Ok(Reply::Count(active.replay_outputs(&mut socket,&outputs,hint).await?))
                    },
                    Call::Artifacts{mut socket,chat,message,key,task,embeds,checkpoints}=>{
                        context.check_socket(&socket)?;
                        Ok(Reply::Items(Plain::new(active.persist_stream_artifacts(&mut socket,&chat,&message,&key,&task,&embeds,&checkpoints).await?)))
                    },
                    Call::CanonicalOpen{chat}=>Ok(Reply::Chat(Plain::new(active.open_chat_live(&chat).await?))),
                    Call::Tasks{mut socket,mut observed,chat,message,key,options}=>{
                        context.check_socket(&socket)?;let child=context.admission.scope.child();
                        let mut borrowed=super::super::send::turn_runtime::BorrowedTurnPhases{client:&mut active};
                        let result=borrowed.finish_task_jobs(&mut socket,&mut observed,&chat,&message,&key,&child,&options).await;
                        Ok(Reply::Tasks{result,observed})
                    },
                    Call::Owner=>{let owner=text(&active.user,"id");let owner=if owner.is_empty(){required(&active.user,"user_id")?}else{owner};Ok(Reply::Owner(Plain::new(owner.into())))},
                    Call::VersionBegin(chat)=>Ok(Reply::VersionStamp(version::stamp(&active,&chat)?)),
                    Call::VersionKey{chat,stamp,detail,wrapping}=>Ok(Reply::VersionKey(version::prepare_key(&active,&chat,stamp,detail,&wrapping)?)),
                    Call::VersionCommit{chat,key,minimum,completed}=>Ok(Reply::Version(version::commit(&mut active,&chat,&key,minimum,completed)?)),
                    Call::Withdraw{..}=>Err(Error::Protocol),
                }
            }.await;
            drop(active);
            // Keep actual remote/header durability even on refusal; only the
            // private result is discarded. Never restore a global snapshot.
            match result{Ok(value)=>match context.check_active_phase(self){Ok(())=>Ok(value),Err(error)=>Err(error)},Err(error)=>Err(error)}
        };
        Ok(OwnedSavedSendResume{context,sequence:step.sequence,envelope:Some(envelope),result:Some(result),negative_withdrawal:negative})
        }.await;
        lifetime.returned();returned
    }
}

#[cfg(not(target_arch="wasm32"))]
type RunFuture=std::pin::Pin<Box<dyn std::future::Future<Output=Result<Plain<Chat>>>+Send+'static>>;
#[cfg(target_arch="wasm32")]
type RunFuture=std::pin::Pin<Box<dyn std::future::Future<Output=Result<Plain<Chat>>>+'static>>;
/// Finite public refusal only; no private output or settlement/continuation.
#[derive(Clone,Copy,Debug,PartialEq,Eq)]
#[doc(hidden)]
pub enum OwnedSavedSendRefusalReason {ObservationUnavailable,AdmissionUnverifiable}
impl OwnedSavedSendRefusalReason {pub fn code(self)->&'static str{match self{Self::ObservationUnavailable=>"owned_send_observation_unavailable",Self::AdmissionUnverifiable=>"owned_send_admission_unverifiable"}}}
/// Sealed actual LOCAL Core return/refusal. Native/Host output queues and remote
/// settlement remain separate. No constructor/Clone/serde/publication/rearm.
#[doc(hidden)]
pub struct OwnedSavedSendReturnedRefusal {context:Arc<OwnedSendContext>,reason:OwnedSavedSendRefusalReason}
impl OwnedSavedSendReturnedRefusal {
    pub fn consume_for(self,original:&OwnedSavedSendControl)->Result<OwnedSavedSendRefusalReason>{
        if !Arc::ptr_eq(&self.context,&original.context){return Err(Error::Cancelled)}
        Ok(self.reason)
    }
}
/// Actual returned send future only. No constructor, Clone, serde or caller
/// outcome can create this proof. Completion/uncertainty is not remote cancel.
#[doc(hidden)]
pub struct OwnedSavedSendTerminal {
    context:Arc<OwnedSendContext>,result:Option<Result<Plain<Chat>>>,outcome:SavedSendOutcome,
    recovery:Option<SavedSendRecoveryIdentity>,consumed:bool,
}
impl OwnedSavedSendTerminal {pub fn outcome(&self)->SavedSendOutcome{self.outcome}}
impl Drop for OwnedSavedSendTerminal {
    fn drop(&mut self){if !self.consumed{self.context.admission.scope.child().cancel();self.context.admission.gate.finish(&self.context.admission.id,false);}}
}
#[doc(hidden)]
pub enum OwnedSavedSendStep {Apply(OwnedClientPhase),Terminal(OwnedSavedSendTerminal)}
/// Owns transport/crypto/task state, never a Client. One command must actually
/// apply/resume before the next drive can proceed; a copied sequence grants nothing.
#[doc(hidden)]
pub struct OwnedSavedSendDriver {
    context:Arc<OwnedSendContext>,receiver:mpsc::Receiver<Envelope>,running:Option<RunFuture>,
    sequence:u64,pending:Option<(u64,Arc<std::sync::atomic::AtomicBool>)>,terminal_returned:bool,returned_refusal:Option<OwnedSavedSendRefusalReason>,refusal_taken:bool,
}
/// Separate negative control remains callable while the actual driver awaits.
/// It cannot touch a different Client/turn or mint terminal continuation.
#[derive(Clone)]
#[doc(hidden)]
pub struct OwnedSavedSendControl {context:Arc<OwnedSendContext>}
impl OwnedSavedSendControl {
    pub fn cancel(&self){self.context.admission.request.cancel();self.context.admission.scope.child().cancel();}
    pub fn publication_guard(&self)->SavedSendPublicationGuard{self.context.guard()}
}
impl Drop for OwnedSavedSendDriver {
    fn drop(&mut self){
        if !self.terminal_returned{
            self.context.admission.scope.child().cancel();
            self.context.admission.gate.finish(&self.context.admission.id,false);
            // The original observation stays in its SAME Client. Drop cannot
            // settle/replay the turn or authorize a successor. Durable encrypted
            // journal/reload remains a separate required acceptance criterion.
        }
    }
}
impl OwnedSavedSendDriver {
    fn refuse_returned(&mut self,reason:OwnedSavedSendRefusalReason){
        self.returned_refusal=Some(reason);
        self.context.admission.scope.child().cancel();self.context.admission.publication.cancel();
        // Negative A-only retirement. Never rearm this gate or touch Client B.
        self.context.admission.gate.finish(&self.context.admission.id,false);
    }
    pub fn take_returned_refusal(&mut self)->Option<OwnedSavedSendReturnedRefusal>{
        if !self.terminal_returned||self.running.is_some()||self.pending.is_some()||self.refusal_taken
            ||!self.context.resources_returned(){return None}
        let reason=self.returned_refusal?;
        // The actual future has returned and the channel holds at most one
        // unstarted command. Closing/discarding it is not completion evidence:
        // all actual resource-return conditions were checked above first.
        self.receiver.close();
        if let Ok(envelope)=self.receiver.try_recv(){drop(envelope);}
        self.refusal_taken=true;
        Some(OwnedSavedSendReturnedRefusal{context:self.context.clone(),reason})
    }
    pub fn control(&self)->OwnedSavedSendControl{OwnedSavedSendControl{context:self.context.clone()}}
    pub async fn drive_next(&mut self)->Result<OwnedSavedSendStep>{
        if let Some((_,completed))=&self.pending {
            if !completed.load(std::sync::atomic::Ordering::Acquire){return Err(Error::Conflict)}
            self.pending=None;
        }
        loop {
            let running=self.running.as_mut().ok_or(Error::Cancelled)?;
            tokio::select!{biased;
                result=running.as_mut()=>{
                    self.running.take();self.terminal_returned=true;
                    // Return of the protocol future is insufficient if a Client
                    // apply was abandoned, transport preparation lost a socket,
                    // or actual close failed. Neither terminal nor refusal may
                    // authorize continuation/drain from an unknown resource.
                    if !self.context.resources_returned(){return Err(Error::Cancelled)}
                    let observation=self.context.observation.clone();
                    let observed=match observation.lock(){Ok(value)=>value,Err(_)=>{self.refuse_returned(OwnedSavedSendRefusalReason::ObservationUnavailable);return Err(Error::Cancelled)}};
                    if observed.attempted&&observed.admission.is_none(){drop(observed);self.refuse_returned(OwnedSavedSendRefusalReason::AdmissionUnverifiable);return Err(Error::Protocol)}
                    let outcome=match &result{
                        Ok(chat) if self.context.admission.chat.as_deref().is_none_or(|id|chat.id==id)=>SavedSendOutcome::Completed,
                        Ok(_)=>SavedSendOutcome::SessionExpired,
                        Err(Error::Conflict) if !observed.attempted=>SavedSendOutcome::Backpressure,
                        Err(Error::Cancelled) if observed.attempted=>SavedSendOutcome::Uncertain,
                        Err(Error::Cancelled)=>SavedSendOutcome::Cancelled,
                        Err(Error::Expired|Error::Authentication|Error::Forbidden)=>SavedSendOutcome::SessionExpired,
                        Err(_) if observed.attempted=>SavedSendOutcome::Uncertain,
                        // A cancelled request that never attempted (e.g. while
                        // awaiting its context snapshot) is a cancellation, not
                        // an unavailable gate that refuses every later send.
                        Err(_) if self.context.admission.request.is_cancelled()=>SavedSendOutcome::Cancelled,
                        Err(_)=>SavedSendOutcome::Unavailable,
                    };
                    let result=if outcome==SavedSendOutcome::Cancelled{Err(Error::Cancelled)}else{result};
                    let recovery=observed.identity.clone();drop(observed);
                    return Ok(OwnedSavedSendStep::Terminal(OwnedSavedSendTerminal{context:self.context.clone(),result:Some(result),outcome,recovery,consumed:false}));
                },
                envelope=self.receiver.recv()=>{
                    let Some(mut envelope)=envelope else{continue};
                    if !Arc::ptr_eq(&envelope.context,&self.context){continue}
                    let Some(sequence)=self.sequence.checked_add(1) else{
                        if let Some(reply)=envelope.reply.take(){let _=reply.send(Err(Error::Conflict));}continue;
                    };
                    self.sequence=sequence;self.pending=Some((sequence,envelope.completed.clone()));
                    return Ok(OwnedSavedSendStep::Apply(OwnedClientPhase{context:self.context.clone(),sequence,envelope:Some(envelope)}));
                }
            }
        }
    }
    pub fn resume(&mut self,mut resume:OwnedSavedSendResume)->Result<()>{
        if !Arc::ptr_eq(&resume.context,&self.context)||self.pending.as_ref().map(|(sequence,_)|*sequence)!=Some(resume.sequence){return Err(Error::Cancelled)}
        let mut envelope=resume.envelope.take().ok_or(Error::Cancelled)?;
        if !Arc::ptr_eq(&envelope.context,&self.context){return Err(Error::Cancelled)}
        let mut result=resume.result.take().ok_or(Error::Cancelled)?;
        if result.is_ok()&&!resume.negative_withdrawal {
            if let Err(error)=self.context.guard().check_release(){result=Err(error);}
        }
        self.pending=None;
        envelope.reply.take().ok_or(Error::Cancelled)?.send(result).map_err(|_|Error::Cancelled)
    }
}
async fn run_protocol(context:Arc<OwnedSendContext>,sender:mpsc::Sender<Envelope>,text:Arc<Plain<String>>,
    options:Arc<SendOptions>,updates:mpsc::Sender<StreamUpdate>)->Result<Plain<Chat>>{
    let mut phases=OwnedTurnPhases{context:context.clone(),sender};
    let mut task=String::new();
    let mut trace=super::super::send::SendTrace::new();
    let result=async {
        let child=context.admission.scope.child();
        if child.is_cancelled()||context.admission.request.is_cancelled(){return Err(Error::Cancelled)}
        let bundle=match phases.exchange(Call::Prepare{text:text.clone(),options:options.clone(),updates:updates.clone()}).await?{
            Reply::Prepared(value)=>value,_=>return Err(Error::Protocol),
        };
        let PreparedBundle{transport,context:prepared}=*bundle;
        let PreparedTurnTransport{generation,id,turn,message,mut chat,new_chat,key,wrapped,baseline,existing:_,team_preparation:_,mut ws,release_scope:_}=transport;
        let outcome=super::super::send::turn_runtime::receive_turn(&mut phases,&mut ws,prepared,&context.admission.scope.crypto,
            &id,&turn,&message,&text,&key,&wrapped,baseline,new_chat,&mut chat,&updates,&child,generation,&options,&mut trace,&mut task).await;
        let mut outcome=Plain::new(outcome?);
        phases.check_now().await?;
        if child.is_cancelled()||context.admission.request.is_cancelled(){return Err(Error::Cancelled)}
        context.guard().check_release()?;
        Ok(Plain::new(std::mem::take(&mut outcome.chat)))
    }.await;
    // All receive futures and queue guards above have RETURNED before this
    // exact original negative Client phase can be issued. No socket guard held.
    if result.is_err()&&!task.is_empty()&&(context.admission.request.is_cancelled()||context.admission.scope.child().is_cancelled()){
        if let Some(socket)=context.socket.get(){
            let chat=context.observation.lock().ok().and_then(|v|v.identity.as_ref().map(|id|id.chat_id().to_owned()));
            if let Some(chat)=chat{let _=phases.exchange(Call::Withdraw{socket:socket.original_phase_handle(),chat,task}).await;}
        }
    }
    let socket_returned=if context.socket_returned.load(std::sync::atomic::Ordering::Acquire){true}
        else if let Some(socket)=context.socket.get(){let mut original=socket.original_phase_handle();close_original_socket(&mut original).await}
        else{context.transport_resources_tracked.load(std::sync::atomic::Ordering::Acquire)};
    context.socket_returned.store(socket_returned,std::sync::atomic::Ordering::Release);
    if matches!(&result,Err(Error::Protocol))&&context.socket.get().is_some(){trace.report_protocol_error();}
    result
}
impl Client {
    /// Synchronous ownership start only. Its actual future asks for typed Client
    /// phases, so socket/crypto/host-queue waits never retain this mutable borrow.
    #[doc(hidden)]
    pub fn start_owned_saved_send(&mut self,mut prepared:PreparedOwnedSavedSend,text:&str,updates:mpsc::Sender<StreamUpdate>)->Result<OwnedSavedSendDriver>{
        let admission=prepared.admission.take().ok_or(Error::Cancelled)?;
        let observation=Arc::new(std::sync::Mutex::new(ScopedSendObservation::default()));
        let context=Arc::new(OwnedSendContext{admission,observation:observation.clone(),socket:std::sync::OnceLock::new(),generation:self.generation,terminal_consumed:std::sync::atomic::AtomicBool::new(false),apply_active:0.into(),apply_abandoned:false.into(),socket_returned:false.into(),transport_resources_tracked:true.into()});
        let stopped=context.admission.request.is_cancelled()||context.admission.scope.child().is_cancelled();
        context.check_client(self,stopped)?;
        if self.scoped_send_observation.is_some(){return Err(Error::Conflict)}
        context.admission.gate.start(&context.admission.id,&context.admission.publication)?;
        self.scoped_send_observation=Some(observation);
        let(sender,receiver)=mpsc::channel(1);let text=Arc::new(Plain::new(text.to_owned()));let options=Arc::new(SendOptions::default());
        let original=context.clone();
        let running=Box::pin(async move{
            let protocol=run_protocol(original.clone(),sender,text,options,updates);tokio::pin!(protocol);
            tokio::select!{biased;
                result=&mut protocol=>result,
                _=original.admission.scope.cancelled()=>{original.admission.scope.child().cancel();protocol.await},
            }
        });
        Ok(OwnedSavedSendDriver{context,receiver,running:Some(running),sequence:0,pending:None,terminal_returned:false,returned_refusal:None,refusal_taken:false})
    }
}

/// One-use release after the ACTUAL owned future returned. The old original
/// scope remains retained; continuation is a new sibling under its SAME parent,
/// never cancellation reset, replay, or settlement of an uncertain turn.
#[doc(hidden)]
pub struct OwnedSavedSendDisposition {
    context:Arc<OwnedSendContext>,continuation:Option<OwnedOperationScope>,epoch:u64,receipt:String,
    result:Option<Result<Plain<Chat>>>,outcome:SavedSendOutcome,reusable:bool,cancelled_result:bool,
    recovery:Option<SavedSendRecoveryIdentity>,
}
impl OwnedSavedSendDisposition {
    pub fn operation_id(&self)->&str{&self.context.admission.id}
    pub fn scope_epoch(&self)->u64{self.epoch}
    pub fn receipt_id(&self)->&str{&self.receipt}
    pub fn outcome(&self)->SavedSendOutcome{self.outcome}
    pub fn reusable(&self)->bool{self.can_continue_parent()}
    pub fn can_continue_parent(&self)->bool{self.reusable}
    pub fn original_turn_settled(&self)->bool{matches!(self.outcome,SavedSendOutcome::Completed|SavedSendOutcome::Cancelled|SavedSendOutcome::Backpressure)}
    pub fn original_cancelled_result(&self)->bool{self.cancelled_result}
    pub fn check_current(&self,client:&Client)->Result<()> {
        self.context.check_client(client,true)?;
        if self.epoch!=client.fresh_auth.operation_epoch(){return Err(Error::Cancelled)}
        if let Some(scope)=&self.continuation{scope.check(client)?;}
        self.context.root_fields(client)
    }
    pub fn publication_guard(&self)->SavedSendPublicationGuard {
        let original=&self.context.admission;
        let scope=self.continuation.as_ref();
        SavedSendPublicationGuard{id:original.id.clone(),child:scope.map_or_else(||original.scope.child(),OwnedOperationScope::child),
            parent:original.parent.clone(),publication:original.publication.clone(),resources:original.scope.crypto.negative_observer(),
            request:if matches!(self.outcome,SavedSendOutcome::Cancelled|SavedSendOutcome::Uncertain|SavedSendOutcome::Backpressure){None}else{Some(original.request.clone())},
            owned_lease:scope.map(OwnedOperationScope::publication_lease),gate:original.gate.clone(),private_gate:original.private_gate.clone()}
    }
    pub fn recovery_identity(&self,client:&Client)->Result<Option<&SavedSendRecoveryIdentity>>{self.check_current(client)?;Ok(self.recovery.as_ref())}
    pub fn encode_result_json(&mut self,client:&Client)->Result<zeroize::Zeroizing<String>>{
        self.check_current(client)?;self.publication_guard().check_release()?;
        let value=self.result.take().ok_or(Error::Cancelled)??;
        let encoded=zeroize::Zeroizing::new(serde_json::to_string(&*value)?);
        self.check_current(client)?;self.publication_guard().check_release()?;Ok(encoded)
    }
    pub fn take_result(&mut self,client:&Client)->Result<Chat>{
        self.check_current(client)?;self.publication_guard().check_release()?;
        self.result.take().ok_or(Error::Cancelled)?.map(Plain::into_inner)
    }
}
impl Client {
    #[doc(hidden)]
    pub fn finish_owned_saved_send(&mut self,mut terminal:OwnedSavedSendTerminal)->Result<OwnedSavedSendDisposition>{
        let context=terminal.context.clone();
        // Only the actual private terminal type reaches this exception. No
        // caller/server "cancelled" label can ignore a live operation's child.
        context.check_client(self,true)?;
        if !self.scoped_send_observation.as_ref().is_some_and(|v|Arc::ptr_eq(v,&context.observation)){return Err(Error::Cancelled)}
        context.admission.gate.check_publication(&context.admission.id,&context.admission.publication)?;
        let reusable=matches!(terminal.outcome,SavedSendOutcome::Completed|SavedSendOutcome::Cancelled|SavedSendOutcome::Uncertain|SavedSendOutcome::Backpressure);
        let continuation=if reusable {
            // Original proof before AND after this synchronous canonical sibling
            // issue; no await/current-user relabel or broad token replacement.
            let scope=OwnedOperationScope::capture(self,CancellationToken::new())?;
            context.check_client(self,true)?;Some(scope)
        }else{None};
        if terminal.outcome==SavedSendOutcome::Uncertain {
            if self.scoped_send_quarantine.contains_key(&context.admission.id)||self.scoped_send_quarantine.len()>=MAX_SCOPED_SAVED_SEND_QUARANTINES{return Err(Error::Conflict)}
            let original=context.observation.lock().map_err(|_|Error::Cancelled)?;
            let matches_identity=match (&original.identity,&terminal.recovery){
                (Some(a),Some(b))=>a.chat_id()==b.chat_id()&&a.turn_id()==b.turn_id()&&a.message_id()==b.message_id(),_=>false,
            };
            if !original.attempted||original.admission.is_none()||!matches_identity{return Err(Error::Cancelled)}
            let bytes=self.scoped_send_quarantine_bytes.checked_add(original.admission_bytes).filter(|bytes|*bytes<=MAX_SCOPED_SAVED_SEND_QUARANTINE_BYTES).ok_or(Error::Conflict)?;
            drop(original);
            self.scoped_send_quarantine.insert(context.admission.id.clone(),context.observation.clone());
            self.scoped_send_quarantine_bytes=bytes;
        }
        self.scoped_send_observation=None;
        let disposition=OwnedSavedSendDisposition{context:context.clone(),continuation,epoch:self.fresh_auth.operation_epoch(),
            receipt:uuid::Uuid::new_v4().to_string(),cancelled_result:matches!(terminal.result.as_ref(),Some(Err(Error::Cancelled))),
            result:terminal.result.take(),outcome:terminal.outcome,reusable,recovery:terminal.recovery.take()};
        disposition.check_current(self)?;
        terminal.consumed=true;
        context.terminal_consumed.store(true,std::sync::atomic::Ordering::Release);
        // Retire only A. Its old queued live-update guard never borrows the new
        // continuation child; healthy sibling reads/monitors stay untouched.
        context.admission.scope.child().cancel();
        context.admission.gate.finish(&context.admission.id,reusable);
        Ok(disposition)
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="owned_saved_send_close_refusal_tests.rs"]
mod close_refusal_tests;
