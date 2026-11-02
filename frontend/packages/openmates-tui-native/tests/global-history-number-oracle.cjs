// Inert actual-source baseline oracle: no imports of the client, credentials or IO.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const { stripTypeScriptTypes } = require('node:module');
const crypto = require('node:crypto');
if (process.version !== 'v24.20.0') throw new Error('Generate this baseline with the pinned installed Node v24.20.0.');
const root = path.resolve(__dirname, '../../../..');
const cliPath = path.join(root, 'frontend/packages/openmates-cli/src/cli.ts');
const clientPath = path.join(root, 'frontend/packages/openmates-cli/src/client.ts');
const cli = fs.readFileSync(cliPath, 'utf8'), client = fs.readFileSync(clientPath, 'utf8');
const parser = cli.slice(cli.indexOf('function parseArgs('), cli.indexOf('function resolveApiKey('));
const handler = cli.slice(cli.indexOf('async function handleHistory('), cli.indexOf('// Teams', cli.indexOf('async function handleHistory(')));
const method = client.slice(client.indexOf('  async listWorkspaceHistory('), client.indexOf('  async listObjectHistory('));
const catchStart = cli.indexOf('main().catch((error) => {');
const catchSource = cli.slice(catchStart, cli.indexOf('  });', catchStart) + 5);
const sandbox = { URLSearchParams, output: [], printJson() {}, console: { log() {} } };
vm.createContext(sandbox);
vm.runInContext(stripTypeScriptTypes(parser + '\n' + handler + '\nclass OracleClient { requireSession() {} getCliRequestHeaders() { return {}; }\n' + method + '\n}'), sandbox);
const raw = ['', ' ', '\uFEFF', '\u0085', '\u00a0 1 \u2029', '0', '-0', '+0', 'NaN', 'nan', 'Infinity', '+Infinity', '-Infinity', 'infinity', 'inf', '+inf', '-inf', '1.5', '-3.5', '1e21', '1e20', '1e-6', '1e-7', '1000000000000000100', '9007199254740993', '9223372036854775808', '1e309', '-1e309', '1e-400', '5e-324', '2.2250738585072014e-308', '1.7976931348623157e308', '0x10', '0XFFFFFFFFFFFFFFFFFFFF', '0x' + 'f'.repeat(300), '0b' + '1'.repeat(100), '0o777777777777777777777777777777', '+0x10', '-0x10', '0x', '0b2', '0o8', '00', '.5', '1.', '1.e2', '1e', '1_000', '1\n2', '\u200b1', '1=2'];
// Seeded bit patterns exercise shortest decimal thresholds/ties, not just ints.
let bits = 0x29ab47c78165ef23n;
const buffer = new ArrayBuffer(8), view = new DataView(buffer);
for (let i = 0; i < 384; i++) {
  bits = BigInt.asUintN(64, bits * 6364136223846793005n + 1442695040888963407n);
  view.setBigUint64(0, bits); const number = view.getFloat64(0);
  if (Number.isFinite(number)) raw.push(String(number));
}
const invocations = [[], ...raw.map(value => ['--limit=' + value]), ['--limit'], ['--type'], ['--id'],
  ['--limit=5', '--limit'], ['--limit', '--limit=2'], ['--type=task=ignored', '--id=a=b'],
  ['--type=task', '--type', '--type=plan'],
  ['--limit=1', '--limit=2'], ['--limit=', '--limit=2'], ['--limit=1', '--limit='],
  ['--type=task', '--type=plan', '--id=a', '--id=b'],
  ['--type=', '--type=project', '--id=', '--id=owned'],
];
(async () => {
  const cases = [];
  for (const flags of invocations) {
    const argv = ['history', 'list', ...flags];
    sandbox.argv = argv;
    const result = await vm.runInContext(`(async()=>{const parsed=parseArgs(argv); const c=new OracleClient(); let path; c.http={get:async p=>{path=p;return {ok:true,data:{change_sets:[]}}}}; await handleHistory(c,parsed.positionals[1],parsed.positionals.slice(2),parsed.flags); return {flags:parsed.flags,path};})()`, sandbox);
    const value = typeof result.flags.limit === 'string' ? Number(result.flags.limit) : NaN;
    view.setFloat64(0, value);
    cases.push({ argv, flags: result.flags, number_bits: view.getBigUint64(0).toString(16).padStart(16, '0'), number_string: String(value), limit_query: value ? String(value) : null, path: result.path });
  }
  const error_cases = [];
  for (const [action, status] of [['list', 422], ['show', 404], ['undo', 409]]) {
    for (const json of [false, true]) {
      const writes = [];
      sandbox.process = { argv: json ? ['openmates', 'history', '--json'] : ['openmates', 'history'], stderr: { write(value) { writes.push(String(value)); } }, exit(code) { sandbox.exitCode = code; } };
      sandbox.console.error = value => writes.push(String(value) + '\n');
      sandbox.action = action; sandbox.httpStatus = status;
      await vm.runInContext(`(async()=>{ const c=new OracleClient(); c.http={get:async()=>({ok:false,status:httpStatus,data:{detail:'PRIVATE_BODY_MUST_NOT_ESCAPE'}}),post:async()=>({ok:false,status:httpStatus,data:{detail:'PRIVATE_BODY_MUST_NOT_ESCAPE'}})}; globalThis.main=async()=>{if(action==='list')await c.listWorkspaceHistory();if(action==='show')await c.getWorkspaceHistory('chg_fixture');if(action==='undo')await c.undoWorkspaceHistory('chg_fixture');}; })()`, sandbox);
      vm.runInContext('globalThis.CliContractError=class extends Error {}; globalThis.ProjectRequesterError=class extends Error {};', sandbox);
      await vm.runInContext(stripTypeScriptTypes(catchSource), sandbox);
      error_cases.push({action,status,json,stdout:'',stderr:writes.join(''),exit_code:sandbox.exitCode});
    }
  }
  const output = { error_cases, oracle: { node: process.version, cli_source_sha256: crypto.createHash('sha256').update(cli).digest('hex'), client_source_sha256: crypto.createHash('sha256').update(client).digest('hex'), execution: 'Actual baseline parser, handler and SDK list method extracted; stubbed session and HTTP only. No product runtime or network.' }, cases };
  const target = path.join(__dirname, 'fixtures/global-history-number-oracle.json');
  fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, JSON.stringify(output, null, 2) + '\n');
  console.log(JSON.stringify({ node: process.version, cases: cases.length, error_cases: error_cases.length, target: path.relative(__dirname, target), source: output.oracle }));
})();
