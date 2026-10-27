// contract-test-file: tooling. Synthetic files/processes only; no product calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { attestSource, sourcePolicy, supplierPath, copySource, parentCurrent, identity, same, sourceDiagnostic, startupFailureEnvelope } from '../ci_stage_node_runtime.mjs';
const script = fileURLToPath(new URL('../ci_stage_node_runtime.mjs', import.meta.url));
function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'node-producer-unit-'));
  const execPath = path.join(root, 'node', process.version.slice(1), process.arch, 'bin', 'node');
  fs.mkdirSync(path.dirname(execPath), { recursive: true });
  fs.writeFileSync(execPath, Buffer.from([0x7f, 0x45, 0x4c, 0x46, 1, 2, 3, 4]), { mode: 0o775 });
  // Exercise the attested supplier exception independently of the test runner umask.
  fs.chmodSync(execPath, 0o775);
  const procPath = path.join(root, 'proc-exe'); fs.symlinkSync(execPath, procPath);
  return { root, execPath, cache: root, procPath, version: process.version, arch: process.arch };
}
function remove(f) { fs.rmSync(f.root, { recursive: true, force: true }); }
function openDir(name) { return fs.openSync(name, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW); }
function run(node, mode, env) {
  return spawnSync(node, [script, mode], { env: { ...process.env, NODE_OPTIONS: '', NODE_PATH: '', ...env }, encoding: 'utf8', timeout: 10000, maxBuffer: 128 * 1024 });
}
test('only exact canonical Node24 toolcache layout/version is admitted', () => {
  const f = fixture(); try {
    assert.equal(supplierPath(f.execPath, f.cache, f.version, f.arch), f.execPath);
    assert.throws(() => supplierPath(f.execPath, f.cache, 'v22.1.0', f.arch), /source_version/);
    assert.throws(() => supplierPath(f.execPath, f.cache, f.version, 'unknown'), /source_arch/);
    const alias = path.join(f.root, 'alias'); fs.symlinkSync(f.execPath, alias);
    assert.throws(() => supplierPath(alias, f.cache, f.version, f.arch), /supplier_path/);
    fs.renameSync(f.execPath, f.execPath + '-real'); fs.symlinkSync(f.execPath + '-real', f.execPath);
    assert.throws(() => supplierPath(f.execPath, f.cache, f.version, f.arch), /supplier_path/);
  } finally { remove(f); }
});
test('proc descriptor must be same inode as supplier; exception never admits world write/hardlinks', () => {
  const f = fixture(); try {
    assert.throws(() => attestSource({ ...f, procPath: '/proc/self/exe' }), /proc_identity/);
    const source = attestSource(f); assert.equal(fs.statSync(f.execPath).mode & 0o777, 0o775); fs.closeSync(source.fd);
    fs.writeFileSync(f.execPath, 'not an ELF'); assert.throws(() => attestSource(f), /source_elf/);
    fs.writeFileSync(f.execPath, Buffer.from([0x7f, 0x45, 0x4c, 0x46]));
    fs.chmodSync(f.execPath, 0o777); assert.throws(() => attestSource(f), /source_mode/);
    fs.chmodSync(f.execPath, 0o775); fs.linkSync(f.execPath, path.join(f.root, 'hardlink'));
    assert.throws(() => attestSource(f), /source_regular_single_link/);
    const fake = { ...fs.statSync(f.execPath, { bigint: true }), isFile: () => true, nlink: 1n, uid: BigInt(process.geteuid()) + 1000n };
    assert.throws(() => sourcePolicy(fake, process.geteuid()), /source_owner/);
  } finally { remove(f); }
});
test('descriptor anchored copy has fresh private inode, excludes atime, and rejects changed source', () => {
  const f = fixture(); let source, dir;
  try {
    source = attestSource(f); const out = path.join(f.root, 'out'); fs.mkdirSync(out, { mode: 0o700 }); dir = openDir(out);
    const result = copySource(source, dir); const copied = fs.statSync(path.join(out, 'node'), { bigint: true });
    assert(same(result, copied)); assert.notEqual(result.ino, String(source.before.ino));
    assert.equal(copied.mode & 0o777n, 0o700n);
    assert(same(source.before, { ...source.before, atimeNs: source.before.atimeNs + 1n }));
    fs.unlinkSync(path.join(out, 'node')); fs.writeFileSync(f.execPath, Buffer.from([0x7f, 0x45, 0x4c, 0x46, 4, 3, 2, 1]));
    assert.throws(() => copySource(source, dir), /source_mutation/);
  } finally { if (source) fs.closeSync(source.fd); if (dir !== undefined) fs.closeSync(dir); remove(f); }
});
test('short write followed by zero refuses immediately, closes output, and leaves source unchanged', () => {
  const f = fixture(); let source, dir, outputFd; const originalWrite = fs.writeSync;
  try {
    source = attestSource(f); const before = fs.readFileSync(f.execPath);
    const out = path.join(f.root, 'out'); fs.mkdirSync(out, { mode: 0o700 }); dir = openDir(out);
    let calls = 0;
    fs.writeSync = (fd, bytes, offset, length) => {
      outputFd = fd; calls += 1;
      if (calls === 1) return originalWrite(fd, bytes, offset, Math.min(2, length));
      if (calls === 2) return 0;
      throw new Error('unexpected_write_after_zero');
    };
    assert.throws(() => copySource(source, dir), /destination_write/);
    assert.equal(calls, 2, 'zero must refuse before another synchronous iteration');
    fs.writeSync = originalWrite;
    assert.throws(() => fs.fstatSync(outputFd), { code: 'EBADF' });
    assert(same(source.before, fs.statSync(f.execPath, { bigint: true })));
    assert.deepEqual(fs.readFileSync(f.execPath), before);
    // Failed copy remains in the caller-owned directory; remove only the known
    // partial inode after checking its identity, without following any symlink.
    const partial = path.join(out, 'node'), owned = fs.lstatSync(partial, { bigint: true });
    assert(owned.isFile() && owned.nlink === 1n && owned.uid === BigInt(process.geteuid()));
    assert.equal(owned.size, 2n);
    assert(same(owned, fs.lstatSync(`/proc/self/fd/${dir}/node`, { bigint: true })));
    fs.unlinkSync(`/proc/self/fd/${dir}/node`);
    assert.deepEqual(fs.readdirSync(out), []);
    fs.closeSync(dir); dir = undefined; fs.rmdirSync(out);
  } finally {
    fs.writeSync = originalWrite;
    if (source) fs.closeSync(source.fd); if (dir !== undefined) fs.closeSync(dir);
    remove(f);
  }
});
test('parent directory replacement is refused while descriptor stays anchored', () => {
  const f = fixture(); let fd; try {
    const parent = path.join(f.root, 'parent'); fs.mkdirSync(parent); fd = openDir(parent);
    const before = fs.fstatSync(fd, { bigint: true }); parentCurrent({ fd, before }, parent);
    fs.renameSync(parent, parent + '-old'); fs.mkdirSync(parent);
    assert.throws(() => parentCurrent({ fd, before }, parent), /parent_swap/);
    assert.equal(identity(fs.fstatSync(fd, { bigint: true })).ino, String(before.ino));
  } finally { if (fd !== undefined) fs.closeSync(fd); remove(f); }
});
for (const supplierMode of [0o755, 0o775]) test(`real attested supplier mode ${supplierMode.toString(8)} stages unchanged bytes; pinned child and grandchild execPath match; safe cleanup`, { timeout: 30000 }, () => {
  const f = fixture(); let staged;
  try {
    fs.copyFileSync(process.execPath, f.execPath); fs.chmodSync(f.execPath, supplierMode);
    const original = fs.statSync(f.execPath, { bigint: true });
    const githubEnv = path.join(f.root, 'github-env'), githubPath = path.join(f.root, 'github-path');
    const result = run(f.execPath, 'stage', { RUNNER_TOOL_CACHE: f.root, GITHUB_ENV: githubEnv, GITHUB_PATH: githubPath });
    assert.equal(result.status, 0, result.stderr); const receipt = JSON.parse(result.stdout);
    assert.equal(receipt.source.group_write_supplier_exception, (supplierMode & 0o020) !== 0); assert.equal(receipt.destination.mode_0700, true);
    assert(!result.stdout.includes(f.root)); assert(!Object.hasOwn(receipt, 'uid')); assert(!Object.hasOwn(receipt, 'path'));
    const env = Object.fromEntries(fs.readFileSync(githubEnv, 'utf8').trim().split('\n').map(line => line.split('=')));
    staged = path.dirname(env.OPENMATES_CI_NODE); const verified = run(env.OPENMATES_CI_NODE, 'verify', env);
    assert.equal(verified.status, 0, verified.stderr); assert.equal(JSON.parse(verified.stdout).sha256, receipt.sha256);
    assert.equal(fs.statSync(env.OPENMATES_CI_NODE).mode & 0o777, 0o700);
    const child = spawnSync(env.OPENMATES_CI_NODE, ['-e', `const c=require('node:child_process').spawnSync(process.execPath,['-p','process.execPath'],{encoding:'utf8',timeout:2000});if(c.status!==0)process.exit(1);console.log(JSON.stringify([process.execPath,c.stdout.trim()]))`], { encoding: 'utf8', timeout: 5000 });
    assert.equal(child.status, 0, child.stderr); assert.deepEqual(JSON.parse(child.stdout), [env.OPENMATES_CI_NODE, env.OPENMATES_CI_NODE]);
    assert(same(original, fs.statSync(f.execPath, { bigint: true })), 'raw supplier mode and identity stay untouched');
    const cleanup = run(env.OPENMATES_CI_NODE, 'cleanup', env); assert.equal(cleanup.status, 0, cleanup.stderr);
    assert(!fs.existsSync(staged)); staged = undefined;
  } finally { if (staged) fs.rmSync(staged, { recursive: true, force: true }); remove(f); }
});
test('cleanup refuses modified binary and directory swap, retaining uncertain files', { timeout: 30000 }, () => {
  const f = fixture(); const owned = [];
  try {
    fs.copyFileSync(process.execPath, f.execPath); fs.chmodSync(f.execPath, 0o775);
    for (const attack of ['binary', 'directory', 'unknown']) {
      const envFile = path.join(f.root, 'env-' + attack), pathFile = path.join(f.root, 'path-' + attack);
      const start = run(f.execPath, 'stage', { RUNNER_TOOL_CACHE: f.root, GITHUB_ENV: envFile, GITHUB_PATH: pathFile });
      assert.equal(start.status, 0, start.stderr);
      const env = Object.fromEntries(fs.readFileSync(envFile, 'utf8').trim().split('\n').map(line => line.split('=')));
      const directory = path.dirname(env.OPENMATES_CI_NODE); owned.push(directory);
      if (attack === 'binary') fs.chmodSync(env.OPENMATES_CI_NODE, 0o750);
      else if (attack === 'unknown') fs.writeFileSync(path.join(directory, 'unrelated'), 'retain');
      else { fs.renameSync(directory, directory + '-old'); owned.push(directory + '-old'); fs.mkdirSync(directory, { mode: 0o700 }); fs.writeFileSync(path.join(directory, 'unrelated'), 'retain'); }
      const result = run(f.execPath, 'cleanup', env); assert.notEqual(result.status, 0);
      assert.equal(JSON.parse(result.stderr).uncertain_stage_retained, true);
      assert(fs.existsSync(directory)); if (attack !== 'binary') assert.equal(fs.readFileSync(path.join(directory, 'unrelated'), 'utf8'), 'retain');
    }
  } finally { for (const directory of owned) fs.rmSync(directory, { recursive: true, force: true }); remove(f); }
});

test('strict mode predicate distinguishes every special bit, world write and missing execute without private identity', () => {
  const f = fixture();
  try {
    const before = fs.statSync(f.execPath, { bigint: true });
    for (const [mode, flag, expected] of [[0o4775n, 'setuid', 'special_bits'], [0o2775n, 'setgid', 'special_bits'],
      [0o1775n, 'sticky', 'special_bits'], [0o777n, 'world_write', 'world_write'], [0o660n, 'execute_bit', 'no_execute']]) {
      const fake = { ...before, mode: (before.mode & ~0o7777n) | mode, isFile: () => true, isDirectory: () => false };
      assert.throws(() => sourcePolicy(fake, process.geteuid()), /source_mode/);
      const diagnostic = sourceDiagnostic(fake, { procIdentity: true, stable: true });
      assert.deepEqual(diagnostic.mode_rejections, [expected]);
      assert.equal(diagnostic[flag], flag !== 'execute_bit');
      assert.equal(diagnostic.permission_octal, '0' + mode.toString(8).padStart(4, '0'));
      assert.equal(diagnostic.file_type, 'regular'); assert.equal(diagnostic.link_count, 1);
      assert(['root', 'current', 'other'].includes(diagnostic.owner_relation));
      assert(['root', 'current', 'other'].includes(diagnostic.group_relation));
      const text = JSON.stringify(diagnostic);
      assert(!text.includes(f.root));
      for (const forbidden of ['uid', 'gid', 'ino', 'dev', 'execPath', 'environment']) assert(!Object.hasOwn(diagnostic, forbidden));
    }
  } finally { remove(f); }
});
test('source mode refusal exports before any candidate; export failure never replaces primary admission error', { timeout: 30000 }, () => {
  const f = fixture();
  try {
    fs.copyFileSync(process.execPath, f.execPath); fs.chmodSync(f.execPath, 0o777);
    const before = fs.statSync(f.execPath, { bigint: true });
    const tooling = path.join(f.root, 'tooling'), scripts = path.join(tooling, 'scripts');
    fs.mkdirSync(scripts, { recursive: true }); const isolatedScript = path.join(scripts, 'ci_stage_node_runtime.mjs');
    fs.copyFileSync(script, isolatedScript);
    const env = { ...process.env, RUNNER_TOOL_CACHE: f.root, NODE_OPTIONS: '', NODE_PATH: '',
      GITHUB_WORKSPACE: path.join(f.root, 'absent-candidate'), OPENMATES_CI_EXPECTED_SOURCE: 'a'.repeat(40),
      CI_HARNESS_COMMIT: 'b'.repeat(40), GITHUB_RUN_ID: '7', CI_TEST_MODE: 'e2e', PLAYWRIGHT_PROOF_VIDEO_PROFILE: 'web-laptop' };
    const invoke = () => spawnSync(f.execPath, [isolatedScript, 'stage'], { env, encoding: 'utf8', timeout: 10000, maxBuffer: 128 * 1024 });
    const result = invoke(); assert.equal(result.status, 1);
    const receipt = JSON.parse(result.stderr); assert.equal(receipt.predicate, 'source_mode');
    assert.equal(receipt.diagnostic_export, 'written');
    assert.deepEqual(receipt.source_diagnostic.mode_rejections, ['world_write']);
    assert.equal(receipt.source_diagnostic.permission_octal, '00777');
    assert.equal(receipt.source_diagnostic.path_attestation.proc_same_inode_and_canonical_path, true);
    assert.equal(receipt.source_diagnostic.path_attestation.stable_stat, true);
    assert(!result.stderr.includes(f.root)); assert(!fs.existsSync(env.GITHUB_WORKSPACE));
    const directory = path.join(tooling, 'node-runtime-diagnostics'); const names = fs.readdirSync(directory);
    assert.equal(names.length, 2); const sourceName = names.find(name => name.startsWith('source-'));
    const saved = JSON.parse(fs.readFileSync(path.join(directory, sourceName), 'utf8'));
    const report = JSON.parse(fs.readFileSync(path.join(directory, 'ci-results.json'), 'utf8'));
    assert.equal(report.source_commit, env.OPENMATES_CI_EXPECTED_SOURCE); assert.equal(report.run_id, '7');
    assert.equal(report.harness_commit, env.CI_HARNESS_COMMIT); assert.equal(report.proof_profile, 'web-laptop');
    assert.equal(report.success, false); assert.deepEqual(report.results, []); assert.equal(report.source_verified, false);
    assert.equal(report.product_executed, false); assert.equal(report.cleanup, 'not_started');
    assert.equal(saved.predicate, 'source_mode'); assert.deepEqual(saved.source_diagnostic, receipt.source_diagnostic);
    assert.equal(fs.statSync(path.join(directory, sourceName)).mode & 0o777, 0o600);
    assert(same(before, fs.statSync(f.execPath, { bigint: true })), 'supplier was not chmodded or rewritten by producer');
    fs.chmodSync(directory, 0o755); const failed = invoke(); assert.equal(failed.status, 1);
    const refused = JSON.parse(failed.stderr); assert.equal(refused.predicate, 'source_mode');
    assert.equal(refused.diagnostic_export, 'failed'); assert.equal(refused.uncertain_stage_retained, true);
    assert.deepEqual(fs.readdirSync(directory), names, 'export failure neither overwrites nor deletes diagnostics');
  } finally { remove(f); }
});

test('startup failure envelope refuses missing or contradictory request identity without claiming execution', () => {
  const env = { OPENMATES_CI_EXPECTED_SOURCE: 'a'.repeat(40), CI_HARNESS_COMMIT: 'b'.repeat(40),
    GITHUB_RUN_ID: '7', CI_TEST_MODE: 'e2e', PLAYWRIGHT_PROOF_VIDEO_PROFILE: '' };
  const valid = startupFailureEnvelope('source_mode', env);
  assert.equal(valid.source_verified, false); assert.equal(valid.success, false);
  for (const [key, value] of [['OPENMATES_CI_EXPECTED_SOURCE', 'bad'], ['CI_HARNESS_COMMIT', ''], ['GITHUB_RUN_ID', '0'],
    ['CI_TEST_MODE', 'unknown'], ['PLAYWRIGHT_PROOF_VIDEO_PROFILE', 'private/path']]) {
    assert.throws(() => startupFailureEnvelope('source_mode', { ...env, [key]: value }), /failure_report_/);
  }
  assert.throws(() => startupFailureEnvelope('raw private error', env), /failure_report_profile/);
});
