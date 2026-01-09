// Generic group renderer - handles any '*-group' embed types
// Uses the group handler system to render groups dynamically

import type { EmbedRenderer, EmbedRenderContext } from './types';
import type { EmbedNodeAttributes } from '../../../../message_parsing/types';
import { groupHandlerRegistry } from '../../../../message_parsing/groupHandlers';
import { resolveEmbed, decodeToonContent } from '../../../../services/embedResolver';
import { downloadCodeFilesAsZip, type CodeFileData } from '../../../../services/zipExportService';
import { mount, unmount } from 'svelte';
import WebsiteEmbedPreview from '../../../embeds/web/WebsiteEmbedPreview.svelte';
import VideoEmbedPreview from '../../../embeds/videos/VideoEmbedPreview.svelte';
import CodeEmbedPreview from '../../../embeds/code/CodeEmbedPreview.svelte';
import WebSearchEmbedPreview from '../../../embeds/web/WebSearchEmbedPreview.svelte';
import NewsSearchEmbedPreview from '../../../embeds/news/NewsSearchEmbedPreview.svelte';
import VideosSearchEmbedPreview from '../../../embeds/videos/VideosSearchEmbedPreview.svelte';
import MapsSearchEmbedPreview from '../../../embeds/maps/MapsSearchEmbedPreview.svelte';
import VideoTranscriptEmbedPreview from '../../../embeds/videos/VideoTranscriptEmbedPreview.svelte';
import WebReadEmbedPreview from '../../../embeds/web/WebReadEmbedPreview.svelte';

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
      
      // For video embeds, use Svelte component instead of HTML
      if (baseType === 'videos-video') {
        await this.renderVideoComponent(attrs, embedData, decodedContent, content);
        return;
      }
      
      // For code embeds, use Svelte component instead of HTML
      if (baseType === 'code-code') {
        await this.renderCodeComponent(attrs, embedData, decodedContent, content);
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

    // Determine the group display name
    const groupDisplayName = this.getGroupDisplayName(baseType, groupCount);

    // App skill groups must render each item using the existing embed preview components
    // (e.g. WebSearchEmbedPreview) so sizing and interactions match single-item rendering.
    if (baseType === 'app-skill-use') {
      await this.renderAppSkillUseGroup({
        baseType,
        groupDisplayName,
        items: reversedItems,
        content
      });
      return;
    }
    
    // Code groups must render each item using CodeEmbedPreview component
    // so sizing and interactions match single-item rendering.
    if (baseType === 'code-code') {
      await this.renderCodeGroup({
        baseType,
        groupDisplayName,
        items: reversedItems,
        content
      });
      return;
    }
    
    // Generate individual embed HTML for each grouped item (async)
    const groupItemsHtmlPromises = reversedItems.map(item => {
      return this.renderIndividualItem(item, baseType);
    });
    const groupItemsHtml = (await Promise.all(groupItemsHtmlPromises)).join('');
    
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
        // App skill use embeds should be rendered via Svelte components for correct sizing.
        // This HTML path is kept as a last-resort fallback.
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

  private unmountMountedComponentsInSubtree(root: HTMLElement): void {
    const elements: HTMLElement[] = [root, ...Array.from(root.querySelectorAll<HTMLElement>('*'))];
    for (const el of elements) {
      const existingComponent = mountedComponents.get(el);
      if (existingComponent) {
        try {
          unmount(existingComponent);
        } catch (e) {
          console.warn('[GroupRenderer] Error unmounting existing component:', e);
        }
      }
    }
  }

  private async renderAppSkillUseGroup(args: {
    baseType: string;
    groupDisplayName: string;
    items: EmbedNodeAttributes[];
    content: HTMLElement;
  }): Promise<void> {
    const { baseType, groupDisplayName, items, content } = args;

    // Cleanup any mounted components inside this node before re-rendering
    this.unmountMountedComponentsInSubtree(content);

    // Build group DOM (avoid innerHTML for item rendering so we can mount Svelte components)
    content.innerHTML = '';

    const groupWrapper = document.createElement('div');
    groupWrapper.className = `${baseType}-preview-group`;

    const header = document.createElement('div');
    header.className = 'group-header';
    header.textContent = groupDisplayName;

    const scrollContainer = document.createElement('div');
    scrollContainer.className = 'group-scroll-container';

    groupWrapper.appendChild(header);
    groupWrapper.appendChild(scrollContainer);
    content.appendChild(groupWrapper);

    for (const item of items) {
      const itemWrapper = document.createElement('div');
      itemWrapper.className = 'embed-group-item';
      // Ensure items keep their intrinsic (fixed) preview size within the horizontal scroll container
      itemWrapper.style.flex = '0 0 auto';

      scrollContainer.appendChild(itemWrapper);

      await this.mountAppSkillUsePreview(item, itemWrapper);
    }
  }

  private async mountAppSkillUsePreview(item: EmbedNodeAttributes, target: HTMLElement): Promise<void> {
    // CRITICAL: Extract app_id, skill_id, query from item attrs FIRST
    // These are preserved from the original embed parsing and are available
    // even before embed data arrives from the server via WebSocket.
    // This allows proper rendering during streaming.
    const itemAppId = (item as any).app_id || '';
    const itemSkillId = (item as any).skill_id || '';
    const itemQuery = (item as any).query || '';
    const itemProvider = (item as any).provider || '';
    
    // Resolve content for this app-skill-use item from EmbedStore
    const embedId = item.contentRef?.startsWith('embed:') ? item.contentRef.replace('embed:', '') : '';

    let embedData: any = null;
    let decodedContent: any = null;

    if (embedId) {
      try {
        embedData = await resolveEmbed(embedId);
        decodedContent = embedData?.content ? await decodeToonContent(embedData.content) : null;
      } catch (error) {
        console.error('[GroupRenderer] Error loading app-skill-use embed for group item:', error);
      }
    }

    // Determine app_id and skill_id by combining sources in priority order:
    // 1. decodedContent (from TOON content decoding) - most reliable for finished embeds
    // 2. embedData directly (from memory cache for processing embeds)
    // 3. item attrs (from grouped items - preserved from original parsing)
    const appId = decodedContent?.app_id || embedData?.app_id || itemAppId;
    const skillId = decodedContent?.skill_id || embedData?.skill_id || itemSkillId;
    const status = (decodedContent?.status || embedData?.status || item.status || 'processing') as 'processing' | 'finished' | 'error';
    const taskId = decodedContent?.task_id;
    const results = decodedContent?.results || [];
    
    // Merge query from multiple sources
    const query = decodedContent?.query || embedData?.query || itemQuery;
    const provider = decodedContent?.provider || embedData?.provider || itemProvider;
    
    console.debug('[GroupRenderer] mountAppSkillUsePreview:', {
      appId,
      skillId,
      status,
      query,
      provider,
      itemAppId,
      itemSkillId,
      hasEmbedData: !!embedData,
      hasDecodedContent: !!decodedContent
    });

    // Cleanup any existing mounted component (in case this target is reused)
    const existingComponent = mountedComponents.get(target);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn('[GroupRenderer] Error unmounting existing component:', e);
      }
    }
    target.innerHTML = '';

    const handleFullscreen = () => {
      this.openFullscreen(item, embedData, decodedContent);
    };

    try {
      if (appId === 'web' && skillId === 'search') {
        const component = mount(WebSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || '',
            provider: provider || 'Brave Search',
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen
          }
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === 'news' && skillId === 'search') {
        const component = mount(NewsSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || '',
            provider: provider || 'Brave Search',
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen
          }
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === 'videos' && skillId === 'search') {
        const component = mount(VideosSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || '',
            provider: provider || 'Brave Search',
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen
          }
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === 'maps' && skillId === 'search') {
        const component = mount(MapsSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || '',
            provider: provider || 'Google',
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen
          }
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === 'videos' && (skillId === 'get_transcript' || skillId === 'get-transcript')) {
        const component = mount(VideoTranscriptEmbedPreview, {
          target,
          props: {
            id: embedId,
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen
          }
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === 'web' && skillId === 'read') {
        const component = mount(WebReadEmbedPreview, {
          target,
          props: {
            id: embedId,
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen
          }
        });
        mountedComponents.set(target, component);
        return;
      }
    } catch (error) {
      console.error('[GroupRenderer] Error mounting app-skill-use preview component:', error);
    }

    // Fallback: render the legacy HTML view (better than a blank group item)
    const fallbackHtml = await this.renderAppSkillUseItem(item, embedData, decodedContent);
    target.innerHTML = fallbackHtml;
  }
  
  /**
   * Render code embed group with horizontal scrolling
   * Similar to renderAppSkillUseGroup but for code embeds
   * Includes a download icon to download all code files as a zip
   */
  private async renderCodeGroup(args: {
    baseType: string;
    groupDisplayName: string;
    items: EmbedNodeAttributes[];
    content: HTMLElement;
  }): Promise<void> {
    const { baseType, groupDisplayName, items, content } = args;

    // Cleanup any mounted components inside this node before re-rendering
    this.unmountMountedComponentsInSubtree(content);

    // Build group DOM (avoid innerHTML for item rendering so we can mount Svelte components)
    content.innerHTML = '';

    const groupWrapper = document.createElement('div');
    groupWrapper.className = `${baseType}-preview-group`;

    // Create header with text and download icon
    const header = document.createElement('div');
    header.className = 'group-header';
    
    // Text span for the count
    const headerText = document.createElement('span');
    headerText.textContent = groupDisplayName;
    header.appendChild(headerText);
    
    // Download icon for code groups
    const downloadIcon = document.createElement('span');
    downloadIcon.className = 'clickable-icon icon_download group-download-icon';
    downloadIcon.title = 'Download all code files';
    downloadIcon.setAttribute('role', 'button');
    downloadIcon.setAttribute('tabindex', '0');
    
    // Add click handler to download all code files
    downloadIcon.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await this.downloadAllCodeFiles(items);
    });
    
    // Also support keyboard activation
    downloadIcon.addEventListener('keydown', async (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        await this.downloadAllCodeFiles(items);
      }
    });
    
    header.appendChild(downloadIcon);

    const scrollContainer = document.createElement('div');
    scrollContainer.className = 'group-scroll-container';

    groupWrapper.appendChild(header);
    groupWrapper.appendChild(scrollContainer);
    content.appendChild(groupWrapper);

    for (const item of items) {
      const itemWrapper = document.createElement('div');
      itemWrapper.className = 'embed-group-item';
      // Ensure items keep their intrinsic (fixed) preview size within the horizontal scroll container
      itemWrapper.style.flex = '0 0 auto';

      scrollContainer.appendChild(itemWrapper);

      await this.mountCodePreview(item, itemWrapper);
    }
  }
  
  /**
   * Downloads all code files from a code group as a zip
   * Resolves each embed, extracts code content, and creates a zip download
   */
  private async downloadAllCodeFiles(items: EmbedNodeAttributes[]): Promise<void> {
    console.debug('[GroupRenderer] Downloading all code files from group:', items.length);
    
    const codeFiles: CodeFileData[] = [];
    
    for (const item of items) {
      try {
        // Resolve content for this code item
        const embedId = item.contentRef?.startsWith('embed:') ? item.contentRef.replace('embed:', '') : '';
        
        let decodedContent: any = null;
        
        if (embedId) {
          const embedData = await resolveEmbed(embedId);
          decodedContent = embedData?.content ? await decodeToonContent(embedData.content) : null;
        }
        
        // Get code content - for preview embeds use item.code, for real embeds use decodedContent
        let codeContent = '';
        if (item.contentRef?.startsWith('preview:')) {
          codeContent = item.code || '';
        } else {
          codeContent = decodedContent?.code || '';
        }
        
        if (codeContent) {
          codeFiles.push({
            code: codeContent,
            language: decodedContent?.language || item.language || 'text',
            filename: decodedContent?.filename || item.filename
          });
        }
      } catch (error) {
        console.warn('[GroupRenderer] Error loading code embed for download:', error);
      }
    }
    
    if (codeFiles.length > 0) {
      try {
        await downloadCodeFilesAsZip(codeFiles);
        console.debug('[GroupRenderer] Code files download initiated:', codeFiles.length, 'files');
      } catch (error) {
        console.error('[GroupRenderer] Error downloading code files:', error);
      }
    } else {
      console.warn('[GroupRenderer] No code files found to download');
    }
  }

  /**
   * Mount CodeEmbedPreview component for a single code embed item
   */
  private async mountCodePreview(item: EmbedNodeAttributes, target: HTMLElement): Promise<void> {
    // Resolve content for this code item
    const embedId = item.contentRef?.startsWith('embed:') ? item.contentRef.replace('embed:', '') : '';
    const previewId = item.contentRef?.startsWith('preview:') ? item.contentRef.replace('preview:code:', '') : '';

    let embedData: any = null;
    let decodedContent: any = null;

    if (embedId) {
      try {
        embedData = await resolveEmbed(embedId);
        decodedContent = embedData?.content ? await decodeToonContent(embedData.content) : null;
      } catch (error) {
        console.error('[GroupRenderer] Error loading code embed for group item:', error);
      }
    }

    // Use decoded content if available, otherwise fall back to item attributes
    const language = decodedContent?.language || item.language || 'text';
    const filename = decodedContent?.filename || item.filename;
    const lineCount = decodedContent?.lineCount || item.lineCount || 0;
    
    // For preview embeds (contentRef starts with 'preview:'), get code from item attributes
    // For real embeds, get code from decodedContent
    let codeContent = '';
    if (item.contentRef?.startsWith('preview:')) {
      // Preview embed - code is stored temporarily in item attributes
      codeContent = item.code || '';
      console.debug('[GroupRenderer] Rendering preview code embed with inline code content');
    } else {
      // Real embed - code comes from decodedContent (loaded from EmbedStore)
      codeContent = decodedContent?.code || '';
    }
    
    // Determine status
    const status = (decodedContent?.status || embedData?.status || item.status || 'finished') as 'processing' | 'finished' | 'error';
    const taskId = decodedContent?.task_id;

    // Cleanup any existing mounted component (in case this target is reused)
    const existingComponent = mountedComponents.get(target);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn('[GroupRenderer] Error unmounting existing component:', e);
      }
    }
    target.innerHTML = '';

    const handleFullscreen = () => {
      this.openFullscreen(item, embedData, decodedContent);
    };

    try {
      const component = mount(CodeEmbedPreview, {
        target,
        props: {
          id: embedId || previewId || item.id || '',
          language,
          filename,
          lineCount,
          status,
          taskId,
          isMobile: false,
          onFullscreen: handleFullscreen,
          codeContent // Pass full code content - component handles preview extraction
        }
      });
      mountedComponents.set(target, component);
      
      console.debug('[GroupRenderer] Mounted CodeEmbedPreview component in group:', {
        embedId: embedId || previewId,
        language,
        filename,
        lineCount,
        status
      });
    } catch (error) {
      console.error('[GroupRenderer] Error mounting CodeEmbedPreview component:', error);
      // Fallback: render the legacy HTML view (better than a blank group item)
      const fallbackHtml = await this.renderCodeItem(item, embedData, decodedContent);
      target.innerHTML = fallbackHtml;
    }
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
      // Create a handler for fullscreen that receives metadata from preview
      // The preview passes its effective values (props or fetched from preview server)
      // so fullscreen can display the same data without re-fetching
      const handleFullscreen = (metadata?: { title?: string; description?: string; favicon?: string; image?: string }) => {
        // Merge preview's fetched metadata with decoded content
        // Preview metadata takes priority since it may have been fetched fresh
        const enrichedContent = {
          ...decodedContent,
          // Override with preview's fetched metadata if provided
          title: metadata?.title || decodedContent?.title,
          description: metadata?.description || decodedContent?.description,
          favicon: metadata?.favicon || decodedContent?.meta_url_favicon || decodedContent?.favicon,
          image: metadata?.image || decodedContent?.thumbnail_original || decodedContent?.image
        };
        
        console.debug('[GroupRenderer] Opening website fullscreen with metadata from preview:', {
          hasPreviewTitle: !!metadata?.title,
          hasPreviewDescription: !!metadata?.description,
          hasPreviewImage: !!metadata?.image
        });
        
        this.openFullscreen(item, embedData, enrichedContent);
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
  
  /**
   * Render video embed using Svelte component
   */
  private async renderVideoComponent(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
    content: HTMLElement
  ): Promise<void> {
    // Use decoded content if available, otherwise fall back to item attributes
    const videoUrl = decodedContent?.url || item.url;
    const videoTitle = decodedContent?.title || item.title;
    
    // Determine status
    const status = item.status || (videoUrl ? 'finished' : 'processing');
    
    // Get embed ID
    const embedId = item.contentRef?.replace('embed:', '') || '';
    
    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn('[GroupRenderer] Error unmounting existing component:', e);
      }
    }
    
    // Clear the content element
    content.innerHTML = '';
    
    // Mount the Svelte component
    try {
      // Create a handler for fullscreen that receives metadata from VideoEmbedPreview
      // The preview passes its effective values (props or fetched from preview server)
      // so fullscreen can display the same data without re-fetching
      // VideoMetadata uses camelCase, but we convert to snake_case for backend TOON format
      const handleFullscreen = (metadata?: {
        videoId?: string;
        title?: string;
        description?: string;
        channelName?: string;
        channelId?: string;
        thumbnailUrl?: string;
        duration?: { totalSeconds: number; formatted: string };
        viewCount?: number;
        likeCount?: number;
        publishedAt?: string;
      }) => {
        // Merge preview's fetched metadata with decoded content
        // Convert VideoMetadata camelCase to backend TOON snake_case format
        const enrichedContent = {
          ...decodedContent,
          // Override with preview's fetched metadata if provided (maps to backend format)
          video_id: metadata?.videoId || decodedContent?.video_id,
          title: metadata?.title || decodedContent?.title,
          description: metadata?.description || decodedContent?.description,
          channel_name: metadata?.channelName || decodedContent?.channel_name,
          channel_id: metadata?.channelId || decodedContent?.channel_id,
          thumbnail: metadata?.thumbnailUrl || decodedContent?.thumbnail,
          duration_seconds: metadata?.duration?.totalSeconds || decodedContent?.duration_seconds,
          duration_formatted: metadata?.duration?.formatted || decodedContent?.duration_formatted,
          view_count: metadata?.viewCount || decodedContent?.view_count,
          like_count: metadata?.likeCount || decodedContent?.like_count,
          published_at: metadata?.publishedAt || decodedContent?.published_at
        };
        
        console.debug('[GroupRenderer] Opening video fullscreen with metadata from preview:', {
          hasPreviewTitle: !!metadata?.title,
          hasPreviewChannel: !!metadata?.channelName,
          hasPreviewThumbnail: !!metadata?.thumbnailUrl,
          hasPreviewDuration: !!metadata?.duration
        });
        
        this.openFullscreen(item, embedData, enrichedContent);
      };
      
      const component = mount(VideoEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          url: videoUrl || '',
          title: videoTitle,
          status: status as 'processing' | 'finished' | 'error',
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen,
          // Pass all metadata from decodedContent (loaded from IndexedDB embed store)
          channelName: decodedContent?.channel_name,
          channelId: decodedContent?.channel_id,
          channelThumbnail: decodedContent?.channel_thumbnail,
          thumbnail: decodedContent?.thumbnail,
          durationSeconds: decodedContent?.duration_seconds,
          durationFormatted: decodedContent?.duration_formatted,
          viewCount: decodedContent?.view_count,
          likeCount: decodedContent?.like_count,
          publishedAt: decodedContent?.published_at,
          videoId: decodedContent?.video_id
        }
      });
      
      // Store reference for cleanup
      mountedComponents.set(content, component);
      
      console.debug('[GroupRenderer] Mounted VideoEmbedPreview component:', {
        embedId,
        url: videoUrl?.substring(0, 50) + '...',
        status,
        hasTitle: !!videoTitle,
        hasChannelThumbnail: !!decodedContent?.channel_thumbnail,
        hasDuration: !!decodedContent?.duration_formatted
      });
      
    } catch (error) {
      console.error('[GroupRenderer] Error mounting VideoEmbedPreview component:', error);
      // Fallback to HTML rendering
      const fallbackHtml = await this.renderVideoItemHTML(item, embedData, decodedContent);
      content.innerHTML = fallbackHtml;
    }
  }
  
  /**
   * Fallback HTML rendering for videos (used when Svelte mount fails)
   */
  private async renderVideoItemHTML(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null
  ): Promise<string> {
    return this.renderVideoItem(item, embedData, decodedContent);
  }
  
  /**
   * Render code embed using Svelte component
   * Uses CodeEmbedPreview for consistent sizing (300x200px desktop, 150x290px mobile)
   */
  private async renderCodeComponent(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
    content: HTMLElement
  ): Promise<void> {
    // Use decoded content if available, otherwise fall back to item attributes
    const language = decodedContent?.language || item.language || 'text';
    const filename = decodedContent?.filename || item.filename;
    const lineCount = decodedContent?.lineCount || item.lineCount || 0;
    
    // For preview embeds (contentRef starts with 'preview:'), get code from item attributes
    // For real embeds, get code from decodedContent
    let codeContent = '';
    if (item.contentRef?.startsWith('preview:')) {
      // Preview embed - code is stored temporarily in item attributes
      codeContent = item.code || '';
      console.debug('[GroupRenderer] Rendering preview code embed with inline code content');
    } else {
      // Real embed - code comes from decodedContent (loaded from EmbedStore)
      codeContent = decodedContent?.code || '';
    }
    
    // Determine status
    const status = item.status || 'finished';
    
    // Get embed ID (remove prefixes for preview embeds)
    const embedId = item.contentRef?.replace('embed:', '')?.replace('preview:code:', '') || item.id || '';
    
    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn('[GroupRenderer] Error unmounting existing component:', e);
      }
    }
    
    // Clear the content element
    content.innerHTML = '';
    
    // Mount the Svelte component
    try {
      // Create a handler for fullscreen that dispatches the event
      const handleFullscreen = () => {
        this.openFullscreen(item, embedData, decodedContent);
      };
      
      const component = mount(CodeEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          language,
          filename,
          lineCount,
          status: status as 'processing' | 'finished' | 'error',
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen,
          codeContent // Pass full code content - component handles preview extraction
        }
      });
      
      // Store reference for cleanup
      mountedComponents.set(content, component);
      
      console.debug('[GroupRenderer] Mounted CodeEmbedPreview component:', {
        embedId,
        language,
        filename,
        lineCount,
        status
      });
      
    } catch (error) {
      console.error('[GroupRenderer] Error mounting CodeEmbedPreview component:', error);
      // Fallback to HTML rendering
      const fallbackHtml = await this.renderCodeItem(item, embedData, decodedContent);
      content.innerHTML = fallbackHtml;
    }
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
      'app-skill-use': 'request',
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
