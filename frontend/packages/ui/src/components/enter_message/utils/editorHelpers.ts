// src/components/MessageInput/utils/editorHelpers.ts
import { Editor } from '@tiptap/core';
import type { SvelteComponent } from 'svelte';
import MarkdownIt from 'markdown-it';

// Initialize markdown-it (do this only once)
const md = new MarkdownIt({
    html: true,
    breaks: true,
    linkify: true,
    typographer: true,
});

/**
 * Checks if the editor content is empty except for a single mate mention.
 * This is used to determine if the "Send" button should be shown.
 * It's considered "empty" if it's actually empty, or contains just one mention and nothing else.
 */
export function isContentEmptyExceptMention(editor: Editor): boolean {
    if (editor.isEmpty) {
        return true;
    }

    let textContent = '';
    let mentionCount = 0;
    let otherNodeCount = 0;

    editor.state.doc.descendants((node) => {
        if (node.isText) {
            textContent += node.text;
        } else if (node.type.name === 'mate') {
            mentionCount++;
        } else if (node.type.name !== 'paragraph' && node.type.name !== 'doc') {
            otherNodeCount++;
        }
    });

    if (otherNodeCount > 0) {
        return false; // Contains embeds or other non-paragraph, non-doc nodes
    }

    if (textContent.trim().length > 0) {
        return false; // Contains actual text
    }

    // If we are here, the editor is not technically "isEmpty", but it has no text and no other nodes.
    // This means it must contain one or more mentions.
    // We consider it "empty" for sending purposes only if it contains exactly one mention.
    return mentionCount === 1;
}

/**
 * Checks if the editor has any actual content (not just whitespace or a single mention).
 */
export function hasActualContent(editor: Editor): boolean {
    if (!editor) return false;
    if (editor.isEmpty) return false;
    return !isContentEmptyExceptMention(editor);
}

/**
 * Returns the default initial content for the editor.
 */
export function getInitialContent() {
    return {
        type: 'doc',
        content: [{
            type: 'paragraph',
            content: []
        }]
    };
}

/**
 * Mounts a Svelte component to a given DOM element.
 */
export function mountComponent(
    Component: new (options: { target: HTMLElement; props: any }) => SvelteComponent,
    target: HTMLElement,
    props: Record<string, any>
): SvelteComponent {
    return new Component({
        target,
        props
    });
}


/**
 * Converts plain text to Markdown.
 */
export function convertToMarkdown(text: string): string {
    return md.render(text);
}

/**
 * Inserts a CodeEmbed node into the editor with the given text and language.
 * @param editor - The TipTap editor instance.  <-- Corrected: Added editor
 */
export function insertCodeContent(text: string, language: string, editor: Editor) { // Corrected signature
 if (!editor) return;

    const codeEmbed = {
        type: 'codeEmbed',
        attrs: {
            language: language,
            content: text, // Store the raw text content as an attribute
            id: crypto.randomUUID()
        }
    };

    if (editor.isEmpty) {
        editor.commands.setContent({
            type: 'doc',
            content: [{
                type: 'paragraph',
                content: [
                    codeEmbed,
                ]
            }]
        });
    } else {
        editor.commands.insertContent([
            codeEmbed,
            { type: 'text', text: ' ' }
        ]);
    }
    setTimeout(() => {
        editor.commands.focus('end');
    }, 50);
}

/**
 * Inserts a large TextEmbed in the editor
  * @param editor - The TipTap editor instance.  <-- Corrected: Added editor
 */
export function insertTextContent(text: string, editor: Editor) { // Corrected signature
    if (!editor) return;

    const textEmbed = {
        type: 'textEmbed',
        attrs: {
            content: text,
            id: crypto.randomUUID(),
        },
    };

    if (editor.isEmpty) {
        editor.commands.setContent({
            type: 'doc',
            content: [{
                type: 'paragraph',
                content: [
                    textEmbed,
                ],
            }],
        });
    } else {
        editor.commands.insertContent([
            textEmbed,
            { type: 'text', text: ' ' },
        ]);
    }
    setTimeout(() => {
        editor.commands.focus('end');
    }, 50);
}

/**
 * Determines if a given text string should be treated as a large text embed.
 * @param text The text to check.
 * @returns True if the text is considered "large", false otherwise.
 */
export function isLargeText(text: string): boolean {
    // You can customize this logic based on your needs.  Here are some options:
    // - Character count:
    //   return text.length > 500;
    // - Number of lines:
    //   return text.split('\n').length > 5;
    // - Combination of both:
    return text.length > 500 || text.split('\n').length > 5;
    // - Presence of multiple paragraphs (more complex, might require looking for double newlines)
}
