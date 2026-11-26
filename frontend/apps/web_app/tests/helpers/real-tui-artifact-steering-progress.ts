import { mkdirSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

export const RECIPE_PHASES = [
	'started', 'prerequisites_passed', 'build_started', 'build_ready', 'pairing_started', 'pairing_offer_ready',
	'browser_pin_ready', 'pairing_pin_submitted', 'pairing_completed', 'initial_history_read', 'terminal_started',
	'composer_ready', 'original_sent', 'original_streaming', 'original_card_visible', 'red_sent', 'red_step_completed',
	'font_sent', 'font_preview_visible', 'one_chat', 'all_three_user_turns', 'mercury_replies', 'one_matching_card',
	'latest_source_read', 'latest_header_red', 'latest_font_lexend', 'latest_source_verified', 'previous_source_read',
	'previous_source_verified', 'terminal_exit_verified', 'input_plan_verified', 'revised_source_visible', 'passed',
] as const;

type RecipePhase = typeof RECIPE_PHASES[number];
const allowed = new Set<RecipePhase>(RECIPE_PHASES);

export function recordRecipeProgress(file: string): (phase: RecipePhase) => void {
	const started = performance.now();
	const phases: Partial<Record<RecipePhase, number>> = { started: 0 };
	const persist = () => {
		try {
			mkdirSync(dirname(file), { recursive: true, mode: 0o700 });
			const temporary = file + '.tmp';
			writeFileSync(temporary, JSON.stringify({ schemaVersion: 1, phases }) + '\n', { mode: 0o600 });
			renameSync(temporary, file);
		} catch {
			// Keep the last complete receipt. A diagnostic write never changes a proof assertion.
		}
	};
	persist();
	return (phase: RecipePhase) => {
		if (!allowed.has(phase) || Object.hasOwn(phases, phase)) return;
		phases[phase] = Math.max(0, Math.min(3_600_000, Math.round(performance.now() - started)));
		persist();
	};
}
