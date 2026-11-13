import { describe, expect, it, vi } from 'vitest';
import { knownMateCategory, mateDisplayName } from '../mateDisplayName';
import { matesMetadata } from '../../data/matesMetadata';
import { localizeIndicatorLine } from '../../components/chats/utils/chatIndicatorLines';

describe('mateDisplayName', () => {
	// contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selected-mate-identity
	it('translates every known mate category', () => {
		const t = vi.fn((key: string) => `<${key}>`);
		for (const mate of matesMetadata) {
			expect(knownMateCategory(mate.id)).toBe(mate.id);
			expect(mateDisplayName(mate.id, t)).toBe(`<mates.${mate.id}>`);
		}
	});

	// contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selected-mate-identity
	it('never asks for a text key of a category that names no mate', () => {
		const t = vi.fn((key: string) => `[T:${key}]`);
		for (const category of ['ai', 'openmates_official', 'toString', '', null, undefined]) {
			expect(knownMateCategory(category)).toBeNull();
			expect(mateDisplayName(category, t)).toBe('OpenMates');
		}
		expect(t).not.toHaveBeenCalled();
	});

	// contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selected-mate-identity
	it('keeps an unknown category out of the typing indicator line', () => {
		const t = (key: string) => (key === 'enter_message.is_typing' ? '{mate} is typing...' : `[T:${key}]`);
		expect(localizeIndicatorLine({ k: 'mate', category: 'ai', thinking: false }, t)).toBe('OpenMates is typing...');
	});
});
