/** Direct public npm library worker; all scenario assertions live in the independent peer. */
// contract-test-file: tooling
const {RemoteHandshake}=await import('../../../frontend/packages/openmates-cli/dist/sdk-session-v1-entry.js');
const decode=value=>Buffer.from(value,'base64url'),encode=value=>Buffer.from(value).toString('base64url');
let pending,session,buffer=Buffer.alloc(0);
function invoke(item){
 const op=item.op;let value=null;
 if(op==='new'){pending?.close();session?.close();pending=undefined;session=undefined;pending=new RemoteHandshake(decode(item.key),item.identity,item.role);value=pending.handshake();}
 else if(op==='handshake')value=pending.handshake();
 else if(op==='finish')session=pending.finish(item.remote);
 else if(op==='seal')value=session.seal(item.id,decode(item.plaintext));
 else if(op==='open')value=encode(session.open(item.id,item.envelope));
 else if(op==='open_json_text')value=session.openJsonText(item.id,item.envelope);
 else if(op==='close_handshake')pending.close();
 else if(op==='close_session')session.close();
 else throw new Error('fixed worker operation');
 return {ok:true,value};
}
for await(const chunk of process.stdin){
 buffer=Buffer.concat([buffer,chunk]);if(buffer.length>1024*1024)process.exit(1);
 for(let index;(index=buffer.indexOf(10))>=0;){const line=buffer.subarray(0,index);buffer=buffer.subarray(index+1);let output,item;try{item=JSON.parse(line.toString('utf8'));output=invoke(item);}catch(error){output={ok:false,code:typeof error?.code==='string'?error.code:'protocol'};}output.sequence=item?.sequence??null;process.stdout.write(JSON.stringify(output)+'\n');}
}
if(buffer.length)process.exitCode=1;
pending?.close();session?.close();
