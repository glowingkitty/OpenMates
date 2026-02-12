// Document enhancement with embed nodes
// Handles replacing json_embed blocks with actual embed nodes in TipTap documents

import { EmbedNodeAttributes } from "./types";

// Special marker to indicate a duplicate embed reference that should be removed from the document
const DUPLICATE_EMBED_MARKER = Symbol("DUPLICATE_EMBED");

/* eslint-disable @typescript-eslint/no-explicit-any */
// TipTap document structure types (loosely typed to accommodate various node types)
type TipTapDocument = { content?: TipTapNode[] } & Record<string, any>;
type TipTapNode = {
  type: string;
  content?: TipTapNode[];
  text?: string;
  attrs?: Record<string, any>;
} & Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

/**
 * Enhance a TipTap document with unified embed nodes
 * @param doc - The basic TipTap document
 * @param embedNodes - Array of detected embed node attributes
 * @param mode - 'write' or 'read' mode
 * @returns Enhanced TipTap document with unified embed nodes
 */
export function enhanceDocumentWithEmbeds(
  doc: TipTapDocument,
  embedNodes: EmbedNodeAttributes[],
  mode: "write" | "read",
): TipTapDocument {
  if (!doc || !doc.content) {
    return doc;
  }

  // For json_embed blocks, we need to replace them in the text, not just append
  let modifiedContent = [...doc.content];

  // Track which embed_ids have already been rendered to handle duplicate references
  // This happens when the backend sends the same embed reference multiple times in a message
  // (e.g., skill placeholders appearing twice due to streaming concatenation)
  const renderedEmbedIds = new Set<string>();

  console.debug(
    "[enhanceDocumentWithEmbeds] Processing document with",
    embedNodes.length,
    "individual embed nodes",
  );

  // Find and replace embed blocks with embed nodes
  modifiedContent = modifiedContent.map((node) => {
    // Handle code blocks that should be replaced with embed nodes
    // In write mode, replace codeBlocks with PREVIEW embed nodes for visual rendering
    // These preview embeds are temporary and don't create EmbedStore entries
    if (node.type === "codeBlock") {
      // Try to match this code block with an embed node
      const matchResult = findMatchingEmbedForCodeBlock(
        node,
        embedNodes,
        renderedEmbedIds,
      );

      // Check if this is a duplicate embed reference that should be removed
      if (matchResult === DUPLICATE_EMBED_MARKER) {
        console.debug(
          "[enhanceDocumentWithEmbeds] Removing duplicate embed reference from document",
        );
        return null; // Will be filtered out below
      }

      const matchingEmbed = matchResult;
      if (matchingEmbed) {
        // In write mode, replace with preview embeds (contentRef starts with 'preview:')
        // These are temporary visual previews that will be converted to real embeds server-side
        if (
          mode === "write" &&
          matchingEmbed.contentRef?.startsWith("preview:")
        ) {
          console.debug(
            "[enhanceDocumentWithEmbeds] Replacing codeBlock with preview embed in write mode:",
            matchingEmbed,
          );
          // Wrap embed in a paragraph since embed is an inline node and codeBlock is block-level
          return {
            type: "paragraph",
            content: [
              {
                type: "embed",
                attrs: matchingEmbed,
              },
            ],
          };
        }

        // In read mode, replace with real embed nodes (from assistant responses)
        if (
          mode === "read" ||
          matchingEmbed.contentRef?.startsWith("embed:") ||
          matchingEmbed.contentRef?.startsWith("stream:")
        ) {
          console.debug(
            "[enhanceDocumentWithEmbeds] Replacing codeBlock with embed node:",
            matchingEmbed,
          );
          return {
            type: "paragraph",
            content: [
              {
                type: "embed",
                attrs: matchingEmbed,
              },
            ],
          };
        }
      }

      // CRITICAL: In write mode, if there's no matching embed (e.g., unclosed code block),
      // convert the codeBlock back to a plain text paragraph to avoid TipTap schema errors.
      // TipTap's schema doesn't include 'codeBlock' as a valid node type in write mode.
      // The raw markdown will be preserved as text, and decorations will handle highlighting.
      if (mode === "write") {
        const codeText = node.content?.[0]?.text || "";
        const language = node.attrs?.language || "";

        // Reconstruct the raw markdown code block syntax
        // This preserves the user's input as plain text
        const rawMarkdown = language
          ? `\`\`\`${language}\n${codeText}` // Unclosed code block with language
          : `\`\`\`\n${codeText}`; // Unclosed code block without language

        console.debug(
          "[enhanceDocumentWithEmbeds] Converting unclosed codeBlock to paragraph in write mode:",
          {
            language,
            codeTextLength: codeText.length,
          },
        );

        return {
          type: "paragraph",
          content: [
            {
              type: "text",
              text: rawMarkdown,
            },
          ],
        };
      }
    }

    // Handle paragraphs containing json_embed blocks in text
    if (node.type === "paragraph" && node.content) {
      const newParagraphContent = [];

      for (const contentNode of node.content) {
        if (contentNode.type === "text" && contentNode.text) {
          // CRITICAL FIX: Only process text nodes that don't have marks (like bold, italic, link)
          // If the node has marks, preserve them as-is - they contain important formatting info
          // Only call splitTextByJsonEmbedBlocks for plain text that might contain json_embed blocks
          if (contentNode.marks && contentNode.marks.length > 0) {
            // Preserve text nodes with marks (links, bold, italic, etc.)
            newParagraphContent.push(contentNode);
          } else {
            // Plain text - check for json_embed blocks
            const parts = splitTextByJsonEmbedBlocks(
              contentNode.text,
              embedNodes,
            );
            newParagraphContent.push(...parts);
          }
        } else {
          newParagraphContent.push(contentNode);
        }
      }

      return {
        ...node,
        content: newParagraphContent,
      };
    }
    return node;
  });

  // Filter out null nodes (duplicate embed references that were marked for removal)
  modifiedContent = modifiedContent.filter((node) => node !== null);

  // SECOND PASS: Clean up JSON embed references that appear as plain text in paragraphs.
  // This handles cases where markdown code fences weren't properly recognized (e.g., due to
  // excessive indentation in lists), leaving the JSON embed reference as plain text.
  //
  // We collect ALL known embed_ids for cleanup — both those matched via codeBlock replacement
  // (renderedEmbedIds) AND those detected by parseEmbedNodes() (from the embedNodes array).
  // This is critical because when markdown-it fails to create a codeBlock (e.g., indented fences),
  // the embed_id won't be in renderedEmbedIds, but it IS in embedNodes with contentRef="embed:<id>".
  // Without including these, the raw JSON text like {"type":"code","embed_id":"..."} leaks through.
  const allKnownEmbedIds = new Set(renderedEmbedIds);
  for (const embed of embedNodes) {
    if (embed.contentRef?.startsWith("embed:")) {
      const embedId = embed.contentRef.substring(6); // strip 'embed:' prefix
      allKnownEmbedIds.add(embedId);
    }
  }

  if (allKnownEmbedIds.size > 0) {
    modifiedContent = cleanupJsonEmbedReferencesInParagraphs(
      modifiedContent,
      allKnownEmbedIds,
    );
  }

  return {
    ...doc,
    content: modifiedContent,
  };
}

/**
 * Recursively clean up JSON embed references in paragraphs throughout the document.
 * This removes JSON strings like {"type": "code", "embed_id": "..."} from text when
 * the embed has already been rendered (via a codeBlock replacement).
 *
 * @param nodes - Array of TipTap nodes to process
 * @param renderedEmbedIds - Set of embed_ids that have already been rendered
 * @returns Cleaned array of nodes
 */
function cleanupJsonEmbedReferencesInParagraphs(
  nodes: TipTapNode[],
  renderedEmbedIds: Set<string>,
): TipTapNode[] {
  return nodes.map((node) => {
    // Process list items recursively (they can contain paragraphs with embed references)
    if (node.type === "listItem" && node.content) {
      return {
        ...node,
        content: cleanupJsonEmbedReferencesInParagraphs(
          node.content,
          renderedEmbedIds,
        ),
      };
    }

    // Process lists recursively
    if (
      (node.type === "bulletList" || node.type === "orderedList") &&
      node.content
    ) {
      return {
        ...node,
        content: cleanupJsonEmbedReferencesInParagraphs(
          node.content,
          renderedEmbedIds,
        ),
      };
    }

    // Process blockquotes recursively
    if (node.type === "blockquote" && node.content) {
      return {
        ...node,
        content: cleanupJsonEmbedReferencesInParagraphs(
          node.content,
          renderedEmbedIds,
        ),
      };
    }

    // Clean up JSON embed references in paragraph text content
    if (node.type === "paragraph" && node.content) {
      const cleanedContent = node.content
        .map((contentNode) => {
          if (contentNode.type === "text" && contentNode.text) {
            const cleanedText = removeRenderedJsonEmbedReferences(
              contentNode.text,
              renderedEmbedIds,
            );
            if (cleanedText !== contentNode.text) {
              console.debug(
                "[cleanupJsonEmbedReferencesInParagraphs] Cleaned JSON embed references from text:",
                {
                  originalLength: contentNode.text.length,
                  cleanedLength: cleanedText.length,
                  removed: contentNode.text.length - cleanedText.length,
                },
              );
            }
            // If the cleaned text is empty or only whitespace, return null to filter it out
            if (!cleanedText || !cleanedText.trim()) {
              return null;
            }
            return {
              ...contentNode,
              text: cleanedText,
            };
          }
          return contentNode;
        })
        .filter((n) => n !== null);

      // If paragraph is now empty, return null to potentially filter it out
      if (cleanedContent.length === 0) {
        // Keep empty paragraphs for spacing
        return {
          ...node,
          content: [],
        };
      }

      return {
        ...node,
        content: cleanedContent,
      };
    }

    return node;
  });
}

/**
 * Find a matching embed node for a code block
 * @param codeBlockNode - The TipTap codeBlock node
 * @param embedNodes - Array of embed nodes to search
 * @param renderedEmbedIds - Set of embed_ids that have already been rendered (to detect duplicates)
 * @returns The matching embed node, DUPLICATE_EMBED_MARKER for duplicates, or null
 */
function findMatchingEmbedForCodeBlock(
  codeBlockNode: TipTapNode,
  embedNodes: EmbedNodeAttributes[],
  renderedEmbedIds: Set<string>,
): EmbedNodeAttributes | typeof DUPLICATE_EMBED_MARKER | null {
  // Extract text content from the code block
  const codeText = codeBlockNode.content?.[0]?.text || "";

  console.debug("[findMatchingEmbedForCodeBlock] Checking code block:", {
    codeText: codeText.substring(0, 100),
    hasContent: !!codeText,
    embedNodesCount: embedNodes.length,
  });

  if (!codeText.trim()) {
    return null;
  }

  // Try to parse as JSON to check if it's an embed reference
  try {
    const parsed = JSON.parse(codeText.trim());

    console.debug("[findMatchingEmbedForCodeBlock] Parsed JSON:", parsed);

    // Check if this is an embed reference with type and embed_id
    if (parsed.type && parsed.embed_id) {
      const embedId = parsed.embed_id;

      // CRITICAL FIX: Check if this embed_id has already been rendered
      // This handles duplicate embed references in the message content
      // (which can happen when the backend streams embed references multiple times)
      if (renderedEmbedIds.has(embedId)) {
        console.debug(
          "[findMatchingEmbedForCodeBlock] Duplicate embed reference detected, marking for removal:",
          {
            type: parsed.type,
            embed_id: embedId,
          },
        );
        return DUPLICATE_EMBED_MARKER;
      }

      // Find matching embed node by checking contentRef
      const matchingEmbed = embedNodes.find((node) => {
        const expectedContentRef = `embed:${embedId}`;
        console.debug("[findMatchingEmbedForCodeBlock] Comparing:", {
          expectedContentRef,
          nodeContentRef: node.contentRef,
          matches: node.contentRef === expectedContentRef,
        });
        return node.contentRef === expectedContentRef;
      });

      if (matchingEmbed) {
        console.debug(
          "[findMatchingEmbedForCodeBlock] Found matching embed for JSON block:",
          {
            type: parsed.type,
            embed_id: embedId,
            embedNodeId: matchingEmbed.id,
            embedNodeType: matchingEmbed.type,
          },
        );

        // Mark this embed_id as rendered to detect future duplicates
        renderedEmbedIds.add(embedId);

        // NOTE: We no longer remove from the array with splice() because:
        // 1. The same embed_id can appear multiple times in the message (backend bug)
        // 2. Instead, we use renderedEmbedIds Set to track what's been rendered
        // 3. Duplicates are marked for removal from the document

        return matchingEmbed;
      } else {
        // No matching embed found - this could be because:
        // 1. The embed wasn't created by parseEmbedNodes (bug)
        // 2. Or this is a duplicate and the Set check above didn't catch it
        //    (shouldn't happen with the current fix)
        console.warn(
          "[findMatchingEmbedForCodeBlock] No matching embed found for:",
          {
            type: parsed.type,
            embed_id: embedId,
            availableEmbeds: embedNodes.map((n) => ({
              id: n.id,
              type: n.type,
              contentRef: n.contentRef,
            })),
          },
        );
      }
    }
  } catch {
    // Not JSON, might be a regular code block - this is expected for actual code blocks
    console.debug(
      "[findMatchingEmbedForCodeBlock] Not JSON, treating as code block",
    );
  }

  // Check if this is a code-code embed (code snippet with language)
  // Match by checking if there's a code-code embed with similar content
  const codeEmbeds = embedNodes.filter((node) => node.type === "code-code");
  if (codeEmbeds.length > 0) {
    const codeBlockLanguage = codeBlockNode.attrs?.language;

    // For preview embeds (contentRef starts with 'preview:'), match by language AND code content
    // For real embeds, match by language only (content is in EmbedStore)
    const matchingCodeEmbed = codeEmbeds.find((embed) => {
      // Match language: both undefined/empty, or both the same value
      const embedLanguage = embed.language || "";
      const blockLanguage = codeBlockLanguage || "";
      const languageMatch = embedLanguage === blockLanguage;

      // If it's a preview embed, also match by code content
      if (embed.contentRef?.startsWith("preview:")) {
        const embedCode = embed.code || "";
        const codeBlockText = codeText.trim();
        const contentMatch = embedCode.trim() === codeBlockText;

        console.debug(
          "[findMatchingEmbedForCodeBlock] Preview embed comparison:",
          {
            embedLanguage,
            blockLanguage,
            languageMatch,
            embedCodeLength: embedCode.trim().length,
            codeBlockTextLength: codeBlockText.length,
            contentMatch,
          },
        );

        return languageMatch && contentMatch;
      }

      // For real embeds, just match by language
      return languageMatch;
    });

    if (matchingCodeEmbed) {
      console.debug(
        "[findMatchingEmbedForCodeBlock] Found matching code embed:",
        {
          language: matchingCodeEmbed.language,
          embedNodeId: matchingCodeEmbed.id,
          isPreview: matchingCodeEmbed.contentRef?.startsWith("preview:"),
        },
      );
      // Remove from array to prevent reuse
      const index = embedNodes.indexOf(matchingCodeEmbed);
      if (index > -1) {
        embedNodes.splice(index, 1);
      }
      return matchingCodeEmbed;
    }
  }

  return null;
}

/**
 * Remove JSON embed references from text content when the embed has already been rendered.
 * This handles cases where markdown code fences aren't properly recognized (e.g., due to
 * excessive indentation in lists), leaving the JSON embed reference as plain text.
 *
 * Matches patterns like: {"type": "code", "embed_id": "uuid"}
 *
 * IMPORTANT: This function must preserve whitespace in text that does NOT contain JSON
 * embed references. Only remove/trim whitespace that is directly adjacent to the removed
 * JSON references, not leading/trailing whitespace of the entire text.
 *
 * @param text - The text content that may contain JSON embed references
 * @param renderedEmbedIds - Set of embed_ids that have already been rendered
 * @returns Cleaned text with matched JSON references removed
 */
function removeRenderedJsonEmbedReferences(
  text: string,
  renderedEmbedIds: Set<string>,
): string {
  if (!text || renderedEmbedIds.size === 0) {
    return text;
  }

  // First, remove entire fenced ```json blocks that contain rendered embed references.
  // This prevents leaving stray fence markers (```json / ```) in the text when the
  // embed was already rendered as a node, especially in indented list contexts.
  const fencedJsonRegex = /```json[\s\S]*?```/gi;
  let fencedResult = text;
  let fencedMatch: RegExpExecArray | null;
  const fencedMatches: { fullMatch: string; embedId: string; index: number }[] =
    [];

  while ((fencedMatch = fencedJsonRegex.exec(text)) !== null) {
    const fencedBlock = fencedMatch[0];
    const embedIdMatch = fencedBlock.match(/"embed_id"\s*:\s*"([a-f0-9-]+)"/i);
    if (embedIdMatch && renderedEmbedIds.has(embedIdMatch[1])) {
      fencedMatches.push({
        fullMatch: fencedBlock,
        embedId: embedIdMatch[1],
        index: fencedMatch.index,
      });
      console.debug(
        "[removeRenderedJsonEmbedReferences] Removing fenced JSON embed block:",
        {
          embedId: embedIdMatch[1],
          matchLength: fencedBlock.length,
        },
      );
    }
  }

  // Remove fenced matches in reverse order to preserve indices
  for (let i = fencedMatches.length - 1; i >= 0; i--) {
    const { fullMatch, index } = fencedMatches[i];
    const before = fencedResult.substring(0, index);
    const after = fencedResult.substring(index + fullMatch.length);
    // Keep surrounding whitespace stable to avoid collapsing adjacent markdown
    fencedResult =
      before.trimEnd() + (after ? "\n" + after.replace(/^[\s\n]*/, "") : "");
  }

  // Continue cleanup on the possibly trimmed string
  const jsonText = fencedResult;

  // Match JSON objects that look like embed references: {"type": "...", "embed_id": "uuid"}
  // This regex matches JSON-like strings with type and embed_id fields
  // We use a non-greedy match to handle multiple references in the same text
  const jsonEmbedRefRegex =
    /\{[\s]*"type"[\s]*:[\s]*"[^"]*"[\s]*,[\s]*"embed_id"[\s]*:[\s]*"([a-f0-9-]+)"[\s]*(?:,[\s]*[^}]*)?\}/gi;

  let result = jsonText;
  let match;
  const matches: { fullMatch: string; embedId: string; index: number }[] = [];

  // Collect all matches first
  while ((match = jsonEmbedRefRegex.exec(jsonText)) !== null) {
    const embedId = match[1];
    if (renderedEmbedIds.has(embedId)) {
      matches.push({
        fullMatch: match[0],
        embedId,
        index: match.index,
      });
      console.debug(
        "[removeRenderedJsonEmbedReferences] Found rendered JSON embed reference to remove:",
        {
          embedId,
          matchLength: match[0].length,
        },
      );
    }
  }

  // CRITICAL FIX: If no matches found, return the original text UNCHANGED
  // Do NOT trim text that has no JSON embed references - this preserves spaces around
  // bold/italic/link formatting that is essential for proper rendering
  if (matches.length === 0) {
    // Return the post-fenced cleanup string to preserve any removed fenced blocks.
    return jsonText;
  }

  // Remove matches in reverse order to preserve indices
  for (let i = matches.length - 1; i >= 0; i--) {
    const { fullMatch, index } = matches[i];
    // Remove the JSON reference and any trailing newlines/whitespace
    const beforeMatch = result.substring(0, index);
    const afterMatch = result.substring(index + fullMatch.length);

    // Clean up whitespace around the removed reference
    const cleanedAfter = afterMatch.replace(/^[\s\n]*/, "");
    result = beforeMatch.trimEnd() + (cleanedAfter ? "\n" + cleanedAfter : "");
  }

  // Only trim if we actually removed something, and only trim the final result
  // (at this point we know there were JSON references, so trimming is safe)
  return result.trim();
}

/**
 * Split text content by json_embed blocks and replace them with embed nodes
 * @param text - The text content that may contain json_embed blocks
 * @param embedNodes - Array of embed nodes to use for replacement
 * @returns Array of text nodes and embed nodes
 */
function splitTextByJsonEmbedBlocks(
  text: string,
  embedNodes: EmbedNodeAttributes[],
): TipTapNode[] {
  const result = [];

  // Filter to only get website embed nodes that came from json_embed blocks
  const webEmbedNodes = embedNodes.filter(
    (node) => node.type === "web-website",
  );

  // If no web embed nodes, return the original text
  if (webEmbedNodes.length === 0) {
    result.push({
      type: "text",
      text: text,
    });
    return result;
  }

  // Find all json_embed blocks in the text and match them with embed nodes
  const jsonEmbedRegex = /```json_embed\n[\s\S]*?\n```/g;
  const embedMatches: {
    match: RegExpExecArray;
    embedNode: EmbedNodeAttributes;
  }[] = [];
  let match;

  // Reset regex lastIndex to ensure we get all matches
  jsonEmbedRegex.lastIndex = 0;

  while ((match = jsonEmbedRegex.exec(text)) !== null) {
    try {
      // Extract and parse the json content to match with the right embed node
      const jsonContent = match[0].match(/```json_embed\n([\s\S]*?)\n```/)?.[1];
      if (jsonContent) {
        const parsed = JSON.parse(jsonContent);

        // Find the corresponding embed node by URL (use the first available match)
        // Remove used embed nodes to handle multiple instances of the same URL correctly
        const correspondingEmbedNodeIndex = webEmbedNodes.findIndex(
          (node) => node.url === parsed.url,
        );
        if (correspondingEmbedNodeIndex !== -1) {
          const correspondingEmbedNode =
            webEmbedNodes[correspondingEmbedNodeIndex];
          // Remove the used embed node to prevent reuse
          webEmbedNodes.splice(correspondingEmbedNodeIndex, 1);

          embedMatches.push({ match, embedNode: correspondingEmbedNode });
          console.debug(
            "[splitTextByJsonEmbedBlocks] Matched json_embed block with embed node:",
            {
              url: parsed.url,
              embedNodeId: correspondingEmbedNode.id,
              remainingEmbedNodes: webEmbedNodes.length,
            },
          );
        } else {
          console.warn(
            "[splitTextByJsonEmbedBlocks] No matching embed node found for URL:",
            parsed.url,
          );
        }
      }
    } catch (error) {
      console.warn(
        "[splitTextByJsonEmbedBlocks] Error parsing json_embed block:",
        error,
      );
      // Still try to match by order if parsing fails and we have remaining nodes
      if (webEmbedNodes.length > 0) {
        const fallbackEmbedNode = webEmbedNodes.shift()!; // Remove the first available node
        embedMatches.push({ match, embedNode: fallbackEmbedNode });
        console.debug(
          "[splitTextByJsonEmbedBlocks] Used fallback matching for json_embed block",
        );
      }
    }
  }

  // If no matches found, return original text
  if (embedMatches.length === 0) {
    result.push({
      type: "text",
      text: text,
    });
    return result;
  }

  // Sort matches by position to process them in order
  embedMatches.sort((a, b) => a.match.index - b.match.index);

  let lastIndex = 0;

  for (const { match, embedNode } of embedMatches) {
    // Add text before the json_embed block
    if (match.index > lastIndex) {
      const beforeText = text.substring(lastIndex, match.index);
      if (beforeText.trim() || beforeText.includes("\n")) {
        result.push({
          type: "text",
          text: beforeText,
        });
      }
    }

    console.debug(
      "[splitTextByJsonEmbedBlocks] Replacing json_embed block with embed node:",
      embedNode,
    );

    // Add the corresponding embed node
    result.push({
      type: "embed",
      attrs: embedNode,
    });

    // Add a hard break after the embed to force cursor to next line
    result.push({
      type: "hardBreak",
    });

    lastIndex = match.index + match[0].length;
  }

  // Add remaining text after the last json_embed block
  if (lastIndex < text.length) {
    const afterText = text.substring(lastIndex);
    if (afterText.trim() || afterText.includes("\n")) {
      result.push({
        type: "text",
        text: afterText,
      });
    }
  }

  // If no content was added, ensure we have at least the original text
  if (result.length === 0) {
    result.push({
      type: "text",
      text: text,
    });
  }

  return result;
}
