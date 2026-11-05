/** Offline closed decoder proposal. Reads only the actual runner's pure helper
 * block; never imports/executes its SDK adapter or a protected checker. */
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
const BEGIN='// BEGIN CLOSED GENERATED SKILLS DIAGNOSTIC\n';
const END='// END CLOSED GENERATED SKILLS DIAGNOSTIC';
export const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
export function extractGeneratedDiagnostic(source){
  const start=source.indexOf(BEGIN),end=source.indexOf(END);
  if(start<0||end<=start||source.indexOf(BEGIN,start+1)!==-1||source.indexOf(END,end+1)!==-1)throw Error('closed_helper_boundary');
  const block=source.slice(start+BEGIN.length,end);
  return vm.runInNewContext(block+'\n({stages:GENERATED_DIAGNOSTIC_STAGES,vectors:GENERATED_DIAGNOSTIC_VECTORS,preAdmission:GENERATED_DIAGNOSTIC_PRE_ADMISSION,suiteOnly:GENERATED_DIAGNOSTIC_SUITE_ONLY,errors:GENERATED_DIAGNOSTIC_ERRORS,generic:GENERATED_DIAGNOSTIC_GENERIC,classify:generatedDiagnosticError,line:generatedDiagnosticLine})',Object.create(null),{timeout:200});
}
export function generatedDigestCatalog(source){
  const helper=extractGeneratedDiagnostic(source),entries=new Map();
  for(const stage of helper.stages)for(const vector of (helper.suiteOnly.includes(stage)?['none']:helper.vectors))for(const error of helper.errors){
    const bytes=Buffer.from(helper.generic+helper.line(stage,vector,error));
    if(bytes.length>512)throw Error('closed_diagnostic_bound');
    const key=`${bytes.length}:${digest(bytes)}`;
    if(entries.has(key))throw Error('closed_diagnostic_collision');
    entries.set(key,{stage,vector,error});
  }
  return {helper,entries};
}
export function decodeGeneratedDigest(source,byteCount,sha256){
  if(!Number.isSafeInteger(byteCount)||byteCount<0||typeof sha256!=='string'||!/^[0-9a-f]{64}$/.test(sha256))throw Error('closed_digest_identity');
  const {helper,entries}=generatedDigestCatalog(source),match=entries.get(`${byteCount}:${sha256}`);
  if(match)return {status:'matched',...match,attribution:match.vector==='none'?'suite-only':'admitted-vector'};
  const generic=Buffer.from(helper.generic);
  if(byteCount===generic.length&&sha256===digest(generic))return {status:'generic-only',stage:'unclassified',vector:'none',error:'unclassified',attribution:'suite-only'};
  return {status:'unmatched'};
}
function main(){
  const args=process.argv.slice(2),names=['--runner','--runner-sha256','--stderr-bytes','--stderr-sha256'];
  if(args.length!==8||!names.every((name,index)=>args[index*2]===name))throw Error('closed_arguments');
  const bytes=readFileSync(args[1]);if(!/^[0-9a-f]{64}$/.test(args[3])||digest(bytes)!==args[3])throw Error('closed_runner_identity');
  const result=decodeGeneratedDigest(bytes.toString('utf8'),Number(args[5]),args[7]);
  process.stdout.write(JSON.stringify({runnerSha256:args[3],...result})+'\n');
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try{main();}catch{process.stderr.write('generated_skills_decoder_refused\n');process.exitCode=1;}
}
