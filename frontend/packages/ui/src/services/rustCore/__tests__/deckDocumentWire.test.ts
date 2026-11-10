// contract-test-file: tooling
// spec: specifications/features/live-collaboration#live-collab.core.one-shared-model
// Drift guard between the Rust deck serde shapes and deckDocumentTypes.ts. The committed
// fixture (packages/openmates-rust/src/client/shared_items/deck_wire_fixture.json) is
// regenerated and asserted by deck_handles_tests.rs; here the typed exemplars must equal
// it (a Rust shape change fails this test) and are type-checked against the TS types (a
// TS-only change fails tsc), and the view's keys and enum values must match the types.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type {
	DeckAspect, DeckElementContent, DeckElementKind, DeckElementModel, DeckErrorCode, DeckOperation, DeckOperationName,
	DeckOutcome, DeckSlideModel, DeckView,
} from '../deckDocument/deckDocumentTypes';

const fixture = JSON.parse(readFileSync(resolve(__dirname, '../../../../../../../packages/openmates-rust/src/client/shared_items/deck_wire_fixture.json'), 'utf8'));

/** Every key of `T`, checked complete at compile time by the `Record<keyof T, true>` shape. */
function keys<T>(record: Record<keyof T, true>): string[] {
	return Object.keys(record).sort();
}

const VIEW_KEYS = keys<DeckView>({ title: true, aspect: true, template: true, canvas_width: true, canvas_height: true, slides: true, can_undo: true, can_redo: true });
const SLIDE_KEYS = keys<DeckSlideModel>({ id: true, layout: true, transition: true, notes: true, elements: true });
const ELEMENT_KEYS = keys<DeckElementModel>({ id: true, kind: true, x: true, y: true, w: true, h: true, attributes: true, content: true });
const ASPECTS: Record<DeckAspect, true> = { '16:9': true, '16:10': true, '4:3': true };
const KINDS: Record<DeckElementKind, true> = { text: true, image: true, video: true, shape: true, notepad: true, todo: true, link: true, block: true };
const CONTENT_TYPES: Record<DeckElementContent['type'], true> = { empty: true, plain: true, rich_text: true, label: true, items: true, verbatim: true };
const OPERATION_NAMES: Record<DeckOperationName, true> = {
	set_text_content: true, set_text_style: true, set_geometry: true, set_image_source: true, add_element: true, delete_element: true,
	duplicate_element: true, move_element: true, add_slide: true, duplicate_slide: true, delete_slide: true, move_slide: true, set_slide_layout: true,
	set_speaker_notes: true, set_notepad_text: true, set_todo_items: true, set_todo_item_done: true, clear_interactive_element: true,
	clear_all_interactive: true, set_interactive_hidden: true, set_all_interactive_hidden: true,
};
const ERROR_CODES: Record<DeckErrorCode, true> = {
	slides_markup_not_normalised: true, slides_deck_has_no_slide: true, slides_slide_not_found: true, slides_element_not_found: true,
	slides_wrong_element_kind: true, slides_unknown_attribute: true, slides_invalid_value: true, slides_limit_reached: true,
	slides_last_slide: true, slides_item_out_of_range: true, shared_item_invalid_update: true, shared_item_unknown_handle: true,
	slides_invalid_operation: true,
};

// Same order and values as `operations()` in deck_handles_tests.rs.
const OPERATIONS: DeckOperation[] = [
	{ op: 'set_text_content', slide_id: 's1', element_id: 'e1', markup: '<b>x</b>' },
	{ op: 'set_text_style', slide_id: 's1', element_id: 'e1', style: { font: 'heading', size: 32, color: '#112233', align: 'center', weight: 'bold', remove: ['role'] } },
	{ op: 'set_geometry', slide_id: 's1', element_id: 'e1', x: 1, y: 2, w: 3, h: 4 },
	{ op: 'set_image_source', slide_id: 's1', element_id: 'e1', src: 'embed:a', alt: null },
	{
		op: 'add_element', slide_id: 's1', index: 0,
		element: { kind: 'text', x: 10, y: null, w: 400, h: null, attributes: { role: 'body' }, content: { type: 'rich_text', value: 'Hi' } },
	},
	{ op: 'delete_element', slide_id: 's1', element_id: 'e1' },
	{ op: 'duplicate_element', slide_id: 's1', element_id: 'e1' },
	{ op: 'move_element', slide_id: 's1', element_id: 'e1', to_index: 1 },
	{ op: 'add_slide', index: null, layout: 'title' },
	{ op: 'duplicate_slide', slide_id: 's1' },
	{ op: 'delete_slide', slide_id: 's1' },
	{ op: 'move_slide', slide_id: 's1', to_index: 2 },
	{ op: 'set_slide_layout', slide_id: 's1', layout: null },
	{ op: 'set_speaker_notes', slide_id: 's1', notes: 'Notes' },
	{ op: 'set_notepad_text', slide_id: 's1', element_id: 'e1', text: 'Idea' },
	{ op: 'set_todo_items', slide_id: 's1', element_id: 'e1', items: [{ text: 'Do', done: false }] },
	{ op: 'set_todo_item_done', slide_id: 's1', element_id: 'e1', index: 0, done: true },
	{ op: 'clear_interactive_element', slide_id: 's1', element_id: 'e1' },
	{ op: 'clear_all_interactive' },
	{ op: 'set_interactive_hidden', slide_id: 's1', element_id: 'e1', hidden: true },
	{ op: 'set_all_interactive_hidden', hidden: false },
];

const OUTCOMES: DeckOutcome[] = [
	{ outcome: 'applied' },
	{ outcome: 'unchanged' },
	{ outcome: 'slide_created', slide_id: 's3' },
	{ outcome: 'element_created', element_id: 'e9' },
	{ outcome: 'cleared', elements: 2 },
];

describe('deck wire fixture', () => {
	// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model
	it('operations and outcomes equal the Rust serde JSON', () => {
		expect(fixture.operations).toEqual(OPERATIONS);
		expect(fixture.operation_names).toEqual(OPERATIONS.map((operation) => operation.op));
		expect([...fixture.operation_names].sort()).toEqual(Object.keys(OPERATION_NAMES).sort());
		expect(fixture.outcomes).toEqual(OUTCOMES);
		expect([...fixture.error_codes].sort()).toEqual(Object.keys(ERROR_CODES).sort());
	});

	// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model
	it('the view has exactly the DeckView keys and enum values', () => {
		const view = fixture.view;
		expect(Object.keys(view).sort()).toEqual(VIEW_KEYS);
		expect(Object.hasOwn(ASPECTS, view.aspect)).toBe(true);
		const kinds = new Set<string>();
		const contentTypes = new Set<string>();
		for (const slide of view.slides) {
			expect(Object.keys(slide).sort()).toEqual(SLIDE_KEYS);
			for (const element of slide.elements) {
				expect(Object.keys(element).sort()).toEqual(ELEMENT_KEYS);
				kinds.add(element.kind);
				contentTypes.add(element.content.type);
				expect(Object.keys(element.content).sort()).toEqual(element.content.type === 'empty' ? ['type'] : ['type', 'value']);
			}
		}
		// The fixture deck uses every element kind and content type, so both sets are exhaustive.
		expect([...kinds].sort()).toEqual(Object.keys(KINDS).sort());
		expect([...contentTypes].sort()).toEqual(Object.keys(CONTENT_TYPES).sort());
	});
});
