//! Original opaque row seed -> SAME existing header bootstrap and metadata
//! physical CAS policy. Draft-only resources retain their genuine dispatch.
use super::*;
#[doc(hidden)]
pub enum OriginalHintRowMetadataAdmission {Saved(OwnedBrowserReadDriver),Draft(OriginalHintRowSeed)}
pub(super) struct RowMetadataData {pub(super) seed:OriginalHintRowSeed,pub(super) metadata:MetadataData}
#[doc(hidden)]
pub struct OriginalHintRowMetadataPublication {pub(super) context:Arc<Context>,pub(super) data:RowMetadataData}
impl OriginalHintRowSeed {
    pub fn begin_metadata(self,client:&Client,now_seconds:u64)->Result<OriginalHintRowMetadataAdmission>{
        self.ensure_current(client)?;
        if self.draft{return Ok(OriginalHintRowMetadataAdmission::Draft(self))}
        if now_seconds>MAX_SAFE{return Err(Error::Protocol)}
        client.metadata_cache_scope(&self.context.owner,&self.id,BrowserMetadataCacheMode::PersistCurrent)?;
        let Mode::Incoming(monitor)=&self.context.mode else{return Err(Error::Forbidden)};
        let floors=BrowserOwnedMetadataFloor::capture(client,&self.id)?;
        let desired=normalized(&self.row,&self.id,&self.context.owner,false)?;
        let context=Arc::new(Context{profile_absence:Mutex::new(None),profile_cache:None,scope:self.context.scope.clone(),mode:Mode::Incoming(monitor.clone()),
            original:Some(self.context.clone()),server_wrappers:Some(Plain::new((*self.wrappers).clone())),
            owner:self.context.owner.clone(),chat:self.id.clone(),cursor_scope:self.context.cursor_scope.clone(),
            source:Mutex::new(self.source.clone()),floors:Mutex::new(floors),options:Default::default(),
            recovery_issued:self.context.recovery_issued.clone(),recovery_active:self.context.recovery_active.clone(),refresh_issued:AtomicBool::new(false),inventory_issued:AtomicBool::new(false),inventory_drain:self.context.inventory_drain.clone(),inventory_working_issued:Mutex::new(BTreeSet::new()),inventory_finished:AtomicBool::new(false),original_draft_budget:AtomicBool::new(crate::client::browser::original_draft_bounds::has_budget(client,&self.id)?),next:AtomicU64::new(1),outstanding:AtomicU64::new(0),
            evidence:Mutex::new(None),source_metadata:Mutex::new(Some(desired))});
        context.check(client)?;let(send,pending)=mpsc::unbounded_channel();let drain=Arc::new(DriverDrainState::for_context(&context));
        let channel=Channel{context:context.clone(),drain:drain.clone(),send};
        let future=Box::pin(async move{drive_row(channel,self,now_seconds).await.map(Outcome::RowMetadata)});
        Ok(OriginalHintRowMetadataAdmission::Saved(OwnedBrowserReadDriver{context,future,pending,finished:false,drain}))
    }
}
async fn drive_row(channel:Channel,seed:OriginalHintRowSeed,now_seconds:u64)->Result<RowMetadataData>{
    let ctx=channel.context.clone();ctx.negative()?;
    let key=channel.unwrap(Plain::new((*seed.row).clone()),KeyKind::Server).await?;
    // Empty messages means metadata-only bootstrap, not an empty/full history
    // claim. Actual original raw actor row and derived key never leave Rust.
    let raw=crate::client::message_window::BrowserIncomingMessagePage{metadata:Plain::new((*seed.row).clone()),messages:Plain::new(Vec::new()),key};
    let host:BrowserMetadataCacheScope=serde_json::from_value(seed.host.clone())?;
    let mut check=||ctx.negative();let io_channel=channel.clone();
    let mut io=move|encoded:String|{let channel=io_channel.clone();async move{channel.io(encoded).await}};
    let keys=channel.clone();let unwrap=move|row:Plain<Value>|{let channel=keys.clone();async move{channel.validate_metadata(row).await}};
    // Exact existing builder/defaults, null-header CAS, full postimage and
    // metadata-only physical reread. It never clears an existing draft/header.
    let retained=drive_incoming_cache_policy_budget(&ctx.owner,&ctx.chat,host,raw,true,false,Some(now_seconds),&mut check,unwrap,&mut io,ctx.io_budget()).await?;
    // Same existing metadata-field clock/key/patch/raw prepost/readback policy
    // handles both already present and just genuinely bootstrapped headers.
    let metadata=drive_metadata(channel,retained).await?;
    Ok(RowMetadataData{seed,metadata})
}
impl OriginalHintRowMetadataPublication {
    pub(super) fn from_actual(context:Arc<Context>,data:RowMetadataData)->Self{Self{context,data}}
    pub fn ensure_current(&self,client:&Client)->Result<()>{self.context.check(client)?;self.data.seed.ensure_current(client)}
    pub fn kind(&self)->&'static str{"original_hint_row_metadata_pending_client_apply"}
    #[cfg(test)]
    pub(super) fn physical_for_test(&self)->&Value{&self.data.metadata.physical}
    pub fn chat_id(&self)->&str{&self.data.seed.id}
    // No take/remainder/finish/ACK yet: actual owning Host IO drain and a sealed
    // original before->after Client row apply remain required before dispatch
    // accumulator may mark this row handled. Physical stores alone cannot
    // acknowledge drafts/sidecars/startup content/whole original hint.
}
