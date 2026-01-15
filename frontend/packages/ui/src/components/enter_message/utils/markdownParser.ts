// Markdown Parser for converting markdown text to TipTap JSON
import MarkdownIt from 'markdown-it';
// Note: We don't use markdown-it-katex for rendering because we extract math formulas
// ourselves and convert them to TipTap Mathematics nodes. This gives us better control
// over the LaTeX formula preservation for TipTap's Mathematics extension.

// Initialize markdown-it with options
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: false, // Don't convert '\n' in paragraphs into <br> - this causes issues
});

// Override the link renderer to prevent target="_blank" for internal links
// This is called for markdown links like [text](url)
const defaultLinkRender = md.renderer.rules.link_open || ((tokens, idx, options, env, self) => {
  return self.renderToken(tokens, idx, options);
});

md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx];
  const href = token.attrGet('href');
  
  // Check if this is an internal hash-based link
  if (href && (href.startsWith('#chat-id=') || href.startsWith('/#chat-id=') || href.includes('#chat-id='))) {
    // Remove target attribute if present (markdown-it linkify might add it)
    token.attrSet('target', null);
    // Remove rel attributes that might include nofollow
    const rel = token.attrGet('rel');
    if (rel) {
      token.attrSet('rel', null);
    }
  }
  
  return defaultLinkRender(tokens, idx, options, env, self);
};

// Map to store extracted LaTeX formulas for TipTap Mathematics nodes
// Key: placeholder ID, Value: { tex: LaTeX formula, display: boolean }
const mathFormulas = new Map<string, { tex: string; display: boolean }>();

// Helper function to extract math formulas from markdown and replace with placeholders
// This preserves the LaTeX formula for TipTap Mathematics extension
function extractMathFormulas(markdownText: string): { processed: string; formulas: Map<string, { tex: string; display: boolean }> } {
  const formulas = new Map<string, { tex: string; display: boolean }>();
  let processed = markdownText;
  let placeholderCounter = 0;
  
  // Extract block math: $$...$$
  // Use a regex that handles multi-line block math
  processed = processed.replace(/\$\$([\s\S]*?)\$\$/g, (match, formula) => {
    const placeholder = `<!-- MATH_BLOCK_${placeholderCounter} -->`;
    formulas.set(placeholder, { tex: formula.trim(), display: true });
    placeholderCounter++;
    return placeholder;
  });
  
  // Extract inline math: $...$ (but not $$...$$)
  // Use negative lookahead/lookbehind to avoid matching block math
  processed = processed.replace(/(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)/g, (match, formula) => {
    const placeholder = `<!-- MATH_INLINE_${placeholderCounter} -->`;
    formulas.set(placeholder, { tex: formula.trim(), display: false });
    placeholderCounter++;
    return placeholder;
  });
  
  return { processed, formulas };
}

// Helper function to pre-process markdown to ensure double newlines create empty paragraphs
function preprocessMarkdown(markdownText: string): string {
  // First extract math formulas
  const { processed: textWithMathExtracted, formulas } = extractMathFormulas(markdownText);
  // Store formulas globally for use in convertNodeToTiptap
  mathFormulas.clear();
  formulas.forEach((value, key) => mathFormulas.set(key, value));
  
  // Split the text by double newlines and process each section
  const sections = textWithMathExtracted.split(/\n\n+/);
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
    // Check if this is a math formula placeholder
    // Comment text content is just the text between <!-- and -->, so we need to match the pattern
    if (comment && (comment.trim().startsWith('MATH_BLOCK_') || comment.trim().startsWith('MATH_INLINE_'))) {
      const trimmedComment = comment.trim();
      // Try to find the math data - the key includes the full comment syntax
      const fullCommentKey = `<!-- ${trimmedComment} -->`;
      const mathData = mathFormulas.get(fullCommentKey);
      if (mathData) {
        // Create TipTap Mathematics node
        // TipTap Mathematics extension creates two node types: 'inlineMath' and 'blockMath'
        // Both use 'latex' attribute (not 'tex')
        return {
          type: mathData.display ? 'blockMath' : 'inlineMath',
          attrs: {
            latex: mathData.tex
          }
        };
      }
    }
    return null;
  }

  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }

  const element = node as Element;
  const tagName = element.tagName.toLowerCase();
  const content: any[] = [];

  // Handle KaTeX-rendered math elements before processing children
  // This is a fallback in case comment nodes don't work
  // markdown-it-katex renders math to <span class="katex"> or <div class="katex-display">
  if (tagName === 'span' && element.classList.contains('katex') && !element.classList.contains('katex-display')) {
    // Inline math - try to extract LaTeX from data attribute or aria-label
    const latex = element.getAttribute('data-latex') || 
                 element.getAttribute('data-tex') || 
                 element.getAttribute('aria-label') ||
                 element.textContent?.trim() || '';
    if (latex) {
      return {
        type: 'inlineMath',
        attrs: {
          latex: latex
        }
      };
    }
  }
  
  if (tagName === 'div' && element.classList.contains('katex-display')) {
    // Block math - try to extract LaTeX
    const latex = element.getAttribute('data-latex') || 
                 element.getAttribute('data-tex') || 
                 element.getAttribute('aria-label') ||
                 element.textContent?.trim() || '';
    if (latex) {
      return {
        type: 'blockMath',
        attrs: {
          latex: latex
        }
      };
    }
  }

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
      // Filter out empty text nodes but PRESERVE whitespace-only text nodes
      // that appear between other content (these are word separators, e.g., space between bold and link)
      const paragraphContent = content.filter((item, index, arr) => {
        if (item && item.type === 'text') {
          // Remove empty text nodes - not allowed in ProseMirror
          if (item.text === '') {
            return false;
          }
          // For whitespace-only text nodes, only filter if they're at the start or end
          // Whitespace BETWEEN inline elements (like bold and links) must be preserved
          // Example: "**Bold:** [Link](url)" - the space between :</strong> and <a> is important
          if (item.text.trim() === '') {
            // Check if this is leading or trailing whitespace
            const isFirst = index === 0;
            const isLast = index === arr.length - 1;
            
            // Check if there's actual content before/after this whitespace node
            const hasContentBefore = arr.slice(0, index).some(i => i && (i.type !== 'text' || i.text?.trim() !== ''));
            const hasContentAfter = arr.slice(index + 1).some(i => i && (i.type !== 'text' || i.text?.trim() !== ''));
            
            // Remove leading/trailing whitespace, but keep internal whitespace (word separators)
            if (isFirst || isLast || !hasContentBefore || !hasContentAfter) {
              return false;
            }
            // This is whitespace between content - preserve it
            return true;
          }
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
      // Filter out empty text nodes from heading content
      const headingContent = content.filter(item => {
        return !(item && item.type === 'text' && item.text === '');
      });
      return {
        type: 'heading',
        attrs: { level: parseInt(tagName.charAt(1)) },
        content: headingContent.length > 0 ? headingContent : []
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
      
      // Extract language from the code element's class (markdown-it sets it as 'language-xxx')
      // This is critical for matching code blocks with embed nodes
      // Supports ALL programming languages - any valid language identifier after ```
      let language: string | undefined;
      if (codeElement) {
        const classList = codeElement.className.split(' ');
        for (const cls of classList) {
          if (cls.startsWith('language-')) {
            // Extract the language name after 'language-' prefix
            // This handles any language: python, javascript, rust, go, c++, etc.
            language = cls.replace('language-', '');
            break;
          }
        }
      }
      
      // Always include attrs object for consistent structure
      // language can be undefined for plain code blocks (```)
      return {
        type: 'codeBlock',
        attrs: { language: language || undefined },
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
      const target = element.getAttribute('target');

      if (href) {
        // Check if this is an internal hash-based link
        const normalizedHref = href.startsWith('/#') ? href.substring(1) : href;
        const isInternal = normalizedHref.startsWith('#chat-id=') || normalizedHref.includes('#chat-id=');

        // Build link attributes
        let finalHref: string;
        if (isInternal) {
          // For internal links, ensure they start with #
          finalHref = normalizedHref.startsWith('#') ? normalizedHref : '#' + normalizedHref.replace(/^\/+/, '');
        } else {
          // For external links, use the href as-is
          finalHref = href;
        }

        const linkAttrs: Record<string, string> = { href: finalHref };

        // Only include target if it's an external link and target is set
        // For internal links, explicitly do NOT include target
        if (!isInternal && target) {
          linkAttrs.target = target;
        }
        // Internal links should not have target attribute

        return content.map(item => ({
          ...item,
          marks: [...(item.marks || []), { type: 'link', attrs: linkAttrs }]
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
        // Empty list items should have an empty paragraph, not a paragraph with an empty text node
        content: listItemContent.length > 0 ? listItemContent : [{ type: 'paragraph', content: [] }]
      };

    case 'blockquote':
      return {
        type: 'blockquote',
        // Empty blockquotes should have an empty paragraph, not a paragraph with an empty text node
        content: content.length > 0 ? content : [{ type: 'paragraph', content: [] }]
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
        // Empty table headers should have an empty paragraph, not a paragraph with an empty text node
        content: content.length > 0 ? content : [{ type: 'paragraph', content: [] }]
      };

    case 'td':
      return {
        type: 'tableCell',
        // Empty table cells should have an empty paragraph, not a paragraph with an empty text node
        content: content.length > 0 ? content : [{ type: 'paragraph', content: [] }]
      };

    case 'br':
      return { type: 'hardBreak' };

    case 'hr':
      return { type: 'horizontalRule' };

    case 'img':
      // Convert markdown image to embed node for static images
      // This is used for legal document SVG images from the static folder
      const src = element.getAttribute('src');
      const alt = element.getAttribute('alt') || '';
      
      if (src) {
        // Generate a unique ID for the embed node
        // Use a simple UUID-like ID (can't import generateUUID here as it's in a different package)
        const embedId = `img-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
        
        // Check if this is a static file (starts with /images/)
        // Static images should be rendered as embed nodes with type 'image'
        if (src.startsWith('/images/') || src.startsWith('/static/')) {
          return {
            type: 'embed',
            attrs: {
              id: embedId,
              type: 'image',
              status: 'finished',
              contentRef: null,
              url: src, // Use url attribute for the image source
              filename: alt || src.split('/').pop() || 'image.svg' // Use alt text or filename as filename
            }
          };
        }
        
        // For external URLs, also create an embed node
        if (src.startsWith('http://') || src.startsWith('https://')) {
          return {
            type: 'embed',
            attrs: {
              id: embedId,
              type: 'image',
              status: 'finished',
              contentRef: null,
              url: src,
              filename: alt || src.split('/').pop() || 'image'
            }
          };
        }
      }
      
      // If no src, return nothing
      return null;

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

// Helper function to recursively remove empty text nodes from content
// Empty text nodes are not allowed in ProseMirror/Tiptap
function removeEmptyTextNodes(item: any): any {
  if (!item) return item;
  
  // If it's an empty text node, filter it out
  if (item.type === 'text' && item.text === '') {
    return null;
  }
  
  // If the item has content, recursively process it
  if (item.content && Array.isArray(item.content)) {
    const filteredContent = item.content
      .map((child: any) => removeEmptyTextNodes(child))
      .filter((child: any) => child !== null);
    
    return {
      ...item,
      content: filteredContent
    };
  }
  
  return item;
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
    // Return a document with an empty paragraph (no text node)
    // Empty text nodes are not allowed in ProseMirror/Tiptap
    return {
      type: 'doc',
      content: [
        {
          type: 'paragraph',
          content: []
        }
      ]
    };
  }

  try {
    // Pre-process markdown to handle double newlines
    const processedMarkdown = preprocessMarkdown(markdownText);
    // console.log('Preprocessed markdown:', processedMarkdown); // Debug log
    
    // Convert markdown to HTML
    let html = md.render(processedMarkdown);
    // console.log('Generated HTML:', html); // Debug log
    
    // Post-process HTML to remove target="_blank" from internal links
    // This handles cases where markdown-it or other plugins add target="_blank"
    // Use a more robust regex that handles attributes in any order
    html = html.replace(/<a\s+([^>]*?)>/g, (match, attrs) => {
      // Extract href from attributes
      const hrefMatch = attrs.match(/href=["']([^"']*?)["']/);
      if (!hrefMatch) return match; // No href, keep as-is
      
      const href = hrefMatch[1];
      // Check if this is an internal hash-based link
      const normalizedHref = href.startsWith('/#') ? href.substring(1) : href;
      if (normalizedHref.startsWith('#chat-id=') || normalizedHref.includes('#chat-id=')) {
        // Remove target and rel attributes from internal links
        let cleanedAttrs = attrs
          .replace(/\s*target=["'][^"']*["']/gi, '')
          .replace(/\s*rel=["'][^"']*["']/gi, '')
          .trim();
        
        // Normalize href to start with # (not /#)
        const finalHref = normalizedHref.startsWith('#') ? normalizedHref : '#' + normalizedHref.replace(/^\/+/, '');
        
        // Replace href with normalized version
        cleanedAttrs = cleanedAttrs.replace(/href=["'][^"']*["']/, `href="${finalHref}"`);
        
        // Add data-internal attribute for identification
        if (!cleanedAttrs.includes('data-internal')) {
          cleanedAttrs += ' data-internal="true"';
        }
        
        return `<a ${cleanedAttrs}>`;
      }
      return match; // Keep external links as-is
    });
    
    // Convert HTML to TipTap JSON
    const content = htmlToTiptapJson(html);
    // console.log('Converted to TipTap JSON:', content); // Debug log
    
    // Ensure we have a valid document structure
    const docContent = Array.isArray(content) ? content : (content ? [content] : []);
    
    // Filter out null/undefined items and clean the structure
    const filteredContent = docContent.filter(item => item !== null && item !== undefined);
    // Remove any empty text nodes that might have slipped through
    const contentWithoutEmptyText = filteredContent.map(item => removeEmptyTextNodes(item)).filter(item => item !== null);
    const cleanedContent = cleanTiptapDocument(contentWithoutEmptyText);
    
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
