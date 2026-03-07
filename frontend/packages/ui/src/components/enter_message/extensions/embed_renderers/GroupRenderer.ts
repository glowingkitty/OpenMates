// Generic group renderer - handles any '*-group' embed types
// Uses the group handler system to render groups dynamically

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { groupHandlerRegistry } from "../../../../message_parsing/groupHandlers";
import {
  resolveEmbed,
  decodeToonContent,
} from "../../../../services/embedResolver";
import {
  downloadCodeFilesAsZip,
  type CodeFileData,
} from "../../../../services/zipExportService";
import { mount, unmount } from "svelte";
import WebsiteEmbedPreview from "../../../embeds/web/WebsiteEmbedPreview.svelte";
import VideoEmbedPreview from "../../../embeds/videos/VideoEmbedPreview.svelte";
import CodeEmbedPreview from "../../../embeds/code/CodeEmbedPreview.svelte";
import WebSearchEmbedPreview from "../../../embeds/web/WebSearchEmbedPreview.svelte";
import NewsSearchEmbedPreview from "../../../embeds/news/NewsSearchEmbedPreview.svelte";
import VideosSearchEmbedPreview from "../../../embeds/videos/VideosSearchEmbedPreview.svelte";
import MapsSearchEmbedPreview from "../../../embeds/maps/MapsSearchEmbedPreview.svelte";
import VideoTranscriptEmbedPreview from "../../../embeds/videos/VideoTranscriptEmbedPreview.svelte";
import WebReadEmbedPreview from "../../../embeds/web/WebReadEmbedPreview.svelte";
import CodeGetDocsEmbedPreview from "../../../embeds/code/CodeGetDocsEmbedPreview.svelte";
import DocsEmbedPreview from "../../../embeds/docs/DocsEmbedPreview.svelte";
import SheetEmbedPreview from "../../../embeds/sheets/SheetEmbedPreview.svelte";
import ReminderEmbedPreview from "../../../embeds/reminder/ReminderEmbedPreview.svelte";
import TravelSearchEmbedPreview from "../../../embeds/travel/TravelSearchEmbedPreview.svelte";
import TravelStaysEmbedPreview from "../../../embeds/travel/TravelStaysEmbedPreview.svelte";
import TravelConnectionEmbedPreview from "../../../embeds/travel/TravelConnectionEmbedPreview.svelte";
import TravelStayEmbedPreview from "../../../embeds/travel/TravelStayEmbedPreview.svelte";
import ImageGenerateEmbedPreview from "../../../embeds/images/ImageGenerateEmbedPreview.svelte";
import ImageViewEmbedPreview from "../../../embeds/images/ImageViewEmbedPreview.svelte";
import ShoppingSearchEmbedPreview from "../../../embeds/shopping/ShoppingSearchEmbedPreview.svelte";
import EventsSearchEmbedPreview from "../../../embeds/events/EventsSearchEmbedPreview.svelte";
import HealthSearchEmbedPreview from "../../../embeds/health/HealthSearchEmbedPreview.svelte";
import PdfReadEmbedPreview from "../../../embeds/pdf/PdfReadEmbedPreview.svelte";
import PdfViewEmbedPreview from "../../../embeds/pdf/PdfViewEmbedPreview.svelte";
import PdfSearchEmbedPreview from "../../../embeds/pdf/PdfSearchEmbedPreview.svelte";
import MailEmbedPreview from "../../../embeds/mail/MailEmbedPreview.svelte";
import EventEmbedPreview from "../../../embeds/events/EventEmbedPreview.svelte";
import MapsLocationEmbedPreview from "../../../embeds/maps/MapsLocationEmbedPreview.svelte";

// Track mounted components for cleanup
const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

/**
 * Type signature for individual embed mounter functions.
 * Each registered mounter mounts a Svelte preview component for a specific embed type.
 * The mounter is responsible for:
 *   1. Extracting typed props from decodedContent / embedData / item attrs
 *   2. Unmounting any existing component on `content`
 *   3. Calling mount() and storing the result in mountedComponents
 *
 * Architecture: See docs/architecture/embed-rendering.md
 * To add a new direct embed type, register a new entry in individualMounters (GroupRenderer constructor).
 */
type IndividualMounter = (
  item: EmbedNodeAttributes,
  embedData: any,
  decodedContent: any,
  content: HTMLElement,
) => Promise<void>;

/**
 * Generic renderer for group embeds (website-group, code-group, doc-group, etc.)
 * Delegates to individual renderers for each item in the group.
 *
 * IMPORTANT — Incremental rendering during streaming:
 * When a group grows (e.g., 2 → 3 items) the renderer preserves existing
 * Svelte components and only appends / prepends new items.  This avoids the
 * visible "flash" caused by destroying and re-mounting every component on
 * each streaming update.
 */
export class GroupRenderer implements EmbedRenderer {
  type = "group"; // This is a generic type - actual matching happens in the registry

  /**
   * Registry of individual-embed mounter functions, keyed by frontend type string.
   *
   * When a non-group embed of a registered type arrives in render(), we look up the mounter
   * here and call it directly. This replaces the previous scattered `if (baseType === ...)` chain.
   *
   * To add a new direct embed type to GroupRenderer:
   *   1. Import the Preview component at the top of this file
   *   2. Add a `this.individualMounters.set(...)` call in the constructor below
   *   3. Write the corresponding private `mount{TypeName}Component()` method
   *   4. Add an HTML fallback method `render{TypeName}Item()` for group HTML rendering
   *   5. Add a case in renderItemContent() switch for the HTML fallback path
   *
   * See docs/claude/embed-types.md for the full registration checklist.
   */
  private readonly individualMounters: Map<string, IndividualMounter>;

  constructor() {
    this.individualMounters = new Map<string, IndividualMounter>([
      [
        "web-website",
        (item, embedData, decodedContent, content) =>
          this.renderWebsiteComponent(item, embedData, decodedContent, content),
      ],
      [
        "videos-video",
        (item, embedData, decodedContent, content) =>
          this.renderVideoComponent(item, embedData, decodedContent, content),
      ],
      [
        "code-code",
        (item, embedData, decodedContent, content) =>
          this.renderCodeComponent(item, embedData, decodedContent, content),
      ],
      [
        "docs-doc",
        (item, embedData, decodedContent, content) =>
          this.renderDocsComponent(item, embedData, decodedContent, content),
      ],
      [
        "sheets-sheet",
        (item, embedData, decodedContent, content) =>
          this.renderSheetComponent(item, embedData, decodedContent, content),
      ],
      [
        "mail-email",
        (item, embedData, decodedContent, content) =>
          this.renderMailComponent(item, embedData, decodedContent, content),
      ],
      [
        "travel-connection",
        (item, embedData, decodedContent, content) =>
          this.renderTravelConnectionComponent(
            item,
            embedData,
            decodedContent,
            content,
          ),
      ],
      [
        "travel-stay",
        (item, embedData, decodedContent, content) =>
          this.renderTravelStayComponent(
            item,
            embedData,
            decodedContent,
            content,
          ),
      ],
      [
        "events-event",
        (item, embedData, decodedContent, content) =>
          this.renderEventComponent(item, embedData, decodedContent, content),
      ],
      [
        "maps-place",
        (item, embedData, decodedContent, content) =>
          this.renderMapsPlaceComponent(
            item,
            embedData,
            decodedContent,
            content,
          ),
      ],
    ]);

    // Startup check: warn if EMBED_RENDERER_MAP contains GroupRenderer types
    // that are not registered in this.individualMounters (catches future omissions).
    // Import is deferred to avoid circular deps at module load time.
    // See docs/claude/embed-types.md for the full registration checklist.
    if (typeof window !== "undefined") {
      import("../../../../data/embedRegistry.generated")
        .then(({ EMBED_RENDERER_MAP }) => {
          const groupTypes = Object.entries(EMBED_RENDERER_MAP)
            .filter(([, renderer]) => renderer === "GroupRenderer")
            .map(([type]) => type)
            .filter(
              (type) => !type.endsWith("-group") && type !== "app-skill-use",
            );

          for (const type of groupTypes) {
            if (!this.individualMounters.has(type)) {
              console.warn(
                `[GroupRenderer] MISSING individual mounter for type "${type}". ` +
                  `Add it to GroupRenderer.individualMounters. See docs/claude/embed-types.md.`,
              );
            }
          }
        })
        .catch(() => {
          // Registry not available (e.g. in test environment) — skip check
        });
    }
  }

  async render(context: EmbedRenderContext): Promise<void> {
    const { attrs, content } = context;

    console.debug("[GroupRenderer] RENDER CALLED with attrs:", attrs);
    console.debug(
      "[GroupRenderer] RENDER CALLED with content element:",
      content,
    );

    // Load embed content from EmbedStore if contentRef is present
    let embedData = null;
    let decodedContent = null;

    if (attrs.contentRef && attrs.contentRef.startsWith("embed:")) {
      try {
        const { resolveEmbed, decodeToonContent } =
          await import("../../../../services/embedResolver");
        const embedId = attrs.contentRef.replace("embed:", "");
        embedData = await resolveEmbed(embedId);

        if (embedData && embedData.content) {
          decodedContent = await decodeToonContent(embedData.content);
          console.debug(
            "[GroupRenderer] Loaded embed content from EmbedStore:",
            embedId,
            decodedContent,
          );
        }
      } catch (error) {
        console.error(
          "[GroupRenderer] Error loading embed from EmbedStore:",
          error,
        );
      }
    }

    // Check if this is a group embed (has groupedItems or type ends with '-group')
    const isGroup =
      (attrs.groupedItems && attrs.groupedItems.length > 0) ||
      attrs.type.endsWith("-group");

    if (!isGroup) {
      // This is an individual embed. Look up the mounter in the registry.
      // Architecture: individual type → mounter map replaces scattered if-chains.
      // To add a new type, register it in the constructor's individualMounters Map.
      const baseType = attrs.type;
      const mounter = this.individualMounters.get(baseType);

      if (mounter) {
        await mounter(attrs, embedData, decodedContent, content);
        return;
      }

      // No registered mounter — fall back to HTML rendering
      const itemHtml = await this.renderIndividualItem(
        attrs,
        baseType,
        embedData,
        decodedContent,
      );
      content.innerHTML = itemHtml;
      return;
    }

    // This is a group embed - continue with existing group rendering logic
    // Extract the base type from the group type (e.g., 'web-website-group' -> 'web-website')
    const baseType = attrs.type.replace("-group", "");
    const groupedItems = attrs.groupedItems || [];
    const groupCount = attrs.groupCount || groupedItems.length;

    console.debug("[GroupRenderer] Rendering group:", {
      groupType: attrs.type,
      baseType,
      itemCount: groupCount,
      groupedItems: groupedItems.map(
        (item) => item.url || item.title || item.id,
      ),
      attrsKeys: Object.keys(attrs),
    });

    // Validate that we have the required data
    if (!groupedItems || groupedItems.length === 0) {
      console.error(
        "[GroupRenderer] No grouped items found for group type:",
        attrs.type,
      );
      console.error("[GroupRenderer] Full attrs object:", attrs);
      console.error("[GroupRenderer] groupedItems value:", groupedItems);
      content.innerHTML =
        '<div class="error">Error: No grouped items found</div>';
      return;
    }

    // Reverse the items so the most recently added appears on the left
    const reversedItems = [...groupedItems].reverse();

    // Determine the group display name
    const groupDisplayName = this.getGroupDisplayName(baseType, groupCount);

    // App skill groups must render each item using the existing embed preview components
    // (e.g. WebSearchEmbedPreview) so sizing and interactions match single-item rendering.
    if (baseType === "app-skill-use") {
      await this.renderAppSkillUseGroup({
        baseType,
        groupDisplayName,
        items: reversedItems,
        content,
      });
      return;
    }

    // Code groups must render each item using CodeEmbedPreview component
    // so sizing and interactions match single-item rendering.
    if (baseType === "code-code") {
      await this.renderCodeGroup({
        baseType,
        groupDisplayName,
        items: reversedItems,
        content,
      });
      return;
    }

    // Document groups must render each item using DocsEmbedPreview component
    // so sizing and interactions match single-item rendering.
    if (baseType === "docs-doc") {
      await this.renderDocsGroup({
        baseType,
        groupDisplayName,
        items: reversedItems,
        content,
      });
      return;
    }

    // Sheet groups must render each item using SheetEmbedPreview component
    // so sizing and interactions match single-item rendering.
    if (baseType === "sheets-sheet") {
      await this.renderSheetGroup({
        baseType,
        groupDisplayName,
        items: reversedItems,
        content,
      });
      return;
    }

    // Mail groups render each item using MailEmbedPreview component
    if (baseType === "mail-email") {
      await this.renderMailGroup({
        baseType,
        groupDisplayName,
        items: reversedItems,
        content,
      });
      return;
    }

    // Generate individual embed HTML for each grouped item (async)
    const groupItemsHtmlPromises = reversedItems.map((item) => {
      return this.renderIndividualItem(item, baseType);
    });
    const groupItemsHtml = (await Promise.all(groupItemsHtmlPromises)).join("");

    const finalHtml = `
      <div class="${baseType}-preview-group">
        <div class="group-header">${groupDisplayName}</div>
        <div class="group-scroll-container">
          ${groupItemsHtml}
        </div>
      </div>
    `;

    console.debug("[GroupRenderer] Final HTML:", finalHtml);
    content.innerHTML = finalHtml;
  }

  private async renderIndividualItem(
    item: EmbedNodeAttributes,
    baseType: string,
    embedData: any = null,
    decodedContent: any = null,
  ): Promise<string> {
    // Load embed content if not provided and contentRef is present
    if (!embedData && item.contentRef && item.contentRef.startsWith("embed:")) {
      try {
        const { resolveEmbed, decodeToonContent } =
          await import("../../../../services/embedResolver");
        const embedId = item.contentRef.replace("embed:", "");
        embedData = await resolveEmbed(embedId);

        if (embedData && embedData.content) {
          decodedContent = await decodeToonContent(embedData.content);
        }
      } catch (error) {
        console.error("[GroupRenderer] Error loading embed for item:", error);
      }
    }

    // Create a wrapper container for each item
    const itemHtml = await this.renderItemContent(
      item,
      baseType,
      embedData,
      decodedContent,
    );

    return itemHtml;
  }

  private async renderItemContent(
    item: EmbedNodeAttributes,
    baseType: string,
    embedData: any = null,
    decodedContent: any = null,
  ): Promise<string> {
    switch (baseType) {
      case "app-skill-use":
        // App skill use embeds should be rendered via Svelte components for correct sizing.
        // This HTML path is kept as a last-resort fallback.
        return this.renderAppSkillUseItem(item, embedData, decodedContent);
      case "web-website":
        return this.renderWebsiteItem(item, embedData, decodedContent);
      case "videos-video":
        return this.renderVideoItem(item, embedData, decodedContent);
      case "code-code":
        return this.renderCodeItem(item, embedData, decodedContent);
      case "docs-doc":
        return this.renderDocItem(item, embedData, decodedContent);
      case "sheets-sheet":
        return this.renderSheetItem(item, embedData, decodedContent);
      case "mail-email":
        return this.renderMailItem(item, embedData, decodedContent);
      case "travel-connection":
        return this.renderTravelConnectionItem(item, embedData, decodedContent);
      case "travel-stay":
        return this.renderTravelStayItem(item, embedData, decodedContent);
      case "events-event":
        return this.renderEventItem(item, embedData, decodedContent);
      case "maps-place":
        return this.renderMapsPlaceItem(item, embedData, decodedContent);
      default:
        console.error(
          `[GroupRenderer] No renderer found for embed type: ${baseType}`,
        );
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
    decodedContent: any = null,
  ): Promise<string> {
    const skillId = decodedContent?.skill_id || "";
    const appId = decodedContent?.app_id || "web";
    const query = decodedContent?.query || "";
    const provider = decodedContent?.provider || "Brave";

    // For web search skills
    if (skillId === "search" || appId === "web") {
      const childEmbedIds = embedData?.embed_ids || [];
      const embedId = item.contentRef?.replace("embed:", "") || "";

      return `
        <div class="embed-unified-container"
             data-embed-type="app-skill-use"
             data-embed-id="${embedId}"
             style="${embedId ? "cursor: pointer;" : ""}">
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
              <div class="search-results-count">${childEmbedIds.length} result${childEmbedIds.length !== 1 ? "s" : ""}</div>
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
    const elements: HTMLElement[] = [
      root,
      ...Array.from(root.querySelectorAll<HTMLElement>("*")),
    ];
    for (const el of elements) {
      const existingComponent = mountedComponents.get(el);
      if (existingComponent) {
        try {
          unmount(existingComponent);
        } catch (e) {
          console.warn(
            "[GroupRenderer] Error unmounting existing component:",
            e,
          );
        }
      }
    }
  }

  /**
   * Recount the visible items in a group's scroll container and update the
   * header text to reflect the real visible count.
   *
   * Error embeds are now rendered inline (with error state) rather than removed,
   * so the count should match groupedItems.length. This method remains as a
   * safety net to reconcile any DOM-level discrepancies.
   */
  private reconcileGroupHeader(
    scrollContainer: HTMLElement,
    header: HTMLElement,
    baseType: string,
  ): void {
    const visibleItems =
      scrollContainer.querySelectorAll(".embed-group-item").length;
    const newDisplayName = this.getGroupDisplayName(baseType, visibleItems);

    // Update header text, preserving child elements (e.g. download icon)
    const textSpan = header.querySelector("span");
    if (textSpan) {
      textSpan.textContent = newDisplayName;
    } else if (
      header.childNodes.length >= 1 &&
      header.childNodes[0].nodeType === Node.TEXT_NODE
    ) {
      header.childNodes[0].textContent = newDisplayName;
    } else {
      header.textContent = newDisplayName;
    }
  }

  /**
   * Try to incrementally update an existing group DOM by only adding new items.
   *
   * During streaming, groups typically grow (new embeds appended) while existing
   * items stay the same.  Instead of tearing down every Svelte component and
   * recreating the entire group, we:
   *   1. Find the existing scroll-container.
   *   2. Build a set of IDs already rendered (from data-embed-item-id).
   *   3. Append only the items that are genuinely new.
   *   4. Update the header text (e.g. "3 requests" → "4 requests").
   *
   * Returns `true` if the incremental path succeeded. Returns `false` if a full
   * re-render is required (e.g. first render, items reordered, items removed).
   */
  async tryIncrementalGroupUpdate(args: {
    baseType: string;
    groupDisplayName: string;
    items: EmbedNodeAttributes[];
    content: HTMLElement;
    mountFn: (item: EmbedNodeAttributes, target: HTMLElement) => Promise<void>;
  }): Promise<boolean> {
    // Note: groupDisplayName is not used here — reconcileGroupHeader computes
    // the display name from the actual visible item count (accounting for hidden error embeds).
    const { baseType, items, content, mountFn } = args;

    // Find the existing group wrapper and scroll container
    const groupWrapper = content.querySelector<HTMLElement>(
      `.${CSS.escape(baseType)}-preview-group`,
    );
    if (!groupWrapper) return false;

    const scrollContainer = groupWrapper.querySelector<HTMLElement>(
      ".group-scroll-container",
    );
    if (!scrollContainer) return false;

    // Build a set of IDs already rendered in the DOM
    const existingItemElements = Array.from(
      scrollContainer.querySelectorAll<HTMLElement>(
        ".embed-group-item[data-embed-item-id]",
      ),
    );
    const existingIds = new Set<string>();
    for (let i = 0; i < existingItemElements.length; i++) {
      const id = existingItemElements[i].getAttribute("data-embed-item-id");
      if (id) existingIds.add(id);
    }

    // If items were removed or reordered we cannot do an incremental update.
    // Quick check: existing IDs must be a prefix-subset of the new items
    // (since items are reversed, new items appear at the beginning).
    // We allow both prepending (new items at start) and appending (new items at end).

    // Collect new item IDs in order
    const newItemIds = items.map(
      (item) => item.id || item.contentRef || "unknown",
    );

    // Find which items are genuinely new (not yet in DOM)
    const itemsToAdd: { item: EmbedNodeAttributes; index: number }[] = [];
    for (let i = 0; i < items.length; i++) {
      const itemId = newItemIds[i];
      if (!existingIds.has(itemId)) {
        itemsToAdd.push({ item: items[i], index: i });
      }
    }

    // If no new items, reconcile the header count (visible items may differ
    // from groupCount due to error embeds being removed from DOM) and return.
    if (itemsToAdd.length === 0) {
      this.reconcileGroupHeader(
        scrollContainer,
        groupWrapper.querySelector<HTMLElement>(".group-header")!,
        baseType,
      );
      return true;
    }

    // If ALL items are new (shouldn't happen for an update) or items were removed,
    // fall back to full re-render.
    if (itemsToAdd.length === items.length) return false;

    // Check for removed items - if any existing ID is not in the new set, fall back
    const existingIdsArray = Array.from(existingIds);
    for (let i = 0; i < existingIdsArray.length; i++) {
      if (!newItemIds.includes(existingIdsArray[i])) {
        console.debug(
          "[GroupRenderer] Item removed, falling back to full re-render",
        );
        return false;
      }
    }

    console.debug(
      `[GroupRenderer] Incremental update: adding ${itemsToAdd.length} new items to group (${existingIds.size} existing)`,
    );

    // Mount only the new items.
    // Since items are reversed (newest first), new items appear at the
    // beginning of the array.  We insert them at the correct position.
    for (const { item, index } of itemsToAdd) {
      const itemWrapper = document.createElement("div");
      itemWrapper.className = "embed-group-item";
      itemWrapper.style.flex = "0 0 auto";
      itemWrapper.setAttribute(
        "data-embed-item-id",
        item.id || item.contentRef || "unknown",
      );

      // Insert at the correct position in the scroll container
      const referenceNode = scrollContainer.children[index] || null;
      scrollContainer.insertBefore(itemWrapper, referenceNode);

      await mountFn(item, itemWrapper);
    }

    // Reconcile header with actual visible count (error embeds may have been removed)
    const header = groupWrapper.querySelector<HTMLElement>(".group-header");
    if (header) {
      this.reconcileGroupHeader(scrollContainer, header, baseType);
    }

    console.debug(
      `[GroupRenderer] ✅ Incremental update complete: ${itemsToAdd.length} new items added`,
    );
    return true;
  }

  private async renderAppSkillUseGroup(args: {
    baseType: string;
    groupDisplayName: string;
    items: EmbedNodeAttributes[];
    content: HTMLElement;
  }): Promise<void> {
    const { baseType, groupDisplayName, items, content } = args;

    // DEBUG: Log incoming items to verify contentRef is set
    console.debug("[GroupRenderer] renderAppSkillUseGroup called:", {
      itemCount: items.length,
      items: items.map((item, idx) => ({
        idx,
        id: item.id,
        type: item.type,
        status: item.status,
        contentRef: item.contentRef,
        app_id: (item as any).app_id,
        skill_id: (item as any).skill_id,
        query: (item as any).query,
      })),
    });

    // Try incremental update first — avoids destroying existing Svelte components
    const updated = await this.tryIncrementalGroupUpdate({
      baseType,
      groupDisplayName,
      items,
      content,
      mountFn: (item, target) => this.mountAppSkillUsePreview(item, target),
    });
    if (updated) return;

    // Full re-render (first render or structural change)

    // Cleanup any mounted components inside this node before re-rendering
    this.unmountMountedComponentsInSubtree(content);

    // Build group DOM (avoid innerHTML for item rendering so we can mount Svelte components)
    content.innerHTML = "";

    const groupWrapper = document.createElement("div");
    groupWrapper.className = `${baseType}-preview-group`;

    const header = document.createElement("div");
    header.className = "group-header";
    header.textContent = groupDisplayName;

    const scrollContainer = document.createElement("div");
    scrollContainer.className = "group-scroll-container";

    groupWrapper.appendChild(header);
    groupWrapper.appendChild(scrollContainer);
    content.appendChild(groupWrapper);

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const itemWrapper = document.createElement("div");
      itemWrapper.className = "embed-group-item";
      // Ensure items keep their intrinsic (fixed) preview size within the horizontal scroll container
      itemWrapper.style.flex = "0 0 auto";
      // Tag each item wrapper with its ID for incremental updates
      itemWrapper.setAttribute(
        "data-embed-item-id",
        item.id || item.contentRef || "unknown",
      );

      scrollContainer.appendChild(itemWrapper);

      console.debug(`[GroupRenderer] Mounting item ${i + 1}/${items.length}:`, {
        id: item.id,
        contentRef: item.contentRef,
      });
      await this.mountAppSkillUsePreview(item, itemWrapper);
    }

    // Safety net: reconcile header count with actual rendered items.
    // Error embeds are now rendered inline, so count should match items.length.
    this.reconcileGroupHeader(scrollContainer, header, baseType);

    console.debug(
      `[GroupRenderer] ✅ Finished mounting all ${items.length} items in group`,
    );
  }

  private async mountAppSkillUsePreview(
    item: EmbedNodeAttributes,
    target: HTMLElement,
  ): Promise<void> {
    // CRITICAL: Extract app_id, skill_id, query from item attrs FIRST
    // These are preserved from the original embed parsing and are available
    // even before embed data arrives from the server via WebSocket.
    // This allows proper rendering during streaming.
    const itemAppId = (item as any).app_id || "";
    const itemSkillId = (item as any).skill_id || "";
    const itemQuery = (item as any).query || "";
    const itemProvider = (item as any).provider || "";

    // Resolve content for this app-skill-use item from EmbedStore
    const embedId = item.contentRef?.startsWith("embed:")
      ? item.contentRef.replace("embed:", "")
      : "";

    let embedData: any = null;
    let decodedContent: any = null;

    if (embedId) {
      try {
        embedData = await resolveEmbed(embedId);
        decodedContent = embedData?.content
          ? await decodeToonContent(embedData.content)
          : null;
      } catch (error) {
        console.error(
          "[GroupRenderer] Error loading app-skill-use embed for group item:",
          error,
        );
      }
    }

    // Determine app_id and skill_id by combining sources in priority order:
    // 1. decodedContent (from TOON content decoding) - most reliable for finished embeds
    // 2. embedData directly (from memory cache for processing embeds)
    // 3. item attrs (from grouped items - preserved from original parsing)
    const appId = decodedContent?.app_id || embedData?.app_id || itemAppId;
    const skillId =
      decodedContent?.skill_id || embedData?.skill_id || itemSkillId;
    const status = (decodedContent?.status ||
      embedData?.status ||
      item.status ||
      "processing") as "processing" | "finished" | "error";
    const taskId = decodedContent?.task_id;
    const results = decodedContent?.results || [];

    // Error embeds are kept in the group and rendered with status: 'error'.
    // The individual preview components handle the error state display (dimmed,
    // with an error indicator). This preserves group stability during streaming
    // and gives users visibility into what failed.
    if (status === "error") {
      console.debug(
        `[GroupRenderer] Rendering error embed in group:`,
        embedId || item.id,
      );
      // Continue to the mounting logic below — the component will render in error state
    }

    // Merge query from multiple sources
    const query = decodedContent?.query || embedData?.query || itemQuery;
    const provider =
      decodedContent?.provider || embedData?.provider || itemProvider;

    console.debug("[GroupRenderer] mountAppSkillUsePreview:", {
      embedId, // CRITICAL: This is the ID used for embedUpdated event matching
      itemContentRef: item.contentRef, // The raw contentRef from item
      appId,
      skillId,
      status,
      query,
      provider,
      itemAppId,
      itemSkillId,
      hasEmbedData: !!embedData,
      hasDecodedContent: !!decodedContent,
    });

    // Cleanup any existing mounted component (in case this target is reused)
    const existingComponent = mountedComponents.get(target);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }
    target.innerHTML = "";

    const handleFullscreen = () => {
      this.openFullscreen(item, embedData, decodedContent);
    };

    try {
      if (appId === "web" && skillId === "search") {
        const component = mount(WebSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || "",
            provider: provider || "Brave Search",
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === "news" && skillId === "search") {
        const component = mount(NewsSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || "",
            provider: provider || "Brave Search",
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === "events" && skillId === "search") {
        const component = mount(EventsSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || "",
            provider: provider || "Meetup",
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === "videos" && skillId === "search") {
        const component = mount(VideosSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || "",
            provider: provider || "Brave Search",
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === "maps" && skillId === "search") {
        const component = mount(MapsSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || "",
            provider: provider || "Google",
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === "travel" && skillId === "search_connections") {
        const component = mount(TravelSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || "",
            provider: provider || "Google",
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === "travel" && skillId === "search_stays") {
        const component = mount(TravelStaysEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || "",
            provider: provider || "Google",
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      if (
        appId === "videos" &&
        (skillId === "get_transcript" || skillId === "get-transcript")
      ) {
        const component = mount(VideoTranscriptEmbedPreview, {
          target,
          props: {
            id: embedId,
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      if (appId === "web" && skillId === "read") {
        const component = mount(WebReadEmbedPreview, {
          target,
          props: {
            id: embedId,
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      // Handle code.get_docs skill (documentation lookup)
      if (appId === "code" && skillId === "get_docs") {
        const library = decodedContent?.library || "";
        const skillTaskId = decodedContent?.skill_task_id || "";
        const component = mount(CodeGetDocsEmbedPreview, {
          target,
          props: {
            id: embedId,
            results,
            library,
            status,
            taskId,
            skillTaskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      // Handle reminder.set-reminder skill
      if (
        appId === "reminder" &&
        (skillId === "set_reminder" || skillId === "set-reminder")
      ) {
        const component = mount(ReminderEmbedPreview, {
          target,
          props: {
            id: embedId,
            reminderId: decodedContent?.reminder_id || "",
            triggerAtFormatted: decodedContent?.trigger_at_formatted || "",
            triggerAt: decodedContent?.trigger_at,
            targetType: decodedContent?.target_type,
            isRepeating: decodedContent?.is_repeating || false,
            prompt: decodedContent?.prompt || "",
            message: decodedContent?.message || "",
            emailNotificationWarning:
              decodedContent?.email_notification_warning || "",
            status: status as "processing" | "finished" | "error",
            error: decodedContent?.error || "",
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      // Handle images.generate / images.generate_draft skill
      if (
        appId === "images" &&
        (skillId === "generate" || skillId === "generate_draft")
      ) {
        const component = mount(ImageGenerateEmbedPreview, {
          target,
          props: {
            id: embedId,
            prompt: decodedContent?.prompt || embedData?.prompt || "",
            model: decodedContent?.model || embedData?.model || "",
            s3BaseUrl:
              decodedContent?.s3_base_url || embedData?.s3_base_url || "",
            files: decodedContent?.files || embedData?.files || undefined,
            aesKey: decodedContent?.aes_key || embedData?.aes_key || "",
            aesNonce: decodedContent?.aes_nonce || embedData?.aes_nonce || "",
            status: status as "processing" | "finished" | "error",
            error: decodedContent?.error || embedData?.error || "",
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      // Handle images.view skill — shows the original uploaded image.
      // The decoded content contains the original upload embed_id; we mount the
      // component first (shows a skeleton) and then resolve the original embed
      // asynchronously to populate the S3 preview data.
      if (appId === "images" && skillId === "view") {
        // embed_id in the skill-use content references the original uploaded image embed
        const originalEmbedId = decodedContent?.embed_id || "";
        const filename = decodedContent?.filename || "";

        const handleImageViewFullscreen = () => {
          if (!originalEmbedId) return;
          // Open the original uploaded image's fullscreen viewer
          resolveEmbed(originalEmbedId)
            .then(async (uploadEmbed) => {
              if (!uploadEmbed) return;
              const uploadContent = uploadEmbed.content
                ? await decodeToonContent(uploadEmbed.content)
                : null;
              const event = new CustomEvent("imagefullscreen", {
                detail: {
                  src: undefined,
                  filename:
                    uploadContent?.filename ||
                    ((uploadEmbed as Record<string, unknown>)
                      .filename as string) ||
                    "",
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
            })
            .catch((err) => {
              console.error(
                "[GroupRenderer] Failed to open image upload fullscreen:",
                err,
              );
            });
        };

        const component = mount(ImageViewEmbedPreview, {
          target,
          props: {
            id: embedId,
            filename,
            status: status as "processing" | "finished" | "error",
            error: decodedContent?.error || "",
            isMobile: false,
            onFullscreen:
              status === "finished" && originalEmbedId
                ? handleImageViewFullscreen
                : undefined,
          },
        });
        mountedComponents.set(target, component);

        // If finished: resolve the original upload embed asynchronously to
        // populate the S3 preview data in the component.
        if (status === "finished" && originalEmbedId) {
          this.resolveAndUpdateImageViewProps(
            target,
            originalEmbedId,
            handleImageViewFullscreen,
          );
        }
        return;
      }

      // Handle health.search_appointments skill
      if (appId === "health" && skillId === "search_appointments") {
        const component = mount(HealthSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || "",
            provider: provider || "Doctolib",
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      // Handle shopping.search_products skill
      if (appId === "shopping" && skillId === "search_products") {
        const component = mount(ShoppingSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            query: query || "",
            provider: provider || "REWE",
            status,
            results,
            taskId,
            isMobile: false,
            onFullscreen: handleFullscreen,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      // Handle pdf.read skill — dispatches pdfreadfullscreen to open PdfReadEmbedFullscreen
      if (appId === "pdf" && skillId === "read") {
        const filename = decodedContent?.filename || "";
        const pagesReturned: number[] = decodedContent?.pages_returned || [];
        const pagesSkipped: number[] = decodedContent?.pages_skipped || [];
        const pageCount: number | undefined =
          decodedContent?.page_count ?? undefined;
        // Extract text content from results[0].content
        const textContent =
          decodedContent?.results?.[0]?.content ||
          decodedContent?.content ||
          "";

        const handlePdfReadFullscreen = () => {
          this.openPdfReadFullscreen(
            embedId,
            filename,
            pagesReturned,
            pagesSkipped,
            textContent,
          );
        };

        const component = mount(PdfReadEmbedPreview, {
          target,
          props: {
            id: embedId,
            filename,
            pagesReturned,
            pagesSkipped,
            pageCount,
            textContent,
            status: status as "processing" | "finished" | "error",
            error: decodedContent?.error || "",
            isMobile: false,
            onFullscreen:
              status === "finished" ? handlePdfReadFullscreen : undefined,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      // Handle pdf.view skill — opens original uploaded PDF fullscreen on click
      if (appId === "pdf" && skillId === "view") {
        const originalEmbedId = decodedContent?.embed_id || "";
        const filename = decodedContent?.filename || "";
        const pages: number[] = decodedContent?.pages || [];
        const pageCount: number | undefined =
          decodedContent?.page_count ?? undefined;

        const handlePdfViewFullscreen = () => {
          if (!originalEmbedId) return;
          this.openPdfUploadFullscreen(originalEmbedId);
        };

        const component = mount(PdfViewEmbedPreview, {
          target,
          props: {
            id: embedId,
            filename,
            pages,
            pageCount,
            originalEmbedId,
            status: status as "processing" | "finished" | "error",
            error: decodedContent?.error || "",
            isMobile: false,
            onFullscreen:
              status === "finished" && originalEmbedId
                ? handlePdfViewFullscreen
                : undefined,
          },
        });
        mountedComponents.set(target, component);
        return;
      }

      // Handle pdf.search skill — dispatches pdfsearchfullscreen to open PdfSearchEmbedFullscreen
      if (appId === "pdf" && skillId === "search") {
        const filename = decodedContent?.filename || "";
        const searchQuery = decodedContent?.query || query || "";
        const totalMatches: number | undefined =
          decodedContent?.total_matches ?? undefined;
        const truncated: boolean = decodedContent?.truncated ?? false;
        // Extract matches array from results[0].matches
        const matches: any[] =
          decodedContent?.results?.[0]?.matches ||
          decodedContent?.matches ||
          [];

        const handlePdfSearchFullscreen = () => {
          this.openPdfSearchFullscreen(
            embedId,
            filename,
            searchQuery,
            totalMatches,
            truncated,
            matches,
          );
        };

        const component = mount(PdfSearchEmbedPreview, {
          target,
          props: {
            id: embedId,
            filename,
            query: searchQuery,
            totalMatches,
            truncated,
            status: status as "processing" | "finished" | "error",
            error: decodedContent?.error || "",
            isMobile: false,
            onFullscreen:
              status === "finished" ? handlePdfSearchFullscreen : undefined,
          },
        });
        mountedComponents.set(target, component);
        return;
      }
    } catch (error) {
      console.error(
        "[GroupRenderer] Error mounting app-skill-use preview component:",
        error,
      );
    }

    // Fallback: render the legacy HTML view (better than a blank group item)
    const fallbackHtml = await this.renderAppSkillUseItem(
      item,
      embedData,
      decodedContent,
    );
    target.innerHTML = fallbackHtml;
  }

  /**
   * Resolve the original image upload embed and re-mount ImageViewEmbedPreview
   * with the S3 data needed to display the image preview.
   *
   * Called asynchronously after the initial mount (which shows a skeleton) so
   * the group item is visible immediately during streaming.
   */
  private async resolveAndUpdateImageViewProps(
    target: HTMLElement,
    originalEmbedId: string,
    handleFullscreen: () => void,
  ): Promise<void> {
    try {
      const uploadEmbed = await resolveEmbed(originalEmbedId);
      if (!uploadEmbed) return;
      const uploadContent = uploadEmbed.content
        ? await decodeToonContent(uploadEmbed.content)
        : null;
      if (!uploadContent) return;

      // Re-mount with S3 data from the resolved upload embed.
      // We unmount + re-mount because Svelte 5 mount() props cannot be updated
      // after the initial mount.
      const existingComponent = mountedComponents.get(target);
      if (!existingComponent) return;

      try {
        unmount(existingComponent);
      } catch {
        // ignore
      }

      target.innerHTML = "";

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
        target,
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

      mountedComponents.set(target, updated);
      console.debug(
        "[GroupRenderer] Updated ImageViewEmbedPreview with S3 data for upload embed:",
        originalEmbedId,
      );
    } catch (err) {
      console.error(
        "[GroupRenderer] Error resolving original image embed for ImageViewEmbedPreview:",
        err,
      );
    }
  }

  /**
   * Open the ORIGINAL uploaded PDF's fullscreen viewer from a GroupRenderer context.
   *
   * Resolves the PDF upload embed by embed_id, decodes its TOON content, then
   * dispatches 'pdffullscreen' on document so ActiveChat mounts PDFEmbedFullscreen.
   *
   * This mirrors the same method in AppSkillUseRenderer — kept separate here so
   * GroupRenderer has no dependency on AppSkillUseRenderer.
   */
  private async openPdfUploadFullscreen(embedId: string): Promise<void> {
    if (!embedId) {
      console.warn("[GroupRenderer] openPdfUploadFullscreen: no embed_id");
      return;
    }
    try {
      const uploadEmbed = await resolveEmbed(embedId);
      if (!uploadEmbed) {
        console.warn(
          "[GroupRenderer] Could not resolve original PDF embed:",
          embedId,
        );
        return;
      }
      const uploadContent = uploadEmbed.content
        ? await decodeToonContent(uploadEmbed.content)
        : null;

      const event = new CustomEvent("pdffullscreen", {
        detail: {
          embedId,
          filename:
            uploadContent?.filename ||
            (uploadEmbed as Record<string, unknown>).filename ||
            "",
          pageCount:
            (uploadContent?.page_count as number | null | undefined) ??
            (uploadEmbed as Record<string, unknown>).page_count ??
            null,
        },
        bubbles: true,
      });
      document.dispatchEvent(event);
      console.debug(
        "[GroupRenderer] Dispatched pdffullscreen for upload embed:",
        embedId,
      );
    } catch (err) {
      console.error(
        "[GroupRenderer] Failed to open PDF upload fullscreen:",
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
    console.debug("[GroupRenderer] Dispatched pdfreadfullscreen:", embedId);
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
    console.debug("[GroupRenderer] Dispatched pdfsearchfullscreen:", embedId);
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

    // Try incremental update first — avoids destroying existing Svelte components
    const updated = await this.tryIncrementalGroupUpdate({
      baseType,
      groupDisplayName,
      items,
      content,
      mountFn: (item, target) => this.mountCodePreview(item, target),
    });
    if (updated) return;

    // Full re-render (first render or structural change)

    // Cleanup any mounted components inside this node before re-rendering
    this.unmountMountedComponentsInSubtree(content);

    // Build group DOM (avoid innerHTML for item rendering so we can mount Svelte components)
    content.innerHTML = "";

    const groupWrapper = document.createElement("div");
    groupWrapper.className = `${baseType}-preview-group`;

    // Create header with text and download icon
    const header = document.createElement("div");
    header.className = "group-header";

    // Text span for the count
    const headerText = document.createElement("span");
    headerText.textContent = groupDisplayName;
    header.appendChild(headerText);

    // Download icon for code groups
    const downloadIcon = document.createElement("span");
    downloadIcon.className = "clickable-icon icon_download group-download-icon";
    downloadIcon.title = "Download all code files";
    downloadIcon.setAttribute("role", "button");
    downloadIcon.setAttribute("tabindex", "0");

    // Add click handler to download all code files
    downloadIcon.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await this.downloadAllCodeFiles(items);
    });

    // Also support keyboard activation
    downloadIcon.addEventListener("keydown", async (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        await this.downloadAllCodeFiles(items);
      }
    });

    header.appendChild(downloadIcon);

    const scrollContainer = document.createElement("div");
    scrollContainer.className = "group-scroll-container";

    groupWrapper.appendChild(header);
    groupWrapper.appendChild(scrollContainer);
    content.appendChild(groupWrapper);

    for (const item of items) {
      const itemWrapper = document.createElement("div");
      itemWrapper.className = "embed-group-item";
      // Ensure items keep their intrinsic (fixed) preview size within the horizontal scroll container
      itemWrapper.style.flex = "0 0 auto";
      // Tag each item wrapper with its ID for incremental updates
      itemWrapper.setAttribute(
        "data-embed-item-id",
        item.id || item.contentRef || "unknown",
      );

      scrollContainer.appendChild(itemWrapper);

      await this.mountCodePreview(item, itemWrapper);
    }
  }

  /**
   * Downloads all code files from a code group as a zip
   * Resolves each embed, extracts code content, and creates a zip download
   */
  private async downloadAllCodeFiles(
    items: EmbedNodeAttributes[],
  ): Promise<void> {
    console.debug(
      "[GroupRenderer] Downloading all code files from group:",
      items.length,
    );

    const codeFiles: CodeFileData[] = [];

    for (const item of items) {
      try {
        // Resolve content for this code item
        const embedId = item.contentRef?.startsWith("embed:")
          ? item.contentRef.replace("embed:", "")
          : "";

        let decodedContent: any = null;

        if (embedId) {
          const embedData = await resolveEmbed(embedId);
          decodedContent = embedData?.content
            ? await decodeToonContent(embedData.content)
            : null;
        }

        // Get code content - for preview embeds use item.code, for real embeds use decodedContent
        let codeContent = "";
        if (item.contentRef?.startsWith("preview:")) {
          codeContent = item.code || "";
        } else {
          codeContent = decodedContent?.code || "";
        }

        if (codeContent) {
          codeFiles.push({
            code: codeContent,
            language: decodedContent?.language || item.language || "text",
            filename: decodedContent?.filename || item.filename,
          });
        }
      } catch (error) {
        console.warn(
          "[GroupRenderer] Error loading code embed for download:",
          error,
        );
      }
    }

    if (codeFiles.length > 0) {
      try {
        await downloadCodeFilesAsZip(codeFiles);
        console.debug(
          "[GroupRenderer] Code files download initiated:",
          codeFiles.length,
          "files",
        );
      } catch (error) {
        console.error("[GroupRenderer] Error downloading code files:", error);
      }
    } else {
      console.warn("[GroupRenderer] No code files found to download");
    }
  }

  /**
   * Render document embed group with horizontal scrolling
   * Similar to renderCodeGroup but for document embeds
   */
  private async renderDocsGroup(args: {
    baseType: string;
    groupDisplayName: string;
    items: EmbedNodeAttributes[];
    content: HTMLElement;
  }): Promise<void> {
    const { baseType, groupDisplayName, items, content } = args;

    // Try incremental update first — avoids destroying existing Svelte components
    const updated = await this.tryIncrementalGroupUpdate({
      baseType,
      groupDisplayName,
      items,
      content,
      mountFn: (item, target) => this.mountDocsPreview(item, target),
    });
    if (updated) return;

    // Full re-render (first render or structural change)

    // Cleanup any mounted components inside this node before re-rendering
    this.unmountMountedComponentsInSubtree(content);

    // Build group DOM
    content.innerHTML = "";

    const groupWrapper = document.createElement("div");
    groupWrapper.className = `${baseType}-preview-group`;

    const header = document.createElement("div");
    header.className = "group-header";
    header.textContent = groupDisplayName;

    const scrollContainer = document.createElement("div");
    scrollContainer.className = "group-scroll-container";

    groupWrapper.appendChild(header);
    groupWrapper.appendChild(scrollContainer);
    content.appendChild(groupWrapper);

    for (const item of items) {
      const itemWrapper = document.createElement("div");
      itemWrapper.className = "embed-group-item";
      // Ensure items keep their intrinsic (fixed) preview size within the horizontal scroll container
      itemWrapper.style.flex = "0 0 auto";
      // Tag each item wrapper with its ID for incremental updates
      itemWrapper.setAttribute(
        "data-embed-item-id",
        item.id || item.contentRef || "unknown",
      );

      scrollContainer.appendChild(itemWrapper);

      await this.mountDocsPreview(item, itemWrapper);
    }
  }

  /**
   * Mount DocsEmbedPreview component for a single document embed item
   */
  private async mountDocsPreview(
    item: EmbedNodeAttributes,
    target: HTMLElement,
  ): Promise<void> {
    // Resolve content for this document item
    const embedId = item.contentRef?.startsWith("embed:")
      ? item.contentRef.replace("embed:", "")
      : "";

    let embedData: any = null;
    let decodedContent: any = null;

    if (embedId) {
      try {
        embedData = await resolveEmbed(embedId);
        decodedContent = embedData?.content
          ? await decodeToonContent(embedData.content)
          : null;
      } catch (error) {
        console.error(
          "[GroupRenderer] Error loading document embed for group item:",
          error,
        );
      }
    }

    // Use decoded content if available, otherwise fall back to item attributes
    const htmlContent = decodedContent?.html || item.code || "";
    const title = decodedContent?.title || item.title;
    const filename = decodedContent?.filename || item.filename;
    const wordCount = decodedContent?.word_count || item.wordCount || 0;

    // Determine status
    const status = (decodedContent?.status ||
      embedData?.status ||
      item.status ||
      "finished") as "processing" | "finished" | "error";
    const taskId = decodedContent?.task_id;

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(target);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }
    target.innerHTML = "";

    const handleFullscreen = () => {
      this.openFullscreen(item, embedData, decodedContent);
    };

    try {
      const component = mount(DocsEmbedPreview, {
        target,
        props: {
          id: embedId || item.id || "",
          title,
          filename,
          wordCount,
          status,
          taskId,
          isMobile: false,
          onFullscreen: handleFullscreen,
          htmlContent,
        },
      });
      mountedComponents.set(target, component);

      console.debug(
        "[GroupRenderer] Mounted DocsEmbedPreview component in group:",
        {
          embedId,
          title,
          wordCount,
          status,
        },
      );
    } catch (error) {
      console.error(
        "[GroupRenderer] Error mounting DocsEmbedPreview component:",
        error,
      );
      // Fallback: render the legacy HTML view
      const fallbackHtml = await this.renderDocItem(
        item,
        embedData,
        decodedContent,
      );
      target.innerHTML = fallbackHtml;
    }
  }

  /**
   * Mount CodeEmbedPreview component for a single code embed item
   */
  private async mountCodePreview(
    item: EmbedNodeAttributes,
    target: HTMLElement,
  ): Promise<void> {
    // Resolve content for this code item
    const embedId = item.contentRef?.startsWith("embed:")
      ? item.contentRef.replace("embed:", "")
      : "";
    const previewId = item.contentRef?.startsWith("preview:")
      ? item.contentRef.replace("preview:code:", "")
      : "";

    let embedData: any = null;
    let decodedContent: any = null;

    if (embedId) {
      try {
        embedData = await resolveEmbed(embedId);
        decodedContent = embedData?.content
          ? await decodeToonContent(embedData.content)
          : null;
      } catch (error) {
        console.error(
          "[GroupRenderer] Error loading code embed for group item:",
          error,
        );
      }
    }

    // Use decoded content if available, otherwise fall back to item attributes
    const language = decodedContent?.language || item.language || "text";
    const filename = decodedContent?.filename || item.filename;
    const lineCount = decodedContent?.lineCount || item.lineCount || 0;

    // For preview embeds (contentRef starts with 'preview:'), get code from item attributes
    // For real embeds, get code from decodedContent
    let codeContent = "";
    if (item.contentRef?.startsWith("preview:")) {
      // Preview embed - code is stored temporarily in item attributes
      codeContent = item.code || "";
      console.debug(
        "[GroupRenderer] mountCodePreview: preview embed code content",
        {
          hasCode: !!item.code,
          codeLength: item.code?.length || 0,
          codePreview: item.code?.substring(0, 100) || "NO CODE",
          itemKeys: Object.keys(item),
          contentRef: item.contentRef,
        },
      );
    } else {
      // Real embed - code comes from decodedContent (loaded from EmbedStore)
      codeContent = decodedContent?.code || "";
    }

    // Determine status
    const status = (decodedContent?.status ||
      embedData?.status ||
      item.status ||
      "finished") as "processing" | "finished" | "error";
    const taskId = decodedContent?.task_id;

    // Cleanup any existing mounted component (in case this target is reused)
    const existingComponent = mountedComponents.get(target);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }
    target.innerHTML = "";

    const handleFullscreen = () => {
      this.openFullscreen(item, embedData, decodedContent);
    };

    try {
      const component = mount(CodeEmbedPreview, {
        target,
        props: {
          id: embedId || previewId || item.id || "",
          language,
          filename,
          lineCount,
          status,
          taskId,
          isMobile: false,
          onFullscreen: handleFullscreen,
          codeContent, // Pass full code content - component handles preview extraction
        },
      });
      mountedComponents.set(target, component);

      console.debug(
        "[GroupRenderer] Mounted CodeEmbedPreview component in group:",
        {
          embedId: embedId || previewId,
          language,
          filename,
          lineCount,
          status,
        },
      );
    } catch (error) {
      console.error(
        "[GroupRenderer] Error mounting CodeEmbedPreview component:",
        error,
      );
      // Fallback: render the legacy HTML view (better than a blank group item)
      const fallbackHtml = await this.renderCodeItem(
        item,
        embedData,
        decodedContent,
      );
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
    content: HTMLElement,
  ): Promise<void> {
    // Use decoded content if available, otherwise fall back to item attributes
    const websiteUrl = decodedContent?.url || item.url;
    const websiteTitle = decodedContent?.title || item.title;
    const websiteDescription = decodedContent?.description || item.description;
    const favicon =
      decodedContent?.meta_url_favicon ||
      decodedContent?.favicon ||
      item.favicon;
    const image =
      decodedContent?.thumbnail_original || decodedContent?.image || item.image;

    // Determine status.
    // When embed data has been successfully decoded (e.g. metadata fetched by
    // urlMetadataService), override the node's "processing" status to "finished"
    // so the preview renders the full card (image, description) instead of just
    // the hostname. In compose mode, embedParsing.ts sets status="processing"
    // for all write-mode embeds, but by the time GroupRenderer runs, the data
    // is already available in EmbedStore.
    const hasResolvedData =
      decodedContent && (decodedContent.url || decodedContent.title);
    const status = hasResolvedData
      ? "finished"
      : item.status || (websiteUrl ? "finished" : "processing");

    // Get embed ID
    const embedId = item.contentRef?.replace("embed:", "") || "";

    // Clear the content element
    content.innerHTML = "";

    // Mount the Svelte component
    try {
      // Create a handler for fullscreen that receives metadata from preview
      // The preview passes its effective values (props or fetched from preview server)
      // so fullscreen can display the same data without re-fetching
      const handleFullscreen = (metadata?: {
        title?: string;
        description?: string;
        favicon?: string;
        image?: string;
      }) => {
        // Merge preview's fetched metadata with decoded content
        // Preview metadata takes priority since it may have been fetched fresh
        const enrichedContent = {
          ...decodedContent,
          // Override with preview's fetched metadata if provided
          title: metadata?.title || decodedContent?.title,
          description: metadata?.description || decodedContent?.description,
          favicon:
            metadata?.favicon ||
            decodedContent?.meta_url_favicon ||
            decodedContent?.favicon,
          image:
            metadata?.image ||
            decodedContent?.thumbnail_original ||
            decodedContent?.image,
        };

        console.debug(
          "[GroupRenderer] Opening website fullscreen with metadata from preview:",
          {
            hasPreviewTitle: !!metadata?.title,
            hasPreviewDescription: !!metadata?.description,
            hasPreviewImage: !!metadata?.image,
          },
        );

        this.openFullscreen(item, embedData, enrichedContent);
      };

      const component = mount(WebsiteEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          url: websiteUrl || "",
          title: websiteTitle,
          description: websiteDescription,
          favicon: favicon,
          image: image,
          status: status as "processing" | "finished" | "error",
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen,
        },
      });

      // Store reference for cleanup
      mountedComponents.set(content, component);

      console.debug("[GroupRenderer] Mounted WebsiteEmbedPreview component:", {
        embedId,
        url: websiteUrl?.substring(0, 50) + "...",
        status,
        hasTitle: !!websiteTitle,
        hasImage: !!image,
      });
    } catch (error) {
      console.error(
        "[GroupRenderer] Error mounting WebsiteEmbedPreview component:",
        error,
      );
      // Fallback to HTML rendering
      const fallbackHtml = await this.renderWebsiteItemHTML(
        item,
        embedData,
        decodedContent,
      );
      content.innerHTML = fallbackHtml;
    }
  }

  /**
   * Fallback HTML rendering for websites (used when Svelte mount fails)
   */
  private async renderWebsiteItemHTML(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
  ): Promise<string> {
    const isProcessing = item.status === "processing";

    // Use decoded content if available, otherwise fall back to item attributes
    const websiteUrl = decodedContent?.url || item.url;
    const websiteTitle = decodedContent?.title || item.title;
    const websiteDescription = decodedContent?.description || item.description;
    const favicon =
      decodedContent?.meta_url_favicon ||
      decodedContent?.favicon ||
      item.favicon;
    const image =
      decodedContent?.thumbnail_original || decodedContent?.image || item.image;

    const hasMetadata = websiteTitle || websiteDescription;

    if (hasMetadata && websiteUrl) {
      // SUCCESS STATE: Full design with metadata
      const displayTitle = websiteTitle || new URL(websiteUrl).hostname;
      const displayDescription = websiteDescription || "";
      const faviconUrl =
        favicon ||
        `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(websiteUrl)}`;
      const imageUrl =
        image ||
        `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(websiteUrl)}`;

      // Add click handler for fullscreen
      const embedId = item.contentRef?.replace("embed:", "") || "";

      // Create a wrapper that will have the click handler attached
      const containerId = `embed-${embedId || Math.random().toString(36).substr(2, 9)}`;

      return `
        <div class="embed-unified-container" 
             data-embed-type="web-website" 
             data-embed-id="${embedId}"
             id="${containerId}"
             style="${embedId ? "cursor: pointer;" : ""}">
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
      const domain = urlObj ? urlObj.hostname : "Invalid URL";
      const path = urlObj ? urlObj.pathname + urlObj.search + urlObj.hash : "";
      const displayPath = path === "/" ? "" : path;

      return `
        <div class="embed-app-icon web">
          <span class="icon icon_web"></span>
        </div>
        <div class="embed-text-content">
          <div class="embed-text-line">${domain}</div>
          ${displayPath ? `<div class="embed-text-line">${displayPath}</div>` : ""}
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
    decodedContent: any = null,
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
    content: HTMLElement,
  ): Promise<void> {
    // Use decoded content if available, otherwise fall back to item attributes
    const videoUrl = decodedContent?.url || item.url;
    const videoTitle = decodedContent?.title || item.title;

    // Determine status
    const status = item.status || (videoUrl ? "finished" : "processing");

    // Get embed ID
    const embedId = item.contentRef?.replace("embed:", "") || "";

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }

    // Clear the content element
    content.innerHTML = "";

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
          duration_seconds:
            metadata?.duration?.totalSeconds ||
            decodedContent?.duration_seconds,
          duration_formatted:
            metadata?.duration?.formatted || decodedContent?.duration_formatted,
          view_count: metadata?.viewCount || decodedContent?.view_count,
          like_count: metadata?.likeCount || decodedContent?.like_count,
          published_at: metadata?.publishedAt || decodedContent?.published_at,
        };

        console.debug(
          "[GroupRenderer] Opening video fullscreen with metadata from preview:",
          {
            hasPreviewTitle: !!metadata?.title,
            hasPreviewChannel: !!metadata?.channelName,
            hasPreviewThumbnail: !!metadata?.thumbnailUrl,
            hasPreviewDuration: !!metadata?.duration,
          },
        );

        this.openFullscreen(item, embedData, enrichedContent);
      };

      const component = mount(VideoEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          url: videoUrl || "",
          title: videoTitle,
          status: status as "processing" | "finished" | "error",
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
          videoId: decodedContent?.video_id,
        },
      });

      // Store reference for cleanup
      mountedComponents.set(content, component);

      console.debug("[GroupRenderer] Mounted VideoEmbedPreview component:", {
        embedId,
        url: videoUrl?.substring(0, 50) + "...",
        status,
        hasTitle: !!videoTitle,
        hasChannelThumbnail: !!decodedContent?.channel_thumbnail,
        hasDuration: !!decodedContent?.duration_formatted,
      });
    } catch (error) {
      console.error(
        "[GroupRenderer] Error mounting VideoEmbedPreview component:",
        error,
      );
      // Fallback to HTML rendering
      const fallbackHtml = await this.renderVideoItemHTML(
        item,
        embedData,
        decodedContent,
      );
      content.innerHTML = fallbackHtml;
    }
  }

  /**
   * Fallback HTML rendering for videos (used when Svelte mount fails)
   */
  private async renderVideoItemHTML(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
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
    content: HTMLElement,
  ): Promise<void> {
    // Use decoded content if available, otherwise fall back to item attributes
    const language = decodedContent?.language || item.language || "text";
    const filename = decodedContent?.filename || item.filename;
    const lineCount = decodedContent?.lineCount || item.lineCount || 0;

    // For preview embeds (contentRef starts with 'preview:'), get code from item attributes
    // For real embeds, get code from decodedContent
    let codeContent = "";
    if (item.contentRef?.startsWith("preview:")) {
      // Preview embed - code is stored temporarily in item attributes
      codeContent = item.code || "";
      console.debug(
        "[GroupRenderer] Rendering preview code embed with inline code content",
      );
    } else {
      // Real embed - code comes from decodedContent (loaded from EmbedStore)
      codeContent = decodedContent?.code || "";
    }

    // Determine status
    const status = item.status || "finished";

    // Get embed ID (remove prefixes for preview embeds)
    const embedId =
      item.contentRef?.replace("embed:", "")?.replace("preview:code:", "") ||
      item.id ||
      "";

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }

    // Clear the content element
    content.innerHTML = "";

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
          status: status as "processing" | "finished" | "error",
          isMobile: false, // Default to desktop in message view
          onFullscreen: handleFullscreen,
          codeContent, // Pass full code content - component handles preview extraction
        },
      });

      // Store reference for cleanup
      mountedComponents.set(content, component);

      console.debug("[GroupRenderer] Mounted CodeEmbedPreview component:", {
        embedId,
        language,
        filename,
        lineCount,
        status,
      });
    } catch (error) {
      console.error(
        "[GroupRenderer] Error mounting CodeEmbedPreview component:",
        error,
      );
      // Fallback to HTML rendering
      const fallbackHtml = await this.renderCodeItem(
        item,
        embedData,
        decodedContent,
      );
      content.innerHTML = fallbackHtml;
    }
  }

  /**
   * Render document embed using Svelte component
   * Uses DocsEmbedPreview for consistent sizing (300x200px desktop, 150x290px mobile)
   */
  private async renderDocsComponent(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
    content: HTMLElement,
  ): Promise<void> {
    // Use decoded content if available, otherwise fall back to item attributes
    const htmlContent = decodedContent?.html || item.code || "";
    const title = decodedContent?.title || item.title;
    const filename = decodedContent?.filename || item.filename;
    const wordCount = decodedContent?.word_count || item.wordCount || 0;

    // Determine status
    const status = item.status || (htmlContent ? "finished" : "processing");

    // Get embed ID
    const embedId = item.contentRef?.replace("embed:", "") || item.id || "";

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }

    // Clear the content element
    content.innerHTML = "";

    // Mount the Svelte component
    try {
      const handleFullscreen = () => {
        this.openFullscreen(item, embedData, decodedContent);
      };

      const component = mount(DocsEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          title,
          filename,
          wordCount,
          status: status as "processing" | "finished" | "error",
          isMobile: false,
          onFullscreen: handleFullscreen,
          htmlContent,
        },
      });

      // Store reference for cleanup
      mountedComponents.set(content, component);

      console.debug("[GroupRenderer] Mounted DocsEmbedPreview component:", {
        embedId,
        title,
        wordCount,
        status,
      });
    } catch (error) {
      console.error(
        "[GroupRenderer] Error mounting DocsEmbedPreview component:",
        error,
      );
      // Fallback to HTML rendering
      const fallbackHtml = await this.renderDocItem(
        item,
        embedData,
        decodedContent,
      );
      content.innerHTML = fallbackHtml;
    }
  }

  /**
   * Render sheet embed using Svelte component
   * Uses SheetEmbedPreview for consistent sizing (300x200px desktop, 150x290px mobile)
   */
  private async renderSheetComponent(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
    content: HTMLElement,
  ): Promise<void> {
    // Use decoded content if available, otherwise fall back to item attributes.
    // The TOON content from the backend uses field names: title, table, row_count, col_count.
    const title = decodedContent?.title || item.title;
    const rowCount =
      decodedContent?.row_count || decodedContent?.rows || item.rows || 0;
    const colCount =
      decodedContent?.col_count || decodedContent?.cols || item.cols || 0;

    // Get table content (raw markdown) from decoded TOON content or item attributes.
    // Real embeds (embed: ref) → table content from EmbedStore via decodedContent.
    // Legacy ephemeral refs (stream:/preview:) → fallback to item.code attribute.
    const tableContent =
      decodedContent?.table || decodedContent?.code || item.code || "";

    // Determine status
    const status = item.status || (tableContent ? "finished" : "processing");

    // Get embed ID
    const embedId =
      item.contentRef
        ?.replace("embed:", "")
        ?.replace("preview:sheets-sheet:", "")
        ?.replace("stream:", "") ||
      item.id ||
      "";

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }

    // Clear the content element
    content.innerHTML = "";

    // Mount the Svelte component
    try {
      const handleFullscreen = () => {
        // For preview/stream embeds, construct synthetic decodedContent
        // so fullscreen has the table data without hitting EmbedStore
        const fullscreenContent =
          decodedContent ||
          (tableContent
            ? { code: tableContent, title, rows: rowCount, cols: colCount }
            : null);
        this.openFullscreen(item, embedData, fullscreenContent);
      };

      const component = mount(SheetEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          title,
          rowCount,
          colCount,
          status: status as "processing" | "finished" | "error",
          isMobile: false,
          onFullscreen: handleFullscreen,
          tableContent,
        },
      });

      // Store reference for cleanup
      mountedComponents.set(content, component);

      console.debug("[GroupRenderer] Mounted SheetEmbedPreview component:", {
        embedId,
        title,
        rowCount,
        colCount,
        status,
      });
    } catch (error) {
      console.error(
        "[GroupRenderer] Error mounting SheetEmbedPreview component:",
        error,
      );
      // Fallback to HTML rendering
      const fallbackHtml = await this.renderSheetItem(
        item,
        embedData,
        decodedContent,
      );
      content.innerHTML = fallbackHtml;
    }
  }

  /**
   * Render sheet embed group with horizontal scrolling
   * Similar to renderDocsGroup but for sheet embeds
   */
  private async renderSheetGroup(args: {
    baseType: string;
    groupDisplayName: string;
    items: EmbedNodeAttributes[];
    content: HTMLElement;
  }): Promise<void> {
    const { baseType, groupDisplayName, items, content } = args;

    // Try incremental update first — avoids destroying existing Svelte components
    const updated = await this.tryIncrementalGroupUpdate({
      baseType,
      groupDisplayName,
      items,
      content,
      mountFn: (item, target) => this.mountSheetPreview(item, target),
    });
    if (updated) return;

    // Full re-render (first render or structural change)

    // Cleanup any mounted components inside this node before re-rendering
    this.unmountMountedComponentsInSubtree(content);

    // Build group DOM
    content.innerHTML = "";

    const groupWrapper = document.createElement("div");
    groupWrapper.className = `${baseType}-preview-group`;

    const header = document.createElement("div");
    header.className = "group-header";
    header.textContent = groupDisplayName;

    const scrollContainer = document.createElement("div");
    scrollContainer.className = "group-scroll-container";

    groupWrapper.appendChild(header);
    groupWrapper.appendChild(scrollContainer);
    content.appendChild(groupWrapper);

    for (const item of items) {
      const itemWrapper = document.createElement("div");
      itemWrapper.className = "embed-group-item";
      itemWrapper.style.flex = "0 0 auto";
      itemWrapper.setAttribute(
        "data-embed-item-id",
        item.id || item.contentRef || "unknown",
      );

      scrollContainer.appendChild(itemWrapper);

      await this.mountSheetPreview(item, itemWrapper);
    }
  }

  /**
   * Mount SheetEmbedPreview component for a single sheet embed item
   */
  private async mountSheetPreview(
    item: EmbedNodeAttributes,
    target: HTMLElement,
  ): Promise<void> {
    // Resolve content for this sheet item
    const embedId = item.contentRef?.startsWith("embed:")
      ? item.contentRef.replace("embed:", "")
      : "";
    const previewId = item.contentRef?.startsWith("preview:")
      ? item.contentRef.replace("preview:sheets-sheet:", "")
      : "";

    let embedData: any = null;
    let decodedContent: any = null;

    if (embedId) {
      try {
        embedData = await resolveEmbed(embedId);
        decodedContent = embedData?.content
          ? await decodeToonContent(embedData.content)
          : null;
      } catch (error) {
        console.error(
          "[GroupRenderer] Error loading sheet embed for group item:",
          error,
        );
      }
    }

    // Use decoded content if available, otherwise fall back to item attributes
    const title = decodedContent?.title || item.title;
    const rowCount = decodedContent?.rows || item.rows || 0;
    const colCount = decodedContent?.cols || item.cols || 0;

    // For preview/stream embeds, get content from item attributes (code attr).
    // stream: refs are used after reload — content lives in item.code.
    let tableContent = "";
    if (
      item.contentRef?.startsWith("preview:") ||
      item.contentRef?.startsWith("stream:")
    ) {
      tableContent = item.code || "";
    } else {
      tableContent =
        decodedContent?.code || decodedContent?.table || item.code || "";
    }

    // Determine status
    const status = (decodedContent?.status ||
      embedData?.status ||
      item.status ||
      "finished") as "processing" | "finished" | "error";
    const taskId = decodedContent?.task_id;

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(target);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }
    target.innerHTML = "";

    const handleFullscreen = () => {
      // For preview/stream embeds, construct synthetic decodedContent
      // so fullscreen has the table data without hitting EmbedStore
      const fullscreenContent =
        decodedContent ||
        (tableContent
          ? { code: tableContent, title, rows: rowCount, cols: colCount }
          : null);
      this.openFullscreen(item, embedData, fullscreenContent);
    };

    try {
      const component = mount(SheetEmbedPreview, {
        target,
        props: {
          id: embedId || previewId || item.id || "",
          title,
          rowCount,
          colCount,
          status,
          taskId,
          isMobile: false,
          onFullscreen: handleFullscreen,
          tableContent,
        },
      });
      mountedComponents.set(target, component);

      console.debug(
        "[GroupRenderer] Mounted SheetEmbedPreview component in group:",
        {
          embedId: embedId || previewId,
          title,
          rowCount,
          colCount,
          status,
        },
      );
    } catch (error) {
      console.error(
        "[GroupRenderer] Error mounting SheetEmbedPreview in group:",
        error,
      );
      // Fallback to HTML rendering
      const fallbackHtml = await this.renderSheetItem(
        item,
        embedData,
        decodedContent,
      );
      target.innerHTML = fallbackHtml;
    }
  }

  private async renderVideoItem(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
  ): Promise<string> {
    const isProcessing = item.status === "processing";
    const videoUrl = item.url;

    // Extract video ID for YouTube URLs
    let videoId = "";
    let videoTitle = item.title || "";
    let thumbnailUrl = "";

    if (videoUrl) {
      // YouTube URL patterns
      const youtubeMatch = videoUrl.match(
        /(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)/,
      );
      if (youtubeMatch) {
        videoId = youtubeMatch[1];
        thumbnailUrl = `https://img.youtube.com/vi/${videoId}/maxresdefault.jpg`;
        if (!videoTitle) {
          videoTitle = "YouTube Video";
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
      const domain = urlObj ? urlObj.hostname : "Invalid URL";
      const path = urlObj ? urlObj.pathname + urlObj.search + urlObj.hash : "";
      const displayPath = path === "/" ? "" : path;

      return `
        <div class="embed-app-icon videos">
          <span class="icon icon_video"></span>
        </div>
        <div class="embed-text-content">
          <div class="embed-text-line">${domain}</div>
          ${displayPath ? `<div class="embed-text-line">${displayPath}</div>` : ""}
        </div>
      `;
    }
  }

  private async renderCodeItem(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
  ): Promise<string> {
    const language = item.language || "text";
    const filename = item.filename || `code.${language}`;
    const isProcessing = item.status === "processing";

    return `
      <div class="embed-app-icon code">
        <span class="icon icon_code"></span>
      </div>
      <div class="embed-text-content">
        ${isProcessing ? '<div class="embed-modify-icon"><span class="icon icon_edit"></span></div>' : ""}
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
    decodedContent: any = null,
  ): Promise<string> {
    const title = item.title || "Document";
    const isProcessing = item.status === "processing";

    return `
      <div class="embed-app-icon docs">
        <span class="icon icon_document"></span>
      </div>
      <div class="embed-text-content">
        ${isProcessing ? '<div class="embed-modify-icon"><span class="icon icon_edit"></span></div>' : ""}
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
    decodedContent: any = null,
  ): Promise<string> {
    const title = item.title || "Spreadsheet";
    const rows = item.rows || 0;
    const cols = item.cols || 0;
    const isProcessing = item.status === "processing";

    return `
      <div class="embed-app-icon sheets">
        <span class="icon icon_table"></span>
      </div>
      <div class="embed-text-content">
        ${isProcessing ? '<div class="embed-modify-icon"><span class="icon icon_edit"></span></div>' : ""}
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

  // =========================================================================
  // Mail embed rendering — individual + group + mount
  // =========================================================================

  /**
   * Render a single mail embed using MailEmbedPreview Svelte component.
   */
  private async renderMailComponent(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
    content: HTMLElement,
  ): Promise<void> {
    const receiver = decodedContent?.receiver || "";
    const subject = decodedContent?.subject || "";
    const mailContent = decodedContent?.content || "";
    const footer = decodedContent?.footer || "";
    const status = (decodedContent?.status ||
      embedData?.status ||
      item.status ||
      "processing") as "processing" | "finished" | "error" | "cancelled";
    const taskId = decodedContent?.task_id;

    const embedId = item.contentRef?.replace("embed:", "") || item.id || "";

    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }
    content.innerHTML = "";

    try {
      const handleFullscreen = () => {
        this.openFullscreen(item, embedData, decodedContent);
      };

      const component = mount(MailEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          receiver,
          subject,
          content: mailContent,
          footer,
          status,
          taskId,
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug("[GroupRenderer] Mounted MailEmbedPreview component:", {
        embedId,
        subject,
        status,
      });
    } catch (error) {
      console.error(
        "[GroupRenderer] Error mounting MailEmbedPreview component:",
        error,
      );
      const fallbackHtml = await this.renderMailItem(
        item,
        embedData,
        decodedContent,
      );
      content.innerHTML = fallbackHtml;
    }
  }

  /**
   * Render a group of mail embeds using MailEmbedPreview for each item.
   */
  private async renderMailGroup(args: {
    baseType: string;
    groupDisplayName: string;
    items: EmbedNodeAttributes[];
    content: HTMLElement;
  }): Promise<void> {
    const { baseType, groupDisplayName, items, content } = args;

    const updated = await this.tryIncrementalGroupUpdate({
      baseType,
      groupDisplayName,
      items,
      content,
      mountFn: (item, target) => this.mountMailPreview(item, target),
    });
    if (updated) return;

    this.unmountMountedComponentsInSubtree(content);
    content.innerHTML = "";

    const groupWrapper = document.createElement("div");
    groupWrapper.className = `${baseType}-preview-group`;

    const header = document.createElement("div");
    header.className = "group-header";
    header.textContent = groupDisplayName;

    const scrollContainer = document.createElement("div");
    scrollContainer.className = "group-scroll-container";

    groupWrapper.appendChild(header);
    groupWrapper.appendChild(scrollContainer);
    content.appendChild(groupWrapper);

    for (const item of items) {
      const itemWrapper = document.createElement("div");
      itemWrapper.className = "embed-group-item";
      itemWrapper.style.flex = "0 0 auto";
      itemWrapper.setAttribute(
        "data-embed-item-id",
        item.id || item.contentRef || "unknown",
      );
      scrollContainer.appendChild(itemWrapper);
      await this.mountMailPreview(item, itemWrapper);
    }
  }

  /**
   * Mount MailEmbedPreview component for a single mail embed item (in groups).
   */
  private async mountMailPreview(
    item: EmbedNodeAttributes,
    target: HTMLElement,
  ): Promise<void> {
    const embedId = item.contentRef?.startsWith("embed:")
      ? item.contentRef.replace("embed:", "")
      : "";

    let embedData: any = null;
    let decodedContent: any = null;

    if (embedId) {
      try {
        embedData = await resolveEmbed(embedId);
        decodedContent = embedData?.content
          ? await decodeToonContent(embedData.content)
          : null;
      } catch (error) {
        console.error(
          "[GroupRenderer] Error loading mail embed for group item:",
          error,
        );
      }
    }

    const receiver = decodedContent?.receiver || "";
    const subject = decodedContent?.subject || "";
    const mailContent = decodedContent?.content || "";
    const footer = decodedContent?.footer || "";
    const status = (decodedContent?.status ||
      embedData?.status ||
      item.status ||
      "finished") as "processing" | "finished" | "error" | "cancelled";
    const taskId = decodedContent?.task_id;

    const existingComponent = mountedComponents.get(target);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }
    target.innerHTML = "";

    const handleFullscreen = () => {
      this.openFullscreen(item, embedData, decodedContent);
    };

    try {
      const component = mount(MailEmbedPreview, {
        target,
        props: {
          id: embedId || item.id || "",
          receiver,
          subject,
          content: mailContent,
          footer,
          status,
          taskId,
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });
      mountedComponents.set(target, component);

      console.debug(
        "[GroupRenderer] Mounted MailEmbedPreview component in group:",
        {
          embedId,
          subject,
          status,
        },
      );
    } catch (error) {
      console.error(
        "[GroupRenderer] Error mounting MailEmbedPreview in group:",
        error,
      );
      target.innerHTML = `<div style="padding:8px;font-size:12px;color:var(--color-grey-50)">Mail embed unavailable</div>`;
    }
  }

  /**
   * Render a mail item as HTML fallback (for renderItemContent switch).
   */
  private async renderMailItem(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
  ): Promise<string> {
    const subject = decodedContent?.subject || item.title || "Email Draft";
    const receiver = decodedContent?.receiver || "";
    const isProcessing = item.status === "processing";

    return `
      <div class="embed-app-icon mail">
        <span class="icon icon_mail"></span>
      </div>
      <div class="embed-text-content">
        ${isProcessing ? '<div class="embed-modify-icon"><span class="icon icon_edit"></span></div>' : ""}
        <div class="embed-text-line">${subject}</div>
        ${receiver ? `<div class="embed-text-subline">${receiver}</div>` : ""}
      </div>
    `;
  }

  // =========================================================================
  // Travel connection embed rendering — individual Svelte component + HTML fallback
  // =========================================================================

  /**
   * Render a single travel connection embed using TravelConnectionEmbedPreview.
   * Called from the render() individual embed path when baseType === 'travel-connection'.
   */
  private async renderTravelConnectionComponent(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
    content: HTMLElement,
  ): Promise<void> {
    const price = decodedContent?.price?.toString() || "";
    const currency = decodedContent?.currency || "EUR";
    const transportMethod =
      decodedContent?.transport_method ||
      decodedContent?.transportMethod ||
      "airplane";
    const tripType =
      decodedContent?.trip_type || decodedContent?.tripType || "one_way";
    const origin = decodedContent?.origin || "";
    const destination = decodedContent?.destination || "";
    const departure = decodedContent?.departure || "";
    const arrival = decodedContent?.arrival || "";
    const duration = decodedContent?.duration || "";
    const stops = decodedContent?.stops ?? 0;
    const carriers = decodedContent?.carriers || [];
    const carrierCodes =
      decodedContent?.carrier_codes || decodedContent?.carrierCodes || [];
    const bookableSeats =
      decodedContent?.bookable_seats ?? decodedContent?.bookableSeats;
    const isCheapest =
      decodedContent?.is_cheapest ?? decodedContent?.isCheapest ?? false;
    const status = (decodedContent?.status ||
      embedData?.status ||
      item.status ||
      "finished") as "processing" | "finished" | "error";

    const embedId = item.contentRef?.replace("embed:", "") || item.id || "";

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }
    content.innerHTML = "";

    // Guard: target element must be attached to the DOM before mounting a Svelte component.
    // During streaming, TipTap may detach/recreate node views asynchronously.
    if (!content.isConnected) {
      console.warn(
        "[GroupRenderer] Skipping TravelConnectionEmbedPreview mount — target detached from DOM",
      );
      return;
    }

    try {
      // No onFullscreen: TravelConnectionEmbedFullscreen is only accessible as a child
      // overlay inside TravelSearchEmbedFullscreen (drill-down pattern). There is no
      // top-level route in ActiveChat.svelte for individual travel-connection embeds.
      // To enable fullscreen from [!](embed:ref) large previews, add a branch in ActiveChat
      // for embedType === 'travel-connection' (or app-skill-use with skill_id === 'connection')
      // and then wire onFullscreen here.

      const component = mount(TravelConnectionEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          price,
          currency,
          transportMethod,
          tripType,
          origin,
          destination,
          departure,
          arrival,
          duration,
          stops,
          carriers,
          carrierCodes,
          bookableSeats,
          isCheapest,
          status,
          isMobile: false,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[GroupRenderer] Mounted TravelConnectionEmbedPreview component:",
        { embedId, origin, destination, status },
      );
    } catch (error) {
      const err = error as Error;
      console.error(
        "[GroupRenderer] Error mounting TravelConnectionEmbedPreview:",
        err?.name,
        err?.message,
        err?.stack,
      );
      // Guard: only fall back if content is still in DOM
      if (content.isConnected) {
        const fallbackHtml = await this.renderTravelConnectionItem(
          item,
          embedData,
          decodedContent,
        );
        content.innerHTML = fallbackHtml;
      }
    }
  }

  /**
   * HTML fallback for travel connection embeds (used by renderItemContent switch).
   */
  private async renderTravelConnectionItem(
    _item: EmbedNodeAttributes,
    _embedData?: any,
    decodedContent: any = null,
  ): Promise<string> {
    const origin = decodedContent?.origin || "";
    const destination = decodedContent?.destination || "";
    const price = decodedContent?.price || "";
    const currency = decodedContent?.currency || "EUR";

    return `
      <div class="embed-app-icon travel">
        <span class="icon icon_travel"></span>
      </div>
      <div class="embed-text-content">
        <div class="embed-text-line">${origin || "Origin"} → ${destination || "Destination"}</div>
        ${price ? `<div class="embed-text-subline">${price} ${currency}</div>` : ""}
      </div>
    `;
  }

  // =========================================================================
  // Travel stay embed rendering — individual Svelte component + HTML fallback
  // =========================================================================

  /**
   * Render a single travel stay embed using TravelStayEmbedPreview.
   * Called from the render() individual embed path when baseType === 'travel-stay'.
   */
  private async renderTravelStayComponent(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
    content: HTMLElement,
  ): Promise<void> {
    const name = decodedContent?.name || "";
    const thumbnail = decodedContent?.thumbnail || "";
    const hotelClass =
      decodedContent?.hotel_class ?? decodedContent?.hotelClass;
    const overallRating =
      decodedContent?.overall_rating ?? decodedContent?.overallRating;
    const reviews = decodedContent?.reviews;
    const currency = decodedContent?.currency || "EUR";
    const ratePerNight =
      decodedContent?.rate_per_night ?? decodedContent?.ratePerNight;
    const totalRate = decodedContent?.total_rate ?? decodedContent?.totalRate;
    const amenities = decodedContent?.amenities || [];
    const isCheapest =
      decodedContent?.is_cheapest ?? decodedContent?.isCheapest ?? false;
    const ecoCertified =
      decodedContent?.eco_certified ?? decodedContent?.ecoCertified ?? false;
    const freeCancellation =
      decodedContent?.free_cancellation ??
      decodedContent?.freeCancellation ??
      false;
    const status = (decodedContent?.status ||
      embedData?.status ||
      item.status ||
      "finished") as "processing" | "finished" | "error";

    const embedId = item.contentRef?.replace("embed:", "") || item.id || "";

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }
    content.innerHTML = "";

    if (!content.isConnected) {
      console.warn(
        "[GroupRenderer] Skipping TravelStayEmbedPreview mount — target detached from DOM",
      );
      return;
    }

    try {
      // No onFullscreen: TravelStayEmbedFullscreen is only accessible as a child overlay
      // inside TravelStaysEmbedFullscreen (drill-down pattern). There is no top-level route
      // in ActiveChat.svelte for individual travel-stay embeds.
      // To enable fullscreen from [!](embed:ref) large previews, add a branch in ActiveChat
      // for embedType === 'travel-stay' (or app-skill-use with skill_id === 'stay')
      // and then wire onFullscreen here.

      const component = mount(TravelStayEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          name,
          thumbnail,
          hotelClass,
          overallRating,
          reviews,
          currency,
          ratePerNight,
          totalRate,
          amenities,
          isCheapest,
          ecoCertified,
          freeCancellation,
          status,
          isMobile: false,
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[GroupRenderer] Mounted TravelStayEmbedPreview component:",
        { embedId, name, status },
      );
    } catch (error) {
      const err = error as Error;
      console.error(
        "[GroupRenderer] Error mounting TravelStayEmbedPreview:",
        err?.name,
        err?.message,
        err?.stack,
      );
      if (content.isConnected) {
        const fallbackHtml = await this.renderTravelStayItem(
          item,
          embedData,
          decodedContent,
        );
        content.innerHTML = fallbackHtml;
      }
    }
  }

  /**
   * HTML fallback for travel stay embeds (used by renderItemContent switch).
   */
  private async renderTravelStayItem(
    _item: EmbedNodeAttributes,
    _embedData?: any,
    decodedContent: any = null,
  ): Promise<string> {
    const name = decodedContent?.name || "Accommodation";
    const ratePerNight =
      decodedContent?.rate_per_night ?? decodedContent?.ratePerNight;
    const currency = decodedContent?.currency || "EUR";

    return `
      <div class="embed-app-icon travel">
        <span class="icon icon_travel"></span>
      </div>
      <div class="embed-text-content">
        <div class="embed-text-line">${name}</div>
        ${ratePerNight ? `<div class="embed-text-subline">${ratePerNight} ${currency}/night</div>` : ""}
      </div>
    `;
  }

  // =========================================================================
  // Events embed rendering — individual Svelte component + HTML fallback
  // =========================================================================

  /**
   * Render a single events-event embed using EventEmbedPreview.
   *
   * Note: EventEmbedPreview is designed as a drill-down child inside EventsSearchEmbedFullscreen.
   * When rendered standalone via [!](embed:ref) large preview, we reconstruct the EventResult
   * struct from the decoded TOON content.
   *
   * Fullscreen: not dispatched — EventEmbedFullscreen is only accessible as a child overlay
   * inside EventsSearchEmbedFullscreen. A top-level route in ActiveChat.svelte would be needed
   * to support individual-event fullscreen from the [!] large preview path.
   */
  private async renderEventComponent(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
    content: HTMLElement,
  ): Promise<void> {
    const embedId = item.contentRef?.replace("embed:", "") || item.id || "";
    const status = (decodedContent?.status ||
      embedData?.status ||
      item.status ||
      "finished") as "processing" | "finished" | "error";

    // Reconstruct EventResult from decoded TOON content.
    // Mirrors the transformer in EventsSearchEmbedFullscreen.svelte.
    const eventResult = {
      embed_id: embedId,
      id: decodedContent?.id as string | undefined,
      provider: decodedContent?.provider as string | undefined,
      title: decodedContent?.title as string | undefined,
      description: decodedContent?.description as string | undefined,
      url: decodedContent?.url as string | undefined,
      date_start: decodedContent?.date_start as string | undefined,
      date_end: decodedContent?.date_end as string | undefined,
      timezone: decodedContent?.timezone as string | undefined,
      event_type: decodedContent?.event_type as string | undefined,
      venue: decodedContent?.venue as Record<string, unknown> | undefined,
      organizer: decodedContent?.organizer as
        | Record<string, unknown>
        | undefined,
      rsvp_count: decodedContent?.rsvp_count as number | undefined,
      is_paid: decodedContent?.is_paid as boolean | undefined,
      fee: decodedContent?.fee as Record<string, unknown> | undefined,
      image_url: decodedContent?.image_url as string | null | undefined,
    };

    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }
    content.innerHTML = "";

    if (!content.isConnected) {
      console.warn(
        "[GroupRenderer] Skipping EventEmbedPreview mount — target detached from DOM",
      );
      return;
    }

    if (status === "processing") {
      // Show plain HTML skeleton while loading — EventEmbedPreview requires a full EventResult
      content.innerHTML = await this.renderEventItem(
        item,
        embedData,
        decodedContent,
      );
      return;
    }

    try {
      const component = mount(EventEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          event: eventResult,
          isMobile: false,
          // No onFullscreen: EventEmbedFullscreen has no top-level route in ActiveChat.
          // Once a top-level route is added, dispatch embedfullscreen here.
        },
      });

      mountedComponents.set(content, component);
      console.debug("[GroupRenderer] Mounted EventEmbedPreview component:", {
        embedId,
        title: eventResult.title,
        status,
      });
    } catch (error) {
      const err = error as Error;
      console.error(
        "[GroupRenderer] Error mounting EventEmbedPreview:",
        err?.name,
        err?.message,
        err?.stack,
      );
      if (content.isConnected) {
        content.innerHTML = await this.renderEventItem(
          item,
          embedData,
          decodedContent,
        );
      }
    }
  }

  /**
   * HTML fallback for events-event embeds (used by renderItemContent switch).
   */
  private async renderEventItem(
    _item: EmbedNodeAttributes,
    _embedData?: any,
    decodedContent: any = null,
  ): Promise<string> {
    const title = decodedContent?.title || "Event";
    const dateStart = decodedContent?.date_start || "";
    const venue =
      decodedContent?.venue?.city || decodedContent?.venue_city || "";

    return `
      <div class="embed-app-icon events">
        <span class="icon icon_events"></span>
      </div>
      <div class="embed-text-content">
        <div class="embed-text-line">${title}</div>
        ${dateStart ? `<div class="embed-text-subline">${dateStart}${venue ? ` · ${venue}` : ""}</div>` : ""}
      </div>
    `;
  }

  // =========================================================================
  // Maps place embed rendering — individual Svelte component + HTML fallback
  // =========================================================================

  /**
   * Render a single maps-place embed using MapsLocationEmbedPreview.
   *
   * Note: maps-place child embeds from a search result carry different data than
   * the user-inserted maps (direct "location" type). The Preview component accepts
   * flat fields: name, address, locationType, placeType, mapImageUrl, status.
   *
   * Fullscreen: not dispatched — MapsLocationEmbedFullscreen for individual place results
   * has no top-level route in ActiveChat.svelte. Add one to enable fullscreen from [!] previews.
   */
  private async renderMapsPlaceComponent(
    item: EmbedNodeAttributes,
    embedData: any = null,
    decodedContent: any = null,
    content: HTMLElement,
  ): Promise<void> {
    const embedId = item.contentRef?.replace("embed:", "") || item.id || "";
    const status = (decodedContent?.status ||
      embedData?.status ||
      item.status ||
      "finished") as "processing" | "finished" | "error";

    // Extract flat props from TOON content — field names follow the backend schema
    const name =
      decodedContent?.name ||
      (decodedContent?.displayName as string | undefined) ||
      "";
    const address =
      decodedContent?.formatted_address ||
      (decodedContent?.formattedAddress as string | undefined) ||
      decodedContent?.address ||
      "";
    const locationType =
      (decodedContent?.location_type as string | undefined) || "";
    const placeType = (decodedContent?.place_type as string | undefined) || "";
    const mapImageUrl =
      (decodedContent?.map_image_url as string | undefined) || "";

    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[GroupRenderer] Error unmounting existing component:", e);
      }
    }
    content.innerHTML = "";

    if (!content.isConnected) {
      console.warn(
        "[GroupRenderer] Skipping MapsLocationEmbedPreview mount — target detached from DOM",
      );
      return;
    }

    try {
      const component = mount(MapsLocationEmbedPreview, {
        target: content,
        props: {
          id: embedId,
          name,
          address,
          locationType,
          placeType,
          mapImageUrl,
          status,
          isMobile: false,
          // No onFullscreen: MapsLocationEmbedFullscreen has no top-level route in ActiveChat.
          // Once a top-level route is added, dispatch embedfullscreen here.
        },
      });

      mountedComponents.set(content, component);
      console.debug(
        "[GroupRenderer] Mounted MapsLocationEmbedPreview component:",
        {
          embedId,
          name,
          status,
        },
      );
    } catch (error) {
      const err = error as Error;
      console.error(
        "[GroupRenderer] Error mounting MapsLocationEmbedPreview:",
        err?.name,
        err?.message,
        err?.stack,
      );
      if (content.isConnected) {
        content.innerHTML = await this.renderMapsPlaceItem(
          item,
          embedData,
          decodedContent,
        );
      }
    }
  }

  /**
   * HTML fallback for maps-place embeds (used by renderItemContent switch).
   */
  private async renderMapsPlaceItem(
    _item: EmbedNodeAttributes,
    _embedData?: any,
    decodedContent: any = null,
  ): Promise<string> {
    const name =
      decodedContent?.name ||
      (decodedContent?.displayName as string | undefined) ||
      "Place";
    const address =
      decodedContent?.formatted_address ||
      (decodedContent?.formattedAddress as string | undefined) ||
      decodedContent?.address ||
      "";

    return `
      <div class="embed-app-icon maps">
        <span class="icon icon_maps"></span>
      </div>
      <div class="embed-text-content">
        <div class="embed-text-line">${name}</div>
        ${address ? `<div class="embed-text-subline">${address}</div>` : ""}
      </div>
    `;
  }

  private getGroupDisplayName(baseType: string, count: number): string {
    const typeDisplayNames: { [key: string]: string } = {
      "app-skill-use": "request",
      "web-website": "website",
      "videos-video": "video",
      "code-code": "code file",
      "docs-doc": "document",
      "sheets-sheet": "spreadsheet",
      "mail-email": "email draft",
      "travel-connection": "flight",
      "travel-stay": "accommodation",
      "events-event": "event",
      "maps-place": "place",
    };

    const displayName = typeDisplayNames[baseType] || baseType;
    return `${count} ${displayName}${count > 1 ? "s" : ""}`;
  }

  /**
   * Open fullscreen view for an embed
   */
  private async openFullscreen(
    attrs: EmbedNodeAttributes,
    embedData: any,
    decodedContent: any,
  ): Promise<void> {
    // Determine embed type from attrs
    const embedType = attrs.type === "web-website" ? "website" : attrs.type;

    // For preview embeds (contentRef starts with 'preview:'), decodedContent is
    // always null because preview embeds are not stored in EmbedStore. We
    // synthesise a minimal decodedContent object from the node attrs so that
    // ActiveChat.svelte's `{#if decodedContent?.code …}` condition is truthy
    // and the fullscreen component receives the code content correctly.
    let finalDecodedContent = decodedContent;
    if (!finalDecodedContent && attrs.contentRef?.startsWith("preview:")) {
      finalDecodedContent = {
        code: attrs.code || "",
        language: attrs.language || "text",
        filename: attrs.filename || "",
        lineCount: attrs.lineCount || 0,
      };
      console.debug(
        "[GroupRenderer] Built synthetic decodedContent for preview embed fullscreen",
        {
          contentRef: attrs.contentRef,
          codeLength: (attrs.code || "").length,
          language: attrs.language,
          filename: attrs.filename,
        },
      );
    }

    // Dispatch custom event to open fullscreen view
    // The fullscreen component will handle loading and displaying embed content
    const event = new CustomEvent("embedfullscreen", {
      detail: {
        embedId: attrs.contentRef?.replace("embed:", ""),
        embedData,
        decodedContent: finalDecodedContent,
        embedType,
        attrs,
      },
      bubbles: true,
    });

    document.dispatchEvent(event);
    console.debug("[GroupRenderer] Dispatched fullscreen event:", event.detail);
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    // Use the group handler to convert to markdown
    return groupHandlerRegistry.groupToMarkdown(attrs);
  }
}
