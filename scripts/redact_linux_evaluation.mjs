/** Synthetic-only native SDK evaluation. Run through redact_linux_evaluation.py.
 * No OpenMates chat inference, training, provider override, or SDK modification.
 */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { performance } from 'node:perf_hooks';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let currentStage = 'validate-assets';
export const SDK_VERSION = '4.1.0';
export const PATCHED_BROTLI = Object.freeze({ version: '1.1.1', versionNumber: 0x1001001,
  commit: 'db0631dfea829194206d269bc7b25d0908cdb97d',
  archive: '38f9c17ee36c2e930ce00975b50fcd246a8e5594c1bcf43cd56b14118786b82a',
  decoderSource: '79db5a1879540eb7c915ce948e8fb94adc1ff49be87dca01529b9283c6ba343e' });
export const MODEL = Object.freeze({
  repository: 'desert-ant-labs/redact', tag: 'v0.4.0',
  revision: '3ed5033aeb544f454ebde77dc76fd7b7e76cc572',
  files: {
    'redact.tflite': 'ee36727f07e3237569e71427bfe661463a82e526f7e97e92b0fa583cad16ed27',
    'redact_tokenizer.bin': '81bc354dc99285e05b8f70edca9df3afbd83dfa4b0cea18d0448ab17ce58aae2',
    'labels.json': 'fe76679736d86b47a45fe03a94994aa292fc6203', // Git blob SHA-1
  },
});
export const loadSynthetic = file => JSON.parse(fs.readFileSync(file, 'utf8'), (_key, value) =>
  value && Object.keys(value).length === 1 && Array.isArray(value.synthetic_parts) ? value.synthetic_parts.join('') : value);
export function evidenceJSON(value) {
  // Never persist a complete credential-shaped synthetic input/prediction.
  const split = item => ({ synthetic_parts: item.match(/[\s\S]{1,12}/g) ?? [''] });
  return JSON.stringify(value, (key, item) => {
    if (key === 'expected' && Array.isArray(item)) return item.map(([label, original]) => [label, split(original)]);
    if (key === 'custom' && Array.isArray(item)) return item.map(split);
    return ['text', 'original', 'redactedText', 'value', 'match'].includes(key) && typeof item === 'string' ? split(item) : item;
  }, 2) + '\n';
}
const sha256 = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
export function verifyNativeBrotli(nativeRoot, requireNative, env = process.env) {
  if (!env.OPENMATES_REDACT_BROTLI_PREFIX || env.LD_PRELOAD || env.LD_AUDIT) throw new Error('Verified private Brotli prefix required before native SDK load');
  const prefix = fs.realpathSync(env.OPENMATES_REDACT_BROTLI_PREFIX);
  if (env.LD_LIBRARY_PATH !== path.join(prefix, 'lib')) throw new Error('Private Brotli loader path must be set before process startup');
  const receipt = JSON.parse(fs.readFileSync(path.join(prefix, 'security-build.json'), 'utf8'));
  if (receipt.schema !== 1 || receipt.version !== PATCHED_BROTLI.version || receipt.commit !== PATCHED_BROTLI.commit ||
      receipt.archive_sha256 !== PATCHED_BROTLI.archive || receipt.decoder_source_sha256 !== PATCHED_BROTLI.decoderSource ||
      receipt.fixed_block_switch_error_propagation !== true ||
      sha256(path.join(prefix, `brotli-${PATCHED_BROTLI.commit}/c/dec/decode.c`)) !== PATCHED_BROTLI.decoderSource) throw new Error('Patched decoder source identity required');
  const expected = {};
  for (const name of ['libbrotlicommon.so.1', 'libbrotlidec.so.1']) {
    const file = fs.realpathSync(path.join(prefix, 'lib', name));
    if (!file.startsWith(path.join(prefix, 'lib') + path.sep) || path.relative(prefix, file) !== receipt.libraries[name].file ||
        sha256(file) !== receipt.libraries[name].sha256) throw new Error('Private Brotli library hash/path mismatch');
    expected[name] = file;
  }
  const koffi = requireNative('koffi');
  koffi.load(path.join(nativeRoot, 'libLiteRt.so'));
  const core = koffi.load(path.join(nativeRoot, 'libRedactNode.so'));
  if (core.func('int dal_curl_available()')() !== 1) throw new Error('SDK native curl shim unavailable');
  const libc = koffi.load('libc.so.6');
  const handle = libc.func('void *dlopen(const char *, int)')('libcurl.so.4', 2 | 4); // NOW | NOLOAD
  if (!handle) throw new Error('SDK curl handle unavailable');
  const dlsym = libc.func('uintptr_t dlsym(void *, const char *)');
  const curl = koffi.load('libcurl.so.4');
  const version = curl.func('uint32_t BrotliDecoderVersion()')();
  if (version !== PATCHED_BROTLI.versionNumber) throw new Error('SDK libcurl selected an unapproved Brotli decoder');
  const mappings = fs.readFileSync('/proc/self/maps', 'utf8').trim().split('\n');
  const symbols = {};
  for (const name of ['BrotliDecoderVersion', 'BrotliDecoderDecompressStream']) {
    const address = BigInt(dlsym(handle, name));
    const mapping = mappings.find(line => {
      const [start, end] = line.split(' ')[0].split('-').map(hex => BigInt(`0x${hex}`));
      return address >= start && address < end;
    });
    const library = mapping ? fs.realpathSync(mapping.trim().split(/\s+/).at(-1)) : undefined;
    if (library !== expected['libbrotlidec.so.1']) throw new Error('Actual decoder symbol mapped outside verified prefix');
    symbols[name] = { address: `0x${address.toString(16)}`, library, sha256: sha256(library) };
  }
  const mappedBrotli = [...new Set(mappings.filter(line => line.includes('/libbrotli')).map(line => fs.realpathSync(line.trim().split(/\s+/).at(-1))))];
  if (mappedBrotli.some(file => !Object.values(expected).includes(file))) throw new Error('Unapproved system Brotli mapped in evaluator');
  const easy = curl.func('void *curl_easy_init()')();
  if (!easy) throw new Error('Offline libcurl initialization failed');
  curl.func('void curl_easy_cleanup(void *)')(easy);
  return { status: 'verified', version: PATCHED_BROTLI.version, version_number: version, commit: PATCHED_BROTLI.commit,
    prefix, symbols, mapped_brotli_libraries: mappedBrotli, curl_init_cleanup: true,
    sdk_model_or_license_created: false, http_perform_called: false };
}
const filesUnder = dir => fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry =>
  entry.isDirectory() ? filesUnder(path.join(dir, entry.name)) : entry.isFile() ? [path.join(dir, entry.name)] : []);
export function validatedSpans(text, items) {
  return items.map(item => {
    const start = item.start ?? item.startIndex;
    const end = item.end ?? item.endIndex;
    const original = item.original ?? item.match;
    const splitSurrogate = i => i > 0 && i < text.length && /[\uD800-\uDBFF]/.test(text[i - 1]) && /[\uDC00-\uDFFF]/.test(text[i]);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > text.length ||
        splitSurrogate(start) || splitSurrogate(end) || text.slice(start, end) !== original) throw new Error('Invalid UTF-16 span integrity');
    return { label: item.label ?? item.type, original, start_utf16: start, end_utf16: end,
      start: Array.from(text.slice(0, start)).length, end: Array.from(text.slice(0, end)).length,
      ...(item.confidence === undefined ? {} : { confidence: item.confidence }) };
  });
}
export function score(fixtures, rows) {
  const byId = new Map(rows.map(row => [row.id, row]));
  const byCategory = {}, values = [], negatives = [];
  for (const fixture of fixtures) {
    const spans = byId.get(fixture.id).spans;
    const covered = new Set(spans.flatMap(span => Array.from({ length: span.end - span.start }, (_, i) => span.start + i)));
    for (const [label, value] of fixture.expected) {
      const utf16Start = fixture.text.indexOf(value);
      if (utf16Start < 0) throw new Error(`Missing expected annotation: ${fixture.id}`);
      const start = Array.from(fixture.text.slice(0, utf16Start)).length;
      const positions = Array.from(value, (_, i) => start + i);
      // Strict: every annotated character, including spaces and punctuation.
      const hidden = positions.every(i => covered.has(i));
      const characters = Array.from(value);
      const meaningful = positions.filter((_, i) => /[\p{L}\p{N}\p{M}]/u.test(characters[i]));
      const lettersDigitsHidden = meaningful.length > 0 && meaningful.every(i => covered.has(i));
      const missingCharacters = characters.filter((_, i) => !covered.has(start + i));
      const group = byCategory[label] ??= { expected: 0, fully_hidden: 0, letters_digits_hidden: 0, partial: 0, exact_single_span: 0 };
      const partial = !hidden && positions.some(i => covered.has(i));
      const exact = spans.some(span => span.start === start && span.end === start + positions.length);
      group.expected++; group.fully_hidden += Number(hidden); group.letters_digits_hidden += Number(lettersDigitsHidden);
      group.partial += Number(partial); group.exact_single_span += Number(exact);
      values.push({ id: fixture.id, label, value, start, end: start + positions.length, fully_hidden: hidden,
        letters_digits_hidden: lettersDigitsHidden,
        uncovered_character_counts: { total: missingCharacters.length,
          letters_digits_marks: missingCharacters.filter(c => /[\p{L}\p{N}\p{M}]/u.test(c)).length,
          whitespace: missingCharacters.filter(c => /\s/u.test(c)).length,
          punctuation: missingCharacters.filter(c => /\p{P}/u.test(c)).length },
        partial, exact_single_span: exact });
    }
    if (!fixture.expected.length && spans.length) negatives.push({ id: fixture.id, spans });
  }
  return { expected_values: values.length, fully_hidden: values.filter(value => value.fully_hidden).length,
    letters_digits_hidden: values.filter(value => value.letters_digits_hidden).length,
    by_category: byCategory, values, negative_cases: fixtures.filter(fixture => !fixture.expected.length).length,
    false_positive_cases: negatives, offset_integrity: 'validated UTF-16 slices and Unicode code-point boundaries' };
}
async function rescore(sourceFile, output) {
  if (!sourceFile || !output || fs.existsSync(output)) throw new Error('Rescore needs captured predictions and a fresh output');
  currentStage = 'rescore-captured-predictions-no-sdk';
  const source = loadSynthetic(sourceFile);
  const { detectPII } = await import(pathToFileURL(path.join(ROOT, 'frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts')));
  const { mergeWebPIIMatches } = await import(pathToFileURL(path.join(ROOT, 'frontend/packages/ui/src/components/enter_message/services/webPIIMatches.ts')));
  const variants = Object.fromEntries(['raw_default', 'browser_policy', 'regex', 'hybrid', 'configured_regex', 'configured_hybrid'].map(key => [key, []]));
  const captured = new Map(source.quality.browser_policy.rows.map(row => [row.id, row]));
  for (const fixture of source.fixtures) {
    const row = captured.get(fixture.id);
    if (!row) throw new Error('Captured model row missing');
    const entities = row.spans.map(span => ({ label: span.label, original: span.original,
      start: span.start_utf16, end: span.end_utf16, confidence: span.confidence }));
    validatedSpans(fixture.text, entities);
    const options = { personalDataEntries: (fixture.custom ?? []).map((textToHide, i) => ({ textToHide, replaceWith: `CUSTOM_${i}` })) };
    variants.raw_default.push(source.quality.raw_default.rows.find(item => item.id === fixture.id));
    variants.browser_policy.push(row);
    for (const [name, items] of Object.entries({ regex: detectPII(fixture.text), hybrid: mergeWebPIIMatches(fixture.text, entities),
      configured_regex: detectPII(fixture.text, options), configured_hybrid: mergeWebPIIMatches(fixture.text, entities, options) })) {
      variants[name].push({ id: fixture.id, spans: validatedSpans(fixture.text, items) });
    }
  }
  const sourceFiles = ['frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts',
    'frontend/packages/ui/src/components/enter_message/services/webPIIMatches.ts', 'frontend/packages/secret-scanner/src/identifierRanges.ts'];
  const result = { status: 'complete', mode: 'deterministic-rescore-of-captured-native-predictions',
    model_inference_rerun: false, model: source.model, sdk: source.sdk, fixtures: source.fixtures,
    captured_prediction_source: { file: path.relative(ROOT, path.resolve(sourceFile)), sha256: sha256(sourceFile), source_hashes: source.source_hashes },
    current_source_hashes: Object.fromEntries(sourceFiles.map(file => [file, sha256(path.join(ROOT, file))])),
    quality: Object.fromEntries(Object.entries(variants).map(([name, rows]) => [name, { ...score(source.fixtures, rows), rows }])) };
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, evidenceJSON(result));
}
export function boundaryFixtures() {
  return [255, 1024, 4096].map(units => ({ id: `window-tail-${units}`, synthetic_generated: true,
    text: 'ordinary context '.repeat(units) + '👋 Our customer Élodie Moreau needs help. Contact nadia.silva@example.net.',
    expected: [['private_person', 'Élodie Moreau'], ['private_email', 'nadia.silva@example.net']] }));
}
export function percentile(values, fraction) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.max(0, Math.ceil(fraction * sorted.length) - 1)];
}
function sealNetwork(requireNative) {
  // TSYNC applies to all pre-existing Node, Swift and LiteRT threads as well.
  const koffi = requireNative('koffi');
  const lib = koffi.load('libseccomp.so.2');
  const init = lib.func('void *seccomp_init(uint32_t)');
  const attr = lib.func('int seccomp_attr_set(void *, int, uint32_t)');
  const resolve = lib.func('int seccomp_syscall_resolve_name(const char *)');
  const add = lib.func('int seccomp_rule_add(void *, uint32_t, int, unsigned int)');
  const load = lib.func('int seccomp_load(void *)');
  const release = lib.func('void seccomp_release(void *)');
  // Refuse an offline claim when previously opened Internet sockets remain.
  const sockets = new Set(fs.readdirSync('/proc/self/fd').flatMap(fd => {
    try { return [fs.readlinkSync(`/proc/self/fd/${fd}`).match(/^socket:\[(\d+)\]$/)?.[1]].filter(Boolean); } catch { return []; }
  }));
  for (const table of ['tcp', 'tcp6', 'udp', 'udp6']) {
    const inodes = fs.readFileSync(`/proc/self/net/${table}`, 'utf8').trim().split('\n').slice(1).map(line => line.trim().split(/\s+/)[9]);
    if (inodes.some(inode => sockets.has(inode))) throw new Error('Offline proof blocked: existing Internet socket after normal license flush');
  }
  const ctx = init(0x7fff0000);
  if (!ctx) throw new Error('seccomp init failed');
  try {
    if (attr(ctx, 4, 1)) throw new Error('seccomp all-thread synchronization unavailable');
    for (const name of ['socket', 'socketpair', 'connect', 'sendto', 'sendmsg', 'sendmmsg']) {
      const syscall = resolve(name);
      if (syscall < 0 || add(ctx, 0x00050001, syscall, 0)) throw new Error('seccomp deny rule failed');
    }
    if (load(ctx)) throw new Error('seccomp TSYNC load failed');
  } finally { release(ctx); }
  // C ABI self-check avoids DNS caches or a misleading JavaScript fetch mock.
  const libc = koffi.load('libc.so.6');
  const socket = libc.func('int socket(int, int, int)');
  if (socket(2, 1, 0) !== -1 || koffi.errno() !== 1) throw new Error('seccomp socket denial self-check failed');
  return { mechanism: 'libseccomp TSYNC, EPERM', all_threads: true, socket_creation_denied: true,
    existing_internet_sockets: 0, required_telemetry: 'normal SDK load and flush before seal; SDK unmodified' };
}
async function main() {
  const [mode, directory, output, repeatsRaw = '7', phase = 'all', unitsRaw = '32,256,1024,4096'] = process.argv.slice(2);
  if (mode === '--rescore') return rescore(directory, output);
  if (!['--inspect', '--run', '--native-preflight'].includes(mode) || !directory || !output) throw new Error('Usage: --inspect|--run MODEL_DIRECTORY OUTPUT [REPEATS]');
  if (fs.existsSync(output)) throw new Error('Choose a fresh evidence output path');
  if (mode === '--run' && process.env.OPENMATES_REDACT_EVALUATION_GO !== 'web-trial-passed') throw new Error('Benchmark gated on parent confirmation of successful web trial');
  const uiRequire = createRequire(path.join(ROOT, 'frontend/packages/ui/package.json'));
  const sdkRoot = path.dirname(uiRequire.resolve('@desert-ant-labs/redact'));
  const requireNative = createRequire(path.join(sdkRoot, 'node.js'));
  const sdkPackage = JSON.parse(fs.readFileSync(path.join(sdkRoot, 'package.json'), 'utf8'));
  if (sdkPackage.version !== SDK_VERSION) throw new Error('SDK version mismatch');
  const coreRoot = path.dirname(requireNative.resolve('@desert-ant-labs/core'));
  const corePackage = JSON.parse(fs.readFileSync(path.join(coreRoot, 'package.json'), 'utf8'));
  const koffiRoot = path.dirname(requireNative.resolve('koffi/package.json'));
  const koffiPackage = JSON.parse(fs.readFileSync(path.join(koffiRoot, 'package.json'), 'utf8'));
  if (corePackage.version !== '4.1.0' || koffiPackage.version !== '2.16.3') throw new Error('Native dependency version mismatch');
  const nativeRoot = path.join(sdkRoot, 'native', `${process.platform}-${process.arch}`);
  let decoderPreflight;
  if (mode === '--run' || mode === '--native-preflight') {
    currentStage = 'patched-native-decoder-preflight';
    const offline = mode === '--native-preflight' ? sealNetwork(requireNative) : undefined;
    decoderPreflight = verifyNativeBrotli(nativeRoot, requireNative);
    if (mode === '--native-preflight') {
      fs.mkdirSync(path.dirname(output), { recursive: true });
      fs.writeFileSync(output, JSON.stringify({ ...decoderPreflight, offline: { ...offline,
        required_telemetry: 'not started: loader-only preflight creates no model or SDK license client' } }, null, 2) + '\n');
      return;
    }
  }
  const nativeFiles = filesUnder(nativeRoot).map(file => ({ file: path.basename(file), bytes: fs.statSync(file).size, sha256: sha256(file) }));
  const modelFiles = Object.entries(MODEL.files).map(([name, expected]) => {
    const file = path.join(directory, name), bytes = fs.readFileSync(file);
    const hash = name === 'labels.json' ? createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex') : sha256(file);
    if (hash !== expected) throw new Error(`Pinned model hash mismatch: ${name}`);
    return { file: name, bytes: bytes.length, sha256: sha256(file) };
  });
  const base = { status: mode === '--inspect' ? 'verified-assets-only-no-model-load' : 'running',
    native_decoder_preflight: decoderPreflight,
    model: MODEL, sdk: { name: sdkPackage.name, version: sdkPackage.version,
      core_version: corePackage.version, koffi_version: koffiPackage.version },
    environment: { platform: process.platform, architecture: process.arch, node: process.version, os: os.release(),
      cpu: os.cpus()[0]?.model, affinity: fs.readFileSync('/proc/self/status', 'utf8').match(/^Cpus_allowed_list:\s*(.*)$/m)?.[1],
      native_thread_setting: 'SDK default; no supported public thread option; all threads affinity-bounded by supervisor' },
    disk: { native_files: nativeFiles, model_files: modelFiles,
      model_plus_native_bytes: [...nativeFiles, ...modelFiles].reduce((sum, file) => sum + file.bytes, 0),
      note: 'Logical file sizes; excludes shared system libraries, Node executable and npm JS dependency tree' } };
  const save = result => { fs.mkdirSync(path.dirname(output), { recursive: true }); fs.writeFileSync(output, evidenceJSON(result)); };
  if (mode === '--inspect') { save(base); return; }
  if (process.env.OPENMATES_REDACT_EVALUATION_GO !== 'web-trial-passed') throw new Error('Benchmark gated on parent confirmation of successful web trial');
  const repeats = Number(repeatsRaw);
  if (!Number.isInteger(repeats) || repeats < 3 || repeats > 15) throw new Error('Repeats must be 3..15');
  if (!['all', 'latency-only'].includes(phase)) throw new Error('Unknown evaluation phase');
  const latencyUnits = unitsRaw.split(',').map(Number);
  if (!latencyUnits.length || latencyUnits.some(n => ![32, 256, 1024, 4096].includes(n))) throw new Error('Unsupported input length');
  currentStage = 'import-local-detectors';
  const { detectPII } = await import(pathToFileURL(path.join(ROOT, 'frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts')));
  const { mergeWebPIIMatches, WEB_PII_LABELS } = await import(pathToFileURL(path.join(ROOT, 'frontend/packages/ui/src/components/enter_message/services/webPIIMatches.ts')));
  const baselineSource = path.join(ROOT, 'scripts/privacy_filter_regex_baseline.mjs');
  base.source_hashes = Object.fromEntries([baselineSource, fileURLToPath(import.meta.url), path.join(ROOT, 'scripts/redact_linux_evaluation.py'),
    path.join(ROOT, 'frontend/packages/secret-scanner/src/identifierRanges.ts'), 'piiDetectionService.ts', 'webPIIMatches.ts'].map(file => {
    const full = path.isAbsolute(file) ? file : path.join(ROOT, 'frontend/packages/ui/src/components/enter_message/services', file);
    return [path.relative(ROOT, full), sha256(full)];
  }));
  const { Redact, DEFAULT_LABELS } = await import(pathToFileURL(path.join(sdkRoot, 'node.js')));
  const before = process.memoryUsage().rss;
  const progressFile = output.replace(/\.json$/, '') + '.progress.json';
  const progress = { status: 'running', stage: currentStage, completed_quality_cases: 0, quality_timings: [], latency: [] };
  const checkpoint = () => {
    fs.mkdirSync(path.dirname(progressFile), { recursive: true });
    fs.writeFileSync(progressFile, JSON.stringify({ ...progress, stage: currentStage,
      current_rss_bytes: process.memoryUsage().rss }, null, 2) + '\n');
  };
  currentStage = 'load-and-normal-license-flush';
  checkpoint();
  let start = performance.now();
  let model = await Redact.load({ directory });
  const firstLoadMs = performance.now() - start;
  await model.flushTelemetry();
  model.dispose();
  start = performance.now();
  model = await Redact.load({ directory });
  const warmReloadMs = performance.now() - start;
  await model.flushTelemetry();
  const afterLoad = process.memoryUsage().rss;
  base.environment.native_threads_after_load = fs.readdirSync('/proc/self/task').length;
  progress.load = { first_new_process_ms: firstLoadMs, warm_same_process_reload_ms: warmReloadMs };
  progress.environment = base.environment;
  currentStage = 'offline-network-seal';
  const offline = sealNetwork(requireNative);
  progress.offline = offline;
  checkpoint();
  const fixtureFile = path.join(ROOT, 'scripts/fixtures/privacy-filter-synthetic.json');
  const fixtures = phase === 'latency-only' ? [] : [...loadSynthetic(fixtureFile), ...boundaryFixtures()];
  const variants = Object.fromEntries(['raw_default', 'browser_policy', 'regex', 'hybrid', 'configured_regex', 'configured_hybrid'].map(key => [key, []]));
  let restoreFailures = 0;
  currentStage = 'synthetic-quality';
  for (const fixture of fixtures) {
    progress.current_fixture = fixture.id;
    checkpoint();
    start = performance.now();
    const raw = await model.redaction(fixture.text);
    const rawMs = performance.now() - start;
    start = performance.now();
    const browser = await model.redaction(fixture.text, { labels: WEB_PII_LABELS });
    const browserMs = performance.now() - start;
    if (raw.restore(raw.redactedText) !== fixture.text || browser.restore(browser.redactedText) !== fixture.text) restoreFailures++;
    const options = { personalDataEntries: (fixture.custom ?? []).map((textToHide, i) => ({ textToHide, replaceWith: `CUSTOM_${i}` })) };
    const detections = { raw_default: raw.items, browser_policy: browser.items, regex: detectPII(fixture.text),
      hybrid: mergeWebPIIMatches(fixture.text, browser.items), configured_regex: detectPII(fixture.text, options),
      configured_hybrid: mergeWebPIIMatches(fixture.text, browser.items, options) };
    for (const [name, items] of Object.entries(detections)) variants[name].push({ id: fixture.id, spans: validatedSpans(fixture.text, items) });
    progress.completed_quality_cases++;
    progress.quality_timings.push({ id: fixture.id, characters_utf16: fixture.text.length, raw_ms: rawMs, browser_ms: browserMs });
    if (progress.completed_quality_cases === 1) progress.after_first_inference_rss_bytes = process.memoryUsage().rss;
    if (progress.completed_quality_cases === 1 || progress.completed_quality_cases % 10 === 0 || progress.completed_quality_cases >= fixtures.length - 3) {
      const completed = fixtures.slice(0, progress.completed_quality_cases);
      fs.writeFileSync(output.replace(/\.json$/, '') + '.partial.json', evidenceJSON({ ...base, status: 'partial', offline,
        fixtures: completed, quality: Object.fromEntries(Object.entries(variants).map(([name, rows]) => [name, { ...score(completed, rows), rows }])) }));
    }
    checkpoint();
  }
  const latency = [];
  let repeatedOutputDrift = 0;
  currentStage = 'bounded-latency';
  const fingerprint = result => JSON.stringify(result.items.map(({ label, start, end }) => ({ label, start, end })));
  let firstWarmupMs;
  for (const units of latencyUnits) {
    progress.current_latency_whitespace_units = units;
    checkpoint();
    const text = Array.from({ length: units }, (_, i) => ['The', 'ordinary', 'document', 'has', 'useful', 'context', 'for', 'review.'][i % 8]).join(' ');
    start = performance.now();
    const reference = fingerprint(await model.redaction(text, { labels: WEB_PII_LABELS })); // warm-up per length
    firstWarmupMs ??= performance.now() - start;
    const samples = [];
    const rssBefore = process.memoryUsage().rss;
    progress.active_latency_samples_ms = samples;
    for (let i = 0; i < repeats; i++) {
      start = performance.now(); const result = await model.redaction(text, { labels: WEB_PII_LABELS }); samples.push(performance.now() - start);
      if (fingerprint(result) !== reference) repeatedOutputDrift++;
      checkpoint();
    }
    latency.push({ whitespace_units: units, characters_utf16: text.length, tokenizer: 'not measured: whitespace units are NOT model tokens',
      milliseconds: samples, median_ms: percentile(samples, 0.5), p95_ms: percentile(samples, 0.95),
      before_repetitions_rss_bytes: rssBefore, after_repetitions_rss_bytes: process.memoryUsage().rss });
    progress.latency = latency;
    checkpoint();
  }
  model.dispose();
  save({ ...base, status: 'complete', offline, labels: { raw_default: DEFAULT_LABELS, browser_policy: WEB_PII_LABELS },
    fixture_sha256: sha256(fixtureFile), fixtures,
    memory: { before_model_load_rss_bytes: before, after_model_load_rss_bytes: afterLoad,
      after_first_inference_rss_bytes: progress.after_first_inference_rss_bytes,
      final_rss_bytes: process.memoryUsage().rss, process_peak_rss_bytes: process.resourceUsage().maxRSS * 1024 },
    load: { first_new_process_ms: firstLoadMs, warm_same_process_reload_ms: warmReloadMs,
      first_redaction_ms: progress.quality_timings[0]?.raw_ms ?? firstWarmupMs,
      note: 'OS page cache not flushed; SDK can initialize lazily: first_redaction_ms includes any deferred initialization' },
    reliability: { restore_failures: restoreFailures, repeated_output_drift: repeatedOutputDrift, completed_quality_cases: fixtures.length,
      completed_latency_scans: latency.length * repeats, fail_closed_on_sdk_or_offset_error: true },
    quality: phase === 'latency-only' ? null : Object.fromEntries(Object.entries(variants).map(([name, rows]) => [name, { ...score(fixtures, rows), rows }])),
    quality_timings: progress.quality_timings, latency });
  progress.status = 'complete'; checkpoint();
  if (restoreFailures || repeatedOutputDrift) process.exitCode = 1;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => {
    const output = process.argv[4];
    if (output && !fs.existsSync(output)) {
      fs.mkdirSync(path.dirname(output), { recursive: true });
      fs.writeFileSync(output, JSON.stringify({ status: 'failed', stage: currentStage,
        error_type: error.name, note: 'Error message omitted to avoid raw SDK input/output logs' }, null, 2) + '\n');
    }
    process.stderr.write(`Redact evaluation stopped during ${currentStage}: ${error.name}\n`);
    process.exitCode = 1;
  });
}
