// Unit tests for the unified message parsing architecture
// Tests the main parse_message function and related utilities

import { describe, it, expect, beforeEach } from 'vitest';
import { parse_message, parseEmbedNodes, handleStreamingSemantics, enhanceDocumentWithEmbeds } from '../parse_message';
import { EmbedNodeAttributes } from '../types';

describe('parse_message', () => {
  describe('basic functionality', () => {
    it('should fallback to existing parser when unified parsing is disabled', () => {
      const markdown = 'Hello world';
      const result = parse_message(markdown, 'read', { unifiedParsingEnabled: false });
      
      // Should return some kind of TipTap document structure
      expect(result).toBeDefined();
      expect(result.type).toBe('doc');
    });

    it('should parse simple markdown with unified parsing enabled', () => {
      const markdown = 'Hello world';
      const result = parse_message(markdown, 'read', { unifiedParsingEnabled: true });
      
      expect(result).toBeDefined();
      expect(result.type).toBe('doc');
      expect(result.content).toBeDefined();
    });
  });

  describe('embed detection', () => {
    it('should detect code fences with language', () => {
      const markdown = '```javascript\nconsole.log("hello");\n```';
      const result = parse_message(markdown, 'read', { unifiedParsingEnabled: true });
      
      expect(result.content).toBeDefined();
      // Should contain an embed node
      const embedNode = result.content.find((node: any) => node.type === 'embed');
      expect(embedNode).toBeDefined();
      expect(embedNode.attrs.type).toBe('code');
      expect(embedNode.attrs.language).toBe('javascript');
    });

    it('should detect code fences with path', () => {
      const markdown = '```typescript:src/main.ts\nfunction main() {}\n```';
      const result = parse_message(markdown, 'read', { unifiedParsingEnabled: true });
      
      const embedNode = result.content.find((node: any) => node.type === 'embed');
      expect(embedNode).toBeDefined();
      expect(embedNode.attrs.type).toBe('code');
      expect(embedNode.attrs.language).toBe('typescript');
      expect(embedNode.attrs.filename).toBe('src/main.ts');
    });

    it('should detect document_html fences', () => {
      const markdown = '```document_html\n<!-- title: "My Document" -->\n<h1>Hello</h1>\n```';
      const result = parse_message(markdown, 'read', { unifiedParsingEnabled: true });
      
      const embedNode = result.content.find((node: any) => node.type === 'embed');
      expect(embedNode).toBeDefined();
      expect(embedNode.attrs.type).toBe('doc');
      expect(embedNode.attrs.title).toBe('My Document');
    });

    it('should detect table markdown', () => {
      const markdown = '| Column 1 | Column 2 |\n|----------|----------|\n| Data 1   | Data 2   |';
      const result = parse_message(markdown, 'read', { unifiedParsingEnabled: true });
      
      const embedNode = result.content.find((node: any) => node.type === 'embed');
      expect(embedNode).toBeDefined();
      expect(embedNode.attrs.type).toBe('sheet');
      expect(embedNode.attrs.rows).toBe(2); // Header + data row
      expect(embedNode.attrs.cols).toBe(2);
    });

    it('should detect URLs', () => {
      const markdown = 'Check out https://example.com for more info';
      const result = parse_message(markdown, 'read', { unifiedParsingEnabled: true });
      
      const embedNode = result.content.find((node: any) => node.type === 'embed');
      expect(embedNode).toBeDefined();
      expect(embedNode.attrs.type).toBe('web');
      expect(embedNode.attrs.url).toBe('https://example.com');
    });

    it('should detect YouTube URLs', () => {
      const markdown = 'Watch this: https://www.youtube.com/watch?v=dQw4w9WgXcQ';
      const result = parse_message(markdown, 'read', { unifiedParsingEnabled: true });
      
      const embedNode = result.content.find((node: any) => node.type === 'embed');
      expect(embedNode).toBeDefined();
      expect(embedNode.attrs.type).toBe('video');
      expect(embedNode.attrs.url).toBe('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
    });
  });
});

describe('parseEmbedNodes', () => {
  it('should parse multiple embed types in one markdown', () => {
    const markdown = `
# Test Document

Here's some code:
\`\`\`python:hello.py
print("Hello, world!")
\`\`\`

And a table:
| Name | Age |
|------|-----|
| John | 25  |

And a link: https://example.com
    `.trim();

    const embedNodes = parseEmbedNodes(markdown, 'read');
    
    expect(embedNodes).toHaveLength(3);
    
    const codeEmbed = embedNodes.find(node => node.type === 'code');
    expect(codeEmbed).toBeDefined();
    expect(codeEmbed?.language).toBe('python');
    expect(codeEmbed?.filename).toBe('hello.py');
    
    const tableEmbed = embedNodes.find(node => node.type === 'sheet');
    expect(tableEmbed).toBeDefined();
    expect(tableEmbed?.rows).toBe(2);
    expect(tableEmbed?.cols).toBe(2);
    
    const webEmbed = embedNodes.find(node => node.type === 'web');
    expect(webEmbed).toBeDefined();
    expect(webEmbed?.url).toBe('https://example.com');
  });

  it('should set processing status in write mode', () => {
    const markdown = '```javascript\nconsole.log("test");\n```';
    const embedNodes = parseEmbedNodes(markdown, 'write');
    
    expect(embedNodes).toHaveLength(1);
    expect(embedNodes[0].status).toBe('processing');
    expect(embedNodes[0].contentRef).toMatch(/^stream:/);
  });

  it('should set finished status in read mode', () => {
    const markdown = '```javascript\nconsole.log("test");\n```';
    const embedNodes = parseEmbedNodes(markdown, 'read');
    
    expect(embedNodes).toHaveLength(1);
    expect(embedNodes[0].status).toBe('finished');
    expect(embedNodes[0].contentRef).toMatch(/^stream:/);
  });
});

describe('handleStreamingSemantics', () => {
  it('should detect unclosed code fence in write mode', () => {
    const markdown = '```javascript\nconsole.log("hello");';
    const result = handleStreamingSemantics(markdown, 'write');
    
    expect(result.partialEmbeds).toHaveLength(1);
    expect(result.unclosedBlocks).toHaveLength(1);
    
    const partialEmbed = result.partialEmbeds[0];
    expect(partialEmbed.type).toBe('code');
    expect(partialEmbed.status).toBe('processing');
    expect(partialEmbed.language).toBe('javascript');
    
    const unclosedBlock = result.unclosedBlocks[0];
    expect(unclosedBlock.type).toBe('code');
    expect(unclosedBlock.startLine).toBe(0);
  });

  it('should not detect closed blocks as partial', () => {
    const markdown = '```javascript\nconsole.log("hello");\n```';
    const result = handleStreamingSemantics(markdown, 'write');
    
    expect(result.partialEmbeds).toHaveLength(0);
    expect(result.unclosedBlocks).toHaveLength(0);
  });

  it('should detect unclosed document_html fence', () => {
    const markdown = '```document_html\n<h1>Hello World</h1>';
    const result = handleStreamingSemantics(markdown, 'write');
    
    expect(result.partialEmbeds).toHaveLength(1);
    expect(result.partialEmbeds[0].type).toBe('doc');
    expect(result.unclosedBlocks).toHaveLength(1);
    expect(result.unclosedBlocks[0].type).toBe('document_html');
  });

  it('should detect partial table without header separator', () => {
    const markdown = '| Column 1 | Column 2 |\n| Data 1   | Data 2   |';
    const result = handleStreamingSemantics(markdown, 'write');
    
    expect(result.partialEmbeds).toHaveLength(1);
    expect(result.partialEmbeds[0].type).toBe('sheet');
    expect(result.unclosedBlocks).toHaveLength(1);
    expect(result.unclosedBlocks[0].type).toBe('table');
  });

  it('should not treat complete table as partial', () => {
    const markdown = '| Column 1 | Column 2 |\n|----------|----------|\n| Data 1   | Data 2   |';
    const result = handleStreamingSemantics(markdown, 'write');
    
    expect(result.partialEmbeds).toHaveLength(0);
    expect(result.unclosedBlocks).toHaveLength(0);
  });

  it('should not detect partial content in read mode', () => {
    const markdown = '```javascript\nconsole.log("hello");';
    const result = handleStreamingSemantics(markdown, 'read');
    
    expect(result.partialEmbeds).toHaveLength(0);
    expect(result.unclosedBlocks).toHaveLength(0);
  });
});

describe('enhanceDocumentWithEmbeds', () => {
  it('should add embed nodes to document content', () => {
    const doc = {
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [{ type: 'text', text: 'Hello world' }]
        }
      ]
    };

    const embedNodes: EmbedNodeAttributes[] = [
      {
        id: 'test-id',
        type: 'code',
        status: 'finished',
        contentRef: 'cid:sha256:abc123',
        language: 'javascript'
      }
    ];

    const result = enhanceDocumentWithEmbeds(doc, embedNodes, 'read');
    
    expect(result.content).toHaveLength(2);
    expect(result.content[0]).toEqual(doc.content[0]); // Original paragraph
    expect(result.content[1].type).toBe('embed');
    expect(result.content[1].attrs).toEqual(embedNodes[0]);
  });

  it('should return original document if no embeds', () => {
    const doc = {
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [{ type: 'text', text: 'Hello world' }]
        }
      ]
    };

    const result = enhanceDocumentWithEmbeds(doc, [], 'read');
    
    expect(result).toEqual(doc);
  });

  it('should handle null/undefined document', () => {
    const result = enhanceDocumentWithEmbeds(null, [], 'read');
    expect(result).toBeNull();
  });
});
