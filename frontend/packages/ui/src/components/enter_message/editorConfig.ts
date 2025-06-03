// frontend/packages/ui/src/components/enter_message/editorConfig.ts
import StarterKit from '@tiptap/starter-kit';
import { CustomPlaceholder } from './extensions/Placeholder';
import { MateNode } from './extensions/MateNode';
import * as EmbedNodes from "./extensions/embeds"; // WebEmbed is now part of this
import { createKeyboardHandlingExtension } from './handlers/sendHandlers';
import { text } from '@repo/ui'; // Import the text store
import { get } from 'svelte/store'; // Import get for accessing store value
import { json } from 'svelte-i18n'; // Import the json function

export function getEditorExtensions() {
    // Determine if it's a touch device
    const isTouchDevice = typeof window !== 'undefined' && (('ontouchstart' in window) || navigator.maxTouchPoints > 0);

    // Get the placeholder object using json()
    const placeholderObject = get(json)('enter_message.placeholder') as { desktop?: { text: string }, touch?: { text: string } } | undefined;

    // Select the appropriate placeholder text
    let placeholderText = 'Send message...'; // Default fallback
    if (placeholderObject) {
        if (isTouchDevice && placeholderObject.touch?.text) {
            placeholderText = placeholderObject.touch.text;
        } else if (!isTouchDevice && placeholderObject.desktop?.text) {
            placeholderText = placeholderObject.desktop.text;
        } else if (placeholderObject.desktop?.text) { // Fallback to desktop if specific one not found but desktop exists
            placeholderText = placeholderObject.desktop.text;
        }
    }


    return [
        StarterKit.configure({
            hardBreak: { keepMarks: true, HTMLAttributes: {} },
            // Disable features not used
            codeBlock: false, // Explicitly disable the default CodeBlock
        }),
        ...Object.values(EmbedNodes),
        MateNode,
        CustomPlaceholder.configure({
            placeholder: () => placeholderText,
        }),
        createKeyboardHandlingExtension()
    ];
}
