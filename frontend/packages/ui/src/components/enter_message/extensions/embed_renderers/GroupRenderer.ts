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
    
    // Extract the base type from the group type (e.g., 'website-group' -> 'website')
    const baseType = attrs.type.replace('-group', '');
    const groupedItems = attrs.groupedItems || [];
    const groupCount = attrs.groupCount || groupedItems.length;
    
    console.debug('[GroupRenderer] Rendering group:', {
      groupType: attrs.type,
      baseType,
      itemCount: groupCount
    });
    
    // Reverse the items so the most recently added appears on the left
    const reversedItems = [...groupedItems].reverse();
    
    // Generate individual embed HTML for each grouped item
    const groupItemsHtml = reversedItems.map(item => {
      return this.renderIndividualItem(item, baseType);
    }).join('');
    
    // Determine the group display name
    const groupDisplayName = this.getGroupDisplayName(baseType, groupCount);
    
    content.innerHTML = `
      <div class="${baseType}-preview-group">
        <div class="group-header">${groupDisplayName}</div>
        <div class="group-scroll-container">
          ${groupItemsHtml}
        </div>
      </div>
    `;
  }
  
  private renderIndividualItem(item: EmbedNodeAttributes, baseType: string): string {
    // Create a wrapper container for each item
    const itemHtml = this.renderItemContent(item, baseType);
    
    return `
      <div class="embed-unified-container" data-embed-type="${baseType}">
        ${itemHtml}
      </div>
    `;
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
        return this.renderGenericItem(item);
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
        <div class="website-embed-container success">
          <div class="website-image">
            <img src="${imageUrl}" alt="Website preview" loading="lazy" 
                 onerror="this.parentElement.style.display='none'" />
          </div>
          <div class="website-content">
            <div class="website-header">
              <div class="website-icon-container">
                <img src="${faviconUrl}" alt="Favicon" class="website-favicon" 
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'" />
                <span class="website-icon-fallback" style="display: none;">🌐</span>
              </div>
            </div>
            <div class="website-info">
              <div class="website-title">${websiteTitle}</div>
              ${websiteDescription ? `<div class="website-description">${websiteDescription}</div>` : ''}
            </div>
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
        <div class="website-embed-container failed">
          <div class="website-content-simple">
            <div class="website-header-simple">
              <div class="clickable-icon icon_web"></div>
            </div>
            <div class="website-info-simple">
              <div class="website-url-text">
                <div class="website-domain">${domain}</div>
                ${displayPath ? `<div class="website-path">${displayPath}</div>` : ''}
              </div>
              ${isProcessing ? '<div class="website-loading">Loading...</div>' : ''}
            </div>
          </div>
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
        <div class="video-embed-container success">
          <div class="video-thumbnail">
            <img src="${thumbnailUrl}" alt="Video thumbnail" loading="lazy" 
                 onerror="this.parentElement.innerHTML='<div class=\\"video-placeholder\\">📹</div>'" />
            <div class="video-play-button">▶</div>
          </div>
          <div class="video-content">
            <div class="video-header">
              <div class="video-icon">📹</div>
            </div>
            <div class="video-info">
              <div class="video-title">${videoTitle}</div>
              ${isProcessing ? '<div class="video-loading">Loading...</div>' : ''}
            </div>
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
        <div class="video-embed-container failed">
          <div class="video-content-simple">
            <div class="video-header-simple">
              <div class="clickable-icon icon_video">📹</div>
            </div>
            <div class="video-info-simple">
              <div class="video-url-text">
                <div class="video-domain">${domain}</div>
                ${displayPath ? `<div class="video-path">${displayPath}</div>` : ''}
              </div>
              ${isProcessing ? '<div class="video-loading">Loading...</div>' : ''}
            </div>
          </div>
        </div>
      `;
    }
  }
  
  private renderCodeItem(item: EmbedNodeAttributes): string {
    const language = item.language || 'text';
    const filename = item.filename || `code.${language}`;
    const isProcessing = item.status === 'processing';
    
    return `
      <div class="code-embed-container">
        <div class="code-header">
          <div class="code-language">${language}</div>
          ${filename ? `<div class="code-filename">${filename}</div>` : ''}
          ${isProcessing ? '<div class="code-loading">Processing...</div>' : ''}
        </div>
        <div class="code-preview">
          <div class="code-icon">📄</div>
        </div>
      </div>
    `;
  }
  
  private renderDocItem(item: EmbedNodeAttributes): string {
    const title = item.title || 'Document';
    const isProcessing = item.status === 'processing';
    
    return `
      <div class="doc-embed-container">
        <div class="doc-header">
          <div class="doc-icon">📄</div>
          <div class="doc-title">${title}</div>
          ${isProcessing ? '<div class="doc-loading">Processing...</div>' : ''}
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
      <div class="sheet-embed-container">
        <div class="sheet-header">
          <div class="sheet-icon">📊</div>
          <div class="sheet-title">${title}</div>
          ${isProcessing ? '<div class="sheet-loading">Processing...</div>' : ''}
        </div>
        <div class="sheet-info">
          <div class="sheet-dimensions">${rows} rows × ${cols} columns</div>
        </div>
      </div>
    `;
  }
  
  private renderGenericItem(item: EmbedNodeAttributes): string {
    const title = item.title || item.filename || item.type;
    const isProcessing = item.status === 'processing';
    
    return `
      <div class="generic-embed-container">
        <div class="generic-header">
          <div class="generic-title">${title}</div>
          ${isProcessing ? '<div class="generic-loading">Processing...</div>' : ''}
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
