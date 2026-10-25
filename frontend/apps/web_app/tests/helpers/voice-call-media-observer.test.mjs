// contract-test-file: tooling
// Execute the spec-owned callbacks; no browser, provider or product transport.
import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { webcrypto } from 'node:crypto';
const require = createRequire(new URL('../../../../packages/ui/package.json', import.meta.url));
const ts = require('typescript');
const source = fs.readFileSync(new URL('../voice-call.spec.ts', import.meta.url), 'utf8');
const ast = ts.createSourceFile('voice-call.spec.ts', source, ts.ScriptTarget.Latest, true);
const callbacks = [];
function visit(node) {
  if (ts.isCallExpression(node) && node.expression.getText(ast).endsWith('.addInitScript') && node.arguments[0]) {
    callbacks.push(node.arguments[0].getText(ast));
  }
  ts.forEachChild(node, visit);
}
visit(ast);
const callback = marker => callbacks.find(text => text.includes(marker));
function install(context, marker) {
  const text = callback(marker); assert.ok(text, marker);
  vm.runInContext(ts.transpileModule(`(${text})();`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context);
}
function fixture() {
  const context = vm.createContext({ crypto: webcrypto, queueMicrotask, setTimeout, clearTimeout,
    atob: value => Buffer.from(value, 'base64').toString('binary'), performance,
  });
  vm.runInContext(`
    globalThis.window = globalThis; globalThis.location = {href:'https://app.example.invalid/'};
    let nextUrl = 0;
    globalThis.URL = class {
      constructor(value, base) { this.pathname = new globalThis.NativeURL(value, base).pathname; }
      static createObjectURL() { return 'blob:' + (++nextUrl); }
    };
    class SourceBuffer { appendBuffer() {} }
    class MediaSource { addSourceBuffer() { return new SourceBuffer(); } }
    class HTMLMediaElement {
      constructor() { this.src=''; this.currentTime=0; this.paused=false; this.ended=false; this.listeners=[]; }
      addEventListener(type, fn, options) { this.listeners.push({type,fn,capture:options?.capture===true}); }
      emit(type) { for(const item of [...this.listeners].filter(item=>item.type===type).sort((a,b)=>Number(b.capture)-Number(a.capture))) item.fn(); }
      play() { return Promise.resolve(); }
    }
    class HTMLAudioElement extends HTMLMediaElement {}
    class WebSocket {
      constructor() { this.listeners=[]; }
      addEventListener(type, fn) { if(type==='message') this.listeners.push(fn); }
      async receive(data) { for(const fn of this.listeners) { fn({data}); await Promise.resolve(); } }
    }
    Object.assign(globalThis,{SourceBuffer,MediaSource,HTMLMediaElement,HTMLAudioElement,WebSocket});
    globalThis.semanticSegment = 'manual-a';
    globalThis.document = {querySelector:()=>({getAttribute:()=>semanticSegment})};
  `, Object.assign(context, { NativeURL: URL }));
  return context;
}
const settle = () => new Promise(resolve => setTimeout(resolve, 20));

test('exact native-listener payload provenance survives a microtask checkpoint and retained early chunks', async () => {
  const context = fixture(); install(context, '__voiceSpeechMediaSources: sources');
  await vm.runInContext(`(async()=>{
    globalThis.socket = new window.WebSocket('https://app.example.invalid/v1/ws');
    let retained;
    socket.addEventListener('message', event => { const frame=JSON.parse(event.data); if(frame.payload.phase==='chunk') retained=frame.payload; });
    const identity={chat_id:'chat',voice_call_id:'call',message_id:'message',segment_id:'segment',attempt_id:'attempt',source_version:1,execution_version:1,sequence:0,kind:'voice_prose_turn'};
    await socket.receive(JSON.stringify({type:'assistant_speech_audio',payload:{...identity,phase:'start',chunk_index:0}}));
    await socket.receive(JSON.stringify({type:'assistant_speech_audio',payload:{...identity,phase:'chunk',chunk_index:0,audio_data:'AQID'}}));
    await Promise.resolve();
    globalThis.media=new MediaSource(); globalThis.sourceUrl=URL.createObjectURL(media); globalThis.buffer=media.addSourceBuffer();
    const raw=atob(retained.audio_data); buffer.appendBuffer(Uint8Array.from(raw,character=>character.charCodeAt(0)));
  })()`, context);
  await settle();
  assert.equal(vm.runInContext('__voiceSpeechMediaSources.get(sourceUrl)', context), 'segment', JSON.stringify(vm.runInContext('globalThis.__voiceSpeechMediaProof',context)));
  vm.runInContext('buffer.appendBuffer(new Uint8Array([1,2,3]))', context);
  await settle();
  assert.equal(vm.runInContext('__voiceSpeechMediaSources.has(sourceUrl)', context), false, 'unproven appended bytes invalidate binding');
});

test('manual replay binds native generations in both epochs and never follows a later unrelated label', async () => {
  const context = fixture(); install(context, '__voiceManualSpeechPlayback:state');
  vm.runInContext(`globalThis.__voiceSpeechMediaSources=new Map();
    globalThis.__voiceCallEvidence={received:[{type:'assistant_speech_status',speechStatus:'ready',segmentId:'manual-a',generatedAssetId:'asset-a'}]};
    globalThis.audio=new HTMLAudioElement(); audio.src='blob:stored-a'; __voiceManualSpeechPlayback.epoch=1;`, context);
  await vm.runInContext('audio.play()', context); await Promise.resolve();
  vm.runInContext("semanticSegment='unrelated'; audio.currentTime=1; audio.emit('timeupdate')", context);
  assert.equal(vm.runInContext('__voiceManualSpeechPlayback.progress[0]?.segmentId', context), 'manual-a');
  vm.runInContext("semanticSegment='manual-a'; __voiceManualSpeechPlayback.epoch=2; audio.currentTime=0", context);
  await vm.runInContext('audio.play()', context); await Promise.resolve();
  vm.runInContext("semanticSegment='unrelated'; audio.currentTime=1; audio.emit('timeupdate')", context);
  assert.equal(vm.runInContext('__voiceManualSpeechPlayback.progress.some(item=>item.epoch===2&&item.segmentId==="manual-a")', context), true);
  vm.runInContext("audio.addEventListener('ended',()=>{audio.src='blob:next'});audio.ended=true;audio.emit('ended');audio.ended=false",context);
  assert.equal(vm.runInContext('__voiceManualSpeechPlayback.ended[0]?.trackId',context),'manual-a','capture observes the ended generation before queue source replacement');
  vm.runInContext("audio.src='blob:unrelated'; semanticSegment='unrelated'; audio.currentTime=0",context);
  await vm.runInContext('audio.play()',context);await Promise.resolve();
  vm.runInContext("semanticSegment='manual-a'; audio.currentTime=2; audio.emit('timeupdate')",context);
  assert.equal(vm.runInContext('__voiceManualSpeechPlayback.progress.length',context),2,'a later label cannot bind an unrelated source');

});

test('identical received chunks retain distinct segment ownership and mixed ownership fails closed', async () => {
  const context=fixture(); install(context,'__voiceSpeechMediaSources: sources');
  await vm.runInContext(`(async()=>{
    const socket=new window.WebSocket('https://app.example.invalid/v1/ws'),retained=[];
    socket.addEventListener('message',event=>{const frame=JSON.parse(event.data);if(frame.payload.phase==='chunk')retained.push(frame.payload);});
    for(const segment_id of ['first','second']) {
      const identity={chat_id:'chat',voice_call_id:'call',message_id:'message',segment_id,attempt_id:'attempt',source_version:1,execution_version:1,sequence:0,kind:'voice_prose_turn'};
      await socket.receive(JSON.stringify({type:'assistant_speech_audio',payload:{...identity,phase:'start',chunk_index:0}}));
      await socket.receive(JSON.stringify({type:'assistant_speech_audio',payload:{...identity,phase:'chunk',chunk_index:0,audio_data:'AQID'}}));
    }
    globalThis.retained=retained;globalThis.buffers=[];globalThis.sourceUrls=[];
    for(const payload of retained){const media=new MediaSource();sourceUrls.push(URL.createObjectURL(media));const buffer=media.addSourceBuffer();buffers.push(buffer);
      const raw=atob(payload.audio_data);buffer.appendBuffer(Uint8Array.from(raw,c=>c.charCodeAt(0)));}
  })()`,context);
  await settle();
  assert.equal(vm.runInContext('__voiceSpeechMediaSources.get(sourceUrls[0])',context),'first');
  assert.equal(vm.runInContext('__voiceSpeechMediaSources.get(sourceUrls[1])',context),'second');
  vm.runInContext('const raw=atob(retained[1].audio_data);buffers[0].appendBuffer(Uint8Array.from(raw,c=>c.charCodeAt(0)))',context);
  await settle();
  assert.equal(vm.runInContext('__voiceSpeechMediaSources.has(sourceUrls[0])',context),false);
  vm.runInContext('const original=atob(retained[1].audio_data);const changed=Uint8Array.from(original,c=>c.charCodeAt(0));changed[0]=9;buffers[1].appendBuffer(changed)',context);
  await settle();
  assert.equal(vm.runInContext('__voiceSpeechMediaSources.has(sourceUrls[1])',context),false,'changed append bytes fail SHA provenance');
});
