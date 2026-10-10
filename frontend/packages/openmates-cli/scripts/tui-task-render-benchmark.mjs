/**
 * Synthetic 500-task board rendering benchmark.
 * Same workloads can run against a retained before source snapshot.
 * Measures synchronous cold, draft, scroll and selection frame construction.
 * Reports ten warm samples with median and p95.
 * No accounts, disk cache, network, decryption or inference are exercised.
 */
import {performance} from 'node:perf_hooks';
import {register} from 'node:module';
import {pathToFileURL,fileURLToPath} from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
register(pathToFileURL(path.join(root,'tests/loader.mjs')),import.meta.url);
const args=process.argv.slice(2),option=(name,fallback)=>args.includes(name)?args[args.indexOf(name)+1]:fallback;
const source=path.resolve(option('--source',path.join(root,'src')));
const {createInitialTuiState,renderTuiFrame}=await import(pathToFileURL(path.join(source,'tuiRenderer.ts')));
const status=['backlog','todo','in_progress','blocked','done'];
const tasks=Array.from({length:500},(_,index)=>({taskId:`task-${index}`,shortId:`TASK-${index}`,slug:'',
  title:`Synthetic task ${index} review the result`,description:'Synthetic',labels:['review'],tags:[],
  status:status[index%5],position:index,linkedProjectIds:[],assigneeType:'user',assigneeIdentity:null,assigneeHash:null,
  queueState:'none',dueAt:null,priority:0}));
const summarize=values=>{const sorted=[...values].sort((a,b)=>a-b);return {medianMs:+sorted[5].toFixed(3),p95Ms:+sorted[9].toFixed(3)};};
const workloads=[];
for(const [width,height] of [[80,24],[160,50],[240,70]]){
  const state=createInitialTuiState();Object.assign(state,{workspace:'tasks',screen:'tasks',focus:'content',tasks});
  let start=performance.now();renderTuiFrame(state,width,height,{colorMode:'truecolor'});const coldMs=performance.now()-start;
  const draft=[],scroll=[],selection=[];
  for(let i=0;i<3;i++)renderTuiFrame(state,width,height,{colorMode:'truecolor'});
  for(let i=0;i<10;i++){
    state.input=`draft ${i}`;start=performance.now();renderTuiFrame(state,width,height,{colorMode:'truecolor'});draft.push(performance.now()-start);
    state.followSelection=false;state.scrollOffset=100+i*3;start=performance.now();renderTuiFrame(state,width,height,{colorMode:'truecolor'});scroll.push(performance.now()-start);
    state.selectedIndex=470+i;state.followSelection=true;start=performance.now();renderTuiFrame(state,width,height,{colorMode:'truecolor'});selection.push(performance.now()-start);
  }
  const row={tasks:500,viewport:`${width}x${height}`,coldMs:+coldMs.toFixed(3),draft:summarize(draft),scroll:summarize(scroll),selection:summarize(selection)};
  workloads.push(row);process.stderr.write(JSON.stringify(row)+'\n');
}
const report={schemaVersion:1,source,node:process.version,arch:process.arch,
  measurement:'Synchronous synthetic board construction; excludes sync, decryption, real terminal latency and input scheduling.',workloads};
const output=option('--output',null);
if(output){fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');}
else console.log(JSON.stringify(report,null,2));
