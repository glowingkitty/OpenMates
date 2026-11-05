/** Inert regression tests for the actual executable driver's pure guards.
 * Extract only named helper AST nodes; never import SDK or start a peer.
 * Rejection is observed before the simulated release await completes.
 * Fixture mutations must fail the same complete metadata comparator as CI.
 * Opaque cursor scope is structural/context evidence, never authorization.
 */
// contract-test-file: tooling
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {createRequire}=require('node:module');
const ts=createRequire(path.join(__dirname,'../../frontend/packages/openmates-cli/package.json'))('typescript');
const source=fs.readFileSync(path.join(__dirname,'runners/session-message-window.mjs'),'utf8');
const tree=ts.createSourceFile('driver.mjs',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);
const names=new Set(['settledOutcome','assertWindow']);
const functions=tree.statements.filter(n=>ts.isFunctionDeclaration(n)&&names.has(n.name?.text));
assert.equal(functions.length,2);
const context={assert,structuredClone};vm.createContext(context);
vm.runInContext(functions.map(n=>n.getText(tree).replace(/^export\s+/, '')).join('\n'),context);
const suite=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/session-message-window.json'))).capabilities['session.message-window.v1'];
const cursorFields=['startCursor','endCursor','oversizedMessageCursor'];
function wire(vector,scope='a'.repeat(64)){
 const value=structuredClone(vector.expected_public_paging);value.chat.messages=structuredClone(vector.expected_messages);
 for(const name of cursorFields)if(value[name]!==null)Object.assign(value[name],{chatId:suite.protocol.chat_id,scope});
 return value;
}
test('every successful vector is accepted with all literal public paging fields',()=>{
 for(const vector of suite.vectors.filter(v=>v.expected_error===null))context.assertWindow(suite,vector,wire(vector));
});
test('each public paging field plus nested identity/context/extra keys fails when changed',()=>{
 const vector=suite.vectors.find(v=>v.mode==='latest');
 for(const name of Object.keys(vector.expected_public_paging)){
  const bad=wire(vector);const value=bad[name];
  bad[name]=typeof value==='boolean'?!value:typeof value==='number'?value+1:typeof value==='string'?value+'injected':{unexpected:true};
  assert.throws(()=>context.assertWindow(suite,vector,bad),name);
 }
 for(const [name,value] of [['chatId','99999999-9999-4999-8999-999999999999'],['scope','SECRET'],['createdAt',0],['messageId','99999999-9999-4999-8999-999999999999']]){
  const bad=wire(vector);bad.startCursor[name]=value;assert.throws(()=>context.assertWindow(suite,vector,bad),name);
 }
 for(const target of ['root','chat','cursor']){const bad=wire(vector);(target==='root'?bad:target==='chat'?bad.chat:bad.startCursor).extra='arbitrary';assert.throws(()=>context.assertWindow(suite,vector,bad));}
 const bad=wire(vector);bad.endCursor.scope='b'.repeat(64);assert.throws(()=>context.assertWindow(suite,vector,bad));
 assert.throws(()=>context.assertWindow(suite,vector,wire(vector),'b'.repeat(64)));
});
test('pending cancellation rejection is already observed before release completes',async()=>{
 const unhandled=[];const listener=e=>unhandled.push(e);process.on('unhandledRejection',listener);
 try{
  const rejection=new Error('closed cancelled fixture');
  const pending=context.settledOutcome(Promise.reject(rejection));
  // Simulates awaited status/cancel/release-control work before pending is read.
  await new Promise(r=>setImmediate(r));
  assert.deepEqual(unhandled,[]);assert.equal((await pending).error,rejection);
  assert.match(source,/const pending=settledOutcome\(client\.chatMessageWindow\(id,options\)\)/);
 }finally{process.off('unhandledRejection',listener);}
});
