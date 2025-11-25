// Document enhancement with embed nodes
// Handles replacing json_embed blocks with actual embed nodes in TipTap documents

import { EmbedNodeAttributes } from './types';

/**
 * Enhance a TipTap document with unified embed nodes
 * @param doc - The basic TipTap document
 * @param embedNodes - Array of detected embed node attributes
 * @param mode - 'write' or 'read' mode
 * @returns Enhanced TipTap document with unified embed nodes
 */
export function enhanceDocumentWithEmbeds(doc: any, embedNodes: EmbedNodeAttributes[], mode: 'write' | 'read'): any {
  if (!doc || !doc.content) {
    return doc;
  }
  
  // If there are no embed nodes, return the original document
  if (embedNodes.length === 0) {
    return doc;
  }
  
  // For json_embed blocks, we need to replace them in the text, not just append
  let modifiedContent = [...doc.content];
  
  console.debug('[enhanceDocumentWithEmbeds] Processing document with', embedNodes.length, 'individual embed nodes');
  
  // Find and replace embed blocks with embed nodes
  modifiedContent = modifiedContent.map(node => {
    // Handle code blocks that should be replaced with embed nodes
    if (node.type === 'codeBlock') {
      // Try to match this code block with an embed node
      const matchingEmbed = findMatchingEmbedForCodeBlock(node, embedNodes);
      if (matchingEmbed) {
        console.debug('[enhanceDocumentWithEmbeds] Replacing codeBlock with embed node:', matchingEmbed);
        // Wrap embed in a paragraph since embed is an inline node and codeBlock is block-level
        // This prevents ProseMirror schema validation errors (contentMatchAt on a node with invalid content)
        return {
          type: 'paragraph',
          content: [
            {
              type: 'embed',
              attrs: matchingEmbed
            }
          ]
        };
      }
    }

    // Handle paragraphs containing json_embed blocks in text
    if (node.type === 'paragraph' && node.content) {
      const newParagraphContent = [];

      for (const contentNode of node.content) {
        if (contentNode.type === 'text' && contentNode.text) {
          // Split text by json_embed blocks and create appropriate nodes
          const parts = splitTextByJsonEmbedBlocks(contentNode.text, embedNodes);
          newParagraphContent.push(...parts);
        } else {
          newParagraphContent.push(contentNode);
        }
      }

      return {
        ...node,
        content: newParagraphContent
      };
    }
    return node;
  });
  
  return {
    ...doc,
    content: modifiedContent
  };
}

/**
 * Find a matching embed node for a code block
 * @param codeBlockNode - The TipTap codeBlock node
 * @param embedNodes - Array of embed nodes to search
 * @returns The matching embed node or null
 */
function findMatchingEmbedForCodeBlock(codeBlockNode: any, embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes | null {
  // Extract text content from the code block
  const codeText = codeBlockNode.content?.[0]?.text || '';

  console.debug('[findMatchingEmbedForCodeBlock] Checking code block:', {
    codeText: codeText.substring(0, 100),
    hasContent: !!codeText,
    embedNodesCount: embedNodes.length
  });

  if (!codeText.trim()) {
    return null;
  }

  // Try to parse as JSON to check if it's an embed reference
  try {
    const parsed = JSON.parse(codeText.trim());

    console.debug('[findMatchingEmbedForCodeBlock] Parsed JSON:', parsed);

    // Check if this is an embed reference with type and embed_id
    if (parsed.type && parsed.embed_id) {
      // Find matching embed node by checking contentRef
      const matchingEmbed = embedNodes.find(node => {
        const expectedContentRef = `embed:${parsed.embed_id}`;
        console.debug('[findMatchingEmbedForCodeBlock] Comparing:', {
          expectedContentRef,
          nodeContentRef: node.contentRef,
          matches: node.contentRef === expectedContentRef
        });
        return node.contentRef === expectedContentRef;
      });

      if (matchingEmbed) {
        console.debug('[findMatchingEmbedForCodeBlock] Found matching embed for JSON block:', {
          type: parsed.type,
          embed_id: parsed.embed_id,
          embedNodeId: matchingEmbed.id,
          embedNodeType: matchingEmbed.type
        });
        return matchingEmbed;
      } else {
        console.warn('[findMatchingEmbedForCodeBlock] No matching embed found for:', {
          type: parsed.type,
          embed_id: parsed.embed_id,
          availableEmbeds: embedNodes.map(n => ({ id: n.id, type: n.type, contentRef: n.contentRef }))
        });
      }
    }
  } catch (error) {
    // Not JSON, might be a regular code block
    console.debug('[findMatchingEmbedForCodeBlock] Not JSON, treating as code block');
  }

  // Check if this is a code-code embed (code snippet with language)
  // Match by checking if there's a code-code embed with similar content
  const codeEmbeds = embedNodes.filter(node => node.type === 'code-code');
  if (codeEmbeds.length > 0 && codeBlockNode.attrs?.language) {
    // Try to find a match by language and approximate content
    const matchingCodeEmbed = codeEmbeds.find(embed =>
      embed.language === codeBlockNode.attrs.language
    );

    if (matchingCodeEmbed) {
      console.debug('[findMatchingEmbedForCodeBlock] Found matching code embed:', {
        language: matchingCodeEmbed.language,
        embedNodeId: matchingCodeEmbed.id
      });
      // Remove from array to prevent reuse
      const index = embedNodes.indexOf(matchingCodeEmbed);
      if (index > -1) {
        embedNodes.splice(index, 1);
      }
      return matchingCodeEmbed;
    }
  }

  return null;
}

/**
 * Split text content by json_embed blocks and replace them with embed nodes
 * @param text - The text content that may contain json_embed blocks
 * @param embedNodes - Array of embed nodes to use for replacement
 * @returns Array of text nodes and embed nodes
 */
function splitTextByJsonEmbedBlocks(text: string, embedNodes: EmbedNodeAttributes[]): any[] {
  const result = [];
  
  // Filter to only get website embed nodes that came from json_embed blocks
  const webEmbedNodes = embedNodes.filter(node => node.type === 'web-website');
  
  // If no web embed nodes, return the original text
  if (webEmbedNodes.length === 0) {
    result.push({
      type: 'text',
      text: text
    });
    return result;
  }
  
  // Find all json_embed blocks in the text and match them with embed nodes
  const jsonEmbedRegex = /```json_embed\n[\s\S]*?\n```/g;
  const embedMatches: { match: RegExpExecArray; embedNode: EmbedNodeAttributes }[] = [];
  let match;
  
  // Reset regex lastIndex to ensure we get all matches
  jsonEmbedRegex.lastIndex = 0;
  
  while ((match = jsonEmbedRegex.exec(text)) !== null) {
    try {
      // Extract and parse the json content to match with the right embed node
      const jsonContent = match[0].match(/```json_embed\n([\s\S]*?)\n```/)?.[1];
      if (jsonContent) {
        const parsed = JSON.parse(jsonContent);
        
        // Find the corresponding embed node by URL (use the first available match)
        // Remove used embed nodes to handle multiple instances of the same URL correctly
        const correspondingEmbedNodeIndex = webEmbedNodes.findIndex(node => node.url === parsed.url);
        if (correspondingEmbedNodeIndex !== -1) {
          const correspondingEmbedNode = webEmbedNodes[correspondingEmbedNodeIndex];
          // Remove the used embed node to prevent reuse
          webEmbedNodes.splice(correspondingEmbedNodeIndex, 1);
          
          embedMatches.push({ match, embedNode: correspondingEmbedNode });
          console.debug('[splitTextByJsonEmbedBlocks] Matched json_embed block with embed node:', {
            url: parsed.url,
            embedNodeId: correspondingEmbedNode.id,
            remainingEmbedNodes: webEmbedNodes.length
          });
        } else {
          console.warn('[splitTextByJsonEmbedBlocks] No matching embed node found for URL:', parsed.url);
        }
      }
    } catch (error) {
      console.warn('[splitTextByJsonEmbedBlocks] Error parsing json_embed block:', error);
      // Still try to match by order if parsing fails and we have remaining nodes
      if (webEmbedNodes.length > 0) {
        const fallbackEmbedNode = webEmbedNodes.shift()!; // Remove the first available node
        embedMatches.push({ match, embedNode: fallbackEmbedNode });
        console.debug('[splitTextByJsonEmbedBlocks] Used fallback matching for json_embed block');
      }
    }
  }
  
  // If no matches found, return original text
  if (embedMatches.length === 0) {
    result.push({
      type: 'text',
      text: text
    });
    return result;
  }
  
  // Sort matches by position to process them in order
  embedMatches.sort((a, b) => a.match.index - b.match.index);
  
  let lastIndex = 0;
  
  for (const { match, embedNode } of embedMatches) {
    // Add text before the json_embed block
    if (match.index > lastIndex) {
      const beforeText = text.substring(lastIndex, match.index);
      if (beforeText.trim() || beforeText.includes('\n')) {
        result.push({
          type: 'text',
          text: beforeText
        });
      }
    }
    
    console.debug('[splitTextByJsonEmbedBlocks] Replacing json_embed block with embed node:', embedNode);
    
    // Add the corresponding embed node
    result.push({
      type: 'embed',
      attrs: embedNode
    });
    
    // Add a hard break after the embed to force cursor to next line
    result.push({
      type: 'hardBreak'
    });
    
    lastIndex = match.index + match[0].length;
  }
  
  // Add remaining text after the last json_embed block
  if (lastIndex < text.length) {
    const afterText = text.substring(lastIndex);
    if (afterText.trim() || afterText.includes('\n')) {
      result.push({
        type: 'text',
        text: afterText
      });
    }
  }
  
  // If no content was added, ensure we have at least the original text
  if (result.length === 0) {
    result.push({
      type: 'text',
      text: text
    });
  }
  
  return result;
}
