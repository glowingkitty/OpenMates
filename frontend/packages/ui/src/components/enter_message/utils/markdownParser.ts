// Markdown Parser for converting markdown text to TipTap JSON
import MarkdownIt from 'markdown-it';

// Initialize markdown-it with options
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: true, // Convert '\n' in paragraphs into <br>
});

// Helper function to convert HTML to TipTap JSON
function htmlToTiptapJson(html: string): any {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  
  return convertNodeToTiptap(doc.body);
}

function convertNodeToTiptap(node: Node): any {
  if (node.nodeType === Node.TEXT_NODE) {
    const text = node.textContent;
    if (!text) return null;
    // Don't trim text nodes - preserve whitespace
    return { type: 'text', text };
  }

  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }

  const element = node as Element;
  const tagName = element.tagName.toLowerCase();
  const content: any[] = [];

  // Process child nodes
  for (const child of Array.from(element.childNodes)) {
    const childResult = convertNodeToTiptap(child);
    if (childResult) {
      if (Array.isArray(childResult)) {
        content.push(...childResult);
      } else {
        content.push(childResult);
      }
    }
  }

  // Handle different HTML elements
  switch (tagName) {
    case 'body':
    case 'div':
      return content.length > 0 ? content : null;

    case 'p':
      return {
        type: 'paragraph',
        content: content.length > 0 ? content : [{ type: 'text', text: '' }]
      };

    case 'h1':
    case 'h2':
    case 'h3':
    case 'h4':
    case 'h5':
    case 'h6':
      return {
        type: 'heading',
        attrs: { level: parseInt(tagName.charAt(1)) },
        content: content.length > 0 ? content : [{ type: 'text', text: '' }]
      };

    case 'strong':
    case 'b':
      return content.map(item => ({
        ...item,
        marks: [...(item.marks || []), { type: 'bold' }]
      }));

    case 'em':
    case 'i':
      return content.map(item => ({
        ...item,
        marks: [...(item.marks || []), { type: 'italic' }]
      }));

    case 'code':
      if (element.parentElement?.tagName.toLowerCase() === 'pre') {
        // This is a code block, handle it in the 'pre' case
        return content;
      } else {
        // This is inline code
        return content.map(item => ({
          ...item,
          marks: [...(item.marks || []), { type: 'code' }]
        }));
      }

    case 'pre':
      const codeElement = element.querySelector('code');
      const codeText = codeElement ? codeElement.textContent || '' : element.textContent || '';
      return {
        type: 'codeBlock',
        content: [{ type: 'text', text: codeText }]
      };

    case 's':
    case 'del':
    case 'strike':
      return content.map(item => ({
        ...item,
        marks: [...(item.marks || []), { type: 'strike' }]
      }));

    case 'u':
      return content.map(item => ({
        ...item,
        marks: [...(item.marks || []), { type: 'underline' }]
      }));

    case 'mark':
      return content.map(item => ({
        ...item,
        marks: [...(item.marks || []), { type: 'highlight' }]
      }));

    case 'a':
      const href = element.getAttribute('href');
      if (href) {
        return content.map(item => ({
          ...item,
          marks: [...(item.marks || []), { type: 'link', attrs: { href } }]
        }));
      }
      return content;

    case 'ul':
      return {
        type: 'bulletList',
        content: content.filter(item => item.type === 'listItem')
      };

    case 'ol':
      return {
        type: 'orderedList',
        content: content.filter(item => item.type === 'listItem')
      };

    case 'li':
      // Handle nested lists properly - separate paragraphs from nested lists
      const listItemContent: any[] = [];
      
      for (const item of content) {
        if (item && (item.type === 'bulletList' || item.type === 'orderedList')) {
          // This is a nested list - add it directly
          listItemContent.push(item);
        } else if (item && item.type === 'paragraph') {
          // This is a paragraph - add it directly
          listItemContent.push(item);
        } else if (item) {
          // Other content - wrap in paragraph if it's not already
          listItemContent.push(item);
        }
      }
      
      return {
        type: 'listItem',
        content: listItemContent.length > 0 ? listItemContent : [{ type: 'paragraph', content: [{ type: 'text', text: '' }] }]
      };

    case 'blockquote':
      return {
        type: 'blockquote',
        content: content.length > 0 ? content : [{ type: 'paragraph', content: [{ type: 'text', text: '' }] }]
      };

    case 'table':
      return {
        type: 'table',
        content: content.filter(item => item.type === 'tableRow')
      };

    case 'thead':
    case 'tbody':
      return content.filter(item => item.type === 'tableRow');

    case 'tr':
      return {
        type: 'tableRow',
        content: content.filter(item => item.type === 'tableHeader' || item.type === 'tableCell')
      };

    case 'th':
      return {
        type: 'tableHeader',
        content: content.length > 0 ? content : [{ type: 'paragraph', content: [{ type: 'text', text: '' }] }]
      };

    case 'td':
      return {
        type: 'tableCell',
        content: content.length > 0 ? content : [{ type: 'paragraph', content: [{ type: 'text', text: '' }] }]
      };

    case 'br':
      return { type: 'hardBreak' };

    case 'hr':
      return { type: 'horizontalRule' };

    default:
      // For unknown elements, just return their content
      return content.length > 0 ? content : null;
  }
}

// Main function to parse markdown text to TipTap JSON
export function parseMarkdownToTiptap(markdownText: string): any {
  if (!markdownText || typeof markdownText !== 'string') {
    return {
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [{ type: 'text', text: '' }]
        }
      ]
    };
  }

  try {
    // Convert markdown to HTML
    const html = md.render(markdownText);
    
    // Convert HTML to TipTap JSON
    const content = htmlToTiptapJson(html);
    
    // Ensure we have a valid document structure
    const docContent = Array.isArray(content) ? content : (content ? [content] : []);
    
    // Filter out null/undefined items and ensure we have at least one paragraph
    const filteredContent = docContent.filter(item => item !== null && item !== undefined);
    
    if (filteredContent.length === 0) {
      filteredContent.push({
        type: 'paragraph',
        content: [{ type: 'text', text: markdownText }]
      });
    }

    return {
      type: 'doc',
      content: filteredContent
    };
  } catch (error) {
    console.error('Error parsing markdown:', error);
    
    // Fallback: return the text as a simple paragraph
    return {
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: [{ type: 'text', text: markdownText }]
        }
      ]
    };
  }
}

// Helper function to detect if content is likely markdown
export function isMarkdownContent(content: any): boolean {
  if (typeof content === 'string') {
    // Check for common markdown patterns
    const markdownPatterns = [
      /^#{1,6}\s+/m,           // Headers
      /\*\*.*?\*\*/,           // Bold
      /\*.*?\*/,               // Italic
      /_.*?_/,                 // Italic/Underline
      /`.*?`/,                 // Inline code
      /```[\s\S]*?```/,        // Code blocks
      /^\s*[-*+]\s+/m,         // Bullet lists
      /^\s*\d+\.\s+/m,         // Numbered lists
      /^\s*>\s+/m,             // Blockquotes
      /\[.*?\]\(.*?\)/,        // Links
      /\|.*?\|/,               // Tables
    ];
    
    return markdownPatterns.some(pattern => pattern.test(content));
  }
  
  return false;
}
