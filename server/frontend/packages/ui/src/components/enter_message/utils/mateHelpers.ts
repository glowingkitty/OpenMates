// src/components/MessageInput/utils/mateHelpers.ts
import type { Editor } from "@tiptap/core";
/**
 * An array of valid mate names.
 */
export const VALID_MATES = [
    'burton',
    'lisa',
    'sophia',
    'melvin',
    'finn',
    'elton',
    'denise',
    'mark',
    'colin'
];

/**
 * Detects mate mentions in the current editor content and triggers replacement.
 * The actual replacement logic is now handled within the `MateNode` extension
 * and the editor's `onUpdate` handler.
 *
 * @param editor The TipTap editor instance.
 * @param content The current editor content as a string (not used directly here, but kept for consistency).
 */
export function detectAndReplaceMates(editor: Editor, content: string) {
    if (!editor) return;

        // Get current cursor position
        const { from } = editor.state.selection;

        // Get the text content up to the cursor
        const text = editor.state.doc.textBetween(Math.max(0, from - 1000), from);

        // Only process if content ends with space or newline
        const lastChar = text.slice(-1);
        if (lastChar !== ' ' && lastChar !== '\n') return;

        // Match @username pattern
        const mateRegex = /@(\w+)(?=\s|$)/g;  // Match @ followed by word chars
        const matches = Array.from(text.matchAll(mateRegex));
        if (!matches.length) return;

        // Get the last match
        const lastMatch = matches[matches.length - 1];
        const mateName = lastMatch[1].toLowerCase(); // Convert to lowercase for comparison

        // Only process known mates
        if (!VALID_MATES.includes(mateName)) return;

        // Calculate absolute positions
        const matchStart = from - (text.length - lastMatch.index!);
        const matchEnd = matchStart + lastMatch[0].length;

        // Check if this mention is already a mate node
        const nodeAtPos = editor.state.doc.nodeAt(matchStart);
        if (nodeAtPos?.type.name === 'mate') return;

        // Replace text with mate node
        editor
            .chain()
            .focus()
            .deleteRange({ from: matchStart, to: matchEnd })
            .insertContent([
                {
                    type: 'mate',
                    attrs: {
                        name: mateName,
                        id: crypto.randomUUID()
                    }
                },
                {
                    type: 'text',
                    text: ' '  // Add space after mention
                }
            ])
            .run();
}