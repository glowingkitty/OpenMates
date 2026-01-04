/**
 * Unified embed fullscreen handler service
 * 
 * Dynamically resolves and renders the appropriate fullscreen component
 * based on embed type, eliminating the need for if-else chains in ActiveChat.
 * 
 * Usage:
 *   const component = await embedFullscreenHandler.getFullscreenComponent(embedType, data);
 *   // Render component with props
 */

import type { Component, ComponentProps } from 'svelte';

/**
 * Fullscreen component resolver function type
 * Takes embed data and returns component props
 */
type FullscreenComponentResolver = (
  embedFullscreenData: any
) => Promise<{ component: Component; props: Record<string, any> } | null>;

/**
 * Registry of embed type to fullscreen component resolvers
 */
const fullscreenComponentRegistry = new Map<string, FullscreenComponentResolver>();

/**
 * Initialize the fullscreen component registry
 * This dynamically imports components only when needed
 */
async function initializeRegistry(): Promise<void> {
  if (fullscreenComponentRegistry.size > 0) {
    return; // Already initialized
  }

  // App skill use embeds - need special handling based on app_id + skill_id
  fullscreenComponentRegistry.set('app-skill-use', async (data: any) => {
    const appId = data.decodedContent?.app_id || '';
    const skillId = data.decodedContent?.skill_id || '';
    
    // Web search
    if (appId === 'web' && skillId === 'search') {
      const { default: component } = await import('../components/embeds/web/WebSearchEmbedFullscreen.svelte');
      return {
        component,
        props: {
          query: data.decodedContent?.query || '',
          provider: data.decodedContent?.provider || 'Brave',
          results: data.decodedContent?.results || [],
          onClose: data.onClose,
          embedId: data.embedId // Add embedId for sharing functionality
        }
      };
    }
    
    // News search
    if (appId === 'news' && skillId === 'search') {
      const { default: component } = await import('../components/embeds/news/NewsSearchEmbedFullscreen.svelte');
      return {
        component,
        props: {
          query: data.decodedContent?.query || '',
          provider: data.decodedContent?.provider || 'Brave',
          results: data.decodedContent?.results || [],
          onClose: data.onClose,
          embedId: data.embedId // Add embedId for sharing functionality
        }
      };
    }
    
    // Videos search
    if (appId === 'videos' && skillId === 'search') {
      const { default: component } = await import('../components/embeds/videos/VideosSearchEmbedFullscreen.svelte');
      return {
        component,
        props: {
          query: data.decodedContent?.query || '',
          provider: data.decodedContent?.provider || 'Brave Search',
          // Pass embed_ids for loading child video embeds from embedStore
          embedIds: data.decodedContent?.embed_ids || '',
          // Fallback: legacy results prop
          results: data.decodedContent?.results || [],
          onClose: data.onClose,
          embedId: data.embedId // Add embedId for sharing functionality
        }
      };
    }
    
    // Maps search
    if (appId === 'maps' && skillId === 'search') {
      const { default: component } = await import('../components/embeds/maps/MapsSearchEmbedFullscreen.svelte');
      return {
        component,
        props: {
          query: data.decodedContent?.query || '',
          provider: data.decodedContent?.provider || 'Google',
          results: data.decodedContent?.results || [],
          onClose: data.onClose,
          embedId: data.embedId // Add embedId for sharing functionality
        }
      };
    }
    
    // Video transcript
    if (appId === 'videos' && skillId === 'get_transcript') {
      const { default: component } = await import('../components/embeds/videos/VideoTranscriptEmbedFullscreen.svelte');
      return {
        component,
        props: {
          results: data.decodedContent?.results || [],
          status: data.embedData?.status || 'finished',
          onClose: data.onClose,
          embedId: data.embedId // Add embedId for sharing functionality
        }
      };
    }

    // Web read
    if (appId === 'web' && skillId === 'read') {
      const { default: component } = await import('../components/embeds/web/WebReadEmbedFullscreen.svelte');
      return {
        component,
        props: {
          results: data.decodedContent?.results || [],
          status: data.embedData?.status || 'finished',
          onClose: data.onClose,
          embedId: data.embedId // Add embedId for sharing functionality
        }
      };
    }
    
    // Fallback for unknown app skills
    return null;
  });

  // Website embeds
  fullscreenComponentRegistry.set('web-website', async (data: any) => {
    const { default: component } = await import('../components/embeds/web/WebsiteEmbedFullscreen.svelte');
    const url = data.decodedContent?.url || data.attrs?.url || '';
    if (!url) return null;
    
    return {
      component,
      props: {
        url,
        title: data.decodedContent?.title || data.attrs?.title,
        description: data.decodedContent?.description || data.attrs?.description,
        favicon: data.decodedContent?.meta_url_favicon || data.decodedContent?.favicon || data.attrs?.favicon,
        image: data.decodedContent?.thumbnail_original || data.decodedContent?.image || data.attrs?.image,
        snippets: data.decodedContent?.snippets,
        meta_url_favicon: data.decodedContent?.meta_url_favicon,
        thumbnail_original: data.decodedContent?.thumbnail_original,
        onClose: data.onClose,
        embedId: data.embedId // Add embedId for sharing functionality
      }
    };
  });

  // Code embeds
  fullscreenComponentRegistry.set('code-code', async (data: any) => {
    const { default: component } = await import('../components/embeds/code/CodeEmbedFullscreen.svelte');
    const codeContent = data.decodedContent?.code || data.attrs?.code || '';
    if (!codeContent) return null;
    
    return {
      component,
      props: {
        codeContent,
        language: data.decodedContent?.language || data.attrs?.language,
        filename: data.decodedContent?.filename || data.attrs?.filename,
        lineCount: data.decodedContent?.lineCount || data.attrs?.lineCount || 0,
        onClose: data.onClose,
        embedId: data.embedId // Add embedId for sharing functionality
      }
    };
  });

  // Video embeds
  fullscreenComponentRegistry.set('videos-video', async (data: any) => {
    const { default: component } = await import('../components/embeds/videos/VideoEmbedFullscreen.svelte');
    const url = data.decodedContent?.url || data.attrs?.url || '';
    if (!url) return null;
    
    return {
      component,
      props: {
        url,
        title: data.decodedContent?.title || data.attrs?.title,
        onClose: data.onClose,
        embedId: data.embedId // Add embedId for sharing functionality
      }
    };
  });
}

/**
 * Get the fullscreen component and props for an embed type
 * 
 * @param embedType - The embed type (e.g., 'code-code', 'web-website', 'app-skill-use')
 * @param embedFullscreenData - The fullscreen data object from ActiveChat
 * @returns Component and props, or null if no component found
 */
export async function getFullscreenComponent(
  embedType: string,
  embedFullscreenData: any
): Promise<{ component: Component; props: Record<string, any> } | null> {
  await initializeRegistry();
  
  const resolver = fullscreenComponentRegistry.get(embedType);
  if (!resolver) {
    console.warn(`[EmbedFullscreenHandler] No resolver found for embed type: ${embedType}`);
    return null;
  }
  
  try {
    const result = await resolver(embedFullscreenData);
    return result;
  } catch (error) {
    console.error(`[EmbedFullscreenHandler] Error resolving fullscreen component for ${embedType}:`, error);
    return null;
  }
}

/**
 * Check if a fullscreen component exists for an embed type
 */
export async function hasFullscreenComponent(embedType: string): Promise<boolean> {
  await initializeRegistry();
  return fullscreenComponentRegistry.has(embedType);
}

