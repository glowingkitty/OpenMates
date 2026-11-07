#!/usr/bin/env node
/**
 * Generates packages/openmates-rust/src/embed_read_ts_vectors.json: TS-generated
 * parity vectors for openmates_sdk::embed_read (status machine, embed link targets,
 * direct embed refs, version patch replay). Every vector records what the current
 * TS source returns (or `error` + message when it throws). The Rust tests replay it;
 * rustCore/__tests__/embedReadVectors.test.ts re-runs TS over the committed inputs.
 *
 * Usage: node generate-embed-read-vectors.mjs > ../../../packages/openmates-rust/src/embed_read_ts_vectors.json
 */
import { mkdtempSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { stripTypeScriptTypes } from 'node:module';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');
const out = mkdtempSync(join(tmpdir(), 'embed-read-vectors-'));
mkdirSync(join(out, 'a'));
for (const [rel, name] of [
	['services/embedStateMachine.ts', 'status.mjs'],
	['utils/embedFragmentUtils.ts', 'fragment.mjs'],
	['utils/projectFilePatch.ts', 'projectFilePatch.mjs'],
	['utils/embedVersionReconstruction.ts', 'version.mjs'],
]) {
	const code = stripTypeScriptTypes(readFileSync(join(src, rel), 'utf8'), { mode: 'strip' })
		.replace(/from '\.\/projectFilePatch\.js'/g, "from './projectFilePatch.mjs'");
	writeFileSync(join(out, name), code);
}
const load = (n) => import(pathToFileURL(join(out, n)).href);
const status = await load('status.mjs');
const fragment = await load('fragment.mjs');
const version = await load('version.mjs');
const warn = console.warn; console.warn = () => {};

const run = (fn) => { try { return { json: JSON.stringify(fn()) }; } catch (e) { return { error: String(e.message) }; } };
const vectors = [];

const statuses = [...Object.values(status.EmbedStatus), 'bogus', '', 'completed'];
for (const a of statuses) for (const b of statuses) {
	vectors.push({ kind: 'transition', current: a, target: b, json: JSON.stringify(status.validateEmbedTransition(a, b)) });
}
for (const s of statuses) {
	vectors.push({ kind: 'terminal', status: s, json: JSON.stringify(status.isTerminalStatus(s)) });
	vectors.push({ kind: 'normalize', status: s, json: JSON.stringify(status.normalizeEmbedStatus(s)) });
}
vectors.push({ kind: 'normalize', status: null, json: JSON.stringify(status.normalizeEmbedStatus(null)) });

const links = [
	'file.py', 'file.py#L10-L20', 'file.py#L20-L10', 'file.py#L7', 'file.py#L3-5', 'file.py#L1-L', 'file.py#L', 'file.py#l5',
	'doc#text=quote', 'doc#quote=hello+world', 'doc#text=a%20b%26c', 'doc#text=%E0%A4%A', 'doc#text=%ZZ', 'doc#text=%C3%A9t%C3%A9',
	'doc#text=&quote=fallback', 'doc#?text=lead', 'sheet#range=a1:c4', 'sheet#cell=b2', 'sheet#range=&cell=z9', 'sheet#range=a%31:b2',
	'a#b#c', '#L5', '', 'x#', 'x#text', 'x#text=1&text=2', 'x#range=%e9', 'x#unknown=1', 'x#text=a=b', 'x#text=%2B+%2b',
];
for (const input of links) vectors.push({ kind: 'link', input, ...run(() => fragment.parseEmbedLinkTarget(input)) });

const refs = [
	['code', 'abcdef123', { filename: 'My File.py' }], ['code', 'abcdef123', { filename: 'abcdef-x' }],
	['web_search', 'ab', {}], ['', '', {}], ['', 'zz9999', {}], ['sheet', 'q1w2e3r4', { title: '  Q1 Budget / 2026!! ' }],
	['doc', 'a1b2c3d4', { subject: '---' }], ['doc', 'a1b2c3d4', { filename: '', title: 'T', subject: 'S' }],
	['doc', 'a1b2c3d4', { filename: 'x'.repeat(80) }], ['doc', 'a1b2c3d4', { filename: `${'x'.repeat(47)}-.-` }],
	['doc', 'a1b2c3d4', { filename: 'Ünï cödé' }], ['doc', 'a1b2c3d4', { filename: '.._hidden_..' }], ['my_type', 'a1b2c3d4', { title: 'a1b2c3d4' }],
	['doc', 'a1b2c3d4', { filename: 'name-a1b2c3' }], ['doc', 'a1b2c3d4', { title: '\t\n a  b \n' }], ['doc', 'a1b2c3d4', { title: 'A--B__C' }],
];
for (const [embedType, embedId, meta] of refs) {
	vectors.push({ kind: 'ref', embed_type: embedType, embed_id: embedId, ...meta, json: JSON.stringify(fragment.generateDirectEmbedRef(embedType, embedId, meta)) });
}

const base = 'one\ntwo\nthree\nfour\n';
const patches = [
	[base, '@@ -2,1 +2,1 @@\n-two\n+TWO\n'], [base, '--- a\n+++ b\n@@ -1,2 +1,3 @@\n one\n+inserted\n two\n'],
	['', '@@ -0,0 +1,2 @@\n+a\n+b\n'], [base, '@@ -2 +2 @@\n-two\n+2\n'], [base, '@@ -9,1 +9,1 @@\n-x\n+y\n'],
	[base, '@@ -2,1 +2,1 @@\n-nope\n+y\n'], [base, 'garbage'], [base, ''], [base, '--- a\n+++ b\n'],
	[base, '@@ -1,1 +1,2 @@\n-one\n+x\n'], [base, '@@ -1,1 +1,1 @@\n one\n@@ -1,1 +1,1 @@\n one\n'],
	[base, '@@ -3,2 +3,1 @@ ctx\n three\n-four\n'], [base, '@@ -2,1 +2,1 @@\nbad\n'], ['a\nb', '@@ -2,1 +2,1 @@\n-b\n+c'],
	['a\nb', '@@ -2,1 +2,1 @@\n-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n'],
	['a\nb\n', '@@ -2,1 +2,1 @@\n-b\n+c\n\\ No newline at end of file\n'],
	['a\nb', '--- x\n+++ x\n@@ -1,2 +1,2 @@\n a\n-b\n\\ No newline at end of file\n+c\n'],
	['a\nb', '@@ -1,2 +1,2 @@\n a\n-b\n+c\n\\ No newline at end of file\n'],
	['a\nb', '\\ No newline at end of file\n'], ['a\r\nb', '@@ -1,1 +1,1 @@\n-a\r\n+b\n'],
	[base, '@@ -0,0 +1,1 @@\n+z\n'], [base, '@@ -4,0 +5,1 @@\n+z\n'], [base, '@@ -2,1 +9,1 @@\n-two\n+2\n'],
	[base, '@@ -0,1 +1,1 @@\n-one\n+x\n'], [base, '@@ -2,1 +2,1 @@ trailing text\n-two\n+2\n'], [base, '@@ -2,1 +2,1 @@x\n-two\n+2\n'],
];
for (const [content, patch] of patches) {
	vectors.push({ kind: 'patch', content, patch, ...run(() => version.applyVersionPatch(content, patch)) });
}
console.warn = warn;
process.stdout.write(`${JSON.stringify({ generator: 'frontend/packages/ui/scripts/generate-embed-read-vectors.mjs', vectors }, null, 1)}\n`);
