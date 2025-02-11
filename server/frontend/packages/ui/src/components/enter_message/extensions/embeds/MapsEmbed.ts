// src/components/MessageInput/extensions/embeds/MapsEmbed.ts
import { Node, mergeAttributes } from '@tiptap/core';
import { mountComponent } from '../../utils/editorHelpers';
import Maps from '../../in_message_previews/Maps.svelte'; // Import your Svelte component
import type { SvelteComponent } from 'svelte';

export interface MapsOptions {}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    mapsEmbed: {
      setMapsEmbed: (options: { 
        lat: number; 
        lon: number; 
        zoom: number; 
        name: string;
        id: string 
      }) => ReturnType;
    };
  }
}

export const MapsEmbed = Node.create<MapsOptions>({
  name: 'mapsEmbed',
  group: 'inline',
  inline: true,
  selectable: true,
  draggable: true,

  addAttributes() {
    return {
      lat: {
        default: null,
      },
      lon: {
        default: null,
      },
      zoom: {
        default: 16,
      },
      name: {
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
        tag: 'div[data-maps-embed]',
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    return ['div', mergeAttributes(HTMLAttributes, { 'data-maps-embed': true })];
  },

  addNodeView() {
    return ({ node, HTMLAttributes, getPos, editor }) => {
      const dom = document.createElement('div');
      dom.setAttribute('data-maps-embed', 'true');

      let component: SvelteComponent | null = null;
      component = mountComponent(Maps, dom, {
        lat: node.attrs.lat,
        lon: node.attrs.lon,
        zoom: node.attrs.zoom,
        name: node.attrs.name,
        id: node.attrs.id
      });

      return {
        dom,
        destroy: () => {
          component?.$destroy();
        }
      };
    };
  },
  addCommands() {
    return {
      setMapsEmbed: options => ({ commands }) => {
        return commands.insertContent({
          type: this.name,
          attrs: options,
        })
      }
    }
  }
});
