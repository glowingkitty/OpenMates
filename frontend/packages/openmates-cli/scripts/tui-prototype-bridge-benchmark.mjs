/** Measures actual private pipe round trips for prepared synthetic presentation snapshots. */
import {spawn} from 'node:child_process';
import {performance} from 'node:perf_hooks';
import fs from 'node:fs';
import path from 'node:path';
const args=process.argv.slice(2);const option=(name,fallback)=>args.includes(name)?args[args.indexOf(name)+1]:fallback;
const binary=path.resolve(option('--binary','frontend/packages/openmates-tui-prototype/target/release/openmates-tui-prototype'));
const fixtures=path.resolve(option('--fixtures','test-results/rust-tui/fixtures'));
const rows=[];
const stats=values=>{const s=[...values].sort((a,b)=>a-b);return{medianMs:+s[Math.floor(s.length/2)].toFixed(3),p95Ms:+s[Math.ceil(s.length*.95)-1].toFixed(3)};};
for(const count of [20,100,500])for(const width of [160,240]){
  const height=width===160?50:70;
  const snapshot=JSON.parse(fs.readFileSync(path.join(fixtures,`chat-${count}-${width}.json`),'utf8'));
  const started=performance.now();const child=spawn(binary,['--bridge-benchmark',String(width),String(height)],{stdio:['ignore','ignore','pipe','pipe','pipe']});
  let buffer='',waiting=null,error='';child.stderr.on('data',chunk=>{error+=chunk;});
  child.stdio[4].setEncoding('utf8');child.stdio[4].on('data',chunk=>{buffer+=chunk;let end;
    while((end=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,end);buffer=buffer.slice(end+1);const receipt=JSON.parse(line);waiting?.(receipt);waiting=null;}});
  child.on('error',error=>{throw error;});
  const send=()=>new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('Private pipe receipt timed out: '+error)),10000);
    const serialStart=performance.now();const payload=JSON.stringify(snapshot)+'\n';const serializedMs=performance.now()-serialStart;
    const sent=performance.now();waiting=receipt=>{clearTimeout(timer);if(receipt.epoch!==snapshot.epoch||receipt.scope!==snapshot.scope)reject(new Error('Stale prototype receipt'));
      else resolve({serializedMs,roundTripMs:performance.now()-sent,receipt,payloadBytes:Buffer.byteLength(payload)});};
    child.stdio[3].write(payload);
  });
  const first=await send();const startupToFirstFrameMs=performance.now()-started;
  const values=[],serial=[],native=[];let last;
  for(let i=0;i<20;i++){snapshot.epoch++;snapshot.state.draft=`synthetic draft ${i}`;last=await send();values.push(last.roundTripMs+last.serializedMs);serial.push(last.serializedMs);native.push(last.receipt.renderMicros/1000);}
  let rssKiB=null;try{rssKiB=Number(/^VmRSS:\s+(\d+)/m.exec(fs.readFileSync(`/proc/${child.pid}/status`,'utf8'))?.[1]);}catch{}
  child.stdio[3].end();await new Promise(resolve=>child.once('exit',resolve));
  rows.push({messages:count,viewport:`${width}x${height}`,startupToFirstFrameMs:+startupToFirstFrameMs.toFixed(3),
    preparedSnapshotToFrame:stats(values),jsonSerialization:stats(serial),nativeDraw:stats(native),payloadBytes:last.payloadBytes,nativeRssKiB:rssKiB,changedAnsiBytes:last.receipt.ansiBytes});
  process.stderr.write(JSON.stringify(rows.at(-1))+'\n');
}
const report={schemaVersion:1,measurement:'Prepared typed snapshot → JSON serialization → actual private pipes → Rust validation/projection/draw → acknowledgment. Excludes initial Markdown projection, Node startup, real terminal/SSH latency and input scheduling.',node:process.version,workloads:rows};
const output=option('--output',null);if(output)fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');else console.log(JSON.stringify(report,null,2));
