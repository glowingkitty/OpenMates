/**
 * Renderer for app_skill_use embeds (app skill execution results).
 * Handles preview rendering and fullscreen view integration.
 * 
 * Supports:
 * - Web search results (parent app_skill_use with child website embeds)
 * - Single result skills (code generation, image generation, etc.)
 * - Loading embed content from EmbedStore via contentRef
 */

import type { EmbedRenderer, EmbedRenderContext } from './types';
import type { EmbedNodeAttributes } from '../../../../message_parsing/types';
import { resolveEmbed, decodeToonContent } from '../../../../services/embedResolver';

export class AppSkillUseRenderer implements EmbedRenderer {
  type = 'app-skill-use';
  
  async render(context: EmbedRenderContext): Promise<void> {
    const { attrs, content } = context;
    
    // Check if we have a contentRef to load embed data
    if (attrs.contentRef && attrs.contentRef.startsWith('embed:')) {
      const embedId = attrs.contentRef.replace('embed:', '');
      
      // Load embed from EmbedStore
      const embedData = await resolveEmbed(embedId);
      
      if (embedData) {
        // Decode TOON content
        const decodedContent = await decodeToonContent(embedData.content);
        
        // Render based on skill type
        if (decodedContent) {
          const skillId = decodedContent.skill_id || '';
          const appId = decodedContent.app_id || '';
          
          // For web search, render parent embed with child website embeds
          if (skillId === 'search' || appId === 'web') {
            return this.renderWebSearch(attrs, embedData, decodedContent, content);
          }
          
          // For video transcript, render video transcript preview
          if (skillId === 'get_transcript' || (appId === 'videos' && skillId === 'get_transcript')) {
            return this.renderVideoTranscript(attrs, embedData, decodedContent, content);
          }
          
          // For other skills, render generic app skill preview
          return this.renderGenericSkill(attrs, embedData, decodedContent, content);
        }
      }
    }
    
    // Fallback: Render processing state or error
    content.innerHTML = this.renderProcessingState(attrs);
  }
  
  private renderWebSearch(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement
  ): void {
    const query = decodedContent.query || '';
    const provider = decodedContent.provider || 'Brave';
    const childEmbedIds = embedData.embed_ids || [];
    
    // Render web search preview
    const html = `
      <div class="embed-app-icon web">
        <span class="icon icon_web"></span>
      </div>
      <div class="embed-text-content">
        <div class="embed-text-line">Web Search: ${query}</div>
        <div class="embed-text-line">${provider}</div>
      </div>
      <div class="embed-extended-preview">
        <div class="web-search-preview">
          <div class="search-query">${query}</div>
          <div class="search-results-count">${childEmbedIds.length} result${childEmbedIds.length !== 1 ? 's' : ''}</div>
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
    
    // Render video transcript preview
    const html = `
      <div class="embed-app-icon videos">
        <span class="icon icon_videos"></span>
      </div>
      <div class="embed-text-content">
        <div class="embed-text-line">Video Transcript: ${videoTitle}</div>
        <div class="embed-text-line">YouTube Transcript API</div>
      </div>
      <div class="embed-extended-preview">
        <div class="video-transcript-preview">
          <div class="transcript-title">${videoTitle}</div>
          ${wordCount > 0 ? `<div class="transcript-word-count">${wordCount.toLocaleString()} words</div>` : ''}
          ${videoCount > 1 ? `<div class="transcript-video-count">${videoCount} videos</div>` : ''}
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
    
    const html = `
      <div class="embed-app-icon ${appId}">
        <span class="icon icon_${appId}"></span>
      </div>
      <div class="embed-text-content">
        <div class="embed-text-line">${title}</div>
        <div class="embed-text-line">${appId} | ${skillId}</div>
      </div>
      <div class="embed-extended-preview">
        <div class="app-skill-preview-content">
          <div class="skill-result-preview">Skill result preview</div>
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

