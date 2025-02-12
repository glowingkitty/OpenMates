// src/components/MessageInput/extensions/embeds/ImageEmbed.ts
import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../../utils/editorHelpers';
import Photos from '../../in_message_previews/Photos.svelte'; // Import your Svelte component
import type { SvelteComponent } from 'svelte';

export interface ImageOptions {
    src: string;
    originalFile?: File;
    filename: string;
    id: string;
    isRecording?: boolean;
}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        imageEmbed: {
            setImageEmbed: (options: {
                src: string;
                originalFile?: File;
                filename: string;
                id: string;
                isRecording?: boolean
            }) => ReturnType
        }
    }
}

export const ImageEmbed = Node.create<ImageOptions>({
    name: 'imageEmbed',
    group: 'inline',
    inline: true,
    selectable: true,
    draggable: true,

    addAttributes() {
        return {
            src: {
                default: null,
            },
            originalFile: {
                default: null,
            },
            filename: {
                default: null,
            },
            id: {
                default: () => crypto.randomUUID(),
            },
            isRecording: {
                default: false,
            },
        };
    },

     parseHTML() {
        return [
            {
                tag: 'div[data-image-embed]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-image-embed': true })];
    },

    addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-image-embed', 'true');

            let component: SvelteComponent | null = null;
            component = mountComponent(Photos, dom, {
                src: node.attrs.src,
                filename: node.attrs.filename,
                id: node.attrs.id,
                isRecording: node.attrs.isRecording,
            });

            return {
                dom,
                update: (updatedNode) => {
                    if (updatedNode.type !== this.type) {
                        return false;
                    }

                    component?.$set({
                        src: updatedNode.attrs.src,
                        filename: updatedNode.attrs.filename,
                        id: updatedNode.attrs.id,
                        isRecording: updatedNode.attrs.isRecording
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
            setImageEmbed: options => ({ commands }) => {
                return commands.insertContent({
                    type: this.name,
                    attrs: options,
                })
            }
        }
    }
});