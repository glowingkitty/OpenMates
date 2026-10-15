/* eslint-disable @typescript-eslint/no-require-imports */
/** Cold, noninteractive CLI sync must finish typed recovery discovery without inference. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { runCli } = require('./helpers/cli-test-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');
const { execFileSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const {
	clearWorkflowCliSyncCache, createWorkflowCliHome, loginWorkflowCliViaPair,
	removeWorkflowCliHome, workflowApiUrl, workflowCliEnv
} = require('./helpers/workflow-cli-e2e-helpers');

const { email, password, otpKey } = getTestAccount();
const repositoryRoot = path.resolve(__dirname, '../../../..');
const isolatedCompose = path.join(repositoryRoot, 'test-results/ci-private/compose.json');

/** Read or remove a private proof only through the disposable CI PostgreSQL service. */
function isolatedProofSql(chatId: string, operation: 'read' | 'delete'): unknown {
	if (process.env.OPENMATES_CI_ISOLATED !== '1' || !fs.existsSync(isolatedCompose)) {
		throw new Error('Routing proof SQL requires the disposable isolated CI database');
	}
	if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(chatId)) {
		throw new Error('Routing proof SQL requires a canonical UUID');
	}
	const sql = operation === 'read'
		? "SELECT COALESCE(json_agg(row_to_json(proof)), '[]'::json)::text FROM (SELECT chat_id, preflight_id, inference_task_id, messages_v, message_digest FROM public.chat_routing_proofs WHERE chat_id = :'chat_id'::uuid) AS proof;"
		: "WITH deleted AS (DELETE FROM public.chat_routing_proofs WHERE chat_id = :'chat_id'::uuid RETURNING 1) SELECT count(*) FROM deleted;";
	const output = execFileSync('docker', ['compose', '-f', isolatedCompose, 'exec', '-T', 'cms-database',
		'sh', '-ec', 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -X -q -A -t -v ON_ERROR_STOP=1 -v chat_id="$1" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -',
		'sh', chatId], { cwd: repositoryRoot, input: sql, encoding: 'utf8', timeout: 30_000 }).trim();
	return operation === 'read' ? JSON.parse(output) : Number(output) === 1;
}

/** Let the API fixture request proof-only SQL without granting Directus collection access. */
async function runIsolatedProofFixture(program: string, owner: unknown, testInfo: any): Promise<any> {
	if (process.env.OPENMATES_CI_ISOLATED !== '1' || !fs.existsSync(isolatedCompose)) {
		throw new Error('Routing proof fixture requires the disposable isolated CI stack');
	}
	const stderrPath = testInfo.outputPath('routing-proof-fixture-stderr.private.log');
	let stderrFd = fs.openSync(stderrPath, 'w', 0o600);
	try {
	return await new Promise((resolve, reject) => {
		const child = spawn('docker', ['compose', '-f', isolatedCompose, 'exec', '-T', '-e',
			'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program],
			{ cwd: repositoryRoot, stdio: ['pipe', 'pipe', 'pipe'] });
		let stdout = '', stderrTail = '', stderrBytes = 0, result: any = null, settled = false;
		let sqlFailureOperation = '', sqlFailureCategory = '';
		const finish = (error?: Error) => {
			if (settled) return;
			settled = true;
			clearTimeout(timeout);
			if (stderrFd >= 0) { fs.closeSync(stderrFd); stderrFd = -1; }
			if (error) reject(error); else resolve(result);
		};
		const timeout = setTimeout(() => { child.kill(); finish(new Error('Isolated routing proof fixture timed out')); }, 90_000);
		child.stdin.write(JSON.stringify(owner) + '\n');
		child.stdout.setEncoding('utf8');
		child.stdout.on('data', (chunk: string) => {
			stdout += chunk;
			let newline = stdout.indexOf('\n');
			while (newline >= 0) {
				const line = stdout.slice(0, newline).trim();
				stdout = stdout.slice(newline + 1);
				if (line.startsWith('OPENMATES_PROOF_SQL_REQUEST:')) {
					let operation = 'parse_request';
					try {
						const request = JSON.parse(line.slice('OPENMATES_PROOF_SQL_REQUEST:'.length));
						operation = request.operation;
						if (operation !== 'read' && operation !== 'delete') throw new Error('Invalid proof SQL operation');
						child.stdin.write(JSON.stringify({ value: isolatedProofSql(request.chatId, operation) }) + '\n');
					} catch (error) {
						sqlFailureOperation = operation;
						const sqlStderr = (error as any)?.stderr;
						if (stderrFd >= 0 && sqlStderr) fs.writeSync(stderrFd, Buffer.isBuffer(sqlStderr) ? sqlStderr : String(sqlStderr));
						const detail = String(sqlStderr || '').toLowerCase();
						sqlFailureCategory = detail.includes('syntax error') ? 'sql_syntax'
							: detail.includes('does not exist') ? 'missing_relation'
							: detail.includes('permission denied') ? 'sql_permission'
							: detail.includes('authentication failed') ? 'sql_auth'
							: error instanceof Error ? error.name : 'UnknownError';
						child.stdin.write(JSON.stringify({ error: sqlFailureCategory }) + '\n');
					}
				} else if (line.startsWith('OPENMATES_PROOF_FIXTURE_RESULT:')) {
					try { result = JSON.parse(line.slice('OPENMATES_PROOF_FIXTURE_RESULT:'.length)); }
					catch { finish(new Error('Invalid routing proof fixture result')); }
				}
				newline = stdout.indexOf('\n');
			}
		});
		child.stderr.on('data', (chunk: Buffer) => {
			stderrBytes += chunk.length;
			if (stderrFd >= 0) fs.writeSync(stderrFd, chunk);
			stderrTail = (stderrTail + chunk.toString('utf8')).slice(-4096);
		});
		child.on('error', (error: Error) => finish(error));
		child.on('close', (code: number) => {
			if (code !== 0 || result === null) {
				const frames = [...stderrTail.matchAll(/File "<string>", line (\d+), in ([a-zA-Z_]+)/g)];
				const frame = frames.at(-1);
				const categories = [...stderrTail.matchAll(/(?:^|\n)([A-Za-z_]+(?:Error|Exception))(?=:|$)/g)];
				const category = categories.at(-1)?.[1] || 'UnknownError';
				finish(new Error('Routing proof fixture failed (exit ' + code + ', stderr bytes ' + stderrBytes
					+ ', python ' + category + ' at ' + (frame ? frame[2] + ':' + frame[1] : 'unknown')
					+ ', sql operation ' + (sqlFailureOperation || 'none') + ', sql category ' + (sqlFailureCategory || 'none') + ')'));
			} else finish();
		});
	});
	} catch (error) {
		await testInfo.attach('routing-proof-fixture-stderr-private', {
			path: stderrPath, contentType: 'text/plain'
		});
		throw error;
	}
}


type CanonicalHistoryFixture = { chatId: string; ownerId: string; clientMessageId: string;
	chat: Record<string, unknown>; message: Record<string, unknown>;
	embed?: Record<string, unknown>; embedKeys?: Array<Record<string, unknown>>;
	outputs?: Array<Record<string, unknown>>; staleOutputs?: Array<Record<string, unknown>>;
	childEmbed?: Record<string, unknown>; childOutput?: Record<string, unknown>; childStaleOutput?: Record<string, unknown> };

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

function canonicalHistoryFixtureProgram(): string {
	return `
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
            if data.get('embed'):
                assert data['embed']['hashed_user_id']==owner
                created,_=await directus.create_item('embeds',data['embed'],admin_required=True)
                assert created, 'Encrypted recovery embed seed failed'
                for key in data.get('embedKeys',[]):
                    assert key['hashed_user_id']==owner
                    created,_=await directus.create_item('embed_keys',key,admin_required=True)
                    assert created, 'Encrypted recovery key seed failed'
                if data.get('childEmbed'):
                    child=data['childEmbed']
                    assert child['hashed_user_id']==owner and child['hashed_chat_id']==data['embed']['hashed_chat_id']
                    assert child['parent_embed_id']==data['embed']['embed_id']
                    created,_=await directus.create_item('embeds',child,admin_required=True)
                    assert created, 'Encrypted child seed failed'
                fixture_outputs=[*data.get('outputs',[]),*([data['childOutput']] if data.get('childOutput') else [])]
                for output in fixture_outputs:
                    assert output['hashed_user_id']==owner and output['root_chat_id']==data['chatId']
                    assert output['target_chat_id']==data['chatId'] and output['subject_id'] in [data['embed']['embed_id'],data.get('childEmbed',{}).get('embed_id')]
                    created,_=await directus.create_item('chat_recovery_outputs',output,admin_required=True)
                    assert created, 'Acknowledged recovery output seed failed'
            assert await cache.add_chat_to_ids_versions(data['ownerId'],data['chatId'],data['chat']['last_edited_overall_timestamp'])
            assert await cache.set_chat_list_item_data(data['ownerId'],data['chatId'],_chat_list_cache_data_from_metadata(data['chat']))
            assert await cache.set_chat_versions(data['ownerId'],data['chatId'],_chat_versions_from_metadata(data['chat']))
        elif data['operation'] in ('keys-unavailable','keys-ready'):
            metadata=await directus.chat.get_chat_metadata(data['chatId'])
            assert metadata and metadata['hashed_user_id']==owner
            for key in data.get('embedKeys',[]):
                assert key['hashed_user_id']==owner and key['hashed_embed_id']==data['embed']['hashed_embed_id']
                rows=await directus.get_items('embed_keys',params={'filter':{'id':{'_eq':key['id']}},'limit':2},no_cache=True,admin_required=True)
                assert len(rows)<=1
                if data['operation']=='keys-unavailable':
                    assert rows and all(rows[0].get(field)==key.get(field) for field in ('hashed_user_id','hashed_embed_id','hashed_chat_id','key_type','encrypted_embed_key'))
                    assert await directus.delete_item('embed_keys',key['id'],admin_required=True)
                else:
                    assert not rows
                    created,_=await directus.create_item('embed_keys',key,admin_required=True)
                    assert created
        else:
            metadata=await directus.chat.get_chat_metadata(data['chatId'])
            if metadata:
                assert metadata.get('hashed_user_id')==owner, 'Only fixture-owned chat may be removed'
                for output in [*data.get('outputs',[]),*([data['childOutput']] if data.get('childOutput') else [])]:
                    rows=await directus.get_items('chat_recovery_outputs',params={'filter':{'id':{'_eq':output['id']}},'limit':1},no_cache=True,admin_required=True)
                    if rows:
                        assert rows[0]['hashed_user_id']==owner
                        assert await directus.delete_item('chat_recovery_outputs',output['id'],admin_required=True)
                for key in data.get('embedKeys',[]):
                    rows=await directus.get_items('embed_keys',params={'filter':{'id':{'_eq':key['id']}},'limit':1},no_cache=True,admin_required=True)
                    if rows:
                        assert rows[0]['hashed_user_id']==owner
                        assert await directus.delete_item('embed_keys',key['id'],admin_required=True)
                if data.get('childEmbed'):
                    rows=await directus.get_items('embeds',params={'filter':{'id':{'_eq':data['childEmbed']['id']}},'limit':1},no_cache=True,admin_required=True)
                    if rows:
                        assert rows[0]['hashed_user_id']==owner and rows[0]['parent_embed_id']==data['embed']['embed_id']
                        assert await directus.delete_item('embeds',data['childEmbed']['id'],admin_required=True)
                if data.get('embed'):
                    rows=await directus.get_items('embeds',params={'filter':{'id':{'_eq':data['embed']['id']}},'limit':1},no_cache=True,admin_required=True)
                    if rows:
                        assert rows[0]['hashed_user_id']==owner
                        assert await directus.delete_item('embeds',data['embed']['id'],admin_required=True)
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
}

function persistCanonicalHistoryFixture(fixture: CanonicalHistoryFixture,
	operation: 'seed' | 'cleanup' | 'keys-unavailable' | 'keys-ready'): void {
	expect(fs.existsSync(isolatedCompose), 'Requires the disposable isolated CI compose').toBe(true);
	const program = canonicalHistoryFixtureProgram();
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

// contract-test: direct surface=cli assertions=chats.sync.key-gated-recovery,chats.completion.recovery-takeover,chats.persistence.client-encrypted
test('stale CLI embed discovery reconciles only a verified canonical ACK', async ({ page }: { page: any }, testInfo: any) => {
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('stale-recovery-ack');
	let fixture: CanonicalHistoryFixture | undefined;
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_STALE_RECOVERY_ACK');
		fixture = canonicalHistorySdk(apiUrl, home, `
			const owner=await client.whoAmI();
			if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal account');
			const chatId=randomUUID(),clientMessageId=randomUUID(),embedId=randomUUID(),key=randomBytes(32);
			const now=Math.floor(Date.now()/1000),date=new Date().toISOString(),hashedOwner=hash(owner.id);
			const chat={id:chatId,hashed_user_id:hashedOwner,created_at:now,updated_at:now,
				last_edited_overall_timestamp:now,last_message_timestamp:now,messages_v:1,title_v:1,metadata_v:1,
				unread_count:0,encrypted_chat_key:await encrypt(key,client.getMasterKeyBytes()),
				encrypted_title:await encrypt('Stale recovery fixture',key),encrypted_chat_summary:await encrypt('Saved fixture.',key)};
			const message={id:clientMessageId,client_message_id:clientMessageId,message_id:clientMessageId,
				chat_id:chatId,hashed_user_id:hashedOwner,role:'user',created_at:now,updated_at:now,
				encrypted_sender_name:await encrypt('You',key),encrypted_content:await encrypt('Saved fixture prompt.',key)};
			const hkdf=await webcrypto.subtle.importKey('raw',key,'HKDF',false,['deriveBits']);
			const embedKey=Buffer.from(await webcrypto.subtle.deriveBits({name:'HKDF',hash:'SHA-256',
				salt:Buffer.from('openmates-embed-key-v1'),info:Buffer.from(embedId)},hkdf,256));
			const encryptedContent=await encrypt('type: code\\ncode: verified recovery fixture',embedKey);
			const embed={id:randomUUID(),embed_id:embedId,hashed_embed_id:hash(embedId),
				hashed_chat_id:hash(chatId),hashed_message_id:hash(clientMessageId),hashed_user_id:hashedOwner,
				encrypted_content:encryptedContent,encrypted_type:await encrypt('code',embedKey),
				status:'finished',version_number:1,encryption_mode:'client',is_private:false,is_shared:false,
				created_at:now,updated_at:now};
			const embedKeys=[{id:randomUUID(),hashed_embed_id:hash(embedId),key_type:'master',
				hashed_chat_id:null,encrypted_embed_key:await encrypt(embedKey,client.getMasterKeyBytes()),
				hashed_user_id:hashedOwner,created_at:now},{id:randomUUID(),hashed_embed_id:hash(embedId),
				key_type:'chat',hashed_chat_id:hash(chatId),encrypted_embed_key:await encrypt(embedKey,key),
				hashed_user_id:hashedOwner,created_at:now}];
			const canonicalDigest=hash(encryptedContent);
			const outputs=['verified','tampered'].map((kind)=>({id:randomUUID(),hashed_user_id:hashedOwner,
				root_chat_id:chatId,root_hashed_team_id:null,target_chat_id:chatId,turn_id:randomUUID(),
				preflight_id:randomUUID(),inference_task_id:randomUUID(),subject_id:embedId,
				output_kind:'embed',message_role:null,output_version:1,chat_key_version:1,
				sealed_payload:null,sealed_payload_digest:hash('fixture-'+kind),payload_storage:'inline',
				payload_size_bytes:1,state:'ACKNOWLEDGED',created_at:date,acknowledged_at:date,
				canonical_digest:kind==='verified'?canonicalDigest:'0'.repeat(64)}));
			const staleOutputs=outputs.map(output=>({record_id:output.id,root_chat_id:output.root_chat_id,
				root_hashed_team_id:null,target_chat_id:output.target_chat_id,turn_id:output.turn_id,
				subject_id:embedId,output_kind:'embed',output_version:1,chat_key_version:1,message_role:null}));
			const childId=randomUUID();
			const childContent=await encrypt('type: code\\ncode: child source readiness fixture',embedKey);
			const childEmbed={...embed,id:randomUUID(),embed_id:childId,hashed_embed_id:hash(childId),
				parent_embed_id:embedId,encrypted_content:childContent};
			const childOutput={...outputs[0],id:randomUUID(),subject_id:childId,canonical_digest:hash(childContent)};
			const childStaleOutput={...staleOutputs[0],record_id:childOutput.id,subject_id:childId};
			process.stdout.write(JSON.stringify({chatId,ownerId:owner.id,clientMessageId,chat,message,
				embed,embedKeys,outputs,staleOutputs,childEmbed,childOutput,childStaleOutput}));
		`);
		persistCanonicalHistoryFixture(fixture, 'seed');
		const guardedHead = canonicalHistorySdk(apiUrl, home, `
			await client.whoAmI();
			const {ws}=await client.openWsClient();
			try {
				const requestId=randomUUID(),now=Math.floor(Date.now()/1000);
				const attempted=ws.waitForMessage('store_embed_confirmed',payload=>payload?.request_id===requestId,10_000);
				void attempted.catch(()=>{});
				await ws.sendAsync('store_embed',{request_id:requestId,chat_id:input.chatId,
					embed_id:input.embed.embed_id,hashed_user_id:input.embed.hashed_user_id,
					hashed_chat_id:input.embed.hashed_chat_id,hashed_message_id:input.embed.hashed_message_id,
					encrypted_content:await encrypt('reciphered recovery head',randomBytes(32)),
					encrypted_type:input.embed.encrypted_type,status:'finished',version_number:1,
					is_private:false,is_shared:false,created_at:now,updated_at:now});
				let rewriteError=null;
				try{await attempted;}catch(error){rewriteError=error?.code??null;}
				const statusRequestId=randomUUID();
				const status=ws.waitForMessage('recovery_output_status_ready',payload=>
					payload?.request_id===statusRequestId,10_000);
				void status.catch(()=>{});
				await ws.sendAsync('recovery_output_status',{protocol_version:1,
					record_id:input.verifiedRecordId,request_id:statusRequestId});
				const result=(await status).payload;
				process.stdout.write(JSON.stringify({rewriteError,state:result.state,
					canonicalVerified:result.canonical_verified}));
			} finally {ws.close();}
		`, { chatId: fixture.chatId, embed: fixture.embed,
			verifiedRecordId: fixture.outputs![0].id });
		expect(guardedHead).toEqual({ rewriteError: 'embed_write_denied',
			state: 'ACKNOWLEDGED', canonicalVerified: true });
		clearWorkflowCliSyncCache(home);
		const streamedReplay = canonicalHistorySdk(apiUrl, home, `
			await client.whoAmI();
			const wrapped=Buffer.from(input.chat.encrypted_chat_key,'base64');
			const master=await webcrypto.subtle.importKey('raw',client.getMasterKeyBytes(),'AES-GCM',false,['decrypt']);
			const chatKey=new Uint8Array(await webcrypto.subtle.decrypt({name:'AES-GCM',iv:wrapped.subarray(0,12)},master,wrapped.subarray(12)));
			const target='/v1/embeds/chats/'+input.chatId+'/embeds/'+input.embed.embed_id;
			const read=()=>client.http.get(target,client.getCliRequestHeaders());
			const before=await read();
			if(!before.ok||!before.data?.embed||!before.data?.embed_keys)throw Error('Canonical fixture read failed');
			const wrappers=value=>value.embed_keys.map(row=>hash(JSON.stringify(row))).sort();
			const {ws}=await client.openWsClient({taskUpdateJobs:false});
			const frames=[],send=ws.sendAsync.bind(ws);
			ws.sendAsync=async(type,payload)=>{frames.push(type);return send(type,payload)};
			const replay=source=>client.persistStreamedEmbeds({ws,chatId:input.chatId,ownerId:input.ownerId,
				chatKeyBytes:chatKey,fallbackMessageId:input.clientMessageId,embeds:[{
					embed_id:input.embed.embed_id,type:'code',content:source,status:'finished',version_number:1,
					message_id:input.clientMessageId,task_id:input.outputs[0].inference_task_id,
					file_path:'src/recovered.ts',content_hash:hash('verified recovery fixture'),embed_ids:[]}]});
			try {
				await replay('type: code\\ncode: verified recovery fixture');
				let changedRejected=false;
				try{await replay('type: code\\ncode: changed source');}
				catch(error){changedRejected=/does not match streamed source/.test(error.message)};
				const enriched=await read();
				if(!enriched.ok)throw Error('Enriched fixture reread failed');
				const enrichmentRejects=[];
				for(const conflict of ['version','cipher','metadata']){
					const requestId=randomUUID();
					const receipt=ws.waitForMessage('store_embed_confirmed',payload=>payload?.request_id===requestId,10000);
					void receipt.catch(()=>{});
					await ws.sendAsync('store_embed',{request_id:requestId,embed_id:input.embed.embed_id,
						chat_id:input.chatId,hashed_user_id:input.embed.hashed_user_id,
						hashed_chat_id:input.embed.hashed_chat_id,hashed_message_id:input.embed.hashed_message_id,
						hashed_task_id:conflict==='metadata'?hash('different producer'):hash(input.outputs[0].inference_task_id),
						canonical_metadata_enrichment:{expected_version:conflict==='version'?2:1,
							expected_ciphertext_sha256:conflict==='cipher'?'0'.repeat(64):hash(input.embed.encrypted_content)}});
					try{await receipt;enrichmentRejects.push(null)}catch(error){enrichmentRejects.push(error?.code??null)}
				}
				const after=await read();
				if(!after.ok)throw Error('Canonical fixture reread failed');
				process.stdout.write(JSON.stringify({changedRejected,enrichmentRejects,
					producerTaskPreserved:after.data.embed.hashed_task_id===hash(input.outputs[0].inference_task_id),
					fileMetadataPreserved:after.data.embed.file_path==='src/recovered.ts'
						&&after.data.embed.content_hash===hash('verified recovery fixture'),
					cipherUnchanged:before.data.embed.encrypted_content===after.data.embed.encrypted_content,
					versionUnchanged:before.data.embed.version_number===after.data.embed.version_number,
					wrappersUnchanged:JSON.stringify(wrappers(before.data))===JSON.stringify(wrappers(after.data)),
					storeAttempts:frames.filter(type=>type==='store_embed').length,
					wrapperWrites:frames.filter(type=>type==='store_embed_keys').length,
					newAcknowledgements:frames.filter(type=>type==='recovery_output_ack_embed').length}));
			} finally {ws.close()}
		`, fixture);
		expect(streamedReplay).toEqual({ changedRejected: true,
			enrichmentRejects: ['embed_write_denied', 'embed_write_denied', 'embed_write_denied'],
			producerTaskPreserved: true, fileMetadataPreserved: true, cipherUnchanged: true,
			versionUnchanged: true, wrappersUnchanged: true, storeAttempts: 6,
			wrapperWrites: 0, newAcknowledgements: 0 });
		clearWorkflowCliSyncCache(home);
		const observed = canonicalHistorySdk(apiUrl, home, `
			await client.whoAmI();
			const requests=[],statuses=[],accepted=[],rejected=[];
			let discoveryPasses=0;
			const replay=client.replayAvailableRecoveryOutputs.bind(client);
			client.replayAvailableRecoveryOutputs=async (...args)=>{
				const id=args[2][0]?.record_id;
				try{const count=await replay(...args);if(input.staleOutputs.some(row=>row.record_id===id))accepted.push(id);return count;}
				catch(error){if(input.staleOutputs.some(row=>row.record_id===id))rejected.push(id);throw error;}
			};
			const open=client.openWsClient.bind(client);
			client.openWsClient=async (...args)=>{
				const result=await open(...args),ws=result.ws;
				const drain=ws.drainAvailableRecoveryOutputPages.bind(ws);
				ws.drainAvailableRecoveryOutputPages=(rootChatId)=>{
					const pages=drain(rootChatId);
					// Simulate the same stale discovery on the mandatory post-ACK
					// metadata refresh. A third pass would be an empty recovery loop.
					discoveryPasses++;
					pages.push(input.staleOutputs);
					return pages;
				};
				const send=ws.sendAsync.bind(ws);
				ws.sendAsync=async (type,payload)=>{
					if(type==='recovery_output_get'||type==='recovery_output_status')
						requests.push({type,record_id:payload.record_id});
					return send(type,payload);
				};
				ws.onMessageType('recovery_output_status_ready',payload=>{
					if(input.staleOutputs.some(row=>row.record_id===payload.record_id))
						statuses.push({record_id:payload.record_id,state:payload.state,verified:payload.canonical_verified});
				});
				return result;
			};
			const listed=await client.listChats(100,1,{forceRefresh:true});
			process.stdout.write(JSON.stringify({listed:listed.chats.some(chat=>chat.id===input.chatId),
				discoveryPasses,requests,statuses,accepted,rejected}));
		`, { chatId: fixture.chatId, staleOutputs: fixture.staleOutputs });
		expect(observed.listed).toBe(true);
		expect(observed.discoveryPasses, 'one post-ACK metadata refresh, then return').toBe(2);
		const [verified, tampered] = fixture.staleOutputs!;
		const fixtureIds = new Set([verified.record_id, tampered.record_id]);
		expect(observed.requests.filter((row: any) => row.type === 'recovery_output_get')
			.filter((row: any) => fixtureIds.has(row.record_id))
			.map((row: any) => row.record_id)).toEqual([verified.record_id, tampered.record_id]);
		expect(observed.requests.filter((row: any) => row.type === 'recovery_output_status')
			.filter((row: any) => fixtureIds.has(row.record_id))
			.map((row: any) => row.record_id)).toEqual([verified.record_id, tampered.record_id]);
		expect(observed.statuses).toEqual([
			{ record_id: verified.record_id, state: 'ACKNOWLEDGED', verified: true },
			{ record_id: tampered.record_id, state: 'ACKNOWLEDGED', verified: false }
		]);
		expect(observed.accepted).toEqual([verified.record_id]);
		expect(observed.rejected).toEqual([tampered.record_id]);


		// A child uses only its verified same-source parent's wrappers. Remove
		// and restore those exact fixture-owned rows through the isolated protocol.
		persistCanonicalHistoryFixture(fixture, 'keys-unavailable');
		clearWorkflowCliSyncCache(home);
		const parentReadiness = canonicalHistorySdk(apiUrl, home, `
			await client.whoAmI();
			let clock=Date.now(); const actualNow=Date.now; Date.now=()=>clock;
			const leaf=client.replayAvailableRecoveryOutputs.bind(client),attempts=[];let childAccepted=0,inferenceRequests=0;
			client.replayAvailableRecoveryOutputs=async(...args)=>{
				if(args[2][0]?.record_id===input.fixture.childStaleOutput.record_id)attempts.push('child');
				const count=await leaf(...args);if(args[2][0]?.record_id===input.fixture.childStaleOutput.record_id&&count>0)childAccepted++;return count;
			};
			const open=client.openWsClient.bind(client);
			client.openWsClient=async(...args)=>{
				const result=await open(...args),drain=result.ws.drainAvailableRecoveryOutputPages.bind(result.ws),send=result.ws.sendAsync.bind(result.ws);
				result.ws.sendAsync=async(type,payload)=>{if(['chat_turn_admit','new_chat','chat_message'].includes(type))inferenceRequests++;return send(type,payload)};
				result.ws.drainAvailableRecoveryOutputPages=(root)=>{
					const pages=drain(root);
					pages.push([input.fixture.childStaleOutput],[input.fixture.childStaleOutput]);
					return pages;
				};return result;
			};
			const childPath='/v1/embeds/chats/'+input.fixture.chatId+'/embeds/'+input.fixture.childEmbed.embed_id;
			const before=await client.http.get(childPath,client.getCliRequestHeaders());
			if(before.status!==404)throw Error('Child with unavailable parent wrappers must remain opaque404');
			const first=await client.listChats(100,1,{forceRefresh:true}),firstAttempts=attempts.length;
			const second=await client.listChats(100,1,{forceRefresh:true}),secondAttempts=attempts.length;
			clock+=5001;
			const expired=await client.listChats(100,1,{forceRefresh:true}),expiredAttempts=attempts.length;
			const {execFileSync}=require('node:child_process');
			execFileSync('docker',['compose','-f',input.compose,'exec','-T','-e','OPENMATES_CI_ISOLATED=1',
				'api','python','-c',input.fixtureProgram],{cwd:input.root,input:JSON.stringify({...input.fixture,operation:'keys-ready'}),encoding:'utf8',timeout:90000});
			const restored=await client.listChats(100,1,{forceRefresh:true}),restoredAttempts=attempts.length;
			const after=await client.http.get(childPath,client.getCliRequestHeaders());
			const parentAfter=await client.http.get('/v1/embeds/chats/'+input.fixture.chatId+'/embeds/'+input.fixture.embed.embed_id,
				client.getCliRequestHeaders());
			Date.now=actualNow;
			process.stdout.write(JSON.stringify({missingStatus:before.status,firstAttempts,secondAttempts,expiredAttempts,restoredAttempts,
				pendingFirst:first.pendingRecoveryOutputs>=1,pendingSecond:second.pendingRecoveryOutputs>=1,
				pendingExpired:expired.pendingRecoveryOutputs>=1,restoredReadable:after.ok,
				childCipherUnchanged:after.data?.embed?.encrypted_content===input.fixture.childEmbed.encrypted_content,
				childVersionUnchanged:after.data?.embed?.version_number===1,
				parentCipherUnchanged:parentAfter.data?.embed?.encrypted_content===input.fixture.embed.encrypted_content,
				childAccepted,inferenceRequests}));
		`, {fixture,compose:isolatedCompose,root:repositoryRoot,fixtureProgram:canonicalHistoryFixtureProgram()});
		expect(parentReadiness).toEqual({missingStatus:404,firstAttempts:1,secondAttempts:1,expiredAttempts:2,restoredAttempts:3,
			pendingFirst:true,pendingSecond:true,pendingExpired:true,restoredReadable:true,childCipherUnchanged:true,
			childVersionUnchanged:true,parentCipherUnchanged:true,childAccepted:1,inferenceRequests:0});
		await testInfo.attach('cli-bounded-parent-readiness', {body:JSON.stringify(parentReadiness),contentType:'application/json'});

		installRecorderDeps();
		const result = await runCli(apiUrl, ['chats', 'list', '--limit', '100', '--json'], 120_000, {
			useApiKey: false,
			env: { ...workflowCliEnv(apiUrl, home), OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'cli-recovery-stale-ack' }
		});
		expect(result.code, `CLI list failed: ${result.stderr.slice(-2000)}`).toBe(0);
		expect(JSON.parse(result.stdout).chats.some((chat: { id: string }) => chat.id === fixture!.chatId)).toBe(true);
		expect(result.recording?.videoPath).toBeTruthy();
		await testInfo.attach('cli-stale-recovery-ack', { path: result.recording.videoPath, contentType: 'video/mp4' });
	} finally {
		if (fixture) persistCanonicalHistoryFixture(fixture, 'cleanup');
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

// contract-test: supporting surface=rest_api assertions=chats.direction.context-assessment,plans.active-context.vault-boundary,chats.send.immediate-admission,app-memories.surface.semantic-parity
test('SDK-minted first Personal chat admits after fresh Memory privacy and before Project resolution', async ({ page }: { page: any }) => {
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
			let phase='minted',lastFullPrivacyGeneration=null;
			const privacyReceipts=new Map();
			const result={minted:{focus:0,plans:0,projects:0,tasks:0,taskDirectoryCalls:0,taskDirectoryPages:[],taskListScopes:[],routingDirectoryCalls:0,routingDirectoryGets:0,
				projectSettingsGets:0,snapshotDirectoryRowsEnabled:false,combinedRequests:0,memoryRequests:0,
				combinedProjectRows:false,memoryReady:false,privacyAfterMemoryReceipt:false,
				projectDeliveredBeforeAdmission:null,admission:null,routing:null,details:null},
				supplied:{focus:0,plans:0,projects:0,tasks:0,taskDirectoryCalls:0,taskDirectoryPages:[],taskListScopes:[],routingDirectoryCalls:0,routingDirectoryGets:0,
				projectSettingsGets:0,snapshotDirectoryRowsEnabled:false,combinedRequests:0,memoryRequests:0,
				combinedProjectRows:false,memoryReady:false,privacyAfterMemoryReceipt:false,
				projectDeliveredBeforeAdmission:null,admission:null,routing:null,details:null}};
			for(const [method,field] of [['getActiveProjectFocus','focus'],['listUserPlans','plans'],
				['listProjects','projects'],['listUserTasks','tasks']]){
				const original=client[method].bind(client);
				client[method]=async(...args)=>{
					const currentPhase=phase;
					result[currentPhase][field]++;
					if(method==='listUserTasks')result[currentPhase].taskListScopes.push({
						chatId:args[0]?.chatId??null,limit:args[0]?.limit??null});
					const value=await original(...args);
					return value;
				};
			}
			const taskDirectory=client.listUserTaskDiscoveryPage.bind(client);
			client.listUserTaskDiscoveryPage=async(...args)=>{
				result[phase].taskDirectoryCalls++;
				return taskDirectory(...args);
			};
			const get=client.http.get.bind(client.http);
			client.http.get=async(...args)=>{
				const path=args[0];
				if(typeof path==='string'&&path.startsWith('/v1/user-tasks?')){
					const query=new URL(path,'https://fixture.invalid').searchParams;
					if(!query.has('chat_id'))result[phase].taskDirectoryPages.push({
						limit:query.get('limit'),paginate:query.get('paginate'),cursor:query.get('cursor')});
				}
				if(path==='/v1/projects/routing-directory')result[phase].routingDirectoryGets++;
				if(typeof path==='string'&&path.startsWith('/v1/projects/')
					&&path.split('?')[0].endsWith('/settings'))result[phase].projectSettingsGets++;
				return get(...args);
			};
			const listRoutingDirectory=client.listPersonalProjectRoutingDirectory.bind(client);
			client.listPersonalProjectRoutingDirectory=async(...args)=>{
				const currentPhase=phase;
				result[currentPhase].routingDirectoryCalls++;
				const rows=await listRoutingDirectory(...args);
				return rows;
			};
			const open=client.openWsClient.bind(client);
			client.openWsClient=async(...args)=>{
				const opened=await open(...args),send=opened.ws.sendAsync.bind(opened.ws);
				const wait=opened.ws.waitForMessage.bind(opened.ws);
				const waitForDiscovery=opened.ws.waitForRecoveryOutputDiscovery.bind(opened.ws);
				const currentPhase=phase;
				const requestCombined=opened.ws.requestPersonalSendContextSnapshot.bind(opened.ws);
				const requestMemory=opened.ws.requestPersonalMemorySnapshot.bind(opened.ws);
				const requestV2=opened.ws.requestPersonalSendContextSnapshotV2.bind(opened.ws);
				opened.ws.requestPersonalSendContextSnapshotV2=async(request,...args)=>{
					const snapshot=await requestV2(request,...args);
					const fullRows=Array.isArray(snapshot.personal_memories?.memories)
						&&snapshot.personal_memories.memories.every(row=>row&&typeof row==='object'&&!Array.isArray(row));
					const matchedGeneration=snapshot.unchanged&&typeof request.known_generation==='string'
						&&request.known_generation===snapshot.privacy_generation
						&&snapshot.privacy_generation===lastFullPrivacyGeneration;
					if(fullRows)lastFullPrivacyGeneration=snapshot.privacy_generation;
					result[currentPhase].snapshotDirectoryRowsEnabled=Array.isArray(snapshot.project_candidates)
						&&snapshot.project_candidates.length<=40&&snapshot.project_candidates.every(row=>
							row.auto_selection===true&&typeof row.project_id==='string'
							&&typeof row.encrypted_project_key==='string'&&row.encrypted_project_key.length>0
							&&typeof row.encrypted_name==='string'&&row.encrypted_name.length>0);
					privacyReceipts.set(currentPhase,{request,snapshot});
					result[currentPhase].v2Requests=(result[currentPhase].v2Requests??0)+1;
					result[currentPhase].memoryReady=fullRows||matchedGeneration;
					result[currentPhase].privacyObservation={purposeSend:request.purpose==='send',
						turnBound:typeof request.turn_id==='string'&&snapshot.turn_id===request.turn_id,
						receiptPresent:typeof snapshot.receipt_id==='string'&&snapshot.receipt_id.length>0,
						generationValid:snapshot.privacy_generation===null
							||typeof snapshot.privacy_generation==='string'&&snapshot.privacy_generation.length>0&&snapshot.privacy_generation.length<=100,
						memoryRowsOrVerifiedGeneration:fullRows||matchedGeneration,
						projectCandidatesArray:Array.isArray(snapshot.project_candidates)};
					return snapshot;
				};
				opened.ws.requestPersonalMemorySnapshot=async(...args)=>{
					const snapshot=await requestMemory(...args);
					result[currentPhase].memoryRequests++;
					result[currentPhase].memoryReady=Array.isArray(snapshot.memories);
					return snapshot;
				};
				opened.ws.requestPersonalSendContextSnapshot=async(...args)=>{
					const snapshot=await requestCombined(...args);
					result[currentPhase].combinedRequests++;
					result[currentPhase].combinedProjectRows=Array.isArray(snapshot.project_candidates);
					return snapshot;
				};
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
						const receipt=privacyReceipts.get(currentPhase);
						result[phase].admission={...describeContext(payload.inference_request??{}),
							chatId:payload.chat_id,
							privacyReceiptBound:receipt?.request.turn_id===payload.turn_id
								&&receipt?.snapshot.receipt_id===payload.privacy_receipt_id
								&&receipt?.snapshot.privacy_generation===payload.privacy_generation,
						contextPending:payload.inference_request?.client_context_pending===true,
						privacyAfterMemoryReceipt:result[phase].privacyAfterMemoryReceipt,
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
						const receipt=privacyReceipts.get(currentPhase);
						const directory=receipt?.snapshot.project_candidates??[];
						const candidates=payload.context?.project_focus_candidates;
						const ids=rows=>rows.map(row=>row.project_id).sort();
						const verifiedDirectory=payload.phase!=='routing'||Array.isArray(candidates)
							&&JSON.stringify(ids(candidates))===JSON.stringify(ids(directory))
							&&candidates.every(row=>row.auto_selection===true&&typeof row.name==='string'&&row.name.length>0
								&&typeof row.summary==='string'&&directory.some(source=>source.project_id===row.project_id
									&&source.focus_activation_policy===row.focus_activation_policy));
						if(payload.phase==='routing')result[phase].projectDeliveredBeforeAdmission=capturedAdmission===null;
						result[phase][payload.phase]={...describeContext(payload.context??{}),identitiesMatch,verifiedDirectory};
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
					onPrivacyPrepared:()=>{result[current].privacyAfterMemoryReceipt=result[current].memoryReady
						||result[current].combinedRequests===1;},
						jevContext:suppliedContext,...(current==='supplied'?{newChatId:randomUUID()}:{})});
					throw Error('Inference preflight was not captured');
				}catch(error){if(error.message!=='EXPECTED_PRE_DISPATCH_STOP')throw error;}
				if(!result[current].admission||!result[current].routing||!result[current].details)throw Error('Missing phased context observation');
			}
			process.stdout.write(JSON.stringify(result));
		`);
		expect(observed.minted.focus).toBe(0);
		expect(observed.minted.plans).toBe(0);
		expect(observed.minted.combinedRequests).toBe(0);
		expect(observed.minted.memoryRequests).toBe(0);
		expect(observed.minted.memoryReady).toBe(true);
		expect(observed.minted.combinedProjectRows).toBe(false);
		expect(observed.minted.projects).toBe(0);
		expect(observed.minted.routingDirectoryCalls).toBe(0);
		expect(observed.minted.routingDirectoryGets).toBe(0);
		expect(observed.minted.projectSettingsGets).toBe(0);
		expect(observed.minted.snapshotDirectoryRowsEnabled).toBe(true);
		expect(observed.minted.projectDeliveredBeforeAdmission).toBe(false);
		expect(observed.minted.admission.privacyAfterMemoryReceipt).toBe(true);
		// A newly minted chat has no canonical chat-scoped Tasks yet. Its
		// fresh candidate inventory still comes from exactly one bounded page.
		expect(observed.minted.tasks).toBe(0);
		expect(observed.minted.taskListScopes).toEqual([]);
		expect(observed.supplied.focus).toBe(2);
		expect(observed.supplied.plans).toBe(1);
		expect(observed.supplied.combinedRequests).toBe(0);
		expect(observed.supplied.memoryRequests).toBe(0);
		expect(observed.supplied.combinedProjectRows).toBe(false);
		expect(observed.supplied.admission.privacyAfterMemoryReceipt).toBe(true);
		expect(observed.supplied.projects).toBe(0);
		expect(observed.supplied.routingDirectoryCalls).toBe(0);
		expect(observed.supplied.routingDirectoryGets).toBe(0);
		expect(observed.supplied.projectSettingsGets).toBe(0);
		expect(observed.supplied.tasks).toBeGreaterThan(0);
		expect(observed.supplied.taskListScopes.length).toBe(observed.supplied.tasks);
		for(const scope of observed.supplied.taskListScopes){
			expect(scope).toEqual({chatId:observed.supplied.admission.chatId,limit:100});
		}
		for(const turn of [observed.minted,observed.supplied]){
			expect(turn.taskDirectoryCalls).toBe(1);
			expect(turn.taskDirectoryPages).toEqual([{limit:'100',paginate:'true',cursor:null}]);
		}
		expect(observed.minted.selectionDetailsV2).toBe(true);
		expect(observed.supplied.selectionDetailsV2).toBe(false);
		expect(observed.minted.admission.discoveryCompleted).toBe(false);
		expect(observed.supplied.admission.discoveryCompleted).toBe(true);
		for (const turn of [observed.minted, observed.supplied]) {
			expect(turn.v2Requests).toBe(1);
			expect(turn.memoryReady).toBe(true);
			expect(turn.privacyObservation).toEqual({ purposeSend: true, turnBound: true,
				receiptPresent: true, generationValid: true, memoryRowsOrVerifiedGeneration: true,
				projectCandidatesArray: true });
			expect(turn.admission.privacyReceiptBound).toBe(true);
			expect(turn.snapshotDirectoryRowsEnabled).toBe(true);
			expect(turn.routing.verifiedDirectory).toBe(true);
			expect(turn.projectDeliveredBeforeAdmission).toBe(false);
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
			let authCalls=0,preflights=0,liveReceipt=null;
			client.http.post=async(...args)=>{if(args[0]==='/v1/auth/session')authCalls++;return post(...args);};
			const open=client.openWsClient.bind(client);
			client.openWsClient=async(...args)=>{
				const opened=await open(...args),send=opened.ws.sendAsync.bind(opened.ws);
				const requestV2=opened.ws.requestPersonalSendContextSnapshotV2.bind(opened.ws);
				opened.ws.requestPersonalSendContextSnapshotV2=async(request,...options)=>{
					const snapshot=await requestV2(request,...options);
					if(request.purpose!=='send'||snapshot.turn_id!==request.turn_id
						||typeof snapshot.receipt_id!=='string'
						||!snapshot.unchanged&&!Array.isArray(snapshot.personal_memories?.memories))throw Error('Fresh live privacy receipt missing');
					liveReceipt={request,snapshot,authCalls};return snapshot;
				};
				opened.ws.sendAsync=async(type,payload)=>{
					if(type==='chat_turn_admit'){
						if(!liveReceipt||authCalls!==liveReceipt.authCalls
							||liveReceipt.request.turn_id!==payload.turn_id
							||liveReceipt.snapshot.receipt_id!==payload.privacy_receipt_id
							||liveReceipt.snapshot.privacy_generation!==payload.privacy_generation)throw Error('Live privacy auth was not reused at preflight');
						preflights++;throw Error('EXPECTED_PRE_DISPATCH_STOP');
					}
					return send(type,payload);
				};
				return opened;
			};
			const counts=[];
			for(const mode of ['fresh','expired']){
				liveReceipt=null;
				let expiredReceipt=false;
				if(mode==='expired'){
					await client.whoAmI();
					const validated=client.pendingWhoAmIAuthHandoff;
					if(!validated)throw Error('Validated owner receipt missing');
					validated.validatedAt-=6000;
					expiredReceipt=performance.now()-validated.validatedAt>5000;
					if(!expiredReceipt)throw Error('Owner receipt was not expired');
				}
				try{
					await client.sendMessage({message:'Ordinary Personal auth boundary check.',personal:true,
						piiDetection:false});
					throw Error('Inference preflight was not captured');
				}catch(error){if(error.message!=='EXPECTED_PRE_DISPATCH_STOP')throw error;}
				counts.push({authCalls,preflights,authAtPrivacyReceipt:liveReceipt?.authCalls,
					expiredReceipt,receiptReusedAtPreflight:authCalls===liveReceipt?.authCalls});
			}
			process.stdout.write(JSON.stringify({counts}));
		`);
		expect(observed.counts).toEqual([
			{ authCalls: 1, preflights: 1, authAtPrivacyReceipt: 1, expiredReceipt: false, receiptReusedAtPreflight: true },
			{ authCalls: 3, preflights: 2, authAtPrivacyReceipt: 3, expiredReceipt: true, receiptReusedAtPreflight: true }
		]);
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
test('SDK reports a Project directory failure after durable epoch-one first Personal admission', async ({ page }: { page: any }, testInfo: any) => {
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('post-admission-context-failure');
	const diagnosticAttachment = testInfo.outputPath('private-routing-diagnostic.json');
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_POST_ADMISSION_CONTEXT_FAILURE');
		let observed;
		try { observed = canonicalHistorySdk(apiUrl, home, `
			const diagnosticAttachment=${JSON.stringify(diagnosticAttachment)};
			const owner=await client.whoAmI();
			if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal account');
			const diagnosticFs=require('node:fs');
			const {spawnSync}=require('node:child_process');
			const diagnosticCompose=require('node:path').join(process.cwd(),'test-results/ci-private/compose.json');
			const diagnosticRuns=[];
			const runDiagnostic=(name,program,input,timeout)=>{
				const stdoutPath=diagnosticAttachment+'.'+name+'.stdout';
				const stderrPath=diagnosticAttachment+'.'+name+'.stderr';
				let outFd=-1,errFd=-1,result=null,spawnError=null;
				try{
					outFd=diagnosticFs.openSync(stdoutPath,'wx',0o600);
					errFd=diagnosticFs.openSync(stderrPath,'wx',0o600);
					diagnosticFs.fchmodSync(outFd,0o600);diagnosticFs.fchmodSync(errFd,0o600);
					result=spawnSync('docker',['compose','-f',diagnosticCompose,'exec','-T','-e',
						'OPENMATES_CI_ISOLATED=1','api','python','-u','-c',program],{
						input:JSON.stringify(input),stdio:['pipe',outFd,errFd],timeout,killSignal:'SIGKILL'
					});
					spawnError=result.error?.code??null;
				}catch(error){spawnError=error?.code??'probe_error';}
				finally{
					if(outFd>=0)diagnosticFs.closeSync(outFd);
					if(errFd>=0)diagnosticFs.closeSync(errFd);
				}
				const stdout=diagnosticFs.existsSync(stdoutPath)?diagnosticFs.readFileSync(stdoutPath):Buffer.alloc(0);
				const stderr=diagnosticFs.existsSync(stderrPath)?diagnosticFs.readFileSync(stderrPath):Buffer.alloc(0);
				if(diagnosticFs.existsSync(stdoutPath))diagnosticFs.unlinkSync(stdoutPath);
				if(diagnosticFs.existsSync(stderrPath))diagnosticFs.unlinkSync(stderrPath);
				const run={name,status:result?.status??null,signal:result?.signal??null,
					errorCode:spawnError,stdout,stderr};
				diagnosticRuns.push(run);
				return run;
			};
			const saveDiagnostic=()=>{
				try{
					const fd=diagnosticFs.openSync(diagnosticAttachment,'wx',0o600);
					try{
						diagnosticFs.fchmodSync(fd,0o600);
						diagnosticFs.writeSync(fd,JSON.stringify({runs:diagnosticRuns.map(run=>({
							name:run.name,status:run.status,signal:run.signal,errorCode:run.errorCode,
							stdoutBase64:run.stdout.toString('base64'),stderrBase64:run.stderr.toString('base64')
						}))}));
					}finally{diagnosticFs.closeSync(fd);}
					return true;
				}catch{return false;}
			};
			const runSummary=run=>{
				const rows=run.stdout.toString('utf8').split(/\\r?\\n/);
				const allowed=new Set(['broker_bootstrap','broker_app_imported',
					'broker_main','broker_routing','broker_depth','broker_registered','broker_queues',
					'state_bootstrap','state_imported','state_preflight','state_outbox','state_active','state_complete']);
				const stages=rows.filter(line=>line.startsWith('OPENMATES_DIAG_STAGE:'))
					.map(line=>line.slice('OPENMATES_DIAG_STAGE:'.length)).filter(stage=>allowed.has(stage));
				return {category:run.errorCode==='ETIMEDOUT'?'timeout'
					:run.signal?'signalled':run.status===0?'ok':run.errorCode?'spawn_error':'nonzero_exit',
					stdoutBytes:run.stdout.length,stderrBytes:run.stderr.length,
					lastStage:stages.at(-1)??'not_started'};
			};
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
			// Own the fixture rejection before any asynchronous directory consumer starts.
			void projectGate.catch(()=>{});
			const failDirectory=async()=>{projectReads++;return projectGate;};
			client.listProjects=failDirectory;
			client.listPersonalProjectRoutingDirectory=failDirectory;
			const outbound=[];
			const open=client.openWsClient.bind(client);
			client.openWsClient=async(...args)=>{
				const opened=await open(...args),send=opened.ws.sendAsync.bind(opened.ws);
				// Exercise deferred discovery compatibility; v2's verified empty directory
				// correctly needs no extra Project read and cannot consume this fault.
				const supports=opened.ws.supportsServerCapability.bind(opened.ws);
				opened.ws.supportsServerCapability=capability=>capability==='personal_send_context_snapshot_v2'?false:supports(capability);
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
				let serverState={diagnosticUnavailable:true};
				try{
					const brokerProgram=[
						'import json,logging,os,signal,sys,uuid',
						'print("OPENMATES_DIAG_STAGE:broker_bootstrap",flush=True)',
						'assert os.environ.get("OPENMATES_CI_ISOLATED")=="1"',
						'data=json.load(sys.stdin);task=data["task_id"]',
						'assert str(uuid.UUID(task))==task',
						'logging.disable(logging.CRITICAL)',
						'from backend.core.api.app.tasks.celery_config import app',
						'print("OPENMATES_DIAG_STAGE:broker_app_imported",flush=True)',
						'def alarm(*_): raise TimeoutError()',
						'def bounded(operation):',
						'    previous=signal.signal(signal.SIGALRM,alarm);signal.setitimer(signal.ITIMER_REAL,2)',
						'    try: return {"status":"ok","value":operation()}',
						'    except TimeoutError: return {"status":"timeout"}',
						'    except Exception: return {"status":"error"}',
						'    finally: signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)',
						'def emit(step,value): print("OPENMATES_BROKER_PART:"+json.dumps({"step":step,"value":value}),flush=True)',
						'def depth():',
						'    with app.connection_for_read(connect_timeout=1.5,transport_options={"socket_timeout":1.5,"socket_connect_timeout":1.5}) as connection:',
						'        channel=connection.channel()',
						'        try:',
						'            if not channel.__class__.__module__.startswith("kombu.transport.redis") or tuple(channel.priority_steps)!=(0,3,6,9): return {"status":"unsupported_transport"}',
						'            with channel.client.pipeline() as pipeline:',
						'                for name in ("app_ai","app_ai_routing"):',
						'                    for priority in (0,3,6,9): pipeline.llen(channel._q_for_pri(name,priority))',
						'                counts=pipeline.execute()',
						'            return {"status":"ok","appAi":sum(counts[:4]),"appAiRouting":sum(counts[4:])}',
						'        finally: channel.close()',
						'for label,identifier in (("main",task),("routing",task+":routing")):',
						'    result=bounded(lambda: app.AsyncResult(identifier).state)',
						'    emit(label,result.get("value",result["status"]))',
						'    print("OPENMATES_DIAG_STAGE:broker_"+label,flush=True)',
						'result=bounded(depth);emit("depth",result.get("value",{"status":result["status"]}))',
						'print("OPENMATES_DIAG_STAGE:broker_depth",flush=True)',
						'reg=bounded(lambda: app.control.inspect(timeout=1.2).registered())',
						'print("OPENMATES_DIAG_STAGE:broker_registered",flush=True)',
						'queues=bounded(lambda: app.control.inspect(timeout=1.2).active_queues())',
						'print("OPENMATES_DIAG_STAGE:broker_queues",flush=True)',
						'registered=reg.get("value") if reg["status"]=="ok" and isinstance(reg.get("value"),dict) else None',
						'active=queues.get("value") if queues["status"]=="ok" and isinstance(queues.get("value"),dict) else None',
						'target={name for name,items in (active or {}).items() if isinstance(items,list) and any(isinstance(item,dict) and item.get("name")=="app_ai_routing" for item in items)}',
						'stage_one={name for name in target if isinstance((registered or {}).get(name),list) and "apps.ai.tasks.stage_one" in registered[name]}',
						'emit("inspect",{"registrationStatus":reg["status"] if registered is not None else "no_reply","queuesStatus":queues["status"] if active is not None else "no_reply","routingConsumers":len(target) if active is not None else None,"stageOneRegisteredOnRoutingConsumers":len(stage_one) if registered is not None and active is not None else None})'
					].join(String.fromCharCode(10));
					const brokerRun=runDiagnostic('broker',brokerProgram,{
						task_id:preflightAck?.inference_task_id
					},14000);
					const stateProgram=[
						'import asyncio,json,logging,os,sys,uuid',
						'print("OPENMATES_DIAG_STAGE:state_bootstrap",flush=True)',
						'assert os.environ.get("OPENMATES_CI_ISOLATED")=="1"',
						'data=json.load(sys.stdin)',
						'assert all(str(uuid.UUID(data[key]))==data[key] for key in ("user_id","chat_id","turn_id","message_id","request_id","preflight_id"))',
						'logging.disable(logging.CRITICAL)',
						'from backend.core.api.app.services.cache import CacheService',
						'from backend.core.api.app.services.directus import DirectusService',
						'from backend.core.api.app.services.client_context_continuation import _scope,_reference,_key',
						'print("OPENMATES_DIAG_STAGE:state_imported",flush=True)',
						'def emit(step,value): print("OPENMATES_STATE_PART:"+json.dumps({"step":step,"value":value}),flush=True)',
						'async def main():',
						'    cache=CacheService();directus=DirectusService(cache_service=cache)',
						'    try:',
						'        preflights=await asyncio.wait_for(directus.get_items("chat_turn_preflights",params={"filter":{"id":{"_eq":data["preflight_id"]}},"limit":1},no_cache=True,admin_required=True,raise_on_error=True),2)',
						'        emit("preflight",{"state":(preflights or [{}])[0].get("state")})',
						'        print("OPENMATES_DIAG_STAGE:state_preflight",flush=True)',
						'        outboxes=await asyncio.wait_for(directus.get_items("chat_inference_outbox",params={"filter":{"preflight_id":{"_eq":data["preflight_id"]}},"limit":2},no_cache=True,admin_required=True,raise_on_error=True),2)',
						'        task=(outboxes or [{}])[0].get("inference_task_id")',
						'        emit("outbox",{"state":(outboxes or [{}])[0].get("state"),"count":len(outboxes or []),"taskMatches":bool(task and task==data.get("task_id"))})',
						'        print("OPENMATES_DIAG_STAGE:state_outbox",flush=True)',
						'        active=await asyncio.wait_for(cache.get_active_ai_task(data["chat_id"]),2)',
						'        emit("active",{"present":bool(active),"matches":bool(task and active==task)})',
						'        print("OPENMATES_DIAG_STAGE:state_active",flush=True)',
						'        scope=_scope(user_id=data["user_id"],chat_id=data["chat_id"],turn_id=data["turn_id"],message_id=data["message_id"],request_id=data["request_id"])',
						'        key=_key(_reference(scope));redis=await cache.client',
						'        phases={name:bool(await asyncio.wait_for(redis.exists(key+suffix),1)) for name,suffix in (("binding",""),("failed",":failed"),("routing",":routing"),("details",":details"))}',
						'        emit("context",phases)',
						'        print("OPENMATES_DIAG_STAGE:state_complete",flush=True)',
						'    finally: await directus.close();await cache.close()',
						'asyncio.run(main())'
					].join(String.fromCharCode(10));
					const stateRun=runDiagnostic('state',stateProgram,{
						user_id:owner.id,chat_id:newChatId,turn_id:admission.turn_id,
						message_id:admission.message_id,request_id:admission.inference_request.client_context_request_id,
						preflight_id:preflightAck.preflight_id,task_id:preflightAck.inference_task_id
					},12000);
					const parts=(run,prefix)=>run.stdout.toString('utf8').split(/\\r?\\n/)
						.filter(line=>line.startsWith(prefix)).map(line=>{
							try{return JSON.parse(line.slice(prefix.length));}catch{return null;}
						}).filter(Boolean);
					serverState={brokerProbe:runSummary(brokerRun),brokerParts:parts(brokerRun,'OPENMATES_BROKER_PART:'),
						stateProbe:runSummary(stateRun),stateParts:parts(stateRun,'OPENMATES_STATE_PART:')};
				}catch(diagnosticError){serverState={diagnosticUnavailable:true,
					category:'probe_exception',errorType:diagnosticError?.name??'UnknownError'};}
				serverState.attachmentSaved=saveDiagnostic();
				let activeTaskPresent=null,activityReadFailed=false,activityReadStatus='unavailable';
				const activityTimeout=Symbol('activity timeout');
				let activityTimer;
				try{
					const deadline=new Promise((_,reject)=>{activityTimer=setTimeout(()=>reject(activityTimeout),3000);});
					activeTaskPresent=(await Promise.race([client.getChatActivity({personal:true}),deadline])).ids.includes(newChatId);
					activityReadStatus='ok';
				}catch(activityError){activityReadFailed=true;
					activityReadStatus=activityError===activityTimeout?'timeout':'error';
				}finally{clearTimeout(activityTimer);}
				console.error('FIRST_PERSONAL_TERMINAL_DIAGNOSTIC',JSON.stringify({
					...beforeTerminal,observerOpenAfterWait:observer.isOpen(),
					chatActivityPresent:activeTaskPresent,activityReadFailed,activityReadStatus,serverState,
				}));
				throw error;
			}
			const canonicalBefore=await client.getChatMessagesWindow(newChatId,{personal:true,limit:20,
				respectCompressionBoundary:false});
			const beforeIds=canonicalBefore.messages.map(message=>message.clientMessageId||message.id);
			const wrongWrapper={...admission,encrypted_chat_key:randomBytes(48).toString('base64')};
			let rejectionTimer,stopRejection=()=>{};
			const rejection=new Promise((resolve,reject)=>{
				const finish=(settle,value)=>{clearTimeout(rejectionTimer);stopRejection();settle(value);};
				stopRejection=observer.onMessageType('error',payload=>{
					if(payload?.turn_id===admission?.turn_id)finish(resolve,payload);
				});
				rejectionTimer=setTimeout(()=>finish(reject,Error('Timed out waiting for scoped wrapper rejection')),10000);
			});
			void rejection.catch(()=>{});
			let rejected;
			try{
				await observer.sendAsync('chat_turn_admit',wrongWrapper);
				rejected=await rejection;
			}finally{clearTimeout(rejectionTimer);stopRejection();}
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
				wrapperRejectionCode:rejected?.code??null,
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
		`); } catch(error) {
			if (fs.existsSync(diagnosticAttachment)) await testInfo.attach('private-routing-diagnostic', { path: diagnosticAttachment, contentType: 'application/json' });
			throw error;
		}
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
		expect(observed.wrapperRejectionCode).toBe('immutable_chat_key_mismatch');
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
test('durable routing proof authorizes the exact active Personal turn across concurrent follower admission', async ({ page }: { page: any }, testInfo: any) => {
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
    owner_id=json.loads(sys.stdin.readline())['ownerId']
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
    async def proof_sql(operation):
        print('OPENMATES_PROOF_SQL_REQUEST:'+json.dumps({'operation':operation,'chatId':chat_id}),flush=True)
        response=json.loads(sys.stdin.readline())
        assert 'error' not in response, 'Isolated proof SQL failed: '+str(response.get('error'))
        return response['value']
    async def rows(collection):
        if collection=='chat_routing_proofs':
            result=await proof_sql('read')
        else:
            result=await directus.get_items(collection,params={'filter':{'chat_id':{'_eq':chat_id}},'limit':-1},
                no_cache=True,raise_on_error=True)
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
        assert len(samples)==4 and all(value is True for value in samples)
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
        print('OPENMATES_PROOF_FIXTURE_RESULT:'+json.dumps({'concurrent_verifications':len(samples),
            'proof_version':proof[0]['messages_v'],'exact_active_authorized':True,
            'cipher_revision_owner_deletion_rejected':True}),flush=True)
    finally:
        for collection in ('chat_recovery_chat_deletion_fences','chat_routing_proofs',
            'chat_inference_outbox','chat_turn_preflights','messages'):
            for row in await rows(collection):
                if collection=='chat_routing_proofs':
                    assert await proof_sql('delete')
                else:
                    assert await directus.delete_item(collection,row.get('id') or row['chat_id'],admin_required=True)
        chats=await directus.get_items('chats',params={'filter':{'id':{'_eq':chat_id}},'limit':1},no_cache=True)
        for row in chats or []: assert await directus.delete_item('chats',row['id'],admin_required=True)
        await directus.close()
asyncio.run(main())
`;
		const result = await runIsolatedProofFixture(program, owner, testInfo);
		expect(result.concurrent_verifications).toBe(4);
		expect(result.proof_version).toBe(3);
		expect(result.exact_active_authorized).toBe(true);
		expect(result.cipher_revision_owner_deletion_rejected).toBe(true);
	} finally {
		removeWorkflowCliHome(home);
	}
});

/** Synthetic sealed records belong only to the disposable CI owner/chat. */
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
            created,_=await directus.create_item('embeds',child,admin_required=True); assert created
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
                    keys=await directus.get_items('embed_keys',params={'filter':{'hashed_embed_id':{'_eq':hashlib.sha256(embed_id.encode()).hexdigest()}},'limit':3},no_cache=True,admin_required=True)
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

// contract-test: supporting surface=cli assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
test('bounded CLI app-output recovery preserves durable parent and acknowledgement fences', async () => {
  const packageDir = path.resolve(__dirname, '../../../packages/openmates-cli');
  const output = execFileSync(process.execPath, ['--test', '--test-reporter=tap', '--experimental-strip-types', '--loader', './tests/loader.mjs',
    'tests/recoveryBatch.test.ts', 'tests/recoveryOutputClient.test.ts', 'tests/recoveryOutputWs.test.ts',
    'tests/warmSlotRearm.test.ts', 'tests/serverCaddyUpdate.test.ts', 'tests/serverCaddyUpgrade.test.ts'], {
    cwd: packageDir, encoding: 'utf8', timeout: 90_000,
    env: { ...process.env, OPENMATES_STATE_DIR: undefined, OPENMATES_PROFILE: undefined,
      OPENMATES_API_KEY: undefined, OPENMATES_API_URL: undefined },
  });
  expect(output).toContain('verifies sealed outputs with four canonical readers and never ACKs before the final reread');
  expect(output).toContain('drains started recovery workers on failure without starting queued work or returning readiness');
  expect(output).toContain('recovers parents before children without weakening scope: cross-page');
  expect(output).toContain('replenishes distinct unused slots for repeated same-owner turns only after cleanup and close');
  expect(output).toContain('requires the exact account-key preflight independently of disabled Workflows');
  expect(output).toContain('# fail 0');
});
