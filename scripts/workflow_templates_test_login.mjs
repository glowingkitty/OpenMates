#!/usr/bin/env node
/* Disposable workflow-template proof login only. Never migrates credentials.
 * Password-v2 crypto is shared with web; transport, TOTP and CLI session fields
 * follow openmates_cli_test_account.mjs without changing that shared helper.
 */
import { createHmac, randomUUID, webcrypto } from 'node:crypto';
import { chmodSync, existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs';
import { arch, platform, release } from 'node:os';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createPasswordV2Proof, derivePasswordV2Direct } from '../frontend/packages/ui/src/services/passwordV2Core.ts';

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const API_URL = 'https://api.dev.openmates.org';
const WEB_ORIGIN = 'https://app.dev.openmates.org';
const DEVICE_ID = process.env.OPENMATES_CLI_DEVICE_IDENTITY || `cli:${platform()}:${arch()}`;

class LoginError extends Error {
  constructor(code, status) { super(code); this.code = code; this.status = status; }
}

function loadDotenv() {
  const path = join(REPO_ROOT, '.env');
  if (!existsSync(path)) return;
  for (const raw of readFileSync(path, 'utf8').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const index = line.indexOf('=');
    const key = line.slice(0, index).trim();
    let value = line.slice(index + 1).trim();
    if (value.length >= 2 && ['"', "'"].includes(value[0]) && value.at(-1) === value[0]) value = value.slice(1, -1);
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

export function requireDisposableState(state, apiUrl) {
  if (apiUrl !== API_URL) throw new LoginError('login.test_target_required');
  if (!state || !isAbsolute(state) || !resolve(state).startsWith('/tmp/')) throw new LoginError('login.private_tmp_state_required');
  if (existsSync(state) && (lstatSync(state).isSymbolicLink() || !lstatSync(state).isDirectory())) throw new LoginError('login.unsafe_state_path');
  mkdirSync(state, { recursive: true, mode: 0o700 });
  if (!realpathSync(state).startsWith('/tmp/') || readdirSync(state).length) throw new LoginError('login.fresh_state_required');
  chmodSync(state, 0o700);
  return realpathSync(state);
}

const fromB64 = (value) => new Uint8Array(Buffer.from(value, 'base64'));
const toB64 = (value) => Buffer.from(value).toString('base64');
const sha256 = async (value) => toB64(new Uint8Array(await webcrypto.subtle.digest('SHA-256', value)));

export function generateTotp(secret, windowOffset = 0, now = Date.now()) {
  // Preserve the existing helper's base32 and adjacent-window semantics.
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const character of secret.replace(/\s+/g, '').replace(/=+$/, '').toUpperCase()) {
    const value = alphabet.indexOf(character);
    if (value !== -1) bits += value.toString(2).padStart(5, '0');
  }
  const bytes = [];
  for (let index = 0; index + 8 <= bits.length; index += 8) bytes.push(Number.parseInt(bits.slice(index, index + 8), 2));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(now / 1000 / 30) + windowOffset));
  const hmac = createHmac('sha1', Buffer.from(bytes)).update(counter).digest();
  return String((hmac.readUInt32BE(hmac.at(-1) & 0x0f) & 0x7fffffff) % 1_000_000).padStart(6, '0');
}

function cookiesFrom(headers) {
  const cookies = {};
  const headersList = typeof headers.getSetCookie === 'function' ? headers.getSetCookie() : [];
  const rows = headersList.length ? headersList : (headers.get('set-cookie') || '').split(/,(?=\s*[^;,\s]+=)/g);
  for (const header of rows) {
    const pair = header.split(';')[0], index = pair.indexOf('=');
    if (index > 0) cookies[pair.slice(0, index)] = pair.slice(index + 1);
  }
  return cookies;
}

async function post(path, body) {
  let response;
  try {
    response = await fetch(API_URL + path, {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(30_000),
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', Origin: WEB_ORIGIN,
        'User-Agent': `OpenMates CLI/0.1 (${platform()} ${release()})`, 'X-OpenMates-SDK': 'cli',
        'X-OpenMates-Device-Identity': DEVICE_ID }, body: JSON.stringify(body),
    });
  } catch { throw new LoginError('login.transport_failure'); }
  let data;
  try { data = await response.json(); } catch { throw new LoginError('login.invalid_response', response.status); }
  return { response, data, cookies: cookiesFrom(response.headers) };
}

export async function unwrapV2MasterKey(user, wrapKey, saltB64) {
  if (user.credential_version !== 2) throw new LoginError('login.password_v2_required');
  if (user.salt !== saltB64 || !user.encrypted_key || !user.key_iv) throw new LoginError('login.invalid_password_wrapper');
  const iv = fromB64(user.key_iv);
  if (iv.length !== 12 || wrapKey.length !== 32) throw new LoginError('login.invalid_password_wrapper');
  let decrypted;
  try {
    const key = await webcrypto.subtle.importKey('raw', wrapKey, 'AES-GCM', false, ['decrypt']);
    decrypted = new Uint8Array(await webcrypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, fromB64(user.encrypted_key)));
  } catch { throw new LoginError('login.master_key_unwrap_failed'); }
  try {
    if (decrypted.length !== 32) throw new LoginError('login.invalid_master_key');
    return toB64(decrypted);
  } finally { decrypted.fill(0); }
}

export async function loginWithAccount(account, options, transport = post) {
  const hashedEmail = await sha256(new TextEncoder().encode(account.email));
  const lookup = await transport('/v1/auth/lookup', { hashed_email: hashedEmail, stay_logged_in: true });
  if (!lookup.response.ok || !lookup.data.user_email_salt) throw new LoginError('login.lookup_failed', lookup.response.status);
  const userEmailSalt = lookup.data.user_email_salt, salt = fromB64(userEmailSalt);
  const emailBytes = new TextEncoder().encode(account.email);
  const combined = new Uint8Array(emailBytes.length + salt.length);
  combined.set(emailBytes); combined.set(salt, emailBytes.length);
  const emailEncryptionKeyB64 = await sha256(combined);
  const sessionId = randomUUID();
  const keys = await derivePasswordV2Direct(account.password, salt);
  try {
    let result;
    for (const offset of account.otpKey ? [0, -1, 1] : [null]) {
      // Password challenges are one-use, including attempts rejected by OTP.
      const challenge = await transport('/v1/auth/password-v2/challenge', { purpose: 'login', hashed_email: hashedEmail, session_id: sessionId });
      if (!challenge.response.ok || typeof challenge.data.challenge_id !== 'string') throw new LoginError('login.challenge_failed', challenge.response.status);
      const body = { hashed_email: hashedEmail, session_id: sessionId, stay_logged_in: true,
        email_encryption_key: emailEncryptionKeyB64, login_method: 'password', credential_version: 2,
        challenge_id: challenge.data.challenge_id,
        password_proof: await createPasswordV2Proof(keys.authKey, challenge.data.nonce, 'login') };
      if (offset !== null) Object.assign(body, { tfa_code: generateTotp(account.otpKey, offset), code_type: 'otp' });
      result = await transport('/v1/auth/login', body);
      if (result.response.ok && result.data.success && !result.data.tfa_required) break;
      if (result.response.status === 429 || result.response.status >= 500 || result.data.message !== 'login.code_wrong' || !account.otpKey) break;
    }
    if (!result.response.ok || !result.data.success || result.data.tfa_required) {
      // Explicit legacy fallback is allowed only for authentication rejection,
      // never outages/rate limits, challenge errors or successful typed-v2 login.
      if (options.allowLegacyFallback && result.response.status !== 429 && result.response.status < 500 && !result.data.tfa_required &&
          (result.response.status === 401 || (result.response.ok && result.data.message === 'login.code_wrong'))) {
        const fallback = spawnSync(process.execPath, [join(REPO_ROOT, 'scripts/openmates_cli_test_account.mjs'), 'login', '--slot', String(account.slot), '--api-url', API_URL], { cwd: REPO_ROOT, encoding: 'utf8', timeout: 90_000 });
        if (fallback.status === 0 && existsSync(join(options.state, 'session.json'))) return { success: true, slot: account.slot, credential_version: 1 };
        throw new LoginError('login.legacy_fallback_failed');
      }
      const code = /^login\.[a-z_]+$/.test(result.data.message || '') ? result.data.message : 'login.authentication_failed';
      throw new LoginError(code, result.response.status);
    }
    const masterKeyExportedB64 = await unwrapV2MasterKey(result.data.user || {}, keys.wrapKey, userEmailSalt);
    const session = { apiUrl: API_URL, sessionId, wsToken: result.data.ws_token || null, cookies: result.cookies,
      masterKeyExportedB64, masterKeyStorage: 'plaintext', emailEncryptionKeyB64, emailEncryptionKeyStorage: 'plaintext',
      hashedEmail, userEmailSalt, createdAt: Date.now(), authorizerDeviceName: 'test-account-script', autoLogoutMinutes: null };
    if (!Object.keys(session.cookies).length) throw new LoginError('login.session_cookie_missing');
    const path = join(options.state, 'session.json');
    writeFileSync(path, JSON.stringify(session, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
    chmodSync(path, 0o600);
    return { success: true, slot: account.slot, credential_version: 2 };
  } finally { keys.authKey.fill(0); keys.wrapKey.fill(0); }
}

async function main() {
  loadDotenv();
  const argv = process.argv.slice(2);
  if (argv.shift() !== 'login') throw new LoginError('login.test_login_command_required');
  const options = { apiUrl: API_URL, allowLegacyFallback: false };
  for (let index = 0; index < argv.length; index++) {
    if (argv[index] === '--slot') options.slot = Number(argv[++index]);
    else if (argv[index] === '--api-url') options.apiUrl = argv[++index];
    else if (argv[index] === '--allow-legacy-fallback') options.allowLegacyFallback = true;
    else throw new LoginError('login.unsupported_argument');
  }
  if (!Number.isInteger(options.slot) || options.slot < 1 || options.slot > 20) throw new LoginError('login.explicit_test_slot_required');
  options.state = requireDisposableState(process.env.OPENMATES_STATE_DIR, options.apiUrl);
  const prefix = `OPENMATES_TEST_ACCOUNT_${options.slot}_`;
  const account = { slot: options.slot, email: process.env[prefix + 'EMAIL'], password: process.env[prefix + 'PASSWORD'], otpKey: process.env[prefix + 'OTP_KEY'] };
  if (!account.email || !account.password) throw new LoginError('login.test_slot_not_configured');
  process.stdout.write(JSON.stringify(await loginWithAccount(account, options)) + '\n');
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    const code = error instanceof LoginError ? error.code : 'login.protocol_failure';
    process.stderr.write(JSON.stringify({ success: false, code, ...(error instanceof LoginError && Number.isInteger(error.status) ? { http_status: error.status } : {}) }) + '\n');
    process.exitCode = 1;
  });
}
