// Continue-carousel `continueDecide` parity vectors (chatState unit).
// The committed packages/openmates-rust/src/web_continue_ts_vectors.json is regenerated
// here from the real flag-off continueCarouselService.ts (getReminderByTargetChatId,
// sortContinuePriorityItems) through the same input builders the flag-on page path
// sends; web_continue_tests.rs replays the file through the Rust ops. Regenerate:
//   CONTINUE_VECTORS_WRITE=1 npx vitest run src/services/rustCore/__tests__/continueCarouselVectors.test.ts
// spec: specifications/features/continue-carousel#continue-carousel.chat.reminder-gated
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import {
	getReminderByTargetChatId,
	sortContinuePriorityItems,
	type ActiveReminderForContinue,
	type ContinuePriority,
	type ContinuePriorityReason,
} from '../../continueCarouselService';
import { reminderByChatInput, sortPrioritiesInput } from '../../continueCarouselRust';
import { createContinueCarouselHandlers } from '../chatState/continueCarouselOps';
import { UnitRefusal } from '../host/unitPort';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_continue_ts_vectors.json');
type Json = Record<string, unknown>;

const NOW_MS = 1_778_662_800_123;
const NOW_S = Math.floor(NOW_MS / 1000);
const MIN = 60;
const HOUR = 60 * MIN;

// `status` 'none' leaves the field absent (a default parameter would replace undefined).
function r(id: string, offsetSeconds: number | null, chat: unknown, status = 'pending'): ActiveReminderForContinue {
	return {
		reminder_id: id,
		prompt_preview: 'placeholder prompt',
		trigger_at: offsetSeconds === null ? (null as unknown as number) : NOW_S + offsetSeconds,
		target_type: 'existing_chat',
		target_chat_id: chat as string | null,
		target_embed_id: null,
		status: (status === 'none' ? undefined : status) as string,
	};
}

const REMINDER_CASES: Array<[string, ActiveReminderForContinue[], number]> = [
	['empty', [], NOW_MS],
	['due and soon labels', [
		r('a', -30, 'chat-a'), r('b', 30, 'chat-b'), r('c', 89, 'chat-c'), r('d', -90, 'chat-d'),
		r('e', 59 * MIN + 31, 'chat-e'), r('f', 3 * HOUR + 1799, 'chat-f'), r('g', 23 * HOUR + 59 * MIN, 'chat-g'),
		r('h', -11 * HOUR, 'chat-h', 'fired'), r('i', 0, 'chat-i'),
	], NOW_MS],
	['windows and status', [
		r('far', 24 * HOUR + 1, 'chat-far'), r('edge', 24 * HOUR, 'chat-edge'),
		r('old-fired', -12 * HOUR - 1, 'chat-old'), r('old-pending', -40 * HOUR, 'chat-oldp'),
		r('old-no-status', -13 * HOUR, 'chat-nos', 'none'), r('recent-fired', -12 * HOUR, 'chat-rf', 'fired'),
		r('null-trigger', null, 'chat-null'), r('zero', -NOW_S, 'chat-zero'), r('negative', -NOW_S - 5, 'chat-neg'),
	], NOW_MS],
	['targets', [
		r('no-chat', 60, null), r('blank', 60, '   '), r('number', 60, 42), r('padded', 120, '  chat-p  '),
		r('padded-dup', 60, 'chat-p'), r('bom', 60, '﻿chat-bom'), r('undefined', 60, undefined),
	], NOW_MS],
	['best per chat and first-seen order', [
		r('later', 4 * HOUR, 'chat-a'), r('other', 2 * HOUR, 'chat-b'), r('soon', 30 * MIN, 'chat-a'),
		r('due-beats-soon', -5 * HOUR, 'chat-b'), r('closer-due', -MIN, 'chat-b'), r('tie-first', 600, 'chat-c'),
		r('tie-second', 600, 'chat-c'), r('mirror', -600, 'chat-c'), r('soon-loses', 5, 'chat-b'),
	], NOW_MS],
	['day labels', [
		r('d1', -11 * HOUR - 59 * MIN, 'chat-1', 'fired'), r('d2', -36 * HOUR, 'chat-2'), r('d3', -30 * 24 * HOUR, 'chat-3'),
	], NOW_MS],
	['second-aligned now', [r('x', 90, 'chat-x'), r('y', -150, 'chat-y')], NOW_S * 1000],
];

function p(reason: ContinuePriorityReason, offsetMs: number): ContinuePriority {
	return { reason, label: 'ignored', timestamp: NOW_MS + offsetMs };
}

const SORT_CASES: Array<[string, ContinuePriority[]]> = [
	['empty', []],
	['rank order', [p('upcoming_saved_item', 10), p('ongoing_saved_item', 5), p('reminder_soon', 100), p('reminder_due', -100)]],
	['distance within rank', [p('reminder_due', -5000), p('reminder_due', -10), p('reminder_due', 0), p('reminder_due', -999)]],
	['stable ties', [p('reminder_soon', 600), p('upcoming_saved_item', -600), p('reminder_soon', -600), p('upcoming_saved_item', 600), p('reminder_soon', 600)]],
	['mixed', [
		p('ongoing_saved_item', 7 * 3_600_000), p('reminder_soon', 20 * 3_600_000), p('upcoming_saved_item', -3_600_000),
		p('reminder_due', -11 * 3_600_000), p('ongoing_saved_item', 3_600_000), p('upcoming_saved_item', 1), p('reminder_due', -1),
	]],
];

function buildVectors(): Json {
	const reminderByChat = REMINDER_CASES.map(([name, reminders, nowMs]) => {
		const map = getReminderByTargetChatId(reminders, nowMs);
		const entries = Array.from(map.entries()).map(([chatId, { reminder, priority }]) => ({
			chatId, reminderIndex: reminders.indexOf(reminder), priority,
		}));
		return { name, input: reminderByChatInput(reminders, nowMs), expected: { entries } };
	});
	const sortPriorities = SORT_CASES.map(([name, priorities]) => {
		const items = priorities.map((priority, index) => ({ priority, index }));
		const order = sortContinuePriorityItems(items, NOW_MS).map((item) => item.index);
		return { name, input: sortPrioritiesInput(items, NOW_MS), expected: { order } };
	});
	return { ops: { reminderByChat, sortPriorities } };
}

describe('continue-carousel parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=continue-carousel.chat.reminder-gated
	it('the flag-off continueCarouselService reproduces every committed vector', () => {
		const fresh = JSON.parse(JSON.stringify(buildVectors()));
		if (process.env.CONTINUE_VECTORS_WRITE === '1') writeFileSync(VECTORS, `${JSON.stringify(fresh, null, 1)}\n`);
		const committed = existsSync(VECTORS) ? JSON.parse(readFileSync(VECTORS, 'utf8')) : null;
		// Hosts that cannot write the file (isolated CI) get the regenerated document in the log.
		if (JSON.stringify(fresh) !== JSON.stringify(committed)) console.log(`CONTINUE_VECTORS_FRESH_BEGIN\n${JSON.stringify(fresh)}\nCONTINUE_VECTORS_FRESH_END`);
		expect(fresh).toEqual(committed);
	});
});

describe('chatState continueDecide op', () => {
	// contract-test: supporting surface=gui.web assertions=continue-carousel.chat.reminder-gated
	it('forwards op and JSON input to the Rust export and refuses with protocol on failure', () => {
		const calls: unknown[][] = [];
		const handlers = createContinueCarouselHandlers({
			chat_state_continue_decide: (op: string, input: string) => {
				calls.push([op, input]);
				if (op === 'boom') throw new Error('unknown_op:boom');
				return JSON.stringify({ order: [0] });
			},
		});
		const decide = handlers.continueDecide as (payload: unknown) => unknown;
		expect(decide({ op: 'sortPriorities', input: { priorities: [], nowMs: 1 } })).toEqual({ order: [0] });
		expect(calls[0]).toEqual(['sortPriorities', '{"priorities":[],"nowMs":1}']);
		expect(() => decide({ op: 'boom', input: {} })).toThrow(UnitRefusal);
		expect(() => decide({ input: {} })).toThrow(UnitRefusal);
		const unbound = createContinueCarouselHandlers({}).continueDecide as (payload: unknown) => unknown;
		expect(() => unbound({ op: 'sortPriorities', input: {} })).toThrow(UnitRefusal);
	});
});
