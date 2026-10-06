/* eslint-disable @typescript-eslint/no-require-imports */
/** Real terminal proof of saved Markdown, linked views, and a finished Fitness result. */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';

const {test, expect, email, password, otpKey, captureProof, installRecorderDeps,
	requireIsolatedCliBuild, workflowApiUrl,
	createWorkflowCliHome, skipWithoutCredentials} = require('./cli-tui-proof-helpers');
const {workflowCliEnv, clearWorkflowCliSyncCache, loginWorkflowCliViaPair, removeWorkflowCliHome} = require('./helpers/workflow-cli-e2e-helpers');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../../..');
const COMPOSE = path.join(ROOT, 'test-results/ci-private/compose.json');
const PROFILE = 'cli-terminal';

type ChatFixture = {chatId: string; userMessageId: string; assistantMessageId: string;
	embedIds: [string,string,string]; ownerId: string; chat: Record<string, unknown>;
	messages: [Record<string, unknown>,Record<string, unknown>]};

function sdk(apiUrl: string, home: string, cli: string, program: string, input: unknown = {}): any {
	const modulePath = path.join(path.dirname(cli), 'index.js');
	const source = `
		const {pathToFileURL}=require('node:url');
		const {randomUUID,randomBytes,createHash,webcrypto}=require('node:crypto');
		(async()=>{
			const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
			const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
			const input=JSON.parse(process.argv[2]);
			const hash=value=>createHash('sha256').update(value).digest('hex');
			const encrypt=async(value,key)=>{
				const iv=randomBytes(12), cryptoKey=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
				const bytes=typeof value==='string'?Buffer.from(value):value;
				return Buffer.concat([iv,Buffer.from(await webcrypto.subtle.encrypt({name:'AES-GCM',iv},cryptoKey,bytes))]).toString('base64');
			};
			${program}
		})().catch(error=>{console.error('TUI chat proof fixture:',error.message);process.exit(1)});
	`;
	return JSON.parse(execFileSync('node', ['-e', source, modulePath, JSON.stringify(input)], {
		cwd: ROOT, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 90_000,
	}).trim());
}

function makeChatFixture(apiUrl: string, home: string, cli: string): ChatFixture {
	return sdk(apiUrl, home, cli, `
		const owner=await client.whoAmI();
		if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal account');
		const chatId=randomUUID(),userMessageId=randomUUID(),assistantMessageId=randomUUID();
		const embedIds=[randomUUID(),randomUUID(),randomUUID()];
		const key=randomBytes(32),master=client.getMasterKeyBytes(),now=Math.floor(Date.now()/1000);
		const title='Proof rich chat '+chatId.slice(0,6);
		const fence=String.fromCharCode(96).repeat(3);
		const content='### Saved answer\\n\\n**Nearby classes** are ready. See [Apple Watch](wiki:Apple_Watch) and [Dance search](embed:'+embedIds[0]+').\\n\\n'
			+fence+'json_embed\\n'+JSON.stringify({type:'app_skill_use',embed_id:embedIds[0],
				app_id:'fitness',skill_id:'search_classes'})+'\\n'+fence+'\\n\\n'
			+fence+'embeds_results_view\\n'+'title: Mapped results\\n'+'sources: '+embedIds[0]+'\\n'+fence;
		const chat={id:chatId,hashed_user_id:hash(owner.id),created_at:now,updated_at:now,
			last_edited_overall_timestamp:now,last_message_timestamp:now,messages_v:1,title_v:1,metadata_v:1,
			unread_count:0,encrypted_chat_key:await encrypt(key,master),encrypted_title:await encrypt(title,key),
			encrypted_chat_summary:await encrypt('Classes and linked views.',key),
			encrypted_category:await encrypt('medical_health',key)};
		const userMessage={id:userMessageId,client_message_id:userMessageId,message_id:userMessageId,chat_id:chatId,
			hashed_user_id:hash(owner.id),role:'user',created_at:now-1,updated_at:now-1,
			encrypted_sender_name:await encrypt('You',key),encrypted_category:await encrypt('medical_health',key),
			encrypted_content:await encrypt('Find local classes with a map and calendar.',key)};
		const assistantMessage={id:assistantMessageId,client_message_id:assistantMessageId,message_id:assistantMessageId,chat_id:chatId,
			hashed_user_id:hash(owner.id),role:'assistant',created_at:now,updated_at:now,
			encrypted_sender_name:await encrypt('Assistant',key),encrypted_category:await encrypt('medical_health',key),
			encrypted_content:await encrypt(content,key)};
		process.stdout.write(JSON.stringify({chatId,userMessageId,assistantMessageId,embedIds,ownerId:owner.id,
			chat,messages:[userMessage,assistantMessage]}));
	`);
}

function persistChatFixture(fixture: ChatFixture, operation: 'seed' | 'cleanup'): void {
	expect(fs.existsSync(COMPOSE), 'Requires the disposable isolated CI compose').toBe(true);
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
    assert data['chat']['hashed_user_id']==owner
    assert all(message['hashed_user_id']==owner for message in data['messages'])
    try:
        if data['operation']=='seed':
            created,duplicate=await directus.chat.create_chat_in_directus(data['chat'])
            assert created and not duplicate, 'Encrypted chat seed failed'
            for message in data['messages']:
                stored=await directus.chat.create_message_in_directus(message)
                assert stored and stored.get('id'), 'Encrypted message seed failed'
            assert await cache.add_chat_to_ids_versions(data['ownerId'],data['chatId'],data['chat']['last_edited_overall_timestamp'])
            assert await cache.set_chat_list_item_data(data['ownerId'],data['chatId'],_chat_list_cache_data_from_metadata(data['chat']))
            assert await cache.set_chat_versions(data['ownerId'],data['chatId'],_chat_versions_from_metadata(data['chat']))
        else:
            metadata=await directus.chat.get_chat_metadata(data['chatId'])
            if metadata:
                assert metadata.get('hashed_user_id')==owner, 'Only fixture-owned chat may be removed'
                messages=await directus.chat.get_all_messages_for_chat(data['chatId'],decrypt_content=False)
                for raw_message in messages or []:
                    message=json.loads(raw_message) if isinstance(raw_message,str) else raw_message
                    if message.get('client_message_id') in (data['userMessageId'],data['assistantMessageId']):
                        assert await directus.delete_item('messages',message['id'],admin_required=True), 'Fixture message deletion failed'
                assert await directus.delete_item('chats',data['chatId'],admin_required=True), 'Fixture chat deletion failed'
            await cache.remove_chat_from_ids_versions(data['ownerId'],data['chatId'])
        print('chat proof fixture applied')
    finally: await directus.close(); await cache.close()
asyncio.run(main())
`;
	const output = execFileSync('docker', ['compose', '-f', COMPOSE, 'exec', '-T', '-e',
		'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program], {
		cwd: ROOT, input: JSON.stringify({...fixture, operation}), encoding: 'utf8', timeout: 90_000,
	});
	expect(output.trim()).toBe('chat proof fixture applied');
}

function seedFitnessEmbeds(apiUrl: string, home: string, cli: string, fixture: ChatFixture): void {
	const result = sdk(apiUrl, home, cli, `
		const owner=await client.whoAmI();if(owner.id!==input.ownerId)throw Error('Fixture owner changed');
		const now=Math.floor(Date.now()/1000),key=randomBytes(32);
		const classes=[
			{name:'Dance fundamentals',date:'2026-10-08',time_range:'18:00–19:00',venue_name:'Dance studio Mitte',
				venue_address:'Example Str. 12, Berlin',venue_lat:52.5200,venue_lon:13.4050,
				distance_km:1.25,plans_required:['M','L'],disciplines:['Dance'],spots_display:'4 spots',
				detail_url:'https://example.org/fitness/dance'},
			{name:'Evening yoga',date:'2026-10-09',time_range:'19:00–20:00',venue_name:'Yoga studio Kreuzberg',
				venue_address:'Sample Str. 4, Berlin',venue_lat:52.4990,venue_lon:13.4030,
				distance_km:2.50,plans_required:['S','M','L'],disciplines:['Yoga'],spots_display:'6 spots',
				detail_url:'https://example.org/fitness/yoga'}
		];
		const parent={app_id:'fitness',skill_id:'search_classes',status:'finished',
			provider:'Urban Sports Club',query:'Dance in Berlin',embed_ids:input.embedIds.slice(1),
			results:[{provider:'Urban Sports Club',filters:{city:'Berlin',radius_km:5},
				summary:'Two nearby classes',result_count:2,
				results:input.embedIds.slice(1).map(embed_id=>({embed_id}))}]};
		const {ws}=await client.openWsClient({taskUpdateJobs:false});
		const send=async(type,reply,payload)=>{const requestId=randomUUID(),receipt=ws.waitForMessage(reply,p=>p.request_id===requestId,30000);
			await ws.sendAsync(type,{...payload,request_id:requestId});return (await receipt).payload};
		try{
			for(const [index,embedId] of input.embedIds.entries()){
				await send('store_embed','store_embed_confirmed',{embed_id:embedId,
					encrypted_content:await encrypt(JSON.stringify(index===0?parent:classes[index-1]),key),
					encrypted_type:await encrypt(index===0?'app_skill_use':'fitness-class',key),status:'finished',
					...(index===0?{}:{parent_embed_id:input.embedIds[0]}),
					hashed_chat_id:hash(input.chatId),hashed_message_id:hash(input.assistantMessageId),hashed_user_id:hash(owner.id),
					created_at:now,updated_at:now,version_number:1});
			}
			await send('store_embed_keys','store_embed_keys_confirmed',{keys:[{hashed_embed_id:hash(input.embedIds[0]),
				key_type:'master',hashed_chat_id:null,encrypted_embed_key:await encrypt(key,client.getMasterKeyBytes()),
				hashed_user_id:hash(owner.id),created_at:now}]});
			const saved=await client.getEmbed(input.embedIds[0],{preferCache:true,chatId:input.chatId});
			if(saved.content.app_id!=='fitness'||saved.content.skill_id!=='search_classes'||saved.content.status!=='finished')
				throw Error('Saved Fitness parent missing');
			for(const [index,id] of input.embedIds.slice(1).entries()){
				const child=await client.getEmbed(id,{preferCache:true,chatId:input.chatId});
				if(child.content.name!==classes[index].name||child.content.venue_lat!==classes[index].venue_lat)
					throw Error('Saved Fitness child missing');
			}
			process.stdout.write(JSON.stringify({ok:true}));
		}finally{ws.close()}
	`, {chatId:fixture.chatId,assistantMessageId:fixture.assistantMessageId,embedIds:fixture.embedIds,ownerId:fixture.ownerId});
	expect(result.ok).toBe(true);
}

const contract = {
	id: 'cli-tui-rich-chat-real-terminal', title: 'Encrypted Markdown chat, linked views, and Fitness preview',
	surface: 'cli', devices: [PROFILE],
	transcript: [
		{id: 'markdown', text: 'The saved assistant answer renders a styled heading, bold text, a wiki link, and a finished Fitness result below the text-only request.', checkpoint: 'chat-open', devices: [PROFILE]},
		{id: 'views', text: 'The first result switches between calendar, map, and list without losing its saved chat.', checkpoint: 'view-list', devices: [PROFILE]},
		{id: 'wiki', text: 'The exact wiki target opens and Escape returns to the chat.', checkpoint: 'wiki-return', devices: [PROFILE]},
		{id: 'fitness', text: 'The short Fitness alias opens the saved result and its real dated classes.', checkpoint: 'fitness-open', devices: [PROFILE]}
	],
	assertions: [
		{id: 'chats.rendering.inline-entity-interaction', checkpoint: 'chat-open', visual: 'A text-only user message remains plain, while the assistant Markdown and finished Fitness result render with a bottom preview bar.', devices: [PROFILE]},
		{id: 'cli.output.actionable-readable', checkpoint: 'view-list', visual: 'The saved class results can switch among calendar, text map, and list presentations.', devices: [PROFILE]},
		{id: 'cli.surface.semantic-parity', checkpoint: 'wiki-return', visual: 'The exact wiki target opens and Escape returns to the saved chat.', devices: [PROFILE]}
	],
	tutorial: {readingWordsPerSecond: 2.5, minimumHoldMs: 1200, maximumHoldMs: 5000}
};
const offlineContract = {
	id: 'cli-tui-rich-chat-offline-real-terminal', title: 'Saved Markdown chat and linked view offline',
	surface: 'cli', devices: [PROFILE],
	transcript: [
		{id: 'offline-chat', text: 'The encrypted chat reopens from the same saved local profile while the API is unavailable.', checkpoint: 'offline-chat-open', devices: [PROFILE]},
		{id: 'offline-view', text: 'The saved Fitness result still opens its map view offline.', checkpoint: 'offline-map', devices: [PROFILE]}
	],
	assertions: [
		{id: 'chats.rendering.inline-entity-interaction', checkpoint: 'offline-chat-open', visual: 'The saved assistant Markdown and Fitness preview reopen without an API connection.', devices: [PROFILE]},
		{id: 'cli.output.actionable-readable', checkpoint: 'offline-map', visual: 'The cached Fitness coordinates remain available as a readable map view.', devices: [PROFILE]}
	], tutorial: contract.tutorial
};

// contract-test: direct surface=cli assertions=chats.rendering.inline-entity-interaction,cli.output.actionable-readable,cli.surface.semantic-parity
test('records saved Markdown, linked Fitness views, wiki navigation, and offline replay in a real terminal', async ({page}: {page: any}, testInfo: any) => {
	test.setTimeout(360_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted' || process.env.CI_TEST_MODE !== 'e2e', 'Requires isolated GitHub product stack');
	skipWithoutCredentials(test, email, password, otpKey);
	const cli = requireIsolatedCliBuild();
	installRecorderDeps();
	const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('tui-rich-chat-proof');
	let chat: ChatFixture | undefined;
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CLI_TUI_RICH_CHAT_PROOF');
		chat = makeChatFixture(apiUrl, home, cli);
		persistChatFixture(chat, 'seed');
		seedFitnessEmbeds(apiUrl, home, cli, chat);
		const windowHealth = sdk(apiUrl, home, cli, `
			const response=await client.http.get('/v1/chats/'+input.chatId+'/messages/window?limit=30&respect_compression_boundary=false');
			process.stdout.write(JSON.stringify({status:response.status}));
		`, {chatId: chat.chatId});
		expect(windowHealth.status, 'Encrypted message window must be readable').toBe(200);
		clearWorkflowCliSyncCache(home);
		const steps: ProofStep[] = [
			{name: 'landing', wait_for: 'DAILY INSPIRATION', hold_ms: 250},
			{name: 'chat-command', text: '/chat ' + chat.chatId},
			{name: 'chat-open', key: 'Return', wait_for: 'Dance studio Mitte', hold_ms: 900},
			{name: 'view-calendar-command', text: '/view 1 calendar'},
			{name: 'view-calendar', key: 'Return', wait_for: 'Mapped results · Calendar · 2 results', hold_ms: 500},
			{name: 'view-map-key', text: 'm', wait_for: 'Mapped results · Map · 2 results', hold_ms: 350},
			{name: 'view-list-key', text: 'l', wait_for: 'Mapped results · List · 2 results', hold_ms: 350},
			{name: 'view-return', key: 'Escape', wait_for: 'Saved answer', hold_ms: 300},
			{name: 'view-map-command', text: '/view 1 map'},
			{name: 'view-map', key: 'Return', wait_for: 'Mapped results · Map · 2 results', hold_ms: 500},
			{name: 'view-map-return', key: 'Escape', wait_for: 'Saved answer', hold_ms: 300},
			{name: 'view-list-command', text: '/view 1 list'},
			{name: 'view-list', key: 'Return', wait_for: 'Mapped results · List · 2 results', hold_ms: 500},
			{name: 'view-list-return', key: 'Escape', wait_for: 'Saved answer', hold_ms: 300},
			{name: 'wiki-command', text: '/wiki Apple_Watch'},
			{name: 'wiki-open', key: 'Return', wait_for: 'Apple Watch', hold_ms: 650},
			{name: 'wiki-return', key: 'Escape', wait_for: 'Saved answer', hold_ms: 450},
			{name: 'fitness-command', text: '/embed fit-s_c-1'},
			{name: 'fitness-open', key: 'Return', wait_for: 'Dance fundamentals', hold_ms: 700},
			{name: 'fitness-return', key: 'Escape', wait_for: 'Saved answer', hold_ms: 300},
			{name: 'exit-command', text: '/exit'},
			{name: 'exit', key: 'Return'}
		];
		const recording = await captureProof(apiUrl, home, cli, steps, contract, testInfo);
		const frame = (name: string) => recording.frame(name).join('\n');
		const opened = frame('chat-open');
		expect(opened).toContain('Find local classes with a map and calendar.');
		expect(opened).toContain('Saved answer');
		expect(opened).not.toContain('### Saved answer');
		expect(opened).toContain('Nearby classes');
		expect(opened).not.toContain('**Nearby classes**');
		expect(opened).toContain('Apple Watch');
		expect(opened).toContain('/wiki Apple_Watch');
		expect(opened).not.toContain('[Apple Watch](wiki:Apple_Watch)');
		expect(opened).toContain('Dance search (/embed fit-s_c-1)');
		expect(opened).not.toContain('(embed:');
		expect(opened).toContain('/embed fit-s_c-1');
		expect(opened).toContain('Fitness · Search classes');
		expect(opened.indexOf('Fitness · Search classes')).toBeGreaterThan(opened.indexOf('Saved answer'));
		expect(opened).not.toContain('sources: parent');
		expect(opened).not.toContain('embeds_results_view');
		expect(opened).not.toContain('json_embed');
		const userStart = opened.indexOf('Find local classes with a map and calendar.');
		const assistantStart = opened.indexOf('Melvin', userStart);
		expect(userStart).toBeGreaterThanOrEqual(0);
		expect(assistantStart).toBeGreaterThan(userStart);
		expect(opened.slice(userStart, assistantStart)).not.toMatch(/Search classes|\/embed fit-s_c-1/);
		const before = Buffer.from(recording.transcript, 'utf8');
		const offset = recording.manifest.input_checkpoints.find((point: {name: string}) => point.name === 'chat-open')!.transcript_offset;
		const raw = before.subarray(0, offset).toString('utf8');
		const end = raw.lastIndexOf('\x1b[?2026l'), start = raw.lastIndexOf('\x1b[?2026h', end);
		expect(start).toBeGreaterThanOrEqual(0);
		const richFrame = raw.slice(start, end);
		// eslint-disable-next-line no-control-regex -- Match real terminal bold on the assistant's Markdown, not the chat header.
		expect(richFrame).toMatch(/\x1b\[1m\x1b\[38;2;\d+;\d+;\d+mNearby classes/);
		expect(frame('view-calendar')).toContain('Dance fundamentals');
		expect(frame('view-calendar')).toContain('2026-10-08');
		expect(frame('view-map-key')).toContain('Dance studio Mitte');
		expect(frame('view-map')).toContain('52.52');
		expect(frame('view-list')).toContain('Evening yoga');
		expect(frame('wiki-open')).toContain('Apple Watch');
		expect(frame('wiki-open')).not.toContain('Saved answer');
		expect(frame('wiki-return')).toContain('Saved answer');
		expect(frame('fitness-open')).toContain('2026-10-08');
		await recording.attest();

		const preload = path.join(home, 'offline-rich-chat-proof.cjs');
		fs.writeFileSync(preload, [
			"const apiOrigin = new URL(process.env.OPENMATES_API_URL).origin;",
			"const liveFetch = globalThis.fetch.bind(globalThis);",
			"globalThis.fetch = (input, init) => {",
			"  const url = typeof input === 'string' || input instanceof URL ? String(input) : input.url;",
			"  if (new URL(url).origin === apiOrigin) return Promise.reject(new TypeError('OFFLINE_PROOF_API_UNAVAILABLE'));",
			"  return liveFetch(input, init);",
			"};"
		].join('\n'), {encoding: 'utf8', mode: 0o600});
		const offlineSteps: ProofStep[] = [
			{name: 'offline-landing', wait_for: 'DAILY INSPIRATION'},
			{name: 'offline-chat-command', text: '/chat ' + chat.chatId},
			{name: 'offline-chat-open', key: 'Return', wait_for: 'Dance studio Mitte', hold_ms: 700},
			{name: 'offline-map-command', text: '/view 1 map'},
			{name: 'offline-map', key: 'Return', wait_for: 'Mapped results · Map · 2 results', hold_ms: 500},
			{name: 'offline-calendar', text: 'c', wait_for: 'Mapped results · Calendar · 2 results', hold_ms: 400},
			{name: 'offline-chat-return', key: 'Escape', wait_for: 'Saved answer', hold_ms: 350},
			{name: 'offline-exit-command', text: '/exit'},
			{name: 'offline-exit', key: 'Return'}
		];
		const offlineInfo = {
			outputPath: (...parts: string[]) => testInfo.outputPath('offline', ...parts),
			attach: (name: string, options: unknown) => testInfo.attach('offline-' + name, options)
		};
		const priorNodeOptions = process.env.NODE_OPTIONS;
		const offline = await (async (): Promise<Awaited<ReturnType<typeof captureProof>>> => {
			try {
				process.env.NODE_OPTIONS = [priorNodeOptions, `--require=${preload}`].filter(Boolean).join(' ');
				return await captureProof(apiUrl, home, cli, offlineSteps, offlineContract, offlineInfo);
			} finally {
				if (priorNodeOptions === undefined) delete process.env.NODE_OPTIONS;
				else process.env.NODE_OPTIONS = priorNodeOptions;
			}
		})();
		expect(offline.frame('offline-chat-open').join('\n')).toContain('Saved answer');
		expect(offline.frame('offline-map').join('\n')).toContain('Dance studio Mitte');
		expect(offline.frame('offline-calendar').join('\n')).toContain('2026-10-08');
		expect(offline.frame('offline-chat-return').join('\n')).toContain('Fitness · Search classes');
		await offline.attest();
	} finally {
		try { if (chat) persistChatFixture(chat, 'cleanup'); }
		finally { removeWorkflowCliHome(home); }
	}
});
