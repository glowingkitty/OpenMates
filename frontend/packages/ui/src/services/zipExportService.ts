/**
 * Zip Export Service
 * Handles creating enhanced zip exports for chats with:
 * - YAML format of the chat
 * - Markdown format of the chat history
 * - Separate code files for each code embed (with original file paths)
 * - Separate transcript files for each video transcript embed
 */

import JSZip from 'jszip';
import type { Chat, Message } from '../types/chat';
import { convertChatToYaml, generateChatFilename } from './chatExportService';
import { extractEmbedReferences, loadEmbeds, decodeToonContent } from './embedResolver';
import { tipTapToCanonicalMarkdown } from '../message_parsing/serializers';

/**
 * Converts a single message to markdown format
 */
async function convertMessageToMarkdown(message: Message): Promise<string> {
  try {
    const timestamp = new Date(message.created_at * 1000).toISOString();
    const role = message.role === 'assistant' ? 'Assistant' : 'You';

    let content = '';
    if (typeof message.content === 'string') {
      content = message.content;
    } else if (message.content && typeof message.content === 'object') {
      content = tipTapToCanonicalMarkdown(message.content);
    }

    return `## ${role} - ${timestamp}\n\n${content}\n\n`;
  } catch (error) {
    console.error('[ZipExportService] Error converting message to markdown:', error);
    return '';
  }
}

/**
 * Converts chat messages to markdown format
 */
async function convertChatToMarkdown(chat: Chat, messages: Message[]): Promise<string> {
  try {
    let markdown = '';

    // Add title header
    if (chat.title) {
      markdown += `# ${chat.title}\n\n`;
    }

    // Add metadata
    const createdDate = new Date(chat.created_at * 1000).toISOString();
    markdown += `*Created: ${createdDate}*\n\n`;
    markdown += '---\n\n';

    // Add all messages
    for (const message of messages) {
      const messageMarkdown = await convertMessageToMarkdown(message);
      markdown += messageMarkdown;
    }

    return markdown;
  } catch (error) {
    console.error('[ZipExportService] Error converting chat to markdown:', error);
    return '';
  }
}

/**
 * Recursively loads all embeds and finds code embeds including nested ones
 * @param embedIds - Array of embed IDs to load
 * @param loadedEmbedIds - Set of already loaded embed IDs to avoid duplicates
 * @returns Array of code embed data
 */
async function loadCodeEmbedsRecursively(embedIds: string[], loadedEmbedIds: Set<string> = new Set()): Promise<Array<{
  embed_id: string;
  language: string;
  filename?: string;
  content: string;
  file_path?: string;
}>> {
  const codeEmbeds: Array<{
    embed_id: string;
    language: string;
    filename?: string;
    content: string;
    file_path?: string;
  }> = [];

  // Filter out already loaded embeds
  const newEmbedIds = embedIds.filter(id => !loadedEmbedIds.has(id));
  if (newEmbedIds.length === 0) {
    return codeEmbeds;
  }

  // Mark these as being loaded
  newEmbedIds.forEach(id => loadedEmbedIds.add(id));

  // Load embeds from EmbedStore
  const loadedEmbeds = await loadEmbeds(newEmbedIds);

  // Process each embed
  for (const embed of loadedEmbeds) {
    try {
      if (!embed.content || typeof embed.content !== 'string') {
        continue;
      }

      // Decode TOON content to get actual embed values
      const decodedContent = await decodeToonContent(embed.content);

      // If this is a code embed, process it
      if (embed.type === 'code' && decodedContent && typeof decodedContent === 'object') {
        const codeContent = decodedContent.code || decodedContent.content || '';
        const language = decodedContent.language || decodedContent.lang || 'text';
        const filename = decodedContent.filename || undefined;
        const filePath = decodedContent.file_path || undefined;

        if (codeContent) {
          codeEmbeds.push({
            embed_id: embed.embed_id,
            language,
            filename,
            content: codeContent,
            file_path: filePath
          });
        }
      }

      // Handle nested embeds (composite embeds like app_skill_use)
      const childEmbedIds: string[] = [];

      // Check for embed_ids in the decoded content (for composite embeds)
      if (decodedContent && typeof decodedContent === 'object') {
        // Check if decoded content has embed_ids (could be array or pipe-separated string)
        if (Array.isArray(decodedContent.embed_ids)) {
          childEmbedIds.push(...decodedContent.embed_ids);
        } else if (typeof decodedContent.embed_ids === 'string') {
          // Handle pipe-separated string format
          childEmbedIds.push(...decodedContent.embed_ids.split('|').filter(id => id.trim()));
        }
      }

      // Also check embed.embed_ids directly (from the embed metadata)
      if (embed.embed_ids && Array.isArray(embed.embed_ids)) {
        childEmbedIds.push(...embed.embed_ids);
      }

      // Remove duplicates
      const uniqueChildEmbedIds = Array.from(new Set(childEmbedIds));

      // Recursively load child embeds
      if (uniqueChildEmbedIds.length > 0) {
        console.debug('[ZipExportService] Loading nested embeds for code processing:', {
          parentEmbedId: embed.embed_id,
          childCount: uniqueChildEmbedIds.length,
          childIds: uniqueChildEmbedIds
        });

        const childCodeEmbeds = await loadCodeEmbedsRecursively(uniqueChildEmbedIds, loadedEmbedIds);
        codeEmbeds.push(...childCodeEmbeds);
      }
    } catch (error) {
      console.warn('[ZipExportService] Error processing embed for code extraction:', embed.embed_id, error);
    }
  }

  return codeEmbeds;
}

/**
 * Gets all code embeds from a chat including nested embeds
 */
async function getCodeEmbedsForChat(messages: Message[]): Promise<Array<{
  embed_id: string;
  language: string;
  filename?: string;
  content: string;
  file_path?: string;
}>> {
  try {
    // Extract all embed references from messages
    const embedRefs = new Map<string, { type: string; embed_id: string; version?: number }>();

    for (const message of messages) {
      let markdownContent = '';
      if (typeof message.content === 'string') {
        markdownContent = message.content;
      } else if (message.content && typeof message.content === 'object') {
        markdownContent = tipTapToCanonicalMarkdown(message.content);
      }

      const refs = extractEmbedReferences(markdownContent);
      for (const ref of refs) {
        // Include all embed types, not just code, since nested embeds might contain code
        if (!embedRefs.has(ref.embed_id)) {
          embedRefs.set(ref.embed_id, ref);
        }
      }
    }

    if (embedRefs.size === 0) {
      return [];
    }

    // Load embeds recursively to catch nested code embeds
    const embedIds = Array.from(embedRefs.keys());
    return await loadCodeEmbedsRecursively(embedIds);
  } catch (error) {
    console.error('[ZipExportService] Error getting code embeds:', error);
    return [];
  }
}

/**
 * Recursively loads all embeds and finds video transcript embeds including nested ones
 * @param embedIds - Array of embed IDs to load
 * @param loadedEmbedIds - Set of already loaded embed IDs to avoid duplicates
 * @returns Array of video transcript embed data
 */
async function loadVideoTranscriptEmbedsRecursively(embedIds: string[], loadedEmbedIds: Set<string> = new Set()): Promise<Array<{
  embed_id: string;
  filename: string;
  content: string;
}>> {
  const transcriptEmbeds: Array<{
    embed_id: string;
    filename: string;
    content: string;
  }> = [];

  // Filter out already loaded embeds
  const newEmbedIds = embedIds.filter(id => !loadedEmbedIds.has(id));
  if (newEmbedIds.length === 0) {
    return transcriptEmbeds;
  }

  // Mark these as being loaded
  newEmbedIds.forEach(id => loadedEmbedIds.add(id));

  // Load embeds from EmbedStore
  const loadedEmbeds = await loadEmbeds(newEmbedIds);

  // Process each embed
  for (const embed of loadedEmbeds) {
    try {
      if (!embed.content || typeof embed.content !== 'string') {
        continue;
      }

      // Decode TOON content to get actual embed values
      const decodedContent = await decodeToonContent(embed.content);

      // If this is a video transcript embed, process it
      if (
        embed.type === 'app_skill_use' &&
        decodedContent &&
        typeof decodedContent === 'object' &&
        decodedContent.app_id === 'videos' &&
        (decodedContent.skill_id === 'get_transcript' || decodedContent.skill_id === 'get-transcript')
      ) {
        // Extract results array from decoded content
        const results = decodedContent.results || decodedContent.data || [];

        if (Array.isArray(results) && results.length > 0) {
          // Format transcript as markdown
          const transcriptText = results
            .filter((r: any) => {
              return r.transcript || r.formatted_transcript || r.text || r.content;
            })
            .map((r: any) => {
              let content = '';

              if (r.metadata?.title) {
                content += `# ${r.metadata.title}\n\n`;
              }

              if (r.url) {
                content += `Source: ${r.url}\n\n`;
              }

              if (r.word_count) {
                content += `Word count: ${r.word_count.toLocaleString()}\n\n`;
              }

              const transcript = r.transcript || r.formatted_transcript || r.text || r.content || '';
              content += transcript;

              return content;
            })
            .join('\n\n---\n\n');

          if (transcriptText) {
            // Generate filename from first result's title or URL
            let filename = 'transcript.md';
            const firstResult = results[0];
            if (firstResult?.metadata?.title) {
              filename = `${firstResult.metadata.title.replace(/[^a-z0-9]/gi, '_').toLowerCase()}_transcript.md`;
            } else if (firstResult?.url) {
              try {
                const urlObj = new URL(firstResult.url);
                const videoId = urlObj.searchParams.get('v') || urlObj.pathname.split('/').pop() || 'video';
                filename = `${videoId}_transcript.md`;
              } catch (e) {
                filename = `${embed.embed_id}_transcript.md`;
              }
            } else {
              filename = `${embed.embed_id}_transcript.md`;
            }

            transcriptEmbeds.push({
              embed_id: embed.embed_id,
              filename,
              content: transcriptText
            });
          }
        }
      }

      // Handle nested embeds (composite embeds like app_skill_use)
      const childEmbedIds: string[] = [];

      // Check for embed_ids in the decoded content (for composite embeds)
      if (decodedContent && typeof decodedContent === 'object') {
        // Check if decoded content has embed_ids (could be array or pipe-separated string)
        if (Array.isArray(decodedContent.embed_ids)) {
          childEmbedIds.push(...decodedContent.embed_ids);
        } else if (typeof decodedContent.embed_ids === 'string') {
          // Handle pipe-separated string format
          childEmbedIds.push(...decodedContent.embed_ids.split('|').filter(id => id.trim()));
        }
      }

      // Also check embed.embed_ids directly (from the embed metadata)
      if (embed.embed_ids && Array.isArray(embed.embed_ids)) {
        childEmbedIds.push(...embed.embed_ids);
      }

      // Remove duplicates
      const uniqueChildEmbedIds = Array.from(new Set(childEmbedIds));

      // Recursively load child embeds
      if (uniqueChildEmbedIds.length > 0) {
        console.debug('[ZipExportService] Loading nested embeds for transcript processing:', {
          parentEmbedId: embed.embed_id,
          childCount: uniqueChildEmbedIds.length,
          childIds: uniqueChildEmbedIds
        });

        const childTranscriptEmbeds = await loadVideoTranscriptEmbedsRecursively(uniqueChildEmbedIds, loadedEmbedIds);
        transcriptEmbeds.push(...childTranscriptEmbeds);
      }
    } catch (error) {
      console.warn('[ZipExportService] Error processing embed for transcript extraction:', embed.embed_id, error);
    }
  }

  return transcriptEmbeds;
}

/**
 * Gets all video transcript embeds from a chat including nested embeds
 * Extracts video transcript embeds (app_skill_use with app_id='videos' and skill_id='get_transcript')
 * and formats them as markdown files similar to VideoTranscriptEmbedFullscreen handleDownload
 */
async function getVideoTranscriptEmbedsForChat(messages: Message[]): Promise<Array<{
  embed_id: string;
  filename: string;
  content: string;
}>> {
  try {
    // Extract all embed references from messages
    const embedRefs = new Map<string, { type: string; embed_id: string; version?: number }>();

    for (const message of messages) {
      let markdownContent = '';
      if (typeof message.content === 'string') {
        markdownContent = message.content;
      } else if (message.content && typeof message.content === 'object') {
        markdownContent = tipTapToCanonicalMarkdown(message.content);
      }

      const refs = extractEmbedReferences(markdownContent);
      for (const ref of refs) {
        // Include all embed types, not just app_skill_use, since nested embeds might contain transcripts
        if (!embedRefs.has(ref.embed_id)) {
          embedRefs.set(ref.embed_id, ref);
        }
      }
    }

    if (embedRefs.size === 0) {
      return [];
    }

    // Load embeds recursively to catch nested transcript embeds
    const embedIds = Array.from(embedRefs.keys());
    return await loadVideoTranscriptEmbedsRecursively(embedIds);
  } catch (error) {
    console.error('[ZipExportService] Error getting video transcript embeds:', error);
    return [];
  }
}

/**
 * Determines the file extension for a code language
 */
function getFileExtensionForLanguage(language: string): string {
  const extensions: Record<string, string> = {
    'javascript': 'js',
    'typescript': 'ts',
    'python': 'py',
    'java': 'java',
    'cpp': 'cpp',
    'c': 'c',
    'rust': 'rs',
    'go': 'go',
    'ruby': 'rb',
    'php': 'php',
    'swift': 'swift',
    'kotlin': 'kt',
    'yaml': 'yml',
    'xml': 'xml',
    'markdown': 'md',
    'bash': 'sh',
    'shell': 'sh',
    'sql': 'sql',
    'json': 'json',
    'css': 'css',
    'html': 'html',
    'dockerfile': 'Dockerfile'
  };

  return extensions[language.toLowerCase()] || language.toLowerCase();
}

/**
 * Downloads a single chat as a zip with yml, markdown, and code files
 */
export async function downloadChatAsZip(chat: Chat, messages: Message[]): Promise<void> {
  try {
    console.debug('[ZipExportService] Starting zip download for chat:', chat.chat_id);

    const zip = new JSZip();

    // Generate filename base (without extension)
    const filename = await generateChatFilename(chat, '');
    const filenameWithoutExt = filename.replace(/\.[^.]+$/, '');

    // Add YAML file
    const yamlContent = await convertChatToYaml(chat, messages, false);
    zip.file(`${filenameWithoutExt}.yml`, yamlContent);

    // Add Markdown file
    const markdownContent = await convertChatToMarkdown(chat, messages);
    zip.file(`${filenameWithoutExt}.md`, markdownContent);

    // Add code embeds as separate files
    const codeEmbeds = await getCodeEmbedsForChat(messages);
    for (const codeEmbed of codeEmbeds) {
      // Use file_path if available (reconstruct directory structure)
      // Otherwise use filename + language, or fallback to embed_id
      let filePath: string;

      if (codeEmbed.file_path) {
        filePath = codeEmbed.file_path;
      } else if (codeEmbed.filename) {
        filePath = `code/${codeEmbed.filename}`;
      } else {
        const ext = getFileExtensionForLanguage(codeEmbed.language);
        filePath = `code/${codeEmbed.embed_id}.${ext}`;
      }

      zip.file(filePath, codeEmbed.content);
    }

    // Add video transcript embeds as separate files
    const transcriptEmbeds = await getVideoTranscriptEmbedsForChat(messages);
    for (const transcriptEmbed of transcriptEmbeds) {
      // Store transcripts in a transcripts folder
      const filePath = `transcripts/${transcriptEmbed.filename}`;
      zip.file(filePath, transcriptEmbed.content);
    }

    // Generate and download zip
    const zipBlob = await zip.generateAsync({ type: 'blob' });
    const url = URL.createObjectURL(zipBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${filenameWithoutExt}.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    console.debug('[ZipExportService] Zip download completed for chat:', chat.chat_id);
  } catch (error) {
    console.error('[ZipExportService] Error downloading chat as zip:', error);
    throw new Error('Failed to download chat as zip');
  }
}

/**
 * Downloads multiple chats as a zip with folders for each chat
 */
export async function downloadChatsAsZip(chats: Chat[], messagesMap: Map<string, Message[]>): Promise<void> {
  try {
    console.debug('[ZipExportService] Starting bulk zip download for', chats.length, 'chats');

    const zip = new JSZip();
    let successCount = 0;

    // Process each chat
    for (const chat of chats) {
      try {
        const messages = messagesMap.get(chat.chat_id) || [];

        // Generate filename base (without extension)
        const filename = await generateChatFilename(chat, '');
        const filenameWithoutExt = filename.replace(/\.[^.]+$/, '');

        // Create folder for this chat
        const chatFolder = zip.folder(filenameWithoutExt);
        if (!chatFolder) {
          console.warn('[ZipExportService] Failed to create folder for chat:', chat.chat_id);
          continue;
        }

        // Add YAML file
        const yamlContent = await convertChatToYaml(chat, messages, false);
        chatFolder.file(`${filenameWithoutExt}.yml`, yamlContent);

        // Add Markdown file
        const markdownContent = await convertChatToMarkdown(chat, messages);
        chatFolder.file(`${filenameWithoutExt}.md`, markdownContent);

        // Add code embeds as separate files
        const codeEmbeds = await getCodeEmbedsForChat(messages);
        for (const codeEmbed of codeEmbeds) {
          let filePath: string;

          if (codeEmbed.file_path) {
            filePath = codeEmbed.file_path;
          } else if (codeEmbed.filename) {
            filePath = `code/${codeEmbed.filename}`;
          } else {
            const ext = getFileExtensionForLanguage(codeEmbed.language);
            filePath = `code/${codeEmbed.embed_id}.${ext}`;
          }

          chatFolder.file(filePath, codeEmbed.content);
        }

        // Add video transcript embeds as separate files
        const transcriptEmbeds = await getVideoTranscriptEmbedsForChat(messages);
        for (const transcriptEmbed of transcriptEmbeds) {
          // Store transcripts in a transcripts folder
          const filePath = `transcripts/${transcriptEmbed.filename}`;
          chatFolder.file(filePath, transcriptEmbed.content);
        }

        successCount++;
      } catch (error) {
        console.warn('[ZipExportService] Error processing chat for bulk download:', chat.chat_id, error);
      }
    }

    if (successCount === 0) {
      throw new Error('No chats could be downloaded');
    }

    // Generate and download zip
    const zipBlob = await zip.generateAsync({ type: 'blob' });
    const url = URL.createObjectURL(zipBlob);
    const link = document.createElement('a');
    link.href = url;

    // Use current date/time for bulk download filename
    const now = new Date();
    const zipDateStr = now.toISOString().slice(0, 19).replace(/[:-]/g, '-').replace('T', '_');
    link.download = `chats_${zipDateStr}.zip`;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    console.debug('[ZipExportService] Bulk zip download completed:', successCount, 'chats');
  } catch (error) {
    console.error('[ZipExportService] Error in bulk zip download:', error);
    throw error;
  }
}

/**
 * Downloads a code file with appropriate naming
 */
export async function downloadCodeFile(
  codeContent: string,
  language: string,
  filename?: string
): Promise<void> {
  try {
    console.debug('[ZipExportService] Downloading code file:', { language, filename });

    // Determine filename
    let downloadFilename: string;
    if (filename) {
      downloadFilename = filename;
    } else {
      const ext = getFileExtensionForLanguage(language);
      downloadFilename = `code_snippet.${ext}`;
    }

    // Create blob and download
    const blob = new Blob([codeContent], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = downloadFilename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    console.debug('[ZipExportService] Code file download completed:', downloadFilename);
  } catch (error) {
    console.error('[ZipExportService] Error downloading code file:', error);
    throw new Error('Failed to download code file');
  }
}
