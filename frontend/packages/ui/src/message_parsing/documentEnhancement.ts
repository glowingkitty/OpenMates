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
  
  // Find and replace json_embed blocks with embed nodes
  modifiedContent = modifiedContent.map(node => {
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
