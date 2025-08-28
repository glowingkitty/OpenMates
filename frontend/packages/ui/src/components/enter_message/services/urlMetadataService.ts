// Service for fetching URL metadata from preview.openmates.org
// Handles website metadata retrieval and caching

export interface UrlMetadata {
    type: 'website';
    url: string;
    title: string;
    description: string;
    favicon?: string;
    image?: string;
}

/**
 * Fetches metadata for a given URL from preview.openmates.org
 * @param url The URL to fetch metadata for
 * @returns Promise with metadata or null if failed
 * 
 * TODO: Implement the preview endpoint at preview.openmates.org/api/metadata
 * Currently the endpoint is not available, so this will always return null
 */
export async function fetchUrlMetadata(url: string): Promise<UrlMetadata | null> {
    try {
        console.debug('[urlMetadataService] Fetching metadata for URL:', url);
        
        // Make request to preview.openmates.org
        const response = await fetch(`https://preview.openmates.org/api/metadata`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url })
        });
        
        if (!response.ok) {
            console.warn('[urlMetadataService] Failed to fetch metadata:', response.status, response.statusText);
            return null;
        }
        
        const data = await response.json();
        
        // Validate the response structure
        if (!data || typeof data.title !== 'string' || typeof data.description !== 'string') {
            console.warn('[urlMetadataService] Invalid metadata response:', data);
            return null;
        }
        
        const metadata: UrlMetadata = {
            type: 'website',
            url: url,
            title: data.title,
            description: data.description,
            favicon: data.favicon,
            image: data.image
        };
        
        console.info('[urlMetadataService] Successfully fetched metadata:', {
            url,
            title: metadata.title.substring(0, 50) + '...',
            description: metadata.description.substring(0, 100) + '...'
        });
        
        return metadata;
        
    } catch (error) {
        console.error('[urlMetadataService] Error fetching URL metadata:', error);
        return null;
    }
}

/**
 * Creates a JSON code block markdown for the given URL metadata
 * @param metadata The URL metadata to serialize
 * @returns Markdown string with JSON code block format
 */
export function createJsonCodeBlock(metadata: UrlMetadata): string {
    const jsonContent = JSON.stringify(metadata, null, 2);
    return `\n\`\`\`json\n${jsonContent}\n\`\`\`\n`;
}

/**
 * Extracts URL from a JSON code block if it contains website metadata
 * @param jsonBlock The JSON code block content
 * @returns Original URL or null if not a valid website JSON block
 */
export function extractUrlFromJsonBlock(jsonBlock: string): string | null {
    try {
        // Remove the code block markers and parse JSON
        const cleanJson = jsonBlock.replace(/```json\n?|\n?```/g, '').trim();
        const parsed = JSON.parse(cleanJson);
        
        if (parsed.type === 'website' && typeof parsed.url === 'string') {
            return parsed.url;
        }
        
        return null;
    } catch (error) {
        return null;
    }
}
