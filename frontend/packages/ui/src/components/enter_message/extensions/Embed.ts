// Unified Embed extension for the new message parsing architecture
// Replaces individual embed extensions with a single, type-agnostic embed node

import { Node, mergeAttributes } from '@tiptap/core';
import { EmbedNodeAttributes, EmbedType } from '../../../message_parsing/types';

export interface EmbedOptions {
  // Configuration options for the unified embed extension
  inline?: boolean;
  group?: string;
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    embed: {
      setEmbed: (attributes: EmbedNodeAttributes) => ReturnType;
      updateEmbed: (id: string, attributes: Partial<EmbedNodeAttributes>) => ReturnType;
      removeEmbed: (id: string) => ReturnType;
    }
  }
}

/**
 * Unified Embed extension that handles all embed types through a single node
 * Uses the new unified embed node attributes defined in the architecture
 */
export const Embed = Node.create<EmbedOptions>({
  name: 'embed',
  group: 'block',
  inline: false,
  selectable: true,
  draggable: true,
  isolating: true,

  addOptions() {
    return {
      inline: false,
      group: 'block',
    };
  },

  addAttributes() {
    return {
      // Core unified attributes per the new architecture
      id: {
        default: null,
        parseHTML: element => element.getAttribute('data-id'),
        renderHTML: attributes => {
          if (!attributes.id) {
            return {};
          }
          return { 'data-id': attributes.id };
        },
      },
      type: {
        default: 'text',
        parseHTML: element => element.getAttribute('data-type'),
        renderHTML: attributes => {
          if (!attributes.type) {
            return {};
          }
          return { 'data-type': attributes.type };
        },
      },
      status: {
        default: 'finished',
        parseHTML: element => element.getAttribute('data-status'),
        renderHTML: attributes => {
          if (!attributes.status) {
            return {};
          }
          return { 'data-status': attributes.status };
        },
      },
      contentRef: {
        default: null,
        parseHTML: element => element.getAttribute('data-content-ref'),
        renderHTML: attributes => {
          if (!attributes.contentRef) {
            return {};
          }
          return { 'data-content-ref': attributes.contentRef };
        },
      },
      contentHash: {
        default: null,
        parseHTML: element => element.getAttribute('data-content-hash'),
        renderHTML: attributes => {
          if (!attributes.contentHash) {
            return {};
          }
          return { 'data-content-hash': attributes.contentHash };
        },
      },
      // Optional metadata attributes
      language: {
        default: null,
        parseHTML: element => element.getAttribute('data-language'),
        renderHTML: attributes => {
          if (!attributes.language) {
            return {};
          }
          return { 'data-language': attributes.language };
        },
      },
      filename: {
        default: null,
        parseHTML: element => element.getAttribute('data-filename'),
        renderHTML: attributes => {
          if (!attributes.filename) {
            return {};
          }
          return { 'data-filename': attributes.filename };
        },
      },
      title: {
        default: null,
        parseHTML: element => element.getAttribute('data-title'),
        renderHTML: attributes => {
          if (!attributes.title) {
            return {};
          }
          return { 'data-title': attributes.title };
        },
      },
      url: {
        default: null,
        parseHTML: element => element.getAttribute('data-url'),
        renderHTML: attributes => {
          if (!attributes.url) {
            return {};
          }
          return { 'data-url': attributes.url };
        },
      },
      // Count metadata
      lineCount: {
        default: null,
        parseHTML: element => {
          const value = element.getAttribute('data-line-count');
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: attributes => {
          if (!attributes.lineCount) {
            return {};
          }
          return { 'data-line-count': attributes.lineCount.toString() };
        },
      },
      wordCount: {
        default: null,
        parseHTML: element => {
          const value = element.getAttribute('data-word-count');
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: attributes => {
          if (!attributes.wordCount) {
            return {};
          }
          return { 'data-word-count': attributes.wordCount.toString() };
        },
      },
      cellCount: {
        default: null,
        parseHTML: element => {
          const value = element.getAttribute('data-cell-count');
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: attributes => {
          if (!attributes.cellCount) {
            return {};
          }
          return { 'data-cell-count': attributes.cellCount.toString() };
        },
      },
      rows: {
        default: null,
        parseHTML: element => {
          const value = element.getAttribute('data-rows');
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: attributes => {
          if (!attributes.rows) {
            return {};
          }
          return { 'data-rows': attributes.rows.toString() };
        },
      },
      cols: {
        default: null,
        parseHTML: element => {
          const value = element.getAttribute('data-cols');
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: attributes => {
          if (!attributes.cols) {
            return {};
          }
          return { 'data-cols': attributes.cols.toString() };
        },
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'div[data-embed-unified="true"]',
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    const attrs = mergeAttributes(HTMLAttributes, {
      'data-embed-unified': 'true',
      class: `embed-unified embed-${HTMLAttributes['data-type'] || 'text'} embed-status-${HTMLAttributes['data-status'] || 'finished'}`,
    });

    return ['div', attrs];
  },

  addNodeView() {
    return ({ node, getPos, editor }) => {
      const attrs = node.attrs as EmbedNodeAttributes;
      
      // Create container element
      const container = document.createElement('div');
      container.classList.add('embed-unified-container');
      container.setAttribute('data-embed-type', attrs.type);
      container.setAttribute('data-embed-status', attrs.status);
      
      // Add processing/finished visual indicators
      if (attrs.status === 'processing') {
        container.classList.add('embed-processing');
      } else {
        container.classList.add('embed-finished');
      }

      // Create a placeholder content element
      const content = document.createElement('div');
      content.classList.add('embed-content');
      
      // Add type-specific styling and preview content
      switch (attrs.type) {
        case 'code':
          content.innerHTML = `
            <div class="embed-header">
              <span class="embed-icon">📄</span>
              <span class="embed-title">${attrs.filename || 'Code'}</span>
              ${attrs.language ? `<span class="embed-language">${attrs.language}</span>` : ''}
              ${attrs.lineCount ? `<span class="embed-meta">${attrs.lineCount} lines</span>` : ''}
            </div>
            <div class="embed-preview">Code content will be loaded from contentRef: ${attrs.contentRef}</div>
          `;
          break;
        
        case 'doc':
          content.innerHTML = `
            <div class="embed-header">
              <span class="embed-icon">📝</span>
              <span class="embed-title">${attrs.title || 'Document'}</span>
              ${attrs.wordCount ? `<span class="embed-meta">${attrs.wordCount} words</span>` : ''}
            </div>
            <div class="embed-preview">Document content will be loaded from contentRef: ${attrs.contentRef}</div>
          `;
          break;
        
        case 'sheet':
          content.innerHTML = `
            <div class="embed-header">
              <span class="embed-icon">📊</span>
              <span class="embed-title">${attrs.title || 'Spreadsheet'}</span>
              ${attrs.rows && attrs.cols ? `<span class="embed-meta">${attrs.rows}×${attrs.cols}</span>` : ''}
            </div>
            <div class="embed-preview">Table data will be loaded from contentRef: ${attrs.contentRef}</div>
          `;
          break;
        
        case 'video':
          content.innerHTML = `
            <div class="embed-header">
              <span class="embed-icon">🎥</span>
              <span class="embed-title">Video</span>
            </div>
            <div class="embed-preview">
              ${attrs.url ? `<a href="${attrs.url}" target="_blank">${attrs.url}</a>` : 'Video preview will be loaded'}
            </div>
          `;
          break;
        
        case 'web':
          content.innerHTML = `
            <div class="embed-header">
              <span class="embed-icon">🌐</span>
              <span class="embed-title">Web Link</span>
            </div>
            <div class="embed-preview">
              ${attrs.url ? `<a href="${attrs.url}" target="_blank">${attrs.url}</a>` : 'Web preview will be loaded'}
            </div>
          `;
          break;
        
        default:
          content.innerHTML = `
            <div class="embed-header">
              <span class="embed-icon">📎</span>
              <span class="embed-title">${attrs.type} Embed</span>
            </div>
            <div class="embed-preview">Content will be loaded from contentRef: ${attrs.contentRef}</div>
          `;
      }
      
      container.appendChild(content);
      
      // Make the node selectable and add basic interaction
      container.addEventListener('click', () => {
        if (typeof getPos === 'function') {
          const pos = getPos();
          editor.commands.setNodeSelection(pos);
        }
      });
      
      return {
        dom: container,
        update: (updatedNode) => {
          // Update the node view when attributes change
          if (updatedNode.type.name !== 'embed') return false;
          
          const newAttrs = updatedNode.attrs as EmbedNodeAttributes;
          container.setAttribute('data-embed-type', newAttrs.type);
          container.setAttribute('data-embed-status', newAttrs.status);
          
          // Update classes
          container.className = 'embed-unified-container';
          if (newAttrs.status === 'processing') {
            container.classList.add('embed-processing');
          } else {
            container.classList.add('embed-finished');
          }
          
          return true;
        },
        destroy: () => {
          // Cleanup if needed
        },
      };
    };
  },

  addCommands() {
    return {
      setEmbed:
        (attributes: EmbedNodeAttributes) =>
        ({ commands }) => {
          return commands.insertContent({
            type: this.name,
            attrs: attributes,
          });
        },
      
      updateEmbed:
        (id: string, attributes: Partial<EmbedNodeAttributes>) =>
        ({ tr, state }) => {
          const { doc } = state;
          let updated = false;

          doc.descendants((node, pos) => {
            if (node.type.name === this.name && node.attrs.id === id) {
              const newAttrs = { ...node.attrs, ...attributes };
              tr.setNodeMarkup(pos, undefined, newAttrs);
              updated = true;
              return false; // Stop traversal
            }
          });

          return updated;
        },
      
      removeEmbed:
        (id: string) =>
        ({ tr, state }) => {
          const { doc } = state;
          let removed = false;

          doc.descendants((node, pos) => {
            if (node.type.name === this.name && node.attrs.id === id) {
              tr.delete(pos, pos + node.nodeSize);
              removed = true;
              return false; // Stop traversal
            }
          });

          return removed;
        },
    };
  },
});
