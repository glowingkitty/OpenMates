// Markdown Parser for converting markdown text to TipTap JSON
import MarkdownIt from 'markdown-it';

// Initialize markdown-it with options
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: false, // Don't convert '\n' in paragraphs into <br> - this causes issues
});

// Helper function to pre-process markdown to ensure double newlines create empty paragraphs
function preprocessMarkdown(markdownText: string): string {
  // Split the text by double newlines and process each section
  const sections = markdownText.split(/\n\n+/);
  const processedSections: string[] = [];
  
  for (let i = 0; i < sections.length; i++) {
    const section = sections[i].trim();
    if (section) {
      processedSections.push(section);
    }
    
    // Add empty paragraph marker between sections (except for the last one)
    if (i < sections.length - 1) {
      processedSections.push('<!-- EMPTY_PARAGRAPH -->');
    }
  }
  
  return processedSections.join('\n\n');
}

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
    
    // Only skip text nodes that are just whitespace/newlines if they're not inside a paragraph
    // This allows empty paragraphs to be preserved for proper spacing
    const parentElement = node.parentElement;
    if (text.trim() === '' && parentElement?.tagName.toLowerCase() !== 'p') {
      return null;
    }
    
    return { type: 'text', text };
  }

  if (node.nodeType === Node.COMMENT_NODE) {
    const comment = node.textContent;
    if (comment === ' EMPTY_PARAGRAPH ') {
      return {
        type: 'paragraph',
        content: []
      };
    }
    return null;
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
      // Always create paragraphs, even if empty (for \n\n spacing)
      // Filter out whitespace-only text nodes from paragraph content, but preserve the paragraph itself
      const paragraphContent = content.filter(item => {
        if (item && item.type === 'text' && item.text.trim() === '') {
          return false; // Remove whitespace-only text nodes from paragraph content
        }
        return true;
      });
      
      // For empty paragraphs, create a proper empty paragraph structure
      if (paragraphContent.length === 0) {
        return {
          type: 'paragraph',
          content: []
        };
      }
      
      return {
        type: 'paragraph',
        content: paragraphContent
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
        content: content.filter(item => item && item.type === 'listItem')
      };

    case 'ol':
      // Preserve the start attribute for ordered lists to maintain proper numbering
      const startAttr = element.getAttribute('start');
      const attrs = startAttr ? { start: parseInt(startAttr) } : undefined;
      
      return {
        type: 'orderedList',
        attrs,
        content: content.filter(item => item && item.type === 'listItem')
      };

    case 'li':
      // Handle list items more carefully
      const listItemContent: any[] = [];
      let currentParagraphContent: any[] = [];
      
      for (const item of content) {
        if (!item) continue;
        
        if (item.type === 'bulletList' || item.type === 'orderedList') {
          // If we have accumulated paragraph content, wrap it in a paragraph first
          if (currentParagraphContent.length > 0) {
            listItemContent.push({
              type: 'paragraph',
              content: currentParagraphContent
            });
            currentParagraphContent = [];
          }
          // Add the nested list
          listItemContent.push(item);
        } else if (item.type === 'paragraph') {
          // If we have accumulated paragraph content, wrap it first
          if (currentParagraphContent.length > 0) {
            listItemContent.push({
              type: 'paragraph',
              content: currentParagraphContent
            });
            currentParagraphContent = [];
          }
          // Add the paragraph
          listItemContent.push(item);
        } else if (item.type === 'heading') {
          // Headers inside list items should be converted to bold text
          if (item.content && Array.isArray(item.content)) {
            const boldContent = item.content.map((textItem: any) => ({
              ...textItem,
              marks: [...(textItem.marks || []), { type: 'bold' }]
            }));
            currentParagraphContent.push(...boldContent);
          }
        } else if (item.type === 'blockquote') {
          // Blockquotes inside list items should be flattened to paragraph content
          if (item.content && Array.isArray(item.content)) {
            for (const blockquoteItem of item.content) {
              if (blockquoteItem.type === 'paragraph' && blockquoteItem.content) {
                currentParagraphContent.push(...blockquoteItem.content);
              }
            }
          }
        } else if (item.type === 'codeBlock' || item.type === 'table' || item.type === 'horizontalRule') {
          // Other block-level elements should not be inside list items in TipTap
          // Convert them to paragraph content or skip
          if (item.content && Array.isArray(item.content)) {
            currentParagraphContent.push(...item.content);
          } else if (item.type === 'horizontalRule') {
            // Skip horizontal rules inside list items
            continue;
          }
        } else {
          // Text nodes and inline elements
          currentParagraphContent.push(item);
        }
      }
      
      // If we have remaining paragraph content, wrap it
      if (currentParagraphContent.length > 0) {
        listItemContent.push({
          type: 'paragraph',
          content: currentParagraphContent
        });
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
        content: content.filter(item => item && item.type === 'tableRow')
      };

    case 'thead':
    case 'tbody':
      return content.filter(item => item && item.type === 'tableRow');

    case 'tr':
      return {
        type: 'tableRow',
        content: content.filter(item => item && (item.type === 'tableHeader' || item.type === 'tableCell'))
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

// Helper function to merge consecutive ordered lists and preserve numbering
function mergeOrderedLists(content: any[]): any[] {
  const merged: any[] = [];
  let currentOrderedList: any = null;
  let expectedStart = 1;
  
  for (const item of content) {
    if (item && item.type === 'orderedList') {
      const itemStart = item.attrs?.start || 1;
      
      if (currentOrderedList && itemStart === expectedStart) {
        // This list continues the previous one, merge them
        currentOrderedList.content.push(...item.content);
        expectedStart += item.content.length;
      } else {
        // This is a new list or doesn't continue the previous one
        if (currentOrderedList) {
          merged.push(currentOrderedList);
        }
        currentOrderedList = { ...item };
        expectedStart = itemStart + item.content.length;
      }
    } else {
      // Non-list item, push any pending list and the current item
      if (currentOrderedList) {
        merged.push(currentOrderedList);
        currentOrderedList = null;
      }
      merged.push(item);
      expectedStart = 1; // Reset expected start for next potential list
    }
  }
  
  // Don't forget to push the last list if there is one
  if (currentOrderedList) {
    merged.push(currentOrderedList);
  }
  
  return merged;
}

// Helper function to clean and validate TipTap document structure
function cleanTiptapDocument(content: any[]): any[] {
  const cleaned: any[] = [];
  
  for (const item of content) {
    if (!item) continue;
    
    // Skip text nodes at document level (they should be inside paragraphs)
    if (item.type === 'text') {
      // Wrap standalone text in a paragraph
      cleaned.push({
        type: 'paragraph',
        content: [item]
      });
      continue;
    }
    
    // Keep horizontal rules at document level
    if (item.type === 'horizontalRule') {
      cleaned.push(item);
      continue;
    }
    
    // Keep blockquotes at document level
    if (item.type === 'blockquote') {
      cleaned.push(item);
      continue;
    }
    
    // Ensure proper document structure - no block elements inside inline elements
    if (item.type === 'listItem' && item.content) {
      // Validate list item content
      const validContent: any[] = [];
      for (const listContent of item.content) {
        if (listContent && (
          listContent.type === 'paragraph' || 
          listContent.type === 'bulletList' || 
          listContent.type === 'orderedList'
        )) {
          validContent.push(listContent);
        }
      }
      if (validContent.length > 0) {
        cleaned.push({
          ...item,
          content: validContent
        });
      }
    } else if (item.type === 'bulletList' || item.type === 'orderedList') {
      // Validate list content
      if (item.content && item.content.length > 0) {
        const validListItems = item.content.filter((listItem: any) => 
          listItem && listItem.type === 'listItem'
        );
        if (validListItems.length > 0) {
          cleaned.push({
            ...item,
            content: validListItems
          });
        }
      }
    } else if (item.type === 'table') {
      // Validate table content
      if (item.content && item.content.length > 0) {
        const validRows = item.content.filter((row: any) => 
          row && row.type === 'tableRow'
        );
        if (validRows.length > 0) {
          cleaned.push({
            ...item,
            content: validRows
          });
        }
      }
    } else if (item.type === 'paragraph') {
      // Always keep paragraphs, even empty ones for spacing
      cleaned.push(item);
    } else {
      // Keep all other items
      cleaned.push(item);
    }
  }
  
  // Merge consecutive ordered lists to preserve numbering
  return mergeOrderedLists(cleaned);
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
    // Pre-process markdown to handle double newlines
    const processedMarkdown = preprocessMarkdown(markdownText);
    // console.log('Preprocessed markdown:', processedMarkdown); // Debug log
    
    // Convert markdown to HTML
    const html = md.render(processedMarkdown);
    // console.log('Generated HTML:', html); // Debug log
    
    // Convert HTML to TipTap JSON
    const content = htmlToTiptapJson(html);
    // console.log('Converted to TipTap JSON:', content); // Debug log
    
    // Ensure we have a valid document structure
    const docContent = Array.isArray(content) ? content : (content ? [content] : []);
    
    // Filter out null/undefined items and clean the structure
    const filteredContent = docContent.filter(item => item !== null && item !== undefined);
    const cleanedContent = cleanTiptapDocument(filteredContent);
    
    if (cleanedContent.length === 0) {
      cleanedContent.push({
        type: 'paragraph',
        content: [{ type: 'text', text: markdownText }]
      });
    }

    const result = {
      type: 'doc',
      content: cleanedContent
    };
    
    // console.log('Final TipTap JSON:', JSON.stringify(result, null, 2)); // Debug log
    return result;
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
