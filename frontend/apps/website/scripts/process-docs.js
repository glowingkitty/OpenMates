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
    
    // Convert markdown to HTML at build time
    const { marked } = await import('marked');
    
    // Configure marked options
    marked.setOptions({
        gfm: true, // GitHub Flavored Markdown
        breaks: true, // Convert \n to <br>
    });
    
    // Convert markdown to HTML
    processedContent = marked(processedContent);
    
    // Fix image paths in HTML: convert relative paths to static file paths
    // Pattern: <img src="relative/path/to/image.jpg"> -> <img src="/docs/relative/path/to/image.jpg">
    // Pattern: <img src="/images/..."> -> <img src="/docs/images/...">
    processedContent = processedContent.replace(
        /<img([^>]*?)src="([^"]*?)"([^>]*?)>/g,
        (match, before, imagePath, after) => {
            // Skip if external URL
            if (imagePath.startsWith('http://') || imagePath.startsWith('https://')) {
                return match;
            }
            
            // If path starts with /images, convert to /docs/images
            if (imagePath.startsWith('/images')) {
                const staticPath = `/docs${imagePath}`;
                return `<img${before}src="${staticPath}"${after}>`;
            }
            
            // If already starts with /docs, keep it
            if (imagePath.startsWith('/docs')) {
                return match;
            }
            
            // Handle relative paths like ../../images/... or ./images/...
            if (imagePath.includes('images/')) {
                // Extract the images/... part from relative paths
                const imagesMatch = imagePath.match(/images\/.*$/);
                if (imagesMatch) {
                    const staticPath = `/docs/images/${imagesMatch[0].substring(7)}`; // Remove 'images/' prefix
                    return `<img${before}src="${staticPath}"${after}>`;
                }
            }
            
            // Convert relative path to static file path
            const staticPath = `/docs/${imagePath}`;
            return `<img${before}src="${staticPath}"${after}>`;
        }
    );
    
    // Fix relative markdown links: convert .md links to website routes
    // Pattern: [text](./other-file.md) -> [text](/docs/other-file)
    // Pattern: [text](../folder/file.md) -> [text](/docs/folder/file)
    processedContent = processedContent.replace(
        /\[([^\]]+)\]\(([^)]+\.md)\)/g,
        (match, linkText, mdPath) => {
            // Skip if already absolute or external
            if (mdPath.startsWith('http') || mdPath.startsWith('/')) {
                return match;
            }
            
            // Convert relative .md path to website route
            const routePath = mdPath
                .replace(/\.md$/, '') // Remove .md extension
                .replace(/^\.\//, '') // Remove ./ prefix
                .replace(/^\.\.\//, '') // Remove ../ prefix
                .replace(/\\/g, '/'); // Normalize path separators
            
            const websiteRoute = `/docs/${routePath}`;
            return `[${linkText}](${websiteRoute})`;
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

