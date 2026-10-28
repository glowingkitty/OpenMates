// @vitest-environment node
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import { createContext, runInContext } from 'node:vm';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createWebPIINetworkBroker, WEB_PII_BROKER_FAILURE_CODES } from '../webPIINetworkBroker';
import { licenseStorageKey, parseLicenseJSON, PII_ASSET_PATH, PII_DEVICE_KEY, PII_LICENSE_BASE, validateLicenseRequest, validateStoredLicense, verifyLicenseToken } from '../webPIINetworkPolicy';

vi.mock('../webPIIRuntimeManifest', () => ({ piiPinnedFiles: {
  'sdk.js': { bytes: 3, sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' },
} }));
const encode = (value: unknown) => new TextEncoder().encode(JSON.stringify(value));
const hostname = 'app.openmates.org';
const origin = `https://${hostname}`;
const installId = 'cd5bc78c-c557-4c42-91a5-ab8f90b4ad06';
const grant = () => ({ installId, model: 'redact', modelVersion: 'v0.4.0', sdk: { name: 'desert-ant-core', version: '4.1.0' }, platform: 'web', app: { id: hostname } });
const request = (url = `${origin}${PII_ASSET_PATH}sdk.js`, extra = {}) => ({ kind: 'pii-network', id: 1, url, method: 'GET', headers: [], ...extra });
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(resolve => setTimeout(resolve, 0)); };
let local: Map<string, string>;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto);
  local = new Map([['openmates.pii.license.installId.v1', installId]]);
  vi.stubGlobal('window', { location: { origin, hostname } });
  vi.stubGlobal('localStorage', { getItem: (key: string) => local.get(key) ?? null, setItem: (key: string, value: string) => local.set(key, value), removeItem: (key: string) => local.delete(key) });
  fetchMock = vi.fn().mockResolvedValue(new Response('abc'));
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('caches', { open: vi.fn().mockRejectedValue(new Error('storage unavailable')) });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function fixture() {
  const worker = { postMessage: vi.fn() }; const onViolation = vi.fn();
  const broker = createWebPIINetworkBroker(worker, { onViolation });
  return { worker, onViolation, broker };
}

describe('PII trusted network broker', () => {
  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('uses a host-controlled install identity and transfers only verified asset bytes with credential-free transport', async () => {
    const { worker, broker, onViolation } = fixture(); await broker.initialize();
    expect(worker.postMessage.mock.calls[0][0]).toEqual({ kind: 'pii-init', values: { [PII_DEVICE_KEY]: installId } });
    expect(broker.handleMessage(request())).toBe(true); await settle();
    expect(fetchMock).toHaveBeenCalledWith(`${origin}${PII_ASSET_PATH}sdk.js`, expect.objectContaining({ method: 'GET', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer', mode: 'same-origin' }));
    expect(worker.postMessage.mock.calls[1][0]).toMatchObject({ kind: 'pii-network-result', id: 1, status: 200, body: new TextEncoder().encode('abc') });
    expect(onViolation).not.toHaveBeenCalled();
    broker.dispose();
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it.each([
    request(`${origin}${PII_ASSET_PATH}sdk.js?prompt=secret`),
    request(`${origin}${PII_ASSET_PATH}../sdk.js`),
    request(`${origin}${PII_ASSET_PATH}worker.js`),
    request('https://huggingface.co/desert-ant-labs/redact/resolve/v0.4.0/redact.tflite'),
    request('https://events.desertant.com/api/v1/report', { method: 'POST', body: encode({ text: 'private' }) }),
    request(`${PII_LICENSE_BASE}license?text=private`, { method: 'POST' }),
    request(undefined, { credentials: 'include' }),
    request(undefined, { headers: [['x-private-text', 'secret']] }),
  ])('rejects unreviewed URL/method/options before any network call (%j)', async message => {
    const { broker, onViolation } = fixture(); await broker.initialize();
    broker.handleMessage(message); await settle();
    expect(fetchMock).not.toHaveBeenCalled(); expect(onViolation).toHaveBeenCalledOnce();
    expect(WEB_PII_BROKER_FAILURE_CODES).toContain(onViolation.mock.calls[0][0]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it.each(['abd', 'abcdef', '<html>fallback</html>'])('fails closed on asset integrity/size failure (%s)', async bytes => {
    fetchMock.mockResolvedValue(new Response(bytes));
    const { broker, worker, onViolation } = fixture(); await broker.initialize();
    broker.handleMessage(request()); await settle();
    expect(worker.postMessage).toHaveBeenCalledTimes(1); expect(onViolation).toHaveBeenCalledOnce();
    expect(onViolation).toHaveBeenCalledWith('asset-integrity');
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('reports a fixed transport failure code without forwarding exception content', async () => {
    fetchMock.mockRejectedValue(new Error('private-input-must-never-be-reported'));
    const { broker, onViolation } = fixture(); await broker.initialize(); broker.handleMessage(request()); await settle();
    expect(onViolation).toHaveBeenCalledWith('asset-network');
    expect(JSON.stringify(onViolation.mock.calls)).not.toContain('private-input');
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('rejects licensing transport back to the SDK, permits a genuine retry, and suppresses disposed rejections', async () => {
    const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
    const part = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
    const input = `${part({ alg: 'ES256', typ: 'dal-license+jwt', kid: 'prod-20261008' })}.${part({ v: 1, lid: 'server-license', period: '2026-10', periodEnd: '2026-11-01T00:00:00Z', iat: 1 })}`;
    const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, pair.privateKey, new TextEncoder().encode(input));
    const token = `${input}.${Buffer.from(signature).toString('base64url')}`;
    vi.spyOn(crypto.subtle, 'importKey').mockResolvedValue(pair.publicKey);
    fetchMock.mockRejectedValueOnce(new Error('private-browser-network-details'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ token }), { headers: { 'content-type': 'application/json' } }));
    const { broker, worker, onViolation } = fixture(); await broker.initialize();
    const message = (id: number) => request(`${PII_LICENSE_BASE}license`, { id, method: 'POST', headers: [['content-type', 'application/json']], body: encode(grant()) });
    broker.handleMessage(message(1)); await settle();
    expect(worker.postMessage.mock.calls[1]).toEqual([{ kind: 'pii-network-error', id: 1 }]);
    expect(onViolation).not.toHaveBeenCalled();
    broker.handleMessage(message(2)); await settle();
    expect(worker.postMessage.mock.calls[2][0]).toMatchObject({ kind: 'pii-network-result', id: 2, status: 200, body: encode({ token }) });
    expect(fetchMock).toHaveBeenCalledTimes(2); expect(onViolation).not.toHaveBeenCalled();
    expect(JSON.stringify(worker.postMessage.mock.calls)).not.toContain('private-browser-network-details');
    let rejectNetwork!: (reason: Error) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((_resolve, reject) => { rejectNetwork = reject; }));
    broker.handleMessage(message(3)); await settle(); broker.dispose();
    rejectNetwork(new Error('private-browser-network-details')); await settle();
    expect(worker.postMessage).toHaveBeenCalledTimes(3); expect(onViolation).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it.each(['pii-network-error', 'pii-network-result', 'pii-init'])('rejects a worker forging a host-only %s envelope', async kind => {
    const { broker, worker, onViolation } = fixture(); await broker.initialize();
    expect(broker.handleMessage({ kind, id: 1, error: 'private-input' })).toBe(true);
    expect(onViolation).toHaveBeenCalledWith('message'); expect(fetchMock).not.toHaveBeenCalled();
    expect(worker.postMessage).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('verifies cache reads, evicts corrupt bytes, and caches only a verified response', async () => {
    const cache = { match: vi.fn().mockResolvedValue(new Response('bad')), delete: vi.fn(), put: vi.fn() };
    vi.stubGlobal('caches', { open: vi.fn().mockResolvedValue(cache) });
    const { broker, onViolation } = fixture(); await broker.initialize(); broker.handleMessage(request()); await settle();
    expect(cache.delete).toHaveBeenCalledOnce(); expect(cache.put).toHaveBeenCalledOnce(); expect(onViolation).not.toHaveBeenCalled();
    expect(await (cache.put.mock.calls[0][1] as Response).text()).toBe('abc');
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('supports offline reads of verified cached public assets', async () => {
    vi.stubGlobal('caches', { open: vi.fn().mockResolvedValue({ match: vi.fn().mockResolvedValue(new Response('abc')) }) });
    fetchMock.mockRejectedValue(new Error('offline'));
    const { broker, worker, onViolation } = fixture(); await broker.initialize(); broker.handleMessage(request()); await settle();
    expect(fetchMock).not.toHaveBeenCalled(); expect(worker.postMessage).toHaveBeenCalledTimes(2); expect(onViolation).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('aborts disposal and never delivers stale network completions', async () => {
    let complete!: (response: Response) => void;
    fetchMock.mockImplementation(() => new Promise<Response>(resolve => { complete = resolve; }));
    const { broker, worker, onViolation } = fixture(); await broker.initialize(); broker.handleMessage(request()); await settle();
    broker.dispose(); complete(new Response('abc')); await settle();
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true); expect(worker.postMessage).toHaveBeenCalledTimes(1); expect(onViolation).not.toHaveBeenCalled();
    broker.handleMessage(request(undefined, { id: 2 })); await settle(); expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('sends genuine licensing requests unchanged in meaning and rejects a response schema change without fabricating success', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ token: 'unsigned-private-value', unexpected: 'field' }), { headers: { 'content-type': 'application/json' } }));
    const { broker, worker, onViolation } = fixture(); await broker.initialize();
    broker.handleMessage(request(`${PII_LICENSE_BASE}license`, { method: 'POST', headers: [['content-type', 'application/json']], body: encode(grant()) })); await settle();
    expect(fetchMock).toHaveBeenCalledWith(`${PII_LICENSE_BASE}license`, expect.objectContaining({ method: 'POST', body: JSON.stringify(grant()), credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer', headers: { 'Content-Type': 'application/json' } }));
    expect(worker.postMessage).toHaveBeenCalledTimes(1); expect(onViolation).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it.each([{ host: hostname, withContext: false }, { host: hostname, withContext: true }, { host: 'localhost', withContext: true }])('preserves authentic grant and activation responses and restores only signed allowlisted SDK state (%j)', async ({ host, withContext }) => {
    vi.stubGlobal('window', { location: { origin: `https://${host}`, hostname: host } });
    const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
    const part = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
    const claims = { v: 1, lid: 'server-issued-license', period: '2026-10', periodEnd: '2026-11-01T00:00:00Z', iat: 1,
      // Pinned SDK Tests/UsageTests/Resources/license_vectors.json carries
      // these signed fields even though its Swift decoder exposes only five.
      ...(withContext ? { app: host === 'localhost' ? 'web:localhost' : 'web:openmates.org', model: 'redact', modelVersion: 'v0.4.0', sdk: 'desert-ant-core', sdkVersion: '4.1.0', platform: 'web' } : {}),
    };
    const input = `${part({ alg: 'ES256', typ: 'dal-license+jwt', kid: 'prod-20261008' })}.${part(claims)}`;
    const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, pair.privateKey, new TextEncoder().encode(input));
    const token = `${input}.${Buffer.from(signature).toString('base64url')}`;
    // A local test issuer substitutes only the public key import. Signature
    // verification is real; the separate forged-token test uses the pinned key.
    const keyImport = vi.spyOn(crypto.subtle, 'importKey').mockResolvedValue(pair.publicKey);
    if (withContext) {
      for (const changed of [{ app: 'web:private-input.example' }, { modelVersion: 'private-input' }, { sdkVersion: 'private-input' }, { platform: 'server' }, { privateInput: 'private-input' }]) {
        const altered = `${part({ alg: 'ES256', typ: 'dal-license+jwt', kid: 'prod-20261008' })}.${part({ ...claims, ...changed })}.${Buffer.from(signature).toString('base64url')}`;
        await expect(verifyLicenseToken(altered, host)).rejects.toThrow(/context|fields/);
      }
    }
    const grantResponse = { token, serverTime: '2026-10-28T00:00:00.000Z',
      // Same complete response shape as the pinned SDK's grantReply fixture;
      // retain the minimal decoder shape as a separate supported case.
      ...(withContext ? { licenseId: claims.lid, period: claims.period, periodEnd: claims.periodEnd } : {}),
    };
    const activationResponse = { activated: true,
      // Complete paired activatedReply fixture, alongside its minimal decoder
      // shape in the case without context or optional response metadata.
      ...(withContext ? { period: claims.period, serverTime: '2026-10-28T00:00:00.000Z' } : {}),
    };
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(grantResponse), { headers: { 'content-type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(activationResponse), { headers: { 'content-type': 'application/json' } }));
    const { broker, worker, onViolation } = fixture(); await broker.initialize();
    broker.handleMessage(request(`${PII_LICENSE_BASE}license`, { method: 'POST', headers: [['content-type', 'application/json']], body: encode({ ...grant(), app: { id: host } }) })); await settle();
    expect(keyImport).toHaveBeenCalledWith('raw', expect.any(Uint8Array), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
    expect(worker.postMessage.mock.calls[1][0].body).toEqual(encode(grantResponse));
    broker.handleMessage(request(`${PII_LICENSE_BASE}activate`, { id: 2, method: 'POST', headers: [['content-type', 'application/json']], body: encode({ license: token }) })); await settle();
    expect(fetchMock.mock.calls[1][1].body).toBe(JSON.stringify({ license: token }));
    expect(worker.postMessage.mock.calls[2][0].body).toEqual(encode(activationResponse));
    const state = { token, licenseId: claims.lid, period: claims.period, activated: true, serverOffset: 0 };
    broker.handleMessage({ kind: 'pii-storage', key: licenseStorageKey(host), value: JSON.stringify(state) });
    broker.dispose();
    const restored = fixture(); await restored.broker.initialize();
    expect(restored.worker.postMessage.mock.calls[0][0].values[licenseStorageKey(host)]).toBe(JSON.stringify(state));
    expect(onViolation).not.toHaveBeenCalled(); expect(restored.onViolation).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it.each([
    { licenseId: 'different-license' }, { period: '2026-11' }, { periodEnd: '2026-12-01T00:00:00Z' },
    { licenseId: 42 }, { periodEnd: undefined }, { unreviewed: 'private-input' },
  ])('rejects mismatched, partial or unreviewed grant metadata even with a genuine signed token (%j)', async changed => {
    const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
    const part = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
    const claims = { v: 1, lid: 'server-license', period: '2026-10', periodEnd: '2026-11-01T00:00:00Z', iat: 1 };
    const input = `${part({ alg: 'ES256', typ: 'dal-license+jwt', kid: 'prod-20261008' })}.${part(claims)}`;
    const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, pair.privateKey, new TextEncoder().encode(input));
    const token = `${input}.${Buffer.from(signature).toString('base64url')}`;
    vi.spyOn(crypto.subtle, 'importKey').mockResolvedValue(pair.publicKey);
    const response = { token, licenseId: claims.lid, period: claims.period, periodEnd: claims.periodEnd,
      serverTime: '2026-10-28T00:00:00.000Z', ...changed };
    fetchMock.mockResolvedValue(new Response(JSON.stringify(response), { headers: { 'content-type': 'application/json' } }));
    const { broker, worker, onViolation } = fixture(); await broker.initialize();
    broker.handleMessage(request(`${PII_LICENSE_BASE}license`, { method: 'POST', headers: [['content-type', 'application/json']], body: encode(grant()) })); await settle();
    expect(onViolation).toHaveBeenCalledWith('license-response');
    expect(worker.postMessage).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(local.has(`openmates.pii.license.state.v1.${hostname}`)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it.each([{ period: '2026-11' }, { period: 202610 }, { licenseId: 'server-license' }, { token: 'private-input' }])('rejects mismatched or grant-only activation response fields (%j)', async changed => {
    const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
    const part = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
    const claims = { v: 1, lid: 'server-license', period: '2026-10', periodEnd: '2026-11-01T00:00:00Z', iat: 1 };
    const input = `${part({ alg: 'ES256', typ: 'dal-license+jwt', kid: 'prod-20261008' })}.${part(claims)}`;
    const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, pair.privateKey, new TextEncoder().encode(input));
    const token = `${input}.${Buffer.from(signature).toString('base64url')}`;
    vi.spyOn(crypto.subtle, 'importKey').mockResolvedValue(pair.publicKey);
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ token, licenseId: claims.lid, period: claims.period,
      periodEnd: claims.periodEnd, serverTime: '2026-10-28T00:00:00.000Z' }), { headers: { 'content-type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ activated: true, period: claims.period,
        serverTime: '2026-10-28T00:00:00.000Z', ...changed }), { headers: { 'content-type': 'application/json' } }));
    const { broker, worker, onViolation } = fixture(); await broker.initialize();
    broker.handleMessage(request(`${PII_LICENSE_BASE}license`, { method: 'POST', headers: [['content-type', 'application/json']], body: encode(grant()) })); await settle();
    expect(onViolation).not.toHaveBeenCalled();
    broker.handleMessage(request(`${PII_LICENSE_BASE}activate`, { id: 2, method: 'POST', headers: [['content-type', 'application/json']], body: encode({ license: token }) })); await settle();
    expect(onViolation).toHaveBeenCalledWith('license-response');
    expect(worker.postMessage).toHaveBeenCalledTimes(2); // initialization + genuine grant only
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(local.has(`openmates.pii.license.state.v1.${hostname}`)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it.each([
    { ...grant(), installId: '12345678-1234-4234-8234-123456789012' },
    { ...grant(), text: 'private content' },
    { ...grant(), key: 'private content' },
    { ...grant(), modelVersion: '0.4.0' },
    { ...grant(), app: { id: 'private content' } },
    { license: 'private input encoded as token' },
  ])('rejects private-content metadata or unobserved activation tokens before transport', async body => {
    const { broker, onViolation } = fixture(); await broker.initialize();
    broker.handleMessage(request(`${PII_LICENSE_BASE}${'license' in body ? 'activate' : 'license'}`, { method: 'POST', headers: [['content-type', 'application/json']], body: encode(body) })); await settle();
    expect(fetchMock).not.toHaveBeenCalled(); expect(onViolation).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('rejects all arbitrary storage keys, extra state fields and install identity changes', async () => {
    for (const [key, value] of [['secret', 'private input'], [PII_DEVICE_KEY, '12345678-1234-4234-8234-123456789012'], [licenseStorageKey(hostname), JSON.stringify({ activated: false, serverOffset: 0, text: 'private input' })]]) {
      const { broker, onViolation } = fixture(); await broker.initialize();
      broker.handleMessage({ kind: 'pii-storage', key, value }); expect(onViolation).toHaveBeenCalledOnce();
    }
    expect([...local.values()]).toEqual([installId]);
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('discards forged restored tokens and regenerates malformed install identities without sending their contents', async () => {
    local.set('openmates.pii.license.installId.v1', 'private input');
    local.set(`openmates.pii.license.state.v1.${hostname}`, JSON.stringify({ token: 'private input', activated: false, serverOffset: 0 }));
    const { broker, worker, onViolation } = fixture(); await broker.initialize();
    const values = worker.postMessage.mock.calls[0][0].values;
    expect(values[PII_DEVICE_KEY]).toMatch(/^[\da-f-]{36}$/); expect(Object.keys(values)).toEqual([PII_DEVICE_KEY]); expect(fetchMock).not.toHaveBeenCalled(); expect(onViolation).not.toHaveBeenCalled();
  });
});

describe('PII bounded license policy', () => {
  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('accepts the exact SDK WASM Uint8Array request and refuses duplicate keys, non-byte and oversized bodies', () => {
    expect(validateLicenseRequest(encode(grant()), 'license', installId, hostname, new Set())).toBe(JSON.stringify(grant()));
    for (const body of [new TextEncoder().encode('{"activated":false,"activated":true}'), new Uint8Array(16_385)]) expect(() => parseLicenseJSON(body)).toThrow();
    expect(() => parseLicenseJSON('secret' as unknown as Uint8Array)).toThrow();
  });
  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('allows only SDK license state linked to an authenticated token', () => {
    const token = 'authenticated-token'; const claims = { v: 1, lid: 'known-license', period: '2026-10', periodEnd: '2026-11-01T00:00:00Z', iat: 1 };
    const state = { token, licenseId: claims.lid, period: claims.period, activated: false, serverOffset: 0 };
    expect(validateStoredLicense(JSON.stringify(state), new Map([[token, claims]]))).toBe(JSON.stringify(state));
    expect(() => validateStoredLicense(JSON.stringify({ ...state, licenseId: 'private-input' }), new Map([[token, claims]]))).toThrow();
    expect(() => validateStoredLicense(JSON.stringify(state), new Map())).toThrow();
  });
  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('cryptographically rejects a well-formed forged ES256 token', async () => {
    const part = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
    const token = `${part({ alg: 'ES256', typ: 'dal-license+jwt', kid: 'prod-20261008' })}.${part({ v: 1, lid: 'known-license', period: '2026-10', periodEnd: '2026-11-01T00:00:00Z', iat: 1 })}.${Buffer.alloc(64).toString('base64url')}`;
    await expect(verifyLicenseToken(token)).rejects.toThrow('signature');
  });
});

describe('worker transport sandbox', () => {
  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('supplies only the pinned SDK Unicode normalization constructors while dynamic evaluation stays disabled', () => {
    const postMessage = vi.fn();
    const sandbox: Record<string, unknown> = { URL, Headers, Response, Uint8Array, Map, Object, Promise,
      location: { hostname, href: `${origin}${PII_ASSET_PATH}worker.js` }, postMessage, addEventListener: vi.fn() };
    sandbox.self = sandbox;
    const context = createContext(sandbox, { codeGeneration: { strings: false, wasm: true } });
    runInContext(readFileSync(new URL('../webPIIDetector.worker.js', import.meta.url), 'utf8'), context);
    const constructor = sandbox.Function as new (...args: string[]) => (s: string) => string;
    const nfkc = new constructor('s', "return s.normalize('NFKC')");
    const nfc = Reflect.construct(constructor, ['s', "return s.normalize('NFC')"]) as (s: string) => string;
    expect(nfkc('Ａｍｉｎａ ﬃ ①')).toBe('Amina ffi 1');
    expect(nfc('Ame\u0301lie')).toBe('Amélie');
    expect(nfc('①')).toBe('①');
    expect(runInContext('(function () {}) instanceof Function', context)).toBe(true);
    expect(Object.getOwnPropertyDescriptor(sandbox, 'Function')?.writable).toBe(false);
    expect(() => new constructor('s', 'return fetch(s)')).toThrow('transport rejected');
    expect(postMessage.mock.calls.at(-2)?.[0]).toEqual({ kind: 'pii-diagnostic', code: 'function-construction' });
    expect(() => new constructor('s', "return s.normalize('NFKC');")).toThrow('transport rejected');
    expect(() => new constructor('private-input', "return s.normalize('NFKC')")).toThrow('transport rejected');
    expect(() => Reflect.construct(constructor, ['s', "return s.normalize('NFC')", 'extra'])).toThrow('transport rejected');
    expect(() => nfkc({ normalize: () => 'private-input' } as unknown as string)).toThrow('transport rejected');
    expect(postMessage.mock.calls.at(-2)?.[0]).toEqual({ kind: 'pii-diagnostic', code: 'normalization-input' });
    expect(JSON.stringify(postMessage.mock.calls)).not.toContain('private-input');
    // Native constructor recovery remains covered by the unchanged eval ban.
    expect(() => runInContext('(function () {}).constructor("return 1")', context)).toThrow(/Code generation from strings disallowed/);
  });

  // contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
  it('retains no native fetch and blocks alternative transports while forwarding WASM bytes through the host', async () => {
    const postMessage = vi.fn(); const nativeFetch = vi.fn();
    const sandbox: Record<string, unknown> = { URL, Headers, Response, Uint8Array, Map, Object, Promise, location: { hostname, href: `${origin}${PII_ASSET_PATH}worker.js` }, postMessage, fetch: nativeFetch, addEventListener: vi.fn() };
    sandbox.self = sandbox;
    const context = createContext(sandbox);
    runInContext(readFileSync(new URL('../webPIIDetector.worker.js', import.meta.url), 'utf8'), context);
    const fetch = sandbox.fetch as typeof globalThis.fetch;
    const body = encode(grant());
    const result = fetch(`${PII_LICENSE_BASE}license`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });
    expect(postMessage.mock.calls[0][0]).toMatchObject({ kind: 'pii-network', method: 'POST', headers: [['content-type', 'application/json']], body });
    const onmessage = sandbox.onmessage as (event: { data: unknown }) => void;
    onmessage({ data: { kind: 'pii-network-result', id: 1, status: 200, headers: [['content-type', 'application/json']], body: encode({ error: 'example' }) } });
    expect((await result).ok).toBe(true); expect(nativeFetch).not.toHaveBeenCalled();
    const failedFetch = fetch(`${PII_LICENSE_BASE}license`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });
    const rejected = expect(failedFetch).rejects.toThrow('Network request failed');
    onmessage({ data: { kind: 'pii-network-error', id: 2 } }); await rejected;
    expect(postMessage.mock.calls.at(-1)?.[0]).toEqual({ kind: 'pii-diagnostic', code: 'license-network-rejected' });
    expect(Object.getOwnPropertyDescriptor(sandbox, 'fetch')?.writable).toBe(false);
    for (const name of ['XMLHttpRequest', 'WebSocket', 'EventSource', 'Worker', 'SharedWorker']) expect(() => (sandbox[name] as () => void)()).toThrow('transport rejected');
    await expect(fetch(`${PII_LICENSE_BASE}license`, { referrer: 'https://private.example' })).rejects.toThrow('transport rejected');
    expect(postMessage.mock.calls.at(-2)?.[0]).toEqual({ kind: 'pii-diagnostic', code: 'fetch-options' });
    expect(() => (sandbox.WebSocket as (url: string) => void)('private-input-must-never-be-reported')).toThrow();
    expect(postMessage.mock.calls.at(-2)?.[0]).toEqual({ kind: 'pii-diagnostic', code: 'transport' });
    const csp = (sandbox.addEventListener as ReturnType<typeof vi.fn>).mock.calls.find(([name]) => name === 'securitypolicyviolation')![1];
    csp({ effectiveDirective: 'private-input-must-never-be-reported', blockedURI: 'https://private.example' });
    expect(postMessage.mock.calls.at(-2)?.[0]).toEqual({ kind: 'pii-diagnostic', code: 'csp-other' });
    expect(JSON.stringify(postMessage.mock.calls)).not.toContain('private-input-must-never-be-reported');
  });
});
