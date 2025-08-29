// Website embed renderer - handles 'web' and 'website-group' embed types

import type { EmbedRenderer, EmbedRenderContext } from './types';
import type { EmbedNodeAttributes } from '../../../../message_parsing/types';

/**
 * Renderer for website embeds (individual and grouped)
 * Handles 'website' and 'website-group' embed types
 */
export class WebsiteRenderer implements EmbedRenderer {
  type = 'website';

  render(context: EmbedRenderContext): void {
    const { attrs, content } = context;

    if (attrs.type === 'website-group') {
      this.renderWebsiteGroup(context);
      return;
    }

    // Render individual website embed
    this.renderSingleWebsite(context);
  }

  private renderSingleWebsite(context: EmbedRenderContext): void {
    const { attrs, content } = context;
    const isProcessing = attrs.status === 'processing';
    const hasMetadata = attrs.title || attrs.description;
    const websiteUrl = attrs.url;

    if (hasMetadata && websiteUrl) {
      // SUCCESS STATE: Full Figma design with metadata
      const websiteTitle = attrs.title || new URL(websiteUrl).hostname;
      const websiteDescription = attrs.description || '';
      const faviconUrl = `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(websiteUrl)}`;
      const imageUrl = `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(websiteUrl)}`;

      content.innerHTML = `
        <div class="website-embed-container success">
          <!-- Background/preview image (right side for desktop, top for mobile) -->
          <div class="website-image">
            <img src="${imageUrl}" alt="Website preview" loading="lazy" 
                 onerror="this.parentElement.style.display='none'" />
          </div>
          
          <!-- Content area (left side for desktop, bottom for mobile) -->
          <div class="website-content">
            <!-- Header with icon bar -->
            <div class="website-header">
              <div class="website-icon-container">
                <img src="${faviconUrl}" alt="Favicon" class="website-favicon" 
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'" />
                <span class="website-icon-fallback" style="display: none;">🌐</span>
              </div>
            </div>
            
            <!-- Website info -->
            <div class="website-info">
              <div class="website-title">${websiteTitle}</div>
              ${websiteDescription ? `
                <div class="website-description">${websiteDescription}</div>
              ` : ''}
            </div>
          </div>
        </div>
      `;
    } else {
      // FAILED STATE: Simple URL display as per Figma no-metadata designs
      const urlObj = websiteUrl ? new URL(websiteUrl) : null;
      const domain = urlObj ? urlObj.hostname : 'Invalid URL';
      const path = urlObj ? (urlObj.pathname + urlObj.search + urlObj.hash) : '';
      const displayPath = path === '/' ? '' : path;

      content.innerHTML = `
        <div class="website-embed-container failed">
          <!-- Content area with simple URL breakdown -->
          <div class="website-content-simple">
            <!-- Header with web icon -->
            <div class="website-header-simple">
              <div class="clickable-icon icon_web"></div>
            </div>
            
            <!-- URL info -->
            <div class="website-info-simple">
              <div class="website-url-text">
                <div class="website-domain">${domain}</div>
                ${displayPath ? `<div class="website-path">${displayPath}</div>` : ''}
              </div>
              ${isProcessing ? `
                <div class="website-loading">Loading...</div>
              ` : ''}
            </div>
          </div>
        </div>
      `;
    }
  }

  private renderWebsiteGroup(context: EmbedRenderContext): void {
    const { attrs, content } = context;
    const groupedItems = attrs.groupedItems || [];
    const groupCount = attrs.groupCount || groupedItems.length;

    // Reverse the items so the most recently added appears on the left
    const reversedItems = [...groupedItems].reverse();

    // Generate individual embed HTML for each grouped item
    const groupItemsHtml = reversedItems.map(item => {
      // Determine if this item has metadata
      const hasMetadata = item.title || item.description;
      const websiteUrl = item.url;

      if (hasMetadata && websiteUrl) {
        // SUCCESS STATE
        const websiteTitle = item.title || new URL(websiteUrl).hostname;
        const websiteDescription = item.description || '';
        const faviconUrl = `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(websiteUrl)}`;
        const imageUrl = `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(websiteUrl)}`;

        return `
          <div class="embed-unified-container" data-embed-type="website">
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
          </div>
        `;
      } else {
        // FAILED STATE
        const urlObj = websiteUrl ? new URL(websiteUrl) : null;
        const domain = urlObj ? urlObj.hostname : 'Invalid URL';
        const path = urlObj ? (urlObj.pathname + urlObj.search + urlObj.hash) : '';
        const displayPath = path === '/' ? '' : path;

        return `
          <div class="embed-unified-container" data-embed-type="website">
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
                  ${item.status === 'processing' ? '<div class="website-loading">Loading...</div>' : ''}
                </div>
              </div>
            </div>
          </div>
        `;
      }
    }).join('');

    content.innerHTML = `
      <div class="website-preview-group">
        <div class="group-header">${groupCount} website${groupCount > 1 ? 's' : ''}</div>
        <div class="group-scroll-container">
          ${groupItemsHtml}
        </div>
      </div>
    `;
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    if (attrs.type === 'website-group') {
      // For grouped websites, restore all URLs separated by spaces
      // Reverse the order to maintain the original markdown order (most recent first)
      const groupedItems = attrs.groupedItems || [];
      const reversedItems = [...groupedItems].reverse();
      return reversedItems.map(item => item.url || '').filter(url => url).join(' ');
    }
    
    // For individual website embeds, just restore the URL
    return attrs.url || '';
  }
}
