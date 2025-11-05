// Image renderer for static SVG images and other image embeds
// Used for legal document SVG images from the static folder

import type { EmbedRenderer, EmbedRenderContext } from './types';
import type { EmbedNodeAttributes } from '../../../../message_parsing/types';

/**
 * Renderer for image embeds (static images, SVGs, etc.)
 * Handles both static files and external URLs
 * For SVG images used in legal documents, renders as simple non-clickable images
 */
export class ImageRenderer implements EmbedRenderer {
  type = 'image';
  
  render(context: EmbedRenderContext): void {
    const { attrs, content, container } = context;
    
    // Get the image URL - use url attribute which contains the image path
    const imageUrl = attrs.url;
    const altText = attrs.filename || attrs.title || 'Image';
    
    if (!imageUrl) {
      console.warn('[ImageRenderer] No URL provided for image embed');
      content.innerHTML = '<div class="image-error">Image URL not available</div>';
      return;
    }
    
    // Render a simple img tag for the image
    // For SVG files, we want them to display at their natural size
    // For other images, we can use standard sizing
    const isSvg = imageUrl.toLowerCase().endsWith('.svg');
    
    if (isSvg) {
      // SVG images - display inline with natural size, minimal spacing, no clickability
      // Disable pointer events to make it non-clickable
      container.style.pointerEvents = 'none';
      container.style.cursor = 'default';
      container.style.margin = '0'; // Remove margins to minimize spacing
      container.style.marginBottom = '8px'; // Only small bottom margin between SVGs
      
      content.innerHTML = `
        <img 
          src="${imageUrl}" 
          alt="${altText}" 
          class="legal-svg-image"
          loading="lazy"
          style="max-width: 100%; height: auto; display: block;"
        />
      `;
    } else {
      // Regular images - use standard image embed styling (still clickable)
      content.innerHTML = `
        <div class="image-embed-container">
          <img 
            src="${imageUrl}" 
            alt="${altText}" 
            class="image-embed-img"
            loading="lazy"
            style="max-width: 100%; height: auto; display: block; border-radius: 12px;"
          />
        </div>
      `;
    }
  }
  
  toMarkdown(attrs: EmbedNodeAttributes): string {
    const url = attrs.url || '';
    const alt = attrs.filename || attrs.title || '';
    return `![${alt}](${url})`;
  }
  
  update(context: EmbedRenderContext): boolean {
    // Re-render if attributes change
    this.render(context);
    return true;
  }
}


