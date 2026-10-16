/* eslint-disable @typescript-eslint/no-require-imports */
/** Public example UUIDs can also exist in the authenticated owner's private cache. */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getTestAccount();

const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { createWorkflowCliHome, loginWorkflowCliViaPair, removeWorkflowCliHome,
  workflowApiUrl, workflowCliEnv } = require('./helpers/workflow-cli-e2e-helpers');
const repositoryRoot = path.resolve(__dirname, '../../../..');
const isolatedCompose = path.join(repositoryRoot, 'test-results/ci-private/compose.json');

type SourceFixture = { chatId: string; ownerId: string; embedId: string; staleId: string;
  chat: Record<string, unknown>; embed: Record<string, unknown>; keys: Array<Record<string, unknown>> };

function makeSourceFixture(apiUrl: string, home: string): SourceFixture {
  const sdk = path.resolve(__dirname, '../../../packages/openmates-cli/dist/index.js');
  const program = `
    const {pathToFileURL}=require('node:url');
    const {randomUUID,randomBytes,createHash,webcrypto}=require('node:crypto');
    (async()=>{
      const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);
      const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});
      const owner=await client.whoAmI();if(!owner.id||client.getActiveTeamId())throw Error('Expected paired Personal owner');
      const hash=value=>createHash('sha256').update(value).digest('hex');
      const encrypt=async(value,key)=>{const iv=randomBytes(12),k=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
        return Buffer.concat([iv,Buffer.from(await webcrypto.subtle.encrypt({name:'AES-GCM',iv},k,Buffer.from(value)))]).toString('base64')};
      const chatId=randomUUID(),embedId=randomUUID(),staleId=randomUUID(),key=randomBytes(32),now=Math.floor(Date.now()/1000);
      const ownerHash=hash(owner.id),chatHash=hash(chatId),master=client.getMasterKeyBytes();
      const chat={id:chatId,hashed_user_id:ownerHash,created_at:now,updated_at:now,last_edited_overall_timestamp:now,
        last_message_timestamp:now,messages_v:0,title_v:1,metadata_v:1,unread_count:0,
        encrypted_chat_key:await encrypt(key,master),encrypted_title:await encrypt('Source context fixture',key)};
      const hkdf=await webcrypto.subtle.importKey('raw',key,'HKDF',false,['deriveBits']);
      const embedKey=Buffer.from(await webcrypto.subtle.deriveBits({name:'HKDF',hash:'SHA-256',salt:Buffer.from('openmates-embed-key-v1'),info:Buffer.from(embedId)},hkdf,256));
      const embed={id:randomUUID(),embed_id:embedId,hashed_embed_id:hash(embedId),hashed_chat_id:chatHash,
        hashed_user_id:ownerHash,status:'finished',version_number:1,encryption_mode:'client',is_private:false,is_shared:false,
        encrypted_content:await encrypt('type: code\\nlanguage: text\\ncode: SOURCE_CONTEXT_RENDER_MARKER\\nfilename: source-proof.txt\\nstatus: finished\\nline_count: 1',embedKey),
        encrypted_type:await encrypt('code',embedKey),created_at:now,updated_at:now};
      const keys=[{id:randomUUID(),hashed_embed_id:hash(embedId),hashed_user_id:ownerHash,key_type:'master',hashed_chat_id:null,
        encrypted_embed_key:await encrypt(embedKey,master),created_at:now},
        {id:randomUUID(),hashed_embed_id:hash(embedId),hashed_user_id:ownerHash,key_type:'chat',hashed_chat_id:chatHash,
        encrypted_embed_key:await encrypt(embedKey,key),created_at:now}];
      process.stdout.write(JSON.stringify({chatId,ownerId:owner.id,embedId,staleId,chat,embed,keys}));
    })().catch(error=>{console.error('Source fixture failed:',error.message);process.exit(1)});
  `;
  return JSON.parse(execFileSync('node', ['-e', program, sdk], {
    cwd: repositoryRoot, env: workflowCliEnv(apiUrl, home), encoding: 'utf8', timeout: 90_000,
  }).trim());
}

function persistSourceFixture(fixture: SourceFixture, operation: 'seed' | 'cleanup'): void {
  expect(fs.existsSync(isolatedCompose)).toBe(true);
  const program = `
import asyncio,hashlib,json,logging,os,sys
logging.disable(logging.CRITICAL)
assert os.environ.get('OPENMATES_CI_ISOLATED')=='1'
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.tasks.persistence_tasks import _chat_list_cache_data_from_metadata,_chat_versions_from_metadata
async def main():
    data=json.load(sys.stdin);cache=CacheService();directus=DirectusService(cache_service=cache)
    owner=hashlib.sha256(data['ownerId'].encode()).hexdigest();chat_hash=hashlib.sha256(data['chatId'].encode()).hexdigest()
    assert data['chat']['hashed_user_id']==owner and data['embed']['hashed_user_id']==owner
    assert data['embed']['hashed_chat_id']==chat_hash
    try:
        if data['operation']=='seed':
            created,duplicate=await directus.chat.create_chat_in_directus(data['chat']);assert created and not duplicate
            created,_=await directus.create_item('embeds',data['embed'],admin_required=True);assert created
            for key in data['keys']:
                assert key['hashed_user_id']==owner and key['hashed_embed_id']==data['embed']['hashed_embed_id']
                created,_=await directus.create_item('embed_keys',key,admin_required=True);assert created
            assert await cache.add_chat_to_ids_versions(data['ownerId'],data['chatId'],data['chat']['last_edited_overall_timestamp'])
            assert await cache.set_chat_list_item_data(data['ownerId'],data['chatId'],_chat_list_cache_data_from_metadata(data['chat']))
            assert await cache.set_chat_versions(data['ownerId'],data['chatId'],_chat_versions_from_metadata(data['chat']))
        else:
            metadata=await directus.chat.get_chat_metadata(data['chatId']);assert metadata and metadata['hashed_user_id']==owner
            for key in data['keys']:
                rows=await directus.get_items('embed_keys',params={'filter':{'id':{'_eq':key['id']}},'limit':1},no_cache=True,admin_required=True)
                if rows:
                    assert rows[0]['hashed_user_id']==owner and rows[0]['hashed_embed_id']==data['embed']['hashed_embed_id']
                    assert await directus.delete_item('embed_keys',key['id'],admin_required=True)
            rows=await directus.get_items('embeds',params={'filter':{'id':{'_eq':data['embed']['id']}},'limit':1},no_cache=True,admin_required=True)
            if rows:
                assert rows[0]['hashed_user_id']==owner and rows[0]['hashed_chat_id']==chat_hash
                assert await directus.delete_item('embeds',data['embed']['id'],admin_required=True)
            assert await directus.delete_item('chats',data['chatId'],admin_required=True)
            await cache.remove_chat_from_ids_versions(data['ownerId'],data['chatId'])
        print('source fixture applied')
    finally:await directus.close();await cache.close()
asyncio.run(main())
`;
  const output = execFileSync('docker', ['compose', '-f', isolatedCompose, 'exec', '-T', '-e',
    'OPENMATES_CI_ISOLATED=1', 'api', 'python', '-c', program], {
    cwd: repositoryRoot, input: JSON.stringify({ ...fixture, operation }), encoding: 'utf8', timeout: 90_000,
  });
  expect(output.trim()).toBe('source fixture applied');
}


test.describe('example embed UUID isolation', () => {
  skipWithoutCredentials(test, email, password, otpKey);

  // contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  test('authenticated same-ID private cache survives opening a public example', async ({ page }: { page: any }) => {
    test.setTimeout(120_000);
    await loginToTestAccount(page);
    const input = {
      exampleChatId: 'example-berlin-english-speaking-gp',
    };
    const check = async (seedPrivate: boolean) => page.evaluate(async (data: typeof input & { seedPrivate: boolean }) => {
      const hook = (window as typeof window & {
        __openmatesE2EExampleEmbedCollision?: (value: typeof data) => Promise<{
          privateCachePreserved: boolean; privateResolverPreserved: boolean; publicResolverSelected: boolean;
          missingPublicFixtureBlocked: boolean; privateRefIndexPreserved: boolean; privatePiiPreserved: boolean;
        }>;
      }).__openmatesE2EExampleEmbedCollision;
      if (!hook) throw new Error('Scoped collision hook unavailable');
      return hook(data);
    }, { ...input, seedPrivate });

    expect(await check(true)).toEqual({
      privateCachePreserved: true,
      privateResolverPreserved: true,
      publicResolverSelected: true,
      missingPublicFixtureBlocked: true,
      privateRefIndexPreserved: true,
      privatePiiPreserved: true,
    });
    await page.evaluate((chatId: string) => { window.location.hash = `#chat-id=${chatId}`; }, input.exampleChatId);
    await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 25_000 });
    await expect(page.getByTestId('embed-preview').first()).toBeVisible({ timeout: 25_000 });
    await page.evaluate(() => document.dispatchEvent(new CustomEvent('embedfullscreen', {
      detail: { embedId: '11111111-1111-4111-8111-111111111111', sourceChatId: 'e2e-stale-source-chat' },
    })));
    await expect(page.getByTestId('embed-fullscreen-container')).toHaveCount(0);
    expect(await check(false), 'Opening the example must not replace the owner cache').toEqual({
      privateCachePreserved: true,
      privateResolverPreserved: true,
      publicResolverSelected: true,
      missingPublicFixtureBlocked: true,
      privateRefIndexPreserved: true,
      privatePiiPreserved: true,
    });
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,public-example-chats.transcript.safe-rendering,chats.sync.key-gated-recovery
  test('authorized source preview renders while another chat is active and unavailable source stops retrying', async ({ page }: { page: any }, testInfo: any) => {
    test.setTimeout(240_000);
    test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
      || process.env.CI_TEST_MODE !== 'e2e', 'Requires isolated owner-encrypted fixtures');
    const apiUrl = workflowApiUrl(), home = createWorkflowCliHome('resolver-source-context');
    let fixture: SourceFixture | undefined;
    const reads: Array<{ owningSource: boolean; kind: string }> = [];
    try {
      await loginWorkflowCliViaPair(page, apiUrl, home, 'RESOLVER_SOURCE_CONTEXT');
      await page.evaluate(() => { window.location.hash = '#chat-id=example-berlin-english-speaking-gp'; });
      await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 25_000 });
      fixture = makeSourceFixture(apiUrl, home);
      persistSourceFixture(fixture, 'seed');
      const authorized = await page.request.get(`${apiUrl}/v1/embeds/chats/${fixture.chatId}/embeds/${fixture.embedId}`);
      expect(authorized.status()).toBe(200);
      const protectedHead = await authorized.json();
      expect(protectedHead.embed.encrypted_content).toBeTruthy();
      expect(JSON.stringify(protectedHead)).not.toContain('SOURCE_CONTEXT_RENDER_MARKER');
      page.on('request', (request: any) => {
        const pathname = new URL(request.url()).pathname;
        const match = pathname.match(/^\/v1\/embeds\/chats\/([^/]+)\/embeds\/([^/]+)$/);
        if (!match || !fixture || ![fixture.embedId, fixture.staleId].includes(match[2])) return;
        reads.push({ owningSource: match[1] === fixture.chatId, kind: match[2] === fixture.embedId ? 'valid' : 'unavailable' });
      });
      const probe = async (embedId: string, cleanup = false) => page.evaluate(async (data: {
        exampleChatId: string; sourceProbe: { chatId: string; embedId: string; cleanup: boolean }
      }) => {
        const hook = (window as typeof window & { __openmatesE2EExampleEmbedCollision?: (input: typeof data) => Promise<unknown> }).__openmatesE2EExampleEmbedCollision;
        if (!hook) throw new Error('Existing scoped collision hook unavailable');
        return hook(data);
      }, { exampleChatId: 'example-berlin-english-speaking-gp', sourceProbe: { chatId: fixture!.chatId, embedId, cleanup } });
      expect(await probe(fixture.embedId)).toEqual({ sourceProbeMounted: true, sourceDiffersFromActive: true });
      const preview = page.getByTestId('e2e-source-context-preview');
      await expect(preview.getByText('SOURCE_CONTEXT_RENDER_MARKER')).toBeVisible({ timeout: 25_000 });
      await expect(preview).toBeInViewport({ ratio: 1 });
      await expect(preview.getByText('Source fetch · component integration', { exact: true })).toBeInViewport({ ratio: 1 });
      await expect(preview.getByText('SOURCE_CONTEXT_RENDER_MARKER')).toBeInViewport({ ratio: 1 });
      expect(reads.filter(row => row.kind === 'valid')).toEqual([{ owningSource: true, kind: 'valid' }]);
      await expect(page.getByTestId('example-chat-badge')).toBeVisible();
      await expect(page.getByTestId('example-chat-badge')).toBeInViewport({ ratio: 1 });
      expect(await probe(fixture.staleId)).toEqual({ sourceProbeMounted: true, sourceDiffersFromActive: true });
      await expect(preview.getByText('Preview unavailable', { exact: true })).toBeVisible({ timeout: 20_000 });
      await expect(preview).toBeInViewport({ ratio: 1 });
      await expect(preview.getByText('Preview unavailable', { exact: true })).toBeInViewport({ ratio: 1 });
      const terminalRequests = reads.filter(row => row.kind === 'unavailable').length;
      expect(terminalRequests).toBe(1);
      // Advancing beyond the resolver's10s cooldown proves the existing
      // terminal state does not start its own poll loop.
      await page.clock.install();
      await page.clock.runFor(11_000);
      await expect(preview.getByText('Preview unavailable', { exact: true })).toBeVisible();
      await expect(preview.getByText('Preview unavailable', { exact: true })).toBeInViewport({ ratio: 1 });
      expect(reads.filter(row => row.kind === 'unavailable')).toHaveLength(terminalRequests);
      expect(reads.every(row => row.owningSource)).toBe(true);
      await testInfo.attach('caller-source-preview-verdict', {
        body: JSON.stringify({ proofKind: 'source-fetch/component-integration', previewInViewport: true,
          markerInViewport: true, terminalInViewport: true, authorizedReadStatus: 200, sourceDiffersFromActive: true,
          validRequests: 1, unavailableTerminalRequests: terminalRequests, requestsAfterTerminal: 0,
          owningSourceOnly: true, encryptedBodyBoundary: true }), contentType: 'application/json',
      });
      await probe(fixture.staleId, true);
    } finally {
      if (fixture) persistSourceFixture(fixture, 'cleanup');
      removeWorkflowCliHome(home);
    }
  });

});
