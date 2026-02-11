// Generic group handler system for embed grouping
// Provides extensible interfaces for different embed type grouping behaviors

import { EmbedNodeAttributes } from "./types";

/**
 * Generate a deterministic group ID based on the first item's ID.
 * This is CRITICAL for streaming updates - when a group grows from N to N+1 items,
 * the group ID must remain stable so TipTap can match and update the existing node
 * instead of destroying and recreating it (which breaks the UI during streaming).
 *
 * We use the FIRST item's ID because groups grow by appending items at the end.
 * This means the first item is always the anchor for the group identity.
 *
 * @param embedNodes - Array of embed nodes being grouped
 * @returns A deterministic group ID based on the first item
 */
function generateDeterministicGroupId(
  embedNodes: EmbedNodeAttributes[],
): string {
  if (embedNodes.length === 0) {
    // Fallback for empty groups (shouldn't happen in practice)
    return "group_empty_" + Date.now();
  }

  // Use the first item's ID as the basis for the group ID
  // This ensures the group ID remains stable as more items are added
  const firstItemId = embedNodes[0].id || embedNodes[0].contentRef || "";

  // Prefix with 'group_' to make it clear this is a group node
  return `group_${firstItemId}`;
}

/**
 * Interface for handling specific embed type grouping behavior
 */
export interface EmbedGroupHandler {
  /**
   * The embed type this handler manages (e.g., 'website', 'code', 'doc')
   */
  embedType: string;

  /**
   * Determine if two embed nodes can be grouped together
   * @param nodeA - First embed node
   * @param nodeB - Second embed node
   * @returns true if they can be grouped, false otherwise
   */
  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean;

  /**
   * Create a group embed node from multiple individual embed nodes
   * @param embedNodes - Array of individual embed nodes to group
   * @returns Group embed node attributes
   */
  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes;

  /**
   * Handle backspace behavior for group nodes
   * @param groupAttrs - The group embed node attributes
   * @returns Backspace action result
   */
  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult;

  /**
   * Convert group back to markdown (for serialization)
   * @param groupAttrs - The group embed node attributes
   * @returns Markdown representation
   */
  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string;
}

/**
 * Result of a group backspace operation
 */
export interface GroupBackspaceResult {
  /**
   * Action type to perform
   */
  action: "delete-group" | "split-group" | "convert-to-text";

  /**
   * Content to replace the group with (for TipTap)
   */
  replacementContent?: any[];

  /**
   * Plain text to replace with (fallback)
   */
  replacementText?: string;
}

/**
 * Web website embed group handler
 */
export class WebWebsiteGroupHandler implements EmbedGroupHandler {
  embedType = "web-website";

  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    // Web website embeds can only be grouped with other web website embeds
    return nodeA.type === "web-website" && nodeB.type === "web-website";
  }

  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes {
    // Generate deterministic group ID BEFORE sorting (based on first item in original order)
    // This is critical for streaming updates - the group ID must remain stable
    const groupId = generateDeterministicGroupId(embedNodes);

    // Sort according to status: processing first, then finished
    const sortedEmbeds = [...embedNodes].sort((a, b) => {
      if (a.status === "processing" && b.status !== "processing") return -1;
      if (a.status !== "processing" && b.status === "processing") return 1;
      return 0; // Keep original order for same status
    });

    // Extract only the essential, serializable attributes for groupedItems
    const serializableGroupedItems = sortedEmbeds.map((embed) => ({
      id: embed.id,
      type: embed.type as any, // Type assertion to avoid complex type issues
      status: embed.status as "processing" | "finished", // Type assertion for status
      contentRef: embed.contentRef,
      url: embed.url,
      title: embed.title,
      description: embed.description,
      favicon: embed.favicon,
      image: embed.image,
    }));

    console.log(
      "[WebWebsiteGroupHandler] Creating group with items:",
      serializableGroupedItems,
    );

    const result = {
      id: groupId,
      type: "web-website-group",
      status: "finished",
      contentRef: null,
      groupedItems: serializableGroupedItems,
      groupCount: sortedEmbeds.length,
    } as EmbedNodeAttributes;

    console.log("[WebWebsiteGroupHandler] Created group:", result);
    return result;
  }

  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult {
    const groupedItems = groupAttrs.groupedItems || [];

    if (groupedItems.length > 2) {
      // For groups with >2 items: keep remaining items grouped, show last one in edit mode
      const remainingItems = groupedItems.slice(0, -1);
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create a new group with the remaining items
      const remainingGroupAttrs = this.createGroup(remainingItems);

      // Build the replacement content: group + editable text
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: remainingGroupAttrs,
        },
        { type: "text", text: " " }, // Space between group and editable text
        { type: "text", text: lastItem.url || "" }, // Last item as editable text
        { type: "hardBreak" }, // Hard break after editable text
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 2) {
      // For groups with 2 items: split into individual items, show last one in edit mode
      const firstItem = groupedItems[0];
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create individual embed nodes for the remaining items
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: {
            ...firstItem,
            type: "web-website", // Convert back to individual web website embed
          },
        },
        { type: "text", text: " " }, // Space between embeds
        { type: "text", text: lastItem.url || "" }, // Last item as editable text
        { type: "hardBreak" }, // Hard break after editable text
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 1) {
      // Single item group - convert to URL for editing
      const singleItem = groupedItems[0];
      return {
        action: "convert-to-text",
        replacementText: (singleItem.url || "") + "\n\n",
      };
    }

    // Empty group - just delete
    return {
      action: "delete-group",
    };
  }

  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    // Serialize web website groups back to individual json_embed blocks separated by newlines
    const groupedItems = groupAttrs.groupedItems || [];
    return groupedItems
      .map((item) => {
        const websiteData: any = {
          type: "website",
          url: item.url,
        };

        // Add optional metadata if available
        if (item.title) websiteData.title = item.title;
        if (item.description) websiteData.description = item.description;
        if (item.favicon) websiteData.favicon = item.favicon;
        if (item.image) websiteData.image = item.image;

        const jsonContent = JSON.stringify(websiteData, null, 2);
        return `\`\`\`json_embed\n${jsonContent}\n\`\`\``;
      })
      .join("\n\n");
  }
}

/**
 * Videos video embed group handler
 */
export class VideosVideoGroupHandler implements EmbedGroupHandler {
  embedType = "videos-video";

  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    // Videos video embeds can be grouped together
    return nodeA.type === "videos-video" && nodeB.type === "videos-video";
  }

  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes {
    // Generate deterministic group ID BEFORE sorting (based on first item in original order)
    const groupId = generateDeterministicGroupId(embedNodes);

    // Sort according to status: processing first, then finished
    const sortedEmbeds = [...embedNodes].sort((a, b) => {
      if (a.status === "processing" && b.status !== "processing") return -1;
      if (a.status !== "processing" && b.status === "processing") return 1;
      return 0; // Keep original order for same status
    });

    // Extract only the essential, serializable attributes for groupedItems
    const serializableGroupedItems = sortedEmbeds.map((embed) => ({
      id: embed.id,
      type: embed.type,
      status: embed.status,
      contentRef: embed.contentRef,
      url: embed.url,
      title: embed.title,
    }));

    return {
      id: groupId,
      type: "videos-video-group",
      status: "finished",
      contentRef: null,
      groupedItems: serializableGroupedItems,
      groupCount: sortedEmbeds.length,
    };
  }

  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult {
    const groupedItems = groupAttrs.groupedItems || [];

    if (groupedItems.length > 2) {
      // For groups with >2 items: keep remaining items grouped, show last one in edit mode
      const remainingItems = groupedItems.slice(0, -1);
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create a new group with the remaining items
      const remainingGroupAttrs = this.createGroup(remainingItems);

      // Build the replacement content: group + editable text
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: remainingGroupAttrs,
        },
        { type: "text", text: " " }, // Space between group and editable text
        { type: "text", text: lastItem.url || "" }, // Last item as editable text
        { type: "hardBreak" }, // Hard break after editable text
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 2) {
      // For groups with 2 items: split into individual items, show last one in edit mode
      const firstItem = groupedItems[0];
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create individual embed nodes for the remaining items
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: {
            ...firstItem,
            type: "videos-video", // Convert back to individual videos video embed
          },
        },
        { type: "text", text: " " }, // Space between embeds
        { type: "text", text: lastItem.url || "" }, // Last item as editable text
        { type: "hardBreak" }, // Hard break after editable text
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 1) {
      // Single item group - convert to URL for editing
      const singleItem = groupedItems[0];
      return {
        action: "convert-to-text",
        replacementText: (singleItem.url || "") + "\n\n",
      };
    }

    // Empty group - just delete
    return {
      action: "delete-group",
    };
  }

  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    // Serialize videos video groups back to individual URLs separated by spaces
    const groupedItems = groupAttrs.groupedItems || [];
    return groupedItems
      .map((item) => item.url || "")
      .filter((url) => url)
      .join(" ");
  }
}

/**
 * Code code embed group handler
 */
export class CodeCodeGroupHandler implements EmbedGroupHandler {
  embedType = "code-code";

  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    // Code code embeds can be grouped together regardless of language
    return nodeA.type === "code-code" && nodeB.type === "code-code";
  }

  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes {
    // Generate deterministic group ID BEFORE sorting (based on first item in original order)
    const groupId = generateDeterministicGroupId(embedNodes);

    const sortedEmbeds = [...embedNodes].sort((a, b) => {
      if (a.status === "processing" && b.status !== "processing") return -1;
      if (a.status !== "processing" && b.status === "processing") return 1;
      return 0;
    });

    // Extract only the essential, serializable attributes for groupedItems
    const serializableGroupedItems = sortedEmbeds.map((embed) => ({
      id: embed.id,
      type: embed.type,
      status: embed.status,
      contentRef: embed.contentRef,
      language: embed.language,
      filename: embed.filename,
    }));

    return {
      id: groupId,
      type: "code-code-group",
      status: "finished",
      contentRef: null,
      groupedItems: serializableGroupedItems,
      groupCount: sortedEmbeds.length,
    };
  }

  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult {
    const groupedItems = groupAttrs.groupedItems || [];

    if (groupedItems.length > 2) {
      // For groups with >2 items: keep remaining items grouped, show last one in edit mode
      const remainingItems = groupedItems.slice(0, -1);
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create a new group with the remaining items
      const remainingGroupAttrs = this.createGroup(remainingItems);

      // Convert last item to code fence for editing
      const language = lastItem.language || "";
      const filename = lastItem.filename ? `:${lastItem.filename}` : "";
      const lastItemMarkdown = `\`\`\`${language}${filename}\n\`\`\``;

      // Build the replacement content: group + editable text
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: remainingGroupAttrs,
        },
        { type: "text", text: "\n\n" }, // Newlines between group and editable text
        { type: "text", text: lastItemMarkdown },
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 2) {
      // For groups with 2 items: split into individual items, show last one in edit mode
      const firstItem = groupedItems[0];
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create individual embed nodes for the remaining items
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: {
            ...firstItem,
            type: "code-code",
          },
        },
        { type: "text", text: "\n\n" }, // Newlines between embeds
        {
          type: "text",
          text: `\`\`\`${lastItem.language || ""}${lastItem.filename ? ":" + lastItem.filename : ""}\n\`\`\``,
        },
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 1) {
      const singleItem = groupedItems[0];
      const language = singleItem.language || "";
      const filename = singleItem.filename ? `:${singleItem.filename}` : "";
      return {
        action: "convert-to-text",
        replacementText: `\`\`\`${language}${filename}\n\`\`\`\n\n`,
      };
    }

    return { action: "delete-group" };
  }

  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    const groupedItems = groupAttrs.groupedItems || [];
    return groupedItems
      .map((item) => {
        const language = item.language || "";
        const filename = item.filename ? `:${item.filename}` : "";
        return `\`\`\`${language}${filename}\n\`\`\``;
      })
      .join("\n\n");
  }
}

/**
 * Docs doc embed group handler
 */
export class DocsDocGroupHandler implements EmbedGroupHandler {
  embedType = "docs-doc";

  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    // Docs doc embeds can always be grouped together
    return nodeA.type === "docs-doc" && nodeB.type === "docs-doc";
  }

  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes {
    // Generate deterministic group ID BEFORE sorting (based on first item in original order)
    const groupId = generateDeterministicGroupId(embedNodes);

    const sortedEmbeds = [...embedNodes].sort((a, b) => {
      if (a.status === "processing" && b.status !== "processing") return -1;
      if (a.status !== "processing" && b.status === "processing") return 1;
      return 0;
    });

    // Extract only the essential, serializable attributes for groupedItems
    const serializableGroupedItems = sortedEmbeds.map((embed) => ({
      id: embed.id,
      type: embed.type,
      status: embed.status,
      contentRef: embed.contentRef,
      title: embed.title,
    }));

    return {
      id: groupId,
      type: "docs-doc-group",
      status: "finished",
      contentRef: null,
      groupedItems: serializableGroupedItems,
      groupCount: sortedEmbeds.length,
    };
  }

  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult {
    const groupedItems = groupAttrs.groupedItems || [];

    if (groupedItems.length > 2) {
      // For groups with >2 items: keep remaining items grouped, show last one in edit mode
      const remainingItems = groupedItems.slice(0, -1);
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create a new group with the remaining items
      const remainingGroupAttrs = this.createGroup(remainingItems);

      // Convert last item to document_html fence for editing
      const title = lastItem.title
        ? `<!-- title: "${lastItem.title}" -->\n`
        : "";
      const lastItemMarkdown = `\`\`\`document_html\n${title}\`\`\``;

      // Build the replacement content: group + editable text
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: remainingGroupAttrs,
        },
        { type: "text", text: "\n\n" }, // Newlines between group and editable text
        { type: "text", text: lastItemMarkdown },
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 2) {
      // For groups with 2 items: split into individual items, show last one in edit mode
      const firstItem = groupedItems[0];
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create individual embed nodes for the remaining items
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: {
            ...firstItem,
            type: "docs-doc",
          },
        },
        { type: "text", text: "\n\n" }, // Newlines between embeds
        {
          type: "text",
          text: `\`\`\`document_html\n${lastItem.title ? `<!-- title: "${lastItem.title}" -->\n` : ""}\`\`\``,
        },
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 1) {
      const singleItem = groupedItems[0];
      const title = singleItem.title
        ? `<!-- title: "${singleItem.title}" -->\n`
        : "";
      return {
        action: "convert-to-text",
        replacementText: `\`\`\`document_html\n${title}\`\`\`\n\n`,
      };
    }

    return { action: "delete-group" };
  }

  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    const groupedItems = groupAttrs.groupedItems || [];
    return groupedItems
      .map((item) => {
        const title = item.title ? `<!-- title: "${item.title}" -->\n` : "";
        return `\`\`\`document_html\n${title}\`\`\``;
      })
      .join("\n\n");
  }
}

/**
 * Sheets sheet embed group handler
 */
export class SheetsSheetGroupHandler implements EmbedGroupHandler {
  embedType = "sheets-sheet";

  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    // Sheets sheet embeds can always be grouped together
    return nodeA.type === "sheets-sheet" && nodeB.type === "sheets-sheet";
  }

  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes {
    // Generate deterministic group ID BEFORE sorting (based on first item in original order)
    const groupId = generateDeterministicGroupId(embedNodes);

    const sortedEmbeds = [...embedNodes].sort((a, b) => {
      if (a.status === "processing" && b.status !== "processing") return -1;
      if (a.status !== "processing" && b.status === "processing") return 1;
      return 0;
    });

    // Extract only the essential, serializable attributes for groupedItems
    const serializableGroupedItems = sortedEmbeds.map((embed) => ({
      id: embed.id,
      type: embed.type,
      status: embed.status,
      contentRef: embed.contentRef,
      title: embed.title,
      rows: embed.rows,
      cols: embed.cols,
    }));

    return {
      id: groupId,
      type: "sheets-sheet-group",
      status: "finished",
      contentRef: null,
      groupedItems: serializableGroupedItems,
      groupCount: sortedEmbeds.length,
    };
  }

  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult {
    const groupedItems = groupAttrs.groupedItems || [];

    if (groupedItems.length > 2) {
      // For groups with >2 items: keep remaining items grouped, show last one in edit mode
      const remainingItems = groupedItems.slice(0, -1);
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create a new group with the remaining items
      const remainingGroupAttrs = this.createGroup(remainingItems);

      // Convert last item to table markdown for editing
      const title = lastItem.title
        ? `<!-- title: "${lastItem.title}" -->\n`
        : "";
      const lastItemMarkdown = `${title}| Column 1 | Column 2 |\n|----------|----------|\n| Data     | Data     |`;

      // Build the replacement content: group + editable text
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: remainingGroupAttrs,
        },
        { type: "text", text: "\n\n" }, // Newlines between group and editable text
        { type: "text", text: lastItemMarkdown },
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 2) {
      // For groups with 2 items: split into individual items, show last one in edit mode
      const firstItem = groupedItems[0];
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create individual embed nodes for the remaining items
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: {
            ...firstItem,
            type: "sheets-sheet",
          },
        },
        { type: "text", text: "\n\n" }, // Newlines between embeds
        {
          type: "text",
          text: `${lastItem.title ? `<!-- title: "${lastItem.title}" -->\n` : ""}| Column 1 | Column 2 |\n|----------|----------|\n| Data     | Data     |`,
        },
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 1) {
      const singleItem = groupedItems[0];
      const title = singleItem.title
        ? `<!-- title: "${singleItem.title}" -->\n`
        : "";
      return {
        action: "convert-to-text",
        replacementText: `${title}| Column 1 | Column 2 |\n|----------|----------|\n| Data     | Data     |\n\n`,
      };
    }

    return { action: "delete-group" };
  }

  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    const groupedItems = groupAttrs.groupedItems || [];
    return groupedItems
      .map((item) => {
        const title = item.title ? `<!-- title: "${item.title}" -->\n` : "";
        return `${title}| Column 1 | Column 2 |\n|----------|----------|\n| Data     | Data     |`;
      })
      .join("\n\n");
  }
}

/**
 * App skill use embed group handler
 * Groups consecutive app_skill_use embeds (e.g., multiple search requests) for horizontal scrolling
 */
export class AppSkillUseGroupHandler implements EmbedGroupHandler {
  embedType = "app-skill-use";

  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    // App skill use embeds can only be grouped if they have the SAME app_id AND skill_id
    // This ensures that different skill types (e.g., web.search vs code.get_docs) are NOT grouped together
    // Each unique app_id+skill_id combination should be in its own group
    if (nodeA.type !== "app-skill-use" || nodeB.type !== "app-skill-use") {
      return false;
    }

    // CRITICAL: If either embed is missing app_id or skill_id, they CANNOT be grouped.
    // This prevents undefined === undefined from incorrectly grouping different skill types together.
    // Without this check, web.search and code.get_docs would be grouped together when their
    // app_id/skill_id haven't been resolved yet from the EmbedStore.
    if (!nodeA.app_id || !nodeA.skill_id || !nodeB.app_id || !nodeB.skill_id) {
      console.debug(
        "[AppSkillUseGroupHandler] canGroup: Missing app_id or skill_id, cannot group:",
        {
          nodeA_app_id: nodeA.app_id,
          nodeA_skill_id: nodeA.skill_id,
          nodeB_app_id: nodeB.app_id,
          nodeB_skill_id: nodeB.skill_id,
        },
      );
      return false;
    }

    // Both must have the same app_id and skill_id to be grouped
    const sameAppId = nodeA.app_id === nodeB.app_id;
    const sameSkillId = nodeA.skill_id === nodeB.skill_id;

    console.debug("[AppSkillUseGroupHandler] canGroup check:", {
      nodeA_app_id: nodeA.app_id,
      nodeA_skill_id: nodeA.skill_id,
      nodeB_app_id: nodeB.app_id,
      nodeB_skill_id: nodeB.skill_id,
      sameAppId,
      sameSkillId,
      canGroup: sameAppId && sameSkillId,
    });

    return sameAppId && sameSkillId;
  }

  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes {
    // CRITICAL: Filter out error embeds - they should not be shown to users
    // Failed skill executions are hidden from the user experience
    const validEmbeds = embedNodes.filter((embed) => {
      if (embed.status === "error") {
        console.debug(
          `[AppSkillUseGroupHandler] Filtering out error embed from group:`,
          embed.id,
        );
        return false;
      }
      return true;
    });

    // If all embeds were filtered out, return an empty/hidden group
    if (validEmbeds.length === 0) {
      console.debug(
        "[AppSkillUseGroupHandler] All embeds filtered out - creating empty group",
      );
      return {
        id: generateDeterministicGroupId(embedNodes),
        type: "app-skill-use-group",
        status: "finished",
        contentRef: null,
        groupedItems: [],
        groupCount: 0,
      } as EmbedNodeAttributes;
    }

    // Generate deterministic group ID BEFORE sorting (based on first item in original order)
    // This is critical for streaming updates - the group ID must remain stable
    const groupId = generateDeterministicGroupId(validEmbeds);

    // Sort according to status: processing first, then finished
    const sortedEmbeds = [...validEmbeds].sort((a, b) => {
      if (a.status === "processing" && b.status !== "processing") return -1;
      if (a.status !== "processing" && b.status === "processing") return 1;
      return 0; // Keep original order for same status
    });

    // Extract serializable attributes for groupedItems
    // CRITICAL: Preserve app_id, skill_id, query, and provider so that GroupRenderer
    // can render the correct Svelte component during streaming, even before
    // the full embed data arrives from the server via WebSocket.
    // Without these, the group items will render as empty/generic fallback HTML.
    const serializableGroupedItems = sortedEmbeds.map((embed) => ({
      id: embed.id,
      type: embed.type as any,
      status: embed.status as "processing" | "finished",
      contentRef: embed.contentRef,
      // Preserve app skill metadata for rendering during streaming
      app_id: embed.app_id,
      skill_id: embed.skill_id,
      query: embed.query,
      provider: embed.provider,
    }));

    console.log(
      "[AppSkillUseGroupHandler] Creating group with items:",
      serializableGroupedItems,
    );

    // CRITICAL: Propagate app_id and skill_id to the group-level attrs.
    // The scattered grouping algorithm (groupScatteredAppSkillEmbeds) checks
    // attrs.app_id && attrs.skill_id on group nodes to merge them with
    // additional scattered individual embeds. Without these at the group level,
    // existing groups won't be detected for merging.
    // Also propagate query and provider for rendering purposes.
    const firstEmbed = validEmbeds[0];
    const result = {
      id: groupId,
      type: "app-skill-use-group",
      status: "finished",
      contentRef: null,
      groupedItems: serializableGroupedItems,
      groupCount: sortedEmbeds.length,
      app_id: firstEmbed.app_id,
      skill_id: firstEmbed.skill_id,
      query: firstEmbed.query,
      provider: firstEmbed.provider,
    } as EmbedNodeAttributes;

    console.log("[AppSkillUseGroupHandler] Created group:", result);
    return result;
  }

  handleGroupBackspace(groupAttrs: EmbedNodeAttributes): GroupBackspaceResult {
    const groupedItems = groupAttrs.groupedItems || [];

    if (groupedItems.length > 2) {
      // For groups with >2 items: keep remaining items grouped, show last one in edit mode
      const remainingItems = groupedItems.slice(0, -1);
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create a new group with the remaining items
      const remainingGroupAttrs = this.createGroup(remainingItems);

      // Build the replacement content: group + editable text
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: remainingGroupAttrs,
        },
        { type: "text", text: " " }, // Space between group and editable text
        { type: "text", text: "" }, // Last item removed (can't edit app_skill_use as text)
        { type: "hardBreak" }, // Hard break after editable text
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 2) {
      // For groups with 2 items: split into individual items
      const firstItem = groupedItems[0];
      const lastItem = groupedItems[groupedItems.length - 1];

      // Create individual embed nodes for both items
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: {
            ...firstItem,
            type: "app-skill-use", // Convert back to individual app-skill-use embed
          },
        },
        { type: "text", text: " " }, // Space between embeds
        {
          type: "embed",
          attrs: {
            ...lastItem,
            type: "app-skill-use", // Convert back to individual app-skill-use embed
          },
        },
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    } else if (groupedItems.length === 1) {
      // Single item group - convert back to individual embed
      const singleItem = groupedItems[0];
      const replacementContent: any[] = [
        {
          type: "embed",
          attrs: {
            ...singleItem,
            type: "app-skill-use",
          },
        },
      ];

      return {
        action: "split-group",
        replacementContent,
      };
    }

    // Empty group - just delete
    return {
      action: "delete-group",
    };
  }

  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    // Serialize app_skill_use groups back to individual JSON embed blocks
    const groupedItems = groupAttrs.groupedItems || [];
    return groupedItems
      .map((item) => {
        // Extract embed_id from contentRef (format: "embed:...")
        const embedId = item.contentRef?.replace("embed:", "") || "";
        const embedData: any = {
          type: "app_skill_use",
          embed_id: embedId,
        };

        const jsonContent = JSON.stringify(embedData, null, 2);
        return `\`\`\`json\n${jsonContent}\n\`\`\``;
      })
      .join("\n\n");
  }
}

/**
 * Registry of group handlers
 */
export class GroupHandlerRegistry {
  private handlers = new Map<string, EmbedGroupHandler>();

  constructor() {
    // Register supported embed type handlers
    this.register(new WebWebsiteGroupHandler());
    this.register(new VideosVideoGroupHandler());
    this.register(new CodeCodeGroupHandler());
    this.register(new DocsDocGroupHandler());
    this.register(new SheetsSheetGroupHandler());
    this.register(new AppSkillUseGroupHandler());
  }

  /**
   * Register a new group handler
   */
  register(handler: EmbedGroupHandler): void {
    this.handlers.set(handler.embedType, handler);
    console.debug(
      `[GroupHandlerRegistry] Registered handler for embed type: ${handler.embedType}`,
    );
  }

  /**
   * Get handler for a specific embed type
   */
  getHandler(embedType: string): EmbedGroupHandler | null {
    return this.handlers.get(embedType) || null;
  }

  /**
   * Get handler for a group type (e.g., 'website-group' -> 'website' handler)
   */
  getHandlerForGroupType(groupType: string): EmbedGroupHandler | null {
    // Extract base type from group type (e.g., 'website-group' -> 'website')
    const baseType = groupType.replace("-group", "");
    return this.getHandler(baseType);
  }

  /**
   * Check if two embed nodes can be grouped together
   */
  canGroup(nodeA: EmbedNodeAttributes, nodeB: EmbedNodeAttributes): boolean {
    const handler = this.getHandler(nodeA.type);
    return handler ? handler.canGroup(nodeA, nodeB) : false;
  }

  /**
   * Create a group from multiple embed nodes
   */
  createGroup(embedNodes: EmbedNodeAttributes[]): EmbedNodeAttributes | null {
    if (embedNodes.length === 0) return null;

    const handler = this.getHandler(embedNodes[0].type);
    return handler ? handler.createGroup(embedNodes) : null;
  }

  /**
   * Handle backspace for a group node
   */
  handleGroupBackspace(
    groupAttrs: EmbedNodeAttributes,
  ): GroupBackspaceResult | null {
    const handler = this.getHandlerForGroupType(groupAttrs.type);
    return handler ? handler.handleGroupBackspace(groupAttrs) : null;
  }

  /**
   * Convert group to markdown
   */
  groupToMarkdown(groupAttrs: EmbedNodeAttributes): string {
    const handler = this.getHandlerForGroupType(groupAttrs.type);
    return handler ? handler.groupToMarkdown(groupAttrs) : "";
  }
}

// Export singleton instance
export const groupHandlerRegistry = new GroupHandlerRegistry();
