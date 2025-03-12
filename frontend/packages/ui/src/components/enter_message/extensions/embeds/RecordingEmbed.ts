// src/components/MessageInput/extensions/embeds/RecordingEmbed.ts
import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../../utils/editorHelpers';
import Audio from '../../in_message_previews/Audio.svelte';
import type { SvelteComponent } from 'svelte';

export interface RecordingOptions {}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        recordingEmbed: {
            setRecordingEmbed: (options: { src: string; filename: string; id: string; duration?: string }) => ReturnType;
        };
    }
}

export const RecordingEmbed = Node.create<RecordingOptions>({
    name: 'recordingEmbed',
    group: 'inline',
    inline: true,
    selectable: true,
    draggable: true,

    addAttributes() {
        return {
            src: {
                default: null,
            },
            filename: {
                default: null,
            },
            id: {
                default: () => crypto.randomUUID(),
            },
            duration: {
                default: '00:00',
            },
        };
    },

    parseHTML() {
        return [
            {
                tag: 'div[data-recording-embed]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-recording-embed': true })];
    },

     addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-recording-embed', 'true');

            let component: SvelteComponent | null = null;

            // Use mountComponent to mount the Svelte component
            component = mountComponent(Audio, dom, {
                src: node.attrs.src,
                filename: node.attrs.filename,
                id: node.attrs.id,
                duration: node.attrs.duration || '00:00',
                type: 'recording' //always a recording
            });

            return {
                dom,
                update: (updatedNode) => {
                    if (updatedNode.type !== this.type) {
                        return false;
                    }
                    // Update props of the mounted Svelte component
                    component?.$set({
                        src: updatedNode.attrs.src,
                        filename: updatedNode.attrs.filename,
                        id: updatedNode.attrs.id,
                        duration: updatedNode.attrs.duration,
                        type: 'recording'
                    });
                    return true;

                },
                destroy: () => {
                    component?.$destroy();
                    component = null;
                }
            };
        };
    },
    addCommands() {
        return {
            setRecordingEmbed: (options) => ({ commands }) => {
                return commands.insertContent({
                    type: this.name,
                    attrs: options,
                });
            },
        };
    },
});