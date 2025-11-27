/**
 * Renderer for app_skill_use embeds (app skill execution results).
 * Handles preview rendering and fullscreen view integration.
 * 
 * Uses Svelte 5's mount() to render components into DOM elements.
 * 
 * Supports:
 * - Web search results (parent app_skill_use with child website embeds)
 * - Video transcript skills
 * - Other app skills (generic fallback)
 */

import type { EmbedRenderer, EmbedRenderContext } from './types';
import type { EmbedNodeAttributes } from '../../../../message_parsing/types';
import { resolveEmbed, decodeToonContent } from '../../../../services/embedResolver';
import { mount, unmount } from 'svelte';
import WebSearchEmbedPreview from '../../../embeds/WebSearchEmbedPreview.svelte';
import NewsSearchEmbedPreview from '../../../embeds/NewsSearchEmbedPreview.svelte';
import VideosSearchEmbedPreview from '../../../embeds/VideosSearchEmbedPreview.svelte';
import MapsSearchEmbedPreview from '../../../embeds/MapsSearchEmbedPreview.svelte';

// Track mounted components for cleanup
const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

export class AppSkillUseRenderer implements EmbedRenderer {
  type = 'app-skill-use';
  
  async render(context: EmbedRenderContext): Promise<void> {
    const { attrs, content } = context;
    
    // Check if we have a contentRef to load embed data
    if (attrs.contentRef && attrs.contentRef.startsWith('embed:')) {
      const embedId = attrs.contentRef.replace('embed:', '');
      
      // CRITICAL FIX: Show processing state IMMEDIATELY if attrs.status indicates processing
      // This ensures the user sees "processing" state during streaming, not waiting
      // for the embed data to be fetched. The embed data might arrive with "finished"
      // status due to race conditions in the JavaScript event loop where send_embed_data
      // is processed during the await below.
      if (attrs.status === 'processing') {
        content.innerHTML = this.renderProcessingState(attrs);
        console.debug('[AppSkillUseRenderer] Immediately rendered processing state for embed:', embedId);
        return;
      }
      
      // Load embed from EmbedStore
      const embedData = await resolveEmbed(embedId);
      
      if (embedData) {
        // Decode TOON content
        const decodedContent = await decodeToonContent(embedData.content);
        
        // Render based on skill type
        if (decodedContent) {
          const skillId = decodedContent.skill_id || '';
          const appId = decodedContent.app_id || '';
          
          // For web search, render using Svelte component
          if (appId === 'web' && skillId === 'search') {
            return this.renderWebSearchComponent(attrs, embedData, decodedContent, content);
          }
          
          // For news search, render using Svelte component
          if (appId === 'news' && skillId === 'search') {
            return this.renderNewsSearchComponent(attrs, embedData, decodedContent, content);
          }
          
          // For videos search, render using Svelte component
          if (appId === 'videos' && skillId === 'search') {
            return this.renderVideosSearchComponent(attrs, embedData, decodedContent, content);
          }
          
          // For maps search, render using Svelte component
          if (appId === 'maps' && skillId === 'search') {
            return this.renderMapsSearchComponent(attrs, embedData, decodedContent, content);
          }
          
          // For video transcript, render video transcript preview
          // Check both 'get_transcript' and 'get-transcript' (hyphen variant)
          if (appId === 'videos' && (skillId === 'get_transcript' || skillId === 'get-transcript')) {
            console.debug('[AppSkillUseRenderer] Rendering video transcript for', { appId, skillId, decodedContent });
            return this.renderVideoTranscript(attrs, embedData, decodedContent, content);
          }
          
          // For web read, render web read preview
          if (appId === 'web' && skillId === 'read') {
            return this.renderWebRead(attrs, embedData, decodedContent, content);
          }
          
          // For other skills, render generic app skill preview
          return this.renderGenericSkill(attrs, embedData, decodedContent, content);
        }
      }
    }
    
    // Fallback: Render processing state or error
    content.innerHTML = this.renderProcessingState(attrs);
  }
  
  /**
   * Render web search embed using Svelte component
   * Uses Svelte 5's mount() API to mount the component into the DOM
   */
  private renderWebSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement
  ): void {
    const query = decodedContent.query || '';
    const provider = decodedContent.provider || 'Brave Search';
    const status = decodedContent.status || attrs.status || 'finished';
    const taskId = decodedContent.task_id || '';
    
    // Parse embed_ids to get results count (for display)
    // embed_ids may be a pipe-separated string OR an array
    const rawEmbedIds = decodedContent.embed_ids || embedData.embed_ids || [];
    const childEmbedIds: string[] = typeof rawEmbedIds === 'string' 
      ? rawEmbedIds.split('|').filter((id: string) => id.length > 0)
      : Array.isArray(rawEmbedIds) ? rawEmbedIds : [];
    
    // Create placeholder results with favicon URLs from the results data
    // These will be populated from the decoded content if available
    const results = decodedContent.results || [];
    
    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn('[AppSkillUseRenderer] Error unmounting existing component:', e);
      }
    }
    
    // Clear the content element
    content.innerHTML = '';
    
    // Mount the Svelte component
    try {
      const embedId = attrs.contentRef?.replace('embed:', '') || '';
      
      // Create a handler for fullscreen that dispatches the event
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };
      
      const component = mount(WebSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query,
          provider,
          status: status as 'processing' | 'finished' | 'error',
          results,
          taskId,
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen
        }
      });
      
      // Store reference for cleanup
      mountedComponents.set(content, component);
      
      console.debug('[AppSkillUseRenderer] Mounted WebSearchEmbedPreview component:', {
        embedId,
        query: query.substring(0, 30) + '...',
        status,
        resultsCount: results.length,
        childEmbedIdsCount: childEmbedIds.length
      });
      
    } catch (error) {
      console.error('[AppSkillUseRenderer] Error mounting Svelte component:', error);
      // Fallback to HTML rendering
      this.renderWebSearchHTML(attrs, embedData, decodedContent, content);
    }
  }
  
  /**
   * Render news search embed using Svelte component
   */
  private renderNewsSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement
  ): void {
    const query = decodedContent.query || '';
    const provider = decodedContent.provider || 'Brave Search';
    const status = decodedContent.status || attrs.status || 'finished';
    const taskId = decodedContent.task_id || '';
    const results = decodedContent.results || [];
    
    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn('[AppSkillUseRenderer] Error unmounting existing component:', e);
      }
    }
    
    content.innerHTML = '';
    
    try {
      const embedId = attrs.contentRef?.replace('embed:', '') || '';
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };
      
      const component = mount(NewsSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query,
          provider,
          status: status as 'processing' | 'finished' | 'error',
          results,
          taskId,
          isMobile: false,
          onFullscreen: handleFullscreen
        }
      });
      
      mountedComponents.set(content, component);
      console.debug('[AppSkillUseRenderer] Mounted NewsSearchEmbedPreview component');
    } catch (error) {
      console.error('[AppSkillUseRenderer] Error mounting NewsSearchEmbedPreview:', error);
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }
  
  /**
   * Render videos search embed using Svelte component
   */
  private renderVideosSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement
  ): void {
    const query = decodedContent.query || '';
    const provider = decodedContent.provider || 'Brave Search';
    const status = decodedContent.status || attrs.status || 'finished';
    const taskId = decodedContent.task_id || '';
    const results = decodedContent.results || [];
    
    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn('[AppSkillUseRenderer] Error unmounting existing component:', e);
      }
    }
    
    content.innerHTML = '';
    
    try {
      const embedId = attrs.contentRef?.replace('embed:', '') || '';
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };
      
      const component = mount(VideosSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query,
          provider,
          status: status as 'processing' | 'finished' | 'error',
          results,
          taskId,
          isMobile: false,
          onFullscreen: handleFullscreen
        }
      });
      
      mountedComponents.set(content, component);
      console.debug('[AppSkillUseRenderer] Mounted VideosSearchEmbedPreview component');
    } catch (error) {
      console.error('[AppSkillUseRenderer] Error mounting VideosSearchEmbedPreview:', error);
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }
  
  /**
   * Render maps search embed using Svelte component
   */
  private renderMapsSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement
  ): void {
    const query = decodedContent.query || '';
    const provider = decodedContent.provider || 'Google';
    const status = decodedContent.status || attrs.status || 'finished';
    const taskId = decodedContent.task_id || '';
    const results = decodedContent.results || [];
    
    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn('[AppSkillUseRenderer] Error unmounting existing component:', e);
      }
    }
    
    content.innerHTML = '';
    
    try {
      const embedId = attrs.contentRef?.replace('embed:', '') || '';
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };
      
      const component = mount(MapsSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query,
          provider,
          status: status as 'processing' | 'finished' | 'error',
          results,
          taskId,
          isMobile: false,
          onFullscreen: handleFullscreen
        }
      });
      
      mountedComponents.set(content, component);
      console.debug('[AppSkillUseRenderer] Mounted MapsSearchEmbedPreview component');
    } catch (error) {
      console.error('[AppSkillUseRenderer] Error mounting MapsSearchEmbedPreview:', error);
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }
  
  /**
   * Fallback HTML rendering for web search (used when Svelte mount fails)
   */
  private renderWebSearchHTML(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement
  ): void {
    const query = decodedContent.query || '';
    const provider = decodedContent.provider || 'Brave Search';
    
    // embed_ids may be a pipe-separated string OR an array - normalize and count
    const rawEmbedIds = decodedContent.embed_ids || embedData.embed_ids || [];
    const childEmbedIds: string[] = typeof rawEmbedIds === 'string' 
      ? rawEmbedIds.split('|').filter((id: string) => id.length > 0)
      : Array.isArray(rawEmbedIds) ? rawEmbedIds : [];
    
    const status = decodedContent.status || attrs.status || 'finished';
    const resultCount = childEmbedIds.length;
    
    // Render web search preview matching Figma design (300x200px desktop, 150x290px mobile)
    // Use desktop layout by default in message view
    const html = `
      <div class="app-skill-preview-container web-search desktop">
        <div class="app-skill-preview-inner">
          <!-- Web icon -->
          <div class="icon_rounded web"></div>
          
          <!-- Title section -->
          <div class="skill-title-section">
            <div class="skill-title">${this.escapeHtml(query)}</div>
            <div class="skill-subtitle">via ${this.escapeHtml(provider)}</div>
          </div>
          
          <!-- Status bar -->
          <div class="skill-status-bar">
            <div class="skill-icon" data-skill-icon="search"></div>
            <div class="skill-status-content">
              <span class="skill-status-label">Search</span>
              <span class="skill-status-text">${status === 'processing' ? 'Processing...' : 'Completed'}</span>
            </div>
          </div>
          
          <!-- Results count (only when finished) -->
          ${status === 'finished' && resultCount > 0 ? `
            <div class="skill-results-indicator">
              ${resultCount} result${resultCount !== 1 ? 's' : ''}
            </div>
          ` : ''}
          
          <!-- Processing indicator -->
          ${status === 'processing' ? `
            <div class="skill-processing-indicator">
              <div class="processing-dot"></div>
            </div>
          ` : ''}
        </div>
      </div>
    `;
    
    content.innerHTML = html;
    
    // Add click handler for fullscreen
    if (status === 'finished') {
      content.addEventListener('click', () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      });
      content.style.cursor = 'pointer';
    }
  }
  
  /**
   * Escape HTML special characters to prevent XSS
   */
  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
  
  private renderVideoTranscript(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement
  ): void {
    const results = decodedContent.results || [];
    const firstResult = results[0] || {};
    const videoTitle = firstResult.metadata?.title || firstResult.url || 'Video Transcript';
    const wordCount = firstResult.word_count || 0;
    const videoCount = results.length || 0;
    const status = decodedContent.status || attrs.status || 'finished';
    
    // Render video transcript preview with proper container structure
    // This matches the structure used by other embed previews
    const html = `
      <div class="embed-unified-container embed-finished" 
           data-embed-type="app-skill-use" 
           data-embed-status="${status}"
           ${status === 'finished' ? 'style="cursor: pointer;"' : ''}>
        <div class="embed-content">
          <div class="embed-app-icon videos">
            <span class="icon icon_videos"></span>
          </div>
          <div class="embed-text-content">
            <div class="embed-text-line">Video Transcript: ${this.escapeHtml(videoTitle)}</div>
            <div class="embed-text-line">via YouTube Transcript API</div>
          </div>
          <div class="embed-extended-preview">
            <div class="video-transcript-preview">
              <div class="transcript-title">${this.escapeHtml(videoTitle)}</div>
              ${wordCount > 0 ? `<div class="transcript-word-count">${wordCount.toLocaleString()} words</div>` : ''}
              ${videoCount > 1 ? `<div class="transcript-video-count">${videoCount} videos</div>` : ''}
            </div>
          </div>
        </div>
      </div>
    `;
    
    content.innerHTML = html;
    
    // Add click handler for fullscreen
    if (status === 'finished') {
      const container = content.querySelector('.embed-unified-container');
      if (container) {
        container.addEventListener('click', () => {
          this.openFullscreen(attrs, embedData, decodedContent);
        });
      }
    }
  }
  
  /**
   * Render web read skill embed preview
   * Shows website information from read results
   */
  private renderWebRead(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement
  ): void {
    // Extract results array - all skills return results as an array
    const results = decodedContent.results || [];
    const firstResult = results[0] || {};
    
    // Extract website information from first result
    const url = firstResult.url || '';
    const title = firstResult.title || '';
    const hostname = url ? new URL(url).hostname : '';
    const displayTitle = title || hostname || 'Website';
    const resultCount = results.length;
    
    // Render web read preview
    const html = `
      <div class="embed-unified-container embed-finished" 
           data-embed-type="app-skill-use" 
           data-embed-status="finished"
           ${attrs.status === 'finished' ? 'style="cursor: pointer;"' : ''}>
        <div class="embed-content">
          <div class="embed-app-icon web">
            <span class="icon icon_web"></span>
          </div>
          <div class="embed-text-content">
            <div class="embed-text-line">${this.escapeHtml(displayTitle)}</div>
            <div class="embed-text-line">${hostname ? this.escapeHtml(hostname) : 'Web Read'}</div>
          </div>
          <div class="embed-extended-preview">
            <div class="web-read-preview">
              ${resultCount > 1 ? `<div class="read-result-count">${resultCount} pages read</div>` : ''}
              ${url ? `<div class="read-url">${this.escapeHtml(url)}</div>` : ''}
            </div>
          </div>
        </div>
      </div>
    `;
    
    content.innerHTML = html;
    
    // Add click handler for fullscreen
    if (attrs.status === 'finished') {
      content.addEventListener('click', () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      });
      content.style.cursor = 'pointer';
    }
  }
  
  private renderGenericSkill(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement
  ): void {
    const skillId = decodedContent.skill_id || '';
    const appId = decodedContent.app_id || '';
    const title = attrs.title || `${appId} | ${skillId}`;
    const status = decodedContent.status || attrs.status || 'finished';
    
    // Log when generic skill is rendered (for debugging)
    console.debug('[AppSkillUseRenderer] Rendering generic skill:', { appId, skillId, decodedContent });
    
    const html = `
      <div class="embed-unified-container embed-finished" 
           data-embed-type="app-skill-use" 
           data-embed-status="${status}"
           ${status === 'finished' ? 'style="cursor: pointer;"' : ''}>
        <div class="embed-content">
          <div class="embed-app-icon ${appId}">
            <span class="icon icon_${appId}"></span>
          </div>
          <div class="embed-text-content">
            <div class="embed-text-line">${this.escapeHtml(title)}</div>
            <div class="embed-text-line">${appId} | ${skillId}</div>
          </div>
          <div class="embed-extended-preview">
            <div class="app-skill-preview-content">
              <div class="skill-result-preview">Skill result preview</div>
            </div>
          </div>
        </div>
      </div>
    `;
    
    content.innerHTML = html;
    
    // Add click handler for fullscreen
    if (status === 'finished') {
      const container = content.querySelector('.embed-unified-container');
      if (container) {
        container.addEventListener('click', () => {
          this.openFullscreen(attrs, embedData, decodedContent);
        });
      }
    }
  }
  
  private renderProcessingState(attrs: EmbedNodeAttributes): string {
    return `
      <div class="embed-app-icon web">
        <span class="icon icon_web"></span>
      </div>
      <div class="embed-text-content">
        <div class="embed-text-line">Processing...</div>
        <div class="embed-text-line">Please wait</div>
      </div>
      <div class="embed-extended-preview">
        <div class="processing-indicator">
          <div class="processing-dot"></div>
        </div>
      </div>
    `;
  }
  
  private async openFullscreen(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any
  ): Promise<void> {
    // Dispatch custom event to open fullscreen view
    // The fullscreen component will handle loading and displaying embed content
    const event = new CustomEvent('embedfullscreen', {
      detail: {
        embedId: attrs.contentRef?.replace('embed:', ''),
        embedData,
        decodedContent,
        embedType: 'app-skill-use',
        attrs
      },
      bubbles: true
    });
    
    document.dispatchEvent(event);
    console.debug('[AppSkillUseRenderer] Dispatched fullscreen event:', event.detail);
  }
  
  toMarkdown(attrs: EmbedNodeAttributes): string {
    // Convert back to JSON code block format
    if (attrs.contentRef && attrs.contentRef.startsWith('embed:')) {
      const embedId = attrs.contentRef.replace('embed:', '');
      return `\`\`\`json\n{\n  "type": "app_skill_use",\n  "embed_id": "${embedId}"\n}\n\`\`\`\n\n`;
    }
    
    // Fallback to basic markdown
    return `[App Skill: ${attrs.type}]`;
  }
}
