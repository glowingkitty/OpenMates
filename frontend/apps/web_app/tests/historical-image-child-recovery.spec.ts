/* eslint-disable @typescript-eslint/no-require-imports */
/** Repairs parent-only historical image children through exact scoped ciphertext reads, without inference. */
export {};

const { test, expect } = require('./console-monitor');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { getTestAccount } = require('./signup-flow-helpers');
const { CLI_DIST } = require('./helpers/cli-test-helpers');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair,
	runWorkflowCli, workflowCliEnv, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');

const ROOT = path.resolve(__dirname, '../../../..');
const QUERY = 'deterministic historical image';
type Seed = { chatId: string; embedId: string; childId: string; ownerId: string };

function seedViaPairedCli(apiUrl: string, home: string): Seed {
	const modulePath = path.join(path.dirname(CLI_DIST), 'index.js');
	const source = String.raw`
		const {pathToFileURL}=require('node:url');
		const {randomUUID,randomBytes,createHash,webcrypto}=require('node:crypto');
		(async()=>{
			const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
			const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
			const owner=await client.whoAmI();
			if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal account');
			const hash=value=>createHash('sha256').update(value).digest('hex');
			const encrypt=async(value,key)=>{
				const iv=randomBytes(12),cryptoKey=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
				return Buffer.concat([iv,Buffer.from(await webcrypto.subtle.encrypt({name:'AES-GCM',iv},cryptoKey,
					Buffer.from(value)))]).toString('base64');
			};
			const chatId=randomUUID(),userId=randomUUID(),assistantId=randomUUID();
			const embedId=randomUUID(),childId=randomUUID(),chatKey=randomBytes(32),embedKey=randomBytes(32);
			const now=Math.floor(Date.now()/1000);
			const newline=String.fromCharCode(10);
			const answer='Historical image recovery '+chatId+newline+newline+'[!](embed:historical-image-result)'
				+newline+newline+'[!](embed:unrelated-ref-must-not-fetch)';
			const {ws}=await client.openWsClient({taskUpdateJobs:false});
			const send=async(type,reply,payload)=>{
				const requestId=randomUUID();
				const receipt=ws.waitForMessage(reply,p=>p.request_id===requestId,30000);
				await ws.sendAsync(type,{...payload,request_id:requestId});
				return (await receipt).payload;
			};
			try{
				const metadataReceipt=ws.waitForMessage('encrypted_metadata_stored',p=>p.chat_id===chatId,30000);
				await ws.sendAsync('encrypted_chat_metadata',{
					chat_id:chatId,message_id:userId,team_id:null,created_at:now-1,
					encrypted_content:await encrypt('Find the historical image fixture',chatKey),
					encrypted_sender_name:await encrypt('You',chatKey),
					encrypted_category:await encrypt('general_knowledge',chatKey),
					encrypted_title:await encrypt('Historical image recovery '+chatId.slice(0,6),chatKey),
					encrypted_icon:await encrypt('image',chatKey),
					encrypted_chat_category:await encrypt('general_knowledge',chatKey),
					encrypted_chat_key:await encrypt(chatKey,client.getMasterKeyBytes()),
					versions:{messages_v:2,title_v:1,metadata_v:1,last_edited_overall_timestamp:now},
					message_history:[{message_id:assistantId,role:'assistant',created_at:now,
						encrypted_content:await encrypt(answer,chatKey),
						encrypted_sender_name:await encrypt('Assistant',chatKey),
						encrypted_category:await encrypt('general_knowledge',chatKey)}]
				});
				const stored=(await metadataReceipt).payload;
				if(stored.chat_id!==chatId||stored.message_id!==userId)throw Error('Encrypted metadata not accepted');
				let historyReady=false,lastObservation='owned encrypted message window not ready';
				for(let attempt=0;attempt<30;attempt++){
					try{
						await client.ensureSynced(true,[chatId],{personal:true});
						const history=await client.getChatMessagesWindow(chatId,{
							direction:'latest',limit:10,respectCompressionBoundary:false
						});
						lastObservation='fresh window roles='+history.messages.map(message=>message.role).join(',');
						if(history.messages.some(message=>message.role==='user')
							&&history.messages.some(message=>message.role==='assistant')){historyReady=true;break}
					}catch(error){lastObservation='SDK read: '+(error?.message??String(error))}
					await new Promise(resolve=>setTimeout(resolve,1000));
				}
				if(!historyReady)throw Error('Encrypted chat history did not sync: '+lastObservation);
				const parent={app_id:'images',skill_id:'search',status:'finished',query:'${QUERY}',
					provider:'Brave Search',embed_ids:childId,result_count:1};
				const child={type:'image_result',app_id:'images',skill_id:'search',embed_ref:'historical-image-result',title:'Historical image fixture',
                    image_url:'/favicon.png',thumbnail_url:'/favicon.png',
                    source_page_url:'https://app.dev.openmates.org',source:'openmates.org',description:'Deterministic encrypted historical image'};
				for(const [id,content,type] of [[embedId,parent,'app_skill_use'],[childId,child,'image_result']]){
					const receipt=await send('store_embed','store_embed_confirmed',{
						embed_id:id,chat_id:chatId,team_id:null,
						app_id:'images',skill_id:'search',
						...(id===childId?{parent_embed_id:embedId}:{}),
						encrypted_content:await encrypt(JSON.stringify(content),embedKey),
						encrypted_type:await encrypt(type,embedKey),status:'finished',
						hashed_chat_id:hash(chatId),hashed_message_id:hash(assistantId),hashed_user_id:hash(owner.id),
						created_at:now,updated_at:now,version_number:1
					});
					if(receipt.embed_id!==id)throw Error('Embed store receipt mismatch');
				}
				const keys=(await Promise.all([embedId].map(async id=>[
					{hashed_embed_id:hash(id),key_type:'master',hashed_chat_id:null,
						encrypted_embed_key:await encrypt(embedKey,client.getMasterKeyBytes()),
						hashed_user_id:hash(owner.id),created_at:now},
					{hashed_embed_id:hash(id),key_type:'chat',hashed_chat_id:hash(chatId),
						encrypted_embed_key:await encrypt(embedKey,chatKey),
						hashed_user_id:hash(owner.id),created_at:now}
				]))).flat();
				const keyReceipt=await send('store_embed_keys','store_embed_keys_confirmed',{keys});
				if(keyReceipt.created_count!==keys.length||keyReceipt.failed_count!==0)throw Error('Embed key wrappers were not exactly confirmed');
				await client.ensureSynced(true,[chatId],{personal:true});
				const saved=await client.getEmbed(embedId,{preferCache:true,chatId});
				if(saved.content.embed_ids!==childId||saved.content.results)throw Error('Image parent must contain the child ID without inline results');
				process.stdout.write(JSON.stringify({chatId,embedId,childId,ownerId:owner.id}));
			}finally{ws.close()}
		})().catch(error=>{console.error('Encrypted image fixture:',error.message);process.exit(1)});
	`;
	return JSON.parse(execFileSync('node', ['-e', source, modulePath], {
		cwd: ROOT, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 90_000,
	}).trim());
}

// contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence,auth.session.authoritative-enforcement
test('historical Personal image ref recovers only missing encrypted children and survives reload', async ({ page }: { page: any }, testInfo: any) => {
  test.slow(); test.setTimeout(300_000);
  test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.CI_TEST_MODE !== 'e2e',
    'Requires disposable isolated paired browser and CLI backend');
  test.skip(!getTestAccount().email, 'Isolated account required');
  const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('historical-image-child');
  let seed: Seed | undefined;
  let syncCompleted = 0;
  const reads: { path: string; status: number; cipher: boolean; parent: string | null }[] = [];
  let readGeneration = 0;
  const requestGenerations = new WeakMap<object, number>();
  const diagnostics: unknown[] = [];
  const diagnosticRequestIds = new Set<string>();
  // Retain only this synthetic child transport/initiator and embed scope warnings.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  cdp.on('Network.requestWillBeSent', (event: any) => {
    if (event.type === 'Document' && diagnostics.length < 80) diagnostics.push({
      kind: 'document', generation: readGeneration, timestamp: event.timestamp, loaderId: event.loaderId });
    if (!seed || new URL(event.request.url).pathname !== `/v1/embeds/chats/${seed.chatId}/embeds/${seed.childId}`) return;
    diagnosticRequestIds.add(event.requestId);
    if (diagnostics.length < 80) diagnostics.push({ kind: 'request', requestId: event.requestId, loaderId: event.loaderId, generation: readGeneration,
      timestamp: event.timestamp, initiator: event.initiator });
  });
  cdp.on('Network.responseReceived', (event: any) => {
    if (diagnosticRequestIds.has(event.requestId) && diagnostics.length < 80) diagnostics.push({
      kind: 'response', requestId: event.requestId, timestamp: event.timestamp, status: event.response.status });
  });
  cdp.on('Network.loadingFinished', (event: any) => {
    if (diagnosticRequestIds.has(event.requestId) && diagnostics.length < 80) diagnostics.push({
      kind: 'finished', requestId: event.requestId, timestamp: event.timestamp });
  });
  cdp.on('Network.loadingFailed', (event: any) => {
    if (diagnosticRequestIds.has(event.requestId) && diagnostics.length < 80) diagnostics.push({
      kind: 'failed', requestId: event.requestId, timestamp: event.timestamp, error: event.errorText });
  });
  page.on('console', (message: any) => {
    const text = message.text();
    if (diagnostics.length < 80 && (text.includes(seed?.childId ?? '__no_fixture_child__') || /Personal embed read|Embed child recovery|scope changed/.test(text))) {
      diagnostics.push({ kind: 'console', generation: readGeneration, text: text.slice(0, 1500) });
    }
  });
  // Perturb only incoming fixture child rows: backend ciphertext and scoped REST stay real.
  // This models the historical parent-only cache without Phase1b immediately refilling it.
  await page.routeWebSocket(/\/ws(?:\?|$)/, (socket: any) => {
    const server = socket.connectToServer();
    socket.onMessage((message: any) => server.send(message));
    server.onMessage((message: any) => {
      if (!seed || typeof message !== 'string') { socket.send(message); return; }
      let frame: any;
      try { frame = JSON.parse(message); } catch { socket.send(message); return; }
      const omit = (payload: any) => {
        if (!payload || typeof payload !== 'object') return;
        if (Array.isArray(payload.embeds)) payload.embeds = payload.embeds.filter((row: any) => row.embed_id !== seed!.childId);
        if (Array.isArray(payload.chats)) payload.chats.forEach(omit);
      };
      if (frame.type === 'send_embed_data' && frame.payload?.embed_id === seed.childId) return;
      if (frame.type === 'phased_sync_complete') syncCompleted++;
      omit(frame.payload);
      socket.send(JSON.stringify(frame));
    });
  });
  page.on('request', (request: any) => {
    if (seed && new URL(request.url()).pathname === `/v1/embeds/chats/${seed.chatId}/embeds/${seed.childId}`) {
      requestGenerations.set(request, readGeneration);
    }
  });
  page.on('response', async (response: any) => {
    const pathname = new URL(response.url()).pathname;
    if (!seed || pathname !== `/v1/embeds/chats/${seed.chatId}/embeds/${seed.childId}`) return;
    const generation = requestGenerations.get(response.request());
    if (generation !== readGeneration) return;
    const body = await response.json().catch(() => null);
    if (generation !== readGeneration) return;
    reads.push({ path: pathname, status: response.status(), cipher: typeof body?.embed?.encrypted_content === 'string',
      parent: body?.embed?.parent_embed_id ?? null });
  });
  try {
    await loginWorkflowCliViaPair(page, apiUrl, home, 'HISTORICAL_IMAGE_CHILD');
    await page.getByTestId('icon-button-close').click();
    seed = seedViaPairedCli(apiUrl, home);
    await page.goto(`${process.env.PLAYWRIGHT_TEST_BASE_URL}/#chat-id=${seed.chatId}`, { waitUntil: 'domcontentloaded' });
    const syncBeforeInitialReload = syncCompleted;
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect.poll(() => syncCompleted, { timeout: 60_000 }).toBeGreaterThan(syncBeforeInitialReload);
    await expect(page.getByTestId('image-result-preview-image').first()).toBeVisible({ timeout: 60_000 });
    // Equal-version historical chat: retain its chat/message/key rows and durable parent, delete only local child.
    const missing = await page.evaluate(async ({ childId, embedId }) => {
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const req = indexedDB.open('chats_db'); req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
      });
      try {
        const parent = await new Promise<any>((resolve, reject) => {
          const req = db.transaction('embeds').objectStore('embeds').get(`embed:${embedId}`);
          req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
        });
        if (!parent?.encrypted_content) throw Error('Encrypted parent must already be local');
        await new Promise<void>((resolve, reject) => {
          const tx = db.transaction('embeds', 'readwrite'); tx.objectStore('embeds').delete(`embed:${childId}`);
          tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error);
        });
        return true;
      } finally { db.close(); }
    }, seed);
    expect(missing).toBe(true);
    // Count only requests started in this remount, excluding late initial-response callbacks.
    readGeneration++; reads.length = 0;
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect.poll(() => reads.some(row => row.status === 200 && row.cipher && row.parent === seed!.embedId),
      { timeout: 60_000 }).toBe(true);
    await expect(page.getByTestId('image-result-preview-image').first()).toBeVisible({ timeout: 30_000 });
    expect(reads.filter(row => row.status === 200)).toHaveLength(1);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('image-result-preview-image').first()).toBeVisible({ timeout: 30_000 });
    const negative = await page.evaluate(async ({ apiUrl, chatId, childId }) => {
      const wrongChat = '99999999-9999-4999-8999-999999999999';
      const wrong = await fetch(`${apiUrl}/v1/embeds/chats/${wrongChat}/embeds/${childId}`, { credentials: 'include' });
      const malformed = await fetch(`${apiUrl}/v1/embeds/chats/${chatId}/embeds/not-a-uuid`, { credentials: 'include' });
      const unauthenticated = await fetch(`${apiUrl}/v1/embeds/chats/${chatId}/embeds/${childId}`, { credentials: 'omit' });
      return [wrong.status, malformed.status, unauthenticated.status];
    }, { apiUrl, ...seed });
    expect(negative).toEqual([404, 404, 401]);
  } finally {
    await testInfo.attach('historical-child-read-diagnostics', { body: Buffer.from(JSON.stringify(diagnostics, null, 2)), contentType: 'application/json' });
    await cdp.detach();
    try { if (seed) {
      const deletion = await runWorkflowCli(apiUrl, home, ['chats', 'delete', seed.chatId, '--yes'], 15_000);
      expect(deletion.code, deletion.stderr).toBe(0);
    } } finally { removeWorkflowCliHome(home); }
  }
});
