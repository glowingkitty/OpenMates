/* eslint-disable @typescript-eslint/no-require-imports */
// contract-test-file: infrastructure
/** Real terminal loop with a synthetic SDK stream; no API or inference timing claim. */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';
const {test,expect,captureProof,installRecorderDeps,requireIsolatedCliBuild,workflowApiUrl,createWorkflowCliHome}=require('./cli-tui-proof-helpers');
const {removeWorkflowCliHome}=require('./helpers/workflow-cli-e2e-helpers');
const path=require('node:path');
const profile='cli-terminal';
const contract={id:'cli-tui-synthetic-stream-real-terminal',title:'Synthetic response in the real terminal TUI',surface:'cli',devices:[profile],
  transcript:[
    {id:'thinking',text:'A deterministic SDK stream exercises immediate user message rendering and transient centered Thinking.',checkpoint:'thinking-animation',devices:[profile]},
    {id:'writing',text:'The bottom inside rainbow remains animated while ordered paragraphs appear.',checkpoint:'writing-animation',devices:[profile]},
    {id:'complete',text:'Completion removes the transient indicator and retains one user and one assistant response.',checkpoint:'complete',devices:[profile]},
  ],assertions:[
    {id:'tui.synthetic.optimistic-send',checkpoint:'thinking-animation',visual:'The sent user row appears above centered Thinking and an empty composer.',devices:[profile]},
    {id:'tui.synthetic.streaming-glow',checkpoint:'writing-animation',visual:'The response and its animated rainbow sit above the composer.',devices:[profile]},
    {id:'tui.synthetic.completed',checkpoint:'complete',visual:'The completed response has no Thinking or active rainbow.',devices:[profile]},
  ],tutorial:{readingWordsPerSecond:2.5,minimumHoldMs:1200,maximumHoldMs:5000}};
// eslint-disable-next-line no-empty-pattern
test('records optimistic send, centered Thinking and bounded rainbow animation in the real TUI loop',async ({},testInfo:any)=>{
  test.setTimeout(150_000);
  const cli=requireIsolatedCliBuild();installRecorderDeps();
  const fixture=path.resolve(path.dirname(cli),'../tests/fixtures/tui-streaming-proof.mjs');
  const home=createWorkflowCliHome('synthetic-streaming-proof');
  try {
    const steps:ProofStep[]=[
      {name:'landing',wait_for:'DAILY INSPIRATION',hold_ms:250},
      {name:'draft',text:'Synthetic streaming request'},
      {name:'thinking',key:'Return',wait_for:'Thinking…',hold_ms:550},
      {name:'thinking-animation',wait_for:'Thinking…',hold_ms:650},
      {name:'reasoning',wait_for:'Thinking for this response',hold_ms:150},
      {name:'reasoning-open',click:{text:'Thinking for this response'},wait_for:'Synthetic visible reasoning for this response.',hold_ms:150},
      {name:'researching',wait_for:'✦ Researching…',hold_ms:450},
      {name:'researching-animation',wait_for:'✦ Researching…',hold_ms:450},
      {name:'streaming-mentions',text:'@search',wait_for:'@Web-Search',hold_ms:300},
      {name:'streaming-mentions-animation',wait_for:'@Web-Search',hold_ms:700},
      {name:'streaming-mentions-dismiss',key:'Escape',wait_for_absent:'@ Suggestions',wait_for:'@search',hold_ms:100},
      {name:'streaming-mentions-clear',key:'ctrl+u'},
      {name:'working-skills',wait_for:'✦ Working…',hold_ms:450},
      {name:'writing',wait_for:'First paragraph',hold_ms:500},
      {name:'writing-animation',wait_for:'First paragraph',hold_ms:600},
      {name:'complete',wait_for:'Complete response.',wait_for_absent:'Thinking…',hold_ms:400},
      {name:'exit-command',text:'/exit'}, {name:'exit',key:'Return'},
    ];
    const recording=await captureProof(workflowApiUrl(),home,fixture,steps,contract,testInfo);
    const frame=(name:string)=>recording.frame(name).join('\n');
    const thinking=frame('thinking');
    expect(thinking.split('Synthetic streaming request')).toHaveLength(2);
    expect(thinking).toContain('Sophia');expect(thinking).toContain('Synthetic model');
    expect(thinking).toContain('Ask a follow-up');expect(thinking).toContain('▁');
    const row=recording.frame('thinking').find((value:string)=>value.includes('Thinking…'));
    expect(row.indexOf('Thinking…')).toBeGreaterThan(row.indexOf('Sophia')+10);
    // A timer paint recolors only the already laid-out glow, even without tokens.
    expect(recording.segment('thinking-animation','thinking')).toContain('▁');
    expect(frame('thinking-animation')).toBe(thinking);
    expect(frame('reasoning-open')).toContain('Synthetic visible reasoning for this response.');
    expect(frame('researching')).toContain('✦ Researching…');
    expect(recording.segment('researching-animation','researching')).toContain('▁');
    expect(frame('streaming-mentions-animation')).toContain('@ Suggestions');
    expect(frame('streaming-mentions-animation')).toContain('@Web-Search');
    expect(frame('streaming-mentions-dismiss')).toContain('@search');
    expect(frame('working-skills')).toContain('✦ Working…');
    const writing=frame('writing');
    expect(writing).toContain('First paragraph');expect(writing).not.toContain('**First paragraph**');
    expect(writing).not.toContain('Thinking…');expect(writing).toContain('✦ Working…');
    expect(writing.indexOf('▁')).toBeGreaterThan(writing.indexOf('First paragraph'));
    expect(writing.indexOf('▁')).toBeLessThan(writing.indexOf('Ask a follow-up'));
    expect(recording.segment('writing-animation','writing')).toContain('▁');
    const completed=frame('complete');
    expect(completed).toContain('First paragraph');expect(completed).toContain('Second paragraph');
    expect(completed).toContain('Complete response.');expect(completed).not.toContain('▁');
    expect(completed).not.toContain('Thinking…');
    expect(completed.split('Synthetic streaming request')).toHaveLength(2);
    expect(completed.split('Sophia')).toHaveLength(2);
    expect(completed.split('Thinking for this response')).toHaveLength(2);
    await recording.attest();
  } finally {removeWorkflowCliHome(home);}
});


const cachedStartupContract={id:'cli-tui-encrypted-cache-startup',title:'Encrypted cache navigation in the terminal',surface:'cli',devices:[profile],
 transcript:[
  {id:'home',text:'The chat workspace shows recent previews from an encrypted synthetic local cache while sync is unavailable.',checkpoint:'landing',devices:[profile]},
  {id:'chat',text:'The selected chat opens its recent decrypted messages and preserves a new composer draft.',checkpoint:'draft',devices:[profile]},
  {id:'history',text:'Older cached messages remain reachable and the newest response can be reopened after returning to the workspace.',checkpoint:'reopen',devices:[profile]},
 ],assertions:[
  {id:'tui.cache.synthetic.home',checkpoint:'landing',visual:'Recent cached chat cards are visible while sync is unavailable.',devices:[profile]},
  {id:'tui.cache.synthetic.open',checkpoint:'draft',visual:'The newest cached message is visible above the new composer draft.',devices:[profile]},
  {id:'tui.cache.synthetic.history',checkpoint:'reopen',visual:'Returning to the workspace and reopening preserves the cached transcript and draft.',devices:[profile]},
 ],tutorial:{readingWordsPerSecond:2.5,minimumHoldMs:1200,maximumHoldMs:5000}};
// eslint-disable-next-line no-empty-pattern
test('records encrypted cached startup, full history, draft preservation and repeated opening',async ({},testInfo:any)=>{
 test.setTimeout(150_000);const cli=requireIsolatedCliBuild();installRecorderDeps();
 const fixture=path.resolve(path.dirname(cli),'../tests/fixtures/tui-cache-startup-proof.mjs');
 const home=createWorkflowCliHome('encrypted-cache-startup');
 try{
  const steps:ProofStep[]=[
   {name:'landing',wait_for:'Cached conversation 0',hold_ms:400},
   {name:'open',key:'Return',wait_for:'Cached message 239.',hold_ms:400},
   {name:'draft',text:'Keep this draft',wait_for:'Keep this draft',hold_ms:350},
   {name:'oldest',key:'Home',wait_for:'Cached message 0.',hold_ms:350},
   {name:'newest',key:'End',wait_for:'Cached message 239.',hold_ms:350},
   {name:'back',key:'Escape',wait_for:'Continue where you left off',wait_for_absent:'Cached message 239.',hold_ms:350},
   {name:'older-card-1',key:'Right',repeat:15},{name:'older-card-2',key:'Right',repeat:15},{name:'older-card-3',key:'Right',repeat:15},
   {name:'warm-selection',wait_for:'Cached conversation 45',hold_ms:250},
   {name:'refresh-command',text:'/refresh'},
   {name:'warm-refresh',key:'Return',wait_for:'Sync failed',hold_ms:350},
   {name:'reopen-command',text:'/chat 11111111-1111-4111-8111-111111111111'},
   {name:'reopen',key:'Return',wait_for:'Cached message 239.',hold_ms:700},
   {name:'exit',key:'ctrl+c'},
  ];
  const recording=await captureProof(workflowApiUrl(),home,fixture,steps,cachedStartupContract,testInfo);
  const frame=(name:string)=>recording.frame(name).join('\n');
  expect(frame('landing')).toContain('Continue where you left off');expect(frame('landing')).not.toContain('Loading your recent chats');
  expect(frame('draft')).toContain('Cached message 239.');expect(frame('draft')).toContain('Keep this draft');
  expect(frame('oldest')).toContain('Cached message 0.');expect(frame('oldest')).toContain('Keep this draft');
  expect(frame('newest')).toContain('Cached message 239.');expect(frame('warm-refresh')).toContain('Cached conversation 45');expect(frame('reopen')).toContain('Keep this draft');
  expect(frame('reopen')).toContain('Cached conversation 0');await recording.attest();
 }finally{removeWorkflowCliHome(home);}
});
