//! Explicit selected latest-page local-first policy on the original owned B.
//! The existing native cursor adapter supplies readonly transaction results.
//! Native absence is data; cancellation, corruption and IO errors never become
//! misses. No Client borrow spans native IO or opaque master-key operations.
use super::*;
use crate::client::local_cached_read::{checkpoint_presentation,wire};

const PACKET:usize=256*1024;
const RECEIPT_RESERVE:usize=2048;
pub(super) struct LocalSelected {pub(super) retained:RetainedData,pub(super) checkpoints:Plain<Vec<Value>>}

fn plan(ctx:&Context,operation:&str,kind:&str,limit:usize,lower:Option<i64>,bytes:usize)->Plain<Value>{
    Plain::new(json!({"version":1,"kind":kind,"operationId":operation,"owner":ctx.owner,
        "chatId":ctx.chat,"maxPacketBytes":bytes,"maxCheckpointRows":if kind=="owned_metadata"{128}else{0},
        "maxPayloadRows":limit,"lower":lower.map(|created_at|json!({"createdAt":created_at,"messageId":null,"open":true})),
        "upper":null,"direction":if kind=="messages"{"prev"}else{"next"}}))
}
fn exact(value:&Value,fields:&[&str])->bool{
    value.as_object().is_some_and(|o|o.len()==fields.len()&&fields.iter().all(|field|o.contains_key(*field)))
}
fn version(value:&Value)->Result<u64>{value.as_u64().filter(|v|(1..=MAX_SAFE).contains(v)).ok_or(Error::Protocol)}
async fn read(channel:&Channel,plan:&Value)->Result<Plain<Value>>{
    channel.context.negative()?;
    let encoded=Zeroizing::new(serde_json::to_string(plan)?);local_json::validate(&encoded)?;
    let response=Zeroizing::new(channel.io(encoded.to_string()).await?);
    channel.context.negative()?;
    let limit=plan["maxPacketBytes"].as_u64().ok_or(Error::Protocol)? as usize;
    if response.len()>limit{return Err(Error::Protocol)}
    let value=Plain::new(serde_json::from_str::<Value>(&response)?);
    if value["version"]!=1||value["operationId"]!=plan["operationId"]||value["kind"]!=plan["kind"]{return Err(Error::Protocol)}
    version(&value["databaseVersion"])?;Ok(value)
}
fn metadata_frame(frame:&Value,ctx:&Context)->Result<bool>{
    if !exact(frame,&["version","kind","operationId","databaseVersion","chat_metadata","messages","wrappers","boundary","compression_checkpoints"])
        ||frame["messages"]!=json!([])||frame["wrappers"]!=json!([])||!frame["boundary"].is_null(){return Err(Error::Protocol)}
    let checkpoints=frame["compression_checkpoints"].as_array().ok_or(Error::Protocol)?;
    if checkpoints.len()>128{return Err(Error::Protocol)}
    wire::compression_timestamp(checkpoints,&ctx.chat)?;
    let row=&frame["chat_metadata"];
    if row.is_null(){if !checkpoints.is_empty(){return Err(Error::Conflict)}return Ok(false)}
    if !row.is_object()||row["chat_id"].as_str()!=Some(ctx.chat.as_str())
        ||row["id"].as_str()!=Some(ctx.chat.as_str())
        ||row.get("user_id").filter(|v|!v.is_null()).is_some_and(|v|v.as_str()!=Some(ctx.owner.as_str())){return Err(Error::Forbidden)}
    for field in ["team_id","hashed_team_id"]{if row.get(field).is_some_and(|v|!v.is_null()&&v.as_str()!=Some("")){return Err(Error::Forbidden)}}
    if row.get("chat_visibility").filter(|v|!v.is_null()).is_some_and(|v|!matches!(v.as_str(),Some(""|"personal"))){return Err(Error::Forbidden)}
    for field in super::super::super::CIPHERS.iter().copied().chain(["encrypted_chat_key"]){
        if row.get(field).filter(|v|!v.is_null()).is_some_and(|v|!v.is_string()){return Err(Error::Protocol)}
    }
    for field in ["title_v","metadata_v","messages_v","created_at","updated_at","last_edited_overall_timestamp","key_version"]{
        if let Some(value)=row.get(field).filter(|v|!v.is_null()){safe_number(value)?;}
    }
    if text(row,"encrypted_chat_key").is_empty(){
        // Existing cold persistence cannot recover a preexisting keyless header
        // in this subset. Preserve that typed gap; never fetch around it.
        if row["is_metadata_only"]==true{return Err(unsupported("KEYLESS_PARTIAL_LOCAL_FIRST_REQUIRES_OWNED_KEY_RECOVERY"))}
        return Err(Error::Crypto)
    }
    let _closed=normalized(row,&ctx.chat,&ctx.owner,true)?;Ok(true)
}
fn message_rows(frame:&Value,ctx:&Context,limit:usize,lower:Option<i64>,database:u64)->Result<Plain<Vec<Value>>>{
    if !exact(frame,&["version","kind","operationId","databaseVersion","messages","nextKey","rangeExhausted"])
        ||version(&frame["databaseVersion"])?!=database{return Err(Error::Conflict)}
    let exhausted=frame["rangeExhausted"].as_bool().ok_or(Error::Protocol)?;
    let next=if frame["nextKey"].is_null(){None}else{
        let next=&frame["nextKey"];
        if !exact(next,&["createdAt","messageId"]){return Err(Error::Protocol)}
        let at=next["createdAt"].as_i64().filter(|v|*v>=0&&(*v as u64)<=MAX_SAFE).ok_or(Error::Protocol)?;
        let id=required(next,"messageId")?;wire::storage_id(id)?;Some((at,id))
    };
    if exhausted!=next.is_none(){return Err(Error::Protocol)}
    let raw=frame["messages"].as_array().ok_or(Error::Protocol)?;
    if raw.len()>limit||next.is_some()&&raw.len()!=limit{return Err(Error::Protocol)}
    let mut rows=Plain::new(raw.clone());rows.reverse();
    // The maintained physical aliases/order/row and ciphertext packet guards.
    let normalized=Plain::new(wire::message_rows(&rows,&ctx.chat)?);
    if normalized.iter().any(|row|wire::position(row).is_err()||lower.is_some_and(|lower|row["created_at"].as_i64().is_none_or(|at|at<=lower))){return Err(Error::Protocol)}
    if let Some(next)=next{
        if lower.is_some_and(|lower|next.0<=lower)||!wire::position_cmp(next,wire::position(normalized.first().ok_or(Error::Protocol)?)?).is_lt(){return Err(Error::Protocol)}
    }
    Ok(rows)
}
pub(super) async fn drive(channel:Channel,host:BrowserMetadataCacheScope,now:u64)->Result<Outcome>{
    let ctx=channel.context.clone();ctx.negative()?;
    let operation=uuid::Uuid::new_v4().to_string();
    let metadata_plan=plan(&ctx,&operation,"owned_metadata",0,None,PACKET);
    let metadata=read(&channel,&metadata_plan).await?;
    if !metadata_frame(&metadata,&ctx)?{
        if ctx.profile_cache.is_some(){profile_absence::record(&ctx,metadata,None,host)?;return Err(Error::Offline)}
        return super::drive(channel,host,now).await.map(Outcome::Selected)
    }
    let database=version(&metadata["databaseVersion"])?;
    let checkpoints=Plain::new(metadata["compression_checkpoints"].as_array().ok_or(Error::Protocol)?.clone());
    let timestamp=wire::compression_timestamp(&checkpoints,&ctx.chat)?;
    let lower=if ctx.options.respect_compression_boundary{timestamp}else{None};
    let bytes=crate::client::monitor::cached_view::bounded_bytes(&*metadata,PACKET).ok_or(Error::Protocol)?;
    let available=PACKET.checked_sub(bytes).and_then(|n|n.checked_sub(RECEIPT_RESERVE)).filter(|n|*n>=1024).ok_or(Error::Protocol)?;
    let rows_plan=plan(&ctx,&operation,"messages",ctx.options.limit,lower,available);
    let frame=read(&channel,&rows_plan).await?;
    let rows=message_rows(&frame,&ctx,ctx.options.limit,lower,database)?;
    // Revalidate the original native physical source, not just version fields,
    // before either local publication or absence-based HTTP fallback.
    let metadata_again=read(&channel,&metadata_plan).await?;
    if *metadata_again!=*metadata{return Err(Error::Conflict)}
    let frame_again=read(&channel,&rows_plan).await?;
    if *frame_again!=*frame{return Err(Error::Conflict)}
    let key=channel.validate_metadata(normalized(&metadata["chat_metadata"],&ctx.chat,&ctx.owner,true)?).await?;
    if rows.is_empty()&&checkpoints.is_empty()&&(metadata["chat_metadata"]["is_metadata_only"]==true||metadata["chat_metadata"]["messages_v"].as_u64().is_some_and(|v|v>0)){
        if ctx.profile_cache.is_some(){profile_absence::record(&ctx,metadata,Some(frame),host)?;return Err(Error::Offline)}
        return super::drive(channel,host,now).await.map(Outcome::Selected)
    }
    let dispositions=Plain::new(rows.iter().map(|row|Ok(json!({"messageId":wire::position(row)?.1,"disposition":"retained_local","incomingSuppliedWriteFieldsMatch":false}))).collect::<Result<Vec<_>>>()?);
    let retained=RetainedData{plan:rows_plan,readback:Plain::new(json!({"metadata":metadata["chat_metadata"],"rows":&*rows})),
        dispositions,summary:Zeroizing::new(String::new()),key};
    ctx.negative()?;Ok(Outcome::LocalSelected(LocalSelected{retained,checkpoints}))
}
pub(super) fn add_checkpoint(ctx:&Context,output:&mut Plain<Value>,checkpoints:&[Value],key:&Key)->Result<()>{
    let mut presentation=checkpoint_presentation::project(checkpoints,&ctx.chat,key,None,||ctx.negative())?;
    output["checkpointPresentation"]=serde_json::to_value(&presentation)?;
    if crate::client::monitor::cached_view::bounded_bytes(&**output,checkpoint_presentation::MAX_PRESENTATION_FRAME_BYTES).is_none(){
        presentation.omit_summary();output["checkpointPresentation"]=serde_json::to_value(&presentation)?;
    }
    if crate::client::monitor::cached_view::bounded_bytes(&**output,PACKET).is_none(){return Err(Error::Protocol)}
    ctx.negative()
}
