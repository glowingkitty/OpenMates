// Generic embed grouping functionality
// Handles grouping consecutive embeds of the same type at the document level

import { EmbedNodeAttributes } from './types';
import { generateUUID } from './utils';

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
      if (currentGroupType === embedType) {
        // Same type, add to current group
        currentGroup.push(node);
        console.debug('[groupConsecutiveEmbedsInParagraph] Added embed to group:', { 
          type: embedType,
          identifier: node.attrs.url || node.attrs.filename || node.attrs.title || node.attrs.id,
          groupSize: currentGroup.length 
        });
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
    // Multiple embeds - create a group
    console.debug('[flushEmbedGroup] Creating group for', group.length, embedType, 'embeds');
    
    // Extract the embed attributes from the nodes
    const embedAttrs = group.map(node => node.attrs);
    
    // Sort according to status: processing first, then finished
    const sortedEmbeds = [...embedAttrs].sort((a, b) => {
      if (a.status === 'processing' && b.status !== 'processing') return -1;
      if (a.status !== 'processing' && b.status === 'processing') return 1;
      return 0; // Keep original order for same status
    });
    
    const groupId = generateUUID();
    const groupEmbed = {
      type: 'embed',
      attrs: {
        id: groupId,
        type: `${embedType}-group`, // e.g., 'website-group', 'code-group', 'doc-group'
        status: 'finished',
        contentRef: null,
        // Store the grouped items as a custom property
        groupedItems: sortedEmbeds,
        // Add count information for the header
        groupCount: sortedEmbeds.length
      }
    };
    
    console.debug('[flushEmbedGroup] Created embed group:', {
      groupId,
      groupType: `${embedType}-group`,
      itemCount: sortedEmbeds.length,
      items: sortedEmbeds.map(item => ({
        type: item.type,
        identifier: item.url || item.filename || item.title || item.id
      }))
    });
    
    return [groupEmbed];
  }
  
  return [];
}

/**
 * Group consecutive website embeds into website-preview-group containers (legacy function)
 * @param embedNodes - Array of embed nodes to process
 * @returns Array with individual embeds and grouped website embeds
 * @deprecated Use groupConsecutiveEmbedsInDocument for proper document-level grouping
 */
export function groupConsecutiveWebsiteEmbeds(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes[] {
  if (embedNodes.length === 0) return embedNodes;
  
  console.debug('[groupConsecutiveWebsiteEmbeds] Input embeds:', embedNodes.map(embed => ({ type: embed.type, url: embed.url })));
  
  const result: EmbedNodeAttributes[] = [];
  let currentGroup: EmbedNodeAttributes[] = [];
  
  for (let i = 0; i < embedNodes.length; i++) {
    const embed = embedNodes[i];
    
    // TODO rename 'video' to 'web-video' type 
    if (embed.type === 'website' || embed.type === 'video') {
      // Add to current group
      currentGroup.push(embed);
      console.debug('[groupConsecutiveWebsiteEmbeds] Added to group:', { type: embed.type, url: embed.url, groupSize: currentGroup.length });
    } else {
      // Non-website embed, flush current group if it exists
      if (currentGroup.length > 0) {
        console.debug('[groupConsecutiveWebsiteEmbeds] Flushing group of size:', currentGroup.length);
        result.push(...flushWebsiteGroup(currentGroup));
        currentGroup = [];
      }
      result.push(embed);
    }
  }
  
  // Flush any remaining group
  if (currentGroup.length > 0) {
    console.debug('[groupConsecutiveWebsiteEmbeds] Flushing final group of size:', currentGroup.length);
    result.push(...flushWebsiteGroup(currentGroup));
  }
  
  console.debug('[groupConsecutiveWebsiteEmbeds] Final result:', result.map(embed => ({ type: embed.type, url: embed.url, groupCount: embed.groupCount })));
  
  return result;
}

/**
 * Flush a group of website embeds, creating a group if there are multiple items (legacy function)
 * @param group - Array of consecutive website embeds
 * @returns Array with either individual embeds or a group embed
 */
function flushWebsiteGroup(group: EmbedNodeAttributes[]): EmbedNodeAttributes[] {
  if (group.length === 1) {
    // Single website embed - return as is
    return group;
  }
  
  if (group.length > 1) {
    // Multiple website embeds - create a group
    // Sort according to web.md: processing first, then finished
    const sortedGroup = [...group].sort((a, b) => {
      if (a.status === 'processing' && b.status !== 'processing') return -1;
      if (a.status !== 'processing' && b.status === 'processing') return 1;
      return 0; // Keep original order for same status
    });
    
    const groupId = generateUUID();
    const groupEmbed: EmbedNodeAttributes = {
      id: groupId,
      type: 'website-group',
      status: 'finished',
      contentRef: null,
      // Store the grouped items as a custom property
      groupedItems: sortedGroup,
      // Add count information for the header
      groupCount: sortedGroup.length
    };
    
    console.debug('[flushWebsiteGroup] Created website group:', {
      groupId,
      itemCount: sortedGroup.length,
      urls: sortedGroup.map(item => item.url)
    });
    
    return [groupEmbed];
  }
  
  return [];
}
