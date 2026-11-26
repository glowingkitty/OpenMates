import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { recordRecipeProgress } from './real-tui-artifact-steering-progress';
import { parseInputProgress } from './rust-cli-terminal';

// contract-test-file: infrastructure
test('the receipt exists initially and retains only first elapsed times for reviewed phases', () => {
	const directory = mkdtempSync(join(tmpdir(), 'recipe-progress-'));
	try {
		const file = join(directory, 'real-tui-artifact-steering-progress.json');
		const mark = recordRecipeProgress(file);
		const read = () => JSON.parse(readFileSync(file, 'utf8'));
		assert.deepEqual(read(), { schemaVersion: 1, phases: { started: 0 } });
		mark('build_started');
		mark('red_sent');
		const partial = read();
		assert.deepEqual(Object.keys(partial.phases), ['started', 'build_started', 'red_sent']);
		assert.ok(Object.values(partial.phases).every(value => typeof value === 'number'
			&& Number.isInteger(value) && value >= 0 && value <= 3_600_000));
		mark('red_sent');
		mark('unreviewed fixture text and identifier' as Parameters<typeof mark>[0]);
		assert.deepEqual(read(), partial);
	} finally {
		rmSync(directory, { recursive: true, force: true });
	}
});

test('the private recorder pipe accepts only indexed checkpoints and an exact requested card', () => {
	const steps = [{ name: 'plain' }, { name: 'original-card', capture_code_card: true }];
	assert.deepEqual(parseInputProgress('[1,true,"emb-v-1"]', steps), { index: 1, completed: true, card: 'emb-v-1' });
	assert.deepEqual(parseInputProgress('[0,false,null]', steps), { index: 0, completed: false });
	for (const data of ['[0,true,"emb-v-1"]', '[1,false,"emb-v-1"]', '[1,true,"PRIVATE"]', '[1,true,"ab12cdef"]',
		'[1,true,"emb-v-01"]', '[2,true,null]', '[1,0,null]', '[1,true,"emb-v-1","EXTRA"]', '{"index":1}', 'non-JSON']) {
		assert.equal(parseInputProgress(data, steps), undefined);
	}
});
