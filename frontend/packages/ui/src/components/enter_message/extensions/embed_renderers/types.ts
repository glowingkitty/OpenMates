// Types and interfaces for the extensible embed renderer system

import type { EmbedNodeAttributes } from '../../../../message_parsing/types';

/**
 * Context provided to embed renderers for creating DOM content
 */
export interface EmbedRenderContext {
  attrs: EmbedNodeAttributes;
  container: HTMLElement;
  content: HTMLElement;
}

/**
 * Interface for embed type renderers
 * Each embed type (web, video, code, etc.) implements this interface
 */
export interface EmbedRenderer {
  /**
   * The embed type this renderer handles (e.g., 'web', 'video', 'code')
   */
  type: string;
  
  /**
   * Render the embed content into the provided content element
   * @param context - Rendering context with attributes and DOM elements
   */
  render(context: EmbedRenderContext): void;
  
  /**
   * Convert embed back to canonical markdown when user presses backspace
   * @param attrs - Embed node attributes
   * @returns Markdown string representation
   */
  toMarkdown(attrs: EmbedNodeAttributes): string;
  
  /**
   * Optional: Handle updates when attributes change
   * @param context - Rendering context with updated attributes
   * @returns true if update was handled, false to use default update
   */
  update?(context: EmbedRenderContext): boolean;
  
  /**
   * Optional: Clean up resources when node is destroyed
   * @param context - Rendering context
   */
  destroy?(context: EmbedRenderContext): void;
}

/**
 * Registry of embed renderers by type
 */
export interface EmbedRendererRegistry {
  [embedType: string]: EmbedRenderer;
}
