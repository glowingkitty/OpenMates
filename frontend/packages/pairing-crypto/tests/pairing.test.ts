import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createPairApprover, createPairContext, createPairReceiver,
  generateGrantSecret, generateReceiverCapability, hashPairSecret,
  type PairBundle,
} from '../src/index';

const fields = {
  token: 'ABC346',
  session_id: '00000000-0000-4000-8000-000000000001',
  receiver_token_hash: 'a'.repeat(64),
  authorizer_user_id: '00000000-0000-4000-8000-000000000002',
  auto_logout_minutes: 60 as const,
};
const context = createPairContext(fields);

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

function pauseSubtle(method: 'digest' | 'encrypt' | 'decrypt') {
  const original = crypto.subtle[method].bind(crypto.subtle) as unknown as (...args: unknown[]) => Promise<ArrayBuffer>;
  const entered = deferred<void>();
  const released = deferred<void>();
  vi.spyOn(crypto.subtle, method).mockImplementation((async (...args: unknown[]) => {
    entered.resolve();
    await released.promise;
    return original(...args);
  }) as never);
  return { entered: entered.promise, release: () => released.resolve() };
}

afterEach(() => vi.restoreAllMocks());

async function exchange() {
  const approver = await createPairApprover(context);
  const pin = approver.pin;
  const receiver = await createPairReceiver(context, pin);
  const ke2 = await approver.receiveRequest(receiver.request);
  const ke3 = await receiver.receiveResponse(ke2);
  await approver.verifyFinish(ke3);
  return { approver, receiver, ke2, ke3, pin };
}

describe('pairing v2 client-to-client OPAQUE', () => {
  // contract-test: direct surface=gui.web assertions=auth.pair-login.single-use-zk,auth.pair-login.session-grant
  it('binds both clients to one context and encrypts only after final proof', async () => {
    const approver = await createPairApprover(context);
    const pin = approver.pin;
    const receiver = await createPairReceiver(context, pin);
    const ke2 = await approver.receiveRequest(receiver.request);
    await expect(approver.encryptBundle({} as PairBundle)).rejects.toThrow('Pairing proof not verified');
    const ke3 = await receiver.receiveResponse(ke2);
    await approver.verifyFinish(ke3);
    const grant = await generateGrantSecret();
    const bundle: PairBundle = {
      protocol_version: 2,
      master_key_exported: 'synthetic-master-key',
      grant_secret: grant.secret,
      user_email_salt: 'synthetic-salt',
      hashed_email: 'synthetic-hashed-email',
      user_id: fields.authorizer_user_id,
    };
    const encrypted = await approver.encryptBundle(bundle);
    expect(await receiver.decryptBundle(encrypted.encrypted_bundle, encrypted.iv)).toEqual(bundle);
    expect(await hashPairSecret(grant.secret)).toBe(grant.hash);
    expect(JSON.stringify({ ke2, ke3, encrypted })).not.toContain(pin);
    expect(JSON.stringify(encrypted)).not.toContain(bundle.master_key_exported);
    await expect(approver.encryptBundle(bundle)).rejects.toThrow();
    await expect(receiver.decryptBundle(encrypted.encrypted_bundle, encrypted.iv)).rejects.toThrow();
  });

  // contract-test: direct surface=gui.web assertions=auth.pair-login.single-use-zk
  it('rejects a wrong PIN and cannot retry that receiver state', async () => {
    const approver = await createPairApprover(context);
    const wrong = approver.pin[0] === 'A' ? 'B' : 'A';
    const receiver = await createPairReceiver(context, wrong + approver.pin.slice(1));
    const ke2 = await approver.receiveRequest(receiver.request);
    await expect(receiver.receiveResponse(ke2)).rejects.toThrow();
    await expect(receiver.receiveResponse(ke2)).rejects.toThrow();
    approver.abort();
  });

  // contract-test: direct surface=gui.web assertions=auth.pair-login.single-use-zk
  it('rejects a changed context and a second message', async () => {
    const approver = await createPairApprover(context);
    const altered = createPairContext({ ...fields, auto_logout_minutes: 30 });
    const receiver = await createPairReceiver(altered, approver.pin);
    const ke2 = await approver.receiveRequest(receiver.request);
    await expect(approver.receiveRequest(receiver.request)).rejects.toThrow();
    await expect(receiver.receiveResponse(ke2)).rejects.toThrow();
    approver.abort();
  });

  // contract-test: direct surface=gui.web assertions=auth.pair-login.single-use-zk
  it('rejects malformed messages and fails closed', async () => {
    const approver = await createPairApprover(context);
    const pin = approver.pin;
    await expect(approver.receiveRequest('not base64!')).rejects.toThrow();
    const receiver = await createPairReceiver(context, pin);
    await expect(approver.receiveRequest(receiver.request)).rejects.toThrow();
    receiver.abort();
  });

  // contract-test: direct surface=gui.web assertions=auth.pair-login.single-use-zk
  it('rejects tampering with ciphertext or IV', async () => {
    const { approver, receiver } = await exchange();
    const grant = await generateGrantSecret();
    const encrypted = await approver.encryptBundle({
      protocol_version: 2, master_key_exported: 'synthetic-master-key', grant_secret: grant.secret,
      user_email_salt: 'synthetic-salt', hashed_email: 'synthetic-hash', user_id: fields.authorizer_user_id,
    });
    const last = encrypted.encrypted_bundle.at(-1)!;
    const tampered = encrypted.encrypted_bundle.slice(0, -1) + (last === 'A' ? 'B' : 'A');
    await expect(receiver.decryptBundle(tampered, encrypted.iv)).rejects.toThrow();
    await expect(receiver.decryptBundle(encrypted.encrypted_bundle, encrypted.iv)).rejects.toThrow();

    const second = await exchange();
    const sealed = await second.approver.encryptBundle({
      protocol_version: 2, master_key_exported: 'synthetic-master-key', grant_secret: grant.secret,
      user_email_salt: 'synthetic-salt', hashed_email: 'synthetic-hash', user_id: fields.authorizer_user_id,
    });
    const alteredIv = (sealed.iv[0] === 'A' ? 'B' : 'A') + sealed.iv.slice(1);
    await expect(second.receiver.decryptBundle(sealed.encrypted_bundle, alteredIv)).rejects.toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=auth.pair-login.session-grant
  it('generates 32-byte independent capability secrets', async () => {
    const a = await generateReceiverCapability();
    const b = await generateReceiverCapability();
    expect(a.secret).not.toBe(b.secret);
    expect(a.secret.length).toBe(43);
    expect(a.hash).toMatch(/^[0-9a-f]{64}$/);
    expect(await hashPairSecret(a.secret)).toBe(a.hash);
  });

  // contract-test: direct surface=gui.web assertions=auth.pair-login.single-use-zk,auth.pair-login.lifecycle
  it('does not restore PAKE state or release a proof after abort during key derivation', async () => {
    const approver = await createPairApprover(context);
    const receiver = await createPairReceiver(context, approver.pin);
    const ke2 = await approver.receiveRequest(receiver.request);
    const ke3 = await receiver.receiveResponse(ke2);

    const pausedServer = pauseSubtle('digest');
    const verifying = approver.verifyFinish(ke3);
    await pausedServer.entered;
    approver.abort();
    pausedServer.release();
    await expect(verifying).rejects.toThrow('Pairing exchange aborted');
    await expect(approver.encryptBundle({} as PairBundle)).rejects.toThrow();
    vi.restoreAllMocks();

    const nextApprover = await createPairApprover(context);
    const nextReceiver = await createPairReceiver(context, nextApprover.pin);
    const nextKe2 = await nextApprover.receiveRequest(nextReceiver.request);
    const pausedClient = pauseSubtle('digest');
    const finishing = nextReceiver.receiveResponse(nextKe2);
    await pausedClient.entered;
    nextReceiver.abort();
    pausedClient.release();
    await expect(finishing).rejects.toThrow('Pairing exchange aborted');
    await expect(nextReceiver.decryptBundle('AA', 'AA')).rejects.toThrow();
    nextApprover.abort();
  });

  // contract-test: direct surface=gui.web assertions=auth.pair-login.single-use-zk,auth.pair-login.lifecycle
  it('does not release an encrypted or decrypted bundle after abort during WebCrypto', async () => {
    const grant = await generateGrantSecret();
    const bundle: PairBundle = {
      protocol_version: 2, master_key_exported: 'synthetic-master-key', grant_secret: grant.secret,
      user_email_salt: 'synthetic-salt', hashed_email: 'synthetic-hash', user_id: fields.authorizer_user_id,
    };
    const first = await exchange();
    const pausedEncrypt = pauseSubtle('encrypt');
    const encrypting = first.approver.encryptBundle(bundle);
    await pausedEncrypt.entered;
    first.approver.abort();
    pausedEncrypt.release();
    await expect(encrypting).rejects.toThrow('Pairing exchange aborted');
    first.receiver.abort();
    vi.restoreAllMocks();

    const second = await exchange();
    const sealed = await second.approver.encryptBundle(bundle);
    const pausedDecrypt = pauseSubtle('decrypt');
    const decrypting = second.receiver.decryptBundle(sealed.encrypted_bundle, sealed.iv);
    await pausedDecrypt.entered;
    second.receiver.abort();
    pausedDecrypt.release();
    await expect(decrypting).rejects.toThrow('Pairing exchange aborted');
  });
});
