/* eslint-disable @typescript-eslint/no-require-imports */
/** Real terminal proof for encrypted saved interactive questions. */
export {};
import type {ProofStep} from './cli-tui-proof-helpers';

const {test,expect,email,password,otpKey,captureProof,installRecorderDeps,
	requireIsolatedCliBuild,workflowApiUrl,createWorkflowCliHome,skipWithoutCredentials} = require('./cli-tui-proof-helpers');
const {workflowCliEnv,loginWorkflowCliViaPair,removeWorkflowCliHome} = require('./helpers/workflow-cli-e2e-helpers');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const ROOT=path.resolve(__dirname,'../../../..');
const COMPOSE=path.join(ROOT,'test-results/ci-private/compose.json');
const PROFILE='cli-terminal';

type ChatFixture={chatId:string;ownerId:string;chat:Record<string,unknown>;
	messages:Record<string,unknown>[];messageIds:string[]};

const QUESTIONS=[
	{id:'q-single',type:'choice',question:'Which route should we take?',options:[
		{id:'train',text:'Train to the venue'},{id:'walk',text:'Walk to the venue'}]},
	{id:'q-multi',type:'choice',multiple:true,question:'Which supplies should we pack?',
		custom_option_id:'other',custom_placeholder:'Name another supply',options:[
			{id:'water',text:'Water bottle'},{id:'map',text:'Paper map'},{id:'other',text:'Something else'}]},
	{id:'q-input',type:'input',question:'Where should we meet?',fields:[
		{id:'name',label:'Your name',required:true},{id:'place',label:'Meeting place',required:true}]},
	{id:'q-slider',type:'slider',question:'How much time should we allow?',min:1,max:5,step:1,default:3},
	{id:'q-rating',type:'rating',question:'Rate the route suggestion',max_stars:5},
	{id:'q-swipe',type:'swipe',question:'Choose a proposed route',cards:[
		{id:'route-a',text:'Riverside path'},{id:'route-b',text:'Main street'}]},
] as const;

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
		})().catch(error=>{console.error('Interactive question fixture:',error.message);process.exit(1)});
	`;
	return JSON.parse(execFileSync('node',['-e',source,modulePath,JSON.stringify(input)],{
		cwd:ROOT,env:workflowCliEnv(apiUrl,home),encoding:'utf8',timeout:90_000,
	}).trim());
}

function makeFixture(apiUrl:string,home:string,cli:string):ChatFixture {
	return sdk(apiUrl,home,cli,`
		const owner=await client.whoAmI();
		if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal account');
		const chatId=randomUUID(),key=randomBytes(32),master=client.getMasterKeyBytes();
		const now=Math.floor(Date.now()/1000),messageIds=[],messages=[];
		const chat={id:chatId,hashed_user_id:hash(owner.id),created_at:now-7,updated_at:now,
			last_edited_overall_timestamp:now,last_message_timestamp:now,messages_v:1,title_v:1,metadata_v:1,
			unread_count:0,encrypted_chat_key:await encrypt(key,master),
			encrypted_title:await encrypt('Interactive question terminal proof',key),
			encrypted_chat_summary:await encrypt('Six saved questions for terminal answers.',key),
			encrypted_category:await encrypt('general_knowledge',key)};
		const add=async(role,content,index)=>{const id=randomUUID(),stamp=now-6+index;messageIds.push(id);
			messages.push({id,client_message_id:id,message_id:id,chat_id:chatId,
				hashed_user_id:hash(owner.id),role,created_at:stamp,updated_at:stamp,
				encrypted_sender_name:await encrypt(role==='user'?'You':'Assistant',key),
				encrypted_category:await encrypt('general_knowledge',key),encrypted_content:await encrypt(content,key)})};
		await add('user','Ask me a few planning questions.',0);
		for(const [index,question] of input.questions.entries())await add('assistant',
			'Question '+(index+1)+':\\n\\n'+String.fromCharCode(96).repeat(3)+'interactive_question\\n'
			+JSON.stringify(question)+'\\n'+String.fromCharCode(96).repeat(3),index+1);
		process.stdout.write(JSON.stringify({chatId,ownerId:owner.id,chat,messages,messageIds}));
	`,{questions:QUESTIONS});
}

function persistFixture(fixture:ChatFixture,operation:'seed'|'cleanup'):void {
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
    for message in await directus.chat.get_all_messages_for_chat(data['chatId'],decrypt_content=False) or []:
     value=json.loads(message) if isinstance(message,str) else message
     if value.get('client_message_id') in data['messageIds']:
      assert await directus.delete_item('messages',value['id'],admin_required=True)
    assert await directus.delete_item('chats',data['chatId'],admin_required=True)
   await cache.remove_chat_from_ids_versions(data['ownerId'],data['chatId'])
  print('interactive fixture applied')
 finally: await directus.close();await cache.close()
asyncio.run(main())
`;
	const output=execFileSync('docker',['compose','-f',COMPOSE,'exec','-T','-e',
		'OPENMATES_CI_ISOLATED=1','api','python','-c',program],{
		cwd:ROOT,input:JSON.stringify({...fixture,operation}),encoding:'utf8',timeout:90_000,
	});
	expect(output.trim()).toBe('interactive fixture applied');
}

function seedOfflineCache(apiUrl:string,home:string,cli:string,fixture:ChatFixture):void {
	const result=sdk(apiUrl,home,cli,`
		const owner=await client.whoAmI();if(owner.id!==input.ownerId)throw Error('Fixture owner changed');
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
		const saved=await client.getChatMessages(input.chatId,{preferCache:true,maxHistoryPages:1});
		if(saved.messages.length!==input.messages.length)throw Error('Saved encrypted questions missing');
		process.stdout.write(JSON.stringify({ok:true}));
	`,fixture);
	expect(result.ok).toBe(true);
}

const contract={
	id:'cli-tui-interactive-questions-real-terminal',title:'Encrypted interactive questions in terminal chat',
	surface:'cli',devices:[PROFILE],
	transcript:[
		{id:'history',text:'Six encrypted saved questions are readable in the terminal chat without raw protocol JSON.',checkpoint:'questions-open',devices:[PROFILE]},
		{id:'editor',text:'Question shortcuts open a keyboard editor; invalid answers remain visible until corrected.',checkpoint:'question-invalid',devices:[PROFILE]},
		{id:'answer',text:'An explicit answer uses the ordinary encrypted chat path and locks the answered question.',checkpoint:'question-answered',devices:[PROFILE]},
	],
	assertions:[
		{id:'cli.surface.semantic-parity',checkpoint:'questions-open',visual:'All five question types render readable prompts and a keyboard answer shortcut.',devices:[PROFILE]},
		{id:'cli.output.actionable-readable',checkpoint:'question-invalid',visual:'The editor exposes choices and validation in terminal text.',devices:[PROFILE]},
		{id:'chats.rendering.inline-entity-interaction',checkpoint:'question-answered',visual:'The submitted answer appears as user text with hidden interactive_response protocol and the question locks.',devices:[PROFILE]},
	],
	tutorial:{readingWordsPerSecond:2.5,minimumHoldMs:1200,maximumHoldMs:5000},
};

function installSendCapture(home:string,cli:string,chatId:string):{captureFile:string;restore:()=>void} {
	const adapterPath=path.join(home,'interactive-send-adapter.mjs');
	const captureFile=path.join(home,'interactive-sent-messages.jsonl');
	const modulePath=path.join(path.dirname(cli),'index.js');
	fs.writeFileSync(adapterPath,`
		import fs from 'node:fs';
		import {pathToFileURL} from 'node:url';
		const {OpenMatesClient}=await import(pathToFileURL(${JSON.stringify(modulePath)}).href);
		OpenMatesClient.prototype.sendMessage=async function(options){
			if(options.chatId!==${JSON.stringify(chatId)})throw Error('Interactive proof crossed chat boundary');
			if(options.interactiveHuman!==true)throw Error('Interactive proof skipped ordinary human send');
			fs.appendFileSync(${JSON.stringify(captureFile)},JSON.stringify({chatId:options.chatId,
				interactiveHuman:options.interactiveHuman,message:options.message})+'\\n',{mode:0o600});
			return {assistant:'Recorded answer received.',chatId:options.chatId,followUpSuggestions:[]};
		};
	`);
	const previousNodeOptions=process.env.NODE_OPTIONS;
	process.env.NODE_OPTIONS=[previousNodeOptions,`--import=${adapterPath}`].filter(Boolean).join(' ');
	return {captureFile,restore:()=>{
		if(previousNodeOptions===undefined)delete process.env.NODE_OPTIONS;
		else process.env.NODE_OPTIONS=previousNodeOptions;
	}};
}

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable,chats.rendering.inline-entity-interaction
test('records encrypted choice, input, slider, rating, and swipe answers in the real terminal',async({page}:{page:any},testInfo:any)=>{
	test.setTimeout(360_000);
	test.skip(process.env.GITHUB_ACTIONS!=='true'||process.env.RUNNER_ENVIRONMENT!=='github-hosted'||process.env.CI_TEST_MODE!=='e2e','Requires isolated GitHub product stack');
	skipWithoutCredentials(test,email,password,otpKey);
	const cli=requireIsolatedCliBuild();installRecorderDeps();
	const apiUrl=workflowApiUrl(),home=createWorkflowCliHome('tui-interactive-questions');
	let fixture:ChatFixture|undefined;
	try{
		await loginWorkflowCliViaPair(page,apiUrl,home,'CLI_TUI_INTERACTIVE_QUESTIONS');
		fixture=makeFixture(apiUrl,home,cli);
		persistFixture(fixture,'seed');
		seedOfflineCache(apiUrl,home,cli,fixture);
		const adapter=installSendCapture(home,cli,fixture.chatId);
		try{
			const steps:(ProofStep & {wait_timeout_ms?:number})[]=[
				{name:'landing',wait_for:'DAILY INSPIRATION',hold_ms:250},
				{name:'chat-command',text:'/chat '+fixture.chatId},
				{name:'questions-open',key:'Return',wait_for:'Question 6',wait_for_absent:'Loading chat…',wait_timeout_ms:30_000,hold_ms:700},
				{name:'question-command',text:'/question 1'},
				{name:'question-cancel-open',key:'Return',wait_for:'Answer question 1',hold_ms:350},
				{name:'question-cancel',key:'Escape',wait_for:'Ask a follow-up',wait_for_absent:'Answer question 1',hold_ms:300},
				{name:'composer-after-cancel',key:'Tab',hold_ms:100},
				{name:'question-command-again',text:'/question 1'},
				{name:'question-open-again',key:'Return',wait_for:'Answer question 1',hold_ms:250},
				{name:'question-invalid',key:'ctrl+s',wait_for:'Select a valid option.',hold_ms:400},
				{name:'choice-single-select',key:'space',wait_for:'[✓] Train to the venue',hold_ms:250},
				{name:'question-answered',key:'ctrl+s',wait_for:'Recorded answer received.',wait_for_absent:'is typing...',hold_ms:500},
				{name:'composer-multi',key:'Tab',hold_ms:100},
				{name:'multi-command',text:'/question 2'},
				{name:'multi-open',key:'Return',wait_for:'Answer question 2',hold_ms:250},
				{name:'multi-water',key:'space',hold_ms:150},
				{name:'multi-map-focus',key:'Down',hold_ms:100},
				{name:'multi-map',key:'space',hold_ms:150},
				{name:'multi-other-focus',key:'Down',hold_ms:100},
				{name:'multi-other',key:'space',wait_for:'Name another supply',hold_ms:150},
				{name:'multi-custom-focus',key:'Down',hold_ms:100},
				{name:'multi-custom-text',text:'Bandages',hold_ms:150},
				{name:'multi-answered',key:'ctrl+s',wait_for:'Recorded answer received.',wait_for_absent:'is typing...',hold_ms:300},
				{name:'composer-input',key:'Tab',hold_ms:100},
				{name:'input-command',text:'/question 3'},
				{name:'input-open',key:'Return',wait_for:'Answer question 3',hold_ms:250},
				{name:'input-invalid',key:'ctrl+s',wait_for:'Fill in every required field.',hold_ms:150},
				{name:'input-name',text:'Alex',hold_ms:100},
				{name:'input-place-focus',key:'Return',hold_ms:100},
				{name:'input-place',text:'Central Plaza',hold_ms:100},
				{name:'input-answered',key:'ctrl+s',wait_for:'Recorded answer received.',wait_for_absent:'is typing...',hold_ms:300},
				{name:'composer-slider',key:'Tab',hold_ms:100},
				{name:'slider-command',text:'/question 4'},
				{name:'slider-open',key:'Return',wait_for:'Answer question 4',hold_ms:250},
				{name:'slider-invalid',key:'ctrl+s',wait_for:'Adjust the slider before sending.',hold_ms:150},
				{name:'slider-adjust',key:'Right',wait_for:'4',hold_ms:150},
				{name:'slider-answered',key:'ctrl+s',wait_for:'Recorded answer received.',wait_for_absent:'is typing...',hold_ms:300},
				{name:'composer-rating',key:'Tab',hold_ms:100},
				{name:'rating-command',text:'/question 5'},
				{name:'rating-open',key:'Return',wait_for:'Answer question 5',hold_ms:250},
				{name:'rating-adjust-one',key:'Right',hold_ms:100},
				{name:'rating-adjust-two',key:'Right',hold_ms:100},
				{name:'rating-comment-focus',key:'Down',hold_ms:100},
				{name:'rating-comment',text:'Good route',hold_ms:100},
				{name:'rating-answered',key:'ctrl+s',wait_for:'Recorded answer received.',wait_for_absent:'is typing...',hold_ms:300},
				{name:'latest-open',key:'ctrl+q',wait_for:'Answer question 6',hold_ms:250},
				{name:'swipe-invalid',key:'ctrl+s',wait_for:'Review every card.',hold_ms:150},
				{name:'swipe-dislike',key:'Left',wait_for:'dislike',hold_ms:150},
				{name:'swipe-like',key:'Right',wait_for:'like',hold_ms:150},
				{name:'swipe-answered',key:'ctrl+s',wait_for:'Recorded answer received.',wait_for_absent:'is typing...',hold_ms:400},
				{name:'latest-locked',key:'ctrl+q',wait_for:'No unanswered question here.',hold_ms:250},
				{name:'composer-after-lock',key:'Tab',hold_ms:100},
				{name:'reopen-command',text:'/question 1'},
				{name:'reopen-locked',key:'Return',wait_for:'already been answered',hold_ms:250},
				{name:'exit-clear',key:'ctrl+u',hold_ms:100},
				{name:'exit-command',text:'/exit'},
				{name:'exit',key:'Return'},
			];
			const recording=await captureProof(apiUrl,home,cli,steps,contract,testInfo);
			const frame=(name:string)=>recording.frame(name).join('\n');
			for(const [name,prompt] of [
				['question-cancel-open','Which route should we take?'],['multi-open','Which supplies should we pack?'],
				['input-open','Where should we meet?'],['slider-open','How much time should we allow?'],
				['rating-open','Rate the route suggestion'],['latest-open','Choose a proposed route']]){
				expect(frame(name)).toContain(prompt);
			}
			expect(frame('question-cancel')).not.toContain('Answer question 1');
			expect(frame('question-invalid')).toContain('Select a valid option.');
			expect(frame('input-invalid')).toContain('Fill in every required field.');
			expect(frame('slider-invalid')).toContain('Adjust the slider before sending.');
			expect(frame('swipe-invalid')).toContain('Review every card.');
			expect(frame('reopen-locked')).toContain('already been answered');
			for(const name of ['questions-open','question-answered','multi-answered','input-answered',
				'slider-answered','rating-answered','swipe-answered']){
				expect(frame(name)).not.toContain('interactive_question');
				expect(frame(name)).not.toContain('interactive_response');
				expect(frame(name)).not.toContain('"selection"');
			}
			const calls=fs.readFileSync(adapter.captureFile,'utf8').trim().split('\n').map((line:string)=>JSON.parse(line));
			expect(calls).toHaveLength(6);
			const responses=calls.map((call:any)=>{
				expect(call.chatId).toBe(fixture!.chatId);
				expect(call.interactiveHuman).toBe(true);
				const match=call.message.match(/```interactive_response\n([\s\S]*?)\n```/);
				expect(match).toBeTruthy();
				return JSON.parse(match[1]);
			});
			expect(responses).toEqual([
				{id:'q-single',selection:['train']},
				{id:'q-multi',selection:['water','map','other'],custom_answer:'Bandages'},
				{id:'q-input',inputs:{name:'Alex',place:'Central Plaza'}},
				{id:'q-slider',value:4},
				{id:'q-rating',rating:2,comment:'Good route'},
				{id:'q-swipe',swipes:{'route-a':'dislike','route-b':'like'}},
			]);
			await recording.attest();
		}finally{adapter.restore();}
	}finally{
		try{if(fixture)persistFixture(fixture,'cleanup');}
		finally{removeWorkflowCliHome(home);}
	}
});
