// src/components/MessageInput/extensions/Placeholder.ts
import Placeholder from '@tiptap/extension-placeholder';
import { isContentEmptyExceptMention } from '../utils/editorHelpers';
import type { Editor } from '@tiptap/core';
import type { PlaceholderOptions } from '@tiptap/extension-placeholder';
import { get } from 'svelte/store';
import { writable } from 'svelte/store';
import { text } from '@repo/ui'; // Use text store from @repo/ui for reactive translations

export const messageInputPlaceholderOverride = writable<string | null>(null);

/** When set to 'followup', uses the followup_desktop/followup_touch i18n keys instead of the default placeholder. */
export const messageInputPlaceholderVariant = writable<'default' | 'followup'>('default');

// Helper function to detect touch device
const isTouchDevice = () => {
    return (('ontouchstart' in window) ||
            (navigator.maxTouchPoints > 0) ||
            // @ts-expect-error -- msMaxTouchPoints is a non-standard MS property
            (navigator.msMaxTouchPoints > 0));
};

export const CustomPlaceholder = Placeholder.extend<PlaceholderOptions>({
    addOptions() {
        return {
            ...this.parent?.(),
            placeholder: ({ editor }: { editor: Editor }) => {
                // Only show placeholder when empty or just has mention and not focused
                if ((editor.isEmpty || isContentEmptyExceptMention(editor)) && !editor.isFocused) {
                    const override = get(messageInputPlaceholderOverride);
                    if (override) {
                        return override;
                    }

                    // Get appropriate translation based on device type and variant
                    const variant = get(messageInputPlaceholderVariant);
                    const suffix = variant === 'followup' ? 'followup_' : '';
                    const deviceType = isTouchDevice() ? 'touch' : 'desktop';
                    const key = `enter_message.placeholder.${suffix}${deviceType}`;
                    // Get the current value from the text store (reactive to language changes)
                    const translateFn = get(text);
                    return translateFn(key);
                }
                return '';
            },
            emptyEditorClass: 'is-editor-empty',
            showOnlyWhenEditable: false,
        } as PlaceholderOptions;
    },

    // Subscribe to variant + override stores so the placeholder text updates
    // reactively even when the editor state hasn't changed (e.g., switching
    // from an example chat to the welcome screen without re-mounting the editor).
    onCreate() {
        const editor = this.editor;
        const forceUpdate = () => {
            if (!editor.isDestroyed) {
                editor.view.dispatch(editor.state.tr);
            }
        };
        const unsub1 = messageInputPlaceholderVariant.subscribe(forceUpdate);
        const unsub2 = messageInputPlaceholderOverride.subscribe(forceUpdate);
        // Store unsubscribe functions for cleanup
        (editor as Editor & { _placeholderUnsubs?: (() => void)[] })._placeholderUnsubs = [unsub1, unsub2];
    },

    onDestroy() {
        const editor = this.editor as Editor & { _placeholderUnsubs?: (() => void)[] };
        editor._placeholderUnsubs?.forEach(fn => fn());
        delete editor._placeholderUnsubs;
    },
});
