/**
 * Renderer for focus_mode_activation embeds.
 *
 * Mounts FocusModeActivationEmbed.svelte which shows:
 * - A compact card with app icon + focus mode name
 * - A countdown timer (4,3,2,1) with progress bar
 * - Click-to-reject during countdown
 * - "Focus activated" state after countdown
 *
 * The renderer checks the current chat's active focus mode state (from IndexedDB/cache)
 * to determine if the focus mode is already active. If so, it passes `alreadyActive=true`
 * to the component, which skips the countdown and shows the activated state immediately.
 * This prevents the countdown from replaying when the user revisits a chat.
 *
 * On rejection the renderer:
 * 1. Dispatches a "focusModeRejected" custom event on document (picked up by ActiveChat)
 * 2. Sends a deactivation request to the backend via WebSocket
 */

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { mount, unmount } from "svelte";
import FocusModeActivationEmbed from "../../../embeds/FocusModeActivationEmbed.svelte";
import { activeChatStore } from "../../../../stores/activeChatStore";
import { chatMetadataCache } from "../../../../services/chatMetadataCache";
import { chatDB } from "../../../../services/db";

// Track mounted components for cleanup
const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

export class FocusModeActivationRenderer implements EmbedRenderer {
  type = "focus-mode-activation";

  async render(context: EmbedRenderContext): Promise<void> {
    const { attrs, content } = context;

    // Extract focus mode metadata from attrs (parsed from JSON embed reference)
    const focusId = attrs.focus_id || "";
    const appId = attrs.app_id || "";
    const focusModeName = attrs.focus_mode_name || focusId;

    if (!focusId) {
      console.warn(
        "[FocusModeActivationRenderer] Missing focus_id in attrs, skipping render",
      );
      content.innerHTML = "";
      return;
    }

    // Check if this focus mode is already active on the current chat.
    // This prevents the countdown from replaying when the user revisits
    // a chat where a focus mode was previously activated.
    let alreadyActive = false;
    try {
      const chatId = activeChatStore.get();
      if (chatId) {
        const chat = await chatDB.getChat(chatId);
        if (chat) {
          const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
          if (metadata?.activeFocusId === focusId) {
            alreadyActive = true;
          }
        }
      }
    } catch (e) {
      // Non-blocking: if we can't determine the active state, fall back to countdown
      console.debug(
        "[FocusModeActivationRenderer] Could not check active focus state:",
        e,
      );
    }

    console.debug("[FocusModeActivationRenderer] Rendering:", {
      focusId,
      appId,
      focusModeName,
      embedId: attrs.id,
      alreadyActive,
    });

    // Cleanup any existing mounted component
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[FocusModeActivationRenderer] Error unmounting existing component:",
          e,
        );
      }
    }

    // Clear the content element
    content.innerHTML = "";

    // Set data attributes for context menu detection in ChatMessage.svelte
    const container = content.parentElement || content;
    container.setAttribute("data-embed-type", "focus-mode-activation");
    container.setAttribute("data-focus-id", focusId);
    container.setAttribute("data-app-id", appId);
    container.setAttribute("data-focus-mode-name", focusModeName);

    try {
      const component = mount(FocusModeActivationEmbed, {
        target: content,
        props: {
          id: attrs.id || "",
          focusId,
          appId,
          focusModeName,
          alreadyActive,
          onReject: (rejectedFocusId: string, rejectedName: string) => {
            console.debug(
              "[FocusModeActivationRenderer] Focus mode rejected:",
              rejectedFocusId,
            );
            // Dispatch a custom event for ActiveChat / ChatMessage to handle
            // This will create a system message and deactivate the focus mode
            document.dispatchEvent(
              new CustomEvent("focusModeRejected", {
                bubbles: true,
                detail: {
                  focusId: rejectedFocusId,
                  focusModeName: rejectedName,
                  appId,
                  embedId: attrs.id,
                },
              }),
            );
          },
          onDeactivate: (deactivatedFocusId: string) => {
            console.debug(
              "[FocusModeActivationRenderer] Focus mode deactivated:",
              deactivatedFocusId,
            );
            document.dispatchEvent(
              new CustomEvent("focusModeDeactivated", {
                bubbles: true,
                detail: {
                  focusId: deactivatedFocusId,
                  appId,
                  embedId: attrs.id,
                },
              }),
            );
          },
          onDetails: (detailsFocusId: string, detailsAppId: string) => {
            console.debug(
              "[FocusModeActivationRenderer] Focus mode details requested:",
              detailsFocusId,
            );
            document.dispatchEvent(
              new CustomEvent("focusModeDetailsRequested", {
                bubbles: true,
                detail: {
                  focusId: detailsFocusId,
                  appId: detailsAppId,
                },
              }),
            );
          },
        },
      });

      mountedComponents.set(content, component);
    } catch (e) {
      console.error(
        "[FocusModeActivationRenderer] Error mounting component:",
        e,
      );
      content.innerHTML = `<span style="color: var(--color-grey-50); font-size: 12px;">Focus mode: ${focusModeName}</span>`;
    }
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    const focusModeName =
      attrs.focus_mode_name || attrs.focus_id || "Focus mode";
    return `[Focus: ${focusModeName}]`;
  }

  destroy(context: EmbedRenderContext): void {
    const { content } = context;
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[FocusModeActivationRenderer] Error unmounting on destroy:",
          e,
        );
      }
      mountedComponents.delete(content);
    }
  }
}
