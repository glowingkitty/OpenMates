/* eslint-disable @typescript-eslint/no-explicit-any */
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
 *
 * Note: `any` is intentionally used throughout this file for embed data
 * received from dynamic TOON-decoded content with unknown schemas.
 */

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import {
  resolveEmbed,
  decodeToonContent,
  isEmbedKnownError,
} from "../../../../services/embedResolver";
import { chatSyncService } from "../../../../services/chatSyncService";
import { unmarkEmbedAsProcessed } from "../../../../services/chatSyncServiceHandlersAI";
import { embedStore } from "../../../../services/embedStore";
import { mount, unmount } from "svelte";
import WebSearchEmbedPreview from "../../../embeds/web/WebSearchEmbedPreview.svelte";
import MailSearchEmbedPreview from "../../../embeds/mail/MailSearchEmbedPreview.svelte";
import NewsSearchEmbedPreview from "../../../embeds/news/NewsSearchEmbedPreview.svelte";
import VideosSearchEmbedPreview from "../../../embeds/videos/VideosSearchEmbedPreview.svelte";
import MapsSearchEmbedPreview from "../../../embeds/maps/MapsSearchEmbedPreview.svelte";
import MapsLocationEmbedPreview from "../../../embeds/maps/MapsLocationEmbedPreview.svelte";
import VideoTranscriptEmbedPreview from "../../../embeds/videos/VideoTranscriptEmbedPreview.svelte";
import WebReadEmbedPreview from "../../../embeds/web/WebReadEmbedPreview.svelte";
import CodeGetDocsEmbedPreview from "../../../embeds/code/CodeGetDocsEmbedPreview.svelte";
import ReminderEmbedPreview from "../../../embeds/reminder/ReminderEmbedPreview.svelte";
import TravelSearchEmbedPreview from "../../../embeds/travel/TravelSearchEmbedPreview.svelte";
import TravelPriceCalendarEmbedPreview from "../../../embeds/travel/TravelPriceCalendarEmbedPreview.svelte";
import TravelStaysEmbedPreview from "../../../embeds/travel/TravelStaysEmbedPreview.svelte";
import ImageGenerateEmbedPreview from "../../../embeds/images/ImageGenerateEmbedPreview.svelte";
import ImageViewEmbedPreview from "../../../embeds/images/ImageViewEmbedPreview.svelte";
import PdfViewEmbedPreview from "../../../embeds/pdf/PdfViewEmbedPreview.svelte";
import PdfReadEmbedPreview from "../../../embeds/pdf/PdfReadEmbedPreview.svelte";
import PdfSearchEmbedPreview from "../../../embeds/pdf/PdfSearchEmbedPreview.svelte";
import HealthSearchEmbedPreview from "../../../embeds/health/HealthSearchEmbedPreview.svelte";
import ShoppingSearchEmbedPreview from "../../../embeds/shopping/ShoppingSearchEmbedPreview.svelte";
import EventsSearchEmbedPreview from "../../../embeds/events/EventsSearchEmbedPreview.svelte";
import MathCalculateEmbedPreview from "../../../embeds/math/MathCalculateEmbedPreview.svelte";
import ImagesSearchEmbedPreview from "../../../embeds/images/ImagesSearchEmbedPreview.svelte";
import ImageResultEmbedPreview from "../../../embeds/images/ImageResultEmbedPreview.svelte";
import HomeSearchEmbedPreview from "../../../embeds/home/HomeSearchEmbedPreview.svelte";
import { proxyImage } from "../../../../utils/imageProxy";

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

      // DECRYPTION FAILURE RECOVERY: If the embed loaded from IndexedDB but failed to decrypt
      // (e.g. on tab reload when embed key could not be unwrapped), evict the broken entry and
      // re-request fresh data from the server. The server response (send_embed_data) includes
      // embed_keys, which lets the client try the unwrap again with a clean store state.
      // Without this, the embed would be permanently hidden because status="error" is set by
      // the decryption failure path, causing the "hide error embeds" guard below to fire.
      if (embedData?._decryptionFailed) {
        console.warn(
          "[AppSkillUseRenderer] Embed decryption failed — evicting and re-requesting from server:",
          embedId,
        );
        try {
          // Evict the undecryptable entry so the next resolveEmbed() triggers a server fetch.
          await embedStore.deleteEmbed(embedId);
        } catch (deleteError) {
          console.warn(
            "[AppSkillUseRenderer] Could not evict decryption-failed embed:",
            deleteError,
          );
        }
        // Register a one-shot listener so we re-render the moment fresh data arrives.
        const decryptRetryHandler = (event: Event) => {
          const customEvent = event as CustomEvent<{ embed_id: string }>;
          if (customEvent.detail?.embed_id !== embedId) return;
          chatSyncService.removeEventListener(
            "embedUpdated",
            decryptRetryHandler,
          );
          this.render(context).catch((err) => {
            console.error(
              "[AppSkillUseRenderer] Error in decryption-retry re-render:",
              err,
            );
          });
        };
        chatSyncService.addEventListener("embedUpdated", decryptRetryHandler);
        // CRITICAL: Remove this embed from the processed-embeds set before requesting
        // fresh data. If the embed was processed in this session (e.g., during live
        // generation), `isEmbedAlreadyProcessed` would silently drop the incoming
        // `send_embed_data` response, preventing re-encryption with the new key.
        unmarkEmbedAsProcessed(embedId);

        // Request fresh embed data from the server (includes embed_keys for re-decryption).
        try {
          const { webSocketService } =
            await import("../../../../services/websocketService");
          await webSocketService.sendMessage("request_embed", {
            embed_id: embedId,
          });
        } catch (requestError) {
          console.warn(
            "[AppSkillUseRenderer] Could not request embed from server after decryption failure:",
            requestError,
          );
        }
        // Leave content empty (processing skeleton) while waiting for the server response.
        content.innerHTML = "";
        return;
      }

      // If the embed is not in IndexedDB yet but the node attributes already say "finished",
      // the send_embed_data WebSocket event hasn't been processed yet (race condition). Register
      // a one-shot listener so we re-render the moment the embed data arrives. Without this,
      // the embed renders with an empty decodedContent and stays stuck on the skeleton forever
      // because renderImageViewComponent (and similar) won't call resolveAndUpdateImageViewProps
      // when originalEmbedId is empty (fix for issue #5dc543b0 — images view never shows image).
      if (
        !embedData &&
        attrs.status === "finished" &&
        !isEmbedKnownError(embedId)
      ) {
        // Retry resolveEmbed() a few times to handle Phase 1 IDB timing gap.
        // The 50ms delay in chatSyncServiceHandlersCoreSync.ts before phase_1_last_chat_ready
        // may not be enough for all IDB transactions to become visible. Two short retries
        // cover the common case without introducing perceptible latency.
        for (let attempt = 1; attempt <= 2 && !embedData; attempt++) {
          await new Promise((resolve) => setTimeout(resolve, 200 * attempt));
          embedData = await resolveEmbed(embedId);
          if (embedData) {
            try {
              decodedContent = embedData.content
                ? await decodeToonContent(embedData.content)
                : null;
            } catch {
              decodedContent = null;
            }
            console.debug(
              `[AppSkillUseRenderer] Embed found on IDB retry ${attempt}:`,
              embedId,
            );
          }
        }

        // Only register the embedUpdated listener if still missing after retries
        if (!embedData) {
          const retryHandler = (event: Event) => {
            const customEvent = event as CustomEvent<{ embed_id: string }>;
            if (customEvent.detail?.embed_id !== embedId) return;
            chatSyncService.removeEventListener("embedUpdated", retryHandler);
            // Re-invoke the full render() so all routing + component mounting runs with fresh data.
            this.render(context).catch((err) => {
              console.error(
                "[AppSkillUseRenderer] Error in embedUpdated re-render for finished embed:",
                err,
              );
            });
          };
          chatSyncService.addEventListener("embedUpdated", retryHandler);
          console.debug(
            "[AppSkillUseRenderer] Embed not cached yet (finished status), waiting for embedUpdated:",
            embedId,
          );
        }
      }

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
    let skillId =
      decodedContent?.skill_id || embedData?.skill_id || attrsSkillId;

    // CHILD EMBED TYPE OVERRIDE: Child embeds (e.g. image_result from images/search)
    // store the parent's skill_id ("search") in their TOON content, but their actual
    // child type must be inferred. Two signals are checked in priority order:
    //
    // 1. New embeds: backend now sends skill_id = child_type in the WebSocket payload,
    //    stored as embedData.skill_id. After our backend fix this will be "image_result".
    //
    // 2. Old/stored embeds: skill_id = "search" (the parent's) is stored in IndexedDB.
    //    Detect child type by checking TOON content fields unique to each child type:
    //    - image_result: has image_url or thumbnail_url
    //    - web_result / search_result: has url + title but no image_url
    //
    // See docs/architecture/embeds.md for the full embed type resolution chain.
    const CHILD_TYPE_OVERRIDES: Record<string, boolean> = {
      image_result: true,
      web_result: true,
      news_result: true,
      video_result: true,
      location: true,
      flight: true,
      stay: true,
      event: true,
      product: true,
      job: true,
      health_result: true,
      recipe: true,
      price_calendar_result: true,
      listing: true,
    };
    const childType = decodedContent?.type || embedData?.type;
    if (childType && CHILD_TYPE_OVERRIDES[childType as string]) {
      skillId = childType as string;
    } else if (attrsSkillId && CHILD_TYPE_OVERRIDES[attrsSkillId]) {
      // EmbedReferencePreview already detected the child type and set it in attrs
      skillId = attrsSkillId;
    } else if (
      appId === "images" &&
      skillId === "search" &&
      decodedContent &&
      !decodedContent.embed_ids
    ) {
      // Heuristic for stored child embeds: parent images/search embeds always have
      // embed_ids in their content; child image_result embeds have image_url instead.
      // If this is images/search WITHOUT embed_ids, it's actually a child image_result.
      if (decodedContent.image_url || decodedContent.thumbnail_url) {
        skillId = "image_result";
      }
    }

    // Determine status - prefer embedData status, then check knownErrorEmbeds (for error embeds
    // that are intentionally never persisted to IndexedDB), then attrs.status, then 'processing'.
    // Without the knownErrorEmbeds check, error embeds show as "Completed" because:
    // 1. embedData is null (error embeds are never stored by design)
    // 2. attrs.status is 'finished' (set by the AI stream before the error signal arrived)
    // 3. The error guard below never fires, and the card renders with 0 results as "Completed"
    const statusEmbedId = attrs.contentRef?.replace("embed:", "") || "";
    const isKnownError = statusEmbedId
      ? isEmbedKnownError(statusEmbedId)
      : false;
    const status =
      embedData?.status ||
      (isKnownError ? "error" : null) ||
      attrs.status ||
      "processing";

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

      // For mail search, render using Svelte component
      if (appId === "mail" && skillId === "search") {
        return this.renderMailSearchComponent(
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

      // For maps location (user-selected location pin), render using Svelte component
      if (appId === "maps" && skillId === "location") {
        return this.renderMapsLocationComponent(
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

      // For travel search_stays, render stays preview
      if (appId === "travel" && skillId === "search_stays") {
        return this.renderTravelStaysComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For health search_appointments, render health appointment search preview
      if (appId === "health" && skillId === "search_appointments") {
        return this.renderHealthSearchComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For shopping search_products, render shopping product search preview
      if (appId === "shopping" && skillId === "search_products") {
        return this.renderShoppingSearchComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }
      // For images search, render images search preview using Svelte component
      if (appId === "images" && skillId === "search") {
        return this.renderImagesSearchComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For image_result embeds (standalone image from image search)
      if (appId === "images" && skillId === "image_result") {
        return this.renderImageResultComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For events search, render events search preview using Svelte component
      if (appId === "events" && skillId === "search") {
        return this.renderEventsSearchComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For home search, render housing search preview using Svelte component
      if (appId === "home" && skillId === "search") {
        return this.renderHomeSearchComponent(
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

      // For images/view skill, render image view preview with original embed fullscreen
      if (appId === "images" && skillId === "view") {
        console.debug("[AppSkillUseRenderer] Rendering images view for", {
          appId,
          skillId,
          decodedContent,
          status,
        });
        return this.renderImageViewComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For pdf/view skill, render PDF view preview with original embed fullscreen
      if (appId === "pdf" && skillId === "view") {
        console.debug("[AppSkillUseRenderer] Rendering pdf view for", {
          appId,
          skillId,
          decodedContent,
          status,
        });
        return this.renderPdfViewComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For pdf/read skill, render PDF read preview with original embed fullscreen
      if (appId === "pdf" && skillId === "read") {
        console.debug("[AppSkillUseRenderer] Rendering pdf read for", {
          appId,
          skillId,
          decodedContent,
          status,
        });
        return this.renderPdfReadComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For pdf/search skill, render PDF search preview with original embed fullscreen
      if (appId === "pdf" && skillId === "search") {
        console.debug("[AppSkillUseRenderer] Rendering pdf search for", {
          appId,
          skillId,
          decodedContent,
          status,
        });
        return this.renderPdfSearchComponent(
          attrs,
          embedData,
          decodedContent,
          content,
        );
      }

      // For math calculate, render math calculate preview using Svelte component
      if (appId === "math" && skillId === "calculate") {
        console.debug("[AppSkillUseRenderer] Rendering math calculate for", {
          appId,
          skillId,
          decodedContent,
          status,
        });
        return this.renderMathCalculateComponent(
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
   * Render mail search embed using Svelte component
   */
  private renderMailSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const query =
      decodedContent?.query || (attrs as any).query || "Recent emails";
    const provider = decodedContent?.provider || "Proton Mail Bridge";
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const skillTaskId = decodedContent?.skill_task_id || "";
    const results = decodedContent?.results || [];

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

      const component = mount(MailSearchEmbedPreview, {
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
        "[AppSkillUseRenderer] Mounted MailSearchEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting MailSearchEmbedPreview:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
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
   * Render maps location embed using Svelte component.
   * Triggered when a user selects a location via the MapsView map picker.
   * Displays a static map image with the selected location pin.
   */
  private renderMapsLocationComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";

    // Extract location-specific fields
    const lat = decodedContent?.lat ?? undefined;
    const lon = decodedContent?.lon ?? undefined;
    const zoom = decodedContent?.zoom ?? 15;
    const name = decodedContent?.name || "";
    const locationType = decodedContent?.location_type || "precise_location";
    const mapImageUrl = decodedContent?.map_image_url || "";

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

      const component = mount(MapsLocationEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          lat,
          lon,
          zoom,
          name,
          locationType,
          mapImageUrl: mapImageUrl || undefined,
          status: status as "processing" | "finished" | "error",
          taskId,
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted MapsLocationEmbedPreview component:",
        { embedId, status, lat, lon, name },
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting MapsLocationEmbedPreview:",
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
   * Render travel search_stays embed using Svelte component
   */
  private renderTravelStaysComponent(
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

      const component = mount(TravelStaysEmbedPreview, {
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
        "[AppSkillUseRenderer] Mounted TravelStaysEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting TravelStaysEmbedPreview:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render health search_appointments embed using Svelte component.
   * Mirrors renderTravelSearchComponent exactly — same props pattern.
   */
  private renderHealthSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const query = decodedContent?.query || (attrs as any).query || "";
    const provider = decodedContent?.provider || "Doctolib";
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

      const component = mount(HealthSearchEmbedPreview, {
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
        "[AppSkillUseRenderer] Mounted HealthSearchEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting HealthSearchEmbedPreview:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render shopping search_products embed using Svelte component.
   * Mirrors renderHealthSearchComponent exactly — same props pattern.
   */
  private renderShoppingSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const query = decodedContent?.query || (attrs as any).query || "";
    const provider = decodedContent?.provider || "REWE";
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

      const component = mount(ShoppingSearchEmbedPreview, {
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
        "[AppSkillUseRenderer] Mounted ShoppingSearchEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting ShoppingSearchEmbedPreview:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render events search embed using Svelte component.
   * Event results are stored inline in the parent embed TOON — no child embeds needed.
   */
  private renderEventsSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const query = decodedContent?.query || (attrs as any).query || "";
    const provider = decodedContent?.provider || "Meetup";
    const providers: string[] = (decodedContent?.providers as string[]) || [];
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

      const component = mount(EventsSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query,
          provider,
          providers,
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
        "[AppSkillUseRenderer] Mounted EventsSearchEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting EventsSearchEmbedPreview:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render home search embed using Svelte component (home/search skill).
   * Shows housing listings from ImmoScout24, Kleinanzeigen, and WG-Gesucht.
   */
  private renderHomeSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const query = decodedContent?.query || (attrs as any).query || "";
    const provider = decodedContent?.provider || "Multi";
    const providers: string[] = (decodedContent?.providers as string[]) || [];
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

      const component = mount(HomeSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          query,
          provider,
          providers,
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
        "[AppSkillUseRenderer] Mounted HomeSearchEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting HomeSearchEmbedPreview:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render the images search preview component (images/search skill).
   * Shows thumbnail mosaic and handles processing -> finished transition.
   */
  private renderImagesSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const query = decodedContent?.query || (attrs as any).query || "";
    const provider = decodedContent?.provider || "Brave";
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const skillTaskId = decodedContent?.skill_task_id || "";
    const results = decodedContent?.results || [];

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
      const component = mount(ImagesSearchEmbedPreview, {
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
        "[AppSkillUseRenderer] Mounted ImagesSearchEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting ImagesSearchEmbedPreview:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render a standalone image_result embed preview.
   * Uses ImageResultEmbedPreview in standalone mode (wraps in UnifiedEmbedPreview).
   */
  private renderImageResultComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const title = decodedContent?.title || "";
    const sourceDomain = decodedContent?.source || "";
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";

    // Proxy external image URLs
    const rawImageUrl = decodedContent?.image_url || "";
    const rawThumbnailUrl = decodedContent?.thumbnail_url || "";
    const rawFaviconUrl = decodedContent?.favicon_url || "";
    const imageUrl = rawImageUrl ? proxyImage(rawImageUrl) : undefined;
    const thumbnailUrl = rawThumbnailUrl
      ? proxyImage(rawThumbnailUrl)
      : undefined;
    const faviconUrl = rawFaviconUrl ? proxyImage(rawFaviconUrl) : undefined;

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
      const component = mount(ImageResultEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          title,
          sourceDomain,
          thumbnailUrl,
          imageUrl,
          faviconUrl,
          status: status as "processing" | "finished" | "error",
          taskId,
          isMobile: false,
          onFullscreen: handleFullscreen,
          standalone: true,
        },
      });
      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted ImageResultEmbedPreview (standalone)",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting ImageResultEmbedPreview:",
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

    const rawStatus =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const resultCount = childEmbedIds.length;
    // Detect failed searches: status is "finished" but 0 results AND content has error field.
    // This happens when individual search queries fail (rate limit, sanitization block, etc.)
    // but the skill execution itself "finished" successfully.
    const hasGroupError = !!decodedContent?.error;
    const status =
      rawStatus !== "processing" && resultCount === 0 && hasGroupError
        ? "error"
        : rawStatus;

    // Render web search preview matching Figma design (300x200px desktop, 150x290px mobile)
    // Use desktop layout by default in message view
    const statusLabel =
      status === "processing"
        ? "Processing..."
        : status === "error"
          ? "Failed"
          : "Completed";
    const statusClass = status === "error" ? " search-error" : "";
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
          <div class="skill-status-bar${statusClass}">
            <div class="skill-icon" data-skill-icon="search"></div>
            <div class="skill-status-content">
              <span class="skill-status-label">Search</span>
              <span class="skill-status-text">${statusLabel}</span>
            </div>
          </div>
          
          <!-- Results count (only when finished with results) -->
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
    // Extract URL from decoded content — the processing placeholder includes the
    // YouTube URL from request metadata so metadata fetch can start immediately.
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
          url, // YouTube URL from placeholder metadata — enables early metadata fetch
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
    const model = decodedContent?.model || "";
    const s3BaseUrl = decodedContent?.s3_base_url || "";
    const files = decodedContent?.files || undefined;
    const aesKey = decodedContent?.aes_key || "";
    const aesNonce = decodedContent?.aes_nonce || "";
    const error = decodedContent?.error || "";
    const inputEmbedIds: string[] = Array.isArray(
      decodedContent?.input_embed_ids,
    )
      ? decodedContent.input_embed_ids
      : [];
    // Determine the actual skill ID from embed content or attributes
    const imageSkillId =
      decodedContent?.skill_id || attrs.skill_id || "generate";

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
          skillId: imageSkillId as "generate" | "generate_draft",
          prompt,
          model,
          s3BaseUrl,
          files,
          aesKey,
          aesNonce,
          status: status as "processing" | "finished" | "error",
          error,
          taskId,
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen,
          inputEmbedIds: inputEmbedIds.length > 0 ? inputEmbedIds : undefined,
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

  /**
   * Open the ORIGINAL uploaded image's fullscreen viewer.
   * Resolves the original image upload embed by embed_id, then fires
   * 'imagefullscreen' CustomEvent so ActiveChat mounts ImageEmbedFullscreen.
   *
   * If the upload embed is not yet cached (sync still in flight), waits for the
   * 'embedUpdated' event and retries — preventing silent failures when the user
   * clicks the view embed card immediately after a fresh upload.
   */
  private async openImageUploadFullscreen(embedId: string): Promise<void> {
    if (!embedId) {
      console.warn(
        "[AppSkillUseRenderer] openImageUploadFullscreen: no embed_id",
      );
      return;
    }

    /**
     * Fire the imagefullscreen event from a decoded upload embed content object.
     * Returns true if the event was dispatched, false if content was unavailable.
     */
    const dispatchFullscreenEvent = async (
      uploadEmbed: any,
    ): Promise<boolean> => {
      if (!uploadEmbed) return false;
      const uploadContent = uploadEmbed.content
        ? await decodeToonContent(uploadEmbed.content)
        : null;

      const event = new CustomEvent("imagefullscreen", {
        detail: {
          src: undefined, // no local blob URL (this is a persisted embed)
          filename:
            uploadContent?.filename || (uploadEmbed as any).filename || "",
          s3Files: uploadContent?.files || undefined,
          s3BaseUrl: uploadContent?.s3_base_url || "",
          aesKey: uploadContent?.aes_key || "",
          aesNonce: uploadContent?.aes_nonce || "",
          isAuthenticated: true,
          fileSize: uploadContent?.file_size,
          fileType: uploadContent?.file_type,
          aiDetection: uploadContent?.ai_detection ?? null,
        },
        bubbles: true,
      });
      document.dispatchEvent(event);
      console.debug(
        "[AppSkillUseRenderer] Dispatched imagefullscreen for upload embed:",
        embedId,
      );
      return true;
    };

    try {
      const uploadEmbed = await resolveEmbed(embedId);
      if (await dispatchFullscreenEvent(uploadEmbed)) return;

      // Embed not in cache yet — register a one-shot listener and retry when it arrives
      console.debug(
        "[AppSkillUseRenderer] Upload embed not cached yet for fullscreen, waiting for embedUpdated:",
        embedId,
      );
      const handler = (event: Event) => {
        const customEvent = event as CustomEvent<{ embed_id: string }>;
        if (customEvent.detail?.embed_id !== embedId) return;

        chatSyncService.removeEventListener("embedUpdated", handler);

        resolveEmbed(embedId)
          .then((fresh) => dispatchFullscreenEvent(fresh))
          .catch((err) => {
            console.error(
              "[AppSkillUseRenderer] Failed to open fullscreen after embedUpdated:",
              err,
            );
          });
      };
      chatSyncService.addEventListener("embedUpdated", handler);
    } catch (err) {
      console.error(
        "[AppSkillUseRenderer] Failed to open image upload fullscreen:",
        err,
      );
    }
  }

  /**
   * Open the ORIGINAL uploaded PDF's fullscreen viewer.
   * Resolves the original PDF upload embed by embed_id, then fires
   * 'pdffullscreen' CustomEvent so ActiveChat mounts PDFEmbedFullscreen.
   */
  private async openPdfUploadFullscreen(embedId: string): Promise<void> {
    if (!embedId) {
      console.warn(
        "[AppSkillUseRenderer] openPdfUploadFullscreen: no embed_id",
      );
      return;
    }
    try {
      const uploadEmbed = await resolveEmbed(embedId);
      if (!uploadEmbed) {
        console.warn(
          "[AppSkillUseRenderer] Could not resolve original PDF embed:",
          embedId,
        );
        return;
      }
      const uploadContent = uploadEmbed.content
        ? await decodeToonContent(uploadEmbed.content)
        : null;

      const event = new CustomEvent("pdffullscreen", {
        detail: {
          // embedId is required by PDFEmbedFullscreen to load TOON content from IDB
          embedId,
          filename:
            uploadContent?.filename || (uploadEmbed as any).filename || "",
          pageCount:
            uploadContent?.page_count ??
            (uploadEmbed as any).page_count ??
            null,
        },
        bubbles: true,
      });
      document.dispatchEvent(event);
      console.debug(
        "[AppSkillUseRenderer] Dispatched pdffullscreen for upload embed:",
        embedId,
      );
    } catch (err) {
      console.error(
        "[AppSkillUseRenderer] Failed to open PDF upload fullscreen:",
        err,
      );
    }
  }

  /**
   * Dispatch 'pdfreadfullscreen' so ActiveChat mounts PdfReadEmbedFullscreen.
   * Carries the skill-use embed ID + extracted text content.
   */
  private openPdfReadFullscreen(
    embedId: string,
    filename: string,
    pagesReturned: number[],
    pagesSkipped: number[],
    textContent: string,
  ): void {
    const event = new CustomEvent("pdfreadfullscreen", {
      detail: {
        embedId,
        filename,
        pagesReturned,
        pagesSkipped,
        textContent,
      },
      bubbles: true,
    });
    document.dispatchEvent(event);
    console.debug(
      "[AppSkillUseRenderer] Dispatched pdfreadfullscreen:",
      embedId,
    );
  }

  /**
   * Dispatch 'pdfsearchfullscreen' so ActiveChat mounts PdfSearchEmbedFullscreen.
   * Carries the skill-use embed ID + search query + matches.
   */
  private openPdfSearchFullscreen(
    embedId: string,
    filename: string,
    query: string,
    totalMatches: number | undefined,
    truncated: boolean,
    matches: any[],
  ): void {
    const event = new CustomEvent("pdfsearchfullscreen", {
      detail: {
        embedId,
        filename,
        query,
        totalMatches,
        truncated,
        matches,
      },
      bubbles: true,
    });
    document.dispatchEvent(event);
    console.debug(
      "[AppSkillUseRenderer] Dispatched pdfsearchfullscreen:",
      embedId,
    );
  }

  /**
   * Render images/view skill embed using ImageViewEmbedPreview component.
   * On fullscreen click, opens the original uploaded image's fullscreen viewer.
   */
  private renderImageViewComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const error = decodedContent?.error || "";

    // embed_id references the original uploaded image embed
    const originalEmbedId = decodedContent?.embed_id || "";

    // Filename from the original embed (backend includes it in the skill output text)
    const filename = decodedContent?.filename || "";

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

      // On fullscreen click: open the ORIGINAL uploaded image's fullscreen
      const handleFullscreen = () => {
        this.openImageUploadFullscreen(originalEmbedId);
      };

      const component = mount(ImageViewEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          filename,
          status: status as "processing" | "finished" | "error",
          error,
          isMobile: false,
          // Wire fullscreen — will only be triggered when status === 'finished' (UnifiedEmbedPreview
          // only calls onFullscreen on click when finished). handler is always defined to satisfy
          // the required prop, but is effectively a no-op during processing/error states.
          onFullscreen: handleFullscreen,
          // S3 data will be resolved from the original embed by the component
          // (passed via AppSkillUseRenderer after resolving the original embed)
        },
      });

      mountedComponents.set(content, component);

      // If finished: resolve the original embed to get S3 data for image preview
      if (status === "finished" && originalEmbedId) {
        this.resolveAndUpdateImageViewProps(
          content,
          originalEmbedId,
          component,
          handleFullscreen,
        );
      }

      // On first load (live generation), the TOON content stored in IDB is a
      // processing placeholder that has no embed_id yet. When the finalized
      // send_embed_data WS event arrives, the IDB entry is updated with the real
      // embed_id, but this component instance is already mounted and won't
      // re-render automatically. Register a one-shot 'embedUpdated' listener so
      // we re-call renderImageViewComponent with the fresh data once it arrives.
      if (!originalEmbedId && embedId) {
        const imageViewRetryHandler = (event: Event) => {
          const customEvent = event as CustomEvent<{ embed_id: string }>;
          if (customEvent.detail?.embed_id !== embedId) return;
          chatSyncService.removeEventListener(
            "embedUpdated",
            imageViewRetryHandler,
          );
          // Re-run the full render() so renderImageViewComponent is called again
          // with the updated decodedContent (which will now have a real embed_id).
          // We resolve fresh embedData + decodedContent via re-render().
          resolveEmbed(embedId)
            .then(async (freshEmbedData) => {
              const freshDecoded = freshEmbedData?.content
                ? await decodeToonContent(freshEmbedData.content)
                : null;
              this.renderImageViewComponent(
                attrs,
                freshEmbedData,
                freshDecoded,
                content,
              );
            })
            .catch((err) => {
              console.error(
                "[AppSkillUseRenderer] Error in imageViewRetryHandler re-render:",
                err,
              );
            });
        };
        chatSyncService.addEventListener("embedUpdated", imageViewRetryHandler);
        console.debug(
          "[AppSkillUseRenderer] ImageView embed has no embed_id yet, waiting for embedUpdated:",
          embedId,
        );
      }

      console.debug(
        "[AppSkillUseRenderer] Mounted ImageViewEmbedPreview component:",
        {
          embedId,
          status,
          originalEmbedId,
          filename,
        },
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting ImageViewEmbedPreview component:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Resolve the original image upload embed and update the ImageViewEmbedPreview
   * component with S3 data so it can show the actual image preview.
   *
   * If the upload embed is not yet in IndexedDB (e.g. sync is still in flight),
   * registers a one-shot 'embedUpdated' listener and retries automatically when
   * the embed arrives — same pattern as ImageRenderer.ts for restored draft images.
   */
  private async resolveAndUpdateImageViewProps(
    content: HTMLElement,
    originalEmbedId: string,
    component: ReturnType<typeof mount>,
    handleFullscreen: () => void,
  ): Promise<void> {
    /**
     * Inner helper: decode the upload embed content and remount the preview
     * with S3 data. Returns true if the remount succeeded, false otherwise.
     */
    const tryUpdateWithEmbed = async (uploadEmbed: any): Promise<boolean> => {
      if (!uploadEmbed) return false;
      const uploadContent = uploadEmbed.content
        ? await decodeToonContent(uploadEmbed.content)
        : null;
      if (!uploadContent) return false;

      // Re-mount with S3 data populated from the original embed.
      // Unmount + remount because Svelte 5 mount() props are not reactive after mount.
      const existingComponent = mountedComponents.get(content);
      if (!existingComponent) return false;

      try {
        unmount(existingComponent);
      } catch {
        // ignore
      }

      content.innerHTML = "";

      const s3Files = uploadContent.files as
        | Record<
            string,
            {
              s3_key: string;
              width: number;
              height: number;
              size_bytes: number;
              format: string;
            }
          >
        | undefined;

      const updated = mount(ImageViewEmbedPreview, {
        target: content,
        props: {
          id: originalEmbedId,
          filename: (uploadContent.filename as string) || "",
          status: "finished" as const,
          isMobile: false,
          onFullscreen: handleFullscreen,
          s3BaseUrl: (uploadContent.s3_base_url as string) || "",
          s3Files,
          aesKey: (uploadContent.aes_key as string) || "",
          aesNonce: (uploadContent.aes_nonce as string) || "",
        },
      });

      mountedComponents.set(content, updated);
      console.debug(
        "[AppSkillUseRenderer] Updated ImageViewEmbedPreview with S3 data for embed:",
        originalEmbedId,
      );
      return true;
    };

    try {
      const uploadEmbed = await resolveEmbed(originalEmbedId);
      if (await tryUpdateWithEmbed(uploadEmbed)) return;

      // Upload embed not in IndexedDB yet (e.g. still syncing from server or the
      // embed_data WS event hasn't arrived yet). Register a one-shot listener and
      // retry when the embed is delivered — same approach as ImageRenderer.ts.
      console.debug(
        "[AppSkillUseRenderer] Original image embed not cached yet, waiting for embedUpdated:",
        originalEmbedId,
      );
      const handler = (event: Event) => {
        const customEvent = event as CustomEvent<{ embed_id: string }>;
        if (customEvent.detail?.embed_id !== originalEmbedId) return;

        // Remove listener immediately to avoid duplicate remounts
        chatSyncService.removeEventListener("embedUpdated", handler);

        resolveEmbed(originalEmbedId)
          .then((fresh) => tryUpdateWithEmbed(fresh))
          .catch((err) => {
            console.error(
              "[AppSkillUseRenderer] Failed to update ImageViewEmbedPreview after embedUpdated:",
              err,
            );
          });
      };
      chatSyncService.addEventListener("embedUpdated", handler);
    } catch (err) {
      console.error(
        "[AppSkillUseRenderer] Error resolving original image embed for preview:",
        err,
      );
    }
  }

  /**
   * Render pdf/view skill embed using PdfViewEmbedPreview component.
   * On fullscreen click, opens the original uploaded PDF's fullscreen viewer.
   */
  private renderPdfViewComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const error = decodedContent?.error || "";

    // embed_id references the original uploaded PDF embed
    const originalEmbedId = decodedContent?.embed_id || "";

    // Pages viewed (the LLM passes this as an array)
    const pages: number[] = Array.isArray(decodedContent?.pages)
      ? decodedContent.pages
      : [];

    // Filename and page count from the original PDF embed context
    const filename = decodedContent?.filename || "";
    const pageCount = decodedContent?.page_count ?? undefined;

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

      // On fullscreen click: open the ORIGINAL uploaded PDF's fullscreen
      const handleFullscreen = () => {
        this.openPdfUploadFullscreen(originalEmbedId);
      };

      const component = mount(PdfViewEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          filename,
          pageCount,
          pages,
          originalEmbedId,
          status: status as "processing" | "finished" | "error",
          error,
          taskId,
          isMobile: false,
          // Wire fullscreen — will only be triggered when status === 'finished'.
          // Always pass a handler to satisfy the required prop; no-op during processing states.
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted PdfViewEmbedPreview component:",
        {
          embedId,
          status,
          originalEmbedId,
          pages,
          filename,
        },
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting PdfViewEmbedPreview component:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render pdf/read skill embed using PdfReadEmbedPreview component.
   * On fullscreen click, dispatches 'pdfreadfullscreen' to open PdfReadEmbedFullscreen
   * which shows the full extracted text content.
   */
  private renderPdfReadComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const error = decodedContent?.error || "";

    // embed_id references the original uploaded PDF embed
    const originalEmbedId = decodedContent?.embed_id || "";

    // Pages returned and skipped from the read skill response
    const pagesReturned: number[] = Array.isArray(
      decodedContent?.pages_returned,
    )
      ? decodedContent.pages_returned
      : [];
    const pagesSkipped: number[] = Array.isArray(decodedContent?.pages_skipped)
      ? decodedContent.pages_skipped
      : [];

    const filename = decodedContent?.filename || "";
    const pageCount = decodedContent?.page_count ?? undefined;

    // Extract text content from results[0].content (the actual extracted text)
    const textContent =
      decodedContent?.results?.[0]?.content || decodedContent?.content || "";

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

      // On fullscreen click: dispatch pdfreadfullscreen to open PdfReadEmbedFullscreen
      const handleFullscreen = () => {
        this.openPdfReadFullscreen(
          embedId,
          filename,
          pagesReturned,
          pagesSkipped,
          textContent,
        );
      };

      const component = mount(PdfReadEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          filename,
          pagesReturned,
          pagesSkipped,
          pageCount,
          textContent,
          status: status as "processing" | "finished" | "error",
          error,
          taskId,
          isMobile: false,
          // Always pass handler — UnifiedEmbedPreview only triggers it when finished.
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted PdfReadEmbedPreview component:",
        {
          embedId,
          status,
          originalEmbedId,
          pagesReturned,
          pagesSkipped,
          filename,
          hasTextContent: !!textContent,
        },
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting PdfReadEmbedPreview component:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render pdf/search skill embed using PdfSearchEmbedPreview component.
   * On fullscreen click, dispatches 'pdfsearchfullscreen' to open PdfSearchEmbedFullscreen
   * which shows all search matches with context and highlighted keywords.
   */
  private renderPdfSearchComponent(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
    content: HTMLElement,
  ): void {
    const status =
      decodedContent?.status ||
      embedData?.status ||
      attrs.status ||
      "processing";
    const taskId = decodedContent?.task_id || "";
    const error = decodedContent?.error || "";

    // embed_id references the original uploaded PDF embed
    const originalEmbedId = decodedContent?.embed_id || "";

    // Search-specific fields from the search skill response
    const query = decodedContent?.query || "";
    const totalMatches: number | undefined =
      typeof decodedContent?.total_matches === "number"
        ? decodedContent.total_matches
        : undefined;
    const truncated: boolean = decodedContent?.truncated === true;
    const filename = decodedContent?.filename || "";
    const pageCount = decodedContent?.page_count ?? undefined;

    // Extract matches array from results[0].matches
    const matches: any[] =
      decodedContent?.results?.[0]?.matches || decodedContent?.matches || [];

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

      // On fullscreen click: dispatch pdfsearchfullscreen to open PdfSearchEmbedFullscreen
      const handleFullscreen = () => {
        this.openPdfSearchFullscreen(
          embedId,
          filename,
          query,
          totalMatches,
          truncated,
          matches,
        );
      };

      const component = mount(PdfSearchEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          filename,
          query,
          totalMatches,
          truncated,
          pageCount,
          status: status as "processing" | "finished" | "error",
          error,
          taskId,
          isMobile: false,
          // Always pass handler — UnifiedEmbedPreview only triggers it when finished.
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[AppSkillUseRenderer] Mounted PdfSearchEmbedPreview component:",
        {
          embedId,
          status,
          originalEmbedId,
          query,
          totalMatches,
          matchCount: matches.length,
          filename,
        },
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting PdfSearchEmbedPreview component:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
    }
  }

  /**
   * Render math/calculate skill embed using Svelte component.
   * Displays calculation query and results with math gradient styling.
   */
  private renderMathCalculateComponent(
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

      const component = mount(MathCalculateEmbedPreview, {
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
        "[AppSkillUseRenderer] Mounted MathCalculateEmbedPreview component",
      );
    } catch (error) {
      console.error(
        "[AppSkillUseRenderer] Error mounting MathCalculateEmbedPreview:",
        error,
      );
      this.renderGenericSkill(attrs, embedData, decodedContent, content);
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
          // Generic processing placeholder — no fullscreen available yet.
          // Use a no-op so the required prop is satisfied; UnifiedEmbedPreview
          // will not call this while status === 'processing'.
          onFullscreen: () => {},
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
