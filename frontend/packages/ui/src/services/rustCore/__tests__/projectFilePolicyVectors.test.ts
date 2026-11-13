// TS↔Rust parity vectors for the hosted Project file decisions (projectFilePolicy.ts).
// The cases below run through the real flag-off TypeScript rules; the committed JSON
// (packages/openmates-rust/src/web_projects/hosted_files_ts_vectors.json) holds their
// outcomes and is replayed by Rust in web_projects/hosted_files_tests.rs. When the file
// is missing or stale this test prints the regenerated document to the log.
// The 500-entry list cap is covered by a hand-written Rust test to keep the file small.
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { PROJECT_FILE_POLICY, runProjectFilePolicy, type ProjectFileOpName } from '../../projectState/projectFilePolicy';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_projects/hosted_files_ts_vectors.json');

const LONG_4096 = 'a/'.repeat(2047) + 'ab';
const files = (paths: [string, boolean][]) => paths.map(([path, hidden]) => ({ path, hidden }));
const TREE = files([
	['README.md', false], ['src/a.ts', false], ['src/lib/b.ts', false], ['src/lib/deep/c.ts', false],
	['srcx/d.ts', false], ['docs/x.md', false], ['docs/sub/y.md', false], ['test/t.ts', false],
	['a/test/b/c.ts', false], ['src/ab.ts', false], ['src/é.ts', false], ['src/📁.ts', false],
	['src/secret.ts', true], ['src', false], ['docs/hidden.md', true],
]);
/** A request-validation case: the files do not matter, so none are sent. */
const v = (name: string, args: Record<string, unknown>): [string, unknown] => [name, { args, files: [], excluded: 0 }];
/** A candidate-selection case over TREE. */
const t = (name: string, args: Record<string, unknown>, excluded = 0): [string, unknown] => [name, { args: { query: 'a', ...args }, files: TREE, excluded }];

const cases: Record<ProjectFileOpName, [string, unknown][]> = {
	projectHostedPaths: [
		['valid and invalid shapes', { paths: ['src/a.ts', '', '/abs', 'C:/x', 'z:rel', 'a\\b', 'a//b', './a', 'a/../b', 'a/./b', 'a/', 'x\u0001y', 'x\u007fy', null, 42, {}, [], true] }],
		['protected names', { paths: ['.git/config', 'src/.git/x', '.gitignore', '.env', 'config/.env.local', '.envrc', '.ssh/id', 'deep/.aws/creds', '.gnupg', '.config/gcloud/x', 'home/.config/gcloud', 'x.config/gcloud/y', '.config/gcloudx'] }],
		['credential files', { paths: ['KEY.PEM', 'ID_RSA', 'id_rsa.pub', 'credentials', 'app/credentials.json', 'application_default_credentials.json', 'secret.key.txt', 'notes.keystore', 'db.kdbx', 'a.p12', 'b.PFX', 'c.Credentials', '.npmrc', 'x/.pypirc', '.netrc', '.pgpass', '.my.cnf', '.git-credentials', 'id_ed25519', 'id_dsa', 'id_ecdsa', 'café.PEM'] }],
		['unicode', { paths: ['é/ünï.txt', 'Ⅻ.md', '📁/f.txt', 'İ.env', 'ΣΑΣ.KEY', '\u3000.md'] }],
		['empty', { paths: [] }],
	],
	projectHostedList: [
		['root undefined', { files: TREE }],
		['root dot', { path: '.', files: TREE }],
		['root empty', { path: '', files: TREE }],
		['directory src', { path: 'src', files: TREE }],
		['nested directory', { path: 'src/lib', files: TREE }],
		['trailing slash invalid', { path: 'src/', files: [] }],
		['parent escape', { path: '../x', files: [] }],
		['protected directory', { path: '.ssh', files: [] }],
		['git directory', { path: '.git', files: [] }],
		['null path', { path: null, files: [] }],
		['number path', { path: 7, files: [] }],
		['no match', { path: 'nothing', files: TREE }],
	],
	projectHostedSearchPlan: [
		['defaults', { args: { query: 'needle' }, files: TREE, excluded: 3 }],
		v('files with content', { query: 'a', target: 'files', include_content: true, max_results: 7 }),
		v('content option on content', { query: 'a', target: 'content', include_content: true }),
		v('content option string', { query: 'a', target: 'files', include_content: 'true' }),
		v('content option null', { query: 'a', include_content: null }),
		v('target bogus', { query: 'a', target: 'bogus' }),
		v('target null', { query: 'a', target: null }),
		v('target number', { query: 'a', target: 1 }),
		v('regex refused', { query: 'a.*', mode: 'regex' }),
		v('mode bogus', { query: 'a', mode: 'fuzzy' }),
		v('query missing', {}),
		v('query blank', { query: '   ' }),
		v('query ideographic space', { query: '\u3000\ufeff' }),
		v('query nbsp padded', { query: '\u00a0x\u00a0' }),
		v('query control', { query: 'a\tb' }),
		v('query number', { query: 5 }),
		v('path number', { query: 'a', path: 5 }),
		v('path null defaults', { query: 'a', path: null }),
		v('path empty', { query: 'a', path: '' }),
		v('path absolute', { query: 'a', path: '/src' }),
		v('path backslash', { query: 'a', path: 'src\\lib' }),
		v('path parent', { query: 'a', path: 'src/../x' }),
		v('path dots and slashes', { query: 'a', path: './src/./lib//' }),
		v('path only dots', { query: 'a', path: './/.' }),
		v('path protected', { query: 'a', path: '.env' }),
		v('path git', { query: 'a', path: 'src/.git' }),
		v('path drive', { query: 'a', path: 'C:' }),
		v('glob null', { query: 'a', glob: null }),
		v('glob empty', { query: 'a', glob: '' }),
		v('glob negated', { query: 'a', glob: '!x' }),
		v('glob class', { query: 'a', glob: '[ab].ts' }),
		v('glob brace', { query: 'a', glob: '{a,b}' }),
		v('glob closing brace', { query: 'a', glob: 'a}' }),
		v('glob absolute', { query: 'a', glob: '/x' }),
		v('glob parent', { query: 'a', glob: 'a/../b' }),
		v('glob backslash', { query: 'a', glob: 'a\\b' }),
		v('glob control', { query: 'a', glob: 'a\nb' }),
		v('glob number', { query: 'a', glob: 3 }),
		v('limit zero', { query: 'a', max_results: 0 }),
		v('limit 101', { query: 'a', max_results: 101 }),
		v('limit 100', { query: 'a', max_results: 100 }),
		v('limit fraction', { query: 'a', max_results: 1.5 }),
		v('limit string', { query: 'a', max_results: '5' }),
		v('limit null defaults', { query: 'a', max_results: null }),
		v('limit negative', { query: 'a', max_results: -3 }),
		v('target checked before query', { target: 'x', query: 3, mode: 'y' }),
		v('mode checked before query', { mode: 'y', query: 3 }),
		v('query checked before path', { query: '', path: 5 }),
		v('path checked before glob', { query: 'a', path: '/x', glob: '!y' }),
		v('glob checked before limit', { query: 'a', glob: '!y', max_results: 0 }),
		t('path src boundary', { path: 'src' }, 1),
		t('path dots normalized', { path: './src/./lib//' }),
		t('glob src double star ts', { glob: 'src/**/*.ts' }),
		t('glob any md', { glob: '**/*.md' }),
		t('glob top md', { glob: '*.md' }),
		t('glob question', { glob: 'src/?.ts' }),
		t('glob question pair', { glob: 'src/??.ts' }),
		t('glob double star only', { glob: '**' }),
		t('glob src double star', { glob: 'src/**' }),
		t('glob test anywhere', { glob: '**/test/**' }),
		t('glob double star suffix', { glob: '**.ts' }),
		t('glob literal', { glob: 'src' }),
		t('glob star mid', { glob: 'docs/*/y.md' }),
		t('glob with path', { path: 'docs', glob: '**/*.md' }),
		t('glob many stars', { glob: '*'.repeat(40) }),
		['all hidden', { args: { query: 'a' }, files: files([['a', true], ['b', true]]), excluded: 2 }],
	],
};

function generate(): unknown {
	const ops: Record<string, unknown> = {};
	for (const [op, list] of Object.entries(cases) as [ProjectFileOpName, [string, unknown][]][]) {
		ops[op] = list.map(([name, input]) => ({ name, input: JSON.parse(JSON.stringify(input)), expected: runProjectFilePolicy(op, input) }));
	}
	return {
		generated_by: 'frontend/packages/ui/src/services/rustCore/__tests__/projectFilePolicyVectors.test.ts',
		note: 'Outcomes of the TypeScript rules in frontend/packages/ui/src/services/projectState/projectFilePolicy.ts; replayed by web_projects/hosted_files_tests.rs.',
		ops,
	};
}

describe('hosted Project file policy parity vectors', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('committed vectors equal the TypeScript rule outcomes', () => {
		expect(Object.keys(cases).sort()).toEqual(Object.keys(PROJECT_FILE_POLICY).sort());
		const generated = generate();
		const committed = existsSync(VECTORS) ? JSON.parse(readFileSync(VECTORS, 'utf8')) : null;
		if (JSON.stringify(committed) !== JSON.stringify(generated)) {
			console.log(`PROJECT_FILE_VECTORS_BEGIN${JSON.stringify(generated)}PROJECT_FILE_VECTORS_END`);
		}
		expect(committed).toEqual(generated);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('length limits count UTF-16 units (mirrored by hosted_length_limits_count_utf16_units in Rust)', () => {
		const plan = (args: Record<string, unknown>) => runProjectFilePolicy('projectHostedSearchPlan', { args, files: [], excluded: 0 }) as Record<string, unknown>;
		const searchQuery = (args: Record<string, unknown>) => (plan(args).search as { query?: string; glob?: string; path?: string } | undefined);
		expect(runProjectFilePolicy('projectHostedPaths', { paths: [LONG_4096, `${LONG_4096}b`] }))
			.toEqual({ results: [{ path: LONG_4096 }, { code: 'invalid_path' }] });
		expect(plan({ query: 'q'.repeat(2001) })).toEqual({ searchError: 'invalid_search_query' });
		expect(searchQuery({ query: 'q'.repeat(2000) })?.query).toBe('q'.repeat(2000));
		expect(searchQuery({ query: '📁'.repeat(1000) })?.query).toBe('📁'.repeat(1000));
		expect(plan({ query: '📁'.repeat(1001) })).toEqual({ searchError: 'invalid_search_query' });
		expect(searchQuery({ query: 'a', path: 'p'.repeat(2048) })?.path).toBe('p'.repeat(2048));
		expect(plan({ query: 'a', path: 'p'.repeat(2049) })).toEqual({ searchError: 'invalid_search_path' });
		expect(searchQuery({ query: 'a', glob: '*'.repeat(512) })?.glob).toBe('*'.repeat(512));
		expect(plan({ query: 'a', glob: '*'.repeat(513) })).toEqual({ searchError: 'invalid_search_glob' });
		expect(plan({ query: 'a', glob: '📁'.repeat(257) })).toEqual({ searchError: 'invalid_search_glob' });
	});
});
