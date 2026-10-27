// contract-test-file: tooling
/* eslint-disable @typescript-eslint/no-require-imports */
/** Seed genuine owned encrypted history and embed groups through the paired CLI, without inference. */
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const { CLI_DIST } = require('./cli-test-helpers');
const { workflowCliEnv } = require('./workflow-cli-e2e-helpers');
const ROOT = path.resolve(__dirname, '../../../../..');
const QUERY = 'deterministic historical image';
export type Seed = { chatId: string; embedId: string; childId: string; ownerId: string; cachedChildIds: string[] };

export function seedViaPairedCli(apiUrl: string, home: string, kind: 'image' | 'event' | 'read' = 'image', cachedChildCount = 0, includeSearchReference = false, readResult: Record<string, unknown> | null = null): Seed {
	const modulePath = path.join(path.dirname(CLI_DIST), 'index.js');
	const source = String.raw`
		const {pathToFileURL}=require('node:url');
		const {randomUUID,randomBytes,createHash,webcrypto}=require('node:crypto');
		(async()=>{
			const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
			const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
			const owner=await client.whoAmI();
			if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal account');
			const hash=value=>createHash('sha256').update(value).digest('hex');
			const encrypt=async(value,key)=>{
				const iv=randomBytes(12),cryptoKey=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
				return Buffer.concat([iv,Buffer.from(await webcrypto.subtle.encrypt({name:'AES-GCM',iv},cryptoKey,
					Buffer.from(value)))]).toString('base64');
			};
			const chatId=randomUUID(),userId=randomUUID(),assistantId=randomUUID();
			const embedId=randomUUID(),childId=randomUUID(),chatKey=randomBytes(32),embedKey=randomBytes(32);
			const cachedChildIds=Array.from({length:${cachedChildCount}},()=>randomUUID());
			const childIds=[...cachedChildIds,childId];
			const eventFixture=${kind === 'event'},readFixture=${kind === 'read'};
			const actualReadResult=${JSON.stringify(readResult)};
			if(readFixture&&typeof actualReadResult?.markdown!=='string')throw Error('Actual extracted markdown is required');
			const appId=eventFixture?'events':readFixture?'web':'images',skillId=readFixture?'read':'search';
			const now=Math.floor(Date.now()/1000);
			const newline=String.fromCharCode(10);
			const answer=readFixture?'Saved public page '+chatId+newline+newline+String.fromCharCode(96).repeat(3)+'json'+newline+JSON.stringify({type:'app_skill_use',embed_id:embedId,app_id:'web',skill_id:'read',status:'finished'})+newline+String.fromCharCode(96).repeat(3):'Historical result recovery '+chatId+newline+newline+(eventFixture
				?'[Freelance Barcamp Berlin](embed:freelance-barcamp-berlin-M9b)'
				:'[!](embed:historical-image-result)')
				+(eventFixture?'':newline+newline+'[!](embed:unrelated-ref-must-not-fetch)')
				+(${includeSearchReference}?newline+newline+String.fromCharCode(96).repeat(3)+'json'+newline
					+JSON.stringify({type:'app_skill_use',embed_id:embedId})+newline+String.fromCharCode(96).repeat(3):'');
			const {ws}=await client.openWsClient({taskUpdateJobs:false});
			const send=async(type,reply,payload)=>{
				const requestId=randomUUID();
				const receipt=ws.waitForMessage(reply,p=>p.request_id===requestId,30000);
				await ws.sendAsync(type,{...payload,request_id:requestId});
				return (await receipt).payload;
			};
			try{
				const metadataReceipt=ws.waitForMessage('encrypted_metadata_stored',p=>p.chat_id===chatId,30000);
				await ws.sendAsync('encrypted_chat_metadata',{
					chat_id:chatId,message_id:userId,team_id:null,created_at:now-1,
					encrypted_content:await encrypt(readFixture?'Read the controlled public article':'Find the historical image fixture',chatKey),
					encrypted_sender_name:await encrypt('You',chatKey),
					encrypted_category:await encrypt('general_knowledge',chatKey),
					encrypted_title:await encrypt((readFixture?'Saved public page ':'Historical image recovery ')+chatId.slice(0,6),chatKey),
					encrypted_icon:await encrypt('image',chatKey),
					encrypted_chat_category:await encrypt('general_knowledge',chatKey),
					encrypted_chat_key:await encrypt(chatKey,client.getMasterKeyBytes()),
					versions:{messages_v:2,title_v:1,metadata_v:1,last_edited_overall_timestamp:now},
					message_history:[{message_id:assistantId,role:'assistant',created_at:now,
						encrypted_content:await encrypt(answer,chatKey),
						encrypted_sender_name:await encrypt('Assistant',chatKey),
						encrypted_category:await encrypt('general_knowledge',chatKey)}]
				});
				const stored=(await metadataReceipt).payload;
				if(stored.chat_id!==chatId||stored.message_id!==userId)throw Error('Encrypted metadata not accepted');
				let historyReady=false,lastObservation='owned encrypted message window not ready';
				for(let attempt=0;attempt<30;attempt++){
					try{
						await client.ensureSynced(true,[chatId],{personal:true});
						const history=await client.getChatMessagesWindow(chatId,{
							direction:'latest',limit:10,respectCompressionBoundary:false
						});
						lastObservation='fresh window roles='+history.messages.map(message=>message.role).join(',');
						if(history.messages.some(message=>message.role==='user')
							&&history.messages.some(message=>message.role==='assistant')){historyReady=true;break}
					}catch(error){lastObservation='SDK read: '+(error?.message??String(error))}
					await new Promise(resolve=>setTimeout(resolve,1000));
				}
				if(!historyReady)throw Error('Encrypted chat history did not sync: '+lastObservation);
				const parent=readFixture?{app_id:'web',skill_id:'read',status:'finished',url:actualReadResult.url,results:[actualReadResult]}:{app_id:appId,skill_id:skillId,status:'finished',query:'${QUERY}',
					provider:eventFixture?'ExampleEvents':'Brave Search',embed_ids:childIds.join('|'),result_count:childIds.length};
				const child=eventFixture?{type:'event_result',app_id:'events',skill_id:'search',
					embed_ref:'freelance-barcamp-berlin-M9b',title:'Freelance Barcamp Berlin',provider:'ExampleEvents',
					url:'https://example.com/events/barcamp',date_start:'2026-11-14T09:00:00+01:00',is_paid:false,
					venue:{name:'Original encrypted event venue',address:'Original fixture street 12',city:'Berlin'},
					organizer:{name:'Historical event fixture'},description:'Recovered encrypted event details'}
					:{type:'image_result',app_id:'images',skill_id:'search',embed_ref:'historical-image-result',title:'Historical image fixture',
                    image_url:'/favicon.png',thumbnail_url:'/favicon.png',
                    source_page_url:'https://app.dev.openmates.org',source:'openmates.org',description:'Deterministic encrypted historical image'};
				const rows=[[embedId,parent,'app_skill_use'],...(readFixture?[]:childIds.map(id=>[id,id===childId?child:
					{...child,embed_ref:'cached-event-'+id,title:'Cached event '+id},eventFixture?'event_result':'image_result']))];
				for(const [id,content,type] of rows){
					const receipt=await send('store_embed','store_embed_confirmed',{
						embed_id:id,chat_id:chatId,team_id:null,
						app_id:appId,skill_id:skillId,
						...(id!==embedId?{parent_embed_id:embedId}:{}),
						encrypted_content:await encrypt(JSON.stringify(content),embedKey),
						encrypted_type:await encrypt(type,embedKey),status:'finished',
						hashed_chat_id:hash(chatId),hashed_message_id:hash(assistantId),hashed_user_id:hash(owner.id),
						created_at:now,updated_at:now,version_number:1
					});
					if(receipt.embed_id!==id)throw Error('Embed store receipt mismatch');
				}
				const keys=(await Promise.all([embedId].map(async id=>[
					{hashed_embed_id:hash(id),key_type:'master',hashed_chat_id:null,
						encrypted_embed_key:await encrypt(embedKey,client.getMasterKeyBytes()),
						hashed_user_id:hash(owner.id),created_at:now},
					{hashed_embed_id:hash(id),key_type:'chat',hashed_chat_id:hash(chatId),
						encrypted_embed_key:await encrypt(embedKey,chatKey),
						hashed_user_id:hash(owner.id),created_at:now}
				]))).flat();
				const keyReceipt=await send('store_embed_keys','store_embed_keys_confirmed',{keys});
				if(keyReceipt.created_count!==keys.length||keyReceipt.failed_count!==0)throw Error('Embed key wrappers were not exactly confirmed');
				await client.ensureSynced(true,[chatId],{personal:true});
				const saved=await client.getEmbed(embedId,{preferCache:true,chatId});
				if(readFixture){if(saved.content.results?.[0]?.markdown!==actualReadResult.markdown)throw Error('Saved full markdown changed')}
				else if(saved.content.embed_ids!==childIds.join('|')||saved.content.results)throw Error('Parent must contain child IDs without inline results');
				process.stdout.write(JSON.stringify({chatId,embedId,childId,ownerId:owner.id,cachedChildIds}));
			}finally{ws.close()}
		})().catch(error=>{console.error('Encrypted image fixture:',error.message);process.exit(1)});
	`;
	return JSON.parse(execFileSync('node', ['-e', source, modulePath], {
		cwd: ROOT, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 150_000,
	}).trim());
}

