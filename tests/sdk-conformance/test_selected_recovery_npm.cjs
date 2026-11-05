/** Pure source-extracted npm facade proof only; native is an inert double. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=process.env.OPENMATES_SELECTED_SDK_ROOT||path.resolve(__dirname,'../..');
const base=process.env.OPENMATES_SELECTED_SDK_BASE||root;
const ts=require(path.join(base,'frontend/packages/openmates-cli/node_modules/typescript'));
const source=path.join(root,'frontend/packages/openmates-cli/src/sdkEssential.ts');
const compiled=ts.transpileModule(fs.readFileSync(source,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}});
const output={exports:{}};
class SessionClientError extends Error{constructor(code,message){super(message);this.code=code;}}
vm.runInNewContext(compiled.outputText,{exports:output.exports,require:name=>{assert.equal(name,'./sdkSession.js');return{SessionClientError};},FinalizationRegistry});
(async()=>{
 const calls=[];let failure;
 const native={async completionRecoveryJobsForChat(chat){calls.push(chat);if(failure)throw failure;return JSON.stringify([{id:'opaque',job:{chat_id:chat}}]);}};
 const wrapper=new output.exports.SessionCompletionRecovery(native,async operation=>operation());
 const chat='22222222-2222-4222-8222-222222222222';
 assert.equal((await wrapper.jobsForChat(chat))[0].job.chat_id,chat);assert.deepEqual(calls,[chat]);
 failure=new SessionClientError('cancelled','synthetic cancellation');
 await assert.rejects(()=>wrapper.jobsForChat(chat),error=>error===failure);
 assert.deepEqual(calls,[chat,chat]);
 console.log('npm exact selected delegation + refusal identity PASS (pure native double only)');
})().catch(error=>{console.error(error);process.exitCode=1;});
// Actual selected-only store helpers with an inert POSIX recorder: no filesystem
// or native/network execution. This proves call order and refusal logic only.
function selectedWriter(options={}){
 const events=[],files=new Map(),handles=new Map();let next=2,nextInode=2;
 const parentNode={directory:true,ino:1,data:Buffer.alloc(0)};
 function stat(node){return{dev:1,ino:node.ino,uid:node.directory?(options.owner??123):123,mode:node.directory?0o40700:(0o100000|(options.fileMode??0o600)),nlink:1,size:node.directory?0:node.data.length,isDirectory:()=>!!node.directory,isFile:()=>!node.directory,isSymbolicLink:()=>false};}
 const io={constants:require('node:fs').constants,
  openSync(name,flags){if(name==='/owned'){handles.set(1,parentNode);return 1;}if(flags&this.constants.O_CREAT){assert.equal(files.has(name),false);files.set(name,{directory:false,ino:nextInode++,data:Buffer.alloc(0)});}assert.ok(files.has(name));const fd=next++;handles.set(fd,files.get(name));return fd;},
  fstatSync(fd){assert.ok(handles.has(fd));return stat(handles.get(fd));},
  lstatSync(name){return stat(name==='/owned'?parentNode:files.get(name));},
  writeFileSync(fd,raw){events.push('write');handles.get(fd).data=Buffer.from(raw);},
  fsyncSync(fd){assert.ok(handles.has(fd));events.push(handles.get(fd).directory?'parent-sync':'file-sync');},
  readSync(fd,buffer,offset,length,position){assert.ok(handles.has(fd));events.push('read');const value=handles.get(fd).data,bytes=options.corrupt?Buffer.alloc(value.length,88):value;const count=Math.min(length,Math.max(0,bytes.length-position));bytes.copy(buffer,offset,position,position+count);return count;},
  closeSync(fd){assert.ok(handles.has(fd));events.push('close-'+fd);handles.delete(fd);},
 };
 const source=fs.readFileSync(path.join(root,'tests/sdk-conformance/runners/selected-recovery.mjs'),'utf8');
 const body=source.slice(source.indexOf('// Selected-only durable fixture path:')).replace(/^export /gm,'');
 const helpers=vm.runInNewContext(body+';({writeSelected,readSelected,closeSelected})',{fs:io,path,assert,Buffer,process:{geteuid:()=>123}});
 return{...helpers,events,handles,replace(){const old=files.get('/owned/checkpoint');const pinned=[...handles.values()].includes(old);files.set('/owned/checkpoint',{directory:false,ino:pinned?nextInode++:old.ino,data:Buffer.from(old.data)});return files.get('/owned/checkpoint').ino;}};
}
{
 const writer=selectedWriter();const lease=writer.writeSelected('/owned','checkpoint',Buffer.from('exact'));
 assert.equal(writer.handles.size,2);assert.equal(writer.events.includes('close-2'),false);
 assert.deepEqual(writer.readSelected('/owned','checkpoint',Buffer.from('exact'),lease),Buffer.from('exact'));
 assert.ok(writer.events.indexOf('file-sync')<writer.events.indexOf('parent-sync'));
 assert.ok(writer.events.indexOf('parent-sync')<writer.events.indexOf('read'));
 assert.notEqual(writer.replace(),lease.physical.ino);
 assert.throws(()=>writer.readSelected('/owned','checkpoint',Buffer.from('exact'),lease));
 writer.closeSelected(lease);writer.closeSelected(lease);assert.equal(writer.handles.size,0);
 assert.throws(()=>writer.readSelected('/owned','checkpoint',Buffer.from('exact'),lease));
 assert.equal(writer.events.filter(value=>value==='close-2').length,1);
 assert.equal(writer.events.filter(value=>value==='close-1').length,1);
 for(const options of [{owner:999},{fileMode:0o644},{corrupt:true}]){
  const denied=selectedWriter(options);assert.throws(()=>denied.writeSelected('/owned','checkpoint',Buffer.from('exact')));
  if(!options.corrupt)assert.equal(denied.events.includes('parent-sync'),false);
  assert.equal(denied.handles.size,0);
 }
 console.log('npm selected live writer/parent FD, fsync/readback, replacement/closed-ABA refusal and exact close PASS (inert IO recorder)');
}
