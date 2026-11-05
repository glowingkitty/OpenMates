/** Reviewed wire contract for @desert-ant-labs/redact 4.1.0. No prompt data belongs here. */
export const PII_ASSET_PATH = '/pii-runtime/redact-4.1.0-litert-2.6.0/';
export const PII_LICENSE_BASE = 'https://events.desertant.com/api/v1/';
export const PII_DEVICE_KEY = 'ai.desertant.usage.deviceId';
export const PII_MAX_LICENSE_BYTES = 16_384;
export const PII_HOSTS = new Set(['openmates.org', 'app.openmates.org', 'app.dev.openmates.org', 'localhost', '127.0.0.1']);
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });

export function requireRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('PII boundary object rejected');
  return value as Record<string, unknown>;
}

export function exactKeys(value: Record<string, unknown>, required: string[], optional: string[] = []): void {
  if (required.some(key => !Object.hasOwn(value, key)) || Object.keys(value).some(key => !required.includes(key) && !optional.includes(key))) {
    throw new Error('PII boundary fields rejected');
  }
}

export function parseLicenseJSON(bytes: Uint8Array): Record<string, unknown> {
  if (!(bytes instanceof Uint8Array) || !bytes.byteLength || bytes.byteLength > PII_MAX_LICENSE_BYTES) throw new Error('PII boundary body rejected');
  const text = decoder.decode(bytes);
  const parsed = requireRecord(JSON.parse(text));
  // A canonical comparison also rejects duplicate JSON keys rather than
  // silently stripping them while authorizing an apparently valid object.
  let compact = ''; let quoted = false; let escaped = false;
  for (const char of text) {
    if (quoted || !/\s/.test(char)) compact += char;
    if (escaped) escaped = false;
    else if (quoted && char === '\\') escaped = true;
    else if (char === '"') quoted = !quoted;
  }
  if (compact !== JSON.stringify(parsed)) throw new Error('PII boundary JSON encoding rejected');
  return parsed;
}

export function licenseStorageKey(hostname: string): string { return `ai.desertant.license.${hostname}.redact`; }
export function isInstallId(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

export function validateLicenseRequest(bytes: Uint8Array, path: string, installId: string, hostname: string, authorizedTokens: ReadonlySet<string>): string {
  const body = parseLicenseJSON(bytes);
  if (path === 'license') {
    exactKeys(body, ['installId', 'model', 'modelVersion', 'sdk', 'platform', 'app']);
    const sdk = requireRecord(body.sdk); const app = requireRecord(body.app);
    exactKeys(sdk, ['name', 'version']); exactKeys(app, ['id']);
    if (body.installId !== installId || body.model !== 'redact' || body.modelVersion !== 'v0.4.0' ||
      body.platform !== 'web' || sdk.name !== 'desert-ant-core' || sdk.version !== '4.1.0' || app.id !== hostname) {
      throw new Error('PII license identity rejected');
    }
    // Host-owned serialization prevents whitespace, key order and escape
    // spelling from becoming a user-controlled outbound payload.
    return JSON.stringify({ installId, model: 'redact', modelVersion: 'v0.4.0', sdk: { name: 'desert-ant-core', version: '4.1.0' }, platform: 'web', app: { id: hostname } });
  }
  if (path !== 'activate') throw new Error('PII license endpoint rejected');
  exactKeys(body, ['license']);
  if (typeof body.license !== 'string' || !authorizedTokens.has(body.license)) throw new Error('PII activation token rejected');
  return JSON.stringify({ license: body.license });
}

export interface LicenseClaims { v: number; lid: string; period: string; periodEnd: string; iat: number }
const LICENSE_PUBLIC_KEY = 'BHkp0y3mP25qGm6pUkD52BxFH9NB2/px8QMf/fPemZH45msFUHbn+pVE0hgJ2QRmuou1QEFQru3zbUTQY2udOp8=';
function base64Bytes(value: string): Uint8Array<ArrayBuffer> {
  if (!/^[A-Za-z0-9+/_-]+={0,2}$/.test(value)) throw new Error('PII license encoding rejected');
  return Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), char => char.charCodeAt(0));
}

/** Pinned SDK source Sources/Usage/LicenseToken.swift, prod-20261008 ES256 key. */
export async function verifyLicenseToken(token: string, hostname?: string): Promise<LicenseClaims> {
  if (token.length > 8192) throw new Error('PII license token rejected');
  if (hostname !== undefined && !PII_HOSTS.has(hostname)) throw new Error('PII license host rejected');
  const parts = token.split('.');
  if (parts.length !== 3) throw new Error('PII license token rejected');
  const header = requireRecord(JSON.parse(decoder.decode(base64Bytes(parts[0]))));
  exactKeys(header, ['alg', 'typ', 'kid']);
  const claims = requireRecord(JSON.parse(decoder.decode(base64Bytes(parts[1]))));
  // The Swift decoder exposes only these five claims, but the same pinned
  // release's valid license_vectors.json also contains six signed context
  // claims. Validate their documented values instead of rejecting real grants
  // or accepting arbitrary additional signed fields.
  const contextKeys = ['app', 'model', 'modelVersion', 'sdk', 'sdkVersion', 'platform'];
  exactKeys(claims, ['v', 'lid', 'period', 'periodEnd', 'iat'], contextKeys);
  if (contextKeys.some(key => Object.hasOwn(claims, key))) {
    const app = hostname ? `web:${['localhost', '127.0.0.1'].includes(hostname) ? hostname : 'openmates.org'}` : undefined;
    if (contextKeys.some(key => !Object.hasOwn(claims, key)) ||
      (app ? claims.app !== app : !['web:openmates.org', 'web:localhost', 'web:127.0.0.1'].includes(String(claims.app))) ||
      claims.model !== 'redact' || claims.modelVersion !== 'v0.4.0' || claims.sdk !== 'desert-ant-core' ||
      claims.sdkVersion !== '4.1.0' || claims.platform !== 'web') throw new Error('PII license context rejected');
  }
  const signature = base64Bytes(parts[2]);
  if (header.alg !== 'ES256' || header.typ !== 'dal-license+jwt' || header.kid !== 'prod-20261008' || signature.length !== 64 ||
    claims.v !== 1 || typeof claims.lid !== 'string' || !/^[\w-]{1,128}$/.test(claims.lid) ||
    typeof claims.period !== 'string' || !/^\d{4}-\d{2}$/.test(claims.period) ||
    typeof claims.periodEnd !== 'string' || !/^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/.test(claims.periodEnd) || !Number.isFinite(Date.parse(claims.periodEnd)) ||
    !Number.isSafeInteger(claims.iat) || (claims.iat as number) < 0) throw new Error('PII license claims rejected');
  const key = await crypto.subtle.importKey('raw', base64Bytes(LICENSE_PUBLIC_KEY), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
  if (!await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, key, signature, encoder.encode(`${parts[0]}.${parts[1]}`))) {
    throw new Error('PII license signature rejected');
  }
  return claims as unknown as LicenseClaims;
}

export function validateStoredLicense(value: string, tokens: ReadonlyMap<string, LicenseClaims>): string {
  const state = parseLicenseJSON(encoder.encode(value));
  exactKeys(state, ['activated', 'serverOffset'], ['token', 'licenseId', 'period', 'lastFailedGrantAt']);
  if (typeof state.activated !== 'boolean' || !Number.isSafeInteger(state.serverOffset) || Math.abs(state.serverOffset as number) > 7 * 86400_000 ||
    (state.lastFailedGrantAt !== undefined && (!Number.isSafeInteger(state.lastFailedGrantAt) || Math.abs(Date.now() - (state.lastFailedGrantAt as number)) > 86400_000))) {
    throw new Error('PII license state rejected');
  }
  if (state.token === undefined) {
    if (state.licenseId !== undefined || state.period !== undefined || state.activated) throw new Error('PII empty license state rejected');
  } else {
    const claims = typeof state.token === 'string' ? tokens.get(state.token) : undefined;
    if (!claims || state.licenseId !== claims.lid || state.period !== claims.period) throw new Error('PII stored license rejected');
  }
  return JSON.stringify(state);
}
