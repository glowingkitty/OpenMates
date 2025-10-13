// Unit tests for serializers in the unified message parsing architecture
// Tests TipTap↔Markdown conversion and clipboard operations

import { describe, it, expect } from 'vitest';
import { 
  tipTapToCanonicalMarkdown, 
  markdownToTipTap,
  createEmbedClipboardData,
  parseEmbedClipboardData
} from '../serializers';
import { EmbedNodeAttributes, EmbedClipboardData } from '../types';

describe('tipTapToCanonicalMarkdown', () => {
  it('should convert simple paragraph to markdown', () => {
    const doc = {
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [
            { type: 'text', text: 'Hello world' }
          ]
        }
      ]
    };

    const result = tipTapToCanonicalMarkdown(doc);
    expect(result).toBe('Hello world');
  });

  it('should convert code embed to canonical markdown', () => {
    const doc = {
      type: 'doc',
      content: [
        {
          type: 'embed',
          attrs: {
            id: 'test-id',
            type: 'code',
            status: 'finished',
            contentRef: 'cid:sha256:abc123',
            language: 'javascript',
            filename: 'test.js'
          }
        }
      ]
    };

    const result = tipTapToCanonicalMarkdown(doc);
    expect(result).toBe('```javascript:test.js\n```');
  });

  it('should convert doc embed to canonical markdown with title', () => {
    const doc = {
      type: 'doc',
      content: [
        {
          type: 'embed',
          attrs: {
            id: 'test-id',
            type: 'doc',
            status: 'finished',
            contentRef: 'cid:sha256:abc123',
            title: 'My Document'
          }
        }
      ]
    };

    const result = tipTapToCanonicalMarkdown(doc);
    expect(result).toBe('```document_html\n<!-- title: "My Document" -->\n```');
  });

  it('should convert sheet embed to canonical markdown table', () => {
    const doc = {
      type: 'doc',
      content: [
        {
          type: 'embed',
          attrs: {
            id: 'test-id',
            type: 'sheet',
            status: 'finished',
            contentRef: 'cid:sha256:abc123',
            title: 'My Table',
            rows: 3,
            cols: 2
          }
        }
      ]
    };

    const result = tipTapToCanonicalMarkdown(doc);
    expect(result).toContain('<!-- title: "My Table" -->');
    expect(result).toContain('| Column 1 | Column 2 |');
    expect(result).toContain('|----------|----------|');
  });

  it('should convert web/video embeds to URLs', () => {
    const doc = {
      type: 'doc',
      content: [
        {
          type: 'embed',
          attrs: {
            id: 'test-id',
            type: 'web',
            status: 'finished',
            contentRef: 'cid:sha256:abc123',
            url: 'https://example.com'
          }
        }
      ]
    };

    const result = tipTapToCanonicalMarkdown(doc);
    expect(result).toBe('https://example.com');
  });

  it('should handle mixed content types', () => {
    const doc = {
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [{ type: 'text', text: 'Here is some code:' }]
        },
        {
          type: 'embed',
          attrs: {
            id: 'test-id',
            type: 'code',
            status: 'finished',
            contentRef: 'cid:sha256:abc123',
            language: 'python'
          }
        },
        {
          type: 'paragraph',
          content: [{ type: 'text', text: 'And a link:' }]
        },
        {
          type: 'embed',
          attrs: {
            id: 'test-id-2',
            type: 'web',
            status: 'finished',
            contentRef: 'cid:sha256:def456',
            url: 'https://example.com'
          }
        }
      ]
    };

    const result = tipTapToCanonicalMarkdown(doc);
    expect(result).toContain('Here is some code:');
    expect(result).toContain('```python\n```');
    expect(result).toContain('And a link:');
    expect(result).toContain('https://example.com');
  });

  it('should handle text formatting marks', () => {
    const doc = {
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [
            {
              type: 'text',
              text: 'Bold text',
              marks: [{ type: 'bold' }]
            },
            { type: 'text', text: ' and ' },
            {
              type: 'text',
              text: 'italic text',
              marks: [{ type: 'italic' }]
            }
          ]
        }
      ]
    };

    const result = tipTapToCanonicalMarkdown(doc);
    expect(result).toBe('**Bold text** and *italic text*');
  });

  it('should return empty string for null/undefined document', () => {
    expect(tipTapToCanonicalMarkdown(null)).toBe('');
    expect(tipTapToCanonicalMarkdown(undefined)).toBe('');
    expect(tipTapToCanonicalMarkdown({})).toBe('');
  });
});

describe('markdownToTipTap', () => {
  it('should convert basic markdown to TipTap structure', () => {
    const markdown = 'Hello world';
    const result = markdownToTipTap(markdown);
    
    expect(result).toBeDefined();
    expect(result.type).toBe('doc');
    expect(result.content).toBeDefined();
  });

  it('should handle empty markdown', () => {
    const result = markdownToTipTap('');
    expect(result).toBeDefined();
    expect(result.type).toBe('doc');
  });

  it('should provide fallback for parsing errors', () => {
    // This tests the fallback behavior when the existing parser fails
    const markdown = 'Some text';
    const result = markdownToTipTap(markdown);
    
    expect(result).toBeDefined();
    expect(result.type).toBe('doc');
  });
});

describe('clipboard operations', () => {
  describe('createEmbedClipboardData', () => {
    it('should create clipboard data for code embed', () => {
      const attrs: EmbedNodeAttributes = {
        id: 'test-id',
        type: 'code',
        status: 'finished',
        contentRef: 'cid:sha256:abc123',
        contentHash: 'abc123',
        language: 'javascript',
        filename: 'test.js'
      };

      const clipboardData = createEmbedClipboardData(attrs);
      
      expect(clipboardData.version).toBe(1);
      expect(clipboardData.id).toBe('test-id');
      expect(clipboardData.type).toBe('code');
      expect(clipboardData.language).toBe('javascript');
      expect(clipboardData.filename).toBe('test.js');
      expect(clipboardData.contentRef).toBe('cid:sha256:abc123');
      expect(clipboardData.contentHash).toBe('abc123');
    });

    it('should create clipboard data for doc embed', () => {
      const attrs: EmbedNodeAttributes = {
        id: 'test-id',
        type: 'doc',
        status: 'finished',
        contentRef: 'cid:sha256:def456',
        contentHash: 'def456',
        title: 'My Document'
      };

      const clipboardData = createEmbedClipboardData(attrs);
      
      expect(clipboardData.version).toBe(1);
      expect(clipboardData.type).toBe('doc');
      expect(clipboardData.contentRef).toBe('cid:sha256:def456');
      expect(clipboardData.contentHash).toBe('def456');
    });
  });

  describe('parseEmbedClipboardData', () => {
    it('should parse clipboard data back to embed attributes', () => {
      const clipboardData: EmbedClipboardData = {
        version: 1,
        id: 'test-id',
        type: 'code',
        language: 'python',
        filename: 'script.py',
        contentRef: 'cid:sha256:xyz789',
        contentHash: 'xyz789',
        inlineContent: 'print("hello")'
      };

      const attrs = parseEmbedClipboardData(clipboardData);
      
      expect(attrs.id).toBe('test-id');
      expect(attrs.type).toBe('code');
      expect(attrs.status).toBe('finished'); // Should be set to finished for clipboard data
      expect(attrs.language).toBe('python');
      expect(attrs.filename).toBe('script.py');
      expect(attrs.contentRef).toBe('cid:sha256:xyz789');
      expect(attrs.contentHash).toBe('xyz789');
    });

    it('should handle minimal clipboard data', () => {
      const clipboardData: EmbedClipboardData = {
        version: 1,
        id: 'minimal-id',
        type: 'web',
        contentRef: 'cid:sha256:minimal'
      };

      const attrs = parseEmbedClipboardData(clipboardData);
      
      expect(attrs.id).toBe('minimal-id');
      expect(attrs.type).toBe('web');
      expect(attrs.status).toBe('finished');
      expect(attrs.contentRef).toBe('cid:sha256:minimal');
      expect(attrs.language).toBeUndefined();
      expect(attrs.filename).toBeUndefined();
    });
  });

  describe('round-trip conversion', () => {
    it('should preserve data through create/parse cycle', () => {
      const originalAttrs: EmbedNodeAttributes = {
        id: 'round-trip-test',
        type: 'sheet',
        status: 'finished',
        contentRef: 'cid:sha256:roundtrip',
        contentHash: 'roundtrip',
        title: 'Test Table',
        rows: 5,
        cols: 3,
        cellCount: 15
      };

      const clipboardData = createEmbedClipboardData(originalAttrs);
      const parsedAttrs = parseEmbedClipboardData(clipboardData);

      expect(parsedAttrs.id).toBe(originalAttrs.id);
      expect(parsedAttrs.type).toBe(originalAttrs.type);
      expect(parsedAttrs.status).toBe('finished'); // Should be set to finished
      expect(parsedAttrs.contentRef).toBe(originalAttrs.contentRef);
      expect(parsedAttrs.contentHash).toBe(originalAttrs.contentHash);
      // Note: metadata fields like rows, cols, cellCount are not preserved in clipboard data
    });
  });
});
