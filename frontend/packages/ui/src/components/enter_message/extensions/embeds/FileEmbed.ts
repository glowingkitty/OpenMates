// src/components/MessageInput/extensions/embeds/FileEmbed.ts
import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../../utils/editorHelpers';
import FilePreview from '../../in_message_previews/File.svelte'; // Import your Svelte component
import type { SvelteComponent } from 'svelte';

export interface FileOptions {}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        fileEmbed: {
            setFileEmbed: (options: {src: string; filename: string; id: string}) => ReturnType
        }
    }
}

export const FileEmbed = Node.create<FileOptions>({
    name: 'fileEmbed',
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
        };
    },

     parseHTML() {
        return [
            {
                tag: 'div[data-file-embed]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-file-embed': true })];
    },

    addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-file-embed', 'true');

            let component: SvelteComponent | null = null;
            component = mountComponent(FilePreview, dom, {
                src: node.attrs.src,
                filename: node.attrs.filename,
                id: node.attrs.id,
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
            setFileEmbed: options => ({ commands }) => {
                return commands.insertContent({
                    type: this.name,
                    attrs: options,
                })
            }
        }
    }
});