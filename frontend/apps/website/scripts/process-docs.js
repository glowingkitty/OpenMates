#!/usr/bin/env node

/**
 * Markdown Documentation Processor
 * 
 * This script processes markdown files from /docs directory and converts them
 * into a structured JSON format for the website's documentation system.
 * 
 * Features:
 * - Recursively scans /docs directory
 * - Generates navigation structure
 * - Preserves markdown content for rendering
 * - Creates metadata for each doc page
 * 
 * Runs during build process (vite build) and in dev mode
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Paths relative to script location
const DOCS_ROOT = path.resolve(__dirname, '../../../../docs');
const OUTPUT_DIR = path.resolve(__dirname, '../src/lib/generated');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'docs-data.json');

/**
 * Load .docsignore file and create ignore patterns
 * @param {string} docsRoot - Path to docs root directory
 * @returns {Array} Array of ignore patterns
 */
function loadDocsIgnore(docsRoot) {
    // Look for .docsignore in the docs directory
    const ignoreFile = path.join(docsRoot, '.docsignore');
    const patterns = [];
    
    if (fs.existsSync(ignoreFile)) {
        const content = fs.readFileSync(ignoreFile, 'utf-8');
        const lines = content.split('\n')
            .map(line => line.trim())
            .filter(line => line && !line.startsWith('#'));
        
        patterns.push(...lines);
    }
    
    return patterns;
}

/**
 * Check if a path should be ignored based on .docsignore patterns
 * @param {string} relativePath - Path to check
 * @param {Array} ignorePatterns - Array of ignore patterns
 * @returns {boolean} True if should be ignored
 */
function shouldIgnore(relativePath, ignorePatterns) {
    for (const pattern of ignorePatterns) {
        // Simple glob pattern matching
        if (pattern.includes('*')) {
            const regex = new RegExp(pattern.replace(/\*/g, '.*'));
            if (regex.test(relativePath)) {
                return true;
            }
        } else {
            // Handle patterns with and without trailing slashes
            const cleanPattern = pattern.replace(/\/$/, ''); // Remove trailing slash
            const cleanPath = relativePath.replace(/\/$/, ''); // Remove trailing slash
            
            // Exact match or directory match
            if (cleanPath === cleanPattern || relativePath.startsWith(cleanPattern + '/')) {
                return true;
            }
        }
    }
    return false;
}

/**
 * Process markdown content to fix image paths and relative links
 * @param {string} content - Original markdown content
 * @param {string} filePath - Path to the current file
 * @returns {string} Processed markdown content
 */
async function processMarkdownContent(content, filePath) {
    let processedContent = content;
    
    // Fix relative code file links BEFORE converting to HTML
    // Pattern: [text](./file.js) -> [text](https://github.com/glowingkitty/OpenMates/blob/main/file.js)
    // Pattern: [text](../../folder/file.ts) -> [text](https://github.com/glowingkitty/OpenMates/blob/main/folder/file.ts)
    processedContent = processedContent.replace(
        /\[([^\]]+)\]\(([^)]+\.(js|ts|py|java|cpp|c|h|go|rs|php|rb|swift|kt|scala|r|sql|sh|bash|yaml|yml|json|xml|html|css|scss|sass|less|vue|svelte|jsx|tsx))\)/g,
        (match, linkText, filePath, ext) => {
            // Skip if already absolute or external
            if (filePath.startsWith('http') || filePath.startsWith('/')) {
                return match;
            }
            
            // Clean up relative path - remove ALL ../ and ./
            let cleanPath = filePath;
            while (cleanPath.includes('../')) {
                cleanPath = cleanPath.replace('../', '');
            }
            cleanPath = cleanPath.replace(/\.\//g, ''); // Remove all ./
            cleanPath = cleanPath.replace(/\\/g, '/'); // Normalize path separators
            
            const githubUrl = `https://github.com/glowingkitty/OpenMates/blob/main/${cleanPath}`;
            return `[${linkText}](${githubUrl})`;
        }
    );
    
    // Fix relative markdown links: convert .md links to website routes
    // Pattern: [text](./other-file.md) -> [text](/docs/architecture/other-file)
    // Pattern: [text](../folder/file.md) -> [text](/docs/folder/file)
    processedContent = processedContent.replace(
        /\[([^\]]+)\]\(([^)]+\.md)\)/g,
        (match, linkText, mdPath) => {
            // Skip if already absolute or external
            if (mdPath.startsWith('http') || mdPath.startsWith('/')) {
                return match;
            }
            
            // Get the current file's directory
            const currentDir = path.dirname(filePath).replace(/\\/g, '/');
            const docsRoot = path.resolve(__dirname, '../../../../docs').replace(/\\/g, '/');
            const relativeToDocs = currentDir.replace(docsRoot, '').replace(/^\//, '');
            
            // Resolve the relative path
            let resolvedPath;
            if (mdPath.startsWith('./')) {
                // Same directory: ./file.md -> currentDir/file
                resolvedPath = relativeToDocs ? `${relativeToDocs}/${mdPath.replace('./', '').replace('.md', '')}` : mdPath.replace('./', '').replace('.md', '');
            } else if (mdPath.startsWith('../')) {
                // Parent directory: ../file.md -> parentDir/file
                const parentDir = relativeToDocs.split('/').slice(0, -1).join('/');
                resolvedPath = parentDir ? `${parentDir}/${mdPath.replace('../', '').replace('.md', '')}` : mdPath.replace('../', '').replace('.md', '');
            } else {
                // No prefix: file.md -> currentDir/file
                resolvedPath = relativeToDocs ? `${relativeToDocs}/${mdPath.replace('.md', '')}` : mdPath.replace('.md', '');
            }
            
            // Clean up the path
            resolvedPath = resolvedPath.replace(/\\/g, '/').replace(/\/+/g, '/').replace(/^\//, '');
            
            const websiteRoute = `/docs/${resolvedPath}`;
            return `[${linkText}](${websiteRoute})`;
        }
    );
    
    // Convert markdown to HTML at build time
    const { marked } = await import('marked');
    
    // Configure marked options
    marked.setOptions({
        gfm: true, // GitHub Flavored Markdown
        breaks: true, // Convert \n to <br>
        headerIds: true, // Generate IDs for headings
        headerPrefix: '', // No prefix for IDs
    });
    
    // Convert markdown to HTML
    processedContent = marked(processedContent);
    
    // Ensure all headings have proper IDs for anchor links
    processedContent = processedContent.replace(
        /<h([1-6])>([^<]+)<\/h[1-6]>/g,
        (match, level, text) => {
            // Create a URL-friendly ID from the heading text
            const id = text
                .toLowerCase()
                .replace(/[^a-z0-9\s-]/g, '') // Remove special characters
                .replace(/\s+/g, '-') // Replace spaces with hyphens
                .replace(/-+/g, '-') // Replace multiple hyphens with single
                .replace(/^-|-$/g, ''); // Remove leading/trailing hyphens
            
            return `<h${level} id="${id}">${text}</h${level}>`;
        }
    );
    
    // Fix image paths in HTML: convert relative paths to static file paths
    // Pattern: <img src="relative/path/to/image.jpg"> -> <img src="/docs/relative/path/to/image.jpg">
    // Pattern: <img src="/images/..."> -> <img src="/docs/images/...">
    processedContent = processedContent.replace(
        /<img([^>]*?)src="([^"]*?)"([^>]*?)>/g,
        (match, before, imagePath, after) => {
            let newImagePath = imagePath;
            
            // Skip if external URL
            if (imagePath.startsWith('http://') || imagePath.startsWith('https://')) {
                return match;
            }
            
            // If path starts with /images, convert to /docs/images
            if (imagePath.startsWith('/images')) {
                newImagePath = `/docs${imagePath}`;
            }
            // If already starts with /docs, keep it
            else if (imagePath.startsWith('/docs')) {
                newImagePath = imagePath;
            }
            // Handle relative paths like ../../images/... or ./images/...
            else if (imagePath.includes('images/')) {
                // Extract the images/... part from relative paths
                const imagesMatch = imagePath.match(/images\/.*$/);
                if (imagesMatch) {
                    newImagePath = `/docs/images/${imagesMatch[0].substring(7)}`; // Remove 'images/' prefix
                }
            }
            // Convert relative path to static file path
            else {
                newImagePath = `/docs/${imagePath}`;
            }
            
            // Add inline styles to ensure images are properly sized
            const inlineStyles = 'style="max-width: 100%; width: auto; height: auto; border-radius: 8px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1); margin: 1rem 0; display: block;"';
            
            return `<img${before}src="${newImagePath}"${inlineStyles}${after}>`;
        }
    );
    
    return processedContent;
}

/**
 * Recursively reads directory structure and builds navigation tree
 * @param {string} dir - Directory path to scan
 * @param {string} relativePath - Relative path from docs root
 * @param {Array} ignorePatterns - Patterns to ignore
 * @returns {Object} Navigation structure with files and folders
 */
async function buildDocsStructure(dir, relativePath = '', ignorePatterns = []) {
    const items = fs.readdirSync(dir, { withFileTypes: true });
    const structure = {
        files: [],
        folders: []
    };

    for (const item of items) {
        const itemPath = path.join(dir, item.name);
        const itemRelativePath = path.join(relativePath, item.name);

        // Check if this item should be ignored
        if (shouldIgnore(itemRelativePath, ignorePatterns)) {
            continue;
        }

        if (item.isDirectory()) {
            // Skip node_modules, hidden directories, and other build artifacts
            if (item.name.startsWith('.') || item.name === 'node_modules') {
                continue;
            }

            // Check if this folder should be ignored BEFORE processing
            if (shouldIgnore(itemRelativePath, ignorePatterns)) {
                continue;
            }

            const folderStructure = await buildDocsStructure(itemPath, itemRelativePath, ignorePatterns);
            
            // Only add folder if it has content (files or subfolders)
            if (folderStructure.files.length > 0 || folderStructure.folders.length > 0) {
                structure.folders.push({
                    name: item.name,
                    path: itemRelativePath,
                    ...folderStructure
                });
            }
        } else if (item.isFile() && item.name.endsWith('.md')) {
            // Read markdown content
            let content = fs.readFileSync(itemPath, 'utf-8');
            
            // Process content: fix image paths and relative links
            content = await processMarkdownContent(content, itemRelativePath);
            
            // Extract title from first # heading or use filename
            const titleMatch = content.match(/^#\s+(.+)$/m);
            const title = titleMatch ? titleMatch[1] : item.name.replace('.md', '');

            structure.files.push({
                name: item.name,
                title: title,
                path: itemRelativePath,
                content: content,
                slug: itemRelativePath.replace(/\.md$/, '').replace(/\\/g, '/')
            });
        }
    }

    // Sort folders and files alphabetically
    structure.folders.sort((a, b) => a.name.localeCompare(b.name));
    structure.files.sort((a, b) => a.name.localeCompare(b.name));

    return structure;
}

/**
 * Main execution function
 */
async function main() {
    console.log('📚 Processing documentation files...');
    console.log(`📂 Docs root: ${DOCS_ROOT}`);
    
    if (!fs.existsSync(DOCS_ROOT)) {
        console.error(`❌ Error: Docs directory not found at ${DOCS_ROOT}`);
        process.exit(1);
    }

    // Load ignore patterns
    const ignorePatterns = loadDocsIgnore(DOCS_ROOT);
    console.log(`📋 Ignore patterns: ${ignorePatterns.length} patterns loaded`);
    
    // Build the documentation structure
    const docsStructure = await buildDocsStructure(DOCS_ROOT, '', ignorePatterns);

    // Create output directory if it doesn't exist
    if (!fs.existsSync(OUTPUT_DIR)) {
        fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    }

    // Write the JSON file
    const output = {
        generated: new Date().toISOString(),
        structure: docsStructure
    };

    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));
    
    console.log(`✅ Documentation processed successfully!`);
    console.log(`📝 Output: ${OUTPUT_FILE}`);
    console.log(`📊 Total files: ${countFiles(docsStructure)}`);
    console.log(`📁 Total folders: ${countFolders(docsStructure)}`);
}

/**
 * Count total files in structure
 */
function countFiles(structure) {
    let count = structure.files.length;
    for (const folder of structure.folders) {
        count += countFiles(folder);
    }
    return count;
}

/**
 * Count total folders in structure
 */
function countFolders(structure) {
    let count = structure.folders.length;
    for (const folder of structure.folders) {
        count += countFolders(folder);
    }
    return count;
}

// Execute main function
main();

