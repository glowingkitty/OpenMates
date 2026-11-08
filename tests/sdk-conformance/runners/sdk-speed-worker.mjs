// npm arm of the cross-SDK speed check (tests/sdk-conformance/benchmark_sdk_speed.py).
// The API-key OpenMates drafts/history/wikipedia paths of the published npm SDK are
// the maintained TypeScript implementation (frontend/packages/openmates-cli/src/sdk.ts),
// so this arm is also the TypeScript reference baseline for those operations.
// Protocol: line 1 {api_url, api_key, device_id}; then {op, args, iterations} per line;
// one JSON answer per request with a plaintext-free digest of the last result.
import {createHash} from 'node:crypto';
import {createInterface} from 'node:readline';

const entry = process.env.OPENMATES_SDK_SPEED_NPM_ENTRY
  ?? new URL('../../../frontend/packages/openmates-cli/dist/sdk-entry.js', import.meta.url).href;
const {OpenMates, OpenMatesApiError, OpenMatesConfigError} = await import(entry);

const sha = (value) => createHash('sha256').update(String(value), 'utf8').digest('hex');

function code(error) {
  if (error instanceof OpenMatesConfigError) return 'crypto';
  if (!(error instanceof OpenMatesApiError)) return 'protocol';
  const status = error.status;
  return ({401: 'authentication', 403: 'forbidden', 409: 'conflict'})[status]
    ?? ([400, 404, 410, 422].includes(status) ? 'invalid' : status === 429 || status >= 500 ? 'offline' : 'protocol');
}

async function invoke(client, op, args) {
  if (op === 'drafts.list') {
    const rows = (await client.drafts.list()).map((d) => [d.chatId, sha(d.markdown)]);
    rows.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
    return {count: rows.length, rows};
  }
  if (op === 'drafts.get') {
    const draft = await client.drafts.get(args.chat_id);
    return draft ? {found: true, markdown: sha(draft.markdown)} : {found: false};
  }
  if (op === 'history.list') return {count: (await client.history.list({limit: args.limit})).length};
  if (op === 'wikipedia.search') {
    const value = await client.wikipedia.search(args.query, {language: args.language, limit: args.limit});
    return {count: Array.isArray(value.results) ? value.results.length : 0};
  }
  if (op === 'wikipedia.summary') return {title: (await client.wikipedia.summary(args.title, {language: args.language})).title ?? null};
  throw new Error(`unknown benchmark operation ${op}`);
}

const lines = createInterface({input: process.stdin, crlfDelay: Infinity})[Symbol.asyncIterator]();
const init = JSON.parse((await lines.next()).value);
const client = new OpenMates({apiKey: init.api_key, apiUrl: init.api_url, deviceId: init.device_id});
process.stdout.write(JSON.stringify({ready: true}) + '\n');
for (;;) {
  const next = await lines.next();
  if (next.done) break;
  const request = JSON.parse(next.value);
  if (!Number.isInteger(request.iterations) || request.iterations < 1 || request.iterations > 1000) throw new Error('iterations');
  let answer = {ok: true};
  for (let i = 0; i < request.iterations; i++) {
    try { answer = {ok: true, digest: await invoke(client, request.op, request.args ?? {})}; }
    catch (error) { answer = {ok: false, error: code(error), status: error?.status ?? null, detail: error?.name ?? typeof error}; break; }
  }
  process.stdout.write(JSON.stringify(answer) + '\n');
}
