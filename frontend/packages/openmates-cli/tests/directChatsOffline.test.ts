// contract-test-file: cli
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const stateDir = mkdtempSync(join(tmpdir(), 'openmates-direct-offline-'));
process.env.OPENMATES_STATE_DIR = stateDir;
const { OpenMatesClient } = await import('../src/client.ts');
const { createAccountChatIdentity } = await import('../src/directChats.ts');
const { clearSession, purgeLocalPrivateData, saveTrustedAccountId, loadCachedDirectChatAccountKey,
  saveCachedDirectChatAccountKey, saveSession } = await import('../src/storage.ts');
const apiUrl = 'https://offline.example.invalid';
const accountId = '11111111-1111-4111-8111-111111111111';
const master = Buffer.from(randomBytes(32));
const session = {
  apiUrl, sessionId: 'session-one', wsToken: null, cookies: {}, masterKeyExportedB64: master.toString('base64'),
  hashedEmail: 'account-email-hash', userEmailSalt: 'salt', createdAt: 1700000000000,
  authorizerDeviceName: null, autoLogoutMinutes: null,
};
const cachePath = join(stateDir, 'direct_chat_account_key.json');
function writeSession(value = session): void {
  writeFileSync(join(stateDir, 'session.json'), JSON.stringify(value), { mode: 0o600 });
}
function client(value = session): InstanceType<typeof OpenMatesClient> {
  return new OpenMatesClient({ apiUrl: value.apiUrl, session: value });
}

// contract-test: supporting surface=cli assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation
test('cold process recovers only the opaque account backup and verified participant hash offline', async () => {
  const previousGuard = process.env.OPENMATES_ACCOUNT_GUARD;
  try {
    delete process.env.OPENMATES_ACCOUNT_GUARD;
    writeSession();
    const { identity, record } = await createAccountChatIdentity(master);
    const online = client() as any;
    online.whoAmI = async () => ({ id: accountId });
    online.http.get = async () => ({ ok: true, status: 200, data: { key: record } });
    assert.deepEqual(await online.ensureDirectChatIdentity(), identity);
    const disk = readFileSync(cachePath, 'utf8');
    assert.equal(statSync(cachePath).mode & 0o777, 0o600);
    assert.equal(disk.includes(identity.privateKey), false);
    assert.equal(disk.includes(master.toString('base64')), false);
    assert.equal(disk.includes(record.encrypted_private_key), true);
    saveCachedDirectChatAccountKey(session, apiUrl, accountId,
      { ...record, private_key: 'unexpected-cleartext' } as typeof record);
    assert.equal(readFileSync(cachePath, 'utf8').includes('unexpected-cleartext'), false);
    const child = `import {OpenMatesClient} from './src/client.ts'; import {loadSession} from './src/storage.ts';
      const c=new OpenMatesClient({apiUrl:'${apiUrl}',session:loadSession()});
      let networkCalls=0;
      c.whoAmI=async()=>{networkCalls++;throw new TypeError('offline')};
      c.http.get=async()=>{networkCalls++;throw new TypeError('offline')};
      const [key,hash]=await Promise.all([c.ensureDirectChatIdentity(),c.ownDirectChatHash()]);
      process.stdout.write(JSON.stringify({publicKey:key.publicKey,hash,networkCalls}));`;
    const output = execFileSync(process.execPath, ['--experimental-strip-types', '--loader', './tests/loader.mjs', '--input-type=module', '-e', child],
      { cwd: process.cwd(), env: { ...process.env, OPENMATES_STATE_DIR: stateDir }, encoding: 'utf8' });
    assert.deepEqual(JSON.parse(output), { publicKey: identity.publicKey,
      hash: createHash('sha256').update(accountId).digest('hex'), networkCalls: 0 });
    process.env.OPENMATES_ACCOUNT_GUARD = 'required';
    assert.equal(loadCachedDirectChatAccountKey(session, apiUrl), null);
    assert.throws(() => saveCachedDirectChatAccountKey(session, apiUrl, accountId, record), /owner changed/);
    delete process.env.OPENMATES_ACCOUNT_GUARD;
    saveTrustedAccountId(accountId);
    rmSync(cachePath);
    let release!: (value: unknown) => void;
    const pending = client() as any;
    pending.http.get = async () => new Promise(resolve => { release = resolve; });
    const staleRead = pending.ensureDirectChatIdentity();
    pending.session = { ...session, sessionId: 'switched-in-flight' };
    release({ ok: true, status: 200, data: { key: record } });
    await assert.rejects(staleRead, /Account changed/);
    saveCachedDirectChatAccountKey(session, apiUrl, accountId, record);
    chmodSync(cachePath, 0o400);
    const unwritable = client() as any;
    unwritable.whoAmI = async () => ({ id: accountId });
    unwritable.http.get = async () => ({ ok: true, status: 200, data: { key: record } });
    assert.deepEqual(await unwritable.ensureDirectChatIdentity(), identity);
    chmodSync(cachePath, 0o600);
    const other = await createAccountChatIdentity(master);
    saveCachedDirectChatAccountKey(session, apiUrl, accountId, {
      ...record, public_key: other.record.public_key, key_id: other.record.key_id,
    });
    const mismatched = client() as any;
    mismatched.http.get = async () => { throw new TypeError('offline'); };
    await assert.rejects(mismatched.ensureDirectChatIdentity(), /key pair mismatch/i);
    saveCachedDirectChatAccountKey(session, apiUrl, accountId, record);
    assert.equal(loadCachedDirectChatAccountKey({ ...session, sessionId: 'other' }, apiUrl), null);
    assert.equal(loadCachedDirectChatAccountKey({ ...session, createdAt: session.createdAt + 1 }, apiUrl), null);
    assert.equal(loadCachedDirectChatAccountKey({ ...session, hashedEmail: 'other' }, apiUrl), null);
    assert.equal(loadCachedDirectChatAccountKey(session, 'https://other.example.invalid'), null);
    const wrong = client({ ...session, sessionId: 'other' }) as any;
    wrong.http.get = async () => { throw new TypeError('offline'); };
    await assert.rejects(wrong.ensureDirectChatIdentity(), /offline/);
    writeFileSync(join(stateDir, 'trusted_account.json'), JSON.stringify({ accountId: 'other-account' }), { mode: 0o600 });
    assert.equal(loadCachedDirectChatAccountKey(session, apiUrl), null);
    clearSession();
    assert.equal(existsSync(cachePath), false);
    assert.equal(statSync(stateDir).mode & 0o777, 0o700);
    writeSession({ ...session, sessionId: 'session-two' });
    const nextSession = { ...session, sessionId: 'session-two' };
    saveCachedDirectChatAccountKey(nextSession, apiUrl, 'other-account', record);
    assert.equal(existsSync(cachePath), true);
    const switchedSession = { ...nextSession, sessionId: 'session-three' };
    saveSession(switchedSession, { replace: true });
    assert.equal(existsSync(cachePath), false);
    saveCachedDirectChatAccountKey(switchedSession, apiUrl, 'other-account', record);
    purgeLocalPrivateData();
    assert.equal(existsSync(cachePath), false);
    assert.equal(loadCachedDirectChatAccountKey(session, apiUrl), null);
  } finally {
    if (previousGuard === undefined) delete process.env.OPENMATES_ACCOUNT_GUARD;
    else process.env.OPENMATES_ACCOUNT_GUARD = previousGuard;
    rmSync(stateDir, { recursive: true, force: true });
  }
});
