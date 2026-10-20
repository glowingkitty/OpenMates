/* eslint-disable @typescript-eslint/no-require-imports */
/** Two remaining current-protocol cases; the complete recovery suite stays registered. */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { runCli } = require('./helpers/cli-test-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');
const { observeRecoveryFrames, focusRecoveryPage, requireForegroundRecoveryLifecycle } = require('./storage-recovery-fixtures');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { clearWorkflowCliSyncCache, createWorkflowCliHome, loginWorkflowCliViaPair,
  removeWorkflowCliHome, workflowApiUrl, workflowCliEnv } = require('./helpers/workflow-cli-e2e-helpers');
const { email, password, otpKey } = getTestAccount();
const repositoryRoot = path.resolve(__dirname, '../../../..');
const isolatedCompose = path.join(repositoryRoot, 'test-results/ci-private/compose.json');

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

function sealedParentDependencyFixtureProgram(): string {
	return `
import asyncio,base64,hashlib,json,logging,os,sys
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED')=='1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.tasks.persistence_tasks import _chat_list_cache_data_from_metadata,_chat_versions_from_metadata
from backend.shared.python_utils.chat_completion_recovery import derive_recovery_keypair,seal_recovery_output
async def main():
    data=json.load(sys.stdin); cache=CacheService(); directus=DirectusService(cache_service=cache)
    owner=hashlib.sha256(data['ownerId'].encode()).hexdigest()
    assert data['chat']['hashed_user_id']==owner and data['message']['hashed_user_id']==owner
    try:
        if data['operation']=='seed':
            created,duplicate=await directus.chat.create_chat_in_directus(data['chat']); assert created and not duplicate
            assert await directus.chat.create_message_in_directus(data['message'])
            child=data['childEmbed']; assert child['hashed_user_id']==owner and child['hashed_chat_id']==hashlib.sha256(data['chatId'].encode()).hexdigest()
            if not data.get('omitCanonicalHead'):
                created,_=await directus.create_item('embeds',child,admin_required=True); assert created
            for wrapper in data.get('keyWrappers',[]):
                assert wrapper['hashed_user_id']==owner and wrapper['hashed_embed_id']==child['hashed_embed_id']
                created,_=await directus.create_item('embed_keys',wrapper,admin_required=True); assert created
            _,public=derive_recovery_keypair(data['fixtureChatKey'],data['chatId'],1)
            for output,content in zip(data['outputs'],data['sealedContents']):
                assert output['hashed_user_id']==owner and output['root_chat_id']==data['chatId'] and output['target_chat_id']==data['chatId']
                plaintext=json.dumps({'record_id':output['id'],'target_chat_id':data['chatId'],'subject_id':output['subject_id'],
                    'output_kind':'embed','output_version':1,'content':content},sort_keys=True,separators=(',',':')).encode()
                envelope=seal_recovery_output(plaintext,recovery_public_key=public,owner_id=data['ownerId'],
                    root_chat_id=data['chatId'],target_chat_id=data['chatId'],turn_id=output['turn_id'],record_id=output['id'],
                    subject_id=output['subject_id'],output_kind='embed',output_version=1,key_version=1)
                sealed=json.dumps(envelope,sort_keys=True,separators=(',',':'))
                row={**output,'sealed_payload':sealed,'sealed_payload_digest':hashlib.sha256(sealed.encode()).hexdigest(),
                    'payload_storage':'inline','payload_size_bytes':len(sealed.encode())}
                created,_=await directus.create_item('chat_recovery_outputs',row,admin_required=True); assert created
            assert await cache.add_chat_to_ids_versions(data['ownerId'],data['chatId'],data['chat']['last_edited_overall_timestamp'])
            assert await cache.set_chat_list_item_data(data['ownerId'],data['chatId'],_chat_list_cache_data_from_metadata(data['chat']))
            assert await cache.set_chat_versions(data['ownerId'],data['chatId'],_chat_versions_from_metadata(data['chat']))
        elif data['operation']=='inspect':
            embed=data['childEmbed']
            heads=await directus.get_items('embeds',params={'filter':{'embed_id':{'_eq':embed['embed_id']}},'limit':2},no_cache=True,admin_required=True)
            keys=await directus.get_items('embed_keys',params={'filter':{'hashed_embed_id':{'_eq':embed['hashed_embed_id']}},'limit':10},no_cache=True,admin_required=True)
            outputs=await directus.get_items('chat_recovery_outputs',params={'filter':{'id':{'_in':[row['id'] for row in data['outputs']]}},'limit':3},no_cache=True,admin_required=True)
            assert all(row['hashed_user_id']==owner for row in heads+keys+outputs)
            expected={row['id']:row['encrypted_embed_key'] for row in data.get('keyWrappers',[])}
            print(json.dumps({'headPresent':len(heads)==1,'headUnchanged':len(heads)==1 and all(heads[0].get(field)==embed.get(field) for field in ('id','encrypted_content','encrypted_type','hashed_user_id','hashed_chat_id','hashed_message_id','version_number')),
                'wrapperCount':len(keys),'wrapperIdsUnchanged':set(expected)=={row['id'] for row in keys},
                'wrapperCiphertextsUnchanged':all(expected.get(row['id'])==row['encrypted_embed_key'] for row in keys) and len(keys)==len(expected),
                'states':[row['state'] for row in outputs]}))
            return
        else:
            metadata=await directus.chat.get_chat_metadata(data['chatId'])
            if metadata:
                assert metadata.get('hashed_user_id')==owner
                for output in data['outputs']:
                    rows=await directus.get_items('chat_recovery_outputs',params={'filter':{'id':{'_eq':output['id']}},'limit':2},no_cache=True,admin_required=True)
                    if rows:
                        assert len(rows)==1 and rows[0]['hashed_user_id']==owner and rows[0]['root_chat_id']==data['chatId']
                        assert await directus.delete_item('chat_recovery_outputs',output['id'],admin_required=True)
                for embed_id in (data['parentId'],data['childEmbed']['embed_id']):
                    rows=await directus.get_items('embeds',params={'filter':{'embed_id':{'_eq':embed_id}},'limit':2},no_cache=True,admin_required=True)
                    for row in rows:
                        assert row['hashed_user_id']==owner and row['hashed_chat_id']==hashlib.sha256(data['chatId'].encode()).hexdigest()
                        assert await directus.delete_item('embeds',row['id'],admin_required=True)
                    keys=await directus.get_items('embed_keys',params={'filter':{'hashed_embed_id':{'_eq':hashlib.sha256(embed_id.encode()).hexdigest()}},'limit':10},no_cache=True,admin_required=True)
                    for key in keys:
                        assert key['hashed_user_id']==owner
                        assert await directus.delete_item('embed_keys',key['id'],admin_required=True)
                for raw in await directus.chat.get_all_messages_for_chat(data['chatId'],decrypt_content=False) or []:
                    message=json.loads(raw) if isinstance(raw,str) else raw
                    assert message.get('chat_id')==data['chatId']
                    if message.get('client_message_id')==data['message']['client_message_id']:
                        assert await directus.delete_item('messages',message['id'],admin_required=True)
                assert await directus.delete_item('chats',data['chatId'],admin_required=True)
            await cache.remove_chat_from_ids_versions(data['ownerId'],data['chatId'])
        print('sealed parent dependency fixture applied')
    finally: await directus.close(); await cache.close()
asyncio.run(main())
`;
}


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


// contract-test: direct surface=cli assertions=chats.sync.key-gated-recovery,chats.completion.recovery-takeover,chats.persistence.client-encrypted
test('sealed child discovery recovers a later parent across pages without rewriting the orphan head', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	skipWithoutCredentials(test, email, password, otpKey);
	if (process.env.OPENMATES_CI_ISOLATED !== '1') test.skip(true, 'Synthetic sealed output seed requires isolated CI');
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('sealed-parent-order');
	let fixture: any;
	let primaryFailed = false;
	const cleanupErrors: unknown[] = [];
	const apply = (operation: string) => {
		const output = execFileSync('docker', ['compose', '-f', isolatedCompose, 'exec', '-T', '-e',
			'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', sealedParentDependencyFixtureProgram()], {
			cwd: repositoryRoot, input: JSON.stringify({ ...fixture, operation }), encoding: 'utf8', timeout: 90_000
		});
		expect(output.trim()).toBe('sealed parent dependency fixture applied');
	};
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_SEALED_PARENT_ORDER');
		fixture = canonicalHistorySdk(apiUrl, home, `
			const owner=await client.whoAmI();if(!owner.id)throw Error('Owner identity unavailable');
			const chatId=randomUUID(),messageId=randomUUID(),parentId=randomUUID(),childId=randomUUID(),turnId=randomUUID(),key=randomBytes(32);
			const now=Math.floor(Date.now()/1000),date=new Date().toISOString(),ownerHash=hash(owner.id);
			const chat={id:chatId,hashed_user_id:ownerHash,created_at:now,updated_at:now,last_edited_overall_timestamp:now,
				last_message_timestamp:now,messages_v:1,title_v:1,metadata_v:1,unread_count:0,
				encrypted_chat_key:await encrypt(key,client.getMasterKeyBytes()),encrypted_title:await encrypt('Sealed parent recovery',key)};
			const message={id:messageId,client_message_id:messageId,message_id:messageId,chat_id:chatId,hashed_user_id:ownerHash,
				role:'user',created_at:now,updated_at:now,encrypted_sender_name:await encrypt('You',key),encrypted_content:await encrypt('Recovery fixture.',key)};
			const hkdf=await webcrypto.subtle.importKey('raw',key,'HKDF',false,['deriveBits']);
			const embedKey=Buffer.from(await webcrypto.subtle.deriveBits({name:'HKDF',hash:'SHA-256',salt:Buffer.from('openmates-embed-key-v1'),info:Buffer.from(parentId)},hkdf,256));
			const childSource='type: website\\nurl: https://example.test/parent-recovery';
			const childEmbed={id:randomUUID(),embed_id:childId,hashed_embed_id:hash(childId),hashed_chat_id:hash(chatId),
				hashed_message_id:hash(messageId),hashed_user_id:ownerHash,parent_embed_id:parentId,version_number:1,status:'finished',
				encryption_mode:'client',encrypted_content:await encrypt(childSource,embedKey),encrypted_type:await encrypt('website',embedKey),created_at:now,updated_at:now};
			const base={hashed_user_id:ownerHash,root_chat_id:chatId,target_chat_id:chatId,root_hashed_team_id:null,turn_id:turnId,
				preflight_id:randomUUID(),inference_task_id:randomUUID(),output_kind:'embed',message_role:null,output_version:1,chat_key_version:1,state:'PENDING'};
			const outputs=[{...base,id:randomUUID(),subject_id:childId,created_at:date},
				{...base,id:randomUUID(),subject_id:parentId,created_at:new Date(Date.now()+1).toISOString()}];
			const sealedContents=[{embed_id:childId,parent_embed_id:parentId,version_number:1,type:'website',content:childSource,message_id:messageId},
				{embed_id:parentId,parent_embed_id:null,version_number:1,type:'app_skill_use',content:'type: app_skill_use\\napp_id: web\\nskill_id: search',embed_ids:[childId],message_id:messageId}];
			process.stdout.write(JSON.stringify({ownerId:owner.id,chatId,parentId,chat,message,childEmbed,outputs,sealedContents,fixtureChatKey:key.toString('base64url')}));
		`);
		apply('seed');
		clearWorkflowCliSyncCache(home);
		const observed = canonicalHistorySdk(apiUrl, home, `
			const frames=[],recordIds=new Set(input.fixture.outputs.map(row=>row.id));let inferenceRequests=0,fixtureSplit=false;
			const open=client.openWsClient.bind(client);
			client.openWsClient=async(...args)=>{
				const result=await open(...args),send=result.ws.sendAsync.bind(result.ws),drain=result.ws.drainAvailableRecoveryOutputPages.bind(result.ws);
				result.ws.sendAsync=async(type,payload)=>{if(['chat_turn_admit','new_chat','chat_message'].includes(type))inferenceRequests++;
					if(recordIds.has(payload.record_id)||recordIds.has(payload.recovery_record_id))frames.push({type,id:payload.record_id||payload.recovery_record_id,embedId:payload.embed_id});return send(type,payload)};
				result.ws.drainAvailableRecoveryOutputPages=(...args)=>{
					const pages=drain(...args),fixtureRows=pages.flat().filter(row=>recordIds.has(row.record_id));
					if(fixtureSplit&&fixtureRows.length===0)return pages;
					if(fixtureRows.length!==2)throw Error('Both pending sealed outputs must be discovered');
					fixtureSplit=true;
					const child=fixtureRows.find(row=>row.subject_id===input.fixture.childEmbed.embed_id),parent=fixtureRows.find(row=>row.subject_id===input.fixture.parentId);
					return [[child],[parent],...pages.map(rows=>rows.filter(row=>!recordIds.has(row.record_id)))];
				};return result;
			};
			const childPath='/v1/embeds/chats/'+input.fixture.chatId+'/embeds/'+input.fixture.childEmbed.embed_id;
			const before=await client.http.get(childPath,client.getCliRequestHeaders());
			const result=await client.listChats(100,1,{forceRefresh:true});
			const childAfter=await client.http.get(childPath,client.getCliRequestHeaders());
			const parentAfter=await client.http.get('/v1/embeds/chats/'+input.fixture.chatId+'/embeds/'+input.fixture.parentId,client.getCliRequestHeaders());
			process.stdout.write(JSON.stringify({beforeStatus:before.status,childReadable:childAfter.ok,parentReadable:parentAfter.ok,
				orphanCipherUnchanged:childAfter.data?.embed?.encrypted_content===input.fixture.childEmbed.encrypted_content,
				storeIds:frames.filter(row=>row.type==='store_embed').map(row=>row.embedId),
				ackIds:frames.filter(row=>row.type==='recovery_output_ack_embed').map(row=>row.id),inferenceRequests}));
		`, { fixture });
		await testInfo.attach('cli-sealed-parent-order', { body: JSON.stringify(observed), contentType: 'application/json' });
		expect(observed).toEqual({ beforeStatus: 404, childReadable: true, parentReadable: true,
			orphanCipherUnchanged: true, storeIds: [fixture.parentId],
			ackIds: [fixture.outputs[1].id, fixture.outputs[0].id], inferenceRequests: 0 });
		installRecorderDeps();
		const result = await runCli(apiUrl, ['chats', 'list', '--limit', '100', '--json'], 120_000, {
			useApiKey: false, env: { ...workflowCliEnv(apiUrl, home), OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'cli-sealed-parent-order' }
		});
		expect(result.code).toBe(0);
		await testInfo.attach('cli-sealed-parent-order-recording', { path: result.recording.videoPath, contentType: 'video/mp4' });
	} catch (error) {
		primaryFailed = true;
		throw error;
	} finally {
		try { if (fixture) apply('delete'); } catch (error) { cleanupErrors.push(error); }
		try { removeWorkflowCliHome(home); } catch (error) { cleanupErrors.push(error); }
		if (cleanupErrors.length) {
			await testInfo.attach('cli-sealed-parent-cleanup-errors', { body: JSON.stringify({
				primaryFailurePreserved: primaryFailed,
				errors: cleanupErrors.map(error => ({ name: error instanceof Error ? error.name : 'UnknownError',
					message: error instanceof Error ? error.message : String(error) }))
			}), contentType: 'application/json' }).catch(() => {});
		}
	}
	if (cleanupErrors.length) throw cleanupErrors[0];
});


for (const mode of ['equivalent', 'conflicting', 'initial'] as const) {
	// contract-test: direct surface=gui.web assertions=chats.sync.key-gated-recovery,chats.completion.recovery-takeover,chats.persistence.client-encrypted
	test(`browser sealed recovery preserves ${mode} canonical wrapper records`, async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(240_000);
		skipWithoutCredentials(test, email, password, otpKey);
		test.skip(process.env.OPENMATES_CI_ISOLATED !== '1', 'Synthetic encrypted records require isolated CI');
		const apiUrl = workflowApiUrl(), home = createWorkflowCliHome(`browser-wrapper-${mode}`);
		let fixture: any;
		const frames = observeRecoveryFrames(page, true);
		const recoveryErrors: string[] = [];
		page.on('console', (message: any) => {
			const value = message.text();
			if (value.includes('[ChatSyncService:Recovery] Output recovery failed:')) recoveryErrors.push(value);
		});
		const apply = (operation: string): any => {
			const output = execFileSync('docker', ['compose', '-f', isolatedCompose, 'exec', '-T', '-e',
				'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', sealedParentDependencyFixtureProgram()], {
				cwd: repositoryRoot, input: JSON.stringify({ ...fixture, operation }), encoding: 'utf8', timeout: 90_000
			}).trim();
			if (operation === 'inspect') return JSON.parse(output);
			expect(output).toBe('sealed parent dependency fixture applied');
		};
		let primaryFailed = false;
		let cleanupFailure: AggregateError | undefined;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, home, `BROWSER_WRAPPERS_${mode.toUpperCase()}`);
			// Close the originating connection before seeding. Only the restored
			// real browser may discover and acknowledge this synthetic output.
			await page.goto('about:blank');
			fixture = canonicalHistorySdk(apiUrl, home, `
				const owner=await client.whoAmI();if(!owner.id||client.getActiveTeamId())throw Error('Personal owner required');
				const chatId=randomUUID(),messageId=randomUUID(),embedId=randomUUID(),key=randomBytes(32),turnId=randomUUID();
				const ownerHash=hash(owner.id),now=Math.floor(Date.now()/1000),date=new Date().toISOString();
				const chat={id:chatId,hashed_user_id:ownerHash,created_at:now,updated_at:now,last_edited_overall_timestamp:now,
					last_message_timestamp:now,messages_v:1,title_v:1,metadata_v:1,unread_count:0,
					encrypted_chat_key:await encrypt(key,client.getMasterKeyBytes()),encrypted_title:await encrypt('Canonical wrapper recovery',key)};
				const message={id:messageId,client_message_id:messageId,message_id:messageId,chat_id:chatId,hashed_user_id:ownerHash,
					role:'user',created_at:now,updated_at:now,encrypted_sender_name:await encrypt('You',key),
					encrypted_content:await encrypt('Wrapper recovery fixture.',key)};
				const hkdf=await webcrypto.subtle.importKey('raw',key,'HKDF',false,['deriveBits']);
				const embedKey=Buffer.from(await webcrypto.subtle.deriveBits({name:'HKDF',hash:'SHA-256',salt:Buffer.from('openmates-embed-key-v1'),info:Buffer.from(embedId)},hkdf,256));
				const content='type: website\\nurl: https://example.test/preserved-wrapper';
				const childEmbed={id:randomUUID(),embed_id:embedId,hashed_embed_id:hash(embedId),hashed_chat_id:hash(chatId),
					hashed_message_id:hash(messageId),hashed_user_id:ownerHash,version_number:1,status:'finished',encryption_mode:'client',
					encrypted_content:await encrypt(content,embedKey),encrypted_type:await encrypt('website',embedKey),created_at:now,updated_at:now};
				const keyWrappers=[];
				if(input.mode!=='initial')for(const kind of ['master','chat'])for(let duplicate=0;duplicate<2;duplicate++){
					const wrappingKey=kind==='master'?client.getMasterKeyBytes():key;
					const keyToWrap=input.mode==='conflicting'&&kind==='chat'&&duplicate===1?randomBytes(32):embedKey;
					keyWrappers.push({id:randomUUID(),hashed_embed_id:hash(embedId),hashed_user_id:ownerHash,key_type:kind,
						hashed_chat_id:kind==='chat'?hash(chatId):null,encrypted_embed_key:await encrypt(keyToWrap,wrappingKey),created_at:now});
				}
				const outputs=[{id:randomUUID(),hashed_user_id:ownerHash,root_chat_id:chatId,target_chat_id:chatId,root_hashed_team_id:null,
					turn_id:turnId,preflight_id:randomUUID(),inference_task_id:randomUUID(),output_kind:'embed',message_role:null,
					output_version:1,chat_key_version:1,state:'PENDING',subject_id:embedId,created_at:date}];
				const sealedContents=[{embed_id:embedId,chat_id:chatId,parent_embed_id:null,version_number:1,type:'website',content,message_id:messageId}];
				process.stdout.write(JSON.stringify({ownerId:owner.id,chatId,parentId:randomUUID(),chat,message,childEmbed,outputs,sealedContents,
					keyWrappers,omitCanonicalHead:input.mode==='initial',fixtureChatKey:key.toString('base64url')}));
			`, { mode });
			apply('seed');
			frames.length = 0;
			await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(fixture.chatId)}`));
			await focusRecoveryPage(page);
			await requireForegroundRecoveryLifecycle(frames);
			const recordId = fixture.outputs[0].id;
			const scoped = () => frames.filter((frame: any) => frame.payload.record_id === recordId
				|| frame.payload.recovery_record_id === recordId || frame.payload.embed_id === fixture.childEmbed.embed_id
				|| frame.payload.keys?.some((key: any) => key.hashed_embed_id === fixture.childEmbed.hashed_embed_id));
			await expect.poll(() => scoped().some((frame: any) => frame.direction === 'received'
				&& frame.type === 'recovery_output_ready'), { timeout: 90_000 }).toBe(true);
			if (mode === 'conflicting') {
				await expect.poll(() => recoveryErrors.some(value => value.includes('wrapper did not open to the expected key')),
					{ timeout: 60_000 }).toBe(true);
				expect(scoped().some((frame: any) => frame.type === 'recovery_output_ack_embed')).toBe(false);
			} else {
				await expect.poll(() => scoped().some((frame: any) => frame.direction === 'received'
					&& frame.type === 'recovery_output_embed_acknowledged' && frame.payload.state === 'ACKNOWLEDGED'),
				{ timeout: 90_000 }).toBe(true);
			}
			const stored = apply('inspect');
			expect(stored.states).toEqual([mode === 'conflicting' ? 'PENDING' : 'ACKNOWLEDGED']);
			const writes = scoped().filter((frame: any) => frame.direction === 'sent'
				&& ['store_embed', 'store_embed_keys'].includes(frame.type));
			if (mode === 'initial') {
				expect(writes.map((frame: any) => frame.type)).toEqual(['store_embed']);
				expect(writes[0].payload.recovery_key_wrappers).toHaveLength(2);
				expect(writes[0].payload.recovery_message_id).toBe(fixture.message.client_message_id);
				expect(stored).toMatchObject({ headPresent: true, wrapperCount: 2 });
			} else {
				expect(writes).toEqual([]);
				expect(stored).toMatchObject({ headUnchanged: true, wrapperCount: 4,
					wrapperIdsUnchanged: true, wrapperCiphertextsUnchanged: true });
			}
			expect(frames.some((frame: any) => frame.direction === 'sent' && frame.payload.chat_id === fixture.chatId
				&& ['chat_turn_admit', 'new_chat', 'chat_message'].includes(frame.type))).toBe(false);
			await expect(page.locator('[data-authenticated="true"]')).toBeVisible();
			await page.screenshot({ path: testInfo.outputPath(`canonical-wrappers-${mode}.png`), fullPage: true });
			await testInfo.attach(`canonical-wrappers-${mode}`, { body: JSON.stringify({ mode, ...stored,
				writeTypes: writes.map((frame: any) => frame.type) }), contentType: 'application/json' });
		} catch (error) {
			primaryFailed = true;
			throw error;
		} finally {
			const cleanupErrors: unknown[] = [];
			try { await page.goto('about:blank'); } catch (error) { cleanupErrors.push(error); }
			try { if (fixture) apply('delete'); } catch (error) { cleanupErrors.push(error); }
			try { removeWorkflowCliHome(home); } catch (error) { cleanupErrors.push(error); }
			if (cleanupErrors.length) {
				await testInfo.attach('wrapper-fixture-cleanup-errors', { body: JSON.stringify({ primaryFailed,
					errors: cleanupErrors.map(error => error instanceof Error ? error.message : String(error)) }), contentType: 'application/json' });
				if (!primaryFailed) cleanupFailure = new AggregateError(cleanupErrors, 'Encrypted wrapper fixture cleanup failed');
			}
		}
		if (cleanupFailure) throw cleanupFailure;
	});
}
