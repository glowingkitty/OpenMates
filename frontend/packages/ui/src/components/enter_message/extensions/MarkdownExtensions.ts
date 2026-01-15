// Markdown Extensions for TipTap
import { Extension } from '@tiptap/core';
import { Table } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableHeader } from '@tiptap/extension-table-header';
import { TableCell } from '@tiptap/extension-table-cell';
import { Mathematics } from '@tiptap/extension-mathematics';
import { Highlight } from '@tiptap/extension-highlight';
import { Link } from '@tiptap/extension-link';
import { Strike } from '@tiptap/extension-strike';
import { Underline } from '@tiptap/extension-underline';
import { Plugin, PluginKey } from '@tiptap/pm/state';

// Configure Table extension with custom options
export const MarkdownTable = Table.configure({
  resizable: true,
  HTMLAttributes: {
    class: 'markdown-table',
  },
});

export const MarkdownTableRow = TableRow.configure({
  HTMLAttributes: {
    class: 'markdown-table-row',
  },
});

export const MarkdownTableHeader = TableHeader.configure({
  HTMLAttributes: {
    class: 'markdown-table-header',
  },
});

export const MarkdownTableCell = TableCell.configure({
  HTMLAttributes: {
    class: 'markdown-table-cell',
  },
});

// Configure Mathematics extension for LaTeX formulas
export const MarkdownMathematics = Mathematics.configure({
  katexOptions: {
    throwOnError: false,
    displayMode: false,
  },
});

// Configure additional text formatting extensions
export const MarkdownHighlight = Highlight.configure({
  HTMLAttributes: {
    class: 'markdown-highlight',
  },
});

/**
 * Enhanced MarkdownLink extension that handles internal vs external links
 * - Internal links (hash-based #chat-id= or /#chat-id=): Same tab navigation via hash routing
 * - External links: Open in new tab (default behavior)
 */
export const MarkdownLink = Link.extend({
  // NOTE: We intentionally do NOT override the name here.
  // The parser outputs { type: 'link', ... } so we must use the default 'link' name
  // for TipTap to recognize and render the marks correctly.
  
  addAttributes() {
    const parentAttrs = this.parent?.() || {};
    // Remove target from parent attributes - we'll handle it ourselves
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { target, ...parentAttrsWithoutTarget } = parentAttrs as Record<string, unknown>;
    
    return {
      ...parentAttrsWithoutTarget,
      href: {
        default: null,
        parseHTML: element => element.getAttribute('href'),
        renderHTML: attributes => {
          if (!attributes.href) {
            return {};
          }
          
          // Check if this is an internal link (hash-based chat-id link)
          // Supports #chat-id=, /#chat-id=, and any URL containing #chat-id=
          // Normalize the href first to handle different formats
          let normalizedHref = attributes.href;
          if (normalizedHref.startsWith('/#')) {
            normalizedHref = normalizedHref.substring(1); // Remove leading / from /#chat-id=
          }
          
          const isInternal = normalizedHref.startsWith('#chat-id=') || normalizedHref.includes('#chat-id=');
          
          if (isInternal) {
            // Internal link: same tab, no target="_blank"
            // Ensure href starts with # (not /#)
            const finalHref = normalizedHref.startsWith('#') ? normalizedHref : '#' + normalizedHref.replace(/^\/+/, '');
            // Return object WITHOUT target attribute - this prevents new tab
            const result: Record<string, string> = {
              href: finalHref,
              class: 'markdown-link markdown-link-internal',
              'data-internal': 'true',
            };
            // Explicitly do NOT include target - this is the key to preventing new tab
            return result;
          } else {
            // External link: new tab (default behavior)
            return {
              href: attributes.href,
              class: 'markdown-link',
              rel: 'noopener noreferrer',
              target: '_blank',
            };
          }
        },
      },
      // Override target attribute to prevent it from being added to internal links
      target: {
        default: null,
        parseHTML: element => {
          const href = element.getAttribute('href');
          // For internal links, always return null to prevent target attribute
          if (href) {
            const normalizedHref = href.startsWith('/#') ? href.substring(1) : href;
            if (normalizedHref.startsWith('#chat-id=') || normalizedHref.includes('#chat-id=')) {
              return null; // No target for internal links
            }
          }
          return element.getAttribute('target');
        },
        renderHTML: attributes => {
          // Check if this is an internal link
          if (attributes.href) {
            let normalizedHref = attributes.href;
            if (normalizedHref.startsWith('/#')) {
              normalizedHref = normalizedHref.substring(1);
            }
            if (normalizedHref.startsWith('#chat-id=') || normalizedHref.includes('#chat-id=')) {
              // Return empty object - this prevents target from being rendered
              return {};
            }
          }
          // For external links, render target if provided
          return attributes.target ? { target: attributes.target } : {};
        },
      },
    };
  },
  
  /**
   * Override click behavior for hash-based chat links
   * Prevents TipTap from opening them in a new tab
   */
  addProseMirrorPlugins() {
    return [
      ...this.parent?.() || [],
      new Plugin({
        key: new PluginKey('markdownLinkClickHandler'),
        props: {
          handleDOMEvents: {
            click: (view, event) => {
              const target = event.target as HTMLElement;
              const link = target.closest('a.markdown-link') as HTMLAnchorElement;
              
              if (link) {
                const href = link.getAttribute('href');
                const isInternal = link.hasAttribute('data-internal');
                
                if (isInternal && href && (href.startsWith('#chat-id=') || href.startsWith('/#chat-id='))) {
                  // Internal hash-based link: prevent default and navigate to hash
                  event.preventDefault();
                  event.stopPropagation();
                  event.stopImmediatePropagation();
                  
                  // Normalize href (remove leading / if present)
                  const normalizedHref = href.startsWith('/') ? href.substring(1) : href;
                  
                  // Navigate to hash (triggers hashchange event)
                  if (typeof window !== 'undefined') {
                    window.location.hash = normalizedHref;
                  }
                  
                  return true; // Indicate we handled the click
                } else if (!isInternal && href) {
                  // External link: open in new tab (default browser behavior)
                  // Don't prevent default - let browser handle it
                  // The target="_blank" attribute is already set in renderHTML
                  return false;
                }
              }
              
              return false;
            },
          },
        },
      }),
    ];
  },
}).configure({
  HTMLAttributes: {
    class: 'markdown-link',
    // Don't set default target - we handle it per-link in renderHTML
  },
  openOnClick: false, // Disable TipTap's default openOnClick - we handle it manually via plugin
});

export const MarkdownStrike = Strike.extend({
  // Use default 'strike' name to match parser output (StarterKit's strike is disabled)
}).configure({
  HTMLAttributes: {
    class: 'markdown-strike',
  },
});

export const MarkdownUnderline = Underline.extend({
  // Use default 'underline' name to match parser output
}).configure({
  HTMLAttributes: {
    class: 'markdown-underline',
  },
});

// Enhanced Code extension that works with existing CodeEmbed
export const MarkdownCodeBlock = Extension.create({
  name: 'markdownCodeBlock',
  
  addGlobalAttributes() {
    return [
      {
        types: ['codeBlock'],
        attributes: {
          class: {
            default: 'markdown-code-block',
          },
        },
      },
    ];
  },
});

// Enhanced inline code styling
export const MarkdownInlineCode = Extension.create({
  name: 'markdownInlineCode',
  
  addGlobalAttributes() {
    return [
      {
        types: ['code'],
        attributes: {
          class: {
            default: 'markdown-inline-code',
          },
        },
      },
    ];
  },
});

// Enhanced typography for better markdown rendering
export const MarkdownTypography = Extension.create({
  name: 'markdownTypography',
  
  addGlobalAttributes() {
    return [
      {
        types: ['heading'],
        attributes: {
          class: {
            default: null,
            parseHTML: element => element.getAttribute('class'),
            renderHTML: attributes => {
              const level = attributes.level || 1;
              return {
                class: `markdown-heading markdown-h${level}`,
              };
            },
          },
        },
      },
      {
        types: ['paragraph'],
        attributes: {
          class: {
            default: 'markdown-paragraph',
          },
        },
      },
      {
        types: ['bulletList'],
        attributes: {
          class: {
            default: 'markdown-bullet-list',
          },
        },
      },
      {
        types: ['orderedList'],
        attributes: {
          class: {
            default: 'markdown-ordered-list',
          },
        },
      },
      {
        types: ['listItem'],
        attributes: {
          class: {
            default: 'markdown-list-item',
          },
        },
      },
      {
        types: ['bold'],
        attributes: {
          class: {
            default: 'markdown-bold',
          },
        },
      },
      {
        types: ['italic'],
        attributes: {
          class: {
            default: 'markdown-italic',
          },
        },
      },
      {
        types: ['blockquote'],
        attributes: {
          class: {
            default: 'markdown-blockquote',
          },
        },
      },
      {
        types: ['horizontalRule'],
        attributes: {
          class: {
            default: 'markdown-horizontal-rule',
          },
        },
      },
    ];
  },
});

// Export all markdown extensions as a convenient array
export const MarkdownExtensions = [
  MarkdownTable,
  MarkdownTableRow,
  MarkdownTableHeader,
  MarkdownTableCell,
  MarkdownMathematics,
  MarkdownHighlight,
  MarkdownLink,
  MarkdownStrike,
  MarkdownUnderline,
  MarkdownCodeBlock,
  MarkdownInlineCode,
  MarkdownTypography,
];
