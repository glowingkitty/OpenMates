/** Client-encrypted history seeded only into the disposable CI stack. No inference. */
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

// This existing helper also isolates CLI credentials from the operator's account.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { workflowCliEnv } = require('./workflow-cli-e2e-helpers');
const repositoryRoot = path.resolve(__dirname, '../../../../..');
const compose = path.join(repositoryRoot, 'test-results/ci-private/compose.json');
type Row = Record<string, unknown>;
export type TimelineFixture = {
  chatId: string; ownerId: string; chat: Row; messages: Row[]; checkpoints: Row[];
};

export function createTimelineFixture(apiUrl: string, home: string): TimelineFixture {
  if (process.env.OPENMATES_CI_ISOLATED !== '1') throw new Error('Timeline fixture requires isolated CI');
  const sdk = path.join(repositoryRoot, 'frontend/packages/openmates-cli/dist/index.js');
  const source = `
    const {pathToFileURL}=require('node:url');
    const {randomUUID,randomBytes,createHash,webcrypto}=require('node:crypto');
    (async()=>{
      const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
      const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
      const owner=await client.whoAmI();
      const hashedOwner=createHash('sha256').update(owner.id).digest('hex');
      const encrypt=async(value,key)=>{
        const iv=randomBytes(12),cryptoKey=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
        return Buffer.concat([iv,Buffer.from(await webcrypto.subtle.encrypt({name:'AES-GCM',iv},cryptoKey,Buffer.from(value)))]).toString('base64');
      };
      const chatId=randomUUID(),key=randomBytes(32),now=Math.floor(Date.now()/1000),start=now-21000;
      const chat={id:chatId,hashed_user_id:hashedOwner,created_at:start,updated_at:now,
        last_edited_overall_timestamp:now,last_message_timestamp:start+19999,
        messages_v:20000,title_v:1,metadata_v:1,unread_count:0,
        encrypted_chat_key:await encrypt(key,client.getMasterKeyBytes()),
        encrypted_title:await encrypt('Timeline: ten thousand exchanges',key),
        encrypted_chat_summary:await encrypt('Synthetic retained history for timeline verification.',key)};
      const messages=[];
      for(let i=0;i<10000;i++){
        const userId=randomUUID();
        for(const role of ['user','assistant']){
          const id=role==='user'?userId:randomUUID(),created=start+messages.length;
          messages.push({id,client_message_id:id,chat_id:chatId,hashed_user_id:hashedOwner,
            role,created_at:created,updated_at:created,...(role==='assistant'?{user_message_id:userId}:{}),
            encrypted_sender_name:await encrypt(role==='user'?'You':'OpenMates',key),
            encrypted_content:await encrypt((role==='user'?'Question ':'Response ')+i+': project budget and train tickets.',key)});
        }
      }
      const checkpoints=[];
      for(const count of [6000,12000]) checkpoints.push({id:randomUUID(),chat_id:chatId,hashed_user_id:hashedOwner,
        encrypted_summary:await encrypt('Earlier project planning checkpoint '+count,key),
        compressed_up_to_timestamp:messages[count-1].created_at,
        compressed_up_to_message_id:messages[count-1].client_message_id,
        covered_message_ids:messages.slice(0,count).map(row=>row.client_message_id).sort(),
        compressed_message_count:count,summary_token_estimate:20,created_at:start+count,updated_at:start+count});
      process.stdout.write(JSON.stringify({chatId,ownerId:owner.id,chat,messages,checkpoints}));
    })().catch(error=>{console.error('Timeline fixture encryption failed:',error.message);process.exit(1)});
  `;
  return JSON.parse(execFileSync('node', ['-e', source, sdk], {
    cwd: repositoryRoot, env: workflowCliEnv(apiUrl, home), encoding: 'utf8',
    timeout: 120_000, maxBuffer: 32 * 1024 * 1024,
  }));
}

/** Only encrypted records cross this pipe; database access never runs on shared dev. */
export function persistTimelineFixture(fixture: TimelineFixture, operation: 'seed' | 'snapshot' | 'cleanup'): unknown {
  if (process.env.OPENMATES_CI_ISOLATED !== '1' || !fs.existsSync(compose)) {
    throw new Error('Timeline fixture requires disposable CI compose');
  }
  const program = `
import asyncio,hashlib,json,logging,os,sys
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED')=='1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.tasks.persistence_tasks import _chat_list_cache_data_from_metadata,_chat_versions_from_metadata
from backend.core.api.app.services.chat_timeline import timeline_page
async def main():
    data=json.load(sys.stdin); cache=CacheService(); directus=DirectusService(cache_service=cache)
    owner=hashlib.sha256(data['ownerId'].encode()).hexdigest(); chat_id=data['chatId']
    assert data['chat']['id']==chat_id and data['chat']['hashed_user_id']==owner
    assert len(data['messages'])==20000 and len(data['checkpoints'])==2
    assert all(row['chat_id']==chat_id and row['hashed_user_id']==owner and 'content' not in row for row in data['messages']+data['checkpoints'])
    try:
        headers={'Authorization':'Bearer '+await directus.ensure_auth_token(admin_required=True)}
        if data['operation']=='seed':
            created,duplicate=await directus.chat.create_chat_in_directus(data['chat'])
            assert created and not duplicate, 'Encrypted chat seed failed'
            for offset in range(0,len(data['messages']),400):
                response=await directus._make_api_request('POST',directus.base_url+'/items/messages',headers=headers,
                    json=data['messages'][offset:offset+400],params={'fields':'id'})
                assert response.status_code==200, 'Encrypted message batch seed failed'
                assert len(response.json()['data'])==min(400,len(data['messages'])-offset)
            for checkpoint in data['checkpoints']:
                created,_=await directus.create_item('chat_compression_checkpoints',checkpoint,admin_required=True)
                assert created, 'Encrypted checkpoint seed failed'
            assert await cache.add_chat_to_ids_versions(data['ownerId'],chat_id,data['chat']['last_edited_overall_timestamp'])
            assert await cache.set_chat_list_item_data(data['ownerId'],chat_id,_chat_list_cache_data_from_metadata(data['chat']))
            assert await cache.set_chat_versions(data['ownerId'],chat_id,_chat_versions_from_metadata(data['chat']))
            # Exercise the real metadata query independently of browser transport.
            # Retain database errors only for this content-free read.
            logging.getLogger().setLevel(logging.ERROR); logging.disable(logging.NOTSET)
            try:
                page=await timeline_page(directus=directus,s3=None,chat_id=chat_id,archived=False,before_timestamp=None,before_message_id=None)
                assert len(page['entries'])==200 and page['has_more'], 'Seeded catalogue preflight failed'
                continuation=await timeline_page(directus=directus,s3=None,chat_id=chat_id,archived=False,
                    before_timestamp=page['before']['created_at'],before_message_id=page['before']['message_id'])
                assert len(continuation['entries'])==200 and continuation['has_more'], 'Catalogue continuation preflight failed'
            finally: logging.disable(logging.CRITICAL)
        metadata=await directus.chat.get_chat_metadata(chat_id)
        if metadata:
            assert metadata['hashed_user_id']==owner, 'Fixture ownership changed'
        if data['operation']=='snapshot':
            assert metadata
            checkpoints=await directus.get_items('chat_compression_checkpoints',params={'filter':{'chat_id':{'_eq':chat_id}},'sort':'created_at','limit':20},no_cache=True,admin_required=True)
            print('OPENMATES_TIMELINE_FIXTURE_RESULT:'+json.dumps({'messages_v':metadata['messages_v'],'checkpoints':checkpoints}))
        elif data['operation']=='cleanup':
            if metadata:
                for checkpoint in data['checkpoints']:
                    await directus.delete_item('chat_compression_checkpoints',checkpoint['id'],admin_required=True)
                for offset in range(0,len(data['messages']),400):
                    response=await directus._make_api_request('DELETE',directus.base_url+'/items/messages',headers=headers,
                        json=[row['id'] for row in data['messages'][offset:offset+400]])
                    assert response.status_code==204, 'Fixture message cleanup failed'
                assert await directus.delete_item('chats',chat_id,admin_required=True)
            await cache.remove_chat_from_ids_versions(data['ownerId'],chat_id)
            print('OPENMATES_TIMELINE_FIXTURE_RESULT:null')
        else: print('OPENMATES_TIMELINE_FIXTURE_RESULT:null')
    finally:
        await directus.close(); await cache.close()
asyncio.run(main())
`;
  const output = execFileSync('docker', ['compose', '-f', compose, 'exec', '-T', '-e',
    'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program], {
    cwd: repositoryRoot, input: JSON.stringify({ ...fixture, operation }), encoding: 'utf8',
    timeout: 180_000, maxBuffer: 4 * 1024 * 1024,
  });
  const prefix = 'OPENMATES_TIMELINE_FIXTURE_RESULT:';
  const records = output.split(/\r?\n/).filter(line => line.startsWith(prefix));
  if (records.length !== 1) throw new Error('Invalid timeline fixture result protocol');
  return JSON.parse(records[0].slice(prefix.length));
}
