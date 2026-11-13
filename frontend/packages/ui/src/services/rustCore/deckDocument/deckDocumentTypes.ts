/**
 * Wire types of the core-owned deck replica (types only, no behaviour).
 *
 * 1:1 mirror of the serde shapes in packages/openmates-rust/src/client/shared_items/
 * (deck.rs `DeckView`, deck_markup.rs `SlideModel`/`ElementModel`/`ElementContent`,
 * deck_operations.rs `DeckOperation`/`DeckOutcome`/`TextStyle`/`ElementSpec`,
 * deck_values.rs `DeckAspect`/`ElementKind`, deck_error.rs / deck_handles.rs codes).
 * Field names stay snake_case because they are the Rust JSON. Rust `Option` fields
 * serialise as `null`. The committed deck_wire_fixture.json pins these shapes on both
 * sides (deck_handles_tests.rs and __tests__/deckDocumentWire.test.ts).
 * Spec: specifications/features/live-collaboration (live-collab.core.one-shared-model).
 */

export type DeckAspect = '16:9' | '16:10' | '4:3';

export type DeckElementKind = 'text' | 'image' | 'video' | 'shape' | 'notepad' | 'todo' | 'link' | 'block';

export interface DeckTodoItem {
	text: string;
	done: boolean;
}

/** Element body by kind (`{"type":...,"value":...}`; `empty` has no value). */
export type DeckElementContent =
	| { type: 'empty' }
	| { type: 'plain'; value: string }
	| { type: 'rich_text'; value: string }
	| { type: 'label'; value: string }
	| { type: 'items'; value: DeckTodoItem[] }
	| { type: 'verbatim'; value: string };

export interface DeckElementModel {
	id: string;
	kind: DeckElementKind;
	x: number | null;
	y: number | null;
	w: number | null;
	h: number | null;
	/** Every other validated attribute (`role`, `font`, `src`, `animate`, `hidden`, ...). */
	attributes: Record<string, string>;
	content: DeckElementContent;
}

export interface DeckSlideModel {
	id: string;
	layout: string | null;
	transition: string | null;
	notes: string;
	elements: DeckElementModel[];
}

/** Render model of a deck: everything an editor draws, plus undo state. */
export interface DeckView {
	title: string;
	aspect: DeckAspect;
	template: string;
	canvas_width: number;
	canvas_height: number;
	slides: DeckSlideModel[];
	can_undo: boolean;
	can_redo: boolean;
}

/** Text style change; omitted (or null) fields stay as they are. */
export interface DeckTextStyle {
	font?: string | null;
	size?: number | null;
	color?: string | null;
	align?: string | null;
	weight?: string | null;
	remove?: string[];
}

/** A new element for `add_element`. */
export interface DeckElementSpec {
	kind: DeckElementKind;
	x?: number | null;
	y?: number | null;
	w?: number | null;
	h?: number | null;
	attributes?: Record<string, string>;
	content: DeckElementContent;
}

/** One typed change; the only way an editor changes a deck replica. */
export type DeckOperation =
	| { op: 'set_text_content'; slide_id: string; element_id: string; markup: string }
	| { op: 'set_text_style'; slide_id: string; element_id: string; style: DeckTextStyle }
	| { op: 'set_geometry'; slide_id: string; element_id: string; x: number; y: number; w: number; h: number }
	| { op: 'set_image_source'; slide_id: string; element_id: string; src: string; alt: string | null }
	| { op: 'add_element'; slide_id: string; index: number | null; element: DeckElementSpec }
	| { op: 'delete_element'; slide_id: string; element_id: string }
	| { op: 'duplicate_element'; slide_id: string; element_id: string }
	/** Paint order (z-order): the last element of a slide is drawn on top. */
	| { op: 'move_element'; slide_id: string; element_id: string; to_index: number }
	| { op: 'add_slide'; index: number | null; layout: string | null }
	| { op: 'duplicate_slide'; slide_id: string }
	| { op: 'delete_slide'; slide_id: string }
	| { op: 'move_slide'; slide_id: string; to_index: number }
	| { op: 'set_slide_layout'; slide_id: string; layout: string | null }
	| { op: 'set_speaker_notes'; slide_id: string; notes: string }
	| { op: 'set_notepad_text'; slide_id: string; element_id: string; text: string }
	| { op: 'set_todo_items'; slide_id: string; element_id: string; items: DeckTodoItem[] }
	| { op: 'set_todo_item_done'; slide_id: string; element_id: string; index: number; done: boolean }
	| { op: 'clear_interactive_element'; slide_id: string; element_id: string }
	| { op: 'clear_all_interactive' }
	| { op: 'set_interactive_hidden'; slide_id: string; element_id: string; hidden: boolean }
	| { op: 'set_all_interactive_hidden'; hidden: boolean };

export type DeckOperationName = DeckOperation['op'];

/** What an applied operation did. */
export type DeckOutcome =
	| { outcome: 'applied' }
	| { outcome: 'unchanged' }
	| { outcome: 'slide_created'; slide_id: string }
	| { outcome: 'element_created'; element_id: string }
	| { outcome: 'cleared'; elements: number };

/** Stable refusal codes of the deck unit (core `DeckError::code` and `DeckHandleError::code`). */
export type DeckErrorCode =
	| 'slides_markup_not_normalised'
	| 'slides_deck_has_no_slide'
	| 'slides_slide_not_found'
	| 'slides_element_not_found'
	| 'slides_wrong_element_kind'
	| 'slides_unknown_attribute'
	| 'slides_invalid_value'
	| 'slides_limit_reached'
	| 'slides_last_slide'
	| 'slides_item_out_of_range'
	| 'shared_item_invalid_update'
	| 'shared_item_unknown_handle'
	| 'slides_invalid_operation';
