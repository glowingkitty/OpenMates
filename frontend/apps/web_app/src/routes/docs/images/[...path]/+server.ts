/**
 * Static Image Server for Documentation
 * 
 * Serves images from /docs/images/* directory.
 * This allows markdown docs to reference images with paths like:
 * ![alt](/docs/images/apps/code/example.jpg)
 */
import { error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import fs from 'fs';
import path from 'path';

// Map file extensions to MIME types
const MIME_TYPES: Record<string, string> = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.webp': 'image/webp',
    '.ico': 'image/x-icon'
};

/**
 * GET handler for serving documentation images
 * 
 * Reads image files from the docs/images directory and serves them
 * with appropriate MIME types and caching headers.
 */
export const GET: RequestHandler = async ({ params }) => {
    const imagePath = params.path;
    
    if (!imagePath) {
        throw error(404, 'Image not found');
    }
    
    // Sanitize path to prevent directory traversal attacks
    const sanitizedPath = imagePath.replace(/\.\./g, '');
    
    // Build full path to the image
    // Path from web_app to docs/images
    const fullPath = path.resolve(
        process.cwd(),
        '../../docs/images',
        sanitizedPath
    );
    
    // Verify the file is within the docs/images directory
    const docsImagesDir = path.resolve(process.cwd(), '../../docs/images');
    if (!fullPath.startsWith(docsImagesDir)) {
        throw error(403, 'Access denied');
    }
    
    // Check if file exists
    if (!fs.existsSync(fullPath)) {
        throw error(404, 'Image not found');
    }
    
    // Get file extension and MIME type
    const ext = path.extname(fullPath).toLowerCase();
    const mimeType = MIME_TYPES[ext];
    
    if (!mimeType) {
        throw error(415, 'Unsupported media type');
    }
    
    // Read and serve the file
    try {
        const fileBuffer = fs.readFileSync(fullPath);
        
        return new Response(fileBuffer, {
            headers: {
                'Content-Type': mimeType,
                'Cache-Control': 'public, max-age=31536000, immutable', // Cache for 1 year
                'X-Content-Type-Options': 'nosniff'
            }
        });
    } catch (err) {
        console.error(`Error serving image ${imagePath}:`, err);
        throw error(500, 'Error reading image');
    }
};
