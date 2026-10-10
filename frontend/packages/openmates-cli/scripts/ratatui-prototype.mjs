/** Synthetic developer demo over private pipes. The installed CLI is unchanged. */
import {spawn} from 'node:child_process';
import {register} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
const pkg=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
register(pathToFileURL(path.join(pkg,'tests/loader.mjs')),import.meta.url);
const {currentPrototypeAction}=await import(pathToFileURL(path.join(pkg,'src/tuiPrototypeBridge.ts')));
const args=process.argv.slice(2);
const option=(key,fallback)=>args.includes(key)?args[args.indexOf(key)+1]:fallback;
const prototype=path.resolve(pkg,'../openmates-tui-prototype');
const binary=option('--binary',path.join(prototype,'target/release/openmates-tui-prototype'));
let current=JSON.parse(fs.readFileSync(option('--fixture',path.join(prototype,'fixtures/demo.json')),'utf8'));
if(!process.stdin.isTTY||!process.stderr.isTTY)throw new Error('Run the demo in an interactive terminal.');
const normalizeMessage=message=>({...message,embeds:Array.isArray(message.embeds)?message.embeds:[]});
current.state.messages=current.state.messages.map(normalizeMessage);
const scope=()=>['synthetic-demo','personal',current.state.selectedChatId,current.state.view].join(':');
current.scope=scope();
const initial=structuredClone(current);
const child=spawn(binary,['--bridge'],{stdio:['inherit','inherit','inherit','pipe','pipe'],
  env:Object.fromEntries(['PATH','TERM','COLORTERM','LANG','LC_ALL'].filter(name=>process.env[name]).map(name=>[name,process.env[name]]))});
let buffer='',blocked=false,pending=null;
const publish=()=>{
  if(child.exitCode!==null||child.killed||child.stdio[3].destroyed)return;
  const line=JSON.stringify(current)+'\n';
  if(Buffer.byteLength(line)>4*1024*1024)throw new Error('Demo frame exceeds 4 MiB.');
  if(blocked){pending=line;return;}
  blocked=!child.stdio[3].write(line);
};
child.stdio[3].on('drain',()=>{blocked=false;if(child.exitCode!==null||child.stdio[3].destroyed)return;if(pending){const line=pending;pending=null;blocked=!child.stdio[3].write(line);}});
child.stdio[3].on('error',error=>{if(error.code!=='EPIPE'){process.stderr.write(error.message+'\n');process.exitCode=1;}});
child.stdio[4].setEncoding('utf8');
child.stdio[4].on('data',chunk=>{
  buffer+=chunk;if(Buffer.byteLength(buffer)>4*1024*1024){child.kill();return;}
  let end;
  while((end=buffer.indexOf('\n'))>=0){
    const raw=buffer.slice(0,end);buffer=buffer.slice(end+1);let value;try{value=JSON.parse(raw);}catch{continue;}
    const action=currentPrototypeAction(value,current);if(!action)continue;
    switch(action.action){
      // Rust already owns the visible draft; keep the epoch stable while keys arrive in a burst.
      case 'draft_changed':current.state.draft=action.value;continue;
      case 'set_sidebar':current.state.sidebarOpen=action.open;break;
      case 'open_chat':current.state.selectedChatId=action.id;
        current.state.title=current.state.chats.find(chat=>chat.id===action.id).title;
        current.state.messages=action.id===initial.state.selectedChatId?structuredClone(initial.state.messages):[normalizeMessage({id:'demo-other',role:'assistant',content:'This second chat is synthetic. Authentication and encrypted sync remain in the existing client.'})];break;
      case 'open_workspace':current.state.view=action.id;current.state.workspaceRows=[{id:'demo-item',label:'Synthetic '+action.id,detail:'Renderer experiment'}];break;
      case 'send_message':current.state.messages.push(normalizeMessage({id:'demo-'+current.epoch,role:'user',content:action.value}));current.state.draft='';break;
      case 'back':current.state.view='chats';break;
      default:continue; // Embed/category interactions are local to the Rust presentation.
    }
    current.scope=scope();current.epoch++;publish();
  }
});
child.on('error',error=>{process.stderr.write(error.message+'\n');process.exitCode=1;});
child.on('exit',(code,signal)=>{process.exitCode=code??(signal?1:0);});
// Rust handles Ctrl+C while in raw mode; kill only when the parent is externally interrupted.
process.once('SIGTERM',()=>child.kill('SIGTERM'));
publish();
