/* eslint-disable @typescript-eslint/no-require-imports */
/** Cold, noninteractive CLI sync must finish typed recovery discovery without inference. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { runCli } = require('./helpers/cli-test-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const {
	clearWorkflowCliSyncCache, createWorkflowCliHome, loginWorkflowCliViaPair,
	removeWorkflowCliHome, workflowApiUrl, workflowCliEnv
} = require('./helpers/workflow-cli-e2e-helpers');

const { email, password, otpKey } = getTestAccount();
const repositoryRoot = path.resolve(__dirname, '../../../..');
const isolatedCompose = path.join(repositoryRoot, 'test-results/ci-private/compose.json');

type CanonicalHistoryFixture = { chatId: string; ownerId: string; clientMessageId: string;
	chat: Record<string, unknown>; message: Record<string, unknown> };

function canonicalHistorySdk(apiUrl: string, home: string, program: string, input: unknown = {}): any {
	const cli = path.resolve(__dirname, '../../../packages/openmates-cli/dist/cli.js');
	expect(fs.existsSync(cli), 'Candidate CLI build is required').toBe(true);
	const source = `
		const {pathToFileURL}=require('node:url');
		const {randomUUID,randomBytes,createHash,webcrypto}=require('node:crypto');
		(async()=>{
			const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
			const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
			const input=JSON.parse(process.argv[2]);
			const hash=value=>createHash('sha256').update(value).digest('hex');
			const encrypt=async(value,key)=>{
				const iv=randomBytes(12),cryptoKey=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
				return Buffer.concat([iv,Buffer.from(await webcrypto.subtle.encrypt({name:'AES-GCM',iv},cryptoKey,Buffer.from(value)))]).toString('base64');
			};
			${program}
		})().catch(error=>{console.error('Canonical history fixture:',error.message);process.exit(1)});
	`;
	return JSON.parse(execFileSync('node', ['-e', source, path.join(path.dirname(cli), 'index.js'), JSON.stringify(input)], {
		cwd: repositoryRoot, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 90_000
	}).trim());
}

function persistCanonicalHistoryFixture(fixture: CanonicalHistoryFixture, operation: 'seed' | 'cleanup'): void {
	expect(fs.existsSync(isolatedCompose), 'Requires the disposable isolated CI compose').toBe(true);
	const program = `
import asyncio,hashlib,json,logging,os,sys
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED')=='1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.tasks.persistence_tasks import _chat_list_cache_data_from_metadata,_chat_versions_from_metadata
async def main():
    data=json.load(sys.stdin); cache=CacheService(); directus=DirectusService(cache_service=cache)
    owner=hashlib.sha256(data['ownerId'].encode()).hexdigest()
    assert data['chat']['hashed_user_id']==owner and data['message']['hashed_user_id']==owner
    try:
        if data['operation']=='seed':
            created,duplicate=await directus.chat.create_chat_in_directus(data['chat'])
            assert created and not duplicate, 'Encrypted chat seed failed'
            stored=await directus.chat.create_message_in_directus(data['message'])
            assert stored and stored.get('id'), 'Encrypted message seed failed'
            assert await cache.add_chat_to_ids_versions(data['ownerId'],data['chatId'],data['chat']['last_edited_overall_timestamp'])
            assert await cache.set_chat_list_item_data(data['ownerId'],data['chatId'],_chat_list_cache_data_from_metadata(data['chat']))
            assert await cache.set_chat_versions(data['ownerId'],data['chatId'],_chat_versions_from_metadata(data['chat']))
        else:
            metadata=await directus.chat.get_chat_metadata(data['chatId'])
            if metadata:
                assert metadata.get('hashed_user_id')==owner, 'Only fixture-owned chat may be removed'
                for raw in await directus.chat.get_all_messages_for_chat(data['chatId'],decrypt_content=False) or []:
                    message=json.loads(raw) if isinstance(raw,str) else raw
                    if message.get('client_message_id')==data['clientMessageId']:
                        assert await directus.delete_item('messages',message['id'],admin_required=True)
                assert await directus.delete_item('chats',data['chatId'],admin_required=True)
            await cache.remove_chat_from_ids_versions(data['ownerId'],data['chatId'])
        print('canonical history fixture applied')
    finally: await directus.close(); await cache.close()
asyncio.run(main())
`;
	const output = execFileSync('docker', ['compose', '-f', isolatedCompose, 'exec', '-T', '-e',
		'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program], {
		cwd: repositoryRoot, input: JSON.stringify({ ...fixture, operation }), encoding: 'utf8', timeout: 90_000
	});
	expect(output.trim()).toBe('canonical history fixture applied');
}

// contract-test: direct surface=cli assertions=chats.sync.key-gated-recovery,chats.completion.recovery-takeover
test('noninteractive cold chats list completes recovery discovery', async ({ page }: { page: any }, testInfo: any) => {
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e',
		'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('recovery-discovery');
	let draftChatId = '';
	const quietJson = async (args: string[]) => {
		const result = await runCli(apiUrl, [...args, '--json'], 60_000, {
			useApiKey: false, record: false, env: workflowCliEnv(apiUrl, home)
		});
		expect(result.code, `CLI fixture command failed: ${result.stderr}`).toBe(0);
		return JSON.parse(result.stdout);
	};
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_RECOVERY_DISCOVERY');
		const draft = await quietJson(['drafts', 'create', 'Cold recovery discovery fixture']);
		draftChatId = draft.chatId;
		expect(draft.encryptedDraftMd).not.toContain(draft.markdown);
		clearWorkflowCliSyncCache(home);

		// chats list has no --refresh flag: removing its cache forces a new WebSocket sync.
		installRecorderDeps();
		const result = await runCli(apiUrl, ['chats', 'list', '--limit', '100', '--json'], 120_000, {
			useApiKey: false,
			env: { ...workflowCliEnv(apiUrl, home), OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'cli-recovery-discovery' }
		});
		expect(result.code, `Cold CLI sync failed. stdout: ${result.stdout.slice(-2000)}\nstderr: ${result.stderr.slice(-2000)}`).toBe(0);
		const listed = JSON.parse(result.stdout);
		expect(listed.error).toBeUndefined();
		expect(Array.isArray(listed.chats)).toBe(true);
		expect(listed.chats.some((chat: { id: string }) => chat.id === draftChatId)).toBe(true);
		expect(result.recording?.videoPath).toBeTruthy();
		await testInfo.attach('cold-cli-recovery-discovery', {
			path: result.recording.videoPath, contentType: 'video/mp4'
		});
	} finally {
		if (draftChatId) await quietJson(['drafts', 'clear', draftChatId]).catch(() => undefined);
		removeWorkflowCliHome(home);
	}
});

// contract-test: direct surface=cli assertions=chats.sync.key-gated-recovery
test('saved Personal follow-up sends canonical client message IDs in inference history', async ({ page }: { page: any }) => {
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('canonical-history');
	let fixture: CanonicalHistoryFixture | undefined;
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_CANONICAL_HISTORY');
		const seeded: CanonicalHistoryFixture = canonicalHistorySdk(apiUrl, home, `
			const owner=await client.whoAmI();
			if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal account');
			const chatId=randomUUID(),clientMessageId=randomUUID(),key=randomBytes(32);
			const now=Math.floor(Date.now()/1000),hashedOwner=hash(owner.id);
			const chat={id:chatId,hashed_user_id:hashedOwner,created_at:now,updated_at:now,
				last_edited_overall_timestamp:now,last_message_timestamp:now,messages_v:1,title_v:1,metadata_v:1,
				unread_count:0,encrypted_chat_key:await encrypt(key,client.getMasterKeyBytes()),
				encrypted_title:await encrypt('Canonical history fixture',key),
				encrypted_chat_summary:await encrypt('One saved message.',key)};
			const message={id:clientMessageId,client_message_id:clientMessageId,message_id:clientMessageId,
				chat_id:chatId,hashed_user_id:hashedOwner,role:'user',created_at:now,updated_at:now,
				encrypted_sender_name:await encrypt('You',key),encrypted_content:await encrypt('Saved synthetic prompt.',key)};
			process.stdout.write(JSON.stringify({chatId,ownerId:owner.id,clientMessageId,chat,message}));
		`);
		fixture = seeded;
		persistCanonicalHistoryFixture(seeded, 'seed');
		clearWorkflowCliSyncCache(home);
		const observed = canonicalHistorySdk(apiUrl, home, `
			const {messages}=await client.getChatMessages(input.chatId,{personal:true});
			const saved=messages.find(message=>message.clientMessageId===input.clientMessageId);
			if(!saved)throw Error('Saved canonical message missing after sync');
			let historyIds=null;
			const open=client.openWsClient.bind(client);
			client.openWsClient=async (...args)=>{
				const result=await open(...args),send=result.ws.sendAsync.bind(result.ws);
				result.ws.sendAsync=async (type,payload)=>{
					if(type==='chat_turn_admit'){
						if(payload.inference_request?.client_context_pending!==undefined || payload.inference_request?.client_context_request_id!==undefined)
							throw Error('Existing chat admission must remain independent of continuation expiry');
						if(!Array.isArray(payload.inference_request?.project_context_documents))
							throw Error('Existing chat admission must include its fully collected context');
						historyIds=payload.inference_request?.message_history?.map(message=>message.message_id)??null;
						throw Error('EXPECTED_PRE_DISPATCH_STOP');
					}
					return send(type,payload);
				};
				return result;
			};
			try{await client.sendMessage({chatId:input.chatId,message:'Synthetic follow-up.',piiDetection:false});
				throw Error('Inference preflight was not captured');
			}catch(error){if(error.message!=='EXPECTED_PRE_DISPATCH_STOP')throw error;}
			process.stdout.write(JSON.stringify({storageId:saved.id,clientMessageId:saved.clientMessageId,historyIds}));
		`, { chatId: seeded.chatId, clientMessageId: seeded.clientMessageId });
		expect(observed.storageId).toBeTruthy();
		expect(observed.storageId).not.toBe(seeded.clientMessageId);
		expect(observed.clientMessageId).toBe(seeded.clientMessageId);
		expect(observed.historyIds).toContain(seeded.clientMessageId);
		expect(observed.historyIds).not.toContain(observed.storageId);
	} finally {
		if (fixture) persistCanonicalHistoryFixture(fixture, 'cleanup');
		removeWorkflowCliHome(home);
	}
});

// contract-test: supporting surface=rest_api assertions=chats.direction.context-assessment,plans.active-context.vault-boundary
test('SDK-minted new chat skips only impossible Focus and Plan discovery', async ({ page }: { page: any }) => {
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('fresh-context-discovery');
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_FRESH_CONTEXT_DISCOVERY');
		const observed = canonicalHistorySdk(apiUrl, home, `
			await client.whoAmI();
			if(client.getActiveTeamId())throw Error('Expected paired Personal account');
			let phase='minted';
			const result={minted:{focus:0,plans:0,projects:0,tasks:0,admission:null,routing:null,details:null},
				supplied:{focus:0,plans:0,projects:0,tasks:0,admission:null,routing:null,details:null}};
			for(const [method,field] of [['getActiveProjectFocus','focus'],['listUserPlans','plans'],
				['listProjects','projects'],['listUserTasks','tasks']]){
				const original=client[method].bind(client);
				client[method]=async(...args)=>{result[phase][field]++;return original(...args);};
			}
			const open=client.openWsClient.bind(client);
			client.openWsClient=async(...args)=>{
				const opened=await open(...args),send=opened.ws.sendAsync.bind(opened.ws);
				const wait=opened.ws.waitForMessage.bind(opened.ws);
				const waitForDiscovery=opened.ws.waitForRecoveryOutputDiscovery.bind(opened.ws);
				const currentPhase=phase;
				let discoveryCompleted=false,releaseMintedDiscovery;
				const mintedDiscoveryGate=new Promise(resolve=>{releaseMintedDiscovery=resolve;});
				opened.ws.waitForRecoveryOutputDiscovery=async()=>{
					await waitForDiscovery();
					if(currentPhase==='minted')await mintedDiscoveryGate;
					discoveryCompleted=true;
				};
				let capturedAdmission=null,resolveCapturedAck=null;
				// Observe real SDK envelopes after authorized discovery. Stub only the
				// admission ACK; no admission/context frame reaches inference here.
				opened.ws.waitForMessage=(type,...options)=>type==='chat_turn_preflight_ack'
					? new Promise(resolve=>{resolveCapturedAck=resolve;}) : wait(type,...options);
				const describeContext=context=>({
					projectCandidates:Array.isArray(context.project_focus_candidates),
					taskCandidates:Array.isArray(context.related_task_candidates),
					plan:context.accepted_plan_context!=null,
					memoryDocuments:(context.custom_memory_documents??[]).length,
					projectRules:(context.custom_rule_documents??[]).length,
					focusCatalog:(context.project_focus_catalog??[]).length,
					focusDocuments:(context.project_focus_documents??[]).length,
					projectDocuments:(context.project_context_documents??[]).length});
				opened.ws.sendAsync=async(type,payload)=>{
					if(type==='chat_turn_admit'){
						result[phase].selectionDetailsV2=currentPhase==='minted'
							&&opened.ws.supportsServerCapability('chat_turn_context_selection_details_v2')===true;
						capturedAdmission=payload;
						result[phase].admission={...describeContext(payload.inference_request??{}),
							contextPending:payload.inference_request?.client_context_pending===true,
							discoveryCompleted};
						if(currentPhase==='minted')releaseMintedDiscovery();
						if(!resolveCapturedAck)throw Error('Missing admission ACK observer');
						resolveCapturedAck({type:'chat_turn_preflight_ack',payload:{
							turn_id:payload.turn_id,preflight_id:'capture-only-no-dispatch'}});
						return;
					}
					if(type==='chat_turn_context_ready'){
						if(!capturedAdmission||!['routing','details'].includes(payload.phase))throw Error('Unordered context');
						const initial=capturedAdmission.inference_request;
						const identitiesMatch=payload.chat_id===capturedAdmission.chat_id
							&&payload.turn_id===capturedAdmission.turn_id&&payload.message_id===capturedAdmission.message_id
							&&payload.request_id===initial.client_context_request_id;
						result[phase][payload.phase]={...describeContext(payload.context??{}),identitiesMatch};
						if(payload.phase==='details')throw Error('EXPECTED_PRE_DISPATCH_STOP');
						return;
					}
					return send(type,payload);
				};
				return opened;
			};
			const suppliedContext={custom_rule_documents:[{id:'unowned-rule',source:'project',project_id:'unowned-project',document:'Unowned private rule'}],
				project_focus_catalog:[{id:'unowned-focus',title:'Unowned focus',summary:'Private',revision:'1'}],
				project_focus_documents:[{item_id:'unowned-focus',document:'Unowned private focus',revision:'1'}],
				project_context_documents:[{item_id:'unowned-file',kind:'spec',title:'Unowned file',description:'Private',document:'Unowned private content',revision:'1'}]};
			for(const current of ['minted','supplied']){
				phase=current;
				try{
					await client.sendMessage({message:'Ordinary context discovery check.',personal:true,piiDetection:false,
						jevContext:suppliedContext,...(current==='supplied'?{newChatId:randomUUID()}:{})});
					throw Error('Inference preflight was not captured');
				}catch(error){if(error.message!=='EXPECTED_PRE_DISPATCH_STOP')throw error;}
				if(!result[current].admission||!result[current].routing||!result[current].details)throw Error('Missing phased context observation');
			}
			process.stdout.write(JSON.stringify(result));
		`);
		expect(observed.minted.focus).toBe(0);
		expect(observed.minted.plans).toBe(0);
		expect(observed.minted.projects).toBeGreaterThan(0);
		expect(observed.minted.tasks).toBeGreaterThan(0);
		expect(observed.supplied.focus).toBe(2);
		expect(observed.supplied.plans).toBe(1);
		expect(observed.supplied.projects).toBeGreaterThan(0);
		expect(observed.supplied.tasks).toBeGreaterThan(0);
		expect(observed.minted.selectionDetailsV2).toBe(true);
		expect(observed.supplied.selectionDetailsV2).toBe(false);
		expect(observed.minted.admission.discoveryCompleted).toBe(false);
		expect(observed.supplied.admission.discoveryCompleted).toBe(true);
		for (const turn of [observed.minted, observed.supplied]) {
			expect(turn.admission.contextPending).toBe(true);
			expect(turn.admission.projectCandidates).toBe(false);
			expect(turn.admission.taskCandidates).toBe(false);
			expect(turn.routing.projectCandidates).toBe(true);
			expect(turn.routing.taskCandidates).toBe(!turn.selectionDetailsV2);
			expect(turn.details.taskCandidates).toBe(turn.selectionDetailsV2);
			expect(turn.routing.identitiesMatch).toBe(true);
			expect(turn.details.identitiesMatch).toBe(true);
			for (const context of [turn.admission, turn.routing, turn.details]) {
				expect(context.plan).toBe(false);
				expect(context.memoryDocuments).toBe(0);
				expect(context.projectRules).toBe(0);
				expect(context.focusCatalog).toBe(0);
				expect(context.focusDocuments).toBe(0);
				expect(context.projectDocuments).toBe(0);
			}
		}
	} finally {
		removeWorkflowCliHome(home);
	}
});

// contract-test: supporting surface=rest_api assertions=auth.session.lifecycle,auth.session.isolation,chats.completion.lease-fenced
test('Personal SDK send reuses only its fresh validated session receipt before preflight', async ({ page }: { page: any }) => {
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('personal-auth-handoff');
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_PERSONAL_AUTH_HANDOFF');
		const observed = canonicalHistorySdk(apiUrl, home, `
			if(client.getActiveTeamId())throw Error('Expected paired Personal account');
			const post=client.http.post.bind(client.http);
			let authCalls=0,preflights=0;
			client.http.post=async(...args)=>{if(args[0]==='/v1/auth/session')authCalls++;return post(...args);};
			const open=client.openWsClient.bind(client);
			client.openWsClient=async(...args)=>{
				const opened=await open(...args),send=opened.ws.sendAsync.bind(opened.ws);
				opened.ws.sendAsync=async(type,payload)=>{
					if(type==='chat_turn_admit'){preflights++;throw Error('EXPECTED_PRE_DISPATCH_STOP');}
					return send(type,payload);
				};
				return opened;
			};
			const counts=[];
			for(const mode of ['fresh','expired']){
				const snapshot=await client.listMemories({personal:true});
				if(mode==='expired')client.personalMemoryAuthHandoff.auth.validatedAt-=6000;
				try{
					await client.sendMessage({message:'Ordinary Personal auth boundary check.',personal:true,
						memorySnapshot:snapshot,piiDetection:false});
					throw Error('Inference preflight was not captured');
				}catch(error){if(error.message!=='EXPECTED_PRE_DISPATCH_STOP')throw error;}
				counts.push({authCalls,preflights});
			}
			process.stdout.write(JSON.stringify({counts}));
		`);
		expect(observed.counts).toEqual([{ authCalls: 1, preflights: 1 }, { authCalls: 3, preflights: 2 }]);
	} finally {
		removeWorkflowCliHome(home);
	}
});

// contract-test: direct surface=cli assertions=chats.send.immediate-admission,chats.persistence.client-encrypted,chats.message.identity-idempotent
test('warmed interactive TUI send borrows its authenticated socket for one encrypted admission', async ({ page }: { page: any }) => {
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('warm-interactive-admission');
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_WARM_INTERACTIVE_ADMISSION');
		const observed = canonicalHistorySdk(apiUrl, home, `
			const stdinTTY=Object.getOwnPropertyDescriptor(process.stdin,'isTTY');
			const stdoutTTY=Object.getOwnPropertyDescriptor(process.stdout,'isTTY');
			Object.defineProperty(process.stdin,'isTTY',{configurable:true,value:true});
			Object.defineProperty(process.stdout,'isTTY',{configurable:true,value:true});
			try{
				const owner=await client.whoAmI();
				if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal account');
				const memorySnapshot=await client.listMemories({personal:true});
				const newChatId=client.preparedNewChatId();
				let openCount=0,admissionCount=0,admissionSocket=null,admissionType=null,admission=null;
				const open=client.openWsClient.bind(client);
				client.openWsClient=async(...args)=>{
					const opened=await open(...args);openCount++;
					const send=opened.ws.sendAsync.bind(opened.ws);
					opened.ws.sendAsync=async(type,payload)=>{
						if(type==='chat_turn_admit'||type==='chat_turn_preflight'){
							admissionCount++;admissionSocket=opened.ws;admissionType=type;admission=payload;
							throw Error('EXPECTED_PRE_DISPATCH_STOP');
						}
						return send(type,payload);
					};
					return opened;
				};
				client.beginInteractiveViewerSession();
				client.warmChatMetadata();
				const prepared=client.preparedSendSocket;
				if(!prepared)throw Error('Interactive send socket was not prepared');
				await prepared.pending;
				if(!prepared.opened?.ownerId||!prepared.opened.ws.isOpen())throw Error('Authenticated warm socket is not ready');
				const warmedSocket=prepared.opened.ws;
				const opensAfterWarm=openCount;
				try{
					await client.sendMessage({message:'Ordinary warmed TUI admission check.',newChatId,
						personal:true,interactiveHuman:true,piiDetection:false,memorySnapshot});
					throw Error('Inference admission was not captured');
				}catch(error){if(error.message!=='EXPECTED_PRE_DISPATCH_STOP')throw error;}
				process.stdout.write(JSON.stringify({opensAfterWarm,openCount,admissionCount,admissionType,
					borrowed:admissionSocket===warmedSocket,ownerMatches:prepared.opened.ownerId===owner.id,
					chatIdMatches:admission?.chat_id===newChatId,
					turnId:admission?.turn_id,messageId:admission?.message_id,
					clientMessageIdMatches:admission?.encrypted_user_message?.client_message_id===admission?.message_id,
					metadataKeyMatches:admission?.encrypted_chat_metadata?.encrypted_chat_key===admission?.encrypted_chat_key,
					encryptedKey:typeof admission?.encrypted_chat_key==='string'&&admission.encrypted_chat_key.length>0,
					encryptedContent:typeof admission?.encrypted_user_message?.encrypted_content==='string'
						&&admission.encrypted_user_message.encrypted_content.length>0,
					expectedMessagesV:admission?.expected_messages_v}));
				client.endInteractiveViewerSession();
			}finally{
				if(stdinTTY)Object.defineProperty(process.stdin,'isTTY',stdinTTY);
				else delete process.stdin.isTTY;
				if(stdoutTTY)Object.defineProperty(process.stdout,'isTTY',stdoutTTY);
				else delete process.stdout.isTTY;
			}
		`);
		expect(observed.opensAfterWarm).toBe(1);
		expect(observed.openCount).toBe(1);
		expect(observed.admissionCount).toBe(1);
		expect(observed.admissionType).toBe('chat_turn_admit');
		expect(observed.borrowed).toBe(true);
		expect(observed.ownerMatches).toBe(true);
		expect(observed.chatIdMatches).toBe(true);
		expect(observed.turnId).toBeTruthy();
		expect(observed.messageId).toBeTruthy();
		expect(observed.clientMessageIdMatches).toBe(true);
		expect(observed.metadataKeyMatches).toBe(true);
		expect(observed.encryptedKey).toBe(true);
		expect(observed.encryptedContent).toBe(true);
		expect(observed.expectedMessagesV).toBe(0);
	} finally {
		removeWorkflowCliHome(home);
	}
});

// contract-test: direct surface=cli assertions=chats.send.immediate-admission,chats.persistence.client-encrypted,chats.message.identity-idempotent
test('SDK reports a Project directory failure after durable epoch-one first Personal admission', async ({ page }: { page: any }) => {
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('post-admission-context-failure');
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_POST_ADMISSION_CONTEXT_FAILURE');
		const observed = canonicalHistorySdk(apiUrl, home, `
			const owner=await client.whoAmI();
			if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal account');
			const memorySnapshot=await client.listMemories({personal:true});
			const newChatId=client.preparedNewChatId();
			const privateFailure='PRIVATE_PROJECT_DIRECTORY_RESPONSE_MUST_STAY_LOCAL';
			let rejectProjects,projectReads=0,admission=null,preflightAck=null,failure=null,failureAck=null;
			const rawOpen=client.openWsClient.bind(client);
			const observer=(await rawOpen({taskUpdateJobs:false})).ws;
			const terminal=observer.waitForMessage('ai_typing_ended',payload=>
				payload.chat_id===newChatId&&payload.user_message_id===admission?.message_id
				&&payload.terminal_failure_code==='client_context_unavailable',30000);
			void terminal.catch(()=>{});
			const projectGate=new Promise((_,reject)=>{rejectProjects=reject;});
			client.listProjects=async()=>{projectReads++;return projectGate;};
			const outbound=[];
			const open=client.openWsClient.bind(client);
			client.openWsClient=async(...args)=>{
				const opened=await open(...args),send=opened.ws.sendAsync.bind(opened.ws);
				opened.ws.onMessageType('chat_turn_preflight_ack',payload=>{preflightAck=payload;});
				opened.ws.onMessageType('chat_turn_context_failed_ack',payload=>{failureAck=payload;});
				opened.ws.sendAsync=async(type,payload)=>{
					if(['chat_turn_admit','chat_turn_context_ready','chat_turn_context_failed'].includes(type))outbound.push(type);
					if(type==='chat_turn_admit'){
						admission=payload;
						await send(type,payload);
						rejectProjects(Error(privateFailure));
						return;
					}
					if(type==='chat_turn_context_failed')failure=payload;
					return send(type,payload);
				};
				return opened;
			};
			let sendError=null;
			try{await client.sendMessage({message:'Ordinary post-admission context failure check.',
				newChatId,personal:true,piiDetection:false,memorySnapshot});}
			catch(error){sendError=error.message;}
			const beforeTerminal={
				admissionSent:outbound[0]==='chat_turn_admit',
				firstMetadataMatches:admission?.expected_messages_v===0
					&&admission?.encrypted_chat_metadata?.encrypted_chat_key===admission?.encrypted_chat_key,
				preflightState:preflightAck?.state??null,
				preflightVersion:preflightAck?.committed_messages_v??null,
				failureSent:outbound.includes('chat_turn_context_failed'),
				failureAckStatus:failureAck?.status??null,
				sendErrorIsPrivate:sendError===privateFailure,
				observerOpen:observer.isOpen(),
			};
			if(!beforeTerminal.admissionSent||!beforeTerminal.firstMetadataMatches
				||beforeTerminal.preflightState!=='ENQUEUED'||beforeTerminal.preflightVersion!==1
				||!beforeTerminal.failureSent||beforeTerminal.failureAckStatus!=='accepted'
				||!beforeTerminal.sendErrorIsPrivate){
				console.error('FIRST_PERSONAL_ADMISSION_DIAGNOSTIC',JSON.stringify(beforeTerminal));
				throw Error('First Personal admission or failure receipt did not satisfy epoch-one contract');
			}
			let terminalEvent;
			try{terminalEvent=(await terminal).payload;}
			catch(error){
				let activeTaskPresent=null,activityReadFailed=false;
				try{activeTaskPresent=(await client.getChatActivity({personal:true})).ids.includes(newChatId);}
				catch{activityReadFailed=true;}
				console.error('FIRST_PERSONAL_TERMINAL_DIAGNOSTIC',JSON.stringify({
					...beforeTerminal,observerOpenAfterWait:observer.isOpen(),
					activeTaskPresent,activityReadFailed,
				}));
				throw error;
			}
			const canonicalBefore=await client.getChatMessagesWindow(newChatId,{personal:true,limit:20,
				respectCompressionBoundary:false});
			const beforeIds=canonicalBefore.messages.map(message=>message.clientMessageId||message.id);
			const wrongWrapper={...admission,encrypted_chat_key:randomBytes(48).toString('base64')};
			const rejection=observer.waitForMessage('error',payload=>payload.turn_id===admission?.turn_id,10000);
			void rejection.catch(()=>{});
			await observer.sendAsync('chat_turn_admit',wrongWrapper);
			const rejected=(await rejection).payload;
			const canonicalAfter=await client.getChatMessagesWindow(newChatId,{personal:true,limit:20,
				respectCompressionBoundary:false});
			const afterIds=canonicalAfter.messages.map(message=>message.clientMessageId||message.id);
			const result={projectReads,outbound,sendErrorIsPrivate:sendError===privateFailure,
				chatIdMatches:admission?.chat_id===newChatId,
				epochOne:preflightAck?.state==='ENQUEUED'&&preflightAck?.committed_messages_v===1,
				outboxIdentity:['inference_task_id','billing_identity','outbox_id'].every(
					key=>typeof preflightAck?.[key]==='string'&&preflightAck[key].length>0),
				firstEncryptedMetadata:admission?.expected_messages_v===0
					&&admission?.encrypted_chat_metadata?.encrypted_chat_key===admission?.encrypted_chat_key,
				clientMessageIdMatches:admission?.encrypted_user_message?.client_message_id===admission?.message_id,
				canonicalSingleUser:beforeIds.length===1&&beforeIds[0]===admission?.message_id
					&&canonicalBefore.messages[0]?.role==='user',
				terminalMatches:terminalEvent?.task_id&&terminalEvent.task_id===terminalEvent.message_id,
				wrapperRejected:rejected?.code==='preflight_mismatch',
				wrapperReplayUnchanged:JSON.stringify(afterIds)===JSON.stringify(beforeIds)
					&&canonicalAfter.serverMessageCount===canonicalBefore.serverMessageCount,
				contextPending:admission?.inference_request?.client_context_pending===true,
				preflightAck:preflightAck?.turn_id===admission?.turn_id&&preflightAck?.preflight_id?.length>0,
				failureKeys:failure?Object.keys(failure).sort():null,
				failureReason:failure?.reason,
				failureMatches:failure?.chat_id===admission?.chat_id&&failure?.turn_id===admission?.turn_id
					&&failure?.message_id===admission?.message_id
					&&failure?.request_id===admission?.inference_request?.client_context_request_id,
				failureAckMatches:failureAck?.chat_id===failure?.chat_id&&failureAck?.turn_id===failure?.turn_id
					&&failureAck?.message_id===failure?.message_id&&failureAck?.request_id===failure?.request_id,
				failureAckStatus:failureAck?.status,
				encryptedUser:typeof admission?.encrypted_user_message?.encrypted_content==='string'
					&&admission.encrypted_user_message.encrypted_content.length>0};
			observer.close();
			if(preflightAck?.preflight_id)await client.deleteChat(newChatId,{personal:true});
			process.stdout.write(JSON.stringify(result));
		`);
		expect(observed.projectReads).toBeGreaterThan(0);
		expect(observed.outbound).toEqual(['chat_turn_admit', 'chat_turn_context_failed']);
		expect(observed.sendErrorIsPrivate).toBe(true);
		expect(observed.chatIdMatches).toBe(true);
		expect(observed.epochOne).toBe(true);
		expect(observed.outboxIdentity).toBe(true);
		expect(observed.firstEncryptedMetadata).toBe(true);
		expect(observed.clientMessageIdMatches).toBe(true);
		expect(observed.canonicalSingleUser).toBe(true);
		expect(observed.terminalMatches).toBe(true);
		expect(observed.wrapperRejected).toBe(true);
		expect(observed.wrapperReplayUnchanged).toBe(true);
		expect(observed.contextPending).toBe(true);
		expect(observed.preflightAck).toBe(true);
		expect(observed.failureKeys).toEqual(['chat_id', 'message_id', 'reason', 'request_id', 'turn_id']);
		expect(observed.failureReason).toBe('project_discovery_failed');
		expect(observed.failureMatches).toBe(true);
		expect(observed.failureAckMatches).toBe(true);
		expect(observed.failureAckStatus).toBe('accepted');
		expect(observed.encryptedUser).toBe(true);
	} finally {
		removeWorkflowCliHome(home);
	}
});

// contract-test: direct surface=rest_api assertions=chat-queued-followups.admission.synced,chat-queued-followups.editing.stable-revision,chats.persistence.client-encrypted
// Real isolated Postgres proof: no outbox is published to inference; the fixture marks only the active receipt DISPATCHED.
test('durable routing proof authorizes the exact active Personal turn across concurrent follower admission', async ({ page }: { page: any }) => {
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	expect(fs.existsSync(isolatedCompose), 'Requires the disposable isolated CI compose').toBe(true);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('routing-proof-postgres');
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_ROUTING_PROOF_POSTGRES');
		const owner = canonicalHistorySdk(apiUrl, home, `
			const owner=await client.whoAmI();
			if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal account');
			process.stdout.write(JSON.stringify({ownerId:owner.id}));
		`);
		const program = `
import asyncio,base64,hashlib,json,logging,os,sys,time,uuid
from datetime import datetime,timezone
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED')=='1'
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService,ChatRecoveryProtocolError
async def main():
    owner_id=json.load(sys.stdin)['ownerId']
    owner=hashlib.sha256(owner_id.encode()).hexdigest()
    chat_id=str(uuid.uuid4()); turn_id=str(uuid.uuid4()); active_message=str(uuid.uuid4())
    active_task=str(uuid.uuid4()); active_outbox=str(uuid.uuid4()); billing=str(uuid.uuid4())
    follower_turn=str(uuid.uuid4()); follower_message=str(uuid.uuid4())
    follower_task=str(uuid.uuid4()); follower_outbox=str(uuid.uuid4())
    device='isolated-routing-proof-device'; wrapped='opaque-wrapped-key'; now=int(time.time())
    recovery_key=base64.urlsafe_b64encode(bytes([7])*32).rstrip(b'=').decode()
    cipher=lambda value: base64.b64encode(value.encode()).decode()
    message=lambda message_id,content: {'client_message_id':message_id,'chat_id':chat_id,
        'hashed_user_id':owner,'encrypted_content':cipher(content),'role':'user','created_at':now,'updated_at':now}
    active_commitment=hashlib.sha256(b'isolated-active-commitment').hexdigest()
    follower_commitment=hashlib.sha256(b'isolated-follower-commitment').hexdigest()
    directus=DirectusService(); recovery=ChatRecoveryService(directus)
    async def execute(operation,data): return await recovery.execute(operation,{'protocol_version':1,**data})
    async def rows(collection):
        result=await directus.get_items(collection,params={'filter':{'chat_id':{'_eq':chat_id}},'limit':-1},no_cache=True)
        assert isinstance(result,list), collection+' read unavailable'
        return result
    async def verify():
        try: return (await execute('verify_routing_admission',routing))['authorized']
        except ChatRecoveryProtocolError as error:
            if error.code in ('chat_not_found','account_recovery_fenced'): return False
            raise
    try:
        prepared=await execute('prepare_preflight',{'hashed_user_id':owner,'chat_id':chat_id,'turn_id':turn_id,
            'user_message_id':active_message,'device_hash':device,'chat_key_version':1,
            'wrapped_chat_key':wrapped,'recovery_public_key':recovery_key,
            'inference_commitment':active_commitment,'commitment_version':1,'expected_messages_v':0,
            'encrypted_user_message':message(active_message,'active-ciphertext'),
            'encrypted_chat_metadata':{'encrypted_title':cipher('title'),'encrypted_chat_key':wrapped,
                'created_at':now,'updated_at':now}})
        active_preflight=prepared['preflight_id']
        queued=await execute('enqueue_inference',{'preflight_id':active_preflight,'hashed_user_id':owner,
            'device_hash':device,'inference_commitment':active_commitment,'inference_task_id':active_task,
            'billing_identity':billing,'outbox_id':active_outbox})
        assert queued['state']=='ENQUEUED'
        proof=await rows('chat_routing_proofs')
        assert len(proof)==1 and proof[0]['preflight_id']==active_preflight and proof[0]['messages_v']==1
        # No PENDING outbox or inference queue publication: Directus admin sets this
        # disposable receipt to an already-dispatched state for routing verification.
        assert await directus.update_item('chat_inference_outbox',active_outbox,
            {'state':'DISPATCHED'},admin_required=True)
        routing={'preflight_id':active_preflight,'inference_task_id':active_task,'hashed_user_id':owner,
            'hashed_team_id':None,'chat_id':chat_id,'message_id':active_message,'turn_id':turn_id}
        assert await verify() is True
        verification_started=asyncio.Event()
        async def first_verify():
            verification_started.set()
            return await verify()
        async def verify_during_follower():
            first=asyncio.create_task(first_verify())
            samples=[await first]
            for _ in range(3): samples.append(await verify())
            return samples
        async def durable_follower():
            await verification_started.wait()
            follower=await execute('prepare_preflight',{'hashed_user_id':owner,'chat_id':chat_id,
                'turn_id':follower_turn,'user_message_id':follower_message,'device_hash':device,
                'chat_key_version':1,'wrapped_chat_key':wrapped,'recovery_public_key':recovery_key,
                'inference_commitment':follower_commitment,'commitment_version':1,
                'expected_messages_v':1,'encrypted_user_message':message(follower_message,'follower-ciphertext'),
                'queued_after_task_id':active_task})
            follower_preflight=follower['preflight_id']
            await execute('enqueue_inference',{'preflight_id':follower_preflight,'hashed_user_id':owner,
                'device_hash':device,'inference_commitment':follower_commitment,'inference_task_id':follower_task,
                'billing_identity':str(uuid.uuid4()),'outbox_id':follower_outbox})
            marker=await execute('mark_queued_message_pending',{'chat_id':chat_id,'message_id':follower_message,
                'hashed_user_id':owner,'hashed_team_id':None,'queue_revision':1,'queue_mode':'follow_up',
                'recovery_preflight_id':follower_preflight,'recovery_task_id':follower_task})
            assert marker['status']=='queued'
            return follower_preflight
        samples,follower_preflight=await asyncio.wait_for(asyncio.gather(
            verify_during_follower(),durable_follower()),timeout=35)
        assert len(samples)==4 and all(type(value) is bool for value in samples)
        proof=await rows('chat_routing_proofs')
        assert len(proof)==1 and proof[0]['preflight_id']==active_preflight
        assert proof[0]['inference_task_id']==active_task and proof[0]['messages_v']==3
        assert follower_preflight!=active_preflight and await verify() is True
        message_rows=[row for row in await rows('messages') if row.get('client_message_id')==active_message]
        assert len(message_rows)==1
        original=message_rows[0]; message_row_id=original['id']
        assert await directus.update_item('messages',message_row_id,
            {'encrypted_content':cipher('tampered-active')},admin_required=True)
        assert await verify() is False
        assert await directus.update_item('messages',message_row_id,
            {'encrypted_content':original['encrypted_content']},admin_required=True)
        assert await verify() is True
        assert await directus.update_item('messages',message_row_id,
            {'updated_at':original['updated_at']+1},admin_required=True)
        assert await verify() is False
        assert await directus.update_item('messages',message_row_id,
            {'updated_at':original['updated_at']},admin_required=True)
        assert await verify() is True
        assert await directus.update_item('chats',chat_id,
            {'hashed_user_id':hashlib.sha256(uuid.uuid4().bytes).hexdigest()},admin_required=True)
        assert await verify() is False
        assert await directus.update_item('chats',chat_id,{'hashed_user_id':owner},admin_required=True)
        assert await verify() is True
        fence={'id':chat_id,'chat_id':chat_id,'hashed_user_id':owner,'hashed_team_id':None,
            'fenced_at':datetime.now(timezone.utc).isoformat()}
        created,_=await directus.create_item('chat_recovery_chat_deletion_fences',fence,admin_required=True)
        assert created and await verify() is False
        print(json.dumps({'concurrent_verifications':len(samples),'proof_version':proof[0]['messages_v'],
            'exact_active_authorized':True,'cipher_revision_owner_deletion_rejected':True}))
    finally:
        for collection in ('chat_recovery_chat_deletion_fences','chat_routing_proofs',
            'chat_inference_outbox','chat_turn_preflights','messages'):
            for row in await rows(collection):
                assert await directus.delete_item(collection,row.get('id') or row['chat_id'],admin_required=True)
        chats=await directus.get_items('chats',params={'filter':{'id':{'_eq':chat_id}},'limit':1},no_cache=True)
        for row in chats or []: assert await directus.delete_item('chats',row['id'],admin_required=True)
        await directus.close()
asyncio.run(main())
`;
		const result = JSON.parse(execFileSync('docker', ['compose', '-f', isolatedCompose, 'exec', '-T', '-e',
			'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program], {
			cwd: repositoryRoot, input: JSON.stringify(owner), encoding: 'utf8', timeout: 90_000
		}).trim());
		expect(result.concurrent_verifications).toBe(4);
		expect(result.proof_version).toBe(3);
		expect(result.exact_active_authorized).toBe(true);
		expect(result.cipher_revision_owner_deletion_rejected).toBe(true);
	} finally {
		removeWorkflowCliHome(home);
	}
});
