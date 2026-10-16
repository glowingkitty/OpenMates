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

type ChatFixture = {chatId: string; userMessageId: string; assistantMessageId: string;
	embedIds: [string,string]; ownerId: string; chat: Record<string, unknown>;
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
		const embedIds=[randomUUID(),randomUUID()];
		const key=randomBytes(32),master=client.getMasterKeyBytes(),now=Math.floor(Date.now()/1000);
		const title='Terminal fitness proof '+chatId.slice(0,8);
		const fence=String.fromCharCode(96).repeat(3);
		const content='Here are two local searches.\\n\\n'+embedIds.map((embedId,index)=>fence+'json_embed\\n'+JSON.stringify({
			type:'app_skill_use',embed_id:embedId,app_id:'fitness',skill_id:'search_classes',
			status:'finished',query:index===0?'Dance in Berlin':'Yoga in Berlin',result_count:2})+'\\n'+fence).join('\\n\\n');
		const chat={id:chatId,hashed_user_id:hash(owner.id),created_at:now,updated_at:now,
			last_edited_overall_timestamp:now,last_message_timestamp:now,messages_v:1,title_v:1,metadata_v:1,
			unread_count:0,encrypted_chat_key:await encrypt(key,master),encrypted_title:await encrypt(title,key),
			encrypted_chat_summary:await encrypt('Two classes for an active evening.',key),
			encrypted_category:await encrypt('medical_health',key)};
		const userMessage={id:userMessageId,client_message_id:userMessageId,message_id:userMessageId,chat_id:chatId,
			hashed_user_id:hash(owner.id),role:'user',created_at:now-1,updated_at:now-1,
			encrypted_sender_name:await encrypt('You',key),encrypted_category:await encrypt('medical_health',key),
			encrypted_content:await encrypt('Find two local Fitness class searches in Berlin.',key)};
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
		const now=Math.floor(Date.now()/1000);
		const danceResults=[
			{name:'Dance fundamentals',date:'2026-10-08',time_range:'18:00–19:00',venue_name:'Dance studio Mitte',
				venue_address:'Example Str. 12, Berlin',distance_km:1.25,plans_required:['M','L'],
				disciplines:['Dance'],spots_display:'4 spots',detail_url:'https://example.org/fitness/dance'},
			{name:'Evening yoga',date:'2026-10-09',time_range:'19:00–20:00',venue_name:'Yoga studio Kreuzberg',
				venue_address:'Sample Str. 4, Berlin',distance_km:2.50,plans_required:['S','M','L'],
				disciplines:['Yoga'],spots_display:'6 spots',detail_url:'https://example.org/fitness/yoga'}
		];
		const yogaResults=[
			{name:'Morning pilates',date:'2026-10-10',time_range:'09:00–10:00',venue_name:'Pilates studio Prenzlauer Berg',
				venue_address:'Example Allee 9, Berlin',distance_km:3.10,plans_required:['M','L'],
				disciplines:['Pilates'],spots_display:'3 spots',detail_url:'https://example.org/fitness/pilates'},
			{name:'Strength basics',date:'2026-10-11',time_range:'17:00–18:00',venue_name:'Training studio Wedding',
				venue_address:'Sample Weg 2, Berlin',distance_km:4.20,plans_required:['L'],
				disciplines:['Strength'],spots_display:'5 spots',detail_url:'https://example.org/fitness/strength'}
		];
		const {ws}=await client.openWsClient({taskUpdateJobs:false});
		const send=async(type,reply,payload)=>{const requestId=randomUUID(),receipt=ws.waitForMessage(reply,p=>p.request_id===requestId,30000);
			await ws.sendAsync(type,{...payload,request_id:requestId});return (await receipt).payload};
		try{
			for(const [index,embedId] of input.embedIds.entries()){
				const key=randomBytes(32),content={app_id:'fitness',skill_id:'search_classes',status:'finished',
					provider:'Urban Sports Club',query:index===0?'Dance in Berlin':'Yoga in Berlin',
					results:[{provider:'Urban Sports Club',filters:{city:'Berlin',radius_km:5},
						summary:index===0?'Two nearby classes':'Two more nearby classes',result_count:2,
						results:index===0?danceResults:yogaResults}]};
				await send('store_embed','store_embed_confirmed',{embed_id:embedId,
					encrypted_content:await encrypt(JSON.stringify(content),key),
					encrypted_type:await encrypt('app_skill_use',key),status:'finished',
					hashed_chat_id:hash(input.chatId),hashed_message_id:hash(input.userMessageId),hashed_user_id:hash(owner.id),
					created_at:now,updated_at:now,version_number:1});
				await send('store_embed_keys','store_embed_keys_confirmed',{keys:[{hashed_embed_id:hash(embedId),
					key_type:'master',hashed_chat_id:null,encrypted_embed_key:await encrypt(key,client.getMasterKeyBytes()),
					hashed_user_id:hash(owner.id),created_at:now}]});
				const saved=await client.getEmbed(embedId,{preferCache:true,chatId:input.chatId});
				if(saved.content.app_id!=='fitness'||saved.content.skill_id!=='search_classes')throw Error('Saved Fitness embed missing');
			}
			process.stdout.write(JSON.stringify({ok:true}));
		}finally{ws.close()}
	`, {chatId:fixture.chatId,userMessageId:fixture.userMessageId,embedIds:fixture.embedIds,ownerId:fixture.ownerId});
	expect(result.ok).toBe(true);
}

const contract = {
	id:'cli-tui-chat-fitness-real-terminal',title:'Encrypted terminal chat and Fitness carousel',
	surface:'cli',devices:[PROFILE],
	transcript:[
		{id:'chat',text:'A text-only user request has no card. Melvin references two encrypted Fitness searches in a horizontal carousel.',checkpoint:'chat-open',devices:[PROFILE]},
		{id:'carousel',text:'Shift+Tab focuses the carousel. Left and Right choose its cards; Enter opens the second search.',checkpoint:'keyboard-root-detail',devices:[PROFILE]},
		{id:'navigation',text:'Ctrl+G focuses cyan navigation while its shortcut hint remains grey.',checkpoint:'navigation-focus',devices:[PROFILE]},
		{id:'selection',text:'Ctrl+Y exposes terminal text selection and resumes the chat composer.',checkpoint:'selection-resume',devices:[PROFILE]},
		{id:'embeds',text:'Short aliases open the grouped search and then the second class detail.',checkpoint:'class-detail',devices:[PROFILE]},
		{id:'escape',text:'Escape returns to the origin chat and then to the Chats landing page.',checkpoint:'landing',devices:[PROFILE]},
		{id:'workspaces',text:'Projects and Workflows use horizontal cards; Tasks uses a five-column board.',checkpoint:'tasks-home',devices:[PROFILE]},
	],
	assertions:[
		{id:'chats.rendering.inline-entity-interaction',checkpoint:'chat-open',visual:'The text-only user message has no embed card; Melvin owns a finished Fitness carousel with two distinct search roots.',devices:[PROFILE]},
		{id:'cli.output.actionable-readable',checkpoint:'class-detail',visual:'The second class opens with date, time, studio, distance and required plans.',devices:[PROFILE]},
		{id:'cli.surface.semantic-parity',checkpoint:'landing',visual:'A category-colored bold chat header, workspace-colored navigation, visible cursor, text selection hint and Escape route are present in the real terminal.',devices:[PROFILE]},
		{id:'app-skills.surface.semantic-parity',checkpoint:'tasks-home',visual:'The Projects and Workflows cards and responsive Tasks Kanban board are present.',devices:[PROFILE]},
	],
	tutorial:{readingWordsPerSecond:2.5,minimumHoldMs:1200,maximumHoldMs:5000},
};

// contract-test: direct surface=cli assertions=chats.rendering.inline-entity-interaction,cli.output.actionable-readable,cli.surface.semantic-parity,app-skills.surface.semantic-parity
test('records encrypted text-only request, Fitness carousel, aliases, and workspace navigation', async ({page}: {page: any}, testInfo: any) => {
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
		seedFitnessEmbeds(apiUrl,home,cli,chat);
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
			{name:'carousel-focus',key:'shift+Tab',wait_for:'←/→ embed',hold_ms:500},
			{name:'carousel-next',key:'Right',wait_for:'/embed fit-s_c-2',hold_ms:650},
			{name:'carousel-prev',key:'Left',wait_for:'/embed fit-s_c-1',hold_ms:500},
			{name:'carousel-next-again',key:'Right',wait_for:'/embed fit-s_c-2',hold_ms:450},
			{name:'keyboard-root-detail',key:'Return',wait_for:'Pilates studio Prenzlauer Berg',hold_ms:900},
			{name:'keyboard-back-to-chat',key:'Escape',wait_for:'Melvin',hold_ms:500},
			{name:'navigation-focus',key:'ctrl+g',wait_for:'Ctrl+G navigation',hold_ms:650},
			{name:'navigation-to-composer',key:'shift+Tab',wait_for:'Ask a follow-up',hold_ms:350},
			{name:'selection-on',key:'ctrl+y',wait_for:'Select text: drag to highlight',hold_ms:700},
			{name:'selection-resume',key:'ctrl+y',wait_for:'Ask a follow-up',hold_ms:350},
			{name:'root-command',text:'/embed fit-s_c-1'},
			{name:'root-detail',key:'Return',wait_for:'/embed fit-s_c-1-2',hold_ms:900},
			{name:'class-command',text:'/embed fit-s_c-1-2'},
			{name:'class-detail',key:'Return',wait_for:'Yoga studio Kreuzberg',hold_ms:1000},
			{name:'escape-to-chat',key:'Escape',wait_for:'Melvin',hold_ms:650},
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
		expect(opened).toContain('Find two local Fitness class searches in Berlin.');
		expect(opened).toContain('Melvin');
		const userSection=opened.slice(opened.indexOf('Find two local Fitness class searches in Berlin.'),opened.indexOf('Melvin'));
		expect(userSection).not.toMatch(/Search classes|Urban Sports Club|\/embed /);
		expect(opened).toContain('Dance studio Mitte');
		expect(opened).toContain('/embed fit-s_c-1');
		expect(opened).toContain('Embed 1/2');
		for(const checkpoint of ['chat-open','carousel-focus','carousel-next','carousel-prev','carousel-next-again','keyboard-back-to-chat']) {
			const shown=frame(checkpoint);
			const request=shown.indexOf('Find two local Fitness class searches in Berlin.'),assistant=shown.indexOf('Melvin');
			expect(request).toBeGreaterThanOrEqual(0);
			expect(assistant).toBeGreaterThan(request);
			expect(shown.slice(request,assistant)).not.toMatch(/Search classes|Urban Sports Club|\/embed /);
			expect(shown).not.toContain('/embed emb-v');
		}
		expect(opened.split('\n')[0]).not.toContain('Terminal fitness proof');
		// eslint-disable-next-line no-control-regex -- Verify truecolor and cursor escape sequences from the real terminal.
		expect(rawChat).toMatch(/\x1b\[1m\x1b\[38;2;255;255;255m\x1b\[48;2;253;80;160m/);
		// The recorder resizes its pixel window after launching the terminal, so measure the rendered
		// column count. The workspace uses a two-cell gutter per side and caps content at 180 cells.
		const terminalColumns=recording.frame('chat-open')[0].length;
		const expectedWorkspaceWidth=Math.min(180,terminalColumns-4);
		expect(expectedWorkspaceWidth).toBeGreaterThan(100);
		// eslint-disable-next-line no-control-regex -- Measure the emitted truecolor header span.
		const headerSpan=rawChat.match(/\x1b\[48;2;253;80;160m([^\x1b]*)\x1b\[0m/);
		expect(headerSpan?.[1].length).toBe(expectedWorkspaceWidth);
		const composerBorder=recording.frame('chat-open').find((row:string)=>/^\s+╭─+╮\s+$/.test(row));
		expect(composerBorder).toBeTruthy();
		expect(composerBorder.indexOf('╮')-composerBorder.indexOf('╭')+1).toBe(100);
		// eslint-disable-next-line no-control-regex -- Verify the active workspace's orange ANSI foreground.
		expect(rawChat).toMatch(/\x1b\[1m\x1b\[38;2;255;85;59m\[Chats\]/);
		// eslint-disable-next-line no-control-regex -- Visible composer caret is emitted after terminal row writes.
		expect(rawChat).toMatch(/\x1b\[\d+;\d+H\x1b\[\?25h/);
		expect(frame('carousel-focus')).toContain('←/→ embed');
		expect(frame('carousel-next')).toContain('Embed 2/2');
		expect(frame('carousel-next')).toContain('/embed fit-s_c-2');
		expect(frame('carousel-next')).toContain('Pilates studio Prenzlauer Berg');
		expect(frame('carousel-prev')).toContain('Embed 1/2');
		expect(frame('carousel-prev')).toContain('Dance studio Mitte');
		expect(frame('carousel-next-again')).toContain('Embed 2/2');
		expect(frame('keyboard-root-detail')).toContain('Two more nearby classes');
		expect(frame('keyboard-root-detail')).toContain('Pilates studio Prenzlauer Berg');
		expect(frame('keyboard-back-to-chat')).toContain('Melvin');
		const navigationCheckpoint=recording.manifest.input_checkpoints.find((point: {name:string})=>point.name==='navigation-focus');
		expect(navigationCheckpoint).toBeTruthy();
		const rawBeforeNavigation=Buffer.from(recording.transcript,'utf8').subarray(0,navigationCheckpoint!.transcript_offset).toString('utf8');
		const navEnd=rawBeforeNavigation.lastIndexOf('\x1b[?2026l'),navStart=rawBeforeNavigation.lastIndexOf('\x1b[?2026h',navEnd);
		const rawNavigation=rawBeforeNavigation.slice(navStart,navEnd);
		// eslint-disable-next-line no-control-regex -- Verify focused cyan navigation and grey shortcut hint in the real terminal.
		expect(rawNavigation).toMatch(/\x1b\[1m\x1b\[38;2;50;173;230m/);
		// eslint-disable-next-line no-control-regex -- Verify the shortcut hint remains grey when navigation has focus.
		expect(rawNavigation).toMatch(/\x1b\[38;2;128;128;128mCtrl\+G navigation/);
		expect(frame('navigation-to-composer')).toContain('Ask a follow-up');
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
		const boardHeader=frame('tasks-home').split('\n').find((row:string)=>/▌\s+Backlog \(\d+\)/.test(row));
		expect(boardHeader).toMatch(/▌\s+Backlog \(\d+\)\s+▌\s+Todo \(\d+\)\s+▌\s+In progress \(\d+\)\s+▌\s+Blocked \(\d+\)\s+▌\s+Done \(\d+\)/);
		expect((boardHeader?.match(/▌/g)??[]).length).toBe(5);
		await recording.attest();
	}finally{
		try { if(chat)persistChatFixture(chat,'cleanup'); }
		finally { await cleanupWorkspace(apiUrl,home,workspace); }
	}
});

const AUDIO_TRANSCRIPT = 'Please check the Berlin forecast for tomorrow morning and tell me whether I should bring a light rain jacket when I leave for the station, because the walk is long and I will be outside for several hours after breakfast.';
const AUDIO_PREVIEW = AUDIO_TRANSCRIPT.slice(0,119)+'…';

function makeAppPreviewFixture(apiUrl: string, home: string, cli: string): ChatFixture {
	return sdk(apiUrl,home,cli,`
		const owner=await client.whoAmI();
		if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal account');
		const chatId=randomUUID(),userMessageId=randomUUID(),assistantMessageId=randomUUID();
		const embedIds=[randomUUID(),randomUUID()],key=randomBytes(32),master=client.getMasterKeyBytes();
		const now=Math.floor(Date.now()/1000),fence=String.fromCharCode(96).repeat(3);
		const reference=(embedId,appId,skillId)=>fence+'json_embed\\n'+JSON.stringify({
			type:'app_skill_use',embed_id:embedId,app_id:appId,skill_id:skillId,status:'finished'})+'\\n'+fence;
		const chat={id:chatId,hashed_user_id:hash(owner.id),created_at:now,updated_at:now,
			last_edited_overall_timestamp:now,last_message_timestamp:now,messages_v:1,title_v:1,metadata_v:1,
			unread_count:0,encrypted_chat_key:await encrypt(key,master),
			encrypted_title:await encrypt('Audio and Weather preview proof',key),
			encrypted_chat_summary:await encrypt('A recorded question and forecast.',key),
			encrypted_category:await encrypt('weather',key)};
		const message=async(id,role,createdAt,content)=>({id,client_message_id:id,message_id:id,chat_id:chatId,
			hashed_user_id:hash(owner.id),role,created_at:createdAt,updated_at:createdAt,
			encrypted_sender_name:await encrypt(role==='user'?'You':'Assistant',key),
			encrypted_category:await encrypt('weather',key),encrypted_content:await encrypt(content,key)});
		const messages=[await message(userMessageId,'user',now-1,reference(embedIds[0],'audio','transcribe')),
			await message(assistantMessageId,'assistant',now,'Here is the Berlin forecast.\\n\\n'+reference(embedIds[1],'weather','forecast'))];
		process.stdout.write(JSON.stringify({chatId,userMessageId,assistantMessageId,embedIds,ownerId:owner.id,chat,messages}));
	`);
}

function seedAppPreviewEmbeds(apiUrl: string, home: string, cli: string, fixture: ChatFixture): void {
	const result=sdk(apiUrl,home,cli,`
		const owner=await client.whoAmI();if(owner.id!==input.ownerId)throw Error('Fixture owner changed');
		const now=Math.floor(Date.now()/1000),{ws}=await client.openWsClient({taskUpdateJobs:false});
		const send=async(type,reply,payload)=>{const requestId=randomUUID(),receipt=ws.waitForMessage(reply,p=>p.request_id===requestId,30000);
			await ws.sendAsync(type,{...payload,request_id:requestId});return (await receipt).payload};
		const content=[{app_id:'audio',skill_id:'transcribe',type:'audio-recording',status:'finished',
			filename:'berlin-weather-question.wav',title:'Berlin weather question',transcript:input.transcript,
			transcript_original:'Original voice recognition differs from the corrected question.',
			transcript_corrected:input.transcript,use_corrected:true},
			{app_id:'weather',skill_id:'forecast',status:'finished',title:'Berlin forecast',
				summary:'Cloudy with a chance of light rain tomorrow morning.'}];
		try{
			for(const [index,embedId] of input.embedIds.entries()){
				const key=randomBytes(32),value=content[index];
				await send('store_embed','store_embed_confirmed',{embed_id:embedId,
					encrypted_content:await encrypt(JSON.stringify(value),key),
					encrypted_type:await encrypt(index===0?'audio-recording':'app_skill_use',key),status:'finished',
					hashed_chat_id:hash(input.chatId),hashed_message_id:hash(index===0?input.userMessageId:input.assistantMessageId),
					hashed_user_id:hash(owner.id),created_at:now,updated_at:now,version_number:1});
				await send('store_embed_keys','store_embed_keys_confirmed',{keys:[{hashed_embed_id:hash(embedId),
					key_type:'master',hashed_chat_id:null,encrypted_embed_key:await encrypt(key,client.getMasterKeyBytes()),
					hashed_user_id:hash(owner.id),created_at:now}]});
				const saved=await client.getEmbed(embedId,{preferCache:true,chatId:input.chatId});
				if(saved.content.app_id!==value.app_id||saved.content.skill_id!==value.skill_id)throw Error('Saved app embed missing');
			}
			// Seed ciphertext into the isolated CLI cache after the saved chat enters its synced census.
			await client.listChats(20,1,{forceRefresh:true});
			const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
			const home=process.env.HOME;
			if(!home||!home.startsWith(os.tmpdir()+path.sep))throw Error('Expected isolated CLI home');
			const cachePath=path.join(home,'.openmates','sync_cache.json');
			const cache=JSON.parse(fs.readFileSync(cachePath,'utf8'));
			const row=cache.chats.find(chat=>chat.details.id===input.chatId);
			if(!row)throw Error('Saved chat missing from isolated CLI census');
			const chats=cache.chats.map(chat=>chat===row?{...chat,messages:input.messages.map(JSON.stringify)}:chat);
			fs.writeFileSync(cachePath,JSON.stringify({...cache,chats},null,2)+'\\n',{mode:0o600});
			const savedChat=await client.getChatMessages(input.chatId,{preferCache:true,maxHistoryPages:1});
			if(savedChat.messages.length!==2)throw Error('Saved chat messages missing');
			process.stdout.write(JSON.stringify({ok:true}));
		}finally{ws.close()}
	`,{...fixture,transcript:AUDIO_TRANSCRIPT});
	expect(result.ok).toBe(true);
}

const appPreviewContract={
	id:'cli-tui-chat-app-previews-real-terminal',title:'Saved audio recording and Weather forecast previews',
	surface:'cli',devices:[PROFILE],
	transcript:[
		{id:'chat',text:'A saved voice recording precedes the assistant forecast. Each preview shows its own app identity and background.',checkpoint:'app-chat-open',devices:[PROFILE]},
		{id:'shortcuts',text:'The user recording and assistant forecast have separate short embed commands.',checkpoint:'app-chat-open',devices:[PROFILE]},
	],
	assertions:[
		{id:'chats.rendering.inline-entity-interaction',checkpoint:'app-chat-open',visual:'The user audio transcript is shortened, the forecast belongs to the assistant, and both embeds have their own shortcut.',devices:[PROFILE]},
		{id:'cli.surface.semantic-parity',checkpoint:'app-chat-open',visual:'Audio and Weather previews emit their exact app colors and readable foregrounds in the real terminal.',devices:[PROFILE]},
	],
	tutorial:{readingWordsPerSecond:2.5,minimumHoldMs:1200,maximumHoldMs:5000},
};

// contract-test: direct surface=cli assertions=chats.rendering.inline-entity-interaction,cli.surface.semantic-parity
test('records saved user audio and assistant Weather previews with distinct app colors',async({page}:{page:any},testInfo:any)=>{
	test.setTimeout(240_000);
	test.skip(process.env.GITHUB_ACTIONS!=='true'||process.env.RUNNER_ENVIRONMENT!=='github-hosted'||process.env.CI_TEST_MODE!=='e2e','Requires isolated GitHub product stack');
	skipWithoutCredentials(test,email,password,otpKey);
	const cli=requireIsolatedCliBuild();installRecorderDeps();
	const apiUrl=workflowApiUrl(),home=createWorkflowCliHome('tui-app-previews'),workspace=newFixture();
	let chat:ChatFixture|undefined;
	try{
		await seedWorkspace(page,apiUrl,home,workspace,false);
		chat=makeAppPreviewFixture(apiUrl,home,cli);
		persistChatFixture(chat,'seed');
		seedAppPreviewEmbeds(apiUrl,home,cli,chat);
		const steps:(ProofStep & {wait_timeout_ms?:number})[]=[
			{name:'app-landing',wait_for:'DAILY INSPIRATION',hold_ms:300},
			{name:'app-chat-command',text:'/chat '+chat.chatId},
			{name:'app-chat-open',key:'Return',wait_for:'Weather · Forecast',wait_for_absent:'Loading chat…',wait_timeout_ms:30_000,hold_ms:1800},
			{name:'app-exit-command',text:'/exit'},
			{name:'app-exit',key:'Return'},
		];
		const recording=await captureProof(apiUrl,home,cli,steps,appPreviewContract,testInfo);
		const opened=recording.frame('app-chat-open').join('\n');
		const audio=opened.indexOf('Audio · Transcribe'),weather=opened.indexOf('Weather · Forecast');
		expect(audio).toBeGreaterThanOrEqual(0);
		expect(weather).toBeGreaterThan(audio);
		// Cards wrap long detail text across bordered rows in the terminal frame.
		const compact=(value:string)=>value.replace(/[│╭╮╰╯─├┤\s]/g,'');
		expect(compact(opened)).toContain(compact(AUDIO_PREVIEW));
		expect(opened).not.toContain(AUDIO_TRANSCRIPT);
		expect(opened).not.toContain('Original voice recognition differs');
		expect(compact(opened)).not.toContain(compact(AUDIO_TRANSCRIPT.slice(119)));
		expect(opened).toContain('/embed aud-t-1');
		expect(opened).toContain('/embed wea-f-1');
		expect(opened.indexOf('/embed aud-t-1')).toBeLessThan(weather);
		expect(opened.indexOf('/embed wea-f-1')).toBeGreaterThan(audio);
		const checkpoint=recording.manifest.input_checkpoints.find((point:{name:string})=>point.name==='app-chat-open');
		expect(checkpoint).toBeTruthy();
		const rawBefore=Buffer.from(recording.transcript,'utf8').subarray(0,checkpoint!.transcript_offset).toString('utf8');
		const rawEnd=rawBefore.lastIndexOf('\x1b[?2026l'),rawStart=rawBefore.lastIndexOf('\x1b[?2026h',rawEnd);
		expect(rawStart).toBeGreaterThanOrEqual(0);
		expect(rawEnd).toBeGreaterThan(rawStart);
		const rawChat=rawBefore.slice(rawStart,rawEnd);
		// eslint-disable-next-line no-control-regex -- Check exact emitted app RGB colors in the real terminal.
		expect(rawChat).toMatch(/\x1b\[48;2;0;199;160m/);
		// eslint-disable-next-line no-control-regex -- Check exact emitted app RGB colors in the real terminal.
		expect(rawChat).toMatch(/\x1b\[48;2;0;91;165m/);
		// eslint-disable-next-line no-control-regex -- Audio's bright green uses a dark foreground for readable contrast.
		expect(rawChat).toMatch(/\x1b\[38;2;(?:[0-5]?\d|6[0-3]);(?:[0-5]?\d|6[0-3]);(?:[0-5]?\d|6[0-3])m\x1b\[48;2;0;199;160m/);
		// eslint-disable-next-line no-control-regex -- Weather's dark blue uses white text.
		expect(rawChat).toMatch(/\x1b\[38;2;255;255;255m\x1b\[48;2;0;91;165m/);
		await recording.attest();
	}finally{
		try{if(chat)persistChatFixture(chat,'cleanup');}
		finally{await cleanupWorkspace(apiUrl,home,workspace);}
	}
});
