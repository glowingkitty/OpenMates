/* eslint-disable @typescript-eslint/no-require-imports */
/** Replays an old preview write through a paired, encrypted chat without AI inference. */
export {};

const { test, expect } = require('./console-monitor');
const { randomUUID, createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { getTestAccount } = require('./signup-flow-helpers');
const { waitForEmbedFinished, openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');
const { CLI_DIST } = require('./helpers/cli-test-helpers');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair,
	runWorkflowCli, workflowCliEnv, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');

const ROOT = path.resolve(__dirname, '../../../..');
const QUERY = 'openmates_e2e_web_fixture_ai';
type Frame = { direction: 'sent' | 'received'; type: string; payload: Record<string, any> };
type Seed = { chatId: string; embedId: string; childId: string; ownerId: string };

async function embedStorageSummary(page: any, seed: Seed) {
	return page.evaluate(async ({ embedId, childId }) => {
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			const request = indexedDB.open('chats_db');
			request.onsuccess = () => resolve(request.result);
			request.onerror = () => reject(request.error);
		});
		try {
			const digest = async (id: string) => Array.from(new Uint8Array(await crypto.subtle.digest(
				'SHA-256', new TextEncoder().encode(id))))
				.map(byte => byte.toString(16).padStart(2, '0')).join('');
			const result = [];
			for (const id of [embedId, childId]) {
				const row = await new Promise<any>((resolve, reject) => {
					const request = db.transaction('embeds', 'readonly').objectStore('embeds').get(`embed:${id}`);
					request.onsuccess = () => resolve(request.result);
					request.onerror = () => reject(request.error);
				});
				const hashedId = await digest(id);
				const wrappers = await new Promise<any[]>((resolve, reject) => {
					const request = db.transaction('embed_keys', 'readonly').objectStore('embed_keys')
						.index('hashed_embed_id').getAll(hashedId);
					request.onsuccess = () => resolve(request.result ?? []);
					request.onerror = () => reject(request.error);
				});
				result.push({ role: id === embedId ? 'parent' : 'child', present: Boolean(row),
					status: row?.status ?? null, type_present: typeof row?.type === 'string', app_id: row?.app_id ?? null,
					skill_id: row?.skill_id ?? null, encryption_mode: row?.encryption_mode ?? null,
					version_number: row?.version_number ?? null,
					content_length: typeof row?.encrypted_content === 'string' ? row.encrypted_content.length : 0,
					wrapper_types: wrappers.map(wrapper => wrapper.key_type).sort() });
			}
			return result;
		} finally { db.close(); }
	}, seed);
}

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
			const now=Math.floor(Date.now()/1000),fence=String.fromCharCode(96).repeat(3);
			const newline=String.fromCharCode(10);
			const answer='The local result is ready.'+newline+newline+fence+'json'+newline+JSON.stringify({
				type:'app_skill_use',embed_id:embedId,app_id:'web',skill_id:'search',status:'finished'
			})+newline+fence;
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
					encrypted_content:await encrypt('Search the web for ${QUERY}',chatKey),
					encrypted_sender_name:await encrypt('You',chatKey),
					encrypted_category:await encrypt('general_knowledge',chatKey),
					encrypted_title:await encrypt('Web preview backfill '+chatId.slice(0,6),chatKey),
					encrypted_icon:await encrypt('search',chatKey),
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
				let historyReady=false,lastObservation='chat absent from synced list';
				for(let attempt=0;attempt<30;attempt++){
					try{
						const page=await client.listChats(20,1,{forceRefresh:true});
						if(page.chats.some(chat=>chat.id===chatId)){
							const history=await client.getChatMessagesWindow(chatId,{
								direction:'latest',limit:10,respectCompressionBoundary:false
							});
							lastObservation='fresh window roles='+history.messages.map(message=>message.role).join(',');
							if(history.messages.some(message=>message.role==='user')
								&&history.messages.some(message=>message.role==='assistant')){historyReady=true;break}
						}
					}catch(error){lastObservation='SDK read: '+(error?.message??String(error))}
					await new Promise(resolve=>setTimeout(resolve,1000));
				}
				if(!historyReady)throw Error('Encrypted chat history did not sync: '+lastObservation);
				const parent={app_id:'web',skill_id:'search',status:'finished',query:'${QUERY}',
					provider:'Brave Search',embed_ids:childId,result_count:1};
				const child={title:'OpenMates E2E Web Fixture',url:'https://app.dev.openmates.org/web/fixtures/ai-assistant',
					description:'A deterministic web result for the preview backfill regression.'};
				for(const [id,content,type] of [[embedId,parent,'app_skill_use'],[childId,child,'website']]){
					const receipt=await send('store_embed','store_embed_confirmed',{
						embed_id:id,chat_id:chatId,team_id:null,app_id:'web',skill_id:'search',
						...(id===childId?{parent_embed_id:embedId}:{}),
						encrypted_content:await encrypt(JSON.stringify(content),embedKey),
						encrypted_type:await encrypt(type,embedKey),status:'finished',
						hashed_chat_id:hash(chatId),hashed_message_id:hash(assistantId),hashed_user_id:hash(owner.id),
						created_at:now,updated_at:now,version_number:1
					});
					if(receipt.embed_id!==id)throw Error('Embed store receipt mismatch');
				}
				const keys=(await Promise.all([embedId,childId].map(async id=>[
					{hashed_embed_id:hash(id),key_type:'master',hashed_chat_id:null,
						encrypted_embed_key:await encrypt(embedKey,client.getMasterKeyBytes()),
						hashed_user_id:hash(owner.id),created_at:now},
					{hashed_embed_id:hash(id),key_type:'chat',hashed_chat_id:hash(chatId),
						encrypted_embed_key:await encrypt(embedKey,chatKey),
						hashed_user_id:hash(owner.id),created_at:now}
				]))).flat();
				const keyReceipt=await send('store_embed_keys','store_embed_keys_confirmed',{keys});
				if(keyReceipt.created_count!==keys.length||keyReceipt.failed_count!==0
					||keyReceipt.requested_count!==keys.length)throw Error('Embed key wrappers were not exactly confirmed');
				const saved=await client.getEmbed(embedId,{preferCache:true,chatId});
				if(saved.content.embed_ids!==childId||saved.content.results)throw Error('Parent must need preview backfill');
				const savedChild=await client.getEmbed(childId,{preferCache:true,chatId});
				if(savedChild.type!=='website'||savedChild.content.url!==child.url
					||savedChild.content.title!==child.title)throw Error('Saved website child did not decrypt');
				process.stdout.write(JSON.stringify({chatId,embedId,childId,ownerId:owner.id}));
			}finally{ws.close()}
		})().catch(error=>{console.error('Encrypted backfill fixture:',error.message);process.exit(1)});
	`;
	return JSON.parse(execFileSync('node', ['-e', source, modulePath], {
		cwd: ROOT, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 90_000,
	}).trim());
}

async function queueLegacyOperation(page: any, embedId: string, operationId: string, payload: Record<string, any>) {
	return page.evaluate(async ({ embedId, operationId, payload }) => {
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			const request = indexedDB.open('chats_db');
			request.onsuccess = () => resolve(request.result);
			request.onerror = () => reject(request.error);
		});
		try {
			const raw = await new Promise<any>((resolve, reject) => {
				const request = db.transaction('embeds', 'readonly').objectStore('embeds').get(`embed:${embedId}`);
				request.onsuccess = () => resolve(request.result);
				request.onerror = () => reject(request.error);
			});
			await new Promise<void>((resolve, reject) => {
				const tx = db.transaction('pending_embed_operations', 'readwrite');
				tx.objectStore('pending_embed_operations').put({ operation_id: operationId, embed_id: embedId,
					store_embed_payload: payload, created_at: Date.now() });
				tx.oncomplete = () => resolve();
				tx.onerror = () => reject(tx.error);
			});
			return { app_id: raw?.app_id, skill_id: raw?.skill_id, hashed_chat_id: raw?.hashed_chat_id };
		} finally { db.close(); }
	}, { embedId, operationId, payload });
}

// contract-test: direct surface=gui.web assertions=web-search.surface-parity,chats.persistence.client-encrypted
test('legacy web search preview backfill replays with canonical catalog context', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.CI_TEST_MODE !== 'e2e',
		'Requires disposable isolated browser and CLI backend');
	test.skip(!getTestAccount().email, 'Isolated test account credentials required');
	expect(fs.existsSync(CLI_DIST), 'Candidate paired CLI build required').toBe(true);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('embed-backfill');
	const frames: Frame[] = [];
	const embedReads: Record<string, unknown>[] = [];
	const browserSignals: Record<string, unknown>[] = [];
	let seed: Seed | undefined;
	page.on('console', (message: any) => {
		const level = message.type();
		if ((level !== 'warning' && level !== 'error') || browserSignals.length >= 20) return;
		const value = message.text();
		const source = [
			['embedStore', '[EmbedStore]'],
			['unifiedPreview', '[UnifiedEmbedPreview]'],
			['embedResolver', '[embedResolver]'],
			['appSkillRenderer', '[AppSkillUseRenderer]'],
			['unifiedFullscreen', '[UnifiedEmbedFullscreen]'],
		] as const;
		const match = source.find(([, prefix]) => value.startsWith(prefix));
		if (!match) return;
		browserSignals.push({ level, source: match[0], decrypt: /decrypt|encrypt/i.test(value),
			key: /\bkey\b|wrapper/i.test(value), fetch: /fetch|request|resolve/i.test(value),
			failure: /fail|error|missing|not found|unavailable/i.test(value),
			error_names: ['OperationError', 'InvalidStateError', 'NotFoundError', 'DataError',
				'AbortError', 'TypeError', 'NetworkError', 'SecurityError'].filter(name => value.includes(name)) });
	});
	page.on('response', async (response: any) => {
		try {
			const url = new URL(response.url());
			if (!/^\/v1\/embeds\/chats\/[^/]+\/(?:embeds\/[^/]+|keys\/window)$/.test(url.pathname)
				|| !seed || !url.pathname.includes(`/chats/${seed.chatId}/`)
				|| embedReads.length >= 20) return;
			const body = await response.json().catch(() => null);
			const row = body?.embed;
			const wrappers = Array.isArray(body?.embed_keys) ? body.embed_keys : [];
			const isEmbedRead = /\/embeds\/[^/]+$/.test(url.pathname);
			embedReads.push({ path: url.pathname, method: response.request().method(), status: response.status(),
				body_fields: body && typeof body === 'object' ? Object.keys(body).slice(0, 12) : [],
				embed_present: Boolean(row), embed_id_matches_path: isEmbedRead
					? row?.embed_id === url.pathname.split('/').at(-1) : null,
				embed_status: row?.status ?? null, encryption_mode: row?.encryption_mode ?? null,
				ciphertext_length: typeof row?.encrypted_content === 'string' ? row.encrypted_content.length : 0,
				encrypted_type_present: typeof row?.encrypted_type === 'string',
				wrapper_types: wrappers.map((wrapper: any) => wrapper.key_type).sort(),
				wrapper_chat_scopes: wrappers.map((wrapper: any) => Boolean(wrapper.hashed_chat_id)),
				keys_has_more_after: body?.embed_keys_has_more_after === true || body?.has_more_after === true });
		} catch { /* Diagnostics cannot affect the product assertion. */ }
	});
	page.on('websocket', (socket: any) => {
		for (const [direction, event] of [['sent', 'framesent'], ['received', 'framereceived']] as const) {
			socket.on(event, (frame: any) => {
				try {
					const decoded = JSON.parse(String(frame.payload));
					if (typeof decoded.type === 'string') frames.push({ direction, type: decoded.type,
						payload: decoded.payload ?? {} });
				} catch { /* Ignore unrelated transport frames. */ }
			});
		}
	});
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'EMBED_BACKFILL');
		const closeSettings = page.getByTestId('icon-button-close');
		await expect(closeSettings).toBeVisible({ timeout: 5_000 });
		await closeSettings.click();
		await expect(page.locator('[data-testid="settings-menu"].visible')).not.toBeVisible({ timeout: 5_000 });
		seed = seedViaPairedCli(apiUrl, home);
		await page.goto(`${process.env.PLAYWRIGHT_TEST_BASE_URL}/#chat-id=${seed.chatId}`,
			{ waitUntil: 'domcontentloaded' });
		// The hash change stays in the paired document; reload after fixture receipts to sync its keys.
		await page.reload({ waitUntil: 'domcontentloaded' });
		const embed = await waitForEmbedFinished(page, 'web', 'search');
		expect(await embed.getAttribute('data-embed-id')).toBe(seed.embedId);
		await expect(embed.locator('.ds-search-query'), 'Browser must decrypt the parent search metadata')
			.toHaveText(QUERY, { timeout: 30_000 });
		const fullscreen = await openFullscreen(page, embed);
		await expect(fullscreen.getByTestId('search-template-grid')).toBeVisible({ timeout: 60_000 });
		await closeFullscreen(page, fullscreen);
		const fresh = () => frames.filter(frame => frame.direction === 'sent'
			&& frame.type === 'store_embed' && frame.payload.embed_id === seed!.embedId
			&& frame.payload.app_id === 'web' && frame.payload.skill_id === 'search'
			&& !frame.payload.parent_embed_id).at(-1);
		await expect.poll(() => Boolean(fresh()), { timeout: 30_000 }).toBe(true);
		const head = fresh()!.payload;
		expect(head).toMatchObject({ chat_id: seed.chatId, app_id: 'web', skill_id: 'search' });
		expect(head.hashed_chat_id).toMatch(/^[0-9a-f]{64}$/);
		expect(head.encrypted_content).toBeTruthy();
		await expect.poll(() => frames.some(frame => frame.direction === 'received'
			&& frame.type === 'store_embed_confirmed' && frame.payload.request_id === head.request_id
			&& frame.payload.embed_id === seed!.embedId), { timeout: 30_000 }).toBe(true);

		const legacyPayload = { ...head };
		for (const field of ['app_id', 'skill_id', 'chat_id', 'team_id', 'request_id']) delete legacyPayload[field];
		const operationId = randomUUID();
		const local = await queueLegacyOperation(page, seed.embedId, operationId, legacyPayload);
		expect(local).toEqual({ app_id: 'web', skill_id: 'search', hashed_chat_id: head.hashed_chat_id });
		const previous = new Set(frames.filter(frame => frame.direction === 'sent'
			&& frame.type === 'store_embed' && frame.payload.embed_id === seed!.embedId)
			.map(frame => frame.payload.request_id));
		await page.reload({ waitUntil: 'domcontentloaded' });
		const replay = () => frames.find(frame => frame.direction === 'sent'
			&& frame.type === 'store_embed' && frame.payload.embed_id === seed!.embedId
			&& !previous.has(frame.payload.request_id));
		await expect.poll(() => Boolean(replay()), { timeout: 60_000 }).toBe(true);
		expect(replay()!.payload).toMatchObject({ app_id: 'web', skill_id: 'search', chat_id: seed.chatId,
			hashed_chat_id: head.hashed_chat_id, encrypted_content: legacyPayload.encrypted_content });
		expect(replay()!.payload.team_id ?? null).toBeNull();
		const requestId = replay()!.payload.request_id;
		expect(requestId).toBeTruthy();
		await expect.poll(() => frames.some(frame => frame.direction === 'received'
			&& frame.type === 'store_embed_confirmed' && frame.payload.request_id === requestId
			&& frame.payload.embed_id === seed!.embedId), { timeout: 60_000 }).toBe(true);
		expect(frames.some(frame => frame.direction === 'received' && frame.type === 'error'
			&& frame.payload.request_id === requestId)).toBe(false);
		await expect.poll(() => page.evaluate(async (id: string) => {
			const db = await new Promise<IDBDatabase>((resolve, reject) => {
				const request = indexedDB.open('chats_db');
				request.onsuccess = () => resolve(request.result);
				request.onerror = () => reject(request.error);
			});
			try {
				return await new Promise<boolean>((resolve, reject) => {
					const request = db.transaction('pending_embed_operations', 'readonly')
						.objectStore('pending_embed_operations').get(id);
					request.onsuccess = () => resolve(request.result === undefined);
					request.onerror = () => reject(request.error);
				});
			} finally { db.close(); }
		}, operationId), { timeout: 30_000 }).toBe(true);
		await waitForEmbedFinished(page, 'web', 'search');
	} catch (error) {
		try {
			const selectedIds = new Set(seed ? [seed.embedId, seed.childId] : []);
			const selectedHashes = new Set([...selectedIds].map(id => createHash('sha256').update(id).digest('hex')));
			const websocket = frames.filter(frame => {
				if (frame.type === 'request_embed' || frame.type === 'send_embed_data' || frame.type === 'embed_update') {
					const payload = frame.payload.payload ?? frame.payload;
					return selectedIds.has(payload.embed_id);
				}
				return seed && (frame.type === 'phase_1b_chat_content_ready'
					|| frame.type === 'phase_2_last_20_chats_ready' || frame.type === 'background_message_sync');
			}).slice(-20).map(frame => {
				const payload = frame.payload.payload ?? frame.payload;
				const embeds = Array.isArray(payload.embeds) ? payload.embeds : [];
				const keys = Array.isArray(payload.embed_keys) ? payload.embed_keys : [];
				return { direction: frame.direction, type: frame.type, embed_id: payload.embed_id ?? null,
					status: payload.status ?? null, already_encrypted: payload.already_encrypted === true,
					ciphertext_length: typeof payload.content === 'string' ? payload.content.length : 0,
					matching_embeds: embeds.filter((row: any) => selectedIds.has(row.embed_id))
						.map((row: any) => ({ status: row.status, has_ciphertext: Boolean(row.encrypted_content) })),
					matching_wrapper_types: keys.filter((key: any) => selectedHashes.has(key.hashed_embed_id))
						.map((key: any) => key.key_type) };
			});
			const storage = seed ? await embedStorageSummary(page, seed)
				.catch((storageError: unknown) => ({ error_name: storageError instanceof Error
					? storageError.name : 'UnknownError' })) : [];
			await testInfo.attach('embed-hydration-metadata', { body: Buffer.from(JSON.stringify({
				embedReads, websocket, storage, browserSignals,
			}, null, 2)), contentType: 'application/json' });
		} catch { /* Keep the original failure and cleanup authoritative. */ }
		throw error;
	} finally {
		try {
			if (seed) {
				const deletion = await runWorkflowCli(apiUrl, home,
					['chats', 'delete', seed.chatId, '--yes'], 15_000);
				expect(deletion.code, `Paired CLI chat cleanup failed: ${deletion.stderr}`).toBe(0);
			}
		} finally { removeWorkflowCliHome(home); }
	}
});
