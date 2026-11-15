/**
 * frontend/packages/ui/src/components/embeds/slides/slidesTemplateApply.ts
 *
 * Applies a template to a deck through the Rust core (`set_theme`, one undo step)
 * and returns the deck's new markup with the facts needed to save it as the next
 * version (slidesDeckVersion.ts). The core document is always closed again.
 */
import {
	applyDeckOperation, closeDeckDocument, deckToMarkup, openDeckDocument
} from '../../../services/rustCore/deckDocument/deckDocumentClient';
import { parseSlidesMarkup } from './slidesMarkup';
import { toCoreTheme, type TemplateOption } from './slidesTemplatePicker';
import type { EditedDeck } from './slidesDeckVersion';

/** Deck markup with `option`'s id and theme; a plain built-in clears the theme. */
export async function applyTemplateToMarkup(deckMarkup: string, option: TemplateOption): Promise<EditedDeck> {
	const parsed = parseSlidesMarkup(option.markup);
	if (!parsed.ok) throw new Error(`Template "${option.id}" does not parse: ${parsed.reason}`);
	const { handle } = await openDeckDocument(deckMarkup);
	try {
		const { view } = await applyDeckOperation(handle, {
			op: 'set_theme', template: option.id, theme: toCoreTheme(parsed.deck.theme)
		});
		const markup = await deckToMarkup(handle);
		return { markup, title: view.title, aspect: view.aspect, slideCount: view.slides.length };
	} finally {
		await closeDeckDocument(handle);
	}
}
