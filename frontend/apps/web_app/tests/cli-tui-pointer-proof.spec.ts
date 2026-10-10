/* eslint-disable @typescript-eslint/no-require-imports */
/** Real XTEST pointer proof over an isolated, encrypted CLI workspace. */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';

const {test,expect,email,password,otpKey,captureProof,installRecorderDeps,seedWorkspace,cleanupWorkspace,
	newFixture,requireIsolatedCliBuild,workflowApiUrl,createWorkflowCliHome,skipWithoutCredentials} = require('./cli-tui-proof-helpers');
const {workflowCliEnv,removeWorkflowCliHome} = require('./helpers/workflow-cli-e2e-helpers');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const ROOT=path.resolve(__dirname,'../../../..');
const COMPOSE=path.join(ROOT,'test-results/ci-private/compose.json');
const PROFILE='cli-terminal';
type ChatFixture={chatId:string;ownerId:string;embedId:string;assistantMessageId:string;
	chat:Record<string,unknown>;messages:Record<string,unknown>[];messageIds:string[]};

function sdk(apiUrl:string,home:string,cli:string,program:string,input:unknown={}):any {
	const modulePath=path.join(path.dirname(cli),'index.js');
	const source=`
		const {pathToFileURL}=require('node:url');
		const {randomUUID,randomBytes,createHash,webcrypto}=require('node:crypto');
		(async()=>{
			const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
			const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
			const input=JSON.parse(process.argv[2]);
			const hash=value=>createHash('sha256').update(value).digest('hex');
			const encrypt=async(value,key)=>{const iv=randomBytes(12);
				const cryptoKey=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
				return Buffer.concat([iv,Buffer.from(await webcrypto.subtle.encrypt({name:'AES-GCM',iv},cryptoKey,
					Buffer.from(value)))]).toString('base64')};
			${program}
		})().catch(error=>{console.error('Pointer fixture:',error.message);process.exit(1)});
	`;
	return JSON.parse(execFileSync('node',['-e',source,modulePath,JSON.stringify(input)],{
		cwd:ROOT,env:workflowCliEnv(apiUrl,home),encoding:'utf8',timeout:90_000,
	}).trim());
}

function makeChatFixture(apiUrl:string,home:string,cli:string):ChatFixture {
	return sdk(apiUrl,home,cli,`
		const owner=await client.whoAmI();if(!owner.id||client.getActiveTeamId())throw Error('Expected Personal owner');
		const chatId=randomUUID(),embedId=randomUUID(),key=randomBytes(32),master=client.getMasterKeyBytes();
		const now=Math.floor(Date.now()/1000),messageIds=[],messages=[];
		const chat={id:chatId,hashed_user_id:hash(owner.id),created_at:now-3,updated_at:now,
			last_edited_overall_timestamp:now,last_message_timestamp:now,messages_v:1,title_v:1,metadata_v:1,
			unread_count:0,encrypted_chat_key:await encrypt(key,master),
			encrypted_title:await encrypt('Pointer chat proof',key),
			encrypted_chat_summary:await encrypt('Saved links and one interactive question.',key),
			encrypted_category:await encrypt('general_knowledge',key)};
		const add=async(role,content,index)=>{const id=randomUUID(),stamp=now-2+index;messageIds.push(id);
			messages.push({id,client_message_id:id,message_id:id,chat_id:chatId,hashed_user_id:hash(owner.id),
				role,created_at:stamp,updated_at:stamp,encrypted_sender_name:await encrypt(role==='user'?'You':'Assistant',key),
				encrypted_category:await encrypt('general_knowledge',key),encrypted_content:await encrypt(content,key)});return id};
		await add('user','Show a saved item, a Wikipedia link, and a choice question.',0);
		const question={id:'pointer-choice',type:'choice',question:'Which route should we take?',options:[
			{id:'train',text:'Train to the venue'},{id:'walk',text:'Walk to the venue'}]};
		const fence=String.fromCharCode(96).repeat(3);
		const content='[Pointer wiki article](wiki:Apple_Watch) and [Pointer saved embed](embed:'+embedId+')'
			+'\\n\\nQuestion 1:\\n\\n'+fence+'interactive_question\\n'+JSON.stringify(question)+'\\n'+fence;
		const assistantMessageId=await add('assistant',content,1);
		process.stdout.write(JSON.stringify({chatId,ownerId:owner.id,embedId,assistantMessageId,chat,messages,messageIds}));
	`);
}

function persistChatFixture(fixture:ChatFixture,operation:'seed'|'cleanup'):void {
	expect(fs.existsSync(COMPOSE),'Requires disposable isolated CI compose').toBe(true);
	const program=`
import asyncio,hashlib,json,logging,os,sys
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED')=='1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.tasks.persistence_tasks import _chat_list_cache_data_from_metadata,_chat_versions_from_metadata
async def main():
 data=json.load(sys.stdin);cache=CacheService();directus=DirectusService(cache_service=cache)
 owner=hashlib.sha256(data['ownerId'].encode()).hexdigest()
 assert data['chat']['hashed_user_id']==owner
 assert all(message['hashed_user_id']==owner for message in data['messages'])
 try:
  if data['operation']=='seed':
   created,duplicate=await directus.chat.create_chat_in_directus(data['chat'])
   assert created and not duplicate,'Encrypted chat seed failed'
   for message in data['messages']:
    stored=await directus.chat.create_message_in_directus(message)
    assert stored and stored.get('id'),'Encrypted message seed failed'
   assert await cache.add_chat_to_ids_versions(data['ownerId'],data['chatId'],data['chat']['last_edited_overall_timestamp'])
   assert await cache.set_chat_list_item_data(data['ownerId'],data['chatId'],_chat_list_cache_data_from_metadata(data['chat']))
   assert await cache.set_chat_versions(data['ownerId'],data['chatId'],_chat_versions_from_metadata(data['chat']))
  else:
   metadata=await directus.chat.get_chat_metadata(data['chatId'])
   if metadata:
    assert metadata.get('hashed_user_id')==owner,'Only fixture-owned chat may be removed'
    for raw in await directus.chat.get_all_messages_for_chat(data['chatId'],decrypt_content=False) or []:
     message=json.loads(raw) if isinstance(raw,str) else raw
     if message.get('client_message_id') in data['messageIds']:
      assert await directus.delete_item('messages',message['id'],admin_required=True)
    assert await directus.delete_item('chats',data['chatId'],admin_required=True)
   await cache.remove_chat_from_ids_versions(data['ownerId'],data['chatId'])
  print('pointer fixture applied')
 finally: await directus.close();await cache.close()
asyncio.run(main())
`;
	const output=execFileSync('docker',['compose','-f',COMPOSE,'exec','-T','-e','OPENMATES_CI_ISOLATED=1',
		'api','python','-c',program],{cwd:ROOT,input:JSON.stringify({...fixture,operation}),encoding:'utf8',timeout:90_000});
	expect(output.trim()).toBe('pointer fixture applied');
}

function seedEmbedAndCache(apiUrl:string,home:string,cli:string,fixture:ChatFixture):void {
	const result=sdk(apiUrl,home,cli,`
		const owner=await client.whoAmI();if(owner.id!==input.ownerId)throw Error('Fixture owner changed');
		const {ws}=await client.openWsClient({taskUpdateJobs:false});
		const send=async(type,reply,payload)=>{const requestId=randomUUID(),receipt=ws.waitForMessage(reply,p=>p.request_id===requestId,30000);
			await ws.sendAsync(type,{...payload,request_id:requestId});return (await receipt).payload};
		try{
			const key=randomBytes(32),now=Math.floor(Date.now()/1000),value={app_id:'web',skill_id:'search',
				status:'finished',title:'Pointer saved result',summary:'A safe local search result.',
				input:{query:'pointer proof'},results:[{title:'Pointer saved result',
					url:'https://example.org/pointer',snippet:'A safe local search result.'}]};
			await send('store_embed','store_embed_confirmed',{embed_id:input.embedId,
				encrypted_content:await encrypt(JSON.stringify(value),key),encrypted_type:await encrypt('app_skill_use',key),
				status:'finished',hashed_chat_id:hash(input.chatId),hashed_message_id:hash(input.assistantMessageId),
				hashed_user_id:hash(owner.id),created_at:now,updated_at:now,version_number:1});
			await send('store_embed_keys','store_embed_keys_confirmed',{keys:[{hashed_embed_id:hash(input.embedId),
				key_type:'master',hashed_chat_id:null,encrypted_embed_key:await encrypt(key,client.getMasterKeyBytes()),
				hashed_user_id:hash(owner.id),created_at:now}]});
			const embed=await client.getEmbed(input.embedId,{preferCache:true,chatId:input.chatId});
			if(embed.content.app_id!=='web')throw Error('Saved embed missing');
		}finally{ws.close()}
		await client.listChats(20,1,{forceRefresh:true});
		const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),home=process.env.HOME;
		if(!home||!home.startsWith(os.tmpdir()+path.sep))throw Error('Expected isolated CLI home');
		const cachePath=path.join(home,'.openmates','sync_cache.json'),cache=JSON.parse(fs.readFileSync(cachePath,'utf8'));
		const row=cache.chats.find(chat=>chat.details.id===input.chatId);
		if(!row)throw Error('Saved chat missing from CLI census');
		const chats=cache.chats.map(chat=>chat===row?{...chat,messages:input.messages.map(JSON.stringify)}:chat);
		fs.writeFileSync(cachePath,JSON.stringify({...cache,chats},null,2)+'\\n',{mode:0o600});
		const saved=await client.getChatMessages(input.chatId,{preferCache:true,maxHistoryPages:1});
		if(saved.messages.length!==input.messages.length)throw Error('Encrypted pointer chat missing');
		process.stdout.write(JSON.stringify({ok:true}));
	`,fixture);
	expect(result.ok).toBe(true);
}

function seedWorkspaceCache(apiUrl:string,home:string,cli:string,workspace:{projectId:string;taskId:string;
	workflowId:string;projectName:string;taskTitle:string;workflowTitle:string;workflowDetail:unknown}):void {
	const dist=path.join(path.dirname(cli),'index.js');
	const sourceDir=path.join(ROOT,'frontend/packages/openmates-cli/src');
	const loader=path.join(ROOT,'frontend/packages/openmates-cli/tests/loader.mjs');
	const script=`
		import {readFileSync} from 'node:fs';
		import {join} from 'node:path';
		import {pathToFileURL} from 'node:url';
		const [dist,sourceDir]=process.argv.slice(1);
		const input=JSON.parse(readFileSync(0,'utf8'));
		const {OpenMatesClient}=await import(pathToFileURL(dist).href);
		const {loadTuiProjects,loadTuiProjectFiles}=await import(pathToFileURL(join(sourceDir,'tuiProjectsWorkspace.ts')).href);
		const {decryptUserTasks}=await import(pathToFileURL(join(sourceDir,'tasksCli.ts')).href);
		const {writeCachedTuiWorkspace,readCachedTuiWorkspace,captureTuiWorkspaceOwner}=
			await import(pathToFileURL(join(sourceDir,'tuiCachedWorkspaces.ts')).href);
		const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
		const owner=await client.whoAmI();
		if(!(owner.id||owner.user_id)||client.getActiveTeamId())throw Error('Expected paired Personal owner');
		const current=captureTuiWorkspaceOwner(client);
		if(!current())throw Error('Workspace cache owner changed');
		const projects=await loadTuiProjects(client);
		const project=projects.find(item=>item.id===input.projectId);
		if(!project||project.name!==input.projectName||project.teamId!==null||
			!(project.projectKey instanceof Uint8Array)||project.projectKey.length!==32||
			project.items.length||project.files.length||project.folders.length||project.sources.length)
			throw Error('Owned empty Project summary unavailable');
		const files=await loadTuiProjectFiles(client,project,{});
		if(files.length)throw Error('New Project unexpectedly has files');
		const allTasks=await decryptUserTasks(await client.listUserTasks(),client.getMasterKeyBytes());
		const task=allTasks.find(item=>item.taskId===input.taskId);
		if(!task||task.title!==input.taskTitle||!task.linkedProjectIds.includes(input.projectId))
			throw Error('Owned linked task unavailable');
		const projectTasks=allTasks.filter(item=>item.linkedProjectIds.includes(input.projectId));
		const workflows=await client.listWorkflows();
		const workflow=workflows.find(item=>item.id===input.workflowId);
		if(!workflow||workflow.title!==input.workflowTitle||input.workflowDetail?.id!==input.workflowId||
			!Array.isArray(input.workflowDetail.graph?.nodes))throw Error('Owned workflow detail unavailable');
		const entries=[
			['projects:list',projects],['project:'+project.id+':detail',project],
			['project:'+project.id+':files:[null,null,null]',files],
			['tasks:list',allTasks],['project:'+project.id+':tasks',projectTasks],
			['workflows:list',workflows],['workflow:'+workflow.id+':detail',input.workflowDetail],
		];
		for(const [key,value] of entries){
			if(!current()||!await writeCachedTuiWorkspace(client,key,value,current))
				throw Error('Owner-fenced workspace cache write failed');
			const saved=await readCachedTuiWorkspace(client,key,current);
			if(saved===null)throw Error('Workspace cache readback failed');
		}
		process.stdout.write(JSON.stringify({ok:true,count:entries.length}));
	`;
	const output=execFileSync('node',['--no-warnings','--experimental-strip-types','--loader',loader,
		'--input-type=module','-e',script,dist,sourceDir],{
		cwd:ROOT,env:workflowCliEnv(apiUrl,home),input:JSON.stringify(workspace),encoding:'utf8',timeout:120_000,
	});
	expect(JSON.parse(output.trim())).toEqual({ok:true,count:7});
}

function installAdapter(home:string,cli:string,chatId:string):{captureFile:string;restore:()=>void} {
	const adapterPath=path.join(home,'pointer-adapter.mjs'),captureFile=path.join(home,'pointer-sent.jsonl');
	const modulePath=path.join(path.dirname(cli),'index.js');
	fs.writeFileSync(adapterPath,`
		import fs from 'node:fs';import {pathToFileURL} from 'node:url';
		const {OpenMatesClient}=await import(pathToFileURL(${JSON.stringify(modulePath)}).href);
		OpenMatesClient.prototype.wikipediaSummary=async function(){return {title:'Pointer wiki article',
			description:'Local proof article',extract:'Pointer wiki excerpt from the isolated proof adapter.',
			source_url:'https://en.wikipedia.org/wiki/Apple_Watch'}};
		OpenMatesClient.prototype.sendMessage=async function(options){
			if(options.chatId!==${JSON.stringify(chatId)}||options.interactiveHuman!==true)throw Error('Pointer answer crossed chat boundary');
			fs.appendFileSync(${JSON.stringify(captureFile)},JSON.stringify({chatId:options.chatId,
				interactiveHuman:options.interactiveHuman,message:options.message})+'\\n',{mode:0o600});
			return {assistant:'Pointer answer recorded.',chatId:options.chatId,followUpSuggestions:[]};
		};
	`);
	const previous=process.env.NODE_OPTIONS;
	process.env.NODE_OPTIONS=[previous,`--import=${adapterPath}`].filter(Boolean).join(' ');
	return {captureFile,restore:()=>{if(previous===undefined)delete process.env.NODE_OPTIONS;else process.env.NODE_OPTIONS=previous;}};
}

const contract={
	id:'cli-tui-pointer-real-terminal',title:'Real mouse actions in the terminal workspace',surface:'cli',devices:[PROFILE],
	transcript:[
		{id:'navigation',text:'Visible workspace tabs and cards respond to real pointer clicks.',checkpoint:'project-open',devices:[PROFILE]},
		{id:'chat',text:'Chat links, question choices, and the explicit answer action respond to pointer clicks.',checkpoint:'answer-sent',devices:[PROFILE]},
		{id:'viewport',text:'After scrolling and resizing, a visible text target still resolves to the correct terminal cell.',checkpoint:'resized-projects',devices:[PROFILE]},
	],
	assertions:[
		{id:'terminal-pointer.visible-action-parity',checkpoint:'answer-sent',visual:'Real XTEST clicks activate the same visible workspace, chat, and question actions as keyboard controls.',devices:[PROFILE]},
		{id:'terminal-pointer.viewport-coherent',checkpoint:'resized-projects',visual:'Semantic click target coordinates are recalculated from the current rendered terminal frame and window size.',devices:[PROFILE]},
		{id:'terminal-pointer.lifecycle-selection-safe',checkpoint:'modal-no-clickthrough',visual:'The question editor consumes a background click without routing to another workspace.',devices:[PROFILE]},
	],
	tutorial:{readingWordsPerSecond:2.5,minimumHoldMs:1200,maximumHoldMs:5000},
};

// contract-test: direct surface=cli assertions=terminal-pointer.visible-action-parity,terminal-pointer.viewport-coherent,terminal-pointer.lifecycle-selection-safe
test('records real pointer navigation, linked content, and an explicit question answer',async({page}:{page:any},testInfo:any)=>{
	test.setTimeout(360_000);
	test.skip(process.env.GITHUB_ACTIONS!=='true'||process.env.RUNNER_ENVIRONMENT!=='github-hosted'||process.env.CI_TEST_MODE!=='e2e',
		'Requires isolated GitHub product stack and real graphical terminal');
	skipWithoutCredentials(test,email,password,otpKey);
	const cli=requireIsolatedCliBuild();installRecorderDeps();
	const apiUrl=workflowApiUrl(),home=createWorkflowCliHome('tui-pointer');
	const workspace=newFixture();workspace.projectName='Pointer project '+workspace.projectName.slice(-8);
	workspace.taskTitle='Pointer task '+workspace.taskTitle.slice(-8);
	workspace.workflowTitle='Pointer workflow '+workspace.workflowTitle.slice(-8);
	let chat:ChatFixture|undefined;
	let proofFailure:unknown;
	let proofFailed=false;
	try{
		await seedWorkspace(page,apiUrl,home,workspace,true);
		seedWorkspaceCache(apiUrl,home,cli,workspace);
		chat=makeChatFixture(apiUrl,home,cli);persistChatFixture(chat,'seed');
		seedEmbedAndCache(apiUrl,home,cli,chat);
		const adapter=installAdapter(home,cli,chat.chatId);
		try{
			const steps:ProofStep[]=[
				{name:'home',wait_for:'Continue where you left off',hold_ms:350},
				{name:'navigation-focus',key:'ctrl+g',hold_ms:250},
				{name:'palette-open',key:'ctrl+p',wait_for:'Actions',hold_ms:250},
				{name:'palette-filter',text:'Projects',wait_for:'Projects  /projects',hold_ms:250},
				{name:'palette-click',click:{text:'Projects  /projects'},wait_for:workspace.projectName,hold_ms:350},
				{name:'projects-tab',click:{text:'Projects',occurrence:0},wait_for:workspace.projectName,hold_ms:450},
				{name:'project-open',click:{text:workspace.projectName},wait_for:'[Overview · 1]',hold_ms:350},
				{name:'project-files',click:{text:'Files · 2'},wait_for:'[Files · 2]',hold_ms:250},
				{name:'project-tasks',click:{text:'Tasks · 3'},wait_for:workspace.taskTitle,hold_ms:250},
				{name:'workflows-tab',click:{text:'Workflows'},wait_for:workspace.workflowTitle,hold_ms:350},
				{name:'workflow-open',click:{text:workspace.workflowTitle},wait_for:'Template · g',hold_ms:350},
				{name:'tasks-tab',click:{text:'Tasks'},wait_for:workspace.taskTitle,hold_ms:350},
				{name:'chats-tab',click:{text:'Chats'},wait_for:'Pointer chat proof',hold_ms:450},
				{name:'chat-card',click:{text:'Pointer chat proof'},wait_for:'Which route should we take?',hold_ms:600},
				{name:'wiki-link',click:{text:'Pointer wiki article'},wait_for:'Pointer wiki excerpt',hold_ms:350},
				{name:'wiki-close',key:'Escape',wait_for:'Which route should we take?',hold_ms:300},
				{name:'embed-link',click:{text:'Pointer saved embed'},wait_for:'Pointer saved result',hold_ms:350},
				{name:'embed-close',key:'Escape',wait_for:'Which route should we take?',hold_ms:300},
				{name:'question-open',click:{text:'/question 1 · Answer'},wait_for:'Answer question 1',hold_ms:300},
				{name:'modal-no-clickthrough',click:{row:1,column:50},hold_ms:250},
				{name:'choice',click:{text:'Train to the venue'},wait_for:'Train to the venue',hold_ms:250},
				{name:'answer-sent',click:{text:'Send answer'},wait_for:'Pointer answer recorded.',
					wait_for_absent:'is typing...',hold_ms:400},
				{name:'composer-focus',click:{text:'Ask a follow-up'},hold_ms:250},
				{name:'apps-tab',click:{text:'Apps'},wait_for:'Browse websites',hold_ms:350},
				{name:'apps-scroll',key:'End',wait_for:'Show all',hold_ms:250},
				{name:'narrow',resize:{width:900,height:600},wait_for:'Show all',hold_ms:400},
				{name:'resized-projects',click:{text:'Projects',occurrence:0},wait_for:workspace.projectName,hold_ms:400},
				{name:'exit-command',text:'/exit'},
				{name:'exit',key:'Return'},
			];
			const recording=await captureProof(apiUrl,home,cli,steps,contract,testInfo);
			const frame=(name:string)=>recording.frame(name).join('\n');
			expect(frame('project-open')).toContain(workspace.projectName);
			expect(frame('project-files')).toContain('[Files · 2]');
			expect(frame('project-tasks')).toContain(workspace.taskTitle);
			expect(frame('workflow-open')).toContain(workspace.workflowTitle);
			expect(frame('wiki-link')).toContain('Pointer wiki excerpt');
			expect(frame('embed-link')).toContain('Pointer saved result');
			expect(frame('modal-no-clickthrough')).toContain('Answer question 1');
			expect(recording.manifest.input_checkpoints.find((point:any)=>point.name==='modal-no-clickthrough').pointer)
				.toMatchObject({row:1,column:50});
			expect(frame('answer-sent')).not.toContain('interactive_response');
			expect(frame('answer-sent')).not.toContain('is typing...');
			expect(frame('composer-focus')).toContain('Pointer answer recorded.');
			expect(frame('composer-focus')).not.toContain('is typing...');
			const pointers=recording.manifest.input_checkpoints.filter((point:any)=>point.pointer);
			expect(pointers.length).toBeGreaterThanOrEqual(14);
			const before=recording.manifest.input_checkpoints.find((point:any)=>point.name==='projects-tab').pointer;
			const after=recording.manifest.input_checkpoints.find((point:any)=>point.name==='resized-projects').pointer;
			expect(before.row).toBe(1);expect(after.row).toBe(1);
			expect(before.window_width).toBe(1280);expect(after.window_width).toBeLessThan(before.window_width);
			expect(after.columns).toBeLessThan(before.columns);
			const calls=fs.readFileSync(adapter.captureFile,'utf8').trim().split('\n').map((line:string)=>JSON.parse(line));
			expect(calls).toHaveLength(1);
			expect(calls[0].chatId).toBe(chat.chatId);expect(calls[0].interactiveHuman).toBe(true);
			const match=calls[0].message.match(/```interactive_response\n([\s\S]*?)\n```/);
			expect(match).toBeTruthy();expect(JSON.parse(match[1])).toEqual({id:'pointer-choice',selection:['train']});
			await recording.attest();
		}finally{adapter.restore();}
	}catch(error){proofFailure=error;proofFailed=true;}
	const cleanupFailures:unknown[]=[];
	try{if(chat)persistChatFixture(chat,'cleanup');}catch(error){cleanupFailures.push(error);}
	try{await cleanupWorkspace(apiUrl,home,workspace);}catch(error){cleanupFailures.push(error);}
	removeWorkflowCliHome(home);
	if(cleanupFailures.length){
		throw new AggregateError(proofFailed?[proofFailure,...cleanupFailures]:cleanupFailures,
			'Pointer proof fixture cleanup failed');
	}
	if(proofFailed)throw proofFailure;
});
