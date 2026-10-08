/* eslint-disable @typescript-eslint/no-require-imports */
/** Disposable owner-encrypted chat and code embed for terminal chrome proof. */
export {};
const {expect} = require('./cli-tui-proof-helpers');
const {workflowCliEnv} = require('./helpers/workflow-cli-e2e-helpers');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../../..');
const COMPOSE = path.join(ROOT, 'test-results/ci-private/compose.json');

export type ChromeFixture = {chatId:string;embedId:string;assistantMessageId:string;ownerId:string;title:string;
	chat:Record<string,unknown>;messages:Record<string,unknown>[];messageIds:string[]};

function sdk<T>(apiUrl:string,home:string,cli:string,program:string,input:unknown={}):T {
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
		})().catch(error=>{console.error('Chrome fixture:',error.message);process.exit(1)});
	`;
	return JSON.parse(execFileSync('node',['-e',source,path.join(path.dirname(cli),'index.js'),JSON.stringify(input)],{
		cwd:ROOT,env:workflowCliEnv(apiUrl,home),encoding:'utf8',timeout:90_000,
	}).trim()) as T;
}

function makeChromeFixture(apiUrl:string,home:string,cli:string):ChromeFixture {
	return sdk<ChromeFixture>(apiUrl,home,cli,`
		const owner=await client.whoAmI();if(!owner.id||client.getActiveTeamId())throw Error('Expected Personal owner');
		const chatId=randomUUID(),embedId=randomUUID(),key=randomBytes(32),master=client.getMasterKeyBytes();
		const title='Chrome proof '+chatId.slice(0,8),now=Math.floor(Date.now()/1000),messageIds=[],messages=[];
		const chat={id:chatId,hashed_user_id:hash(owner.id),created_at:now-2,updated_at:now,
			last_edited_overall_timestamp:now,last_message_timestamp:now,messages_v:1,title_v:1,metadata_v:1,
			unread_count:0,encrypted_chat_key:await encrypt(key,master),encrypted_title:await encrypt(title,key),
			encrypted_chat_summary:await encrypt('Private terminal chrome proof.',key),
			encrypted_category:await encrypt('general_knowledge',key)};
		const add=async(role,content,index)=>{const id=randomUUID(),stamp=now-1+index;messageIds.push(id);
			messages.push({id,client_message_id:id,message_id:id,chat_id:chatId,hashed_user_id:hash(owner.id),
				role,created_at:stamp,updated_at:stamp,encrypted_sender_name:await encrypt(role==='user'?'You':'Assistant',key),
				encrypted_category:await encrypt('general_knowledge',key),encrypted_content:await encrypt(content,key)});return id};
		await add('user','Show the safe code snippet.',0);
		const assistantMessageId=await add('assistant','Code snippet: [Chrome proof code](embed:'+embedId+')',1);
		process.stdout.write(JSON.stringify({chatId,embedId,ownerId:owner.id,title,chat,messages,messageIds,assistantMessageId}));
	`);
}

function persistChromeFixture(fixture:ChromeFixture,operation:'seed'|'cleanup'):void {
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
  print('chrome fixture applied')
 finally: await directus.close();await cache.close()
asyncio.run(main())
`;
	const output=execFileSync('docker',['compose','-f',COMPOSE,'exec','-T','-e','OPENMATES_CI_ISOLATED=1',
		'api','python','-c',program],{cwd:ROOT,input:JSON.stringify({...fixture,operation}),encoding:'utf8',timeout:90_000});
	expect(output.trim()).toBe('chrome fixture applied');
}

function chromeShareState(fixture:ChromeFixture):{isShared:boolean;sharePii:boolean} {
	const program=`
import asyncio,hashlib,json,logging,sys
logging.disable(logging.CRITICAL)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
async def main():
 data=json.load(sys.stdin);cache=CacheService();directus=DirectusService(cache_service=cache)
 try:
  chat=await directus.chat.get_chat_metadata(data['chatId'])
  assert chat and chat['hashed_user_id']==hashlib.sha256(data['ownerId'].encode()).hexdigest()
  print(json.dumps({'isShared':chat.get('is_shared') is True,'sharePii':chat.get('share_pii') is True}))
 finally: await directus.close();await cache.close()
asyncio.run(main())
`;
	return JSON.parse(execFileSync('docker',['compose','-f',COMPOSE,'exec','-T','-e','OPENMATES_CI_ISOLATED=1',
		'api','python','-c',program],{cwd:ROOT,input:JSON.stringify(fixture),encoding:'utf8',timeout:90_000}).trim());
}

function seedChromeEmbedAndCache(apiUrl:string,home:string,cli:string,fixture:ChromeFixture):void {
	const result=sdk<{ok:boolean}>(apiUrl,home,cli,`
		const owner=await client.whoAmI();if(owner.id!==input.ownerId)throw Error('Fixture owner changed');
		const {ws}=await client.openWsClient({taskUpdateJobs:false});
		const send=async(type,reply,payload)=>{const requestId=randomUUID(),receipt=ws.waitForMessage(reply,p=>p.request_id===requestId,30000);
			await ws.sendAsync(type,{...payload,request_id:requestId});return (await receipt).payload};
		try{
			const key=randomBytes(32),now=Math.floor(Date.now()/1000);
			await send('store_embed','store_embed_confirmed',{embed_id:input.embedId,
				encrypted_content:await encrypt(JSON.stringify({code:'export const chromeProof = true;',language:'typescript',filename:'chrome-proof.ts'}),key),
				encrypted_type:await encrypt('code',key),status:'finished',hashed_chat_id:hash(input.chatId),
				hashed_message_id:hash(input.assistantMessageId),hashed_user_id:hash(owner.id),created_at:now,updated_at:now,version_number:1});
			await send('store_embed_keys','store_embed_keys_confirmed',{keys:[{hashed_embed_id:hash(input.embedId),
				key_type:'master',hashed_chat_id:null,encrypted_embed_key:await encrypt(key,client.getMasterKeyBytes()),
				hashed_user_id:hash(owner.id),created_at:now}]});
			const embed=await client.getEmbed(input.embedId,{preferCache:true,chatId:input.chatId});
			if(embed.content.code!=='export const chromeProof = true;')throw Error('Code embed missing');
		}finally{ws.close()}
		await client.listChats(20,1,{forceRefresh:true});
		const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cliHome=process.env.HOME;
		if(!cliHome||!cliHome.startsWith(os.tmpdir()+path.sep))throw Error('Expected isolated CLI home');
		const cachePath=path.join(cliHome,'.openmates','sync_cache.json'),cache=JSON.parse(fs.readFileSync(cachePath,'utf8'));
		const row=cache.chats.find(chat=>chat.details.id===input.chatId);
		if(!row)throw Error('Owned chat missing from CLI cache');
		const chats=cache.chats.map(chat=>chat===row?{...chat,messages:input.messages.map(JSON.stringify)}:chat);
		fs.writeFileSync(cachePath,JSON.stringify({...cache,chats},null,2)+'\\n',{mode:0o600});
		const saved=await client.getChatMessages(input.chatId,{preferCache:true,maxHistoryPages:1});
		if(saved.messages.length!==input.messages.length)throw Error('Encrypted chat messages missing');
		process.stdout.write(JSON.stringify({ok:true}));
	`,fixture);
	expect(result.ok).toBe(true);
}

module.exports={makeChromeFixture,persistChromeFixture,chromeShareState,seedChromeEmbedAndCache};
