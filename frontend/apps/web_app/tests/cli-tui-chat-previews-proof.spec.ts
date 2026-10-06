/* eslint-disable @typescript-eslint/no-require-imports */
/** Real terminal proof of an encrypted saved chat and grouped Fitness results. */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';

const {test, expect, email, password, otpKey, captureProof, installRecorderDeps,
	seedWorkspace, cleanupWorkspace, newFixture, requireIsolatedCliBuild, workflowApiUrl,
	createWorkflowCliHome, skipWithoutCredentials} = require('./cli-tui-proof-helpers');
const {workflowCliEnv, clearWorkflowCliSyncCache} = require('./helpers/workflow-cli-e2e-helpers');
const {execFileSync} = require('node:child_process');
const {randomUUID} = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../../..');
const COMPOSE = path.join(ROOT, 'test-results/ci-private/compose.json');
const PROFILE = 'cli-terminal';

type ChatFixture = {chatId: string; messageId: string; embedId: string; ownerId: string;
	chat: Record<string, unknown>; message: Record<string, unknown>};

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
		const chatId=randomUUID(),messageId=randomUUID(),embedId=randomUUID();
		const key=randomBytes(32),master=client.getMasterKeyBytes(),now=Math.floor(Date.now()/1000);
		const title='Terminal fitness proof '+chatId.slice(0,8);
		const fence=String.fromCharCode(96).repeat(3);
		const content='Here are two local classes.\\n\\n'+fence+'json_embed\\n'+JSON.stringify({
			type:'app_skill_use',embed_id:embedId,app_id:'fitness',skill_id:'search_classes',
			status:'finished',query:'Dance in Berlin',result_count:2})+'\\n'+fence;
		const chat={id:chatId,hashed_user_id:hash(owner.id),created_at:now,updated_at:now,
			last_edited_overall_timestamp:now,last_message_timestamp:now,messages_v:1,title_v:1,metadata_v:1,
			unread_count:0,encrypted_chat_key:await encrypt(key,master),encrypted_title:await encrypt(title,key),
			encrypted_chat_summary:await encrypt('Two classes for an active evening.',key),
			encrypted_category:await encrypt('medical_health',key)};
		const message={id:messageId,client_message_id:messageId,message_id:messageId,chat_id:chatId,
			hashed_user_id:hash(owner.id),role:'assistant',created_at:now,updated_at:now,
			encrypted_sender_name:await encrypt('Assistant',key),encrypted_category:await encrypt('medical_health',key),
			encrypted_content:await encrypt(content,key)};
		process.stdout.write(JSON.stringify({chatId,messageId,embedId,ownerId:owner.id,chat,message}));
	`);
}

function persistChatFixture(fixture: ChatFixture, operation: 'seed' | 'cleanup'): void {
	expect(fs.existsSync(COMPOSE), 'Requires the disposable isolated CI compose').toBe(true);
	const program = `
import asyncio,hashlib,json,logging,sys
logging.disable(logging.CRITICAL)
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
                messages=await directus.chat.get_all_messages_for_chat(data['chatId'],decrypt_content=False)
                for raw_message in messages or []:
                    message=json.loads(raw_message) if isinstance(raw_message,str) else raw_message
                    if message.get('client_message_id')==data['messageId']:
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

function seedFitnessEmbed(apiUrl: string, home: string, cli: string, fixture: ChatFixture): void {
	const result = sdk(apiUrl, home, cli, `
		const owner=await client.whoAmI();if(owner.id!==input.ownerId)throw Error('Fixture owner changed');
		const now=Math.floor(Date.now()/1000),key=randomBytes(32);
		const results=[
			{name:'Dance fundamentals',date:'2026-10-08',time_range:'18:00–19:00',venue_name:'Dance studio Mitte',
				venue_address:'Example Str. 12, Berlin',distance_km:1.25,plans_required:['M','L'],
				disciplines:['Dance'],spots_display:'4 spots',detail_url:'https://example.org/fitness/dance'},
			{name:'Evening yoga',date:'2026-10-09',time_range:'19:00–20:00',venue_name:'Yoga studio Kreuzberg',
				venue_address:'Sample Str. 4, Berlin',distance_km:2.50,plans_required:['S','M','L'],
				disciplines:['Yoga'],spots_display:'6 spots',detail_url:'https://example.org/fitness/yoga'}
		];
		const content={app_id:'fitness',skill_id:'search_classes',status:'finished',provider:'Urban Sports Club',
			query:'Dance in Berlin',results:[{provider:'Urban Sports Club',filters:{city:'Berlin',radius_km:5},
				summary:'Two nearby classes',result_count:2,results}]};
		const {ws}=await client.openWsClient({taskUpdateJobs:false});
		const send=async(type,reply,payload)=>{const requestId=randomUUID(),receipt=ws.waitForMessage(reply,p=>p.request_id===requestId,30000);
			await ws.sendAsync(type,{...payload,request_id:requestId});return (await receipt).payload};
		try{
			await send('store_embed','store_embed_confirmed',{embed_id:input.embedId,
				encrypted_content:await encrypt(JSON.stringify(content),key),
				encrypted_type:await encrypt('app_skill_use',key),status:'finished',
				hashed_chat_id:hash(input.chatId),hashed_message_id:hash(input.messageId),hashed_user_id:hash(owner.id),
				created_at:now,updated_at:now,version_number:1});
			await send('store_embed_keys','store_embed_keys_confirmed',{keys:[{hashed_embed_id:hash(input.embedId),
				key_type:'master',hashed_chat_id:null,encrypted_embed_key:await encrypt(key,client.getMasterKeyBytes()),
				hashed_user_id:hash(owner.id),created_at:now}]});
			const saved=await client.getEmbed(input.embedId,{preferCache:true,chatId:input.chatId});
			if(saved.content.app_id!=='fitness'||saved.content.skill_id!=='search_classes')throw Error('Saved Fitness embed missing');
			process.stdout.write(JSON.stringify({ok:true}));
		}finally{ws.close()}
	`, {chatId:fixture.chatId,messageId:fixture.messageId,embedId:fixture.embedId,ownerId:fixture.ownerId});
	expect(result.ok).toBe(true);
}

const contract = {
	id:'cli-tui-chat-fitness-real-terminal',title:'Encrypted terminal chat and Fitness results',
	surface:'cli',devices:[PROFILE],
	transcript:[
		{id:'chat',text:'A saved encrypted chat opens with a medical category header, Melvin, and two Fitness results.',checkpoint:'chat-open',devices:[PROFILE]},
		{id:'selection',text:'Ctrl+Y exposes terminal text selection and resumes the chat composer.',checkpoint:'selection-resume',devices:[PROFILE]},
		{id:'embeds',text:'Short aliases open the grouped search and then the second class detail.',checkpoint:'class-detail',devices:[PROFILE]},
		{id:'escape',text:'Escape returns to the origin chat and then to the Chats landing page.',checkpoint:'landing',devices:[PROFILE]},
		{id:'workspaces',text:'Projects and Workflows use horizontal cards; Tasks uses a five-column board.',checkpoint:'tasks-home',devices:[PROFILE]},
	],
	assertions:[
		{id:'chats.rendering.inline-entity-interaction',checkpoint:'chat-open',visual:'The decrypted message shows a finished Fitness card with two class summaries and /embed fit-s_c-1.',devices:[PROFILE]},
		{id:'cli.output.actionable-readable',checkpoint:'class-detail',visual:'The second class opens with date, time, studio, distance and required plans.',devices:[PROFILE]},
		{id:'cli.surface.semantic-parity',checkpoint:'landing',visual:'A category-colored bold chat header, workspace-colored navigation, visible cursor, text selection hint and Escape route are present in the real terminal.',devices:[PROFILE]},
		{id:'app-skills.surface.semantic-parity',checkpoint:'tasks-home',visual:'The Projects and Workflows cards and responsive Tasks Kanban board are present.',devices:[PROFILE]},
	],
	tutorial:{readingWordsPerSecond:2.5,minimumHoldMs:1200,maximumHoldMs:5000},
};

// contract-test: direct surface=cli assertions=chats.rendering.inline-entity-interaction,cli.output.actionable-readable,cli.surface.semantic-parity,app-skills.surface.semantic-parity
test('records encrypted chat, short Fitness aliases, selection, Escape, and workspace cards', async ({page}: {page: any}, testInfo: any) => {
	test.setTimeout(360_000);
	test.skip(process.env.GITHUB_ACTIONS!=='true'||process.env.RUNNER_ENVIRONMENT!=='github-hosted'||process.env.CI_TEST_MODE!=='e2e', 'Requires isolated GitHub product stack');
	skipWithoutCredentials(test,email,password,otpKey);
	const cli=requireIsolatedCliBuild();installRecorderDeps();
	const apiUrl=workflowApiUrl(),home=createWorkflowCliHome('tui-chat-previews'),workspace=newFixture();
	workspace.projectName='Proof project '+randomUUID().slice(0,6);
	workspace.workflowTitle='Proof workflow '+randomUUID().slice(0,6);
	let chat:ChatFixture|undefined;
	try{
		await seedWorkspace(page,apiUrl,home,workspace,false);
		chat=makeChatFixture(apiUrl,home,cli);
		persistChatFixture(chat,'seed');
		seedFitnessEmbed(apiUrl,home,cli,chat);
        // Retain the exact server error without plaintext messages or credentials.
        const windowHealth=sdk(apiUrl,home,cli,`
            const response=await client.http.get('/v1/chats/'+input.chatId+'/messages/window?limit=30&respect_compression_boundary=false');
            process.stdout.write(JSON.stringify({status:response.status,detail:response.ok?null:response.data?.detail??null}));
        `,{chatId:chat.chatId});
        await testInfo.attach('chat-message-window-health',{body:Buffer.from(JSON.stringify(windowHealth)),contentType:'application/json'});
        expect(windowHealth.status,'Encrypted message endpoint: '+JSON.stringify(windowHealth.detail)).toBe(200);
		clearWorkflowCliSyncCache(home);
		const steps:(ProofStep & {wait_timeout_ms?:number})[]=[
			{name:'landing-initial',wait_for:'DAILY INSPIRATION',hold_ms:350},
			{name:'missing-chat-command',text:'/chat '+randomUUID()},
			{name:'missing-chat-error',key:'Return',wait_for:'Could not load chat',wait_for_absent:'Loading chat…',hold_ms:350},
			{name:'missing-chat-back',key:'Escape',wait_for:'DAILY INSPIRATION',hold_ms:200},
			{name:'chat-command',text:'/chat '+chat.chatId},
			{name:'chat-open',key:'Return',wait_for:'Dance studio Mitte',wait_for_absent:'Loading chat…',wait_timeout_ms:30_000,hold_ms:1300},
			{name:'selection-on',key:'ctrl+y',wait_for:'Select text: drag to highlight',hold_ms:700},
			{name:'selection-resume',key:'ctrl+y',wait_for:'Ask a follow-up',hold_ms:350},
			{name:'root-command',text:'/embed fit-s_c-1'},
			{name:'root-detail',key:'Return',wait_for:'/embed fit-s_c-1-2',hold_ms:900},
			{name:'class-command',text:'/embed fit-s_c-1-2'},
			{name:'class-detail',key:'Return',wait_for:'Yoga studio Kreuzberg',hold_ms:1000},
			{name:'escape-to-chat',key:'Escape',wait_for:'Dance studio Mitte',hold_ms:650},
			{name:'landing',key:'Escape',wait_for:'DAILY INSPIRATION',hold_ms:500},
			{name:'projects-command',text:'/projects'},
			{name:'projects-home',key:'Return',wait_for:workspace.projectName,hold_ms:700},
			{name:'workflows-command',text:'/workflows'},
			{name:'workflows-home',key:'Return',wait_for:workspace.workflowTitle,hold_ms:700},
			{name:'tasks-command',text:'/tasks'},
			{name:'tasks-home',key:'Return',wait_for:workspace.taskTitle,hold_ms:700},
			{name:'exit-command',text:'/exit'},
			{name:'exit',key:'Return'},
		];
		const recording=await captureProof(apiUrl,home,cli,steps,contract,testInfo);
		const frame=(name:string)=>recording.frame(name).join('\n');
		expect(frame('missing-chat-error')).toContain('/refresh to retry');
		expect(frame('missing-chat-error')).not.toContain('Creating new chat');
		const opened=frame('chat-open');
		const chatCheckpoint=recording.manifest.input_checkpoints.find((point: {name:string})=>point.name==='chat-open');
		expect(chatCheckpoint).toBeTruthy();
		const rawBeforeChat=Buffer.from(recording.transcript,'utf8').subarray(0,chatCheckpoint!.transcript_offset).toString('utf8');
		const rawEnd=rawBeforeChat.lastIndexOf('\x1b[?2026l');
		const rawStart=rawBeforeChat.lastIndexOf('\x1b[?2026h',rawEnd);
		expect(rawStart).toBeGreaterThanOrEqual(0);
		expect(rawEnd).toBeGreaterThan(rawStart);
		const rawChat=rawBeforeChat.slice(rawStart,rawEnd);
		expect(opened).toContain('Medical Health');
		expect(opened).toContain('Melvin');
		expect(opened).toContain('Dance studio Mitte');
		expect(opened).toContain('Yoga studio Kreuzberg');
		expect(opened).toContain('/embed fit-s_c-1');
		expect(opened.split('\n')[0]).not.toContain('Terminal fitness proof');
		// eslint-disable-next-line no-control-regex -- Verify truecolor and cursor escape sequences from the real terminal.
		expect(rawChat).toMatch(/\x1b\[1m\x1b\[38;2;255;255;255m\x1b\[48;2;253;80;160m/);
		// eslint-disable-next-line no-control-regex -- Verify the active workspace's orange ANSI foreground.
		expect(rawChat).toMatch(/\x1b\[1m\x1b\[38;2;255;85;59m\[Chats\]/);
		// eslint-disable-next-line no-control-regex -- Visible composer caret is emitted after terminal row writes.
		expect(rawChat).toMatch(/\x1b\[\d+;\d+H\x1b\[\?25h/);
		expect(frame('selection-on')).toContain('Select text: drag to highlight');
		expect(frame('selection-resume')).not.toContain('Select text: drag to highlight');
		const root=frame('root-detail');
		expect(root).toContain('2 classes');
		expect(root).toContain('/embed fit-s_c-1-2');
		expect(root).toContain('Dance studio Mitte');
		expect(root).toContain('Yoga studio Kreuzberg');
		const selected=frame('class-detail');
		for(const value of ['Evening yoga','2026-10-09','19:00–20:00','Yoga studio Kreuzberg','2.50 km','Plans: S, M, L'])expect(selected).toContain(value);
		expect(frame('escape-to-chat')).toContain('Melvin');
		expect(frame('landing')).toContain('DAILY INSPIRATION');
		expect(frame('landing').split('\n')[0]).not.toContain('Terminal fitness proof');
		expect(frame('projects-home')).toContain(workspace.projectName);
		expect(frame('projects-home')).toMatch(/Project 1 of \d+/);
		expect(frame('workflows-home')).toContain(workspace.workflowTitle);
		expect(frame('workflows-home')).toMatch(/Workflow 1 of \d+/);
		for(const status of ['Backlog','Todo','In progress','Blocked','Done'])expect(frame('tasks-home')).toContain(status);
		expect(frame('tasks-home')).toMatch(/Backlog \(\d+\)\s+Todo \(\d+\)\s+In progress \(\d+\)\s+Blocked \(\d+\)\s+Done \(\d+\)/);
		await recording.attest();
	}finally{
		try { if(chat)persistChatFixture(chat,'cleanup'); }
		finally { await cleanupWorkspace(apiUrl,home,workspace); }
	}
});
