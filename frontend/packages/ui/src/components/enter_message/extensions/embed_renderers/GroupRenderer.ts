// Generic group renderer - handles any '*-group' embed types
// Uses the group handler system to render groups dynamically

import type { EmbedRenderer, EmbedRenderContext } from './types';
import type { EmbedNodeAttributes } from '../../../../message_parsing/types';
import { groupHandlerRegistry } from '../../../../message_parsing/groupHandlers';
import { mount, unmount } from 'svelte';
import WebsiteEmbedPreview from '../../../embeds/WebsiteEmbedPreview.svelte';

// Track mounted components for cleanup
const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

/**
 * Generic renderer for group embeds (website-group, code-group, doc-group, etc.)
 * Delegates to individual renderers for each item in the group
 */
export class GroupRenderer implements EmbedRenderer {
  type = 'group'; // This is a generic type - actual matching happens in the registry
  
  async render(context: EmbedRenderContext): Promise<void> {
    const { attrs, content } = context;
    
    console.log('[GroupRenderer] RENDER CALLED with attrs:', attrs);
    console.log('[GroupRenderer] RENDER CALLED with content element:', content);
    
    // Load embed content from EmbedStore if contentRef is present
    let embedData = null;
    let decodedContent = null;
    
    if (attrs.contentRef && attrs.contentRef.startsWith('embed:')) {
      try {
        const { resolveEmbed, decodeToonContent } = await import('../../../../services/embedResolver');
        const embedId = attrs.contentRef.replace('embed:', '');
        embedData = await resolveEmbed(embedId);
        
        if (embedData && embedData.content) {
          decodedContent = await decodeToonContent(embedData.content);
          console.debug('[GroupRenderer] Loaded embed content from EmbedStore:', embedId, decodedContent);
        }
      } catch (error) {
        console.error('[GroupRenderer] Error loading embed from EmbedStore:', error);
      }
    }
    
    // Check if this is a group embed (has groupedItems or type ends with '-group')
    const isGroup = attrs.groupedItems && attrs.groupedItems.length > 0 || attrs.type.endsWith('-group');
    
    if (!isGroup) {
      // This is an individual embed
      const baseType = attrs.type;
      
      // For website embeds, use Svelte component instead of HTML
      if (baseType === 'web-website') {
        await this.renderWebsiteComponent(attrs, embedData, decodedContent, content);
        return;
      }
      
      // For other types, use HTML rendering
      const itemHtml = await this.renderIndividualItem(attrs, baseType, embedData, decodedContent);
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
    
    // Generate individual embed HTML for each grouped item (async)
    const groupItemsHtmlPromises = reversedItems.map(item => {
      return this.renderIndividualItem(item, baseType);
    });
    const groupItemsHtml = (await Promise.all(groupItemsHtmlPromises)).join('');
    
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
  
  private async renderIndividualItem(
    item: EmbedNodeAttributes, 
    baseType: string,
    embedData: any = null,
    decodedContent: any = null
  ): Promise<string> {
    // Load embed content if not provided and contentRef is present
    if (!embedData && item.contentRef && item.contentRef.startsWith('embed:')) {
      try {
        const { resolveEmbed, decodeToonContent } = await import('../../../../services/embedResolver');
        const embedId = item.contentRef.replace('embed:', '');
        embedData = await resolveEmbed(embedId);
        
        if (embedData && embedData.content) {
          decodedContent = await decodeToonContent(embedData.content);
        }
      } catch (error) {
        console.error('[GroupRenderer] Error loading embed for item:', error);
      }
    }
    
    // Create a wrapper container for each item
    const itemHtml = await this.renderItemContent(item, baseType, embedData, decodedContent);
    
    return itemHtml;
  }
  
  private async renderItemContent(
    item: EmbedNodeAttributes,
    baseType: string,
    embedData: any = null,
    decodedContent: any = null
  ): Promise<string> {
    switch (baseType) {
      case 'app-skill-use':
        return this.renderAppSkillUseItem(item, embedData, decodedContent);
      case 'web-website':
        return this.renderWebsiteItem(item, embedData, decodedContent);
      case 'videos-video':
        return this.renderVideoItem(item, embedData, decodedContent);
      case 'code-code':
        return this.renderCodeItem(item, embedData, decodedContent);
      case 'docs-doc':
        return this.renderDocItem(item, embedData, decodedContent);
      case 'sheets-sheet':
        return this.renderSheetItem(item, embedData, decodedContent);
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

  private async renderAppSkillUseItem(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null
  ): Promise<string> {
    const skillId = decodedContent?.skill_id || '';
    const appId = decodedContent?.app_id || 'web';
    const query = decodedContent?.query || '';
    const provider = decodedContent?.provider || 'Brave';

    // For web search skills
    if (skillId === 'search' || appId === 'web') {
      const childEmbedIds = embedData?.embed_ids || [];
      const embedId = item.contentRef?.replace('embed:', '') || '';

      return `
        <div class="embed-unified-container"
             data-embed-type="app-skill-use"
             data-embed-id="${embedId}"
             style="${embedId ? 'cursor: pointer;' : ''}">
          <div class="embed-app-icon web">
            <span class="icon icon_web"></span>
          </div>
          <div class="embed-text-content">
            <div class="embed-text-line">Web Search: ${query}</div>
            <div class="embed-text-line">via ${provider}</div>
          </div>
          <div class="embed-extended-preview">
            <div class="web-search-preview">
              <div class="search-query">${query}</div>
              <div class="search-results-count">${childEmbedIds.length} result${childEmbedIds.length !== 1 ? 's' : ''}</div>
            </div>
          </div>
        </div>
      `;
    }

    // For other skill types
    return `
      <div class="embed-unified-container"
           data-embed-type="app-skill-use">
        <div class="embed-app-icon ${appId}">
          <span class="icon icon_${appId}"></span>
        </div>
        <div class="embed-text-content">
          <div class="embed-text-line">Skill: ${appId} | ${skillId}</div>
          <div class="embed-text-line">${item.status}</div>
        </div>
      </div>
    `;
  }
  
  /**
   * Render website embed using Svelte component
   */
  private async renderWebsiteComponent(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
    content: HTMLElement
  ): Promise<void> {
    // Use decoded content if available, otherwise fall back to item attributes
    const websiteUrl = decodedContent?.url || item.url;
    const websiteTitle = decodedContent?.title || item.title;
    const websiteDescription = decodedContent?.description || item.description;
    const favicon = decodedContent?.meta_url_favicon || decodedContent?.favicon || item.favicon;
    const image = decodedContent?.thumbnail_original || decodedContent?.image || item.image;
    
    // Determine status
    const status = item.status || (websiteUrl ? 'finished' : 'processing');
    
    // Get embed ID
    const embedId = item.contentRef?.replace('embed:', '') || '';
    
    // Clear the content element
    content.innerHTML = '';
    
    // Mount the Svelte component
    try {
      // Create a handler for fullscreen that dispatches the event
      const handleFullscreen = () => {
        this.openFullscreen(item, embedData, decodedContent);
      };
      
      const component = mount(WebsiteEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          url: websiteUrl || '',
          title: websiteTitle,
          description: websiteDescription,
          favicon: favicon,
          image: image,
          status: status as 'processing' | 'finished' | 'error',
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen
        }
      });
      
      // Store reference for cleanup
      mountedComponents.set(content, component);
      
      console.debug('[GroupRenderer] Mounted WebsiteEmbedPreview component:', {
        embedId,
        url: websiteUrl?.substring(0, 50) + '...',
        status,
        hasTitle: !!websiteTitle,
        hasImage: !!image
      });
      
    } catch (error) {
      console.error('[GroupRenderer] Error mounting WebsiteEmbedPreview component:', error);
      // Fallback to HTML rendering
      const fallbackHtml = await this.renderWebsiteItemHTML(item, embedData, decodedContent);
      content.innerHTML = fallbackHtml;
    }
  }
  
  /**
   * Fallback HTML rendering for websites (used when Svelte mount fails)
   */
  private async renderWebsiteItemHTML(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null
  ): Promise<string> {
    const isProcessing = item.status === 'processing';
    
    // Use decoded content if available, otherwise fall back to item attributes
    const websiteUrl = decodedContent?.url || item.url;
    const websiteTitle = decodedContent?.title || item.title;
    const websiteDescription = decodedContent?.description || item.description;
    const favicon = decodedContent?.meta_url_favicon || decodedContent?.favicon || item.favicon;
    const image = decodedContent?.thumbnail_original || decodedContent?.image || item.image;
    
    const hasMetadata = websiteTitle || websiteDescription;

    if (hasMetadata && websiteUrl) {
      // SUCCESS STATE: Full design with metadata
      const displayTitle = websiteTitle || new URL(websiteUrl).hostname;
      const displayDescription = websiteDescription || '';
      const faviconUrl = favicon || `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(websiteUrl)}`;
      const imageUrl = image || `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(websiteUrl)}`;
      
      // Add click handler for fullscreen
      const embedId = item.contentRef?.replace('embed:', '') || '';
      
      // Create a wrapper that will have the click handler attached
      const containerId = `embed-${embedId || Math.random().toString(36).substr(2, 9)}`;
      
      return `
        <div class="embed-unified-container" 
             data-embed-type="web-website" 
             data-embed-id="${embedId}"
             id="${containerId}"
             style="${embedId ? 'cursor: pointer;' : ''}">
          <div class="embed-app-icon web">
            <span class="icon icon_web"></span>
          </div>
          <div class="embed-text-content">
            <div class="embed-favicon" style="background-image: url('${faviconUrl}')"></div>
            <div class="embed-text-line">${displayTitle}</div>
            <div class="embed-text-line">${new URL(websiteUrl).hostname}</div>
          </div>
          <div class="embed-extended-preview">
            <div class="website-preview">
              <img class="og-image" src="${imageUrl}" alt="Website preview" loading="lazy" 
                  onerror="this.style.display='none'" />
              <div class="og-description">${displayDescription}</div>
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
  
  /**
   * Legacy method for HTML rendering (kept for grouped items)
   */
  private async renderWebsiteItem(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null
  ): Promise<string> {
    return this.renderWebsiteItemHTML(item, embedData, decodedContent);
  }
  
  private async renderVideoItem(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null
  ): Promise<string> {
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
  
  private async renderCodeItem(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null
  ): Promise<string> {
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
  
  private async renderDocItem(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null
  ): Promise<string> {
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
  
  private async renderSheetItem(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null
  ): Promise<string> {
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
  
  /**
   * Open fullscreen view for an embed
   */
  private async openFullscreen(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any
  ): Promise<void> {
    // Determine embed type from attrs
    const embedType = attrs.type === 'web-website' ? 'website' : attrs.type;
    
    // Dispatch custom event to open fullscreen view
    // The fullscreen component will handle loading and displaying embed content
    const event = new CustomEvent('embedfullscreen', {
      detail: {
        embedId: attrs.contentRef?.replace('embed:', ''),
        embedData,
        decodedContent,
        embedType,
        attrs
      },
      bubbles: true
    });
    
    document.dispatchEvent(event);
    console.debug('[GroupRenderer] Dispatched fullscreen event:', event.detail);
  }
  
  toMarkdown(attrs: EmbedNodeAttributes): string {
    // Use the group handler to convert to markdown
    return groupHandlerRegistry.groupToMarkdown(attrs);
  }
}
