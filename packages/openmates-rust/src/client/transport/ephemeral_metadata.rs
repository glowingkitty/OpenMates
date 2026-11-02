//! Fixed-route native metadata transport. No caller frames/routes or host ABI.
use super::*;
use crate::client::ephemeral_metadata::MetadataSource;
use crate::client::plaintext::Plain;
use zeroize::Zeroizing;
pub(in crate::client) struct AuthenticatedMetadataPrincipal {pub principal:Zeroizing<String>,pub token:Zeroizing<String>}

/// Actual maintained POST /v1/auth/session, never cookie input/DTO admission.
/// Drain bounded original HTTP even after cancellation so real header rotations
/// are retained. No positive resource escapes a canceled/denied/malformed body.
pub(in crate::client) async fn authenticate(source:&MetadataSource,expected:Option<&str>,cancel:&CancellationToken)->Result<AuthenticatedMetadataPrincipal>{
    if cancel.is_cancelled(){return Err(Error::Cancelled)}
    source.check_expiry()?;
    let credentials=source.request_credentials()?;
    let cookies=Zeroizing::new(cookie_header(&credentials.cookies)?);
    let request=source.http.post(source.base.join("/v1/auth/session").map_err(|_|Error::Protocol)?)
        .header("X-OpenMates-SDK",source.identity.header()).header("Origin",&source.app)
        .header("Accept","application/json").header(COOKIE,cookies.as_str())
        .json(&json!({"session_id":credentials.session_id.as_str()})).timeout(Duration::from_secs(20));
    let response=tokio::time::timeout(Duration::from_secs(25),async {
        let mut response=request.send().await.map_err(|_|Error::Offline)?;
        source.apply_headers(response.headers())?;
        let status=response.status();
        if response.content_length().is_some_and(|n|n>MAX_BODY as u64){return Err(Error::Protocol)}
        let mut bytes=Zeroizing::new(Vec::new());
        while let Some(chunk)=response.chunk().await.map_err(|_|Error::Offline)?{
            if bytes.len().saturating_add(chunk.len())>MAX_BODY{return Err(Error::Protocol)}bytes.extend_from_slice(&chunk);
        }
        if matches!(status.as_u16(),401|403){return Err(Error::Expired)}
        if !status.is_success(){return Err(if status.is_redirection(){Error::Forbidden}else{Error::Offline})}
        let body=Plain::new(serde_json::from_slice::<Value>(&bytes).map_err(|_|Error::Protocol)?);
        if body.get("success")!=Some(&Value::Bool(true)){return Err(Error::Expired)}
        let user=body.get("user").filter(|u|u.is_object()).ok_or(Error::Protocol)?;
        let principal=user.get("id").and_then(Value::as_str).filter(|id|!id.is_empty())
            .or_else(||user.get("user_id").and_then(Value::as_str).filter(|id|!id.is_empty())).ok_or(Error::Protocol)?;
        if expected.is_some_and(|id|id!=principal){return Err(Error::Expired)}
        let token=required(&body,"ws_token")?;
        if token.is_empty(){return Err(Error::Protocol)}
        if cancel.is_cancelled(){return Err(Error::Cancelled)}
        source.check_expiry()?;
        Ok(AuthenticatedMetadataPrincipal{principal:Zeroizing::new(principal.to_owned()),token:Zeroizing::new(token.to_owned())})
    }).await.map_err(|_|Error::Offline)??;
    Ok(response)
}
pub(in crate::client) async fn initial_sync(source:&MetadataSource,token:&str,epoch:u64,lifetime:&CancellationToken,cancel:&CancellationToken)->Result<Plain<crate::client::sync::SyncPhaseReadData>>{
    let credentials=source.request_credentials()?;
    let mut url=source.base.join("/v1/ws").map_err(|_|Error::Protocol)?;
    url.set_scheme(if source.base.scheme()=="https"{"wss"}else{"ws"}).map_err(|_|Error::Protocol)?;
    url.query_pairs_mut().append_pair("client_capabilities","canonical_embed_receipts_v1,typed_recovery_outputs_v2,agentic-storage-v2")
        .append_pair("sessionId",&uuid::Uuid::new_v4().to_string()).append_pair("token",token);
    let mut request=url.as_str().into_client_request().map_err(|_|Error::Protocol)?;
    for (key,value) in [("User-Agent",USER_AGENT.to_owned()),("Cookie",cookie_header(&credentials.cookies)?),("X-OpenMates-SDK",source.identity.header().to_owned()),("Origin",source.app.clone())]{
        request.headers_mut().insert(tungstenite::http::HeaderName::from_bytes(key.as_bytes()).map_err(|_|Error::Protocol)?,value.parse().map_err(|_|Error::Protocol)?);
    }
    if lifetime.is_cancelled()||cancel.is_cancelled(){return Err(Error::Cancelled)}
    let config=WebSocketConfig::default().max_message_size(Some(MAX_BODY)).max_frame_size(Some(MAX_BODY));
    let (inner,_)=tokio::time::timeout(Duration::from_secs(10),crate::platform::socket::connect(request,Some(config),false)).await.map_err(|_|Error::Offline)?.map_err(|_|Error::Authentication)?;
    let mut socket=Socket::new(inner,None);
    let result=tokio::time::timeout(Duration::from_secs(30),async {
        if lifetime.is_cancelled()||cancel.is_cancelled(){return Err(Error::Cancelled)}
        send(&mut socket,"native_client_lifecycle",json!({"client_type":source.identity.header(),"is_foreground":false,"interactive":false})).await?;
        let mut budget=MAX_BODY;
        let mut read=crate::client::sync::ReadOnlySyncPhase::new(epoch)?;
        // Genuine server discovery terminal precedes the actual startup request.
        loop{let(kind,payload)=next(&mut socket,lifetime,cancel,&mut budget).await?;
            if kind=="recovery_outputs_discovery_complete"{read.accept(&kind,&payload,None)?;break;}}
        send(&mut socket,"phased_sync_request",json!({"phase":"all","context_epoch":epoch,"client_chat_versions":{},"client_chat_ids":[],"client_embed_ids":[]})).await?;
        let mut total=None;
        while !read.terminal_markers_received(){
            let(kind,payload)=next(&mut socket,lifetime,cancel,&mut budget).await?;
            read.accept(&kind,&payload,None)?;
            if kind=="phase_2_last_20_chats_ready"&&payload["context_epoch"].as_u64()==Some(epoch){total=payload["total_chat_count"].as_u64();}
        }
        if total.is_some_and(|count|count>100){
            send(&mut socket,"sync_metadata_chats",json!({"existing_chat_ids":[],"context_epoch":epoch})).await?;
            loop{let(kind,payload)=next(&mut socket,lifetime,cancel,&mut budget).await?;
                if kind=="sync_metadata_chats_response"&&payload["context_epoch"].as_u64()==Some(epoch){
                    if payload.get("team_id")!=Some(&Value::Null){return Err(Error::Forbidden)}
                    read.accept_post_startup_expanded_metadata(&payload,None)?;break;}}
        }
        if lifetime.is_cancelled()||cancel.is_cancelled(){return Err(Error::Cancelled)}read.finish()
    }).await.map_err(|_|Error::Offline).and_then(|r|r);
    // Close only this original socket; no global/durable/ACK settlement claim.
    let closed=tokio::time::timeout(Duration::from_secs(2),socket.close(None)).await;
    match result{Err(error)=>Err(error),Ok(data)=>{closed.map_err(|_|Error::Offline)?.map_err(|_|Error::Offline)?;if lifetime.is_cancelled()||cancel.is_cancelled(){Err(Error::Cancelled)}else{Ok(data)}}}
}
async fn next(socket:&mut Socket,lifetime:&CancellationToken,cancel:&CancellationToken,budget:&mut usize)->Result<(String,Plain<Value>)>{
    let (kind,payload)=tokio::select!{biased;_=lifetime.cancelled()=>return Err(Error::Cancelled),_=cancel.cancelled()=>return Err(Error::Cancelled),frame=receive_monitor(socket)=>frame?};
    let payload=Plain::new(payload);let bytes=Zeroizing::new(serde_json::to_vec(&*payload).map_err(|_|Error::Protocol)?).len();
    *budget=budget.checked_sub(bytes).ok_or(Error::Protocol)?;Ok((kind,payload))
}
