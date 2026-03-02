import type { Editor } from "@tiptap/core";
// TODO: Find correct import for ProseMirrorNode type
// import type { Node as ProseMirrorNode } from '@tiptap/pm/model';
import { getLanguageFromFilename } from "./utils"; // Assuming utils are accessible
import { cancelUpload, deleteDraftEmbed } from "./embedHandlers";

// Define a type for the selected node state if not already defined globally
export interface SelectedNodeState {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  node: Record<string, any>; // ProseMirror node — typed loosely to avoid pulling in @tiptap/pm
  pos: number;
}

/**
 * Handles the interaction (press/click) on an embed element.
 * Finds the corresponding node in the editor and prepares data for the menu.
 *
 * @returns An object containing menu position, embed ID, menu type, and selected node, or null if failed.
 */
export function handleEmbedInteraction(
  event: CustomEvent,
  editor: Editor,
  embedId: string,
): {
  menuX: number;
  menuY: number;
  selectedEmbedId: string;
  menuType: "default" | "pdf" | "web";
  selectedNode: SelectedNodeState;
} | null {
  let foundNode: SelectedNodeState | null = null;

  // Find the node in the editor document based on the embedId attribute
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  editor.state.doc.descendants((node: Record<string, any>, pos: number) => {
    if (node.attrs?.id === embedId) {
      foundNode = { node, pos };
      return false; // Stop searching once found
    }
    return true; // Continue searching
  });

  if (!foundNode) {
    console.warn(`[MenuHandlers] Node not found for embedId: ${embedId}`);
    return null;
  }

  const element = document.getElementById(event.detail.elementId);
  if (!element) {
    console.warn(`[MenuHandlers] Element not found for embedId: ${embedId}`);
    return null;
  }

  const rect = element.getBoundingClientRect();
  const container = element.closest(".message-field"); // Adjust selector if needed
  if (!container) {
    console.warn(`[MenuHandlers] Container element not found.`);
    return null;
  }

  // Calculate menu position relative to the container
  const menuX =
    rect.left - container.getBoundingClientRect().left + rect.width / 2;
  const menuY = rect.top - container.getBoundingClientRect().top;

  // Determine menu type based on the node
  let menuType: "default" | "pdf" | "web" = "default";
  if (foundNode.node.type.name === "webPreview") {
    menuType = "web";
  } else if (foundNode.node.attrs?.type === "pdf") {
    menuType = "pdf";
  }

  return {
    menuX,
    menuY,
    selectedEmbedId: embedId,
    menuType,
    selectedNode: foundNode,
  };
}

/**
 * Handles actions triggered from the embed context menu.
 */
export async function handleMenuAction(
  action: string,
  selectedNodeState: SelectedNodeState | null,
  editor: Editor,
  dispatch: (type: string, detail?: unknown) => void,
  selectedEmbedId: string | null, // Pass selectedEmbedId for UI feedback
): Promise<void> {
  if (!selectedNodeState) return;

  const { node, pos } = selectedNodeState;

  switch (action) {
    case "delete":
      // Cancel any in-flight upload first (no-op if already completed).
      if (node.attrs?.id) {
        cancelUpload(node.attrs.id);
      }
      // Delete the node from the editor.
      editor
        .chain()
        .focus()
        .deleteRange({ from: pos, to: pos + node.nodeSize })
        .run();
      // For file upload embeds (image/pdf/recording), notify the server to delete
      // the upload_files record + S3 variants + decrement storage_used_bytes.
      // Fire-and-forget — server handles gracefully if record doesn't exist.
      // IMPORTANT: The server's upload_files table indexes records by the
      // server-assigned UUID (node.attrs.uploadEmbedId), NOT the local client UUID
      // (node.attrs.id). Use uploadEmbedId when available so the server can find and
      // delete the record. Fall back to the local id only if upload hasn't completed
      // yet (uploadEmbedId is null/undefined in that case).
      if (
        node.attrs?.id &&
        (node.attrs.type === "image" ||
          node.attrs.type === "pdf" ||
          node.attrs.type === "recording")
      ) {
        deleteDraftEmbed(node.attrs.uploadEmbedId ?? node.attrs.id);
      }
      break;

    case "download":
      if (node.attrs.src) {
        const a = document.createElement("a");
        a.href = node.attrs.src;
        a.download = node.attrs.filename || "download"; // Provide a default filename
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      } else {
        console.warn(
          "[MenuHandlers] Download failed: No src attribute found on node.",
          node,
        );
      }
      break;

    case "view":
      if (node.type.name === "codeEmbed") {
        try {
          const response = await fetch(node.attrs.src);
          if (!response.ok)
            throw new Error(`HTTP error! status: ${response.status}`);
          const code = await response.text();
          dispatch("codefullscreen", {
            code,
            filename: node.attrs.filename,
            language:
              node.attrs.language ||
              getLanguageFromFilename(node.attrs.filename),
          });
        } catch (error) {
          console.error(
            "[MenuHandlers] Error loading code content for view:",
            error,
          );
          alert("Failed to load code content."); // Inform user
        }
      } else {
        // Handle web previews (YouTube or generic URLs) and other file types
        const urlToOpen = node.attrs.isYouTube
          ? `https://www.youtube.com/watch?v=${node.attrs.videoId}`
          : node.attrs.url || node.attrs.src; // Use url for webPreview, src for others

        if (urlToOpen) {
          window.open(urlToOpen, "_blank", "noopener,noreferrer");
        } else {
          console.warn(
            "[MenuHandlers] View failed: No URL or src attribute found.",
            node,
          );
        }
      }
      break;

    case "copy": {
      const urlToCopy = node.attrs.isYouTube
        ? `https://www.youtube.com/watch?v=${node.attrs.videoId}`
        : node.attrs.url || node.attrs.src;

      if (urlToCopy) {
        try {
          await navigator.clipboard.writeText(urlToCopy);
          // Provide visual feedback
          const element = document.getElementById(`embed-${selectedEmbedId}`); // Use the passed embedId
          if (element) {
            element.classList.add("show-copied"); // Add class for feedback
            setTimeout(() => element.classList.remove("show-copied"), 2000); // Remove after 2s
          }
        } catch (err) {
          console.error("[MenuHandlers] Failed to copy URL:", err);
          alert("Failed to copy URL to clipboard."); // Inform user
        }
      } else {
        console.warn(
          "[MenuHandlers] Copy failed: No URL or src attribute found.",
          node,
        );
      }
      break;
    }
  }
}
