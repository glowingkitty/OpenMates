// Generic embed grouping functionality
// Handles grouping consecutive embeds of the same type at the document level

import { EmbedNodeAttributes } from './types';
import { generateUUID } from './utils';
import { groupHandlerRegistry } from './groupHandlers';

/**
 * Group consecutive embeds of the same type in a TipTap document structure
 * This function operates on the actual document to accurately determine what's consecutive
 * @param doc - TipTap document with individual embed nodes
 * @returns TipTap document with grouped consecutive embeds
 */
export function groupConsecutiveEmbedsInDocument(doc: any): any {
  if (!doc || !doc.content) {
    return doc;
  }
  
  console.debug('[groupConsecutiveEmbedsInDocument] Processing document');
  
  // Process each top-level content node (paragraphs, etc.)
  const modifiedContent = doc.content.map((contentNode: any) => {
    if (contentNode.type === 'paragraph' && contentNode.content) {
      return groupConsecutiveEmbedsInParagraph(contentNode);
    }
    return contentNode;
  });
  
  return {
    ...doc,
    content: modifiedContent
  };
}

/**
 * Group consecutive embeds of the same type within a paragraph
 * @param paragraph - TipTap paragraph node
 * @returns Modified paragraph with grouped embeds
 */
function groupConsecutiveEmbedsInParagraph(paragraph: any): any {
  if (!paragraph.content || paragraph.content.length === 0) {
    return paragraph;
  }
  
  const newContent: any[] = [];
  let currentGroup: any[] = [];
  let currentGroupType: string | null = null;
  
  for (let i = 0; i < paragraph.content.length; i++) {
    const node = paragraph.content[i];
    
    if (node.type === 'embed') {
      const embedType = node.attrs.type;
      
      // Check if this embed can continue the current group
      if (currentGroupType === embedType && currentGroup.length > 0) {
        // Same type - check if they can actually be grouped using the handler
        const canGroupWithLast = groupHandlerRegistry.canGroup(
          currentGroup[currentGroup.length - 1].attrs,
          node.attrs
        );
        
        if (canGroupWithLast) {
          // Can be grouped, add to current group
          currentGroup.push(node);
          console.debug('[groupConsecutiveEmbedsInParagraph] Added embed to group:', { 
            type: embedType,
            identifier: node.attrs.url || node.attrs.filename || node.attrs.title || node.attrs.id,
            groupSize: currentGroup.length 
          });
        } else {
          // Same type but can't be grouped (e.g., different language for code)
          // Flush current group and start new one
          if (currentGroup.length > 0) {
            const groupedNode = flushEmbedGroup(currentGroup, currentGroupType!);
            newContent.push(...groupedNode);
          }
          
          // Start new group
          currentGroup = [node];
          currentGroupType = embedType;
          console.debug('[groupConsecutiveEmbedsInParagraph] Started new group (different grouping criteria):', { 
            type: embedType,
            identifier: node.attrs.url || node.attrs.filename || node.attrs.title || node.attrs.id
          });
        }
      } else {
        // Different type, flush current group and start new one
        if (currentGroup.length > 0) {
          const groupedNode = flushEmbedGroup(currentGroup, currentGroupType!);
          newContent.push(...groupedNode);
        }
        
        // Start new group
        currentGroup = [node];
        currentGroupType = embedType;
        console.debug('[groupConsecutiveEmbedsInParagraph] Started new group:', { 
          type: embedType,
          identifier: node.attrs.url || node.attrs.filename || node.attrs.title || node.attrs.id
        });
      }
    } else if (node.type === 'text' && node.text.trim() === '') {
      // Empty text or whitespace - don't break the group, skip this node
      continue;
    } else {
      // Non-embed node with content, flush current group if it exists
      if (currentGroup.length > 0) {
        const groupedNode = flushEmbedGroup(currentGroup, currentGroupType!);
        newContent.push(...groupedNode);
        currentGroup = [];
        currentGroupType = null;
      }
      
      // Add the non-embed node
      newContent.push(node);
    }
  }
  
  // Flush any remaining group
  if (currentGroup.length > 0) {
    const groupedNode = flushEmbedGroup(currentGroup, currentGroupType!);
    newContent.push(...groupedNode);
  }
  
  return {
    ...paragraph,
    content: newContent
  };
}

/**
 * Flush a group of consecutive embed nodes, creating a group if there are multiple items
 * @param group - Array of consecutive embed nodes
 * @param embedType - The type of embeds in this group
 * @returns Array with either individual embeds or a group embed
 */
function flushEmbedGroup(group: any[], embedType: string): any[] {
  if (group.length === 1) {
    // Single embed - return as is
    console.debug('[flushEmbedGroup] Single embed, no grouping needed:', embedType);
    return group;
  }
  
  if (group.length > 1) {
    // Multiple embeds - create a group using the appropriate handler
    console.debug('[flushEmbedGroup] Creating group for', group.length, embedType, 'embeds');
    
    // Extract the embed attributes from the nodes
    const embedAttrs = group.map(node => node.attrs);
    
    // Use the group handler to create the group
    const groupAttrs = groupHandlerRegistry.createGroup(embedAttrs);
    
    if (groupAttrs) {
      const groupEmbed = {
        type: 'embed',
        attrs: groupAttrs
      };
      
      console.debug('[flushEmbedGroup] Created embed group using handler:', {
        groupId: groupAttrs.id,
        groupType: groupAttrs.type,
        itemCount: groupAttrs.groupCount,
        items: embedAttrs.map(item => ({
          type: item.type,
          identifier: item.url || item.filename || item.title || item.id
        }))
      });
      
      return [groupEmbed];
    } else {
      console.warn('[flushEmbedGroup] No group handler found for embed type:', embedType);
      // Fallback: return individual embeds
      return group;
    }
  }
  
  return [];
}

// Legacy functions removed - use groupConsecutiveEmbedsInDocument for all grouping
