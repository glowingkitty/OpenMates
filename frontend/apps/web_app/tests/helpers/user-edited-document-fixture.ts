// contract-test-file: tooling
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Seed a real owned encrypted chat with a Document embed that already has a
 * user-made version 2, through the paired npm CLI client and the real routes
 * (store_embed, store_embed_diff, store_embed_keys, POST /v1/embeds/{id}/user-revisions).
 * No inference. The v2 commit leaves its pending chat notice unwritten on
 * purpose: the client under test must write it when it opens the chat.
 */
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const { CLI_DIST } = require('./cli-test-helpers');
const { workflowCliEnv } = require('./workflow-cli-e2e-helpers');
const ROOT = path.resolve(__dirname, '../../../../..');

export type EditedDocumentSeed = { chatId: string; embedId: string; embedRef: string };

export function seedUserEditedDocument(apiUrl: string, home: string): EditedDocumentSeed {
	const modulePath = path.join(path.dirname(CLI_DIST), 'cli-internal-client.js');
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
			const chatId=randomUUID(),userId=randomUUID(),assistantId=randomUUID(),embedId=randomUUID();
			const chatKey=randomBytes(32),embedKey=randomBytes(32),embedRef='kitchen-plan-notes';
			const now=Math.floor(Date.now()/1000);
			const doc=text=>JSON.stringify({type:'document',app_id:'docs',skill_id:'document',embed_ref:embedRef,
				title:'Kitchen plan notes',status:'finished',html:'<p>'+text+'</p>'});
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
					encrypted_content:await encrypt('Write down the kitchen plan',chatKey),
					encrypted_sender_name:await encrypt('You',chatKey),
					encrypted_category:await encrypt('general_knowledge',chatKey),
					encrypted_title:await encrypt('Kitchen plan '+chatId.slice(0,6),chatKey),
					encrypted_icon:await encrypt('file-text',chatKey),
					encrypted_chat_category:await encrypt('general_knowledge',chatKey),
					encrypted_chat_key:await encrypt(chatKey,client.getMasterKeyBytes()),
					versions:{messages_v:2,title_v:1,metadata_v:1,last_edited_overall_timestamp:now},
					message_history:[{message_id:assistantId,role:'assistant',created_at:now,
						encrypted_content:await encrypt('Here are the notes.\n\n[!](embed:'+embedRef+')',chatKey),
						encrypted_sender_name:await encrypt('Assistant',chatKey),
						encrypted_category:await encrypt('general_knowledge',chatKey)}]
				});
				const stored=(await metadataReceipt).payload;
				if(stored.chat_id!==chatId)throw Error('Encrypted metadata not accepted');
				const v1=await encrypt(doc('Version one: white cabinets'),embedKey);
				const receipt=await send('store_embed','store_embed_confirmed',{
					embed_id:embedId,chat_id:chatId,team_id:null,app_id:'docs',skill_id:'document',
					encrypted_content:v1,encrypted_type:await encrypt('document',embedKey),status:'finished',
					hashed_chat_id:hash(chatId),hashed_message_id:hash(assistantId),hashed_user_id:hash(owner.id),
					created_at:now,updated_at:now,version_number:1
				});
				if(receipt.embed_id!==embedId)throw Error('Embed store receipt mismatch');
				const keys=[
					{hashed_embed_id:hash(embedId),key_type:'master',hashed_chat_id:null,
						encrypted_embed_key:await encrypt(embedKey,client.getMasterKeyBytes()),hashed_user_id:hash(owner.id),created_at:now},
					{hashed_embed_id:hash(embedId),key_type:'chat',hashed_chat_id:hash(chatId),
						encrypted_embed_key:await encrypt(embedKey,chatKey),hashed_user_id:hash(owner.id),created_at:now}
				];
				const keyReceipt=await send('store_embed_keys','store_embed_keys_confirmed',{keys});
				if(keyReceipt.failed_count!==0)throw Error('Embed key wrappers were not confirmed');
				const diff=await send('store_embed_diff','store_embed_diff_confirmed',{
					embed_id:embedId,version_number:1,encrypted_snapshot:v1,created_at:now});
				if(diff.version_number!==1)throw Error('Version 1 snapshot was not stored');
				const v2=await encrypt(doc('Version two: oak cabinets'),embedKey);
				const response=await client.http.post('/v1/embeds/'+embedId+'/user-revisions',{
					operation_id:randomUUID(),scope:{kind:'chat',chat_id:chatId},action:'edit',
					expected_revision:1,expected_content_hash:hash(v1),
					head:{encrypted_content:v2,status:'finished',updated_at:now+1},
					history_rows:[{version_number:2,encrypted_snapshot:v2,created_at:now+1}]
				},client.getCliRequestHeaders());
				if(!response.ok||response.data.current_revision!==2||response.data.pending_notice!==true)
					throw Error('User revision v2 not committed: HTTP '+response.status+' '+JSON.stringify(response.data));
				process.stdout.write(JSON.stringify({chatId,embedId,embedRef}));
			}finally{ws.close()}
		})().catch(error=>{console.error('Edited document fixture:',error.message);process.exit(1)});
	`;
	return JSON.parse(execFileSync('node', ['-e', source, modulePath], {
		cwd: ROOT, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 150_000,
	}).trim());
}
