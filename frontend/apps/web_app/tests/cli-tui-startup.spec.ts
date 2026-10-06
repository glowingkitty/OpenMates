/* eslint-disable @typescript-eslint/no-require-imports */
/** Startup gates and inherited-key chat reads over the isolated product stack, without inference. */
export {};
const { test, expect } = require('./console-monitor');
const { requireIsolatedCliBuild, workflowApiUrl, createWorkflowCliHome, captureProof, installRecorderDeps } = require('./cli-tui-proof-helpers');
const { loginWorkflowCliViaPair, removeWorkflowCliHome, workflowCliEnv, clearWorkflowCliSyncCache } = require('./helpers/workflow-cli-e2e-helpers');
const { runTuiPty } = require('./helpers/tui-pty-test-helpers');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const startupProofContract = {
  id: 'cli-tui-cached-event-real-terminal', title: 'Cached saved event and draft-only chat in the terminal',
  surface: 'cli', devices: ['cli-terminal'],
  transcript: [
    {id: 'event', text: 'The saved upcoming event remains visible offline while the expired event is absent.', checkpoint: 'offline-home', devices: ['cli-terminal']},
    {id: 'draft', text: 'The local draft-only chat opens offline and restores its encrypted draft.', checkpoint: 'draft-open', devices: ['cli-terminal']},
  ],
  assertions: [
    {id: 'chats.persistence.client-encrypted', checkpoint: 'draft-open', visual: 'The encrypted local draft is readable in the offline chat.', devices: ['cli-terminal']},
    {id: 'continue-carousel.saved-item.start-time-gated', checkpoint: 'offline-home', visual: 'The upcoming saved event appears while the expired event does not.', devices: ['cli-terminal']},
    {id: 'cli.surface.semantic-parity', checkpoint: 'event-open', visual: 'The saved event opens its details in the terminal.', devices: ['cli-terminal']},
  ],
  tutorial: {readingWordsPerSecond: 2.5, minimumHoldMs: 1200, maximumHoldMs: 5000},
};

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,pii.surface.semantic-parity
// eslint-disable-next-line no-empty-pattern -- Playwright requires an object pattern for unused fixtures.
test('fullscreen update precedes the workspace, skip survives restart, and expires after 24 hours', async ({}, testInfo: any) => {
  test.setTimeout(180_000);
  const cli = requireIsolatedCliBuild(), home = createWorkflowCliHome('tui-startup');
  const api = workflowApiUrl(), env = {...workflowCliEnv(api, home), TERM: 'xterm-256color', OPENMATES_CLI_LATEST_VERSION: '99.0.0'};
  try {
    const first = await runTuiPty(cli, env, [
      {waitFor: 'Software update available', absent: ['DAILY INSPIRATION', 'Ask anything']},
      {key: 'skip', waitFor: 'DAILY INSPIRATION', absent: ['Software update available']},
    ]);
    expect(first.code).toBe(0);
    expect(first.frames[0]).toContain('24 hours');
    const reminder = path.join(home, '.openmates/tui-update-reminder.json');
    const deferred = JSON.parse(fs.readFileSync(reminder, 'utf8'));
    expect(deferred.nextPromptAt).toBeGreaterThan(Date.now() + 23 * 60 * 60 * 1000);
    const second = await runTuiPty(cli, env, [{waitFor: 'DAILY INSPIRATION', absent: ['Software update available']}]);
    expect(second.code).toBe(0);
    deferred.nextPromptAt = Date.now() - 1;
    fs.writeFileSync(reminder, JSON.stringify(deferred), {mode: 0o600});
    const third = await runTuiPty(cli, env, [
      {waitFor: 'Software update available', absent: ['DAILY INSPIRATION', 'Ask anything']},
      {key: 'skip', waitFor: 'DAILY INSPIRATION'},
    ]);
    expect(third.code).toBe(0);
    await testInfo.attach('tui-startup-frames', {body: JSON.stringify({first, second, third}), contentType: 'application/json'});
  } finally { removeWorkflowCliHome(home); }
});

// contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted,chat-navigation.draft-only.addressable,continue-carousel.saved-item.start-time-gated,chats.rendering.inline-entity-interaction
test('cold TUI loads a saved chat and canonical child reads return only authorized parent wrappers', async ({page}: {page: any}, testInfo: any) => {
  test.setTimeout(240_000);
  const cli = requireIsolatedCliBuild(), home = createWorkflowCliHome('tui-inherited-key');
  const api = workflowApiUrl(), env = workflowCliEnv(api, home);
  let chatId: string | undefined;
  let memoryId: string | undefined;
  let expiredMemoryId: string | undefined;
  let offlineSessionOriginal: string | undefined;
  const sessionPath=path.join(home, ".openmates/session.json");
  const sdk = (program: string, input: unknown = {}) => JSON.parse(execFileSync('node', ['-e', `
    const {pathToFileURL}=require('node:url');
    const {randomUUID,randomBytes,createHash,webcrypto}=require('node:crypto');
    (async()=>{
      const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
      const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
      const input=JSON.parse(process.argv[2]);
      ${program}
    })().catch(error=>{console.error(error.message);process.exit(1);});
  `, path.join(path.dirname(cli), 'index.js'), JSON.stringify(input)], {env, encoding: 'utf8', timeout: 90_000}).trim());
  try {
    await loginWorkflowCliViaPair(page, api, home, 'TUI_INHERITED_KEY');
    const fixture = sdk(`
      const chatId=randomUUID(),parentId=randomUUID(),childId=randomUUID();
      const hash=value=>createHash('sha256').update(value).digest('hex');
      const ownerId=(await client.whoAmI()).id;
      const master=client.getMasterKeyBytes(),embedKey=randomBytes(32);
      const encrypt=async(value,key)=>{
        const iv=randomBytes(12), k=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
        const bytes=typeof value==='string'?Buffer.from(value):value;
        return Buffer.concat([iv,Buffer.from(await webcrypto.subtle.encrypt({name:'AES-GCM',iv},k,bytes))]).toString('base64');
      };
      await client.saveDraft({chatId,markdown:'TUI saved recovery draft',preview:'TUI saved recovery draft'});
      const {ws}=await client.openWsClient({taskUpdateJobs:false});
      const send=async(type,reply,payload)=>{
        const requestId=randomUUID(), receipt=ws.waitForMessage(reply,p=>p.request_id===requestId,30000);
        await ws.sendAsync(type,{...payload,request_id:requestId});return (await receipt).payload;
      };
      try {
        const now=Math.floor(Date.now()/1000),eventStart=new Date(Date.now()+3600000).toISOString();
        const expiredStart=new Date(Date.now()-4*3600000).toISOString(),expiredEnd=new Date(Date.now()-3*3600000).toISOString();
        for(const id of [parentId,childId]) await send('store_embed','store_embed_confirmed',{
          embed_id:id,encrypted_content:await encrypt(JSON.stringify(id===childId ? {app_id:'events',skill_id:'event',title:'Remembered terminal event',date_start:eventStart,description:'Full remembered event details',venue:{name:'Community hall'},organizer:{name:'Community'},url:'https://example.org/event',is_paid:false} : {code:'export const terminalProof = true;',language:'typescript'}),embedKey),
          encrypted_type:await encrypt(id===childId?'events-event':'code',embedKey),status:'finished',
          hashed_chat_id:hash(chatId),hashed_message_id:hash(randomUUID()),hashed_user_id:hash(ownerId),
          ...(id===childId?{parent_embed_id:parentId}:{}),created_at:now,updated_at:now,version_number:1
        });
        await send('store_embed_keys','store_embed_keys_confirmed',{keys:[{
          hashed_embed_id:hash(parentId),key_type:'master',hashed_chat_id:null,
          encrypted_embed_key:await encrypt(embedKey,master),hashed_user_id:hash(ownerId),created_at:now
        }]});
        const result=await client.http.get('/v1/embeds/chats/'+chatId+'/embeds/'+childId,client.getCliRequestHeaders());
        if(!result.ok)throw Error('Inherited canonical child read failed: '+result.status);
        if(result.data.embed.embed_id!==childId||result.data.embed_keys.length!==1||result.data.embed_keys[0].hashed_embed_id!==hash(parentId))throw Error('Wrong inherited wrapper scope');
        const missing=await client.http.get('/v1/embeds/chats/'+chatId+'/embeds/'+randomUUID(),client.getCliRequestHeaders());
        if(missing.status!==404)throw Error('Unknown child must stay masked');
        const memory=await client.createMemory({appId:'events',itemType:'saved_events',personal:true,itemValue:{embed_id:childId,title:'Remembered terminal event',date_start:eventStart,url:'https://example.org/event'}});
        const expired=await client.createMemory({appId:'events',itemType:'saved_events',personal:true,itemValue:{embed_id:randomUUID(),title:'Expired terminal event',date_start:expiredStart,date_end:expiredEnd,url:'https://example.org/past-event'}});
        process.stdout.write(JSON.stringify({chatId,memoryId:memory.id,expiredMemoryId:expired.id,version:JSON.parse(require('node:fs').readFileSync(require('node:path').join(require('node:path').dirname(process.argv[1]),'../package.json'),'utf8')).version}));
      } finally {ws.close();}
    `);
    chatId = fixture.chatId;
    memoryId = fixture.memoryId;
    expiredMemoryId = fixture.expiredMemoryId;
    clearWorkflowCliSyncCache(home);
    const result = await runTuiPty(cli, {...env, TERM: 'xterm-256color', OPENMATES_CLI_LATEST_VERSION: fixture.version}, [
      {waitFor: 'Remembered terminal event', absent: ['Expired terminal event', 'Canonical recovery embed reread failed', 'Saved chats could not be loaded']},
      {key: 'enter', waitFor: 'Full remembered event details', absent: ['Loading embed', 'Continue where you left off']},
      {key: 'escape', waitFor: 'Remembered terminal event', absent: ['Full remembered event details']},
      {text: '/chat ' + chatId, waitFor: 'Draft', absent: ['DAILY INSPIRATION', 'Canonical recovery embed reread failed']},
    ]);
    expect(result.code).toBe(0);
    await testInfo.attach('cold-tui-chat-frames', {body: JSON.stringify(result), contentType: 'application/json'});
    // An expired cache must remain immediately usable while the next sync fails.
    const cachePath = path.join(home, '.openmates/sync_cache.json');
    const cache = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
    expect(JSON.stringify(cache)).not.toContain('Full remembered event details');
    expect(JSON.stringify(cache)).not.toContain('Remembered terminal event');
    cache.syncedAt = 0;
    fs.writeFileSync(cachePath, JSON.stringify(cache), {mode: 0o600});
    // HTTP overrides do not change the origin-bound WebSocket saved in a session.
    // Disable both transports in this disposable profile, retaining its encrypted cache.
    offlineSessionOriginal=fs.readFileSync(sessionPath,'utf8');
    const offlineSession=JSON.parse(offlineSessionOriginal);offlineSession.apiUrl='http://127.0.0.1:1';
    fs.writeFileSync(sessionPath,JSON.stringify(offlineSession),{mode:0o600});
    const offline = await runTuiPty(cli, {...env, OPENMATES_API_URL: 'http://127.0.0.1:1',
      TERM: 'xterm-256color', OPENMATES_CLI_LATEST_VERSION: fixture.version}, [
      {waitFor: 'TUI saved recovery draft', absent: ['Expired terminal event', 'Loading your recent chats']},
      {waitFor: 'Showing cached chats. Sync failed', absent: ['Loading your recent chats']},
      {key: 'enter', waitFor: 'Full remembered event details', absent: ['Loading embed', 'Continue where you left off']},
      {key: 'escape', waitFor: 'Remembered terminal event', absent: ['Full remembered event details']},
      {text: '/chat ' + chatId, waitFor: 'TUI saved recovery draft', absent: ['Loading chat', 'Continue where you left off']},
    ]);
    expect(offline.code).toBe(0);
    await testInfo.attach('cached-offline-tui-frames', {body: JSON.stringify(offline), contentType: 'application/json'});
    installRecorderDeps();
    const previousLatestVersion = process.env.OPENMATES_CLI_LATEST_VERSION;
    process.env.OPENMATES_CLI_LATEST_VERSION = fixture.version;
    try {
      const recording = await captureProof('http://127.0.0.1:1', home, cli, [
        {name: 'offline-home', wait_for: 'Remembered terminal event', wait_for_absent: 'Expired terminal event', hold_ms: 500},
        {name: 'event-open', key: 'Return', wait_for: 'Full remembered event details', wait_for_absent: 'Loading embed', hold_ms: 400},
        {name: 'event-close', key: 'Escape', wait_for: 'Remembered terminal event', hold_ms: 300},
        {name: 'draft-command', text: '/chat ' + chatId},
        {name: 'draft-open', key: 'Return', wait_for: 'TUI saved recovery draft', wait_for_absent: 'Loading chat', hold_ms: 500},
        {name: 'draft-close', key: 'Escape', wait_for: 'Remembered terminal event', hold_ms: 300},
        {name: 'exit-command', text: '/exit'},
        {name: 'exit', key: 'Return'},
      ], startupProofContract, testInfo);
      const homeFrame = recording.frame('offline-home').join('\n');
      expect(homeFrame).toContain('Remembered terminal event');
      expect(homeFrame).not.toContain('Expired terminal event');
      expect(recording.frame('event-open').join('\n')).toContain('Full remembered event details');
      expect(recording.frame('draft-open').join('\n')).toContain('TUI saved recovery draft');
      await recording.attest();
    } finally {
      if (previousLatestVersion === undefined) delete process.env.OPENMATES_CLI_LATEST_VERSION;
      else process.env.OPENMATES_CLI_LATEST_VERSION = previousLatestVersion;
    }
  } finally {
    if(offlineSessionOriginal !== undefined)fs.writeFileSync(sessionPath,offlineSessionOriginal,{mode:0o600});
    try {
      if (memoryId) sdk(`await client.deleteMemory(input.memoryId,{personal:true});process.stdout.write('{}');`, {memoryId});
      if (expiredMemoryId) sdk(`await client.deleteMemory(input.memoryId,{personal:true});process.stdout.write('{}');`, {memoryId:expiredMemoryId});
      if (chatId) sdk(`await client.deleteChat(input.chatId,{personal:true});process.stdout.write('{}');`, {chatId});
    } catch {
      // The isolated runner destroys its disposable database after this spec.
      // A fixture cleanup error must not replace the actual test failure.
      await testInfo.attach('fixture-cleanup', {body: 'Chat API cleanup failed; disposable runner database cleanup removes the fixture.', contentType: 'text/plain'});
    } finally { removeWorkflowCliHome(home); }
  }
});
