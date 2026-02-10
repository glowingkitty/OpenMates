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

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import {
  resolveEmbed,
  decodeToonContent,
} from "../../../../services/embedResolver";
import { mount, unmount } from "svelte";
import WebSearchEmbedPreview from "../../../embeds/web/WebSearchEmbedPreview.svelte";
import NewsSearchEmbedPreview from "../../../embeds/news/NewsSearchEmbedPreview.svelte";
import VideosSearchEmbedPreview from "../../../embeds/videos/VideosSearchEmbedPreview.svelte";
import MapsSearchEmbedPreview from "../../../embeds/maps/MapsSearchEmbedPreview.svelte";
import VideoTranscriptEmbedPreview from "../../../embeds/videos/VideoTranscriptEmbedPreview.svelte";
import WebReadEmbedPreview from "../../../embeds/web/WebReadEmbedPreview.svelte";
import CodeGetDocsEmbedPreview from "../../../embeds/code/CodeGetDocsEmbedPreview.svelte";
import ReminderEmbedPreview from "../../../embeds/reminder/ReminderEmbedPreview.svelte";
import TravelSearchEmbedPreview from "../../../embeds/travel/TravelSearchEmbedPreview.svelte";
import TravelPriceCalendarEmbedPreview from "../../../embeds/travel/TravelPriceCalendarEmbedPreview.svelte";
import ImageGenerateEmbedPreview from "../../../embeds/images/ImageGenerateEmbedPreview.svelte";

// Track mounted components for cleanup
const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

export class AppSkillUseRenderer implements EmbedRenderer {
  type = "app-skill-use";

  async render(context: EmbedRenderContext): Promise<void> {
    const { attrs, content } = context;

    // CRITICAL: Extract app_id and skill_id from attrs FIRST
    // These are parsed from the JSON embed reference in embedParsing.ts
    // and are available even before embed data arrives from the server
    const attrsAppId = (attrs as any).app_id || "";
    const attrsSkillId = (attrs as any).skill_id || "";
    const attrsQuery = (attrs as any).query || "";

    // Check if we have a contentRef to load embed data
    let embedData: any = null;
    let decodedContent: any = null;

    if (attrs.contentRef && attrs.contentRef.startsWith("embed:")) {
      const embedId = attrs.contentRef.replace("embed:", "");

      // Load embed from EmbedStore (even if processing, so we can mount the correct component)
      embedData = await resolveEmbed(embedId);

      if (embedData) {
        // CRITICAL FIX: Filter out error embeds with "superseded" message
        // These are placeholder embeds that were replaced by multiple request-specific embeds
        // They should not be rendered to avoid showing confusing error messages
        if (embedData.status === "error") {
          const errorContent = await decodeToonContent(embedData.content);
          if (errorContent && errorContent.error) {
            const errorMessage = errorContent.error;
            if (
              typeof errorMessage === "string" &&
              errorMessage.includes("superseded")
            ) {
              console.debug(
                "[AppSkillUseRenderer] Skipping superseded error embed:",
                embedId,
              );
              // Don't render this embed - it was replaced by multiple specific embeds
              content.innerHTML = "";
              return;
            }
          }
        }

        // Decode TOON content (may be minimal for processing state)
        // Even in processing state, the content should have app_id and skill_id
        try {
          decodedContent = embedData.content
            ? await decodeToonContent(embedData.content)
            : null;
        } catch (error) {
          console.debug(
            "[AppSkillUseRenderer] Error decoding content, may be processing state:",
            error,
          );
          // Continue with null decodedContent - we'll use attrs for rendering
        }
      }
    }

    // Determine app_id and skill_id - check multiple sources in priority order:
    // 1. decodedContent (from TOON content decoding) - most reliable for finished embeds
    // 2. embedData directly (from memory cache for processing embeds)
    // 3. attrs (from JSON embed reference parsing)
    const appId = decodedContent?.app_id || embedData?.app_id || attrsAppId;
    const skillId =
      decodedContent?.skill_id || embedData?.skill_id || attrsSkillId;

    // Determine status - prefer embedData status, then attrs.status, then 'processing'
    const status = embedData?.status || attrs.status || "processing";

    // CRITICAL: Skip rendering error embeds - they should be hidden from users
    // Failed skill executions should not be shown in the user experience
    if (status === "error") {
      console.debug(
        `[AppSkillUseRenderer] Hiding error embed from user:`,
        attrs.contentRef || attrs.id,
      );
      content.innerHTML = "";
      return;
    }

    // CRITICAL: Merge query from multiple sources to ensure it's available for display
    // Priority: decodedContent > embedData > attrs
    if (!decodedContent) {
      decodedContent = {};
    }
    if (!decodedContent.query) {
      decodedContent.query = embedData?.query || attrsQuery;
    }
    // Also merge provider if not set
    if (!decodedContent.provider) {
      decodedContent.provider = embedData?.provider;
    }
    // Also merge results if not set (for processing -> finished transition)
    if (!decodedContent.results && embedData?.results) {
      decodedContent.results = embedData.results;
    }

    console.debug("[AppSkillUseRenderer] Rendering embed:", {
      appId,
      skillId,
      status,
      hasEmbedData: !!embedData,
      hasDecodedContent: !!decodedContent,
      attrsAppId,
      attrsSkillId,
      attrsQuery,
    });

    // Render based on skill type - use Svelte components for ALL states (including processing)
    // This ensures consistent styling and proper preview display during streaming
    if (appId && skillId) {
      // For web search, render using Svelte component
      if (appId === "web" && skillId === "search") {
        return this.renderWebSearchComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For news search, render using Svelte component
      if (appId === "news" && skillId === "search") {
        return this.renderNewsSearchComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For videos search, render using Svelte component
      if (appId === "videos" && skillId === "search") {
        return this.renderVideosSearchComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For maps search, render using Svelte component
      if (appId === "maps" && skillId === "search") {
        return this.renderMapsSearchComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For travel search_connections, render using Svelte component
      if (appId === "travel" && skillId === "search_connections") {
        return this.renderTravelSearchComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For travel price_calendar, render price calendar preview
      if (appId === "travel" && skillId === "price_calendar") {
        return this.renderTravelPriceCalendarComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For video transcript, render video transcript preview using Svelte component
      // Check both 'get_transcript' and 'get-transcript' (hyphen variant)
      if (
        appId === "videos" &&
        (skillId === "get_transcript" || skillId === "get-transcript")
      ) {
        console.debug("[AppSkillUseRenderer] Rendering video transcript for", {
          appId,
          skillId,
          decodedContent,
          status,
        });
        return this.renderVideoTranscriptComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For web read, render web read preview
      if (appId === "web" && skillId === "read") {
        return this.renderWebReadComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For code get_docs, render documentation preview using Svelte component
      if (appId === "code" && skillId === "get_docs") {
        console.debug("[AppSkillUseRenderer] Rendering code get_docs for", {
          appId,
          skillId,
          decodedContent,
          status,
        });
        return this.renderCodeGetDocsComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For reminder set_reminder, render reminder preview using Svelte component
      // Check both 'set_reminder' and 'set-reminder' (hyphen variant)
      if (
        appId === "reminder" &&
        (skillId === "set_reminder" || skillId === "set-reminder")
      ) {
        console.debug(
          "[AppSkillUseRenderer] Rendering reminder set_reminder for",
          { appId, skillId, decodedContent, status },
        );
        return this.renderReminderComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For image generation, render image preview using Svelte component
      if (
        appId === "images" &&
        (skillId === "generate" || skillId === "generate_draft")
      ) {
        console.debug("[AppSkillUseRenderer] Rendering image generate for", {
          appId,
          skillId,
          decodedContent,
          status,
        });
        return this.renderImageGenerateComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For other skills with known app_id/skill_id, render generic app skill preview
      return this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }

    // LAST RESORT: If we truly don't know what type of embed this is, render generic processing
    // This should rarely happen since attrs should have app_id/skill_id from the JSON reference
    console.warn(
      "[AppSkillUseRenderer] Unknown embed type, rendering generic processing state:",
      attrs,
    );
    return this.renderGenericProcessingState(attrs, content);
  }

  /**
   * Render web search embed using Svelte component
   * Uses Svelte 5's mount() API to mount the component into the DOM
   */
  private renderWebSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent and embedData gracefully
    // During streaming, these may be null until embed data arrives from server
    const query = decodedContent?.query || (attrs as any).query || "";
    const provider = decodedContent?.provider || "Brave Search";
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    // CRITICAL: skill_task_id is used for individual skill cancellation (allows AI to continue)
    const skillTaskId = decodedContent?.skill_task_id || "";

    // Parse embed_ids to get results count (for display)
    // embed_ids may be a pipe-separated string OR an array
    // CRITICAL: Handle null embedData
    const rawEmbedIds = decodedContent?.embed_ids || embedData?.embed_ids || [];
    const childEmbedIds: string[] =
      typeof rawEmbedIds === "string"
        ? rawEmbedIds.split("|").filter((id: string) => id.length > 0)
        : Array.isArray(rawEmbedIds)
          ? rawEmbedIds
          : [];

    // Create placeholder results with favicon URLs from the results data
    // These will be populated from the decoded content if available
    const results = decodedContent?.results || [];

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    // Clear the content element
    content.innerHTML = "";

    // Mount the Svelte component
    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";

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
          status: status as "processing" | "finished" | "error",
          results,
          taskId,
          skillTaskId, // For individual skill cancellation
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen,
        },
      });

      // Store reference for cleanup
      mountedComponents.set(content, component);

      console.debug(
        "[AppSkillUseRenderer] Mounted WebSearchEmbedPreview component:",
        {
          embedId,
          query: query.substring(0, 30) + "...",
          status,
          resultsCount: results.length,
          childEmbedIdsCount: childEmbedIds.length,
        },
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting Svelte component:",
        error,
      );
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
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent and embedData gracefully
    const query = decodedContent?.query || (attrs as any).query || "";
    const provider = decodedContent?.provider || "Brave Search";
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const skillTaskId = decodedContent?.skill_task_id || ""; // For individual skill cancellation
    const results = decodedContent?.results || [];

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    content.innerHTML = "";

    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };

      const component = mount(NewsSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query,
          provider,
          status: status as "processing" | "finished" | "error",
          results,
          taskId,
          skillTaskId, // For individual skill cancellation
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted NewsSearchEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting NewsSearchEmbedPreview:",
        error,
      );
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
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent and embedData gracefully
    const query = decodedContent?.query || (attrs as any).query || "";
    const provider = decodedContent?.provider || "Brave Search";
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const skillTaskId = decodedContent?.skill_task_id || ""; // For individual skill cancellation
    const results = decodedContent?.results || [];

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    content.innerHTML = "";

    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };

      const component = mount(VideosSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query,
          provider,
          status: status as "processing" | "finished" | "error",
          results,
          taskId,
          skillTaskId, // For individual skill cancellation
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted VideosSearchEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting VideosSearchEmbedPreview:",
        error,
      );
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
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent and embedData gracefully
    const query = decodedContent?.query || (attrs as any).query || "";
    const provider = decodedContent?.provider || "Google";
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const skillTaskId = decodedContent?.skill_task_id || ""; // For individual skill cancellation
    const results = decodedContent?.results || [];

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    content.innerHTML = "";

    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };

      const component = mount(MapsSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query,
          provider,
          status: status as "processing" | "finished" | "error",
          results,
          taskId,
          skillTaskId, // For individual skill cancellation
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted MapsSearchEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting MapsSearchEmbedPreview:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render travel search_connections embed using Svelte component
   */
  private renderTravelSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const query = decodedContent?.query || (attrs as any).query || "";
    const provider = decodedContent?.provider || "Google";
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const skillTaskId = decodedContent?.skill_task_id || "";
    const results = decodedContent?.results || [];

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    content.innerHTML = "";

    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };

      const component = mount(TravelSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query,
          provider,
          status: status as "processing" | "finished" | "error",
          results,
          taskId,
          skillTaskId,
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted TravelSearchEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting TravelSearchEmbedPreview:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render travel price_calendar embed using Svelte component
   */
  private renderTravelPriceCalendarComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const query = decodedContent?.query || (attrs as any).query || "";
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const skillTaskId = decodedContent?.skill_task_id || "";
    const results = decodedContent?.results || [];

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    content.innerHTML = "";

    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };

      const component = mount(TravelPriceCalendarEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query,
          status: status as "processing" | "finished" | "error",
          results,
          taskId,
          skillTaskId,
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted TravelPriceCalendarEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting TravelPriceCalendarEmbedPreview:",
        error,
      );
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
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent and embedData gracefully
    const query = decodedContent?.query || (attrs as any).query || "";
    const provider = decodedContent?.provider || "Brave Search";

    // embed_ids may be a pipe-separated string OR an array - normalize and count
    const rawEmbedIds = decodedContent?.embed_ids || embedData?.embed_ids || [];
    const childEmbedIds: string[] =
      typeof rawEmbedIds === "string"
        ? rawEmbedIds.split("|").filter((id: string) => id.length > 0)
        : Array.isArray(rawEmbedIds)
          ? rawEmbedIds
          : [];

    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
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
              <span class="skill-status-text">${status === "processing" ? "Processing..." : "Completed"}</span>
            </div>
          </div>
          
          <!-- Results count (only when finished) -->
          ${
            status === "finished" && resultCount > 0
              ? `
            <div class="skill-results-indicator">
              ${resultCount} result${resultCount !== 1 ? "s" : ""}
            </div>
          `
              : ""
          }
          
          <!-- Processing indicator -->
          ${
            status === "processing"
              ? `
            <div class="skill-processing-indicator">
              <div class="processing-dot"></div>
            </div>
          `
              : ""
          }
        </div>
      </div>
    `;

    content.innerHTML = html;

    // Add click handler for fullscreen
    if (status === "finished") {
      content.addEventListener("click", () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      });
      content.style.cursor = "pointer";
    }
  }

  /**
   * Escape HTML special characters to prevent XSS
   */
  private escapeHtml(text: string): string {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Render web read embed using Svelte component
   */
  private renderWebReadComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent and embedData gracefully
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const skillTaskId = decodedContent?.skill_task_id || ""; // For individual skill cancellation
    const results = decodedContent?.results || [];

    // CRITICAL: Extract URL from decodedContent for processing placeholders
    // The processing placeholder stores url at the root level (not in results)
    // This ensures we can display the website info even before results are available
    const url = decodedContent?.url || "";

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    content.innerHTML = "";

    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };

      const component = mount(WebReadEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          status: status as "processing" | "finished" | "error",
          results,
          url, // Pass URL from processing placeholder content
          taskId,
          skillTaskId, // For individual skill cancellation
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted WebReadEmbedPreview component:",
        {
          embedId,
          status,
          resultsCount: results.length,
          url: url ? url.substring(0, 50) + "..." : "none",
        },
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting WebReadEmbedPreview:",
        error,
      );
      this.renderWebReadFallbackHTML(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render video transcript embed using Svelte component
   * Uses Svelte 5's mount() API to mount the component into the DOM
   */
  private renderVideoTranscriptComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent and embedData gracefully
    const results = decodedContent?.results || [];
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const skillTaskId = decodedContent?.skill_task_id || ""; // For individual skill cancellation

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    // Clear the content element
    content.innerHTML = "";

    // Mount the Svelte component
    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";

      // Create a handler for fullscreen that dispatches the event
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };

      const component = mount(VideoTranscriptEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          results,
          status: status as "processing" | "finished" | "error",
          taskId,
          skillTaskId, // For individual skill cancellation
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen,
        },
      });

      // Store reference for cleanup
      mountedComponents.set(content, component);

      console.debug(
        "[AppSkillUseRenderer] Mounted VideoTranscriptEmbedPreview component:",
        {
          embedId,
          status,
          resultsCount: results.length,
        },
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting VideoTranscriptEmbedPreview component:",
        error,
      );
      // Fallback to HTML rendering
      this.renderVideoTranscriptHTML(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Fallback HTML rendering for video transcript (used when Svelte mount fails)
   */
  private renderVideoTranscriptHTML(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent and embedData gracefully
    const results = decodedContent?.results || [];
    const firstResult = results[0] || {};
    const videoTitle =
      firstResult.metadata?.title || firstResult.url || "Video Transcript";
    const wordCount = firstResult.word_count || 0;
    const videoCount = results.length || 0;
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";

    // Render video transcript preview - no need for embed-unified-container wrapper
    // The container is already provided by Embed.ts, just create the content directly
    const html = `
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
            ${wordCount > 0 ? `<div class="transcript-word-count">${wordCount.toLocaleString()} words</div>` : ""}
            ${videoCount > 1 ? `<div class="transcript-video-count">${videoCount} videos</div>` : ""}
          </div>
        </div>
      </div>
    `;

    content.innerHTML = html;

    // Add click handler for fullscreen
    if (status === "finished") {
      content.style.cursor = "pointer";
      content.addEventListener("click", () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      });
    }
  }

  /**
   * Render code get_docs embed using Svelte component
   * Uses Svelte 5's mount() API to mount the component into the DOM
   */
  private renderCodeGetDocsComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent and embedData gracefully
    const results = decodedContent?.results || [];
    const library = decodedContent?.library || (attrs as any).library || "";
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const skillTaskId = decodedContent?.skill_task_id || ""; // For individual skill cancellation

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    // Clear the content element
    content.innerHTML = "";

    // Mount the Svelte component
    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";

      // Create a handler for fullscreen that dispatches the event
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };

      const component = mount(CodeGetDocsEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          results,
          library,
          status: status as "processing" | "finished" | "error",
          taskId,
          skillTaskId, // For individual skill cancellation
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen,
        },
      });

      // Store reference for cleanup
      mountedComponents.set(content, component);

      console.debug(
        "[AppSkillUseRenderer] Mounted CodeGetDocsEmbedPreview component:",
        {
          embedId,
          status,
          resultsCount: results.length,
          library,
        },
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting CodeGetDocsEmbedPreview component:",
        error,
      );
      // Fallback to generic skill rendering
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render reminder set_reminder embed using Svelte component
   * Uses Svelte 5's mount() API to mount the component into the DOM
   */
  private renderReminderComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent and embedData gracefully
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";

    // Extract reminder-specific fields from decoded content
    const reminderId = decodedContent?.reminder_id || "";
    const triggerAtFormatted = decodedContent?.trigger_at_formatted || "";
    const triggerAt = decodedContent?.trigger_at;
    const targetType = decodedContent?.target_type;
    const isRepeating = decodedContent?.is_repeating || false;
    const prompt = decodedContent?.prompt || "";
    const message = decodedContent?.message || "";
    const emailNotificationWarning =
      decodedContent?.email_notification_warning || "";
    const error = decodedContent?.error || "";

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    // Clear the content element
    content.innerHTML = "";

    // Mount the Svelte component
    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";

      // Create a handler for fullscreen that dispatches the event
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };

      const component = mount(ReminderEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          reminderId,
          triggerAtFormatted,
          triggerAt,
          targetType,
          isRepeating,
          prompt,
          message,
          emailNotificationWarning,
          status: status as "processing" | "finished" | "error",
          error,
          taskId,
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen,
        },
      });

      // Store reference for cleanup
      mountedComponents.set(content, component);

      console.debug(
        "[AppSkillUseRenderer] Mounted ReminderEmbedPreview component:",
        {
          embedId,
          status,
          reminderId,
          triggerAtFormatted,
        },
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting ReminderEmbedPreview component:",
        error,
      );
      // Fallback to generic skill rendering
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render image generate embed using Svelte component
   * Uses Svelte 5's mount() API to mount the component into the DOM
   */
  private renderImageGenerateComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent and embedData gracefully
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";

    // Extract image-specific fields from decoded content
    const prompt = decodedContent?.prompt || "";
    const s3BaseUrl = decodedContent?.s3_base_url || "";
    const files = decodedContent?.files || undefined;
    const aesKey = decodedContent?.aes_key || "";
    const aesNonce = decodedContent?.aes_nonce || "";
    const error = decodedContent?.error || "";

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    // Clear the content element
    content.innerHTML = "";

    // Mount the Svelte component
    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";

      // Create a handler for fullscreen that dispatches the event
      const handleFullscreen = () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      };

      const component = mount(ImageGenerateEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          prompt,
          s3BaseUrl,
          files,
          aesKey,
          aesNonce,
          status: status as "processing" | "finished" | "error",
          error,
          taskId,
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen,
        },
      });

      // Store reference for cleanup
      mountedComponents.set(content, component);

      console.debug(
        "[AppSkillUseRenderer] Mounted ImageGenerateEmbedPreview component:",
        {
          embedId,
          status,
          prompt: prompt.substring(0, 30) + "...",
        },
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting ImageGenerateEmbedPreview component:",
        error,
      );
      // Fallback to generic skill rendering
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Fallback HTML rendering for web read (used when Svelte mount fails)
   */
  private renderWebReadFallbackHTML(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent gracefully
    // Extract results array - all skills return results as an array
    const results = decodedContent?.results || [];
    const firstResult = results[0] || {};

    // Extract website information - check both result and root level (processing placeholder)
    // Processing placeholder stores URL at root level, finished embed stores in results
    const url = firstResult.url || decodedContent?.url || "";
    const title = firstResult.title || "";
    let hostname = "";
    if (url) {
      try {
        hostname = new URL(url).hostname;
      } catch {
        const withoutScheme = url.replace(/^[a-zA-Z]+:\/\//, "");
        hostname = withoutScheme.split("/")[0] || "";
      }
    }
    const displayTitle = title || hostname || "Web Read";
    const resultCount = results.length;

    // Render web read preview - no need for embed-unified-container wrapper
    // The container is already provided by Embed.ts, just create the content directly
    const html = `
      <div class="embed-content">
        <div class="embed-app-icon web">
          <span class="icon icon_web"></span>
        </div>
        <div class="embed-text-content">
          <div class="embed-text-line">${this.escapeHtml(displayTitle)}</div>
          <div class="embed-text-line">${hostname ? this.escapeHtml(hostname) : "Web Read"}</div>
        </div>
        <div class="embed-extended-preview">
          <div class="web-read-preview">
            ${resultCount > 1 ? `<div class="read-result-count">${resultCount} pages read</div>` : ""}
            ${url ? `<div class="read-url">${this.escapeHtml(url)}</div>` : ""}
          </div>
        </div>
      </div>
    `;

    content.innerHTML = html;

    // Add click handler for fullscreen
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    if (status === "finished") {
      content.style.cursor = "pointer";
      content.addEventListener("click", () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      });
    }
  }

  private renderGenericSkill(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    // CRITICAL: Handle null decodedContent gracefully - use attrs as fallback
    const skillId = decodedContent?.skill_id || (attrs as any).skill_id || "";
    const appId = decodedContent?.app_id || (attrs as any).app_id || "";
    const title = attrs.title || `${appId} | ${skillId}`;
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";

    // Log when generic skill is rendered (for debugging)
    console.debug("[AppSkillUseRenderer] Rendering generic skill:", {
      appId,
      skillId,
      decodedContent,
    });

    // Render generic skill preview - no need for embed-unified-container wrapper
    // The container is already provided by Embed.ts, just create the content directly
    const html = `
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
    `;

    content.innerHTML = html;

    // Add click handler for fullscreen
    if (status === "finished") {
      content.style.cursor = "pointer";
      content.addEventListener("click", () => {
        this.openFullscreen(attrs, embedData, decodedContent);
      });
    }
  }

  /**
   * Render a generic processing state when we don't know the embed type
   * Uses the WebSearchEmbedPreview component as a fallback with processing status
   * This ensures consistent styling even when embed type is unknown
   */
  private renderGenericProcessingState(
    attrs: EmbedNodeAttributes,
    content: HTMLElement,
  ): void {
    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[AppSkillUseRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    // Clear the content element
    content.innerHTML = "";

    // Mount a generic WebSearchEmbedPreview with processing status as fallback
    // This provides a consistent UI while we wait for more information
    try {
      const embedId = attrs.contentRef?.replace("embed:", "") || "";

      const component = mount(WebSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query: "Loading...",
          provider: "",
          status: "processing" as const,
          results: [],
          taskId: "",
          isMobile: false,
          onFullscreen: undefined,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted generic processing component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting generic processing component:",
        error,
      );
      // Ultimate fallback: simple HTML
      content.innerHTML = `
        <div class="embed-app-icon web">
          <span class="icon icon_web"></span>
        </div>
        <div class="embed-text-content">
          <div class="embed-text-line">Processing...</div>
        </div>
      `;
    }
  }

  private async openFullscreen(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
  ): Promise<void> {
    // Dispatch custom event to open fullscreen view
    // The fullscreen component will handle loading and displaying embed content
    const event = new CustomEvent("embedfullscreen", {
      detail: {
        embedId: attrs.contentRef?.replace("embed:", ""),
        embedData,
        decodedContent,
        embedType: "app-skill-use",
        attrs,
      },
      bubbles: true,
    });

    document.dispatchEvent(event);
    console.debug(
      "[AppSkillUseRenderer] Dispatched fullscreen event:",
      event.detail,
    );
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    // Convert back to JSON code block format
    if (attrs.contentRef && attrs.contentRef.startsWith("embed:")) {
      const embedId = attrs.contentRef.replace("embed:", "");
      return `\`\`\`json\n{\n  "type": "app_skill_use",\n  "embed_id": "${embedId}"\n}\n\`\`\`\n\n`;
    }

    // Fallback to basic markdown
    return `[App Skill: ${attrs.type}]`;
  }
}
