import assert from 'node:assert/strict';
export async function startupSync({first,secondClient,replaceCredentials,vector,endpoint,get,wait,refused}){
 const monitor=await first.watchChats();let operation,metadata;
 try{
  if(vector.mode==='startup_foreign_monitor'){
   const foreign=await secondClient();
   try{assert.throws(()=>foreign.native.initialSyncOpen(monitor.id),error=>JSON.parse(error.message).code==='cancelled');}finally{await foreign.close();}
   const status=await get(endpoint,'/__test/status');assert.equal(status.startup_requests,0);assert.equal(status.metadata_requests,0);
   return;
  }
  operation=await monitor.beginInitialSync();
  if(vector.mode==='startup_cancel_before'){operation.cancel();await refused(()=>operation.run(),['cancelled']);}
  else if(vector.mode==='startup_stale'){await replaceCredentials();await refused(()=>operation.run(),['cancelled']);}
  else{
   const pending=operation.run();pending.catch(()=>{});
   if(['startup_cancel_inflight','startup_foreign_context'].includes(vector.mode)){
    await wait(endpoint,status=>status.metadata_requests===1);
    if(vector.mode==='startup_foreign_context'){
     await wait(endpoint,status=>status.checks.includes('foreign-context-offered'));
     let settled=false;pending.finally(()=>{settled=true;}).catch(()=>{});
     await new Promise(resolve=>setTimeout(resolve,30));assert.equal(settled,false);
    }
    operation.cancel();await refused(()=>pending,['cancelled']);
   }else if(vector.mode==='startup_server_error'){await refused(()=>pending,['offline']);}
   else{
    metadata=await pending;assert.equal(await metadata.receivedMetadataCount(),vector.expected_count);
    await refused(()=>operation.run(),['conflict']);
    if(vector.mode==='startup_repeat'){
     const duplicate=await monitor.beginInitialSync();try{await refused(()=>duplicate.run(),['conflict','cancelled']);}finally{duplicate.cancel();}
    }else{await monitor.close();await refused(()=>metadata.receivedMetadataCount(),['cancelled']);}
   }
  }
  const status=await get(endpoint,'/__test/status');assert.equal(status.failure,null);assert.equal(status.unexpected_frames,0);
  assert.equal(status.startup_requests,['startup_cancel_before','startup_stale'].includes(vector.mode)?0:1);
  assert.equal(status.metadata_requests,vector.total_chat_count>100&&!['startup_cancel_before','startup_stale'].includes(vector.mode)?1:0);
 }finally{metadata?.cancel();operation?.cancel();await monitor.close();}
}
