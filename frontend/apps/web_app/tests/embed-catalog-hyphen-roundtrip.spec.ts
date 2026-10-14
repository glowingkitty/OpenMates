/* eslint-disable @typescript-eslint/no-require-imports */
/** Persists registered hyphenated catalog metadata through paired client encryption without inference. */
export {};

const { test, expect } = require('./console-monitor');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { getTestAccount } = require('./signup-flow-helpers');
const { waitForEmbedFinished } = require('./helpers/embed-test-helpers');
const { CLI_DIST } = require('./helpers/cli-test-helpers');
const { createWorkflowCliHome, removeWorkflowCliHome, loginWorkflowCliViaPair,
	runWorkflowCli, workflowCliEnv, workflowApiUrl } = require('./helpers/workflow-cli-e2e-helpers');

const ROOT = path.resolve(__dirname, '../../../..');
const QUERY = 'openmates_e2e_web_fixture_ai';
type Seed = { chatId: string; embedId: string; childId: string; ownerId: string; reminderId: string };

async function expandFixtureActivity(page: any) {
	const toggle = page.getByTestId('assistant-activity-toggle').last();
	// Older main renders cards directly and has no assistant activity toggle.
	if (await toggle.count() === 0) return;
	await expect(toggle).toBeVisible({ timeout: 30_000 });
	if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
}

function seedViaPairedCli(apiUrl: string, home: string): Seed {
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
			const embedId=randomUUID(),childId=randomUUID(),reminderId=randomUUID(),chatKey=randomBytes(32),embedKey=randomBytes(32);
			const now=Math.floor(Date.now()/1000),fence=String.fromCharCode(96).repeat(3);
			const newline=String.fromCharCode(10);
			const answer='The local result is ready.'+newline+newline+fence+'json'+newline+JSON.stringify({
				type:'app_skill_use',embed_id:embedId,app_id:'web',skill_id:'search',status:'finished'
			})+newline+fence+newline+newline+fence+'json'+newline+JSON.stringify({
				type:'app_skill_use',embed_id:reminderId,app_id:'reminder',skill_id:'set-reminder',status:'finished'
			})+newline+fence;
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
					encrypted_content:await encrypt('Search the web for ${QUERY}',chatKey),
					encrypted_sender_name:await encrypt('You',chatKey),
					encrypted_category:await encrypt('general_knowledge',chatKey),
					encrypted_title:await encrypt('Web preview backfill '+chatId.slice(0,6),chatKey),
					encrypted_icon:await encrypt('search',chatKey),
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
				let historyReady=false,lastObservation='chat absent from synced list';
				for(let attempt=0;attempt<30;attempt++){
					try{
						await client.ensureSynced(true,[chatId],{personal:true});
						const page=await client.listChats(20,1,{forceRefresh:true});
						if(page.chats.some(chat=>chat.id===chatId)){
							const history=await client.getChatMessagesWindow(chatId,{
								direction:'latest',limit:10,respectCompressionBoundary:false
							});
							lastObservation='fresh window roles='+history.messages.map(message=>message.role).join(',');
							if(history.messages.some(message=>message.role==='user')
								&&history.messages.some(message=>message.role==='assistant')){historyReady=true;break}
						}
					}catch(error){lastObservation='SDK read: '+(error?.message??String(error))}
					await new Promise(resolve=>setTimeout(resolve,1000));
				}
				if(!historyReady)throw Error('Encrypted chat history did not sync: '+lastObservation);
				const parent={app_id:'web',skill_id:'search',status:'finished',query:'${QUERY}',
					provider:'Brave Search',embed_ids:childId,result_count:1};
				const child={title:'OpenMates E2E Web Fixture',url:'https://app.dev.openmates.org/web/fixtures/ai-assistant',
					description:'A deterministic web result for the preview backfill regression.'};
				const reminder={app_id:'reminder',skill_id:'set-reminder',status:'finished',
					reminder_id:reminderId,prompt:'Encrypted catalog roundtrip fixture',
					message:'Encrypted catalog roundtrip fixture',trigger_at:now+86400,
					trigger_at_formatted:'Tomorrow',target_type:'new_chat',is_repeating:false};
				for(const [id,content,type] of [[embedId,parent,'app_skill_use'],[childId,child,'website'],
					[reminderId,reminder,'app_skill_use']]){
					const receipt=await send('store_embed','store_embed_confirmed',{
						embed_id:id,chat_id:chatId,team_id:null,
						app_id:id===reminderId?'reminder':'web',skill_id:id===reminderId?'set-reminder':'search',
						...(id===childId?{parent_embed_id:embedId}:{}),
						encrypted_content:await encrypt(JSON.stringify(content),embedKey),
						encrypted_type:await encrypt(type,embedKey),status:'finished',
						hashed_chat_id:hash(chatId),hashed_message_id:hash(assistantId),hashed_user_id:hash(owner.id),
						created_at:now,updated_at:now,version_number:1
					});
					if(receipt.embed_id!==id)throw Error('Embed store receipt mismatch');
				}
				const keys=(await Promise.all([embedId,childId,reminderId].map(async id=>[
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
				if(saved.content.embed_ids!==childId||saved.content.results)throw Error('Parent must need preview backfill');
				const savedChild=await client.getEmbed(childId,{preferCache:true,chatId});
				if(savedChild.type!=='website'||savedChild.content.url!==child.url
					||savedChild.content.title!==child.title)throw Error('Saved website child did not decrypt');
				const savedReminder=await client.getEmbed(reminderId,{preferCache:true,chatId});
				if(savedReminder.content.skill_id!=='set-reminder'
					||savedReminder.content.prompt!==reminder.prompt)throw Error('Hyphenated catalog did not decrypt');
				process.stdout.write(JSON.stringify({chatId,embedId,childId,reminderId,ownerId:owner.id}));
			}finally{ws.close()}
		})().catch(error=>{console.error('Encrypted backfill fixture:',error.message);process.exit(1)});
	`;
	return JSON.parse(execFileSync('node', ['-e', source, modulePath], {
		cwd: ROOT, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 90_000,
	}).trim());
}

// contract-test: supporting surface=cli.sdk assertions=chats.persistence.client-encrypted
function verifyPersistedReminder(apiUrl: string, home: string, seed: Seed): void {
	const modulePath = path.join(path.dirname(CLI_DIST), 'index.js');
	const source = String.raw`
		const {pathToFileURL}=require('node:url');
		(async()=>{
			const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
			const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
			await client.ensureSynced(true,[process.argv[2]],{personal:true});
			const saved=await client.getEmbed(process.argv[3]);
			if(saved.type!=='app_skill_use'||saved.content.app_id!=='reminder'
				||saved.content.skill_id!=='set-reminder'||saved.content.status!=='finished'
				||saved.content.prompt!=='Encrypted catalog roundtrip fixture'
				||saved.content.message!=='Encrypted catalog roundtrip fixture')
				throw Error('Persisted owner reminder content did not exactly decrypt after reload');
			process.stdout.write('true');
		})().catch(error=>{console.error('Persisted reminder:',error.message);process.exit(1)});
	`;
	expect(execFileSync('node', ['-e', source, modulePath, seed.chatId, seed.reminderId], {
		cwd: ROOT, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 60_000,
	}).trim()).toBe('true');
}

// contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,apps.library.embeds-account-paginated
test('registered hyphenated reminder catalog persists and decrypts after browser reload', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(300_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.CI_TEST_MODE !== 'e2e',
		'Requires disposable isolated browser and CLI backend');
	test.skip(!getTestAccount().email, 'Isolated test account credentials required');
	expect(fs.existsSync(CLI_DIST), 'Candidate paired CLI build required').toBe(true);
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('catalog-hyphen');
	let seed: Seed | undefined;
	try {
		await loginWorkflowCliViaPair(page, apiUrl, home, 'CATALOG_HYPHEN');
		const closeSettings = page.getByTestId('icon-button-close');
		await expect(closeSettings).toBeVisible({ timeout: 5_000 });
		await closeSettings.click();
		seed = seedViaPairedCli(apiUrl, home);
		await page.goto(`${process.env.PLAYWRIGHT_TEST_BASE_URL}/#chat-id=${seed.chatId}`,
			{ waitUntil: 'domcontentloaded' });
		for (let attempt = 0; attempt < 2; attempt++) {
			await page.reload({ waitUntil: 'domcontentloaded' });
			await expandFixtureActivity(page);
			const reminder = await waitForEmbedFinished(page, 'reminder', 'set-reminder');
			expect(await reminder.getAttribute('data-embed-id')).toBe(seed.reminderId);
			await expect(reminder).toContainText('Set Reminder');
			verifyPersistedReminder(apiUrl, home, seed);
		}
	} finally {
		try {
			if (seed) {
				const deletion = await runWorkflowCli(apiUrl, home, ['chats', 'delete', seed.chatId, '--yes'], 15_000);
				expect(deletion.code, `Paired CLI chat cleanup failed: ${deletion.stderr}`).toBe(0);
			}
		} finally { removeWorkflowCliHome(home); }
	}
});
