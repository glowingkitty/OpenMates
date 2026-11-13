/**
 * Shared body of the cli-native-plans-sections-*.spec.ts differential specs: the text sections of a Plan
 * (goal, scope-in, ...) with every action, npm CLI against the native Rust binary.
 * The CI spec command times out after 20 minutes, so the nine sections are split over two specs.
 * Harness: helpers/cli-native-differential.ts.
 */
/* eslint-disable @typescript-eslint/no-require-imports, @typescript-eslint/no-explicit-any */
export {};
import type { TestInfo } from '@playwright/test';

const { finishDifferential, setupDifferential } = require('./cli-native-differential');
const { VOLATILE, createFixtures, logAbort, npmJson } = require('./cli-native-plans-fixtures');

/** Runs set/edit/update, add/answer/supersede and clear/remove for each given section on a throwaway Plan. */
async function runSectionChecks(page: any, testInfo: TestInfo, group: string, sections: string[]): Promise<void> {
	const diff = await setupDifferential(page, testInfo, group, { paceMs: 4_000 });
	const fx = await createFixtures(diff, group);
	try {
		const base = await fx.plan('Differential section plan');
		for (const section of sections) {
			const reset = async () => { await npmJson(diff, ['plans', section, 'set', base, '--text', 'Base text'], `reset ${section}`); };
			for (const action of ['set', 'edit', 'update']) {
				await diff.check(`plans ${section} ${action}`, ['plans', section, action, base, '--text', `New ${section}`], { ignoreKeys: VOLATILE, catalog: [`plans ${section} ${action}`] });
			}
			for (const action of ['add', 'answer', 'supersede']) {
				await diff.check(`plans ${section} ${action}`, ['plans', section, action, base, '--text', `More ${section}`], { before: reset, ignoreKeys: VOLATILE, catalog: [`plans ${section} ${action}`] });
			}
			for (const action of ['clear', 'remove']) {
				await diff.check(`plans ${section} ${action}`, ['plans', section, action, base], { before: reset, ignoreKeys: VOLATILE, catalog: [`plans ${section} ${action}`] });
			}
		}
	} catch (error) {
		logAbort(error);
	} finally {
		await fx.cleanup();
		await finishDifferential(diff);
	}
}

module.exports = { runSectionChecks };
