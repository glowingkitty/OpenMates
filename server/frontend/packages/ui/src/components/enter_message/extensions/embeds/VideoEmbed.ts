// src/components/MessageInput/extensions/embeds/VideoEmbed.ts
import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../../utils/editorHelpers';
import Videos from '../../in_message_previews/Videos.svelte'; // Import your Svelte component
import type { SvelteComponent } from 'svelte';

export interface VideoOptions {}

declare module '@tiptap/core' {
    interface Commands<ReturnType> {
        videoEmbed: {
            setVideoEmbed: (options: { src: string; filename: string; id: string; duration?: string; isRecording?: boolean; thumbnailUrl?: string; isYouTube?: boolean; videoId?: string; }) => ReturnType
        }
    }
}

export const VideoEmbed = Node.create<VideoOptions>({
    name: 'videoEmbed',
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
            isRecording: {
                default: false,
            },
            thumbnailUrl: {
                default: null,
            },
            isYouTube: {
                default: false,
            },
            videoId: {
                default: null,
            },
        };
    },

    parseHTML() {
        return [
            {
                tag: 'div[data-video-embed]',
            },
        ];
    },

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-video-embed': true })];
    },

    addNodeView() {
        return ({ node, HTMLAttributes, getPos, editor }) => {
            const dom = document.createElement('div');
            dom.setAttribute('data-video-embed', 'true');

            let component: SvelteComponent | null = null;
            component = mountComponent(Videos, dom, {
                src: node.attrs.src,
                filename: node.attrs.filename,
                id: node.attrs.id,
                duration: node.attrs.duration || '00:00',
                isRecording: node.attrs.isRecording,
                thumbnailUrl: node.attrs.thumbnailUrl,
                isYouTube: node.attrs.isYouTube,
                videoId: node.attrs.videoId
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
                        duration: updatedNode.attrs.duration,
                        isRecording: updatedNode.attrs.isRecording,
                        thumbnailUrl: updatedNode.attrs.thumbnailUrl,
                        isYouTube: updatedNode.attrs.isYouTube,
                        videoId: updatedNode.attrs.videoId,
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
            setVideoEmbed: options => ({ commands }) => {
                return commands.insertContent({
                    type: this.name,
                    attrs: options,
                })
            }
        }
    }
});