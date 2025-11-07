/**
 * Chat Export Service
 * Handles exporting chat content as markdown files
 */

import { chatDB } from './db';
import { chatMetadataCache } from './chatMetadataCache';
import { tipTapToCanonicalMarkdown } from '../message_parsing/serializers';
import type { Chat, Message } from '../types/chat';

/**
 * Downloads a chat as a YAML file
 * @param chat - The chat to download
 * @param messages - Array of messages in the chat
 */
export async function downloadChatAsYaml(chat: Chat, messages: Message[]): Promise<void> {
    try {
        console.debug('[ChatExportService] Starting chat download:', {
            chatId: chat.chat_id,
            messageCount: messages.length,
            hasEncryptedTitle: !!chat.encrypted_title
        });

        // Generate filename with date, time, and title
        const filename = await generateChatFilename(chat, 'yaml');
        
        // Convert chat and messages to YAML
        const yamlContent = await convertChatToYaml(chat, messages);
        
        // Create and download the file
        downloadYamlFile(yamlContent, filename);
        
        console.debug('[ChatExportService] Chat download completed successfully');
    } catch (error) {
        console.error('[ChatExportService] Error downloading chat:', error);
        throw new Error('Failed to download chat');
    }
}

/**
 * Generates a filename for the chat export
 * Format: YYYY-MM-DD_HH-MM-SS_[title].yaml
 */
async function generateChatFilename(chat: Chat, extension: string = 'yaml'): Promise<string> {
    const now = new Date();
    const dateStr = now.toISOString().slice(0, 19).replace(/[:-]/g, '-').replace('T', '_');
    
    let title = 'Untitled Chat';
    
    // Try to get decrypted title from cache (handles both chat-key and master-key decryption)
    const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
    if (metadata?.title) {
        // Sanitize title for filename (remove invalid characters)
        title = metadata.title
            .replace(/[<>:"/\\|?*]/g, '') // Remove invalid filename characters
            .substring(0, 50) // Limit length
            .trim();
        console.debug('[ChatExportService] Using decrypted title from cache:', title);
    } else {
        console.warn('[ChatExportService] Could not decrypt title, using default');
    }
    
    return `${dateStr}_${title}.${extension}`;
}

/**
 * Converts a chat and its messages to YAML format
 * @param chat - The chat to convert
 * @param messages - Array of messages
 * @param includeLink - Whether to include the shareable link in the YAML (default: false for downloads, true for clipboard)
 */
async function convertChatToYaml(chat: Chat, messages: Message[], includeLink: boolean = false): Promise<string> {
    const yamlData: any = {
        chat: {
            title: null,
            exported_at: new Date().toISOString(),
            message_count: messages.length,
            draft: null
        },
        messages: []
    };
    
    // Add chat link at the top if requested (for clipboard copy)
    if (includeLink) {
        yamlData.chat.link = generateChatLink(chat.chat_id);
        console.debug('[ChatExportService] Including chat link in YAML:', yamlData.chat.link);
    }
    
    // Try to get decrypted title from cache
    const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
    if (metadata?.title) {
        yamlData.chat.title = metadata.title;
        console.debug('[ChatExportService] Using decrypted title:', metadata.title);
    } else {
        console.warn('[ChatExportService] Could not decrypt title for YAML export');
    }
    
    // Add draft if present
    // CRITICAL: Handle both encrypted drafts (authenticated users) and cleartext drafts (non-authenticated sessionStorage)
    if (chat.encrypted_draft_md) {
        try {
            // Check if this is a cleartext draft from sessionStorage (non-authenticated users)
            // Cleartext drafts don't start with encryption markers and are shorter
            // For sessionStorage drafts, encrypted_draft_md actually contains cleartext markdown
            const isCleartextDraft = !chat.encrypted_draft_md.includes('encrypted:') && 
                                     !chat.encrypted_draft_md.startsWith('v1:') &&
                                     chat.encrypted_draft_md.length < 1000; // Rough heuristic
            
            if (isCleartextDraft) {
                // This is a cleartext draft from sessionStorage - use it directly
                yamlData.chat.draft = chat.encrypted_draft_md;
                console.debug('[ChatExportService] Included cleartext draft from sessionStorage in export');
            } else {
                // This is an encrypted draft - decrypt it
                const { decryptWithMasterKey } = await import('./cryptoService');
                const decryptedDraft = decryptWithMasterKey(chat.encrypted_draft_md);
                if (decryptedDraft) {
                    yamlData.chat.draft = decryptedDraft;
                    console.debug('[ChatExportService] Successfully included encrypted draft in export');
                } else {
                    console.warn('[ChatExportService] Could not decrypt draft for YAML export');
                }
            }
        } catch (error) {
            console.error('[ChatExportService] Error processing draft:', error);
        }
    }
    
    // Add messages
    for (const message of messages) {
        const messageData = await convertMessageToYaml(message);
        yamlData.messages.push(messageData);
    }
    
    return convertToYamlString(yamlData);
}

/**
 * Converts a single message to YAML format
 */
async function convertMessageToYaml(message: Message): Promise<any> {
    try {
        const messageData: any = {
            role: message.role,
            completed_at: new Date(message.created_at * 1000).toISOString() // When the message was completed
        };
        
        // Add assistant category if available
        if (message.role === 'assistant' && message.category) {
            messageData.assistant_category = message.category;
        }
        
        // Process message content
        if (typeof message.content === 'string') {
            // Simple text content
            messageData.content = message.content;
        } else if (message.content && typeof message.content === 'object') {
            // TipTap JSON content - convert to markdown for YAML
            const markdown = await convertTiptapToMarkdown(message.content);
            messageData.content = markdown;
        } else {
            messageData.content = '';
        }
        
        return messageData;
    } catch (error) {
        console.error('[ChatExportService] Error processing message:', error);
        return {
            role: message.role,
            completed_at: new Date(message.created_at * 1000).toISOString(),
            content: '[Error processing message]'
        };
    }
}

/**
 * Converts TipTap JSON content to markdown
 * This is a simplified version - you might want to use a more robust converter
 */
async function convertTiptapToMarkdown(content: any): Promise<string> {
    if (!content || !content.content) {
        return '';
    }
    
    try {
        // Use the existing tipTapToCanonicalMarkdown function to convert TipTap to markdown
        const markdown = tipTapToCanonicalMarkdown(content);
        return markdown || '';
    } catch (error) {
        console.error('[ChatExportService] Error converting TipTap to markdown:', error);
        return '*[Error converting content]*';
    }
}

/**
 * Converts JavaScript object to YAML string
 */
function convertToYamlString(data: any): string {
    // Simple YAML conversion - in production you might want to use a proper YAML library
    const yamlLines: string[] = [];
    
    function convertValue(key: string, value: any, indent: number = 0): void {
        const spaces = '  '.repeat(indent);
        
        if (value === null || value === undefined) {
            yamlLines.push(`${spaces}${key}: null`);
        } else if (typeof value === 'string') {
            // Handle multiline strings
            if (value.includes('\n')) {
                yamlLines.push(`${spaces}${key}: |`);
                const lines = value.split('\n');
                for (const line of lines) {
                    yamlLines.push(`${spaces}  ${line}`);
                }
            } else {
                yamlLines.push(`${spaces}${key}: "${value}"`);
            }
        } else if (typeof value === 'number' || typeof value === 'boolean') {
            yamlLines.push(`${spaces}${key}: ${value}`);
        } else if (Array.isArray(value)) {
            yamlLines.push(`${spaces}${key}:`);
            for (const item of value) {
                if (typeof item === 'object') {
                    yamlLines.push(`${spaces}  -`);
                    for (const [itemKey, itemValue] of Object.entries(item)) {
                        convertValue(itemKey, itemValue, indent + 2);
                    }
                } else {
                    yamlLines.push(`${spaces}  - ${item}`);
                }
            }
        } else if (typeof value === 'object') {
            yamlLines.push(`${spaces}${key}:`);
            for (const [objKey, objValue] of Object.entries(value)) {
                convertValue(objKey, objValue, indent + 1);
            }
        }
    }
    
    for (const [key, value] of Object.entries(data)) {
        convertValue(key, value);
    }
    
    return yamlLines.join('\n');
}

/**
 * Generates a shareable link for a chat
 * Format: {domain}/#chat_id={id}
 * @param chatId - The chat ID
 * @returns The shareable link
 */
export function generateChatLink(chatId: string): string {
    // Use window.location.origin to get current domain dynamically
    const baseUrl = window.location.origin;
    const link = `${baseUrl}/#chat_id=${chatId}`;
    
    console.debug('[ChatExportService] Generated chat link:', {
        chatId,
        link
    });
    
    return link;
}

/**
 * Copies chat to clipboard as YAML with embedded link wrapped in a markdown code block
 * When pasted inside OpenMates, only the link is used
 * When pasted outside, the full YAML is available in a formatted code block
 * @param chat - The chat to copy
 * @param messages - Array of messages in the chat
 */
export async function copyChatToClipboard(chat: Chat, messages: Message[]): Promise<void> {
    try {
        console.debug('[ChatExportService] Copying chat to clipboard:', {
            chatId: chat.chat_id,
            messageCount: messages.length
        });
        
        // Generate YAML with embedded link
        const yamlContent = await convertChatToYaml(chat, messages, true);
        
        // Wrap YAML content in a markdown code block for better formatting when pasted
        const codeBlock = `\`\`\`yaml\n${yamlContent}\n\`\`\``;
        
        // Try modern clipboard API first (works on most browsers)
        if (navigator.clipboard && navigator.clipboard.writeText) {
            try {
                await navigator.clipboard.writeText(codeBlock);
                console.debug('[ChatExportService] Chat copied to clipboard successfully using modern API');
                return;
            } catch (clipboardError) {
                console.warn('[ChatExportService] Modern clipboard API failed, trying fallback:', clipboardError);
            }
        }
        
        // Fallback for iOS Safari and older browsers
        await fallbackCopyToClipboard(codeBlock);
        
        console.debug('[ChatExportService] Chat copied to clipboard successfully using fallback method');
    } catch (error) {
        console.error('[ChatExportService] Error copying to clipboard:', error);
        throw new Error('Failed to copy to clipboard');
    }
}

/**
 * Fallback clipboard method for iOS Safari and older browsers
 * Uses the deprecated but more compatible execCommand approach
 * @param text - Text to copy to clipboard
 */
async function fallbackCopyToClipboard(text: string): Promise<void> {
    return new Promise((resolve, reject) => {
        // Create a temporary textarea element
        const textArea = document.createElement('textarea');
        textArea.value = text;
        
        // Make it invisible but still focusable
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        textArea.style.opacity = '0';
        textArea.style.pointerEvents = 'none';
        textArea.setAttribute('readonly', '');
        
        // Add to DOM, select, and copy
        document.body.appendChild(textArea);
        
        try {
            // For iOS Safari, we need to focus and select the text
            textArea.focus();
            textArea.select();
            textArea.setSelectionRange(0, text.length);
            
            // Execute copy command
            const successful = document.execCommand('copy');
            
            if (successful) {
                console.debug('[ChatExportService] Fallback copy successful');
                resolve();
            } else {
                throw new Error('execCommand copy failed');
            }
        } catch (error) {
            console.error('[ChatExportService] Fallback copy failed:', error);
            reject(error);
        } finally {
            // Clean up
            document.body.removeChild(textArea);
        }
    });
}

/**
 * Creates and triggers download of a YAML file
 */
function downloadYamlFile(content: string, filename: string): void {
    // Create blob with YAML content
    const blob = new Blob([content], { type: 'text/yaml;charset=utf-8' });
    
    // Create download link
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    
    // Trigger download
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    // Clean up
    URL.revokeObjectURL(url);
}

/**
 * TODO: Future implementation for file attachments
 * This function will handle downloading files associated with the chat
 * when file upload functionality is implemented
 */
export async function downloadChatFiles(chatId: string): Promise<void> {
    // TODO: Implement file download functionality
    // This will be called when file uploads are implemented
    console.debug('[ChatExportService] File download not yet implemented for chat:', chatId);
    
    // Placeholder implementation:
    // 1. Get list of files associated with the chat
    // 2. Download each file
    // 3. Create a zip archive if multiple files
    // 4. Trigger download of the archive
    
    // Example structure:
    // const files = await getChatFiles(chatId);
    // if (files.length > 0) {
    //     await downloadFilesAsZip(files, `${chatId}_files.zip`);
    // }
}
