/** PREVIEW-ONLY in-memory deck model for SlidesLivePair (the real deck is the core's). */
import type { DeckOperation, DeckView } from '../../../services/rustCore/deckDocument/deckDocumentTypes';

const text = (id: string, x: number, y: number, w: number, h: number, value: string, role: string) => ({
	id, kind: 'text' as const, x, y, w, h, attributes: { role }, content: { type: 'rich_text' as const, value },
});

export const previewDeck: DeckView = {
	title: 'Team update', aspect: '16:9', template: 'plain', kind: 'deck', theme: null,
	canvas_width: 1920, canvas_height: 1080, can_undo: false, can_redo: false,
	slides: [
		{ id: 's1', layout: null, transition: null, notes: '', elements: [text('e1', 160, 160, 1200, 200, 'Quarterly update', 'title'), text('e2', 160, 420, 1200, 160, 'What changed and what is next', 'body')] },
		{ id: 's2', layout: null, transition: null, notes: '', elements: [text('e3', 160, 120, 1200, 160, 'Highlights', 'title'), text('e4', 160, 360, 1200, 300, 'Faster sync, shared sheets', 'body')] },
	],
};

let counter = 0;
export function applyPreviewDeckOp(view: DeckView, raw: unknown): DeckView {
	const wrapped = raw as { op?: string; operation?: DeckOperation };
	const op = wrapped.operation;
	if (wrapped.op !== 'deck' || !op) return view;
	const slides = view.slides.map((s) => ({ ...s, elements: s.elements.map((e) => ({ ...e })) }));
	const slide = 'slide_id' in op ? slides.find((s) => s.id === op.slide_id) : undefined;
	if (op.op === 'set_geometry' && slide) {
		const el = slide.elements.find((e) => e.id === op.element_id);
		if (el) Object.assign(el, { x: op.x, y: op.y, w: op.w, h: op.h });
	} else if (op.op === 'set_text_content' && slide) {
		const el = slide.elements.find((e) => e.id === op.element_id);
		if (el) el.content = { type: 'rich_text', value: op.markup };
	} else if (op.op === 'delete_element' && slide) {
		slide.elements = slide.elements.filter((e) => e.id !== op.element_id);
	} else if (op.op === 'add_slide') {
		slides.push({ id: `sn${++counter}`, layout: null, transition: null, notes: '', elements: [] });
	}
	return { ...view, slides };
}
