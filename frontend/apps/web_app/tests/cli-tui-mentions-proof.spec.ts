/* eslint-disable @typescript-eslint/no-require-imports */
// contract-test-file: infrastructure
/** Product terminal and encrypted synthetic local catalog; no live API/inference latency claim. */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';
const {test,expect,captureProof,installRecorderDeps,requireIsolatedCliBuild,workflowApiUrl,createWorkflowCliHome}=require('./cli-tui-proof-helpers');
const {removeWorkflowCliHome}=require('./helpers/workflow-cli-e2e-helpers');
const path=require('node:path');
const profile='cli-terminal';
const contract={id:'cli-tui-composer-mentions',title:'Terminal composer suggestions',surface:'cli',devices:[profile],
 transcript:[
  {id:'defaults',text:'Typing @ opens source and available model suggestions above the composer without sending.',checkpoint:'defaults',devices:[profile]},
  {id:'skill',text:'Keyboard selection inserts an app skill while keeping the composer draft.',checkpoint:'skill-selected',devices:[profile]},
  {id:'contexts',text:'The same picker searches Projects, focus modes, Mates and saved memories.',checkpoint:'project',devices:[profile]},
  {id:'model',text:'A model suggestion updates the model selector and removes its routing token from the draft.',checkpoint:'model-selected',devices:[profile]},
 ],assertions:[
  {id:'tui.mentions.defaults',checkpoint:'defaults',visual:'The @ picker shows Wikipedia and available model shortcuts above the composer.',devices:[profile]},
  {id:'tui.mentions.skill',checkpoint:'skill-selected',visual:'The selected app skill appears as a usable composer token without sending.',devices:[profile]},
  {id:'tui.mentions.project',checkpoint:'project',visual:'The picker shows a matching decrypted Project context.',devices:[profile]},
  {id:'tui.mentions.model',checkpoint:'model-selected',visual:'The chosen model name appears on the model selector with the @ query removed.',devices:[profile]},
 ],tutorial:{readingWordsPerSecond:2.5,minimumHoldMs:1200,maximumHoldMs:5000}};
// eslint-disable-next-line no-empty-pattern
test('records @ suggestions, keyboard and click insertion, model selection and Esc draft preservation',async ({},testInfo:any)=>{
 test.setTimeout(150_000);const cli=requireIsolatedCliBuild();installRecorderDeps();
 const fixture=path.resolve(path.dirname(cli),'../tests/fixtures/tui-cache-startup-proof.mjs');
 const home=createWorkflowCliHome('composer-mentions');
 try{
  const steps:ProofStep[]=[
   {name:'landing',wait_for:'Cached conversation 0',hold_ms:300},
   {name:'composer',key:'Tab'},
   {name:'defaults',text:'@',wait_for:'@Best',hold_ms:500},
   {name:'skill-query',key:'ctrl+u'},
   {name:'skill',text:'Find @search',wait_for:'@Web-Search',hold_ms:400},
   {name:'skill-selected',key:'Return',wait_for:'Find @skill:web:search',wait_for_absent:'@ Suggestions',hold_ms:500},
   {name:'clear-project',key:'ctrl+u'},
   {name:'project',text:'@Synthetic',wait_for:'@Synthetic-Project',hold_ms:400},
   {name:'project-selected',click:{text:'@Synthetic-Project'},wait_for:'@project:22222222-2222-4222-8222-222222222222:read',hold_ms:250},
   {name:'clear-focus',key:'ctrl+u'},
   {name:'focus',text:'@research',wait_for:'Focus mode',hold_ms:250},
   {name:'focus-choice',click:{text:'@Web-Research'},wait_for:'@focus:web:research',hold_ms:250},
   {name:'clear-mate',key:'ctrl+u'},
   {name:'mate',text:'@Sophia',wait_for:'Mate',hold_ms:250},
   {name:'mate-selected',key:'Tab',wait_for:'@mate:software_development',hold_ms:250},
   {name:'clear-memory',key:'ctrl+u'},
   {name:'memory',text:'@preferences',wait_for:'Memories',hold_ms:250},
   {name:'dismiss-memory',key:'Escape',wait_for_absent:'@ Suggestions',wait_for:'@preferences',hold_ms:350},
   {name:'clear-wiki',key:'ctrl+u'},
   {name:'wiki',text:'@wiki:Comet',wait_for:'Synthetic Wikipedia suggestion',hold_ms:250},
   {name:'wiki-selected',key:'Return',wait_for:'@wikipedia:en:Comet',hold_ms:250},
   {name:'clear-model',key:'ctrl+u'},
   {name:'model',text:'@gpt',wait_for:'@GPT-6-Astra',hold_ms:250},
   {name:'model-selected',key:'Return',wait_for:'Model: GPT-6 Astra',wait_for_absent:'@ Suggestions',hold_ms:500},
   {name:'exit',key:'ctrl+c'},
  ];
  const recording=await captureProof(workflowApiUrl(),home,fixture,steps,contract,testInfo);
  const frame=(name:string)=>recording.frame(name).join('\n');
  expect(frame('defaults')).toContain('@Wiki');expect(frame('defaults')).toContain('@Fast');
  expect(frame('skill-selected')).not.toContain('Thinking…');expect(frame('skill-selected')).toContain('Continue where you left off');
  expect(frame('project-selected')).toContain('@project:22222222-2222-4222-8222-222222222222:read');
  expect(frame('focus-choice')).toContain('@focus:web:research');expect(frame('mate-selected')).toContain('@mate:software_development');
  expect(frame('memory')).toContain('Saved memory');expect(frame('dismiss-memory')).toContain('@preferences');
  expect(frame('wiki-selected')).toContain('@wikipedia:en:Comet');
  expect(frame('model-selected')).not.toContain('@gpt');expect(frame('model-selected')).not.toContain('@ai-model:');
  await recording.attest();
 }finally{removeWorkflowCliHome(home);}
});
