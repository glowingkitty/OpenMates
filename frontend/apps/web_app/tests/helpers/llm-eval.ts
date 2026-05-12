/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Reusable LLM-backed evaluation helpers for Playwright specs.
 *
 * These helpers call the authenticated OpenMates AI Ask endpoint from the
 * browser session, so specs can judge qualitative response properties without
 * embedding brittle text assertions. A deterministic fallback is kept for
 * infrastructure failures so tests still produce actionable diagnostics.
 */

export {};

const { expect } = require('@playwright/test');

const FOLLOW_UP_PATTERN = /\b(would you like|do you want|should i|shall i|want me to|i can also|next,? you (?:could|can)|you could also ask|let me know if|if you'd like|if you want)\b/i;

type FollowUpEvaluation = {
	passes: boolean;
	reason: string;
	source: 'llm' | 'heuristic';
	raw?: string;
};

function parseEvaluatorJson(raw: string): { has_follow_up_suggestion: boolean; reason: string } | null {
	const match = raw.match(/\{[\s\S]*\}/);
	if (!match) return null;
	try {
		const parsed = JSON.parse(match[0]);
		if (typeof parsed.has_follow_up_suggestion === 'boolean' && typeof parsed.reason === 'string') {
			return parsed;
		}
	} catch {
		return null;
	}
	return null;
}

function heuristicNoFollowUpEvaluation(responseText: string, error?: unknown): FollowUpEvaluation {
	const hasSuggestion = FOLLOW_UP_PATTERN.test(responseText);
	return {
		passes: !hasSuggestion,
		reason: hasSuggestion
			? 'Heuristic detected a proactive follow-up phrase in the assistant response.'
			: `LLM evaluator unavailable; heuristic found no proactive follow-up phrase.${error ? ` Error: ${String(error)}` : ''}`,
		source: 'heuristic'
	};
}

async function evaluateNoFollowUpSuggestions(
	page: any,
	responseText: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = () => {},
): Promise<FollowUpEvaluation> {
	const trimmedResponse = responseText.trim();
	if (!trimmedResponse) {
		return { passes: false, reason: 'Assistant response was empty.', source: 'heuristic' };
	}

	try {
		const evaluation = await page.evaluate(async (assistantResponse: string) => {
			const prompt = [
				'You are evaluating whether an assistant response violates a user preference.',
				'The user disabled follow-up suggestions.',
				'Return JSON only with: {"has_follow_up_suggestion": boolean, "reason": string}.',
				'Count as a violation: ending with optional next-step questions, suggested prompts, or offers like "Would you like me to...".',
				'Do not count as a violation: necessary clarification questions, concise limitations, or normal explanatory text.',
				'',
				'Assistant response:',
				assistantResponse,
			].join('\n');

			const res = await fetch('/v1/apps/ai/skills/ask', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
				credentials: 'include',
				body: JSON.stringify({
					model: 'mistral/mistral-small-2506',
					stream: false,
					is_incognito: true,
					messages: [
						{ role: 'user', content: prompt }
					],
					apps_enabled: false,
					temperature: 0,
				}),
			});

			if (!res.ok) {
				throw new Error(`Evaluator request failed with ${res.status}: ${await res.text()}`);
			}

			const json = await res.json();
			return json?.choices?.[0]?.message?.content ?? '';
		}, trimmedResponse);

		const parsed = parseEvaluatorJson(evaluation);
		if (!parsed) {
			throw new Error(`Evaluator returned non-JSON content: ${evaluation}`);
		}

		logCheckpoint('LLM follow-up evaluator completed.', parsed);
		return {
			passes: !parsed.has_follow_up_suggestion,
			reason: parsed.reason,
			source: 'llm',
			raw: evaluation,
		};
	} catch (error) {
		const fallback = heuristicNoFollowUpEvaluation(trimmedResponse, error);
		logCheckpoint('LLM follow-up evaluator fell back to heuristic.', fallback);
		return fallback;
	}
}

async function expectNoFollowUpSuggestions(
	page: any,
	responseText: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = () => {},
): Promise<FollowUpEvaluation> {
	const evaluation = await evaluateNoFollowUpSuggestions(page, responseText, logCheckpoint);
	expect(evaluation.passes, evaluation.reason).toBe(true);
	return evaluation;
}

module.exports = {
	evaluateNoFollowUpSuggestions,
	expectNoFollowUpSuggestions,
};
