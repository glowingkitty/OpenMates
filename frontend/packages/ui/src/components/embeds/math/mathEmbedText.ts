/**
 * Text-only renderers for math embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str } from '../../../data/embedTextRenderers';

/** app:math:calculate */
export function renderMathCalculate(c: Record<string, unknown>): string {
	const results = c.results as Array<Record<string, unknown>> | undefined;
	const lines: string[] = ['**Math**'];
	if (Array.isArray(results)) {
		for (const r of results) {
			const expr = str(r.expression) ?? str(r.input) ?? '';
			const result = str(r.result) ?? str(r.output) ?? '';
			if (expr && result) lines.push(`${expr} = ${result}`);
			else if (result) lines.push(result);
		}
	}
	return lines.join('\n');
}

/** math-plot — mathematical plot */
export function renderMathPlot(): string {
	return '**Math Plot**\n[mathematical plot]';
}
