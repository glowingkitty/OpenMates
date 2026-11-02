/** Offline Apps-only finite decoder. Never imports the executable SDK runner. */
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import vm from 'node:vm';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const BEGIN='// BEGIN CLOSED APPS DIAGNOSTIC\n',END='// END CLOSED APPS DIAGNOSTIC';
export const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
export function extractAppsDiagnostic(source){
 const start=source.indexOf(BEGIN),end=source.indexOf(END);
 if(start<0||end<=start||source.indexOf(BEGIN,start+1)!==-1||source.indexOf(END,end+1)!==-1)throw Error('apps_closed_boundary');
 return vm.runInNewContext(source.slice(start+BEGIN.length,end)+'\n({stages:APPS_DIAGNOSTIC_STAGES,vectors:APPS_DIAGNOSTIC_VECTORS,errors:APPS_DIAGNOSTIC_ERRORS,suiteStages:APPS_DIAGNOSTIC_SUITE_STAGES,generic:APPS_DIAGNOSTIC_GENERIC,classify:appsDiagnosticError,line:appsDiagnosticLine,capture:captureAppsFailure,stage(value){appsStage=value;},vector(value){appsVector=value;},failure(){return appsFailure;}})',Object.create(null),{timeout:200});
}
export function appsDigestCatalog(source){
 const helper=extractAppsDiagnostic(source),entries=new Map();
 for(const stage of helper.stages)for(const vector of (helper.suiteStages.includes(stage)?['none']:['none',...helper.vectors]))for(const error of helper.errors)for(const envelope of ['adapter','checker']){
  const prefix=envelope==='checker'?'Library conformance failed sdk.apps/npm (returncode=1, signal=none): ':'';
  const bytes=Buffer.from(prefix+helper.generic+helper.line(stage,vector,error)+(envelope==='checker'?'\n':''));
  if(bytes.length>512)throw Error('apps_closed_bound');
  const key=`${bytes.length}:${digest(bytes)}`;if(entries.has(key))throw Error('apps_closed_collision');
  entries.set(key,{stage,vector,error,envelope});
 }
 return {helper,entries};
}
export function decodeAppsDigest(source,byteCount,sha256){
 if(!Number.isSafeInteger(byteCount)||byteCount<0||typeof sha256!=='string'||!/^[a-f0-9]{64}$/.test(sha256))throw Error('apps_digest_identity');
 const match=appsDigestCatalog(source).entries.get(`${byteCount}:${sha256}`);
 return match?{status:'matched',...match,attribution:match.vector==='none'?'suite-only':'admitted-vector'}:{status:'unmatched'};
}
function main(){
 const args=process.argv.slice(2),names=['--runner','--runner-sha256','--stderr-bytes','--stderr-sha256'];
 if(args.length!==8||!names.every((name,i)=>args[i*2]===name))throw Error('apps_arguments');
 const bytes=readFileSync(args[1]);if(!/^[a-f0-9]{64}$/.test(args[3])||digest(bytes)!==args[3])throw Error('apps_source_identity');
 process.stdout.write(JSON.stringify({runnerSha256:args[3],...decodeAppsDigest(bytes.toString('utf8'),Number(args[5]),args[7])})+'\n');
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){try{main();}catch{process.stderr.write('apps_decoder_refused\n');process.exitCode=1;}}
