// frontend/packages/ui/src/utils/messageTruncation.ts
// Utility functions for handling message truncation to improve performance and UX

import type { Message } from '../types/chat';

// Configuration constants
const MAX_USER_MESSAGE_LENGTH = 1000; // Configurable limit for user messages
const TRUNCATION_SUFFIX = '...';

/**
 * Determines if a message should be truncated based on role and content length
 * Only user messages are truncated, assistant messages are always shown in full
 */
export function shouldTruncateMessage(message: Message): boolean {
  return message.role === 'user' && 
         message.content && 
         typeof message.content === 'string' && 
         message.content.length > MAX_USER_MESSAGE_LENGTH;
}

/**
 * Creates a truncated version of a message for display purposes
 * The original full content is preserved in the message object
 * For TipTap JSON content, we truncate at the text level to avoid breaking node structure
 */
export function createTruncatedMessage(message: Message): Message {
  if (!shouldTruncateMessage(message)) {
    return message;
  }

  const content = message.content as string;
  const truncatedContent = content.substring(0, MAX_USER_MESSAGE_LENGTH) + TRUNCATION_SUFFIX;
  
  return {
    ...message,
    is_truncated: true,
    truncated_content: truncatedContent,
    full_content_length: content.length,
    content: truncatedContent // Use truncated content for display
  };
}

/**
 * Truncates TipTap JSON content by limiting text content while preserving node structure
 * This prevents issues with embed nodes and other complex structures
 */
export function truncateTiptapContent(tiptapContent: any, maxLength: number = MAX_USER_MESSAGE_LENGTH): any {
  if (!tiptapContent || tiptapContent.type !== 'doc' || !tiptapContent.content) {
    return tiptapContent;
  }

  let currentLength = 0;
  const truncatedContent: any[] = [];

  function truncateNode(node: any): any {
    if (currentLength >= maxLength) {
      return null; // Skip remaining nodes
    }

    if (node.type === 'text' && node.text) {
      const remainingLength = maxLength - currentLength;
      if (node.text.length <= remainingLength) {
        currentLength += node.text.length;
        return node;
      } else {
        // Truncate this text node
        const truncatedText = node.text.substring(0, remainingLength) + TRUNCATION_SUFFIX;
        currentLength = maxLength;
        return {
          ...node,
          text: truncatedText
        };
      }
    } else if (node.content) {
      // Process child nodes
      const truncatedChildren: any[] = [];
      for (const child of node.content) {
        const truncatedChild = truncateNode(child);
        if (truncatedChild) {
          truncatedChildren.push(truncatedChild);
        } else {
          break; // Stop processing if we've reached the limit
        }
      }
      
      return {
        ...node,
        content: truncatedChildren
      };
    } else {
      // Non-text node without content (like embeds, images, etc.)
      // For now, we'll include them but this might need refinement
      return node;
    }
  }

  // Process all top-level nodes
  for (const node of tiptapContent.content) {
    const truncatedNode = truncateNode(node);
    if (truncatedNode) {
      truncatedContent.push(truncatedNode);
    } else {
      break; // Stop if we've reached the limit
    }
  }

  return {
    ...tiptapContent,
    content: truncatedContent
  };
}

/**
 * Gets the appropriate content for display (truncated or full)
 */
export function getDisplayContent(message: Message): string {
  return message.is_truncated ? message.truncated_content! : message.content!;
}

/**
 * Checks if a message is currently truncated
 */
export function isMessageTruncated(message: Message): boolean {
  return message.is_truncated === true;
}

/**
 * Gets the full content length of a message (including truncated ones)
 */
export function getFullContentLength(message: Message): number {
  return message.full_content_length || (message.content?.length || 0);
}

/**
 * Creates a message with full content restored (for on-demand loading)
 */
export function restoreFullContent(message: Message, fullContent: string): Message {
  return {
    ...message,
    content: fullContent,
    is_truncated: false,
    truncated_content: undefined,
    full_content_length: fullContent.length
  };
}
