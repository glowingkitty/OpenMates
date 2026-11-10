import { describe, it, expect } from 'vitest';
import { renderEmbedAsText } from '../embedTextRenderers';
import { FOX_RESULT } from '../../components/embeds/design/embroideryFixtures';
import { readEmbroideryDesign, formatDuration, formatSize, noteTranslationKey } from '../../components/embeds/design/embroideryDesign';

describe('design.embroidery text and content reading', () => {
	// contract-test: supporting surface=gui.web assertions=design-embroidery.surface.semantic-parity
	it('lists files, numbers, threads and notes as text', () => {
		const text = renderEmbedAsText('design-embroidery', {
			...FOX_RESULT,
			files: { dst: { s3_key: 'a' }, pes: { s3_key: 'b' }, exp: { s3_key: 'c' }, jef: { s3_key: 'd' }, vp3: { s3_key: 'e' } },
		});
		expect(text).toContain('**Fox**');
		expect(text).toContain('size: 90 x 74 mm');
		expect(text).toContain('stitches: 12840');
		expect(text).toContain('thread changes: 3');
		expect(text).toContain('fits hoop 130 x 180 mm');
		expect(text).toContain('files: DST, PES, EXP, JEF, VP3');
		expect(text).toContain('thread 1: Madeira 1135 (8120 stitches)');
		expect(text).toContain('note: Background left out');
	});

	// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
	it('shows the reason of a failed result and no numbers', () => {
		const text = renderEmbedAsText('design-embroidery', { status: 'error', title: 'Fox', error: 'too many stitches' });
		expect(text).toContain('failed: too many stitches');
		expect(text).not.toContain('stitches:');
	});

	// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
	it('reads untrusted content defensively', () => {
		const design = readEmbroideryDesign({ status: 'weird', hoop: 'x', threads: [{ colour_hex: 'javascript:1', stitch_count: 'a' }], width_mm: '9' });
		expect(design.status).toBe('finished');
		expect(design.hoop).toBe('none');
		expect(design.threads[0].colourHex).toBe('');
		expect(design.widthMm).toBeNull();
		expect(formatSize(design)).toBe('');
		expect(formatDuration(47)).toBe('47 min');
		expect(formatDuration(65)).toBe('1 h 5 min');
	});

	// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
	it('carries the note count and the legacy nonce, and translates only known note codes', () => {
		const design = readEmbroideryDesign({
			aes_nonce: 'bm9uY2U=',
			notes: [{ code: 'tiny_details_removed', text: '3 detail(s) too small to sew left out', count: 3 }, { code: 'scaled', text: 'x' }],
		});
		expect(design.aesNonce).toBe('bm9uY2U=');
		expect(design.notes[0]).toEqual({ code: 'tiny_details_removed', text: '3 detail(s) too small to sew left out', count: 3 });
		expect(design.notes[1].count).toBeNull();
		expect(noteTranslationKey('tiny_details_removed')).toBe('embeds.design.embroidery.note.tiny_details_removed');
		expect(noteTranslationKey('unsolved_live_text')).toBe('embeds.design.embroidery.note.unsolved_live_text');
		expect(noteTranslationKey('scaled')).toBeNull();
	});
});
