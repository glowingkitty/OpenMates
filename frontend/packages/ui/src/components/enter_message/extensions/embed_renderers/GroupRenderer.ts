// Generic group renderer - handles any '*-group' embed types
// Uses the group handler system to render groups dynamically

import type { EmbedRenderer, EmbedRenderContext } from './types';
import type { EmbedNodeAttributes } from '../../../../message_parsing/types';
import { groupHandlerRegistry } from '../../../../message_parsing/groupHandlers';

/**
 * Generic renderer for group embeds (website-group, code-group, doc-group, etc.)
 * Delegates to individual renderers for each item in the group
 */
export class GroupRenderer implements EmbedRenderer {
  type = 'group'; // This is a generic type - actual matching happens in the registry
  
  render(context: EmbedRenderContext): void {
    const { attrs, content } = context;
    
    console.log('[GroupRenderer] RENDER CALLED with attrs:', attrs);
    console.log('[GroupRenderer] RENDER CALLED with content element:', content);
    
    // Check if this is a group embed (has groupedItems or type ends with '-group')
    const isGroup = attrs.groupedItems && attrs.groupedItems.length > 0 || attrs.type.endsWith('-group');
    
    if (!isGroup) {
      // This is an individual embed, render it directly using renderIndividualItem
      const baseType = attrs.type;
      const itemHtml = this.renderIndividualItem(attrs, baseType);
      content.innerHTML = itemHtml;
      return;
    }
    
    // This is a group embed - continue with existing group rendering logic
    // Extract the base type from the group type (e.g., 'web-website-group' -> 'web-website')
    const baseType = attrs.type.replace('-group', '');
    const groupedItems = attrs.groupedItems || [];
    const groupCount = attrs.groupCount || groupedItems.length;
    
    console.debug('[GroupRenderer] Rendering group:', {
      groupType: attrs.type,
      baseType,
      itemCount: groupCount,
      groupedItems: groupedItems.map(item => item.url || item.title || item.id),
      attrsKeys: Object.keys(attrs)
    });
    
    // Validate that we have the required data
    if (!groupedItems || groupedItems.length === 0) {
      console.error('[GroupRenderer] No grouped items found for group type:', attrs.type);
      console.error('[GroupRenderer] Full attrs object:', attrs);
      console.error('[GroupRenderer] groupedItems value:', groupedItems);
      content.innerHTML = '<div class="error">Error: No grouped items found</div>';
      return;
    }
    
    // Reverse the items so the most recently added appears on the left
    const reversedItems = [...groupedItems].reverse();
    
    // Generate individual embed HTML for each grouped item
    const groupItemsHtml = reversedItems.map(item => {
      return this.renderIndividualItem(item, baseType);
    }).join('');
    
    // Determine the group display name
    const groupDisplayName = this.getGroupDisplayName(baseType, groupCount);
    
    const finalHtml = `
      <div class="${baseType}-preview-group">
        <div class="group-header">${groupDisplayName}</div>
        <div class="group-scroll-container">
          ${groupItemsHtml}
        </div>
      </div>
    `;
    
    console.debug('[GroupRenderer] Final HTML:', finalHtml);
    content.innerHTML = finalHtml;
  }
  
  private renderIndividualItem(item: EmbedNodeAttributes, baseType: string): string {
    // Create a wrapper container for each item
    const itemHtml = this.renderItemContent(item, baseType);
    
    return itemHtml;
  }
  
  private renderItemContent(item: EmbedNodeAttributes, baseType: string): string {
    switch (baseType) {
      case 'web-website':
        return this.renderWebsiteItem(item);
      case 'videos-video':
        return this.renderVideoItem(item);
      case 'code-code':
        return this.renderCodeItem(item);
      case 'docs-doc':
        return this.renderDocItem(item);
      case 'sheets-sheet':
        return this.renderSheetItem(item);
      default:
        console.error(`[GroupRenderer] No renderer found for embed type: ${baseType}`);
        return `
          <div class="embed-unified-container" data-embed-type="${item.type}">
            <div class="embed-error">
              <div class="error-message">ERROR: No renderer for type "${baseType}"</div>
              <div class="error-details">Item: ${JSON.stringify(item)}</div>
            </div>
          </div>
        `;
    }
  }
  
  private renderWebsiteItem(item: EmbedNodeAttributes): string {
    const isProcessing = item.status === 'processing';
    const hasMetadata = item.title || item.description;
    const websiteUrl = item.url;

    if (hasMetadata && websiteUrl) {
      // SUCCESS STATE: Full design with metadata
      const websiteTitle = item.title || new URL(websiteUrl).hostname;
      const websiteDescription = item.description || '';
      const faviconUrl = `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(websiteUrl)}`;
      const imageUrl = `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(websiteUrl)}`;

      return `
        <div class="embed-app-icon web">
          <span class="icon icon_web"></span>
        </div>
        <div class="embed-text-content">
          <div class="embed-favicon" style="background-image: url('${faviconUrl}')"></div>
          <div class="embed-text-line">${websiteTitle}</div>
          <div class="embed-text-line">${new URL(websiteUrl).hostname}</div>
        </div>
        <div class="embed-extended-preview">
          <div class="website-preview">
            <img class="og-image" src="${imageUrl}" alt="Website preview" loading="lazy" 
                onerror="this.style.display='none'" />
            <div class="og-description">${websiteDescription}</div>
          </div>
        </div>
      `;
    } else {
      // FAILED STATE: Simple URL display
      const urlObj = websiteUrl ? new URL(websiteUrl) : null;
      const domain = urlObj ? urlObj.hostname : 'Invalid URL';
      const path = urlObj ? (urlObj.pathname + urlObj.search + urlObj.hash) : '';
      const displayPath = path === '/' ? '' : path;

      return `
        <div class="embed-app-icon web">
          <span class="icon icon_web"></span>
        </div>
        <div class="embed-text-content">
          <div class="embed-text-line">${domain}</div>
          ${displayPath ? `<div class="embed-text-line">${displayPath}</div>` : ''}
        </div>
      `;
    }
  }
  
  private renderVideoItem(item: EmbedNodeAttributes): string {
    const isProcessing = item.status === 'processing';
    const videoUrl = item.url;
    
    // Extract video ID for YouTube URLs
    let videoId = '';
    let videoTitle = item.title || '';
    let thumbnailUrl = '';
    
    if (videoUrl) {
      // YouTube URL patterns
      const youtubeMatch = videoUrl.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)/);
      if (youtubeMatch) {
        videoId = youtubeMatch[1];
        thumbnailUrl = `https://img.youtube.com/vi/${videoId}/maxresdefault.jpg`;
        if (!videoTitle) {
          videoTitle = 'YouTube Video';
        }
      }
    }
    
    if (videoId && thumbnailUrl) {
      // SUCCESS STATE: Video with thumbnail
      return `
        <div class="embed-app-icon videos">
          <span class="icon icon_video"></span>
        </div>
        <div class="embed-text-content">
          <div class="embed-text-line">${videoTitle}</div>
          <div class="embed-text-line">YouTube</div>
        </div>
        <div class="embed-extended-preview">
          <div class="video-preview">
            <img class="video-thumbnail" src="${thumbnailUrl}" alt="Video thumbnail" loading="lazy" 
                onerror="this.style.display='none'" />
            <div class="video-play-button">▶</div>
          </div>
        </div>
      `;
    } else {
      // FAILED STATE: Simple URL display
      const urlObj = videoUrl ? new URL(videoUrl) : null;
      const domain = urlObj ? urlObj.hostname : 'Invalid URL';
      const path = urlObj ? (urlObj.pathname + urlObj.search + urlObj.hash) : '';
      const displayPath = path === '/' ? '' : path;

      return `
        <div class="embed-app-icon videos">
          <span class="icon icon_video"></span>
        </div>
        <div class="embed-text-content">
          <div class="embed-text-line">${domain}</div>
          ${displayPath ? `<div class="embed-text-line">${displayPath}</div>` : ''}
        </div>
      `;
    }
  }
  
  private renderCodeItem(item: EmbedNodeAttributes): string {
    const language = item.language || 'text';
    const filename = item.filename || `code.${language}`;
    const isProcessing = item.status === 'processing';
    
    return `
      <div class="embed-app-icon code">
        <span class="icon icon_code"></span>
      </div>
      <div class="embed-text-content">
        ${isProcessing ? '<div class="embed-modify-icon"><span class="icon icon_edit"></span></div>' : ''}
        <div class="embed-text-line">${filename}</div>
        <div class="embed-text-line">${item.lineCount || 0} lines, ${language}</div>
      </div>
      <div class="embed-extended-preview">
        <div class="code-preview">
          <div class="code-snippet">// Code preview would be rendered here</div>
        </div>
      </div>
    `;
  }
  
  private renderDocItem(item: EmbedNodeAttributes): string {
    const title = item.title || 'Document';
    const isProcessing = item.status === 'processing';
    
    return `
      <div class="embed-app-icon docs">
        <span class="icon icon_document"></span>
      </div>
      <div class="embed-text-content">
        ${isProcessing ? '<div class="embed-modify-icon"><span class="icon icon_edit"></span></div>' : ''}
        <div class="embed-text-line">${title}</div>
        <div class="embed-text-line">${item.wordCount || 0} words</div>
      </div>
      <div class="embed-extended-preview">
        <div class="doc-preview">
          <div class="doc-content">Document content preview would be rendered here</div>
        </div>
      </div>
    `;
  }
  
  private renderSheetItem(item: EmbedNodeAttributes): string {
    const title = item.title || 'Spreadsheet';
    const rows = item.rows || 0;
    const cols = item.cols || 0;
    const isProcessing = item.status === 'processing';
    
    return `
      <div class="embed-app-icon sheets">
        <span class="icon icon_table"></span>
      </div>
      <div class="embed-text-content">
        ${isProcessing ? '<div class="embed-modify-icon"><span class="icon icon_edit"></span></div>' : ''}
        <div class="embed-text-line">${title}</div>
        <div class="embed-text-line">${item.cellCount || 0} cells, ${rows}×${cols}</div>
      </div>
      <div class="embed-extended-preview">
        <div class="sheet-preview">
          <div class="sheet-table">Spreadsheet preview would be rendered here</div>
        </div>
      </div>
    `;
  }
  

  
  private getGroupDisplayName(baseType: string, count: number): string {
    const typeDisplayNames: { [key: string]: string } = {
      'web-website': 'website',
      'videos-video': 'video',
      'code-code': 'code file',
      'docs-doc': 'document',
      'sheets-sheet': 'spreadsheet'
    };
    
    const displayName = typeDisplayNames[baseType] || baseType;
    return `${count} ${displayName}${count > 1 ? 's' : ''}`;
  }
  
  toMarkdown(attrs: EmbedNodeAttributes): string {
    // Use the group handler to convert to markdown
    return groupHandlerRegistry.groupToMarkdown(attrs);
  }
}
