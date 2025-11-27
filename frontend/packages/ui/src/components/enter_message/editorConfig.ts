// frontend/packages/ui/src/components/enter_message/editorConfig.ts
import StarterKit from '@tiptap/starter-kit';
import { CustomPlaceholder } from './extensions/Placeholder';
import { MateNode } from './extensions/MateNode';
// Legacy embed nodes no longer needed with unified architecture
// import * as EmbedNodes from "./extensions/embeds";
import { Embed } from './extensions/Embed'; // Import unified Embed extension
import { createKeyboardHandlingExtension } from './handlers/sendHandlers';

export function getEditorExtensions() {
    // Note: We no longer set a static placeholder here.
    // The CustomPlaceholder extension uses the reactive text store from @repo/ui
    // which automatically updates when language changes.
    // This ensures the placeholder text is always in the current language.

    return [
        StarterKit.configure({
            hardBreak: { keepMarks: true, HTMLAttributes: {} },
            // In write mode we only highlight markdown tokens and do NOT render formatting
            // Disable all markdown-rendering marks/nodes so characters like **, ### remain as plain text
            bold: false,
            italic: false,
            strike: false,
            code: false,
            heading: false,
            blockquote: false,
            bulletList: false,
            orderedList: false,
            listItem: false,
            horizontalRule: false,
            // Explicitly disable the default CodeBlock
            codeBlock: false,
        }),
        Embed, // Use unified Embed extension
        MateNode,
        // CustomPlaceholder uses reactive text store, no need to override with static text
        CustomPlaceholder,
        createKeyboardHandlingExtension()
    ];
}
