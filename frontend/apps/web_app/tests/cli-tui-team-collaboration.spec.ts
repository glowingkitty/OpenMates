/* eslint-disable @typescript-eslint/no-require-imports -- CLI E2E helpers expose CommonJS exports. */
/** Isolated two-member Team conversation through the real graphical terminal. */
export {};
import type { Browser, BrowserContext, Page, TestInfo } from '@playwright/test';
const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { createWorkflowCliHome, removeWorkflowCliHome, workflowCliEnv, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');
const { recordInteractiveCli, requireIsolatedCliBuild, installRecorderDeps } = require('./cli-tui-proof-helpers');
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const ROOT=path.resolve(__dirname,'../../../..');
const PACKAGE=path.join(ROOT,'frontend/packages/openmates-cli');
const CLI=path.join(PACKAGE,'dist/cli.js');
const SDK=path.join(PACKAGE,'dist/index.js');

function sdk<T>(apiUrl:string,home:string,program:string,input:unknown={}):T {
  const source=`const {pathToFileURL}=require('node:url');
    (async()=>{const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
      const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
      const input=JSON.parse(process.argv[2]);${program}
    })().catch(error=>{console.error(error.message);process.exit(1)});`;
  return JSON.parse(execFileSync('node',['-e',source,SDK,JSON.stringify(input)],{
    cwd:ROOT,env:workflowCliEnv(apiUrl,home),encoding:'utf8',timeout:90_000,
  }).trim()) as T;
}

type MemberTiming = {readyAt:number;checkpointAt:number;ownerReadyAt:number;sendStartedAt:number;sendFinishedAt:number;ownerSeen:boolean};

function startMemberReply(apiUrl:string,home:string,input:Record<string,unknown>):{
  ready:Promise<void>;completion:Promise<MemberTiming>;stop:()=>void;
} {
  const source=`const {pathToFileURL}=require('node:url');
    const fs=require('node:fs');let phase='prepare',readyAt=0,checkpointAt=0,ownerReadyAt=0,sendStartedAt=0,sendFinishedAt=0;
    let windowReads=0,windowMessages=0,serverMessageCount=null;
    (async()=>{const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
      const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
      const input=JSON.parse(process.argv[2]);
      const initial=await client.getChatMessages(input.chatId,{teamId:input.teamId});
      if(!initial.messages.some(message=>message.content===input.first))throw Error('Initial Team message missing');
      readyAt=Date.now();process.stdout.write(JSON.stringify({stage:'ready',readyAt})+'\\n');
      phase='checkpoint';const deadline=Date.now()+75_000;
      while(!fs.existsSync(input.transcriptPath)||!fs.readFileSync(input.transcriptPath,'utf8').includes(input.marker)){
        if(Date.now()>deadline)throw Error('Inbound checkpoint missing');
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      checkpointAt=Date.now();phase='owner-ready';
      // The recorder can show optimistic owner text before its encrypted send
      // has committed. Require the other member to decrypt it before replying.
      const ownerDeadline=Date.now()+20_000;let ownerSeen=false;
      while(Date.now()<ownerDeadline){
        const window=await client.getChatMessagesWindow(input.chatId,{teamId:input.teamId,direction:'latest',limit:100,respectCompressionBoundary:false,preferCache:true});
        windowReads++;windowMessages=window.messages.length;serverMessageCount=window.serverMessageCount;
        ownerSeen=window.messages.some(message=>message.content===input.ownerText);
        if(ownerSeen)break;
        await new Promise(resolve=>setTimeout(resolve,250));
      }
      if(!ownerSeen)throw Error('Owner TUI message missing before member reply');
      ownerReadyAt=Date.now();phase='send';sendStartedAt=Date.now();
      await client.sendMessage({chatId:input.chatId,message:input.memberText,piiDetection:false});
      sendFinishedAt=Date.now();phase='verify';
      const chat=await client.getChatMessagesWindow(input.chatId,{teamId:input.teamId,direction:'latest',limit:100,respectCompressionBoundary:false,preferCache:true});
      windowReads++;windowMessages=chat.messages.length;serverMessageCount=chat.serverMessageCount;
      ownerSeen=chat.messages.some(message=>message.content===input.ownerText);
      if(!ownerSeen)throw Error('Owner TUI message missing after member reply');
      process.stdout.write(JSON.stringify({stage:'done',readyAt,checkpointAt,ownerReadyAt,sendStartedAt,sendFinishedAt,ownerSeen})+'\\n');
    })().catch(error=>{
      const status=String(error.message||'').match(/HTTP (\\d{3})/);
      const reason=String(error.message||'');
      const kind=reason.startsWith('Owner TUI message missing')?'owner-not-decrypted'
        :reason.includes('Chat key unavailable')?'chat-key-unavailable'
        :reason.includes('Chat cache unavailable')?'chat-cache-unavailable'
        :reason.includes('Team key unavailable')?'team-key-unavailable'
        :reason.includes('Chat workspace changed')?'workspace-changed'
        :/authenticate data|decrypt/i.test(reason)?'decrypt-failed'
        :status?'http-'+status[1]:'window-or-send-error';
      console.error('Member stage failed: '+JSON.stringify({phase,kind,windowReads,windowMessages,serverMessageCount,
        readyAt,checkpointAt,ownerReadyAt,sendStartedAt,sendFinishedAt}));process.exit(1);
    });`;
  const child=spawn('node',['-e',source,SDK,JSON.stringify(input)],{
    cwd:ROOT,env:workflowCliEnv(apiUrl,home),stdio:['ignore','pipe','pipe'],timeout:180_000,killSignal:'SIGKILL',
  });
  let resolveReady:()=>void,rejectReady:(error:Error)=>void;
  const ready=new Promise<void>((resolve,reject)=>{resolveReady=resolve;rejectReady=reject;});
  let resolveCompletion:(timing:MemberTiming)=>void,rejectCompletion:(error:Error)=>void;
  const completion=new Promise<MemberTiming>((resolve,reject)=>{resolveCompletion=resolve;rejectCompletion=reject;});
  void ready.catch(()=>{});void completion.catch(()=>{});
  let buffer='',errorOutput='',isReady=false,timing:MemberTiming|null=null;
  child.stdout.on('data',(chunk:Buffer)=>{
    buffer+=chunk.toString();let end:number;
    while((end=buffer.indexOf('\n'))>=0){
      const line=buffer.slice(0,end);buffer=buffer.slice(end+1);
      let row:{stage?:string}&Partial<MemberTiming>;
      try{row=JSON.parse(line);}catch{continue;}
      if(row.stage==='ready'){isReady=true;resolveReady();}
      if(row.stage==='done')timing=row as MemberTiming;
    }
  });
  child.stderr.on('data',(chunk:Buffer)=>{errorOutput+=chunk.toString();});
  const fail=(error:Error)=>{rejectReady(error);rejectCompletion(error);};
  child.on('error',fail);
  child.on('close',(code:number|null)=>{
    if(code===0&&isReady&&timing)resolveCompletion(timing);
    else fail(new Error(`Member send failed (${code}): ${errorOutput}`));
  });
  return {ready,completion,stop:()=>{if(child.exitCode===null)child.kill('SIGTERM');}};
}

async function pairCli(page:Page,apiUrl:string,home:string):Promise<void> {
  const child=spawn('node',[CLI,'login'],{
    cwd:ROOT,env:workflowCliEnv(apiUrl,home),stdio:['pipe','pipe','pipe'],timeout:60_000,killSignal:'SIGKILL',
  });
  const closed=new Promise<number|null>((resolve,reject)=>{
    child.once('close',resolve);child.once('error',reject);
  });
  void closed.catch(()=>{});
  let output='';child.stdout.on('data',(chunk:Buffer)=>{output+=chunk.toString();});
  child.stderr.on('data',(chunk:Buffer)=>{output+=chunk.toString();});
  const waitOutput=async (pattern:RegExp,label:string) => {
    let match:RegExpMatchArray|null=null;
    await expect.poll(()=>{match=output.match(pattern);return !!match;},{timeout:30_000,message:label}).toBe(true);
    return match!;
  };
  try {
    const token=(await waitOutput(/pair=([A-Z0-9]{6})/,'CLI pair token'))[1];
    const baseUrl=process.env.PLAYWRIGHT_TEST_BASE_URL||'http://localhost:5173';
    await page.goto(`${baseUrl}/#pair=${token}`);
    await page.getByTestId('pair-allow-button').click();
    const pin=((await page.getByTestId('pair-pin-display').textContent())||'').replace(/\s/g,'').trim();
    expect(pin).toMatch(/^[A-Z0-9]{6}$/);
    await waitOutput(/Enter 6-char pairing PIN:/,'CLI PIN prompt');
    child.stdin.write(`${pin}\n`);
    const code=await closed;
    if(code!==0)throw new Error(`CLI login failed (${code}): ${output}`);
    expect(output).toContain('Login successful');
  } catch(error) { child.kill('SIGTERM');throw error; }
}

function frameAt(transcript:string,offset:number):string {
  const output=Buffer.from(transcript,'utf8').subarray(0,offset).toString('utf8');
  const end=output.lastIndexOf('\x1b[?2026l'),start=output.lastIndexOf('\x1b[?2026h',end);
  expect(start).toBeGreaterThanOrEqual(0);
  // eslint-disable-next-line no-control-regex -- Terminal frame boundaries contain ANSI escape bytes.
  return output.slice(start+8,end).replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'');
}

// contract-test: direct surface=cli assertions=teams.chat.encrypted-until-invoked,teams.chat.sender-identity-layout,teams.collaboration.realtime-team-sync,teams.chat-billing.team-credit-boundary,teams.context.full-switch-local,terminal-ui.workspaces.web-aligned
test('two Team members chat in the terminal without AI and refresh the open conversation',async (
  {page,browser}:{page:Page;browser:Browser},testInfo:TestInfo,
) => {
  test.setTimeout(360_000);
  requireIsolatedCliBuild();
  const ownerAccount=getTestAccount(1),memberAccount=getTestAccount(2);
  test.skip(!ownerAccount.email||!ownerAccount.password||!memberAccount.email||!memberAccount.password||ownerAccount.email===memberAccount.email,
    'Two distinct isolated test accounts are required');
  installRecorderDeps();
  const apiUrl=workflowApiUrl();
  const ownerHome=createWorkflowCliHome('team-tui-owner'),memberHome=createWorkflowCliHome('team-tui-member');
  let memberContext:BrowserContext|null=null;
  const outputDir=testInfo.outputPath('team-terminal-video');
  const inputPlan=testInfo.outputPath('team-terminal-input.json');
  let teamId:string|null=null;
  let memberRun:ReturnType<typeof startMemberReply>|null=null;
  let testError:unknown;
  const cleanupErrors:unknown[]=[];
  const first='Owner starts this private Team chat.';
  const ownerText='Owner confirms the venue near Alexanderplatz.';
  const memberText='Maya can bring the printed agenda.';
  const inboundMarker=`inbound-ready-${Date.now()}`;
  try {
    memberContext=await browser.newContext({baseURL:process.env.PLAYWRIGHT_TEST_BASE_URL});
    const memberPage=await memberContext.newPage();
    await loginToTestAccount(page,undefined,undefined,{credentials:ownerAccount});
    await skipIfFeaturesDisabled(test,page,['platform:teams']);
    await pairCli(page,apiUrl,ownerHome);
    await loginToTestAccount(memberPage,undefined,undefined,{credentials:memberAccount});
    await pairCli(memberPage,apiUrl,memberHome);
    const setup=sdk<{teamId:string;chatId:string;inviteId:string;inviteSecret:string;teamName:string}>(apiUrl,ownerHome,`
      const teamName='Terminal Team '+Date.now();
      const team=await client.createTeam({name:teamName,description:'Isolated terminal collaboration proof'});
      const teamId=team.team_id;if(!teamId)throw Error('Team ID missing');
      const invite=await client.createTeamInvite(teamId,{recipient_email:input.memberEmail,role:'member'});
      client.setActiveTeamId(teamId);
      const sent=await client.sendMessage({message:input.first,piiDetection:false});
      process.stdout.write(JSON.stringify({teamId,chatId:sent.chatId,inviteId:invite.invite_id,inviteSecret:invite.invite_secret,teamName}));
    `,{memberEmail:memberAccount.email,first});
    teamId=setup.teamId;
    expect(setup.chatId).toBeTruthy();expect(setup.inviteSecret).toBeTruthy();
    sdk(apiUrl,memberHome,`
      const accepted=await client.acceptTeamInvite(input.inviteId,{inviteSecret:input.inviteSecret,recipientEmail:input.email});
      if(accepted.status!=='accepted')throw Error('Team invite was not accepted');
      client.setActiveTeamId(input.teamId);
      await client.updateOwnTeamMemberProfile(input.teamId,{display_name:'Maya',avatar:'M'});
      process.stdout.write(JSON.stringify({ok:true}));
    `,{...setup,email:memberAccount.email});
    fs.mkdirSync(outputDir,{recursive:true});
    // Keep the member client connected and hydrate its Team key before capture.
    // The inbound deadline then measures delivery, rather than initial account sync.
    memberRun=startMemberReply(apiUrl,memberHome,{teamId,chatId:setup.chatId,first,ownerText,memberText,
      transcriptPath:path.join(outputDir,'transcript.txt'),marker:inboundMarker});
    await memberRun.ready;
    const steps=[
      {name:'team-home',wait_for:`Team · ${setup.teamName}`,wait_timeout_ms:30_000,hold_ms:500},
      {name:'open-chat-command',text:`/chat ${setup.chatId}`,hold_ms:200},
      {name:'open-chat',key:'Return',wait_for:first,wait_timeout_ms:30_000,hold_ms:300},
      {name:'owner-compose',text:ownerText,hold_ms:300},
      {name:'owner-send',key:'Return',wait_for:'Ask a follow-up',wait_timeout_ms:30_000,hold_ms:800},
      {name:'member-arrives',text:inboundMarker,wait_for:memberText,wait_timeout_ms:30_000,hold_ms:500},
      {name:'clear-inbound-marker',key:'ctrl+u',hold_ms:200},
      {name:'members-command',text:'/settings teams/members',hold_ms:200},
      {name:'members-page',key:'Return',wait_for:'Settings  /  Members',wait_timeout_ms:30_000,hold_ms:500},
      {name:'close-settings',click:{text:'Close Settings'}},
      {name:'select-command',text:'/settings teams/select',hold_ms:200},
      {name:'select-page',key:'Return',wait_for:'Switch to Personal',wait_timeout_ms:30_000},
      {name:'switch-personal',click:{text:'Switch to Personal'},wait_for_absent:memberText,wait_for:'DAILY INSPIRATION',wait_timeout_ms:30_000,hold_ms:800},
      {name:'exit',key:'ctrl+c'},
    ];
    fs.writeFileSync(inputPlan,JSON.stringify({steps},null,2));
    const recording=recordInteractiveCli(apiUrl,ownerHome,outputDir,inputPlan,CLI);
    // Always finish the graphical capture, including when the member cannot
    // see the owner's message. Its transcript then identifies the failed step.
    const [recordingResult,memberResult]=await Promise.allSettled([recording,memberRun.completion]);
    if(memberResult.status==='fulfilled') {
      fs.writeFileSync(testInfo.outputPath('team-member-timing.json'),JSON.stringify(memberResult.value,null,2));
      await testInfo.attach('team-member-timing',{path:testInfo.outputPath('team-member-timing.json'),contentType:'application/json'});
    }
    const recorderError=recordingResult.status==='rejected' ? recordingResult.reason
      : recordingResult.value.code===0 ? null : new Error(`Recorder failed (${recordingResult.value.code}): ${recordingResult.value.stderr}\n${recordingResult.value.stdout}`);
    const memberError=memberResult.status==='rejected'?memberResult.reason:null;
    if(recorderError&&memberError)throw new AggregateError([recorderError,memberError],'Recorder and member send failed');
    if(recorderError)throw recorderError;
    if(memberError)throw memberError;
    const recorded=recordingResult.status==='fulfilled'?recordingResult.value:null;
    expect(recorded?.code).toBe(0);
    const manifest=JSON.parse(fs.readFileSync(path.join(outputDir,'manifest.json'),'utf8'));
    expect(manifest.capture_kind).toBe('real_terminal_screen');expect(manifest.reconstructed).toBe(false);
    const transcript=fs.readFileSync(path.join(outputDir,'transcript.txt'),'utf8');
    const checkpoint=(name:string)=>manifest.input_checkpoints.find((item:{name:string})=>item.name===name)?.transcript_offset as number;
    const ownerFrame=frameAt(transcript,checkpoint('owner-send'));
    expect(ownerFrame).toContain(ownerText);expect(ownerFrame).not.toMatch(/Assistant is typing|\n\s*Assistant\s*\n/);
    const arrivalFrame=frameAt(transcript,checkpoint('member-arrives'));
    expect(arrivalFrame).toContain(`[M] Maya`);expect(arrivalFrame).toContain(memberText);
    expect(frameAt(transcript,checkpoint('members-page'))).toContain('Settings  /  Members');
    const personalFrame=frameAt(transcript,checkpoint('switch-personal'));
    expect(personalFrame).not.toContain(memberText);expect(personalFrame).not.toContain(setup.teamName);
    const privateWindow=await page.request.get(`${apiUrl}/v1/chats/${setup.chatId}/messages/window?team_id=${teamId}&limit=100`);
    expect(privateWindow.ok()).toBe(true);
    const windowBody=await privateWindow.json() as {messages:Array<Record<string,unknown>>};
    expect(windowBody.messages.filter(message=>message.role==='user').length).toBeGreaterThanOrEqual(3);
    for(const message of windowBody.messages.filter(message=>message.role==='user')) {
      expect(message.encrypted_content).toBeTruthy();expect(message.hashed_user_id).toMatch(/^[0-9a-f]{64}$/);
      expect(message.content).toBeUndefined();expect(message.sender_name).toBeUndefined();
    }
    for(const line of [first,ownerText,memberText])expect(JSON.stringify(windowBody)).not.toContain(line);
    const usage=sdk<{usage:unknown[]}>(apiUrl,ownerHome,`
      const usage=await client.listTeamUsage(input.teamId);process.stdout.write(JSON.stringify({usage}));
    `,{teamId}).usage;
    expect(usage).toHaveLength(0);
  } catch(error) {testError=error;} finally {
    memberRun?.stop();
    for(const [name,file,contentType] of [
      ['team-terminal-video','raw-terminal.mp4','video/mp4'],
      ['team-terminal-manifest','manifest.json','application/json'],
      ['team-terminal-transcript','transcript.txt','text/plain'],
      ['team-terminal-input-plan',path.basename(inputPlan),'application/json'],
    ]) {
      const target=name==='team-terminal-input-plan'?inputPlan:path.join(outputDir,file);
      if(fs.existsSync(target))try {await testInfo.attach(name,{path:target,contentType});} catch(error) {cleanupErrors.push(error);}
    }
    if(teamId)try {
      sdk(apiUrl,ownerHome,`
        const result=await client.deleteTeam(input.teamId);
        if(!result.success)throw Error('Team deletion did not succeed');
        try { await client.getTeam(input.teamId);throw Error('Deleted Team remains accessible'); }
        catch(error) { if(!String(error.message).includes('HTTP 404'))throw error; }
        process.stdout.write(JSON.stringify({ok:true}));
      `,{teamId});
    } catch(error) {cleanupErrors.push(error);}
    if(memberContext)try {await memberContext.close();} catch(error) {cleanupErrors.push(error);}
    try {removeWorkflowCliHome(memberHome);} catch(error) {cleanupErrors.push(error);}
    try {removeWorkflowCliHome(ownerHome);} catch(error) {cleanupErrors.push(error);}
  }
  if(cleanupErrors.length)throw new AggregateError(testError===undefined?cleanupErrors:[testError,...cleanupErrors],'Team terminal cleanup failed');
  if(testError!==undefined)throw testError;
});
