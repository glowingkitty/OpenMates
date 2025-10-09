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
 */
async function convertChatToYaml(chat: Chat, messages: Message[]): Promise<string> {
    const yamlData: any = {
        chat: {
            title: null,
            exported_at: new Date().toISOString(),
            message_count: messages.length,
            draft: null
        },
        messages: []
    };
    
    // Try to get decrypted title from cache
    const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
    if (metadata?.title) {
        yamlData.chat.title = metadata.title;
        console.debug('[ChatExportService] Using decrypted title:', metadata.title);
    } else {
        console.warn('[ChatExportService] Could not decrypt title for YAML export');
    }
    
    // Add draft if present
    if (chat.encrypted_draft_md) {
        try {
            const { decryptWithMasterKey } = await import('./cryptoService');
            const decryptedDraft = decryptWithMasterKey(chat.encrypted_draft_md);
            if (decryptedDraft) {
                yamlData.chat.draft = decryptedDraft;
                console.debug('[ChatExportService] Successfully included draft in export');
            } else {
                console.warn('[ChatExportService] Could not decrypt draft for YAML export');
            }
        } catch (error) {
            console.error('[ChatExportService] Error decrypting draft:', error);
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
            timestamp: new Date(message.created_at * 1000).toISOString() // Fix timestamp conversion
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
            timestamp: new Date(message.created_at * 1000).toISOString(),
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
