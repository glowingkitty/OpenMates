// Generic embed grouping functionality
// Handles grouping consecutive embeds at the document level.
// For app-skill-use embeds: ALL consecutive ones are grouped together regardless of app_id/skill_id.
// For other types: consecutive same-type embeds are grouped together.
// Also handles merging non-consecutive (scattered) app-skill-use embeds into one group.

import { groupHandlerRegistry } from "./groupHandlers";

/**
 * Group consecutive embeds in a TipTap document structure.
 * For app-skill-use embeds: groups ALL consecutive ones together (regardless of app_id/skill_id).
 * For other types: groups consecutive same-type embeds together.
 * @param doc - TipTap document with individual embed nodes
 * @returns TipTap document with grouped embeds
 */
export function groupConsecutiveEmbedsInDocument(doc: any): any {
  if (!doc || !doc.content) {
    return doc;
  }

  console.debug("[groupConsecutiveEmbedsInDocument] Processing document");

  // First, group embeds within each paragraph
  const contentWithParagraphGrouping = doc.content.map((contentNode: any) => {
    if (contentNode.type === "paragraph" && contentNode.content) {
      return groupConsecutiveEmbedsInParagraph(contentNode);
    }
    return contentNode;
  });

  // Then, group consecutive paragraphs that contain embeds of the same type
  // This handles cases where JSON code blocks are in separate paragraphs
  const consecutiveGroupedContent = groupConsecutiveEmbedParagraphs(
    contentWithParagraphGrouping,
  );

  // Finally, group non-consecutive (scattered) app-skill-use embeds into one group.
  // This handles the common case where the LLM outputs text between tool calls,
  // breaking consecutive grouping but the embeds should still be grouped.
  // Example: Search1 → "Let me search more" → ImageSearch1 → Search2
  // All skill embeds are merged into one group even though text separates them.
  const scatteredGroupedContent = groupScatteredAppSkillEmbeds(
    consecutiveGroupedContent,
  );

  // Post-processing: Remove empty paragraphs that sit immediately after an embed-only
  // paragraph. These come from blank lines in the markdown between the embed code fence
  // closing ``` and the next text content. They create an unwanted visual gap in read mode.
  const modifiedContent = removeEmptyParagraphsAfterEmbeds(
    scatteredGroupedContent,
  );

  return {
    ...doc,
    content: modifiedContent,
  };
}

/**
 * Remove empty paragraphs that immediately follow an embed-only paragraph.
 *
 * When a user sends "image + text", the markdown serializer produces:
 *   ```json\n{"type":"image","embed_id":"..."}\n```\n\ndescribe the image
 *
 * The blank line between the closing ``` and the text causes markdown-it to emit
 * an empty paragraph node between the embed paragraph and the text paragraph.
 * This empty paragraph, combined with CSS margins, creates a large visual gap
 * in ReadOnlyMessage. This function strips those empty spacer paragraphs.
 *
 * @param content - Array of top-level TipTap document nodes
 * @returns Filtered content without empty paragraphs trailing embeds
 */
function removeEmptyParagraphsAfterEmbeds(content: any[]): any[] {
  if (content.length <= 1) return content;

  const result: any[] = [];

  for (let i = 0; i < content.length; i++) {
    const node = content[i];
    const prevNode = result[result.length - 1];

    // Check if previous node is an embed-only paragraph (single embed child)
    const prevIsEmbed =
      prevNode?.type === "paragraph" &&
      Array.isArray(prevNode.content) &&
      prevNode.content.length === 1 &&
      prevNode.content[0]?.type === "embed";

    // Check if current node is an empty paragraph (no content or only whitespace/hardBreaks)
    const isEmptyParagraph =
      node?.type === "paragraph" &&
      (!node.content ||
        node.content.length === 0 ||
        node.content.every((child: any) => {
          if (!child) return true;
          if (child.type === "hardBreak") return true;
          if (child.type === "text") return (child.text || "").trim() === "";
          return false;
        }));

    // Skip empty paragraphs that immediately follow an embed paragraph
    if (prevIsEmbed && isEmptyParagraph) {
      console.debug(
        "[removeEmptyParagraphsAfterEmbeds] Removing empty paragraph after embed",
      );
      continue;
    }

    result.push(node);
  }

  return result;
}

/**
 * Group consecutive paragraphs that contain embeds.
 * For app-skill-use embeds: groups all consecutive ones regardless of app_id/skill_id.
 * For other types: groups consecutive same-type embeds.
 * @param content - Array of content nodes (paragraphs, etc.)
 * @returns Modified content with grouped embed paragraphs
 */
function groupConsecutiveEmbedParagraphs(content: any[]): any[] {
  const newContent: any[] = [];
  let currentGroup: any[] = [];
  let currentGroupType: string | null = null;
  let pendingSpacerParagraphs: any[] = [];

  const isEmbedParagraph = (node: any): boolean =>
    node?.type === "paragraph" &&
    Array.isArray(node.content) &&
    node.content.length === 1 &&
    node.content[0]?.type === "embed";

  const isIgnorableParagraph = (node: any): boolean => {
    if (node?.type !== "paragraph") return false;
    if (!node.content || node.content.length === 0) return true;
    // Consider paragraphs that contain only whitespace text and/or line breaks as "empty"
    return node.content.every((child: any) => {
      if (!child) return true;
      if (child.type === "hardBreak") return true;
      if (child.type === "text") return (child.text || "").trim() === "";
      return false;
    });
  };

  for (let i = 0; i < content.length; i++) {
    const node = content[i];

    // Check if this paragraph contains a single embed
    if (isEmbedParagraph(node)) {
      const embedNode = node.content[0];
      const embedType = embedNode.attrs.type;

      // Check if this embed can continue the current group.
      // For app-skill-use embeds, we group ALL consecutive ones together regardless
      // of app_id/skill_id to save vertical space. For other types, require same type.
      const sameTypeOrBothAppSkill =
        (currentGroupType === embedType) ||
        (currentGroupType === "app-skill-use" && embedType === "app-skill-use");

      if (sameTypeOrBothAppSkill && currentGroup.length > 0) {
        const canGroupWithLast = groupHandlerRegistry.canGroup(
          currentGroup[currentGroup.length - 1].content[0].attrs,
          embedNode.attrs,
        );

        if (canGroupWithLast) {
          // Can be grouped, drop any "blank line" spacer paragraphs between items
          pendingSpacerParagraphs = [];
          currentGroup.push(node);
          console.debug(
            "[groupConsecutiveEmbedParagraphs] Added embed paragraph to group:",
            {
              type: embedType,
              groupSize: currentGroup.length,
            },
          );
          continue;
        }
      }

      // Different type or can't be grouped - flush current group and start new one
      if (currentGroup.length > 0) {
        const groupedParagraph = flushEmbedParagraphGroup(
          currentGroup,
          currentGroupType!,
        );
        newContent.push(...groupedParagraph);
        // Preserve blank-line paragraphs between distinct groups
        if (pendingSpacerParagraphs.length > 0) {
          newContent.push(...pendingSpacerParagraphs);
          pendingSpacerParagraphs = [];
        }
      }

      // Start new group
      currentGroup = [node];
      currentGroupType = embedType;
      console.debug("[groupConsecutiveEmbedParagraphs] Started new group:", {
        type: embedType,
      });
      continue;
    }

    // Allow "blank line" paragraphs to sit between consecutive embed paragraphs without breaking grouping
    if (isIgnorableParagraph(node)) {
      if (currentGroup.length > 0) {
        pendingSpacerParagraphs.push(node);
        continue;
      }
      newContent.push(node);
      continue;
    }

    // Non-embed paragraph or other node - flush current group if it exists
    if (currentGroup.length > 0) {
      const groupedParagraph = flushEmbedParagraphGroup(
        currentGroup,
        currentGroupType!,
      );
      newContent.push(...groupedParagraph);
      // CRITICAL FIX: Discard spacer paragraphs between an embed and a non-embed node.
      // These empty paragraphs (from blank lines in markdown between the embed code fence
      // and the following text) create a large visual gap in ReadOnlyMessage. They are only
      // useful between distinct embed groups, not between an embed and regular text content.
      pendingSpacerParagraphs = [];
      currentGroup = [];
      currentGroupType = null;
    }

    // Add the non-embed node
    newContent.push(node);
  }

  // Flush any remaining group
  if (currentGroup.length > 0) {
    const groupedParagraph = flushEmbedParagraphGroup(
      currentGroup,
      currentGroupType!,
    );
    newContent.push(...groupedParagraph);
    if (pendingSpacerParagraphs.length > 0) {
      newContent.push(...pendingSpacerParagraphs);
      pendingSpacerParagraphs = [];
    }
  }

  return newContent;
}

/**
 * Flush a group of consecutive embed paragraphs, creating a group if there are multiple items
 * @param group - Array of consecutive paragraph nodes, each containing a single embed
 * @param embedType - The type of embeds in this group
 * @returns Array with either individual paragraphs or a grouped paragraph
 */
function flushEmbedParagraphGroup(group: any[], embedType: string): any[] {
  if (group.length === 1) {
    // Single embed paragraph - return as is
    console.debug(
      "[flushEmbedParagraphGroup] Single embed paragraph, no grouping needed:",
      embedType,
    );
    return group;
  }

  if (group.length > 1) {
    // Multiple embed paragraphs - create a group using the appropriate handler
    console.debug(
      "[flushEmbedParagraphGroup] Creating group for",
      group.length,
      embedType,
      "embed paragraphs",
    );

    // Extract the embed attributes from the paragraphs
    const embedAttrs = group.map((paragraph) => paragraph.content[0].attrs);

    // Use the group handler to create the group
    const groupAttrs = groupHandlerRegistry.createGroup(embedAttrs);

    if (groupAttrs) {
      // Create a single paragraph with the grouped embed
      const groupParagraph = {
        type: "paragraph",
        content: [
          {
            type: "embed",
            attrs: groupAttrs,
          },
        ],
      };

      console.debug(
        "[flushEmbedParagraphGroup] Created grouped embed paragraph:",
        {
          groupId: groupAttrs.id,
          groupType: groupAttrs.type,
          itemCount: groupAttrs.groupCount,
        },
      );

      return [groupParagraph];
    } else {
      console.warn(
        "[flushEmbedParagraphGroup] No group handler found for embed type:",
        embedType,
      );
      // Fallback: return individual paragraphs
      return group;
    }
  }

  return [];
}

/**
 * Group consecutive embeds within a paragraph.
 * For app-skill-use embeds: groups all consecutive ones regardless of app_id/skill_id.
 * For other types: groups consecutive same-type embeds.
 * @param paragraph - TipTap paragraph node
 * @returns Modified paragraph with grouped embeds
 */
function groupConsecutiveEmbedsInParagraph(paragraph: any): any {
  if (!paragraph.content || paragraph.content.length === 0) {
    return paragraph;
  }

  const newContent: any[] = [];
  let currentGroup: any[] = [];
  let currentGroupType: string | null = null;

  for (let i = 0; i < paragraph.content.length; i++) {
    const node = paragraph.content[i];

    if (node.type === "embed") {
      const embedType = node.attrs.type;

      // Check if this embed can continue the current group.
      // For app-skill-use embeds, group ALL consecutive ones together regardless
      // of app_id/skill_id to save vertical space.
      const sameTypeOrBothAppSkill =
        (currentGroupType === embedType) ||
        (currentGroupType === "app-skill-use" && embedType === "app-skill-use");

      if (sameTypeOrBothAppSkill && currentGroup.length > 0) {
        // Check if they can actually be grouped using the handler
        const canGroupWithLast = groupHandlerRegistry.canGroup(
          currentGroup[currentGroup.length - 1].attrs,
          node.attrs,
        );

        if (canGroupWithLast) {
          // Can be grouped, add to current group
          currentGroup.push(node);
          console.debug(
            "[groupConsecutiveEmbedsInParagraph] Added embed to group:",
            {
              type: embedType,
              identifier:
                node.attrs.url ||
                node.attrs.filename ||
                node.attrs.title ||
                node.attrs.id,
              groupSize: currentGroup.length,
            },
          );
        } else {
          // Can't be grouped (e.g., different language for code)
          // Flush current group and start new one
          if (currentGroup.length > 0) {
            const groupedNode = flushEmbedGroup(
              currentGroup,
              currentGroupType!,
            );
            newContent.push(...groupedNode);
          }

          // Start new group
          currentGroup = [node];
          currentGroupType = embedType;
          console.debug(
            "[groupConsecutiveEmbedsInParagraph] Started new group (different grouping criteria):",
            {
              type: embedType,
              identifier:
                node.attrs.url ||
                node.attrs.filename ||
                node.attrs.title ||
                node.attrs.id,
            },
          );
        }
      } else {
        // Different type, flush current group and start new one
        if (currentGroup.length > 0) {
          const groupedNode = flushEmbedGroup(currentGroup, currentGroupType!);
          newContent.push(...groupedNode);
        }

        // Start new group
        currentGroup = [node];
        currentGroupType = embedType;
        console.debug(
          "[groupConsecutiveEmbedsInParagraph] Started new group:",
          {
            type: embedType,
            identifier:
              node.attrs.url ||
              node.attrs.filename ||
              node.attrs.title ||
              node.attrs.id,
          },
        );
      }
    } else if (node.type === "text" && node.text.trim() === "") {
      // Empty text or whitespace - don't break the group, skip this node
      continue;
    } else {
      // Non-embed node with content, flush current group if it exists
      if (currentGroup.length > 0) {
        const groupedNode = flushEmbedGroup(currentGroup, currentGroupType!);
        newContent.push(...groupedNode);
        currentGroup = [];
        currentGroupType = null;
      }

      // Add the non-embed node
      newContent.push(node);
    }
  }

  // Flush any remaining group
  if (currentGroup.length > 0) {
    const groupedNode = flushEmbedGroup(currentGroup, currentGroupType!);
    newContent.push(...groupedNode);
  }

  return {
    ...paragraph,
    content: newContent,
  };
}

/**
 * Flush a group of consecutive embed nodes, creating a group if there are multiple items
 * @param group - Array of consecutive embed nodes
 * @param embedType - The type of embeds in this group
 * @returns Array with either individual embeds or a group embed
 */
function flushEmbedGroup(group: any[], embedType: string): any[] {
  if (group.length === 1) {
    // Single embed - return as is
    console.debug(
      "[flushEmbedGroup] Single embed, no grouping needed:",
      embedType,
    );
    return group;
  }

  if (group.length > 1) {
    // Multiple embeds - create a group using the appropriate handler
    console.debug(
      "[flushEmbedGroup] Creating group for",
      group.length,
      embedType,
      "embeds",
    );

    // Extract the embed attributes from the nodes
    const embedAttrs = group.map((node) => node.attrs);

    // Use the group handler to create the group
    const groupAttrs = groupHandlerRegistry.createGroup(embedAttrs);

    if (groupAttrs) {
      const groupEmbed = {
        type: "embed",
        attrs: groupAttrs,
      };

      console.debug("[flushEmbedGroup] Created embed group using handler:", {
        groupId: groupAttrs.id,
        groupType: groupAttrs.type,
        itemCount: groupAttrs.groupCount,
        items: embedAttrs.map((item) => ({
          type: item.type,
          identifier: item.url || item.filename || item.title || item.id,
        })),
      });

      return [groupEmbed];
    } else {
      console.warn(
        "[flushEmbedGroup] No group handler found for embed type:",
        embedType,
      );
      // Fallback: return individual embeds
      return group;
    }
  }

  return [];
}

/**
 * Group non-consecutive (scattered) app-skill-use embeds into a single group.
 *
 * During streaming, the LLM often outputs text between tool calls (e.g., "Let me search for X"),
 * which breaks consecutive grouping. This function collects ALL ungrouped app-skill-use embeds
 * and app-skill-use-group nodes across the entire document and merges them into the first
 * occurrence's position, keeping the text structure intact.
 *
 * All app-skill-use embeds are merged into one group regardless of app_id/skill_id,
 * matching the consecutive grouping behavior.
 *
 * Algorithm:
 * 1. Scan document for all app-skill-use embeds and app-skill-use-group embeds
 * 2. Collect all into a single list
 * 3. If >1 location found: merge all into first position, remove others
 * 4. For existing groups: expand their items into the merged group
 *
 * @param content - Array of content nodes (already processed by consecutive grouping)
 * @returns Modified content with scattered embeds grouped
 */
function groupScatteredAppSkillEmbeds(content: any[]): any[] {
  // Phase 1: Collect all app-skill-use embeds and their positions
  type EmbedLocation = {
    nodeIndex: number;
    // For embeds inside a paragraph
    isInParagraph: boolean;
    attrs: any;
    // For groups: the existing grouped items
    isGroup: boolean;
    groupedItems?: any[];
  };

  // Single list for ALL app-skill-use embeds (no longer keyed by app_id:skill_id)
  const allLocations: EmbedLocation[] = [];

  for (let i = 0; i < content.length; i++) {
    const node = content[i];

    // Check for paragraphs containing a single embed
    if (
      node?.type === "paragraph" &&
      Array.isArray(node.content) &&
      node.content.length === 1
    ) {
      const embedNode = node.content[0];
      if (embedNode?.type === "embed" && embedNode.attrs) {
        const attrs = embedNode.attrs;

        if (attrs.type === "app-skill-use") {
          allLocations.push({
            nodeIndex: i,
            isInParagraph: true,
            attrs,
            isGroup: false,
          });
        } else if (
          attrs.type === "app-skill-use-group" &&
          attrs.groupedItems
        ) {
          allLocations.push({
            nodeIndex: i,
            isInParagraph: true,
            attrs,
            isGroup: true,
            groupedItems: attrs.groupedItems,
          });
        }
      }
    }
  }

  // Phase 2: Check if merging is needed (>1 scattered locations)
  if (allLocations.length <= 1) {
    return content;
  }

  // Phase 3: Merge all scattered embeds into one group at the first location
  const indicesToRemove = new Set<number>();

  console.debug("[groupScatteredAppSkillEmbeds] Merging scattered embeds:", {
    count: allLocations.length,
    indices: allLocations.map((l) => l.nodeIndex),
  });

  // Collect all individual embed attrs (expand existing groups)
  const allEmbedAttrs: any[] = [];
  for (const loc of allLocations) {
    if (loc.isGroup && loc.groupedItems) {
      // Existing group - add all its items
      allEmbedAttrs.push(...loc.groupedItems);
    } else {
      // Individual embed
      allEmbedAttrs.push(loc.attrs);
    }
  }

  // Create a merged group using the group handler
  const groupAttrs = groupHandlerRegistry.createGroup(allEmbedAttrs);

  if (groupAttrs) {
    // Replace the first location with the merged group
    const firstLoc = allLocations[0];
    content[firstLoc.nodeIndex] = {
      type: "paragraph",
      content: [
        {
          type: "embed",
          attrs: groupAttrs,
        },
      ],
    };

    // Mark all other locations for removal
    for (let i = 1; i < allLocations.length; i++) {
      indicesToRemove.add(allLocations[i].nodeIndex);
    }

    console.debug("[groupScatteredAppSkillEmbeds] Created merged group:", {
      groupId: groupAttrs.id,
      itemCount: groupAttrs.groupCount,
      firstIndex: firstLoc.nodeIndex,
      removedIndices: allLocations.slice(1).map((l) => l.nodeIndex),
    });
  }

  // Phase 4: Remove merged nodes
  if (indicesToRemove.size === 0) {
    return content;
  }

  return content.filter((_: any, index: number) => !indicesToRemove.has(index));
}

// Legacy functions removed - use groupConsecutiveEmbedsInDocument for all grouping
