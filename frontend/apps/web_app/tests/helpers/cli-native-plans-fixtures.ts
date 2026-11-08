/**
 * Shared fixtures for the cli-native-plans*.spec.ts differential specs: npm-created throwaway
 * Project/Plan fixtures, per-CLI fixtures and the documented npm-vs-native gap markers.
 * Harness: helpers/cli-native-differential.ts.
 */
/* eslint-disable @typescript-eslint/no-require-imports, @typescript-eslint/no-explicit-any */
export {};
const { expect } = require('@playwright/test');

type Side = 'npm' | 'native';
type Diff = any;

const SECTIONS = ['goal', 'scope-in', 'scope-out', 'open-questions', 'constraints', 'decisions', 'risks', 'reference-patterns', 'context'];
const VOLATILE = ['version', 'short_id'];
/** npm prints child records (assumptions, criteria, checks) as raw server ciphertext; native prints decrypted text. */
const NPM_CIPHERTEXT_GAP = '.encrypted_';
/** npm defaults a missing Task queue_state to "none"; the native Task projection keeps null. */
const QUEUE_STATE_GAP = 'queue_state: npm="none" native=null';

/** Logs the original error before `finally` cleanup can replace it with the report assertion. */
function logAbort(error: unknown): never {
	console.error('DIFFERENTIAL_ABORT', error);
	throw error;
}

async function npmJson(diff: Diff, args: string[], label: string): Promise<any> {
	const result = await diff.npm([...args, '--json'], 120_000);
	expect(result.code, `${label}: ${result.stderr}`).toBe(0);
	return JSON.parse(result.stdout);
}

/** Throwaway Project + Plan fixtures shared by one differential test. */
async function createFixtures(diff: Diff, tag: string) {
	const project = await npmJson(diff, ['projects', 'create', `Diff plans ${tag} ${Date.now()}`, '--write-policy', 'apply_and_show'], 'create project');
	const projectId: string = project.projectId ?? project.project_id ?? project.project?.project_id;
	expect(projectId).toBeTruthy();
	const planIds: string[] = [];
	// The backend refuses a second Plan with an existing title in the scope (HTTP 409): repeated titles get a counter.
	const used = new Map<string, number>();
	const plan = async (title = 'Differential plan', extra: string[] = []): Promise<string> => {
		const seen = used.get(title) ?? 0;
		used.set(title, seen + 1);
		const unique = seen === 0 ? title : `${title} ${seen + 1}`;
		const created = await npmJson(diff, ['plans', 'create', '--title', unique, '--goal', 'Differential goal', ...(extra.includes('--project') ? [] : ['--project', projectId]), ...extra], 'create plan');
		planIds.push(created.plan.plan_id);
		return created.plan.plan_id;
	};
	const cleanup = async () => {
		for (const id of planIds) await diff.npm(['plans', 'delete', id, '--confirm', '--json']);
		await diff.npm(['projects', 'delete', projectId, '--confirm', projectId, '--json']);
	};
	return { projectId, plan, cleanup };
}

/** One fresh fixture per CLI side, created in `before` and read in `argsFor`. */
function perSide<T>(make: (side: Side) => Promise<T>) {
	const values: Partial<Record<Side, T>> = {};
	return {
		before: async (side: Side) => { values[side] = await make(side); },
		get: (side: Side): T => values[side] as T
	};
}

module.exports = { NPM_CIPHERTEXT_GAP, QUEUE_STATE_GAP, SECTIONS, VOLATILE, createFixtures, logAbort, npmJson, perSide };
