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
 * Gets all code embeds from a chat
 */
async function getCodeEmbedsForChat(messages: Message[]): Promise<Array<{
  embed_id: string;
  language: string;
  filename?: string;
  content: string;
  file_path?: string;
}>> {
  try {
    const codeEmbeds: Array<{
      embed_id: string;
      language: string;
      filename?: string;
      content: string;
      file_path?: string;
    }> = [];

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
        if (ref.type === 'code' && !embedRefs.has(ref.embed_id)) {
          embedRefs.set(ref.embed_id, ref);
        }
      }
    }

    if (embedRefs.size === 0) {
      return codeEmbeds;
    }

    // Load embeds
    const embedIds = Array.from(embedRefs.keys());
    const loadedEmbeds = await loadEmbeds(embedIds);

    // Process code embeds
    for (const embed of loadedEmbeds) {
      if (embed.type !== 'code' || !embed.content) {
        continue;
      }

      try {
        const decodedContent = await decodeToonContent(embed.content);

        // Extract code content and metadata
        if (decodedContent && typeof decodedContent === 'object') {
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
      } catch (error) {
        console.warn('[ZipExportService] Error processing code embed:', embed.embed_id, error);
      }
    }

    return codeEmbeds;
  } catch (error) {
    console.error('[ZipExportService] Error getting code embeds:', error);
    return [];
  }
}

/**
 * Gets all video transcript embeds from a chat
 * Extracts video transcript embeds (app_skill_use with app_id='videos' and skill_id='get_transcript')
 * and formats them as markdown files similar to VideoTranscriptEmbedFullscreen handleDownload
 */
async function getVideoTranscriptEmbedsForChat(messages: Message[]): Promise<Array<{
  embed_id: string;
  filename: string;
  content: string;
}>> {
  try {
    const transcriptEmbeds: Array<{
      embed_id: string;
      filename: string;
      content: string;
    }> = [];

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
        // Look for app_skill_use embeds (video transcript embeds are of this type)
        if (ref.type === 'app_skill_use' && !embedRefs.has(ref.embed_id)) {
          embedRefs.set(ref.embed_id, ref);
        }
      }
    }

    if (embedRefs.size === 0) {
      return transcriptEmbeds;
    }

    // Load embeds
    const embedIds = Array.from(embedRefs.keys());
    const loadedEmbeds = await loadEmbeds(embedIds);

    // Process video transcript embeds
    for (const embed of loadedEmbeds) {
      // Only process app_skill_use embeds
      if (embed.type !== 'app_skill_use' || !embed.content) {
        continue;
      }

      try {
        const decodedContent = await decodeToonContent(embed.content);

        // Check if this is a video transcript embed (app_id='videos' and skill_id='get_transcript' or 'get-transcript')
        if (
          decodedContent &&
          typeof decodedContent === 'object' &&
          decodedContent.app_id === 'videos' &&
          (decodedContent.skill_id === 'get_transcript' || decodedContent.skill_id === 'get-transcript')
        ) {
          // Extract results array from decoded content
          // Results can be in various formats: results, data, or directly in the content
          const results = decodedContent.results || decodedContent.data || [];
          
          if (!Array.isArray(results) || results.length === 0) {
            console.debug('[ZipExportService] Video transcript embed has no results:', embed.embed_id);
            continue;
          }

          // Format transcript as markdown (same format as VideoTranscriptEmbedFullscreen handleDownload)
          const transcriptText = results
            .filter((r: any) => {
              // Check various possible field names for transcript
              return r.transcript || r.formatted_transcript || r.text || r.content;
            })
            .map((r: any, index: number) => {
              let content = '';
              
              // Add title if available
              if (r.metadata?.title) {
                content += `# ${r.metadata.title}\n\n`;
              }
              
              // Add source URL if available
              if (r.url) {
                content += `Source: ${r.url}\n\n`;
              }
              
              // Add word count if available
              if (r.word_count) {
                content += `Word count: ${r.word_count.toLocaleString()}\n\n`;
              }
              
              // Add transcript text (check various possible field names)
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
              // Extract video ID from URL for filename
              try {
                const urlObj = new URL(firstResult.url);
                const videoId = urlObj.searchParams.get('v') || urlObj.pathname.split('/').pop() || 'video';
                filename = `${videoId}_transcript.md`;
              } catch (e) {
                // If URL parsing fails, use embed_id
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
      } catch (error) {
        console.warn('[ZipExportService] Error processing video transcript embed:', embed.embed_id, error);
      }
    }

    return transcriptEmbeds;
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
