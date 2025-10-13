// Generic group handler system for embed grouping
// Provides extensible interfaces for different embed type grouping behaviors

import { EmbedNodeAttributes } from './types';

/**
 * Interface for handling specific embed type grouping behavior
 */
export interface EmbedGroupHandler {
  /**
   * The embed type this handler manages (e.g., 'website', 'code', 'doc')
   */
  embedType: string;
  
  /**
   * Determine if two embed nodes can be grouped together
   * @param nodeA - First embed node
   * @param nodeB - Second embed node
   * @returns true if they can be grouped, false otherwise
   */
  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean;
  
  /**
   * Create a group embed node from multiple individual embed nodes
   * @param embedNodes - Array of individual embed nodes to group
   * @returns Group embed node attributes
   */
  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes;
  
  /**
   * Handle backspace behavior for group nodes
   * @param groupAttrs - The group embed node attributes
   * @returns Backspace action result
   */
  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult;
  
  /**
   * Convert group back to markdown (for serialization)
   * @param groupAttrs - The group embed node attributes
   * @returns Markdown representation
   */
  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string;
}

/**
 * Result of a group backspace operation
 */
export interface GroupBackspaceResult {
  /**
   * Action type to perform
   */
  action: 'delete-group' | 'split-group' | 'convert-to-text';
  
  /**
   * Content to replace the group with (for TipTap)
   */
  replacementContent?: any[];
  
  /**
   * Plain text to replace with (fallback)
   */
  replacementText?: string;
}

/**
 * Web website embed group handler
 */
export class WebWebsiteGroupHandler implements EmbedGroupHandler {
  embedType = 'web-website';
  
  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    // Web website embeds can only be grouped with other web website embeds
    return nodeA.type === 'web-website' && nodeB.type === 'web-website';
  }
  
  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes {
    // Sort according to status: processing first, then finished
    const sortedEmbeds = [...embedNodes].sort((a, b) => {
      if (a.status === 'processing' && b.status !== 'processing') return -1;
      if (a.status !== 'processing' && b.status === 'processing') return 1;
      return 0; // Keep original order for same status
    });
    
    // Extract only the essential, serializable attributes for groupedItems
    const serializableGroupedItems = sortedEmbeds.map(embed => ({
      id: embed.id,
      type: embed.type as any, // Type assertion to avoid complex type issues
      status: embed.status as 'processing' | 'finished', // Type assertion for status
      contentRef: embed.contentRef,
      url: embed.url,
      title: embed.title,
      description: embed.description,
      favicon: embed.favicon,
      image: embed.image
    }));
    
    console.log('[WebWebsiteGroupHandler] Creating group with items:', serializableGroupedItems);
    
    const result = {
      id: this.generateGroupId(),
      type: 'web-website-group',
      status: 'finished',
      contentRef: null,
      groupedItems: serializableGroupedItems,
      groupCount: sortedEmbeds.length
    } as EmbedNodeAttributes;
    
    console.log('[WebWebsiteGroupHandler] Created group:', result);
    return result;
  }
  
  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult {
    const groupedItems = groupAttrs.groupedItems || [];
    
    if (groupedItems.length > 2) {
      // For groups with >2 items: keep remaining items grouped, show last one in edit mode
      const remainingItems = groupedItems.slice(0, -1);
      const lastItem = groupedItems[groupedItems.length - 1];
      
      // Create a new group with the remaining items
      const remainingGroupAttrs = this.createGroup(remainingItems);
      
      // Build the replacement content: group + editable text
      const replacementContent: any[] = [
        {
          type: 'embed',
          attrs: remainingGroupAttrs
        },
        { type: 'text', text: ' ' }, // Space between group and editable text
        { type: 'text', text: lastItem.url || '' }, // Last item as editable text
        { type: 'hardBreak' } // Hard break after editable text
      ];
      
      return {
        action: 'split-group',
        replacementContent
      };
    } else if (groupedItems.length === 2) {
      // For groups with 2 items: split into individual items, show last one in edit mode
      const firstItem = groupedItems[0];
      const lastItem = groupedItems[groupedItems.length - 1];
      
      // Create individual embed nodes for the remaining items
      const replacementContent: any[] = [
        {
          type: 'embed',
          attrs: {
            ...firstItem,
            type: 'web-website' // Convert back to individual web website embed
          }
        },
        { type: 'text', text: ' ' }, // Space between embeds
        { type: 'text', text: lastItem.url || '' }, // Last item as editable text
        { type: 'hardBreak' } // Hard break after editable text
      ];
      
      return {
        action: 'split-group',
        replacementContent
      };
    } else if (groupedItems.length === 1) {
      // Single item group - convert to URL for editing
      const singleItem = groupedItems[0];
      return {
        action: 'convert-to-text',
        replacementText: (singleItem.url || '') + '\n\n'
      };
    }
    
    // Empty group - just delete
    return {
      action: 'delete-group'
    };
  }
  
  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    // Serialize web website groups back to individual json_embed blocks separated by newlines
    const groupedItems = groupAttrs.groupedItems || [];
    return groupedItems.map(item => {
      const websiteData: any = {
        type: 'website',
        url: item.url
      };
      
      // Add optional metadata if available
      if (item.title) websiteData.title = item.title;
      if (item.description) websiteData.description = item.description;
      if (item.favicon) websiteData.favicon = item.favicon;
      if (item.image) websiteData.image = item.image;
      
      const jsonContent = JSON.stringify(websiteData, null, 2);
      return `\`\`\`json_embed\n${jsonContent}\n\`\`\``;
    }).join('\n\n');
  }
  
  private generateGroupId(): string {
    return 'group_' + Math.random().toString(36).substr(2, 9);
  }
}

/**
 * Videos video embed group handler
 */
export class VideosVideoGroupHandler implements EmbedGroupHandler {
  embedType = 'videos-video';
  
  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    // Videos video embeds can be grouped together
    return nodeA.type === 'videos-video' && nodeB.type === 'videos-video';
  }
  
  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes {
    // Sort according to status: processing first, then finished
    const sortedEmbeds = [...embedNodes].sort((a, b) => {
      if (a.status === 'processing' && b.status !== 'processing') return -1;
      if (a.status !== 'processing' && b.status === 'processing') return 1;
      return 0; // Keep original order for same status
    });
    
    // Extract only the essential, serializable attributes for groupedItems
    const serializableGroupedItems = sortedEmbeds.map(embed => ({
      id: embed.id,
      type: embed.type,
      status: embed.status,
      contentRef: embed.contentRef,
      url: embed.url,
      title: embed.title
    }));
    
    return {
      id: this.generateGroupId(),
      type: 'videos-video-group',
      status: 'finished',
      contentRef: null,
      groupedItems: serializableGroupedItems,
      groupCount: sortedEmbeds.length
    };
  }
  
  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult {
    const groupedItems = groupAttrs.groupedItems || [];
    
    if (groupedItems.length > 2) {
      // For groups with >2 items: keep remaining items grouped, show last one in edit mode
      const remainingItems = groupedItems.slice(0, -1);
      const lastItem = groupedItems[groupedItems.length - 1];
      
      // Create a new group with the remaining items
      const remainingGroupAttrs = this.createGroup(remainingItems);
      
      // Build the replacement content: group + editable text
      const replacementContent: any[] = [
        {
          type: 'embed',
          attrs: remainingGroupAttrs
        },
        { type: 'text', text: ' ' }, // Space between group and editable text
        { type: 'text', text: lastItem.url || '' }, // Last item as editable text
        { type: 'hardBreak' } // Hard break after editable text
      ];
      
      return {
        action: 'split-group',
        replacementContent
      };
    } else if (groupedItems.length === 2) {
      // For groups with 2 items: split into individual items, show last one in edit mode
      const firstItem = groupedItems[0];
      const lastItem = groupedItems[groupedItems.length - 1];
      
      // Create individual embed nodes for the remaining items
      const replacementContent: any[] = [
        {
          type: 'embed',
          attrs: {
            ...firstItem,
            type: 'videos-video' // Convert back to individual videos video embed
          }
        },
        { type: 'text', text: ' ' }, // Space between embeds
        { type: 'text', text: lastItem.url || '' }, // Last item as editable text
        { type: 'hardBreak' } // Hard break after editable text
      ];
      
      return {
        action: 'split-group',
        replacementContent
      };
    } else if (groupedItems.length === 1) {
      // Single item group - convert to URL for editing
      const singleItem = groupedItems[0];
      return {
        action: 'convert-to-text',
        replacementText: (singleItem.url || '') + '\n\n'
      };
    }
    
    // Empty group - just delete
    return {
      action: 'delete-group'
    };
  }
  
  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    // Serialize videos video groups back to individual URLs separated by spaces
    const groupedItems = groupAttrs.groupedItems || [];
    return groupedItems.map(item => item.url || '').filter(url => url).join(' ');
  }
  
  private generateGroupId(): string {
    return 'group_' + Math.random().toString(36).substr(2, 9);
  }
}

/**
 * Code code embed group handler
 */
export class CodeCodeGroupHandler implements EmbedGroupHandler {
  embedType = 'code-code';
  
  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    // Code code embeds can be grouped together regardless of language
    return nodeA.type === 'code-code' && nodeB.type === 'code-code';
  }
  
  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes {
    const sortedEmbeds = [...embedNodes].sort((a, b) => {
      if (a.status === 'processing' && b.status !== 'processing') return -1;
      if (a.status !== 'processing' && b.status === 'processing') return 1;
      return 0;
    });
    
    // Extract only the essential, serializable attributes for groupedItems
    const serializableGroupedItems = sortedEmbeds.map(embed => ({
      id: embed.id,
      type: embed.type,
      status: embed.status,
      contentRef: embed.contentRef,
      language: embed.language,
      filename: embed.filename
    }));
    
    return {
      id: this.generateGroupId(),
      type: 'code-code-group',
      status: 'finished',
      contentRef: null,
      groupedItems: serializableGroupedItems,
      groupCount: sortedEmbeds.length
    };
  }
  
  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult {
    const groupedItems = groupAttrs.groupedItems || [];
    
    if (groupedItems.length > 2) {
      // For groups with >2 items: keep remaining items grouped, show last one in edit mode
      const remainingItems = groupedItems.slice(0, -1);
      const lastItem = groupedItems[groupedItems.length - 1];
      
      // Create a new group with the remaining items
      const remainingGroupAttrs = this.createGroup(remainingItems);
      
      // Convert last item to code fence for editing
      const language = lastItem.language || '';
      const filename = lastItem.filename ? `:${lastItem.filename}` : '';
      const lastItemMarkdown = `\`\`\`${language}${filename}\n\`\`\``;
      
      // Build the replacement content: group + editable text
      const replacementContent: any[] = [
        {
          type: 'embed',
          attrs: remainingGroupAttrs
        },
        { type: 'text', text: '\n\n' }, // Newlines between group and editable text
        { type: 'text', text: lastItemMarkdown }
      ];
      
      return {
        action: 'split-group',
        replacementContent
      };
    } else if (groupedItems.length === 2) {
      // For groups with 2 items: split into individual items, show last one in edit mode
      const firstItem = groupedItems[0];
      const lastItem = groupedItems[groupedItems.length - 1];
      
      // Create individual embed nodes for the remaining items
      const replacementContent: any[] = [
        {
          type: 'embed',
          attrs: {
            ...firstItem,
            type: 'code-code'
          }
        },
        { type: 'text', text: '\n\n' }, // Newlines between embeds
        { type: 'text', text: `\`\`\`${lastItem.language || ''}${lastItem.filename ? ':' + lastItem.filename : ''}\n\`\`\`` }
      ];
      
      return {
        action: 'split-group',
        replacementContent
      };
    } else if (groupedItems.length === 1) {
      const singleItem = groupedItems[0];
      const language = singleItem.language || '';
      const filename = singleItem.filename ? `:${singleItem.filename}` : '';
      return {
        action: 'convert-to-text',
        replacementText: `\`\`\`${language}${filename}\n\`\`\`\n\n`
      };
    }
    
    return { action: 'delete-group' };
  }
  
  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    const groupedItems = groupAttrs.groupedItems || [];
    return groupedItems.map(item => {
      const language = item.language || '';
      const filename = item.filename ? `:${item.filename}` : '';
      return `\`\`\`${language}${filename}\n\`\`\``;
    }).join('\n\n');
  }
  
  private generateGroupId(): string {
    return 'group_' + Math.random().toString(36).substr(2, 9);
  }
}

/**
 * Docs doc embed group handler
 */
export class DocsDocGroupHandler implements EmbedGroupHandler {
  embedType = 'docs-doc';
  
  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    // Docs doc embeds can always be grouped together
    return nodeA.type === 'docs-doc' && nodeB.type === 'docs-doc';
  }
  
  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes {
    const sortedEmbeds = [...embedNodes].sort((a, b) => {
      if (a.status === 'processing' && b.status !== 'processing') return -1;
      if (a.status !== 'processing' && b.status === 'processing') return 1;
      return 0;
    });
    
    // Extract only the essential, serializable attributes for groupedItems
    const serializableGroupedItems = sortedEmbeds.map(embed => ({
      id: embed.id,
      type: embed.type,
      status: embed.status,
      contentRef: embed.contentRef,
      title: embed.title
    }));
    
    return {
      id: this.generateGroupId(),
      type: 'docs-doc-group',
      status: 'finished',
      contentRef: null,
      groupedItems: serializableGroupedItems,
      groupCount: sortedEmbeds.length
    };
  }
  
  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult {
    const groupedItems = groupAttrs.groupedItems || [];
    
    if (groupedItems.length > 2) {
      // For groups with >2 items: keep remaining items grouped, show last one in edit mode
      const remainingItems = groupedItems.slice(0, -1);
      const lastItem = groupedItems[groupedItems.length - 1];
      
      // Create a new group with the remaining items
      const remainingGroupAttrs = this.createGroup(remainingItems);
      
      // Convert last item to document_html fence for editing
      const title = lastItem.title ? `<!-- title: "${lastItem.title}" -->\n` : '';
      const lastItemMarkdown = `\`\`\`document_html\n${title}\`\`\``;
      
      // Build the replacement content: group + editable text
      const replacementContent: any[] = [
        {
          type: 'embed',
          attrs: remainingGroupAttrs
        },
        { type: 'text', text: '\n\n' }, // Newlines between group and editable text
        { type: 'text', text: lastItemMarkdown }
      ];
      
      return {
        action: 'split-group',
        replacementContent
      };
    } else if (groupedItems.length === 2) {
      // For groups with 2 items: split into individual items, show last one in edit mode
      const firstItem = groupedItems[0];
      const lastItem = groupedItems[groupedItems.length - 1];
      
      // Create individual embed nodes for the remaining items
      const replacementContent: any[] = [
        {
          type: 'embed',
          attrs: {
            ...firstItem,
            type: 'docs-doc'
          }
        },
        { type: 'text', text: '\n\n' }, // Newlines between embeds
        { type: 'text', text: `\`\`\`document_html\n${lastItem.title ? `<!-- title: "${lastItem.title}" -->\n` : ''}\`\`\`` }
      ];
      
      return {
        action: 'split-group',
        replacementContent
      };
    } else if (groupedItems.length === 1) {
      const singleItem = groupedItems[0];
      const title = singleItem.title ? `<!-- title: "${singleItem.title}" -->\n` : '';
      return {
        action: 'convert-to-text',
        replacementText: `\`\`\`document_html\n${title}\`\`\`\n\n`
      };
    }
    
    return { action: 'delete-group' };
  }
  
  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    const groupedItems = groupAttrs.groupedItems || [];
    return groupedItems.map(item => {
      const title = item.title ? `<!-- title: "${item.title}" -->\n` : '';
      return `\`\`\`document_html\n${title}\`\`\``;
    }).join('\n\n');
  }
  
  private generateGroupId(): string {
    return 'group_' + Math.random().toString(36).substr(2, 9);
  }
}

/**
 * Sheets sheet embed group handler
 */
export class SheetsSheetGroupHandler implements EmbedGroupHandler {
  embedType = 'sheets-sheet';
  
  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    // Sheets sheet embeds can always be grouped together
    return nodeA.type === 'sheets-sheet' && nodeB.type === 'sheets-sheet';
  }
  
  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes {
    const sortedEmbeds = [...embedNodes].sort((a, b) => {
      if (a.status === 'processing' && b.status !== 'processing') return -1;
      if (a.status !== 'processing' && b.status === 'processing') return 1;
      return 0;
    });
    
    // Extract only the essential, serializable attributes for groupedItems
    const serializableGroupedItems = sortedEmbeds.map(embed => ({
      id: embed.id,
      type: embed.type,
      status: embed.status,
      contentRef: embed.contentRef,
      title: embed.title,
      rows: embed.rows,
      cols: embed.cols
    }));
    
    return {
      id: this.generateGroupId(),
      type: 'sheets-sheet-group',
      status: 'finished',
      contentRef: null,
      groupedItems: serializableGroupedItems,
      groupCount: sortedEmbeds.length
    };
  }
  
  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult {
    const groupedItems = groupAttrs.groupedItems || [];
    
    if (groupedItems.length > 2) {
      // For groups with >2 items: keep remaining items grouped, show last one in edit mode
      const remainingItems = groupedItems.slice(0, -1);
      const lastItem = groupedItems[groupedItems.length - 1];
      
      // Create a new group with the remaining items
      const remainingGroupAttrs = this.createGroup(remainingItems);
      
      // Convert last item to table markdown for editing
      const title = lastItem.title ? `<!-- title: "${lastItem.title}" -->\n` : '';
      const lastItemMarkdown = `${title}| Column 1 | Column 2 |\n|----------|----------|\n| Data     | Data     |`;
      
      // Build the replacement content: group + editable text
      const replacementContent: any[] = [
        {
          type: 'embed',
          attrs: remainingGroupAttrs
        },
        { type: 'text', text: '\n\n' }, // Newlines between group and editable text
        { type: 'text', text: lastItemMarkdown }
      ];
      
      return {
        action: 'split-group',
        replacementContent
      };
    } else if (groupedItems.length === 2) {
      // For groups with 2 items: split into individual items, show last one in edit mode
      const firstItem = groupedItems[0];
      const lastItem = groupedItems[groupedItems.length - 1];
      
      // Create individual embed nodes for the remaining items
      const replacementContent: any[] = [
        {
          type: 'embed',
          attrs: {
            ...firstItem,
            type: 'sheets-sheet'
          }
        },
        { type: 'text', text: '\n\n' }, // Newlines between embeds
        { type: 'text', text: `${lastItem.title ? `<!-- title: "${lastItem.title}" -->\n` : ''}| Column 1 | Column 2 |\n|----------|----------|\n| Data     | Data     |` }
      ];
      
      return {
        action: 'split-group',
        replacementContent
      };
    } else if (groupedItems.length === 1) {
      const singleItem = groupedItems[0];
      const title = singleItem.title ? `<!-- title: "${singleItem.title}" -->\n` : '';
      return {
        action: 'convert-to-text',
        replacementText: `${title}| Column 1 | Column 2 |\n|----------|----------|\n| Data     | Data     |\n\n`
      };
    }
    
    return { action: 'delete-group' };
  }
  
  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    const groupedItems = groupAttrs.groupedItems || [];
    return groupedItems.map(item => {
      const title = item.title ? `<!-- title: "${item.title}" -->\n` : '';
      return `${title}| Column 1 | Column 2 |\n|----------|----------|\n| Data     | Data     |`;
    }).join('\n\n');
  }
  
  private generateGroupId(): string {
    return 'group_' + Math.random().toString(36).substr(2, 9);
  }
}



/**
 * Registry of group handlers
 */
export class GroupHandlerRegistry {
  private handlers = new Map<string, EmbedGroupHandler>();
  
  constructor() {
    // Register supported embed type handlers
    this.register(new WebWebsiteGroupHandler());
    this.register(new VideosVideoGroupHandler());
    this.register(new CodeCodeGroupHandler());
    this.register(new DocsDocGroupHandler());
    this.register(new SheetsSheetGroupHandler());
  }
  
  /**
   * Register a new group handler
   */
  register(handler: EmbedGroupHandler): void {
    this.handlers.set(handler.embedType, handler);
    console.debug(`[GroupHandlerRegistry] Registered handler for embed type: ${handler.embedType}`);
  }
  
  /**
   * Get handler for a specific embed type
   */
  getHandler(embedType: string): EmbedGroupHandler | null {
    return this.handlers.get(embedType) || null;
  }
  
  /**
   * Get handler for a group type (e.g., 'website-group' -> 'website' handler)
   */
  getHandlerForGroupType(groupType: string): EmbedGroupHandler | null {
    // Extract base type from group type (e.g., 'website-group' -> 'website')
    const baseType = groupType.replace('-group', '');
    return this.getHandler(baseType);
  }
  
  /**
   * Check if two embed nodes can be grouped together
   */
  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    const handler = this.getHandler(nodeA.type);
    return handler ? handler.canGroup(nodeA, nodeB) : false;
  }
  
  /**
   * Create a group from multiple embed nodes
   */
  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes | null {
    if (embedNodes.length === 0) return null;
    
    const handler = this.getHandler(embedNodes[0].type);
    return handler ? handler.createGroup(embedNodes) : null;
  }
  
  /**
   * Handle backspace for a group node
   */
  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult | null {
    const handler = this.getHandlerForGroupType(groupAttrs.type);
    return handler ? handler.handleGroupBackspace(groupAttrs) : null;
  }
  
  /**
   * Convert group to markdown
   */
  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    const handler = this.getHandlerForGroupType(groupAttrs.type);
    return handler ? handler.groupToMarkdown(groupAttrs) : '';
  }
}

// Export singleton instance
export const groupHandlerRegistry = new GroupHandlerRegistry();
