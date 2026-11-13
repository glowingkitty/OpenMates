/**
 * Actual public npm API-key billing and memories calls (gate capabilities sdk.billing,
 * sdk.memories). Without --case it starts the shared Python driver, which serves an
 * independent loopback peer per vector; with --case it reads one vector from stdin,
 * calls the npm SDK source once and prints the language-neutral projection.
 */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../../../', import.meta.url));
const camel = name => name.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
const camelObject = value => Object.fromEntries(Object.entries(value).map(([key, entry]) => [camel(key), entry]));

/** Maps the language-neutral vector (snake_case kwargs, query pairs) onto npm signatures. */
function callArguments(vector) {
  const { operation, args, kwargs } = vector;
  if ('query' in vector) return [{ query: Object.fromEntries(vector.query) }];
  if (operation === 'billing.usage_details') return [{ type: kwargs.type, identifier: kwargs.identifier, yearMonth: kwargs.year_month }];
  if (operation === 'billing.request_refund' || operation === 'memories.delete') return [...args, { confirmed: vector.confirmed === true }];
  return [...args, ...(Object.keys(kwargs).length ? [camelObject(kwargs)] : [])];
}

function project(value) {
  if (value && typeof value === 'object' && typeof value.contentType === 'string' && value.data instanceof ArrayBuffer) {
    return { content_type: value.contentType, filename: value.filename ?? null, data_b64: Buffer.from(value.data).toString('base64') };
  }
  return value;
}

const errorCode = status => ({ 401: 'authentication', 403: 'forbidden', 409: 'conflict' })[status]
  ?? ([400, 404, 410, 422].includes(status) ? 'invalid' : status === 429 || status >= 500 ? 'offline' : 'protocol');

if (!process.argv.includes('--case')) {
  const child = spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON ?? 'python3', ['tests/sdk-conformance/runners/sdk-api-key-wire.py', '--language', 'npm', ...process.argv.slice(2)], { cwd: ROOT, stdio: 'inherit' });
  process.exitCode = await new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', (code, signal) => resolve(signal ? 1 : code ?? 1)); });
} else {
  register(new URL('../../../frontend/packages/openmates-cli/tests/loader.mjs', import.meta.url));
  const { OpenMates, OpenMatesApiError, OpenMatesConfigError } = await import(new URL('../../../frontend/packages/openmates-cli/src/sdk.ts', import.meta.url));
  const raw = readFileSync(0);
  assert.ok(raw.length <= 1024 * 1024);
  const c = JSON.parse(raw);
  const url = new URL(c.endpoint);
  assert.equal(url.protocol, 'http:'); assert.equal(url.hostname, '127.0.0.1'); assert.ok(url.port); assert.equal(url.pathname, '/');
  for (const field of ['search', 'hash', 'username', 'password']) assert.equal(url[field], '');
  assert.equal(c.api_key, 'sk-api-wireOwner.localSetupSuffix'); assert.equal(c.device_id, 'synthetic-wire-device');
  const client = new OpenMates({ apiKey: c.api_key, apiUrl: c.endpoint, deviceId: c.device_id });
  const v = c.vector;
  const [namespace, method] = v.operation.split('.');
  let result;
  try {
    result = { ok: true, value: project(await client[camel(namespace)][camel(method)](...callArguments(v))) };
  } catch (error) {
    if (error instanceof OpenMatesConfigError) result = { ok: false, error: 'invalid' };
    else {
      assert.ok(error instanceof OpenMatesApiError, String(error));
      result = { ok: false, error: errorCode(error.status) };
    }
  }
  console.log(JSON.stringify(result));
}
