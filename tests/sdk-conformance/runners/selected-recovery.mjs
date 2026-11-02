/** Authored actual npm facade calls; execution belongs to isolated CI. */
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
const {existsSync}=fs;
import path from 'node:path';
export async function selectedRecovery({first,suite,vector,endpoint,directory,get,wait,refused,hash}){
 const owned=[];
 try{
 const recovery=first.completionRecovery,chat=vector.chat_id;
 await refused(()=>recovery.jobsForChat(chat),['unavailable']);
 await recovery.enable(true);
 const journal=path.join(directory,'unrelated-journal');
 const preserved=Buffer.from('synthetic opaque encrypted unrelated checkpoint\n','utf8');
 const journalFile=writeSelected(directory,'unrelated-journal',preserved);owned.push(journalFile);
 if(vector.mode==='selected_partial_failure'){
  await refused(()=>recovery.jobsForChat(chat),['protocol']);
 }else if(vector.mode==='selected_cancel'){
  const pending=recovery.jobsForChat(chat);pending.catch(()=>{});
  await wait(endpoint,status=>status.selected_discovery_waiting>=1);
  first.cancel();await refused(()=>pending,['cancelled']);
 }else{
  const jobs=await recovery.jobsForChat(chat);
  assert.ok(jobs.every(entry=>entry.job.chat_id===chat));
  assert.ok(jobs.every(entry=>Object.keys(entry).sort().join(',')==='id,job'));
  if(['selected_empty','selected_pending'].includes(vector.mode))assert.equal(jobs.length,0);
  else{
   assert.equal(jobs.length,1);
   // A second selection must not discard the first selection's opaque handle.
   const other=await recovery.jobsForChat(vector.unrelated_chat_id);
   assert.equal(other.length,1);assert.equal(other[0].job.chat_id,vector.unrelated_chat_id);
   const stage=await recovery.stage(jobs[0].id);assert.equal(stage.kind,'ready');
   const checkpoint=Buffer.from(stage.checkpoint_json,'utf8');const checkpointFile=writeSelected(directory,'checkpoint',checkpoint);owned.push(checkpointFile);
   assert.equal((await get(endpoint,'/__test/status')).persists,0);
   const receipt=await recovery.commit(stage.id,{checkpoint_sha256:hash(readSelected(directory,'checkpoint',checkpoint,checkpointFile))});
   assert.equal(receipt.state,'TERMINAL');assert.equal(receipt.assistant_message_id,suite.protocol.assistant_id);
  }
 }
 assert.deepEqual(readSelected(directory,'unrelated-journal',preserved,journalFile),preserved);
 if(vector.mode!=='selected_main')assert.equal(existsSync(path.join(directory,'checkpoint')),false);
 const status=await get(endpoint,'/__test/status');
 assert.equal(status.failure,null);assert.equal(status.admissions,0);
 assert.equal(status.claims,vector.mode==='selected_main'?1:0);
 assert.ok(status.checks.includes('selected-startup-without-phased-sync'));
 // The peer rejects every phased request and unrelated claim in selected modes.
 }finally{let closeError;for(const entry of owned.reverse()){try{closeSelected(entry);}catch(error){closeError??=error;}}if(closeError)throw closeError;}

}

// Selected-only durable fixture path: no claim of fsync from file close alone.
function sameFile(a,b){assert.equal(a.dev,b.dev);assert.equal(a.ino,b.ino);}
function parent(directory){
 assert.equal(typeof process.geteuid,'function','Unix fixture ownership required');
 const fd=fs.openSync(directory,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);
 try{const stat=fs.fstatSync(fd),named=fs.lstatSync(directory);
  assert.ok(stat.isDirectory()&&!named.isSymbolicLink());sameFile(stat,named);
  assert.equal(stat.uid,process.geteuid());assert.equal(stat.mode&0o7777,0o700);
  return{fd,stat};
 }catch(error){fs.closeSync(fd);throw error;}
}
function currentParent(directory,owned){const now=fs.lstatSync(directory);assert.ok(now.isDirectory()&&!now.isSymbolicLink());sameFile(now,owned.stat);assert.equal(now.uid,owned.stat.uid);assert.equal(now.mode&0o7777,0o700);}
function fileMeta(directory,name,fd,owned,expected){
 assert.ok(name==='checkpoint'||name==='unrelated-journal');
 const stat=fs.fstatSync(fd),named=fs.lstatSync(path.join(directory,name));
 assert.ok(stat.isFile()&&!named.isSymbolicLink());sameFile(stat,named);
 assert.equal(stat.uid,named.uid);assert.equal(stat.mode,named.mode);assert.equal(stat.nlink,named.nlink);assert.equal(stat.size,named.size);
 assert.equal(stat.uid,owned.stat.uid);assert.equal(stat.mode&0o7777,0o600);assert.equal(stat.nlink,1);
 assert.equal(stat.size,expected);currentParent(directory,owned);return stat;
}
export function readSelected(directory,name,expected,lease){
 assert.ok(!lease.closed&&lease.directory===directory&&lease.name===name);
 const {fd,owned,physical}=lease;
 const before=fileMeta(directory,name,fd,owned,expected.length);sameFile(before,physical);
 // Positional reads use the ACTUAL still-open writer descriptor. Its inode
 // cannot be recycled while held, even if an outside writer unlinks the name.
 const bytes=Buffer.alloc(expected.length);let position=0;
 while(position<bytes.length){const count=fs.readSync(fd,bytes,position,bytes.length-position,position);assert.ok(count>0);position+=count;}
 const extra=Buffer.alloc(1);assert.equal(fs.readSync(fd,extra,0,1,expected.length),0);
 sameFile(before,fileMeta(directory,name,fd,owned,expected.length));
 assert.deepEqual(bytes,Buffer.from(expected));return bytes;
}
export function closeSelected(lease){
 if(lease.closed)return;lease.closed=true;
 try{fs.closeSync(lease.fd);}finally{fs.closeSync(lease.owned.fd);}
}
export function writeSelected(directory,name,raw){
 const owned=parent(directory);let fd,lease;
 try{assert.ok(name==='checkpoint'||name==='unrelated-journal');
  fd=fs.openSync(path.join(directory,name),fs.constants.O_RDWR|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);
  fileMeta(directory,name,fd,owned,0);fs.writeFileSync(fd,raw);fileMeta(directory,name,fd,owned,raw.length);
  fs.fsyncSync(fd);fs.fsyncSync(owned.fd);
  lease={directory,name,fd,owned,physical:fileMeta(directory,name,fd,owned,raw.length),closed:false};
  readSelected(directory,name,raw,lease);return lease;
 }catch(error){if(lease){closeSelected(lease);}else{try{if(fd!==undefined)fs.closeSync(fd);}finally{fs.closeSync(owned.fd);}}throw error;}
}
