/** Trusted test-build transport. Opens the official runner's own manual page;
 * never exposes an application API or treats mocked output as execution proof. */
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {performance} from 'node:perf_hooks';
import {fileURLToPath} from 'node:url';
const MAX_OUTPUT=256*1024;
function requireValue(value){if(!value)throw Error('worker_transport_refused');}
export function parseWorkerOutput(text,required){
 requireValue(typeof text==='string' && Buffer.byteLength(text)<=MAX_OUTPUT && Array.isArray(required) && required.length>=8 && required.length<=64 && new Set(required).size===required.length);
 const rows=text.replace(/\r/g,'').split('\n');
 const results=rows.flatMap(line=>{const m=/^test ([A-Za-z0-9_:]{1,240}) \.\.\. (ok|FAILED|ignored)$/.exec(line);return m?[{name:m[1],status:m[2]}]:[];});
 requireValue(results.length===required.length && results.every(r=>r.status==='ok') && new Set(results.map(r=>r.name)).size===required.length && required.every(name=>results.some(r=>r.name===name)));
 const summaries=rows.flatMap(line=>{const m=/^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) filtered out(?:; finished in [0-9.]+s)?$/.exec(line);return m?[m.slice(1).map(Number)]:[];});
 requireValue(summaries.length===1 && summaries[0][0]===required.length && summaries[0].slice(1).every(n=>n===0));
 requireValue(!rows.some(line=>/^test result: (?:FAILED|ignored)/.test(line)));
 return {passed:required.length,failed:0,ignored:0,filteredOut:0};
}
function heldFile(filename,max){
 requireValue(fs.realpathSync(filename)===filename);
 const fd=fs.openSync(filename,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);try{
  const before=fs.fstatSync(fd);requireValue(before.isFile() && before.uid===process.getuid() && !(before.mode&0o022) && before.nlink===1 && before.size>0 && before.size<=max);
  const hash=createHash('sha256'),buf=Buffer.alloc(128*1024);let n,total=0;
  while((n=fs.readSync(fd,buf,0,buf.length,null))>0){hash.update(buf.subarray(0,n));total+=n;requireValue(total<=max);}
  const after=fs.fstatSync(fd),now=fs.lstatSync(filename);for(const key of ['dev','ino','size','mode','uid','gid','nlink','mtimeMs','ctimeMs'])requireValue(before[key]===after[key]&&before[key]===now[key]);
  return hash.digest('hex');
 }finally{fs.closeSync(fd);}
}
async function bounded(promise,ms){
 let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('worker_cleanup_bound')),ms);})]);}finally{clearTimeout(timer);}
}
async function waitExit(server,getExit,ms){
 if(getExit())return;
 let listener;try{await bounded(new Promise(resolve=>{listener=resolve;server.once('exit',listener);}),ms);}finally{server.off('exit',listener);}
}
export async function cleanupOwned(browser,server,getExit,waitMs=5000,browserServer){
 let failed=false;
 try{if(browserServer)await bounded(browserServer.close(),waitMs);else if(browser)await bounded(browser.close(),waitMs);}catch{failed=true;}
 if(browserServer){
  const owned=browserServer.process();
  if(owned.exitCode===null&&owned.signalCode===null){failed=true;try{await bounded(browserServer.kill(),waitMs);}catch{}}
  if(owned.exitCode===null&&owned.signalCode===null)failed=true;
 }
 if(server&&!getExit()){
  try{server.kill('SIGTERM');await waitExit(server,getExit,waitMs);}catch{failed=true;}
 }
 if(server&&!getExit()){
  try{server.kill('SIGKILL');await waitExit(server,getExit,Math.min(waitMs,3000));}catch{failed=true;}
  failed=true;
 }
 return !failed&&(!server||(getExit()?.code===null&&getExit()?.signal==='SIGTERM'));
}
export async function run(){
 const root=fs.realpathSync(process.cwd()),folder=path.join(root,'.ci-worker');
 const request=JSON.parse(fs.readFileSync(path.join(folder,'request.json'),'utf8'));
 requireValue(Object.keys(request).sort().join(',')==='browserVersion,requiredTests,runnerSha256,testWasmSha256,timeoutMs');
 requireValue(Number.isInteger(request.timeoutMs)&&request.timeoutMs>0&&request.timeoutMs<=300000);
 const deadline=performance.now()+request.timeoutMs;
 const left=()=>{const n=deadline-performance.now();requireValue(n>0);return Math.ceil(n);};
 const wasm=path.join(folder,'tests.wasm'),runner=path.join(root,'.ci-bindgen/bin/wasm-bindgen-test-runner');
 requireValue(heldFile(wasm,128*1024**2)===request.testWasmSha256 && heldFile(runner,64*1024**2)===request.runnerSha256);
 const require=createRequire(import.meta.url),{chromium}=require(path.join(folder,'playwright/package'));
 const executable=chromium.executablePath();requireValue(path.isAbsolute(executable)&&executable.startsWith(path.join(folder,'browsers')+path.sep));
 const browserHash=heldFile(executable,512*1024**2);
 const env={...process.env,NO_HEADLESS:'1',WASM_BINDGEN_TEST_ADDRESS:'127.0.0.1:0'};
 // The parent supplies a fresh allowlisted environment; reject escape switches.
 for(const key of ['NODE_OPTIONS','NODE_PATH','WASM_BINDGEN_USE_NODE','WASM_BINDGEN_TEST_ONLY_NODE','WASM_BINDGEN_TEST_ONLY_WEB','GECKODRIVER_REMOTE','CHROMEDRIVER_REMOTE'])requireValue(!env[key]);
 let server,browser,browserServer,interrupted=false,serverExit,output='',workerContexts=[],pageErrors=[];
 const interrupt=()=>{interrupted=true;void browserServer?.kill().catch(()=>{});if(!browserServer)void browser?.close().catch(()=>{});server?.kill('SIGTERM');};
 process.on('SIGINT',interrupt);process.on('SIGTERM',interrupt);
 let outcome,primary;
 try{
  server=spawn(runner,[wasm],{cwd:root,env,stdio:['ignore','pipe','pipe'],detached:false});
  server.once('exit',(code,signal)=>{serverExit={code,signal};});
  server.once('error',()=>{interrupted=true;});
  const collect=chunk=>{output+=chunk.toString('utf8');if(Buffer.byteLength(output)>MAX_OUTPUT){interrupted=true;server.kill('SIGTERM');}};
  server.stdout.on('data',collect);server.stderr.on('data',collect);
  let url;
  while(!url){
   requireValue(!interrupted&&!serverExit);left();
   const matches=[...output.matchAll(/^Interactive browsers tests are now available at (http:\/\/127\.0\.0\.1:([1-9][0-9]{0,4}))\s*$/gm)];
   if(matches.length){requireValue(matches.length===1&&Number(matches[0][2])<=65535);url=matches[0][1];break;}
   await new Promise(resolve=>setTimeout(resolve,25));
  }
  browserServer=await chromium.launchServer({headless:true,executablePath:executable,host:'127.0.0.1',port:0,timeout:left()});
  const endpoint=new URL(browserServer.wsEndpoint());requireValue(endpoint.protocol==='ws:'&&endpoint.hostname==='127.0.0.1'&&Number(endpoint.port)>0);
  browser=await chromium.connect(browserServer.wsEndpoint(),{timeout:left()});
  requireValue(browser.version()===request.browserVersion);
  const context=await browser.newContext({serviceWorkers:'block'});
  await context.route('**/*',route=>new URL(route.request().url()).origin===url?route.continue():route.abort());
  const page=await context.newPage();
  page.on('pageerror',()=>pageErrors.push(true));
  page.on('worker',worker=>{workerContexts.push((async()=>worker.url()===url+'/worker.js'&&await worker.evaluate(()=>typeof DedicatedWorkerGlobalScope!=='undefined'&&self instanceof DedicatedWorkerGlobalScope))());});
  await page.goto(url,{waitUntil:'load',timeout:left()});
  await page.waitForFunction(limit=>{const t=document.getElementById('output')?.textContent||'';if(new TextEncoder().encode(t).length>limit)throw Error('worker_output_bound');return /test result: /.test(t);},MAX_OUTPUT,{timeout:left()});
  const text=await page.locator('#output').textContent({timeout:left()});
  requireValue(!interrupted&&!serverExit&&pageErrors.length===0&&workerContexts.length===1&&(await Promise.all(workerContexts)).every(Boolean));
  const counts=parseWorkerOutput(text,request.requiredTests);
  requireValue(heldFile(wasm,128*1024**2)===request.testWasmSha256&&heldFile(runner,64*1024**2)===request.runnerSha256&&heldFile(executable,512*1024**2)===browserHash);
  outcome={...counts,browserBinarySha256:browserHash};
  await context.close();
  // Manual mode is documented to stay alive after results. Its signal exit is
  // cleanup evidence only; actual success came from the compiled Rust output.
 }catch(error){primary=error;}
 finally{
  if(!await cleanupOwned(browser,server,()=>serverExit,5000,browserServer))primary ||= Error('worker_cleanup');
  process.off('SIGINT',interrupt);process.off('SIGTERM',interrupt);
 }
 requireValue(!primary&&!interrupted&&serverExit?.code===null&&serverExit?.signal==='SIGTERM');
 return {...outcome,context:'dedicated-worker',cleanup:{browserClosed:true,serverStopped:true,serverExitCode:null,serverExitSignal:'SIGTERM'}};
}
if(process.argv[1]&&fileURLToPath(import.meta.url)===path.resolve(process.argv[1])){
 run().then(value=>process.stdout.write(JSON.stringify(value)+'\n')).catch(()=>{process.stderr.write('worker_transport_failed\n');process.exitCode=1;});
}
