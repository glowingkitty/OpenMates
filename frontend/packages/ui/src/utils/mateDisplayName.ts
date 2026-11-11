/**
 * Display name of the mate behind a message or indicator category.
 *
 * Only categories listed in `matesMetadata` have a `mates.<id>` text. Any other
 * value (missing, retired, or sent by another client version) is shown as
 * OpenMates, so a raw "[T:mates.<id>]" placeholder never reaches the page.
 */
import { getMatesById } from '../data/matesMetadata';

type Translate = (key: string) => string;

/** Product name shown when no mate is known for a category. Not translated. */
export const OPENMATES_DISPLAY_NAME = 'OpenMates';

const matesById = getMatesById();

/** The category when it names a mate with a translated display name, else null. */
export function knownMateCategory(category: string | null | undefined): string | null {
	return category && Object.hasOwn(matesById, category) ? category : null;
}

/** Translated mate name for a category, or the product name when the category names no mate. */
export function mateDisplayName(category: string | null | undefined, t: Translate): string {
	const known = knownMateCategory(category);
	return known ? t(`mates.${known}`) : OPENMATES_DISPLAY_NAME;
}
