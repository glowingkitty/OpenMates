//! SAME actual original-monitor refresh dispatch. No raw receipt/DTO/input
//! can construct this batch/row seed. Parser DATA is not freshness/IO authority.
use super::*;
use crate::client::sync::SyncPhaseReadData;
use std::collections::VecDeque;
#[doc(hidden)]
pub enum OriginalHintRefreshAdmission {Driven(OwnedBrowserReadDriver),NotRequired(OwnedBrowserMetadataContinuation)}
pub(super) struct RefreshData {retained:RetainedData,read:Plain<SyncPhaseReadData>}
pub(super) fn begin(remainder:OwnedBrowserMetadataContinuation,client:&Client)->Result<OriginalHintRefreshAdmission>{
    remainder.check_original(client)?;if !remainder.metadata_committed{return Err(Error::Conflict)}
    let Mode::Incoming(monitor)=&remainder.context.mode else{return Err(Error::Forbidden)};
    if !monitor.original_refresh_required()?{return Ok(OriginalHintRefreshAdmission::NotRequired(remainder))}
    remainder.context.refresh_issued.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
    let context=remainder.context;let(send,pending)=mpsc::unbounded_channel();let drain=Arc::new(DriverDrainState::for_context(&context));
    let channel=Channel{context:context.clone(),drain:drain.clone(),send};
    let future=Box::pin(async move{drive(channel,remainder.data).await.map(Outcome::Refresh)});
    Ok(OriginalHintRefreshAdmission::Driven(OwnedBrowserReadDriver{context,future,pending,finished:false,drain}))
}
async fn drive(channel:Channel,retained:RetainedData)->Result<RefreshData>{
    let Resume::MonitorPrepared(ticket)=channel.apply(Work::PrepareMonitorRefresh).await?else{return Err(Error::Protocol)};
    channel.context.negative()?;
    // Do not select-drop actual original dispatched ticket. Its own native
    // actor handles cancellation/physical receive ownership before replying.
    let receipt=ticket.wait().await?;channel.context.negative()?;
    let Resume::MonitorData(data)=channel.apply(Work::TakeMonitorRead(receipt)).await?else{return Err(Error::Protocol)};
    let crate::client::monitor::MonitorReadData::RecentSync(read)=data else{return Err(Error::Protocol)};
    channel.context.negative()?;Ok(RefreshData{retained,read})
}
#[doc(hidden)]
pub struct OriginalHintRefreshBatch {
    pub(super) context:Arc<Context>,pub(super) retained:RetainedData,pub(super) read:Plain<SyncPhaseReadData>,pending:VecDeque<String>,pub(super) ledger:Arc<row_ledger::RowLedger>,
}
impl OriginalHintRefreshBatch {
    pub(super) fn from_actual_read(context:Arc<Context>,data:RefreshData)->Self{
        let pending=data.read.chat_arrival_order.iter().cloned().collect();Self{context,retained:data.retained,read:data.read,pending,ledger:Arc::new(row_ledger::RowLedger::default())}
    }
    pub fn ensure_current(&self,client:&Client)->Result<()>{self.context.check(client)}
    /// Only received exact rows are dispatched. Omitted old rows have NO
    /// deletion meaning; all Phase1/sidecar/draft work remains owned in read.
    pub fn next_row(&mut self,client:&Client)->Result<Option<OriginalHintRowSeed>>{
        self.context.check(client)?;let Some(id)=self.pending.front().cloned()else{return Ok(None)};
        self.context.scope.crypto.check_chat(client,&id)?;
        let row=Plain::new(self.read.chats.get(&id).ok_or(Error::Protocol)?.clone());
        let Mode::Incoming(monitor)=&self.context.mode else{return Err(Error::Forbidden)};
        monitor.check_chat_metadata_floor(&id,&row)?;BrowserOwnedMetadataFloor::capture(client,&id)?.check(&row)?;
        let draft=crate::client::sync::draft_only(&row);
        if draft{client.validate_draft_row_scope(&row,&id)?;}else{client.browser_message_cache_metadata_guard(&row,&id)?;}
        let source=crate::client::browser::original_draft_bounds::source_stamp(client,&id)?;let before=Plain::new(client.chats.get(&id).cloned());
        let wrappers=Plain::new(self.read.wrappers.clone());self.context.check(client)?;
        let ticket=self.ledger.issue(&id,&row,&source,draft)?;self.pending.pop_front();
        Ok(Some(OriginalHintRowSeed{context:self.context.clone(),id,row,wrappers,before,source,draft,host:self.retained.plan["scope"].clone(),ledger:self.ledger.clone(),ticket}))
    }
    pub fn cancel(&self){self.context.scope.observer().cancel();}
    pub async fn wait_cancelled(&self){self.context.cancelled().await}
    // Deliberately NO full-hint complete/take/ack method. Even pending.empty()
    // cannot certify uncommitted row seeds, Phase1 crypto/IO, drafts/sidecars.
}
#[doc(hidden)]
pub struct OriginalHintRowSeed {
    pub(super) context:Arc<Context>,pub(super) id:String,pub(super) row:Plain<Value>,pub(super) wrappers:Plain<Vec<Value>>,
    pub(super) before:Plain<Option<Value>>,pub(super) source:String,pub(super) draft:bool,pub(super) host:Value,pub(super) ledger:Arc<row_ledger::RowLedger>,pub(super) ticket:u64,
}
impl OriginalHintRowSeed {
    pub fn ensure_current(&self,client:&Client)->Result<()> {
        self.context.check(client)?;self.context.scope.crypto.check_chat(client,&self.id)?;
        if crate::client::browser::original_draft_bounds::source_stamp(client,&self.id)?!=self.source||client.chats.get(&self.id)!=self.before.as_ref(){return Err(Error::Conflict)}
        self.context.negative()
    }
    pub fn chat_id(&self)->&str{&self.id}
    pub fn is_personal_draft_data(&self)->bool{self.draft}
    // Internal next-phase data; never a positive output/storage authority.
    pub(in crate::client) fn row(&self)->&Value{&self.row}
    pub(in crate::client) fn wrappers(&self)->&[Value]{&self.wrappers}
}
