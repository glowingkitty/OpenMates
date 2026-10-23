#!/usr/bin/env node
// Trusted Linux CI producer. Builtins only; consumer file guards stay unchanged.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const C = fs.constants;
const LIMIT = 256 * 1024 * 1024;
const SELF = fileURLToPath(import.meta.url);
const fields = ['dev', 'ino', 'mode', 'nlink', 'uid', 'gid', 'size', 'mtimeNs', 'ctimeNs'];
function need(ok, code) { if (!ok) throw new Error(code); }
export function identity(stat) { return Object.fromEntries(fields.map(k => [k, String(stat[k])])); }
export function same(a, b) { return fields.every(k => String(a[k]) === String(b[k])); }
function stat(fd) { return fs.fstatSync(fd, { bigint: true }); }
function lstat(name) { return fs.lstatSync(name, { bigint: true }); }
function directorySame(a, b) {
  return ['dev', 'ino', 'mode', 'uid', 'gid'].every(k => String(a[k]) === String(b[k]));
}
function openDirectory(name) { return fs.openSync(name, C.O_RDONLY | C.O_DIRECTORY | C.O_NOFOLLOW); }
export function digest(fd) {
  const hash = crypto.createHash('sha256'); const bytes = Buffer.alloc(1024 * 1024);
  for (let offset = 0;;) { const n = fs.readSync(fd, bytes, 0, bytes.length, offset); if (!n) break;
    offset += n; need(offset <= LIMIT, 'source_size'); hash.update(bytes.subarray(0, n)); }
  return hash.digest('hex');
}
export function sourcePolicy(s, euid) {
  need(s.isFile() && s.nlink === 1n, 'source_regular_single_link');
  need(s.uid === 0n || s.uid === BigInt(euid), 'source_owner');
  // Only the attested supplier may be group writable. World writable is refused.
  need((s.mode & 0o7002n) === 0n && (s.mode & 0o111n) !== 0n, 'source_mode');
  need(s.size > 0n && s.size <= BigInt(LIMIT), 'source_size');
}
export function supplierPath(execPath, cache, version, arch) {
  need(/^v24\.\d+\.\d+$/.test(version), 'source_version');
  need(['x64', 'arm64'].includes(arch), 'source_arch');
  need(path.isAbsolute(cache) && fs.realpathSync(cache) === cache, 'toolcache_path');
  const expected = path.join(cache, 'node', version.slice(1), arch, 'bin', 'node');
  need(execPath === expected && fs.realpathSync(execPath) === execPath, 'supplier_path');
  return expected;
}
export function attestSource({ execPath = process.execPath, cache = process.env.RUNNER_TOOL_CACHE,
  version = process.version, arch = process.arch, procPath = '/proc/self/exe' } = {}) {
  need(typeof cache === 'string', 'toolcache_missing');
  supplierPath(execPath, cache, version, arch);
  const fd = fs.openSync(procPath, C.O_RDONLY);
  try {
    const before = stat(fd); sourcePolicy(before, process.geteuid());
    need(fs.realpathSync(procPath) === execPath && same(before, lstat(execPath)), 'proc_identity');
    const magic = Buffer.alloc(4); fs.readSync(fd, magic, 0, 4, 0);
    need(magic.equals(Buffer.from([0x7f, 0x45, 0x4c, 0x46])), 'source_elf');
    const hash = digest(fd);
    need(same(before, stat(fd)) && same(before, lstat(execPath)), 'source_mutation');
    return { fd, before, hash, execPath, version, arch };
  } catch (error) { fs.closeSync(fd); throw error; }
}
function privateFile(s, euid) {
  need(s.isFile() && s.nlink === 1n && s.uid === BigInt(euid)
    && (s.mode & 0o077n) === 0n, 'private_file');
}
function parentOpen() {
  need(fs.realpathSync('/tmp') === '/tmp', 'parent_path');
  const fd = openDirectory('/tmp'); const before = stat(fd);
  need(before.uid === 0n && (before.mode & 0o1000n) !== 0n, 'parent_policy');
  need(directorySame(before, lstat('/tmp')), 'parent_identity');
  return { fd, before };
}
export function parentCurrent(parent, filename = '/tmp') {
  need(directorySame(parent.before, stat(parent.fd))
    && directorySame(parent.before, lstat(filename)), 'parent_swap');
}
export function copySource(source, directoryFd) {
  const destination = `/proc/self/fd/${directoryFd}/node`;
  const fd = fs.openSync(destination, C.O_WRONLY | C.O_CREAT | C.O_EXCL | C.O_NOFOLLOW, 0o700);
  try {
    const bytes = Buffer.alloc(1024 * 1024);
    for (let offset = 0;;) { const n = fs.readSync(source.fd, bytes, 0, bytes.length, offset); if (!n) break;
      let written = 0;
      while (written < n) {
        const remaining = n - written;
        const count = fs.writeSync(fd, bytes, written, remaining);
        need(Number.isInteger(count) && count > 0 && count <= remaining, 'destination_write');
        written += count;
      }
      offset += n; need(offset <= LIMIT, 'source_size'); }
    fs.fsyncSync(fd);
  } finally { fs.closeSync(fd); }
  const read = fs.openSync(destination, C.O_RDONLY | C.O_NOFOLLOW);
  try {
    const s = stat(read); privateFile(s, process.geteuid());
    need((s.mode & 0o777n) === 0o700n, 'destination_mode');
    need(s.dev !== source.before.dev || s.ino !== source.before.ino, 'fresh_inode');
    need(digest(read) === source.hash && digest(source.fd) === source.hash
      && same(source.before, stat(source.fd)) && same(source.before, lstat(source.execPath)), 'source_mutation');
    return identity(s);
  } finally { fs.closeSync(read); }
}
function publicReceipt(state) {
  return { schema_version: 1, producer: 'trusted-node-runtime-v1', node_version: state.version,
    architecture: state.arch, sha256: state.hash, producer_sha256: state.producerHash,
    source: { proc_identity: true, toolcache_supplier: true, stable: true, regular_elf: true,
      single_link: true, owner_admitted: true, group_write_supplier_exception: state.sourceGroupWritable },
    destination: { fresh_inode: true, private_directory: true, owner_current: true,
      mode_0700: true, single_link: true, fsynced: true, hash_matches: true } };
}
function producerHash() { return crypto.createHash('sha256').update(fs.readFileSync(SELF)).digest('hex'); }
export function stage() {
  need(process.platform === 'linux', 'linux_required');
  const source = attestSource(); const parent = parentOpen(); let directoryFd;
  try {
    const anchored = fs.mkdtempSync(`/proc/self/fd/${parent.fd}/openmates-ci-node-`);
    const directory = fs.realpathSync(anchored);
    directoryFd = openDirectory(anchored); const ds = stat(directoryFd);
    need(ds.uid === BigInt(process.geteuid()) && (ds.mode & 0o777n) === 0o700n, 'directory_policy');
    const binary = copySource(source, directoryFd); parentCurrent(parent);
    need(directorySame(ds, lstat(directory)), 'directory_swap');
    const state = { schema: 1, directory, directoryIdentity: identity(ds), binary,
      hash: source.hash, version: source.version, arch: source.arch, producerHash: producerHash(),
      sourceGroupWritable: (source.before.mode & 0o020n) !== 0n };
    const stateFd = fs.openSync(`/proc/self/fd/${directoryFd}/state.json`, C.O_WRONLY | C.O_CREAT | C.O_EXCL | C.O_NOFOLLOW, 0o600);
    try { fs.writeFileSync(stateFd, JSON.stringify(state)); fs.fsyncSync(stateFd); } finally { fs.closeSync(stateFd); }
    fs.fsyncSync(directoryFd); parentCurrent(parent);
    return { state, receipt: publicReceipt(state) };
  } finally { fs.closeSync(source.fd); fs.closeSync(parent.fd); if (directoryFd !== undefined) fs.closeSync(directoryFd); }
}
export function readState(filename) {
  need(typeof filename === 'string' && /^\/tmp\/openmates-ci-node-[A-Za-z0-9]+\/state\.json$/.test(filename), 'state_path');
  const directory = path.dirname(filename); const parent = parentOpen(); let directoryFd;
  try {
    directoryFd = openDirectory(directory); const ds = stat(directoryFd);
    need(ds.uid === BigInt(process.geteuid()) && (ds.mode & 0o777n) === 0o700n, 'directory_policy');
    const fd = fs.openSync(`/proc/self/fd/${directoryFd}/state.json`, C.O_RDONLY | C.O_NOFOLLOW);
    let state; let stateIdentity;
    try { const before = stat(fd); privateFile(before, process.geteuid()); need(before.size < 16384n, 'state_size');
      state = JSON.parse(fs.readFileSync(fd, 'utf8')); need(same(before, stat(fd)), 'state_mutation'); stateIdentity = identity(before); }
    finally { fs.closeSync(fd); }
    need(state.schema === 1 && state.directory === directory && directorySame(state.directoryIdentity, ds), 'state_identity');
    need(state.producerHash === producerHash(), 'producer_identity');
    need(/^v24\.\d+\.\d+$/.test(state.version) && state.arch === process.arch, 'state_version');
    const fdNode = fs.openSync(`/proc/self/fd/${directoryFd}/node`, C.O_RDONLY | C.O_NOFOLLOW);
    try { const before = stat(fdNode); privateFile(before, process.geteuid());
      need(same(state.binary, before) && digest(fdNode) === state.hash && same(before, stat(fdNode)), 'binary_identity'); }
    finally { fs.closeSync(fdNode); }
    parentCurrent(parent); need(directorySame(ds, lstat(directory)), 'directory_swap');
    return { state, stateIdentity, directoryFd, parent };
  } catch (error) { if (directoryFd !== undefined) fs.closeSync(directoryFd); fs.closeSync(parent.fd); throw error; }
}
export function verify(filename) {
  const opened = readState(filename);
  try { const expected = path.join(opened.state.directory, 'node');
    const executableFd = fs.openSync('/proc/self/exe', C.O_RDONLY);
    try { need(process.execPath === expected && fs.realpathSync('/proc/self/exe') === expected
      && same(stat(executableFd), opened.state.binary), 'pinned_process'); }
    finally { fs.closeSync(executableFd); }
    need(process.version === opened.state.version, 'pinned_version'); return publicReceipt(opened.state);
  } finally { fs.closeSync(opened.directoryFd); fs.closeSync(opened.parent.fd); }
}
export function cleanup(filename) {
  const opened = readState(filename);
  try {
    parentCurrent(opened.parent);
    for (const name of fs.readdirSync(`/proc/self/fd/${opened.directoryFd}`)) need(['node', 'state.json'].includes(name), 'cleanup_unknown_entry');
    need(directorySame(stat(opened.directoryFd), lstat(opened.state.directory)), 'cleanup_directory_swap');
    need(same(opened.state.binary, lstat(`/proc/self/fd/${opened.directoryFd}/node`)), 'cleanup_binary_swap');
    fs.unlinkSync(`/proc/self/fd/${opened.directoryFd}/node`);
    need(same(opened.stateIdentity, lstat(`/proc/self/fd/${opened.directoryFd}/state.json`)), 'cleanup_state_swap');
    fs.unlinkSync(`/proc/self/fd/${opened.directoryFd}/state.json`);
    parentCurrent(opened.parent);
    need(directorySame(stat(opened.directoryFd), lstat(opened.state.directory)), 'cleanup_directory_swap');
    fs.rmdirSync(opened.state.directory); return { schema_version: 1, cleanup: 'removed', identity_verified: true };
  } finally { fs.closeSync(opened.directoryFd); fs.closeSync(opened.parent.fd); }
}
if (process.argv[1] && path.resolve(process.argv[1]) === SELF) {
  try {
    const mode = process.argv[2]; let receipt;
    if (mode === 'stage') {
      const result = stage(); receipt = result.receipt;
      need(process.env.GITHUB_ENV && process.env.GITHUB_PATH, 'github_outputs');
      fs.appendFileSync(process.env.GITHUB_ENV, `OPENMATES_CI_NODE=${result.state.directory}/node\nOPENMATES_CI_NODE_STATE=${result.state.directory}/state.json\n`);
      fs.appendFileSync(process.env.GITHUB_PATH, `${result.state.directory}\n`);
    } else if (mode === 'verify') receipt = verify(process.env.OPENMATES_CI_NODE_STATE);
    else if (mode === 'cleanup') receipt = cleanup(process.env.OPENMATES_CI_NODE_STATE);
    else throw new Error('mode');
    console.log(JSON.stringify(receipt));
  } catch (error) {
    const allowed = /^[a-z_]+$/.test(error.message) ? error.message : 'producer_io';
    console.error(JSON.stringify({ schema_version: 1, status: 'refused', predicate: allowed, uncertain_stage_retained: true })); process.exitCode = 1;
  }
}
