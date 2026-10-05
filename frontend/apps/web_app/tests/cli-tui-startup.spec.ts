/* eslint-disable @typescript-eslint/no-require-imports */
/** Startup gates and inherited-key chat reads over the isolated product stack, without inference. */
export {};
const { test, expect } = require('./console-monitor');
const { requireIsolatedCliBuild, workflowApiUrl, createWorkflowCliHome } = require('./cli-tui-proof-helpers');
const { loginWorkflowCliViaPair, removeWorkflowCliHome, workflowCliEnv, clearWorkflowCliSyncCache } = require('./helpers/workflow-cli-e2e-helpers');
const { runTuiPty } = require('./helpers/tui-pty-test-helpers');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

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

// contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted,chat-navigation.draft-only.addressable
test('cold TUI loads a saved chat and canonical child reads return only authorized parent wrappers', async ({page}: {page: any}, testInfo: any) => {
  test.setTimeout(240_000);
  const cli = requireIsolatedCliBuild(), home = createWorkflowCliHome('tui-inherited-key');
  const api = workflowApiUrl(), env = workflowCliEnv(api, home);
  let chatId: string | undefined;
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
        const now=Math.floor(Date.now()/1000);
        for(const id of [parentId,childId]) await send('store_embed','store_embed_confirmed',{
          embed_id:id,encrypted_content:await encrypt('encrypted fixture content',embedKey),
          encrypted_type:await encrypt('code',embedKey),status:'finished',
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
        process.stdout.write(JSON.stringify({chatId,version:JSON.parse(require('node:fs').readFileSync(require('node:path').join(require('node:path').dirname(process.argv[1]),'../package.json'),'utf8')).version}));
      } finally {ws.close();}
    `);
    chatId = fixture.chatId;
    clearWorkflowCliSyncCache(home);
    const result = await runTuiPty(cli, {...env, TERM: 'xterm-256color', OPENMATES_CLI_LATEST_VERSION: fixture.version}, [
      {waitFor: 'TUI saved recovery draft', absent: ['Canonical recovery embed reread failed', 'Saved chats could not be loaded']},
      {text: '/chat ' + chatId, waitFor: 'Draft', absent: ['DAILY INSPIRATION', 'Canonical recovery embed reread failed']},
    ]);
    expect(result.code).toBe(0);
    await testInfo.attach('cold-tui-chat-frames', {body: JSON.stringify(result), contentType: 'application/json'});
  } finally {
    try {
      if (chatId) sdk(`await client.deleteChat(input.chatId,{personal:true});process.stdout.write('{}');`, {chatId});
    } catch {
      // The isolated runner destroys its disposable database after this spec.
      // A fixture cleanup error must not replace the actual test failure.
      await testInfo.attach('fixture-cleanup', {body: 'Chat API cleanup failed; disposable runner database cleanup removes the fixture.', contentType: 'text/plain'});
    } finally { removeWorkflowCliHome(home); }
  }
});
