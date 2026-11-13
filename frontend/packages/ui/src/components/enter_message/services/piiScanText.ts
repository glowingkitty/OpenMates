/**
 * Text the composer's live sensitive-data preview scans.
 *
 * Mention chips (Projects, skills, models, mates, memories) are app-provided
 * references, not text the user wrote, and the send path serializes them to
 * opaque ids (`@project:<id>:<mode>`), never their labels. Their labels must
 * therefore not be scanned: a Project called "Budget 2026 0151 2345" would
 * otherwise be flagged as a phone number in the preview.
 *
 * Each mention atom becomes one U+FFFC (object replacement) character. That
 * keeps the scanned text aligned with ProseMirror positions, where an atom is
 * one position wide, so preview highlights after a chip land on the right
 * characters. U+FFFC is neither a digit, a letter nor whitespace, so digits on
 * both sides of a chip are not joined into one number.
 */
import type { Editor } from '@tiptap/core';

export const MENTION_SCAN_PLACEHOLDER = '￼';

const MENTION_NODE_NAMES = new Set(['mate', 'aiModelMention', 'bestModelMention', 'genericMention']);

export function piiScanText(editor: Editor): string {
	const textSerializers: Record<string, () => string> = {};
	for (const name of Object.keys(editor.schema.nodes)) {
		if (MENTION_NODE_NAMES.has(name)) textSerializers[name] = () => MENTION_SCAN_PLACEHOLDER;
	}
	return editor.getText({ textSerializers });
}
