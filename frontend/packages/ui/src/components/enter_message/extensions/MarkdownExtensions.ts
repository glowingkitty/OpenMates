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

export const MarkdownLink = Link.extend({
  name: 'markdownLink', // Unique name to avoid conflicts
}).configure({
  HTMLAttributes: {
    class: 'markdown-link',
    rel: 'noopener noreferrer',
    target: '_blank',
  },
  openOnClick: true,
});

export const MarkdownStrike = Strike.extend({
  name: 'markdownStrike', // Unique name to avoid conflicts
}).configure({
  HTMLAttributes: {
    class: 'markdown-strike',
  },
});

export const MarkdownUnderline = Underline.extend({
  name: 'markdownUnderline', // Unique name to avoid conflicts
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
