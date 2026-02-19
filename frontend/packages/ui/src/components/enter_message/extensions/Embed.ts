// Unified Embed extension for the new message parsing architecture
// Replaces individual embed extensions with a single, type-agnostic embed node

import { Node, mergeAttributes } from "@tiptap/core";
import { EmbedNodeAttributes, EmbedType } from "../../../message_parsing/types";
import { getEmbedRenderer, embedRenderers } from "./embed_renderers";
import { groupHandlerRegistry } from "../../../message_parsing/groupHandlers";
import { cancelUpload } from "../embedHandlers";

/**
 * Extract the embed_id from a contentRef string.
 * Only returns a value for "embed:{embed_id}" format (real embeds stored in EmbedStore).
 * Returns null for preview: or stream: refs which are not stored in EmbedStore.
 */
function extractEmbedIdFromContentRef(
  contentRef: string | null | undefined,
): string | null {
  if (!contentRef) return null;
  if (contentRef.startsWith("embed:")) {
    return contentRef.slice("embed:".length);
  }
  return null;
}

/**
 * Clean up embed data from EmbedStore when an embed node is removed from the editor.
 * This prevents orphaned embeds from accumulating in IndexedDB when the user
 * deletes draft-stage embeds (code pastes, URL embeds) before sending.
 *
 * Uses dynamic import to avoid adding embedStore as a top-level dependency.
 * Runs asynchronously and never blocks the editor operation — failures are logged but not thrown.
 */
function cleanupRemovedEmbed(contentRef: string | null | undefined): void {
  const embedId = extractEmbedIdFromContentRef(contentRef);
  if (!embedId) return;

  // Fire-and-forget: delete from EmbedStore asynchronously
  import("../../../services/embedStore")
    .then(({ embedStore }) => {
      embedStore.deleteEmbed(embedId).then(() => {
        console.debug(
          "[Embed] Cleaned up removed embed from EmbedStore:",
          embedId,
        );
      });
    })
    .catch((error) => {
      console.error(
        "[Embed] Failed to clean up removed embed:",
        embedId,
        error,
      );
    });
}

/**
 * Clean up all embeds in a group node from EmbedStore.
 * Iterates through groupedItems and deletes each stored embed.
 */
function cleanupRemovedGroupEmbeds(attrs: EmbedNodeAttributes): void {
  if (!attrs.groupedItems || attrs.groupedItems.length === 0) return;

  for (const item of attrs.groupedItems) {
    cleanupRemovedEmbed(item.contentRef);
  }
}

export interface EmbedOptions {
  // Configuration options for the unified embed extension
  inline?: boolean;
  group?: string;
}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    embed: {
      setEmbed: (attributes: EmbedNodeAttributes) => ReturnType;
      updateEmbed: (
        id: string,
        attributes: Partial<EmbedNodeAttributes>,
      ) => ReturnType;
      removeEmbed: (id: string) => ReturnType;
    };
  }
}

/**
 * Unified Embed extension that handles all embed types through a single node
 * Uses the new unified embed node attributes defined in the architecture
 */
export const Embed = Node.create<EmbedOptions>({
  name: "embed",
  group: "inline",
  inline: true,
  selectable: true,
  draggable: true,

  addOptions() {
    return {
      inline: true,
      group: "inline",
    };
  },

  addAttributes() {
    return {
      // Core unified attributes per the new architecture
      id: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-id"),
        renderHTML: (attributes) => {
          if (!attributes.id) {
            return {};
          }
          return { "data-id": attributes.id };
        },
      },
      type: {
        default: "text",
        parseHTML: (element) => element.getAttribute("data-type"),
        renderHTML: (attributes) => {
          if (!attributes.type) {
            return {};
          }
          return { "data-type": attributes.type };
        },
      },
      status: {
        default: "finished",
        parseHTML: (element) => element.getAttribute("data-status"),
        renderHTML: (attributes) => {
          if (!attributes.status) {
            return {};
          }
          return { "data-status": attributes.status };
        },
      },
      contentRef: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-content-ref"),
        renderHTML: (attributes) => {
          if (!attributes.contentRef) {
            return {};
          }
          return { "data-content-ref": attributes.contentRef };
        },
      },
      contentHash: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-content-hash"),
        renderHTML: (attributes) => {
          if (!attributes.contentHash) {
            return {};
          }
          return { "data-content-hash": attributes.contentHash };
        },
      },
      // Optional metadata attributes
      language: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-language"),
        renderHTML: (attributes) => {
          if (!attributes.language) {
            return {};
          }
          return { "data-language": attributes.language };
        },
      },
      filename: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-filename"),
        renderHTML: (attributes) => {
          if (!attributes.filename) {
            return {};
          }
          return { "data-filename": attributes.filename };
        },
      },
      title: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-title"),
        renderHTML: (attributes) => {
          if (!attributes.title) {
            return {};
          }
          return { "data-title": attributes.title };
        },
      },
      url: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-url"),
        renderHTML: (attributes) => {
          if (!attributes.url) {
            return {};
          }
          return { "data-url": attributes.url };
        },
      },
      // Count metadata
      lineCount: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute("data-line-count");
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: (attributes) => {
          if (!attributes.lineCount) {
            return {};
          }
          return { "data-line-count": attributes.lineCount.toString() };
        },
      },
      // Temporary field for preview code embeds (stores code content inline)
      // This is only used for preview embeds in write mode, not persisted
      code: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-code"),
        renderHTML: (attributes) => {
          if (!attributes.code) {
            return {};
          }
          return { "data-code": attributes.code };
        },
      },
      wordCount: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute("data-word-count");
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: (attributes) => {
          if (!attributes.wordCount) {
            return {};
          }
          return { "data-word-count": attributes.wordCount.toString() };
        },
      },
      cellCount: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute("data-cell-count");
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: (attributes) => {
          if (!attributes.cellCount) {
            return {};
          }
          return { "data-cell-count": attributes.cellCount.toString() };
        },
      },
      rows: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute("data-rows");
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: (attributes) => {
          if (!attributes.rows) {
            return {};
          }
          return { "data-rows": attributes.rows.toString() };
        },
      },
      cols: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute("data-cols");
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: (attributes) => {
          if (!attributes.cols) {
            return {};
          }
          return { "data-cols": attributes.cols.toString() };
        },
      },
      // Website-specific metadata attributes
      description: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-description"),
        renderHTML: (attributes) => {
          if (!attributes.description) {
            return {};
          }
          return { "data-description": attributes.description };
        },
      },
      favicon: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-favicon"),
        renderHTML: (attributes) => {
          if (!attributes.favicon) {
            return {};
          }
          return { "data-favicon": attributes.favicon };
        },
      },
      image: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-image"),
        renderHTML: (attributes) => {
          if (!attributes.image) {
            return {};
          }
          return { "data-image": attributes.image };
        },
      },
      // App skill metadata attributes
      // CRITICAL: These must be registered as TipTap attributes so they survive setContent()
      // during streaming. Without these, app_id/skill_id get stripped by TipTap, preventing
      // the grouping pipeline from correctly grouping app-skill-use embeds.
      app_id: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-app-id"),
        renderHTML: (attributes) => {
          if (!attributes.app_id) {
            return {};
          }
          return { "data-app-id": attributes.app_id };
        },
      },
      skill_id: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-skill-id"),
        renderHTML: (attributes) => {
          if (!attributes.skill_id) {
            return {};
          }
          return { "data-skill-id": attributes.skill_id };
        },
      },
      query: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-query"),
        renderHTML: (attributes) => {
          if (!attributes.query) {
            return {};
          }
          return { "data-query": attributes.query };
        },
      },
      provider: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-provider"),
        renderHTML: (attributes) => {
          if (!attributes.provider) {
            return {};
          }
          return { "data-provider": attributes.provider };
        },
      },
      // -----------------------------------------------------------------------
      // Maps location embed attributes
      // Stored as data-* attributes so they survive TipTap DOM round-trips.
      // preciseLat/preciseLon are used for the in-editor Leaflet pin preview.
      // zoom is used to set the initial zoom level of the Leaflet map.
      // name is the short display label for the location.
      // -----------------------------------------------------------------------
      preciseLat: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute("data-precise-lat");
          return value ? parseFloat(value) : null;
        },
        renderHTML: (attributes) => {
          if (attributes.preciseLat == null) return {};
          return { "data-precise-lat": String(attributes.preciseLat) };
        },
      },
      preciseLon: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute("data-precise-lon");
          return value ? parseFloat(value) : null;
        },
        renderHTML: (attributes) => {
          if (attributes.preciseLon == null) return {};
          return { "data-precise-lon": String(attributes.preciseLon) };
        },
      },
      zoom: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute("data-zoom");
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: (attributes) => {
          if (attributes.zoom == null) return {};
          return { "data-zoom": String(attributes.zoom) };
        },
      },
      // address: resolved human-readable street address for the embed card secondary line.
      // Stored as a data-* attribute so it survives TipTap DOM round-trips.
      address: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-address") ?? null,
        renderHTML: (attributes) => {
          if (!attributes.address) return {};
          return { "data-address": attributes.address };
        },
      },
      // locationType: "precise_location" | "area" — set by MapsView when the user confirms.
      // "area" means the user had imprecise/privacy mode on; used to show the "Nearby:" label.
      locationType: {
        default: null,
        parseHTML: (element) =>
          element.getAttribute("data-location-type") ?? null,
        renderHTML: (attributes) => {
          if (!attributes.locationType) return {};
          return { "data-location-type": attributes.locationType };
        },
      },
      // Focus mode metadata
      focus_id: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-focus-id"),
        renderHTML: (attributes) => {
          if (!attributes.focus_id) {
            return {};
          }
          return { "data-focus-id": attributes.focus_id };
        },
      },
      focus_mode_name: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-focus-mode-name"),
        renderHTML: (attributes) => {
          if (!attributes.focus_mode_name) {
            return {};
          }
          return { "data-focus-mode-name": attributes.focus_mode_name };
        },
      },
      // Website group attributes
      groupedItems: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute("data-grouped-items");
          try {
            return value ? JSON.parse(value) : null;
          } catch {
            return null;
          }
        },
        renderHTML: (attributes) => {
          if (!attributes.groupedItems) {
            return {};
          }
          return {
            "data-grouped-items": JSON.stringify(attributes.groupedItems),
          };
        },
      },
      groupCount: {
        default: null,
        parseHTML: (element) => {
          const value = element.getAttribute("data-group-count");
          return value ? parseInt(value, 10) : null;
        },
        renderHTML: (attributes) => {
          if (!attributes.groupCount) {
            return {};
          }
          return { "data-group-count": attributes.groupCount.toString() };
        },
      },
      // -----------------------------------------------------------------------
      // Image upload ephemeral attributes — in-memory only, NOT persisted to DOM.
      // These are set by insertImage() and _performUpload() in embedHandlers.ts.
      // rendered: false means TipTap keeps them in the ProseMirror document but
      // never writes them to the HTML (no parseHTML / renderHTML needed).
      // -----------------------------------------------------------------------
      /** Local blob URL for instant preview while uploading. Only valid for the
       *  duration of the upload session — not serialized to HTML. */
      src: { default: null, rendered: false },
      /** Original object URL before any processing (unused currently, reserved) */
      originalUrl: { default: null, rendered: false },
      /** S3 file variant metadata returned by the upload server.
       *  Shape: { preview, full, original } each with s3_key, width, height, etc. */
      s3Files: { default: null, rendered: false },
      /** S3 base URL for constructing full image fetch URLs */
      s3BaseUrl: { default: null, rendered: false },
      /** Plaintext AES-256 key (base64) for client-side image decryption */
      aesKey: { default: null, rendered: false },
      /** AES-GCM nonce (base64) shared across all encrypted image variants */
      aesNonce: { default: null, rendered: false },
      /** Vault-wrapped AES key (base64) for server-side key storage */
      vaultWrappedAesKey: { default: null, rendered: false },
      /** Error message set by _performUpload() when the upload fails */
      uploadError: { default: null, rendered: false },
      /** Unique upload correlation ID set by insertImage() */
      uploadEmbedId: { default: null, rendered: false },
      /** AI detection/moderation result returned by the upload server */
      aiDetection: { default: null, rendered: false },
      /** The original File object (only in editor session, not serialized) */
      originalFile: { default: null, rendered: false },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'div[data-embed-unified="true"]',
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    const attrs = mergeAttributes(HTMLAttributes, {
      "data-embed-unified": "true",
      class: `embed-unified embed-${HTMLAttributes["data-type"] || "text"} embed-status-${HTMLAttributes["data-status"] || "finished"}`,
    });

    return ["div", attrs];
  },

  addNodeView() {
    return ({ node, getPos, editor }) => {
      let currentAttrs = node.attrs as EmbedNodeAttributes;

      // Create full-width wrapper to prevent cursor positioning after embed
      const wrapper = document.createElement("div");
      wrapper.classList.add("embed-full-width-wrapper");
      wrapper.style.width = "100%";
      wrapper.style.display = "block";

      // For image embeds (legal SVGs), minimize spacing
      if (currentAttrs.type === "image") {
        wrapper.style.margin = "0";
        wrapper.style.marginBottom = "8px";
      }

      // For embed types that render Svelte components with their own UnifiedEmbedPreview,
      // mount directly into wrapper (no intermediate container)
      // These types already have their own container styling (background, border-radius, box-shadow, tilt effect)
      // Adding an extra embed-unified-container would cause visual artifacts during 3D transforms
      let container: HTMLElement;
      let mountTarget: HTMLElement;

      // Embed types that use Svelte components with UnifiedEmbedPreview - no wrapper needed.
      // These mount directly into the wrapper; the Svelte component provides its own
      // container styling (background, border-radius, box-shadow, etc.).
      const svelteComponentEmbedTypes = [
        "app-skill-use",
        "code-code", // CodeEmbedPreview uses UnifiedEmbedPreview
        "web-website", // WebsiteEmbedPreview uses UnifiedEmbedPreview
        "videos-video", // VideoEmbedPreview uses UnifiedEmbedPreview
        "image", // ImageEmbedPreview uses UnifiedEmbedPreview (uploaded images)
        "maps", // MapLocationEmbedPreview renders Leaflet map inline
      ];

      if (svelteComponentEmbedTypes.includes(currentAttrs.type)) {
        // Mount directly into wrapper - Svelte component creates its own unified-embed-preview
        // NO intermediate container - wrapper is used directly
        container = wrapper;
        mountTarget = wrapper;
        // Ensure wrapper does NOT have embed-unified-container class
        wrapper.classList.remove("embed-unified-container");
      } else {
        // Create container element for other embed types
        container = document.createElement("div");

        // Use different class for group containers vs individual embeds
        if (currentAttrs.type && currentAttrs.type.endsWith("-group")) {
          container.classList.add("embed-group-container");
        } else {
          container.classList.add("embed-unified-container");
          container.setAttribute("data-embed-type", currentAttrs.type);
          container.setAttribute("data-embed-status", currentAttrs.status);
        }

        // For image embeds, add a special class to identify them
        if (currentAttrs.type === "image") {
          container.classList.add("embed-image-non-interactive");
        }

        // Add processing/finished visual indicators
        if (currentAttrs.status === "processing") {
          container.classList.add("embed-processing");
        } else {
          container.classList.add("embed-finished");
        }

        // Add container to wrapper
        wrapper.appendChild(container);
        mountTarget = container;
      }

      // Check if we have a specific renderer for this embed type
      const renderer = getEmbedRenderer(currentAttrs.type);

      console.debug(
        "[Embed] Looking for renderer for type:",
        currentAttrs.type,
        "found:",
        !!renderer,
      );
      console.debug("[Embed] Renderer object:", renderer);
      console.debug(
        "[Embed] Available renderers:",
        Object.keys(embedRenderers),
      );

      if (renderer) {
        // Use the dedicated renderer
        // For app-skill-use: mount directly into wrapper (Svelte component creates unified-embed-preview)
        // For other types: mount into container (renderers create their own content structure)
        console.debug("[Embed] Using renderer for type:", currentAttrs.type);

        // If renderer.render is async (returns Promise), handle it
        const renderResult = renderer.render({
          attrs: currentAttrs,
          container,
          content: mountTarget,
        });

        if (renderResult instanceof Promise) {
          // Handle async rendering (e.g., loading from EmbedStore)
          renderResult.catch((error) => {
            console.error("[Embed] Error during async render:", error);
            mountTarget.innerHTML = `<div class="embed-error">Error loading embed: ${error.message}</div>`;
          });
        }
      } else {
        // No renderer found - this should not happen for properly configured embed types
        console.error(
          "[Embed] No renderer found for embed type:",
          currentAttrs.type,
        );
        throw new Error(
          `No renderer found for embed type: ${currentAttrs.type}. This indicates a missing renderer registration.`,
        );
      }

      // For image embeds: listen for the 'cancelimageupload' event fired by the
      // Stop button in ImageEmbedPreview. Cancel the in-flight upload and delete
      // the node from the document.
      if (currentAttrs.type === "image") {
        wrapper.addEventListener("cancelimageupload", (e) => {
          const embedId = (e as CustomEvent<{ embedId: string }>).detail
            ?.embedId;
          if (embedId) cancelUpload(embedId);
          if (typeof getPos === "function") {
            const pos = getPos();
            const nodeSize = editor.state.doc.nodeAt(pos)?.nodeSize ?? 1;
            const to = pos + nodeSize;
            const hardBreakAfter = editor.state.doc.nodeAt(to);
            const deleteTo =
              hardBreakAfter?.type.name === "hardBreak" ? to + 1 : to;
            editor
              .chain()
              .focus()
              .deleteRange({ from: pos, to: deleteTo })
              .run();
          }
          console.debug(
            "[Embed] Stop button: cancelled upload and deleted image embed:",
            embedId,
          );
        });
      }

      // Make the node selectable and add basic interaction
      // BUT: Skip click handlers for image embeds (they should not be clickable)
      // For Svelte component embeds, they handle their own click events
      const skipClickHandler =
        currentAttrs.type === "image" ||
        svelteComponentEmbedTypes.includes(currentAttrs.type);
      if (!skipClickHandler) {
        container.addEventListener("click", () => {
          if (typeof getPos === "function") {
            const pos = getPos();
            editor.commands.setNodeSelection(pos);
          }
        });
      }

      // Prevent cursor from being positioned before the embed
      // BUT: Skip this for image embeds (they should not be interactive)
      // For Svelte component embeds, they handle their own interactions
      if (!skipClickHandler) {
        container.addEventListener("mousedown", (event) => {
          // If clicking at the start of the embed, move cursor to after it
          const rect = container.getBoundingClientRect();
          const clickX = event.clientX;
          const isClickingAtStart = clickX < rect.left + rect.width * 0.3; // First 30% of embed

          console.debug("[Embed] Mouse down on embed:", {
            clickX,
            rectLeft: rect.left,
            rectWidth: rect.width,
            isClickingAtStart,
            embedType: currentAttrs.type,
          });

          if (isClickingAtStart && typeof getPos === "function") {
            event.preventDefault();
            const pos = getPos();
            // Move cursor to after the embed
            editor.commands.setTextSelection(
              pos + container.textContent.length,
            );
            console.debug(
              "[Embed] Prevented cursor positioning before embed, moved to after",
            );
          }
        });
      }

      return {
        dom: wrapper,
        update: (updatedNode) => {
          // Update the node view when attributes change
          if (updatedNode.type.name !== "embed") return false;

          const newAttrs = updatedNode.attrs as EmbedNodeAttributes;

          // CRITICAL FIX: When the embed TYPE changes (e.g., app-skill-use -> app-skill-use-group),
          // the DOM structure is fundamentally different:
          // - Individual app-skill-use: container = wrapper (Svelte component path, no intermediate div)
          // - Group app-skill-use-group: uses embed-group-container div inside wrapper
          // Returning false forces TipTap to destroy this NodeView and create a new one
          // with the correct DOM structure for the new type.
          if (newAttrs.type !== currentAttrs.type) {
            console.debug(
              "[Embed] Type changed from",
              currentAttrs.type,
              "to",
              newAttrs.type,
              "- forcing NodeView recreation",
            );
            return false;
          }

          // CRITICAL FIX: For group embeds, detect when groupedItems has changed
          // and re-render the entire group to show new items during streaming.
          // Without this, only the first item would show during streaming.
          if (
            newAttrs.type &&
            newAttrs.type.endsWith("-group") &&
            newAttrs.groupedItems
          ) {
            const oldGroupedItems = currentAttrs.groupedItems || [];
            const newGroupedItems = newAttrs.groupedItems || [];

            // Check if group items have changed (length or IDs)
            const hasGroupChanged =
              oldGroupedItems.length !== newGroupedItems.length ||
              oldGroupedItems.some(
                (item: EmbedNodeAttributes, idx: number) =>
                  item.id !== newGroupedItems[idx]?.id,
              );

            if (hasGroupChanged) {
              console.debug("[Embed] Group items changed, updating group:", {
                oldCount: oldGroupedItems.length,
                newCount: newGroupedItems.length,
                type: newAttrs.type,
              });

              // Update current attrs before re-rendering
              currentAttrs = newAttrs;

              // Re-render the group with new items.
              // GroupRenderer.render() will try an incremental DOM update first
              // (only appending new items) before falling back to a full re-render.
              // This avoids the visible "flash" caused by destroying and re-mounting
              // every Svelte component on each streaming update.
              const groupRenderer = getEmbedRenderer(newAttrs.type);
              if (groupRenderer) {
                const renderResult = groupRenderer.render({
                  attrs: newAttrs,
                  container,
                  content: mountTarget,
                });

                if (renderResult instanceof Promise) {
                  renderResult.catch((error) => {
                    console.error("[Embed] Error re-rendering group:", error);
                  });
                }
              }

              return true;
            }
          }

          // Update current attrs
          currentAttrs = newAttrs;

          // For Svelte component embeds, the wrapper is the container (no intermediate container)
          // For other types, update the container classes
          if (svelteComponentEmbedTypes.includes(newAttrs.type)) {
            // No container to update - Svelte component handles its own structure
            // Just update wrapper attributes if needed
            wrapper.setAttribute("data-embed-type", newAttrs.type);
            wrapper.setAttribute("data-embed-status", newAttrs.status);
            // CRITICAL: Ensure wrapper never has embed-unified-container class
            wrapper.classList.remove("embed-unified-container");
            wrapper.classList.remove("embed-processing");
            wrapper.classList.remove("embed-finished");
          } else {
            // Update classes for non-Svelte component embeds
            if (newAttrs.type && newAttrs.type.endsWith("-group")) {
              container.className = "embed-group-container";
            } else {
              container.className = "embed-unified-container";
              container.setAttribute("data-embed-type", newAttrs.type);
              container.setAttribute("data-embed-status", newAttrs.status);
            }

            // Add processing/finished visual indicators
            if (newAttrs.status === "processing") {
              container.classList.add("embed-processing");
            } else {
              container.classList.add("embed-finished");
            }
          }

          return true;
        },
        destroy: () => {
          // Cleanup if needed
        },
      };
    };
  },

  addCommands() {
    return {
      setEmbed:
        (attributes: EmbedNodeAttributes) =>
        ({ commands }) => {
          return commands.insertContent({
            type: this.name,
            attrs: attributes,
          });
        },

      updateEmbed:
        (id: string, attributes: Partial<EmbedNodeAttributes>) =>
        ({ tr, state }) => {
          const { doc } = state;
          let updated = false;

          doc.descendants((node, pos) => {
            if (node.type.name === this.name && node.attrs.id === id) {
              const newAttrs = { ...node.attrs, ...attributes };
              tr.setNodeMarkup(pos, undefined, newAttrs);
              updated = true;
              return false; // Stop traversal
            }
          });

          return updated;
        },

      removeEmbed:
        (id: string) =>
        ({ tr, state }) => {
          const { doc } = state;
          let removed = false;

          doc.descendants((node, pos) => {
            if (node.type.name === this.name && node.attrs.id === id) {
              tr.delete(pos, pos + node.nodeSize);
              removed = true;
              return false; // Stop traversal
            }
          });

          return removed;
        },
    };
  },

  addKeyboardShortcuts() {
    return {
      // Prevent cursor from being positioned before an embed in the same paragraph
      ArrowLeft: ({ editor }) => {
        const { empty, $anchor } = editor.state.selection;
        if (!empty) return false;

        const pos = $anchor.pos;
        const node = editor.state.doc.nodeAt(pos);

        console.debug(
          "[Embed] ArrowLeft at position:",
          pos,
          "node type:",
          node?.type.name,
        );

        // If we're at the start of an embed, prevent moving left
        if (node?.type.name === this.name) {
          console.debug("[Embed] Prevented arrow left into embed");
          return true; // Prevent default behavior
        }

        return false;
      },

      // Prevent cursor from being positioned after an embed in the same paragraph
      ArrowRight: ({ editor }) => {
        const { empty, $anchor } = editor.state.selection;
        if (!empty) return false;

        const pos = $anchor.pos;
        const node = editor.state.doc.nodeAt(pos - 1);

        console.debug(
          "[Embed] ArrowRight at position:",
          pos,
          "node before:",
          node?.type.name,
        );

        // If we're right after an embed, prevent moving right into it
        if (node?.type.name === this.name) {
          console.debug("[Embed] Prevented arrow right into embed");
          return true; // Prevent default behavior
        }

        return false;
      },

      Backspace: ({ editor }) => {
        const { empty, $anchor } = editor.state.selection;
        if (!empty) return false;

        const pos = $anchor.pos;

        console.debug("[Embed] Backspace triggered at position:", pos);

        // Check if we're positioned right after an embed node
        // ONLY delete when cursor is directly adjacent to the embed:
        //   Case 1: Node at pos-1 is an embed (cursor immediately after embed inline)
        //   Case 2: Node at pos-1 is a hardBreak and the node before the hardBreak is
        //           an embed (cursor at start of line immediately after embed + line break)
        let embedNode = null;
        let embedPos = -1;

        // Case 1: Check the node immediately before the cursor
        const nodeBefore = editor.state.doc.nodeAt(pos - 1);
        console.debug(
          "[Embed] Node before cursor:",
          nodeBefore?.type.name,
          nodeBefore,
        );

        if (nodeBefore?.type.name === this.name) {
          embedNode = nodeBefore;
          embedPos = pos - 1;
          console.debug("[Embed] Found embed node immediately before cursor");
        } else if (nodeBefore?.type.name === "hardBreak" && pos >= 2) {
          // Case 2: Cursor is right after a hardBreak — check if the node before the
          // hardBreak is an embed. This handles the pattern: [embed][hardBreak]|cursor
          const nodeBeforeHardBreak = editor.state.doc.nodeAt(pos - 2);
          if (nodeBeforeHardBreak?.type.name === this.name) {
            embedNode = nodeBeforeHardBreak;
            embedPos = pos - 2;
            console.debug(
              "[Embed] Found embed node before hardBreak at position:",
              embedPos,
            );
          }
        }

        if (embedNode && embedPos !== -1) {
          const attrs = embedNode.attrs as EmbedNodeAttributes;
          const from = embedPos;
          const to = embedPos + embedNode.nodeSize;

          console.debug("[Embed] Processing backspace for embed:", {
            type: attrs.type,
            url: attrs.url,
            from,
            to,
            nodeSize: embedNode.nodeSize,
          });

          // Special handling for group nodes (website-group, code-group, doc-group, etc.)
          if (attrs.type.endsWith("-group")) {
            const backspaceResult =
              groupHandlerRegistry.handleGroupBackspace(attrs);

            if (backspaceResult) {
              const groupedItems = attrs.groupedItems || [];

              switch (backspaceResult.action) {
                case "split-group":
                  if (backspaceResult.replacementContent) {
                    // Notify that we're performing a backspace operation to prevent immediate re-grouping
                    document.dispatchEvent(
                      new CustomEvent("embed-group-backspace", {
                        detail: { action: "split-group" },
                      }),
                    );

                    // Replace the group with individual embeds + editable content
                    // Also remove any hard break that follows the group
                    const hardBreakAfter = editor.state.doc.nodeAt(to);
                    const deleteTo =
                      hardBreakAfter?.type.name === "hardBreak" ? to + 1 : to;

                    editor
                      .chain()
                      .focus()
                      .deleteRange({ from, to: deleteTo })
                      .insertContent(backspaceResult.replacementContent)
                      .run();

                    // Clean up the last item's embed (the one removed from the group and converted to text)
                    if (groupedItems.length > 0) {
                      const removedItem = groupedItems[groupedItems.length - 1];
                      cleanupRemovedEmbed(removedItem.contentRef);
                    }
                  }
                  return true;

                case "convert-to-text":
                  if (backspaceResult.replacementText) {
                    // Convert to plain text for editing
                    // Also remove any hard break that follows the group
                    const hardBreakAfter = editor.state.doc.nodeAt(to);
                    const deleteTo =
                      hardBreakAfter?.type.name === "hardBreak" ? to + 1 : to;

                    editor
                      .chain()
                      .focus()
                      .deleteRange({ from, to: deleteTo })
                      .insertContent(backspaceResult.replacementText)
                      .run();

                    // Clean up all embeds in the group since the entire group is converted to text
                    cleanupRemovedGroupEmbeds(attrs);
                  }
                  return true;

                case "delete-group":
                  // Just delete the group and any following hard break
                  const hardBreakAfter = editor.state.doc.nodeAt(to);
                  const deleteTo =
                    hardBreakAfter?.type.name === "hardBreak" ? to + 1 : to;

                  editor
                    .chain()
                    .focus()
                    .deleteRange({ from, to: deleteTo })
                    .run();

                  // Clean up all embeds in the group since the entire group is deleted
                  cleanupRemovedGroupEmbeds(attrs);
                  return true;
              }
            }

            // Fallback: just delete the group if no handler found
            console.warn(
              "[Embed] No group handler found for group type:",
              attrs.type,
            );
            const hardBreakAfter = editor.state.doc.nodeAt(to);
            const deleteTo =
              hardBreakAfter?.type.name === "hardBreak" ? to + 1 : to;

            editor.chain().focus().deleteRange({ from, to: deleteTo }).run();

            // Clean up all embeds in the group on fallback deletion too
            cleanupRemovedGroupEmbeds(attrs);
            return true;
          }

          // Convert back to canonical markdown based on embed type for non-group embeds
          let markdown = "";

          // For individual embeds (not groups), handle conversion directly
          // Don't use renderer.toMarkdown for individual embeds as it's designed for groups
          switch (attrs.type) {
            case "web-website":
              // For website embeds, restore the original URL
              markdown = attrs.url || "";
              console.debug("[Embed] Converting web-website to URL:", markdown);
              break;
            case "videos-video":
              // For video embeds, restore the original URL
              markdown = attrs.url || "";
              console.debug(
                "[Embed] Converting videos-video to URL:",
                markdown,
              );
              break;
            case "code-code":
              const language = attrs.language || "";
              const filename = attrs.filename ? `:${attrs.filename}` : "";

              // For preview embeds (contentRef starts with 'preview:'), restore code block WITHOUT closing fence
              // This allows the user to continue editing the code block
              // For real embeds, just restore the fence (content is in EmbedStore)
              if (attrs.contentRef?.startsWith("preview:")) {
                const codeContent = attrs.code || "";
                // Remove closing fence to allow continued editing
                markdown = `\`\`\`${language}${filename}\n${codeContent}`;
                console.debug(
                  "[Embed] Converting preview code-code to edit mode (no closing fence)",
                );
              } else {
                markdown = `\`\`\`${language}${filename}\n\`\`\``;
                console.debug(
                  "[Embed] Converting code-code to markdown fence only",
                );
              }
              break;
            case "docs-doc":
              // For preview embeds, restore content WITHOUT closing fence for continued editing
              // For real embeds, just restore the fence
              if (attrs.contentRef?.startsWith("preview:")) {
                const docContent = attrs.code || "";
                const title = attrs.title
                  ? `<!-- title: "${attrs.title}" -->\n`
                  : "";
                // Remove closing fence to allow continued editing
                markdown = `\`\`\`doc\n${title}${docContent}`;
                console.debug(
                  "[Embed] Converting preview docs-doc to edit mode (no closing fence)",
                );
              } else {
                const title = attrs.title
                  ? `<!-- title: "${attrs.title}" -->\n`
                  : "";
                markdown = `\`\`\`document_html\n${title}\`\`\``;
                console.debug(
                  "[Embed] Converting docs-doc to markdown fence only",
                );
              }
              break;
            case "sheets-sheet":
              // For preview embeds, restore full table content
              // For real embeds, restore a placeholder table
              if (attrs.contentRef?.startsWith("preview:")) {
                const tableContent = attrs.code || "";
                const title = attrs.title
                  ? `<!-- title: "${attrs.title}" -->\n`
                  : "";
                markdown = `${title}${tableContent}`;
                console.debug(
                  "[Embed] Converting preview sheets-sheet to full markdown with content",
                );
              } else {
                const sheetTitle = attrs.title
                  ? `<!-- title: "${attrs.title}" -->\n`
                  : "";
                markdown = `${sheetTitle}| Column 1 | Column 2 |\n|----------|----------|\n| Data 1   | Data 2   |`;
                console.debug(
                  "[Embed] Converting sheets-sheet to markdown placeholder",
                );
              }
              break;
            case "image":
              // Image embeds are not converted to markdown on Backspace.
              // Instead we delete the node entirely and cancel any in-flight upload.
              // The embed ID is in attrs.id (set by insertImage).
              if (attrs.id) {
                cancelUpload(attrs.id);
              }
              {
                const hardBreakAfterImg = editor.state.doc.nodeAt(to);
                const deleteToImg =
                  hardBreakAfterImg?.type.name === "hardBreak" ? to + 1 : to;
                editor
                  .chain()
                  .focus()
                  .deleteRange({ from, to: deleteToImg })
                  .run();
              }
              console.debug(
                "[Embed] Deleted image embed and cancelled upload:",
                attrs.id,
              );
              return true;

            case "maps":
              // Maps location embeds are deleted entirely on Backspace
              // (same pattern as image embeds — no meaningful markdown representation).
              {
                const hardBreakAfterMap = editor.state.doc.nodeAt(to);
                const deleteToMap =
                  hardBreakAfterMap?.type.name === "hardBreak" ? to + 1 : to;
                editor
                  .chain()
                  .focus()
                  .deleteRange({ from, to: deleteToMap })
                  .run();
              }
              // Clean up the embed from EmbedStore (contentRef: "embed:{id}")
              cleanupRemovedEmbed(attrs.contentRef);
              console.debug("[Embed] Deleted maps embed:", attrs.id);
              return true;

            default:
              markdown = `[${attrs.type} content]`;
              console.debug(
                "[Embed] Using default fallback markdown:",
                markdown,
              );
          }

          // Replace the embed node with the original markdown text
          // Also remove any hard break that follows the embed
          const hardBreakAfter = editor.state.doc.nodeAt(to);
          const deleteTo =
            hardBreakAfter?.type.name === "hardBreak" ? to + 1 : to;

          console.debug("[Embed] Replacing embed with markdown:", {
            markdown,
            from,
            deleteTo,
            hasHardBreakAfter: hardBreakAfter?.type.name === "hardBreak",
          });

          editor
            .chain()
            .focus()
            .deleteRange({ from, to: deleteTo })
            .insertContent(markdown)
            .run();

          // Clean up the embed from EmbedStore if it was a stored embed (contentRef: "embed:{id}")
          // This prevents orphaned embeds in IndexedDB when users delete draft-stage embeds
          cleanupRemovedEmbed(attrs.contentRef);

          return true;
        }
        return false;
      },
    };
  },
});
