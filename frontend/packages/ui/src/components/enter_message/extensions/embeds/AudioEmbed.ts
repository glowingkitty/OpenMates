// src/components/MessageInput/extensions/embeds/AudioEmbed.ts
import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../../utils/editorHelpers';
import Audio from '../../in_message_previews/Audio.svelte';
import type { SvelteComponent } from 'svelte';

export interface AudioOptions {
    // Add any custom options for your audio embed here
}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        audioEmbed: {
            /**
             * Add an audio embed
             */
            setAudioEmbed: (options: { src: string; filename: string; id: string; duration?: string; type?: string }) => ReturnType;
        };
    }
}

export const AudioEmbed = Node.create<AudioOptions>({
    name: 'audioEmbed',
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
            type: { //allows for specifying 'audio' or 'recording'.
                default: 'audio'
            }
        };
    },

    parseHTML() {
        return [
            {
                tag: 'div[data-audio-embed]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-audio-embed': true })];
    },

    addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-audio-embed', 'true');

            let component: SvelteComponent | null = null;

            // Use mountComponent to mount the Svelte component
            component = mountComponent(Audio, dom, {
                src: node.attrs.src,
                filename: node.attrs.filename,
                id: node.attrs.id,
                duration: node.attrs.duration || '00:00',
                type: node.attrs.type
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
                        type: updatedNode.attrs.type
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
            setAudioEmbed: (options) => ({ commands }) => {
                return commands.insertContent({
                    type: this.name,
                    attrs: options,
                });
            },
        };
    },
});