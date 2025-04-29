// frontend/packages/ui/src/components/enter_message/editorConfig.ts
import StarterKit from '@tiptap/starter-kit';
import { CustomPlaceholder } from './extensions/Placeholder';
import { WebPreview } from './extensions/WebPreview';
import { MateNode } from './extensions/MateNode';
import * as EmbedNodes from "./extensions/embeds";
import { createKeyboardHandlingExtension } from './handlers/sendHandlers';
import { text } from '@repo/ui'; // Import the text store
import { get } from 'svelte/store'; // Import get for accessing store value

export function getEditorExtensions() {
    return [
        StarterKit.configure({
            hardBreak: { keepMarks: true, HTMLAttributes: {} },
            // Disable features not used
        }),
        ...Object.values(EmbedNodes),
        WebPreview,
        MateNode,
        CustomPlaceholder.configure({
            // Access store value using get() in .ts files
            placeholder: () => get(text)('enter_message.placeholder') || 'Send message...',
        }),
        createKeyboardHandlingExtension()
    ];
}