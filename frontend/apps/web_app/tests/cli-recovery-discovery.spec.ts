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
					if(type==='chat_turn_preflight'){
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
