// Service for fetching URL metadata from preview.openmates.org
// Handles website metadata retrieval and caching

export interface UrlMetadata {
    type: 'website';
    url: string;
    title?: string;  // Optional - may not be available if metadata fetch fails
    description?: string;  // Optional - may not be available if metadata fetch fails
    favicon?: string;
    image?: string;
}

/**
 * Fetches metadata for a given URL from preview.openmates.org
 * Uses the /api/v1/metadata endpoint which extracts:
 * - Title (from og:title, twitter:title, or <title>)
 * - Description (from og:description, twitter:description, or meta description)
 * - Image (from og:image or twitter:image)  
 * - Favicon (link rel="icon", rel="shortcut icon")
 * - Site name (from og:site_name)
 * 
 * @param url The URL to fetch metadata for
 * @returns Promise with metadata or null if failed
 */
export async function fetchUrlMetadata(url: string): Promise<UrlMetadata | null> {
    try {
        console.debug('[urlMetadataService] Fetching metadata for URL:', url);
        
        // Make request to preview.openmates.org API v1 endpoint
        const response = await fetch(`https://preview.openmates.org/api/v1/metadata`, {
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
        
        // Validate the response structure - title and description are optional
        if (!data || typeof data !== 'object') {
            console.warn('[urlMetadataService] Invalid metadata response:', data);
            return null;
        }
        
        const metadata: UrlMetadata = {
            type: 'website',
            url: url,
            title: typeof data.title === 'string' ? data.title : undefined,
            description: typeof data.description === 'string' ? data.description : undefined,
            favicon: data.favicon,
            image: data.image
        };
        
        console.info('[urlMetadataService] Successfully fetched metadata:', {
            url,
            title: metadata.title?.substring(0, 50) + '...' || 'No title',
            description: metadata.description?.substring(0, 100) + '...' || 'No description'
        });
        
        return metadata;
        
    } catch (error) {
        console.error('[urlMetadataService] Error fetching URL metadata:', error);
        return null;
    }
}

/**
 * Creates a json_embed code block markdown for website metadata
 * Uses json_embed code block type to distinguish from regular JSON content
 * @param metadata The website metadata to serialize
 * @returns Markdown string with json_embed code block format
 */
export function createJsonEmbedCodeBlock(metadata: UrlMetadata): string {
    const jsonContent = JSON.stringify(metadata, null, 2);
    return `\`\`\`json_embed\n${jsonContent}\n\`\`\``;
}

/**
 * Creates website metadata for a URL with only the URL (for failed metadata fetch)
 * @param url The URL that failed to fetch metadata
 * @returns UrlMetadata object with only URL and type
 */
export function createWebsiteMetadataFromUrl(url: string): UrlMetadata {
    return {
        type: 'website',
        url: url
    };
}

/**
 * Extracts URL from a json_embed code block
 * @param jsonEmbedBlock The json_embed code block content
 * @returns Original URL or null if not a valid json_embed block
 */
export function extractUrlFromJsonEmbedBlock(jsonEmbedBlock: string): string | null {
    try {
        // Remove the code block markers and parse JSON
        const cleanJson = jsonEmbedBlock.replace(/```json_embed\n?|\n?```/g, '').trim();
        const parsed = JSON.parse(cleanJson);
        
        if (parsed.type === 'website' && typeof parsed.url === 'string') {
            return parsed.url;
        }
        
        return null;
    } catch {
        // JSON parsing failed - not a valid json_embed block
        return null;
    }
}

/**
 * Extracts website metadata from a json_embed code block
 * @param jsonEmbedBlock The json_embed code block content
 * @returns UrlMetadata or null if not a valid json_embed block
 */
export function parseJsonEmbedBlock(jsonEmbedBlock: string): UrlMetadata | null {
    try {
        // Remove the code block markers and parse JSON
        const cleanJson = jsonEmbedBlock.replace(/```json_embed\n?|\n?```/g, '').trim();
        const parsed = JSON.parse(cleanJson);
        
        if (parsed.type === 'website' && typeof parsed.url === 'string') {
            return parsed as UrlMetadata;
        }
        
        return null;
    } catch {
        // JSON parsing failed - not a valid json_embed block
        return null;
    }
}


