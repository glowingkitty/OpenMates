#!/usr/bin/env node

/**
 * Markdown Documentation Processor
 * 
 * This script processes markdown files from /docs directory and converts them
 * into a structured JSON format for the web app's documentation system.
 * 
 * Features:
 * - Recursively scans /docs directory
 * - Generates navigation structure (tree of folders and files)
 * - Preserves original markdown for copy functionality
 * - Converts markdown to HTML for rendering
 * - Respects .docsignore patterns
 * - Generates search index for FlexSearch
 * 
 * Output: src/lib/generated/docs-data.json
 * 
 * Runs during:
 * - Build process (vite build)
 * - Dev mode with file watching (vite dev)
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import MarkdownIt from 'markdown-it';
import hljs from 'highlight.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Paths relative to script location
const DOCS_ROOT = path.resolve(__dirname, '../../../../docs');
const OUTPUT_DIR = path.resolve(__dirname, '../src/lib/generated');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'docs-data.json');

// Initialize markdown-it with highlight.js for syntax highlighting
const md = new MarkdownIt({
    html: true,  // Allow HTML in markdown
    linkify: true,  // Auto-convert URLs to links
    typographer: true,  // Smart quotes and other typographic replacements
    highlight: function (str, lang) {
        // Syntax highlighting with highlight.js
        if (lang && hljs.getLanguage(lang)) {
            try {
                return `<pre><code class="hljs language-${lang}">${hljs.highlight(str, { language: lang }).value}</code></pre>`;
            } catch (__) {
                // Fall through to default
            }
        }
        // Use plain text for unknown languages
        return `<pre><code class="hljs">${md.utils.escapeHtml(str)}</code></pre>`;
    }
});

/**
 * Generate heading IDs for anchor links
 * Post-processes rendered HTML to add IDs to headings
 * @param {string} html - Rendered HTML content
 * @returns {string} HTML with heading IDs added
 */
function addHeadingIds(html) {
    return html.replace(/<h([1-6])>([^<]+)<\/h[1-6]>/g, (match, level, text) => {
        const id = text
            .toLowerCase()
            .replace(/[^a-z0-9\s-]/g, '')  // Remove special characters
            .replace(/\s+/g, '-')  // Replace spaces with hyphens
            .replace(/-+/g, '-')  // Replace multiple hyphens with single
            .replace(/^-|-$/g, '');  // Remove leading/trailing hyphens
        
        return `<h${level} id="${id}">${text}</h${level}>`;
    });
}

/**
 * Load .docsignore file and create ignore patterns
 * @param {string} docsRoot - Path to docs root directory
 * @returns {string[]} Array of ignore patterns
 */
function loadDocsIgnore(docsRoot) {
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
 * @param {string} relativePath - Path relative to docs root
 * @param {string[]} ignorePatterns - Array of ignore patterns
 * @returns {boolean} True if should be ignored
 */
function shouldIgnore(relativePath, ignorePatterns) {
    // Normalize path separators
    const normalizedPath = relativePath.replace(/\\/g, '/');
    
    for (const pattern of ignorePatterns) {
        // Handle glob patterns with *
        if (pattern.includes('*')) {
            const regex = new RegExp('^' + pattern.replace(/\*/g, '.*') + '$', 'i');
            if (regex.test(normalizedPath) || regex.test(path.basename(normalizedPath))) {
                return true;
            }
        } else {
            // Handle directory patterns (with or without trailing slash)
            const cleanPattern = pattern.replace(/\/$/, '');
            
            // Check if path matches pattern exactly or starts with pattern/
            if (normalizedPath === cleanPattern || 
                normalizedPath.startsWith(cleanPattern + '/') ||
                path.basename(normalizedPath) === cleanPattern) {
                return true;
            }
        }
    }
    return false;
}

/**
 * Fix links in markdown content without converting to HTML.
 * Handles: relative .md links → /docs/ routes, absolute app URLs → /docs/ routes,
 * relative code file links → GitHub links, relative image paths → /docs/images/.
 * @param {string} content - Original markdown content
 * @param {string} filePath - Path to the current file (relative to docs root)
 * @returns {string} Markdown with fixed links
 */
function fixMarkdownLinks(content, filePath) {
    let processedContent = content;

    // GitHub branch: use DOCS_GITHUB_BRANCH env var, or detect from Vercel/dev environment
    const githubBranch = process.env.DOCS_GITHUB_BRANCH
        || (process.env.VERCEL_GIT_COMMIT_REF === 'dev' ? 'dev' : null)
        || (process.env.NODE_ENV === 'development' ? 'dev' : 'main');

    // Fix absolute app URLs pointing to .md files
    // Pattern: [text](https://app.dev.openmates.org/docs/demo-chats.md) -> [text](/docs/demo-chats)
    // Also handles openmates.org (production) and any subdomain
    processedContent = processedContent.replace(
        /\[([^\]]+)\]\(https?:\/\/(?:app\.(?:dev\.)?)?openmates\.org\/docs\/([^)]+\.md(?:#[^)]*)?)\)/g,
        (match, linkText, mdPath) => {
            const [pathPart, ...anchorParts] = mdPath.split('#');
            const anchor = anchorParts.length ? `#${anchorParts.join('#')}` : '';
            const cleanPath = pathPart.replace(/\.md$/, '').replace(/\/+/g, '/').replace(/^\//, '');
            return `[${linkText}](/docs/${cleanPath}${anchor})`;
        }
    );

    // Fix relative code file links - convert to GitHub links
    // Pattern: [text](./file.js) -> [text](https://github.com/glowingkitty/OpenMates/blob/<branch>/file.js)
    const codeExtensions = 'js|ts|py|java|cpp|c|h|go|rs|php|rb|swift|kt|scala|r|sql|sh|bash|yaml|yml|json|xml|html|css|scss|sass|less|vue|svelte|jsx|tsx';
    const codeFileRegex = new RegExp(
        `\\[([^\\]]+)\\]\\(([^)]+\\.(${codeExtensions}))\\)`,
        'g'
    );

    processedContent = processedContent.replace(codeFileRegex, (match, linkText, codePath) => {
        // Skip absolute URLs
        if (codePath.startsWith('http') || codePath.startsWith('/')) {
            return match;
        }

        // Resolve relative path properly using the current file's directory
        const currentDir = path.dirname(filePath);
        const resolved = path.normalize(path.join(currentDir, codePath)).replace(/\\/g, '/');
        // Remove any leading docs/ prefix — code files are relative to project root
        // The filePath is relative to DOCS_ROOT, so ../backend/ from docs/architecture/core/
        // resolves to something like "backend/..." after normalization
        const cleanPath = resolved.replace(/^(\.\.\/)+/, '');

        const githubUrl = `https://github.com/glowingkitty/OpenMates/blob/${githubBranch}/${cleanPath}`;
        return `[${linkText}](${githubUrl})`;
    });

    // Fix relative markdown links - convert to website routes
    // Pattern: [text](./other-file.md) -> [text](/docs/architecture/other-file)
    // Supports multi-level relative paths (../../user-guide/apps/code.md)
    processedContent = processedContent.replace(
        /\[([^\]]+)\]\(([^)]+\.md(?:#[^)]*)?)\)/g,
        (match, linkText, mdPath) => {
            // Skip absolute URLs
            if (mdPath.startsWith('http') || mdPath.startsWith('/')) {
                return match;
            }

            // Separate anchor fragment from path
            const [pathPart, ...anchorParts] = mdPath.split('#');
            const anchor = anchorParts.length ? `#${anchorParts.join('#')}` : '';

            // Resolve relative path using Node's path module for proper multi-level handling
            const currentDir = path.dirname(filePath);
            const resolved = path.normalize(path.join(currentDir, pathPart)).replace(/\\/g, '/');

            // Remove .md extension and clean up
            let resolvedPath = resolved.replace(/\.md$/, '').replace(/\/+/g, '/').replace(/^\//, '');

            // README/index files map to the folder path (e.g., user-guide/README → user-guide)
            resolvedPath = resolvedPath.replace(/\/(README|index)$/i, '');
            // Root README → empty string (will become /docs/)
            if (/^README$/i.test(resolvedPath)) resolvedPath = '';

            return `[${linkText}](/docs/${resolvedPath}${anchor})`;
        }
    );

    // Fix image paths - convert relative paths to /docs/images/...
    processedContent = processedContent.replace(
        /!\[([^\]]*)\]\(([^)]+)\)/g,
        (match, altText, imagePath) => {
            // Skip absolute URLs
            if (imagePath.startsWith('http://') || imagePath.startsWith('https://')) {
                return match;
            }

            let newImagePath = imagePath;

            // Handle paths starting with /images
            if (imagePath.startsWith('/images')) {
                newImagePath = `/docs${imagePath}`;
            }
            // Already starts with /docs
            else if (imagePath.startsWith('/docs')) {
                newImagePath = imagePath;
            }
            // Handle relative paths like ../../images/... or ./images/...
            else if (imagePath.includes('images/')) {
                const imagesMatch = imagePath.match(/images\/.*$/);
                if (imagesMatch) {
                    newImagePath = `/docs/images/${imagesMatch[0].substring(7)}`;
                }
            }
            // Other relative paths
            else {
                newImagePath = `/docs/${imagePath}`;
            }

            return `![${altText}](${newImagePath})`;
        }
    );

    return processedContent;
}

/**
 * Process markdown content: fix paths and convert to HTML
 * @param {string} content - Original markdown content
 * @param {string} filePath - Path to the current file (relative to docs root)
 * @returns {string} Processed HTML content
 */
function processMarkdownContent(content, filePath) {
    const processedContent = fixMarkdownLinks(content, filePath);

    // Convert markdown to HTML using markdown-it
    let html = md.render(processedContent);

    // Add IDs to headings for anchor links
    html = addHeadingIds(html);

    return html;
}

/**
 * Extract plain text from markdown for search indexing
 * Strips markdown syntax and returns clean text
 * @param {string} markdown - Markdown content
 * @returns {string} Plain text content
 */
/**
 * Extract a short description from plain text content.
 * Skips the title and returns the first meaningful paragraph (max 160 chars).
 */
function extractDescription(plainText, title) {
    const lines = plainText.split("\n").filter(l => l.trim());
    const firstPara = lines.find(l => l.trim() && l.trim() !== title) || "";
    return firstPara.length > 160 ? firstPara.substring(0, 157) + "..." : firstPara;
}

function extractPlainText(markdown) {
    return markdown
        // Remove code blocks
        .replace(/```[\s\S]*?```/g, '')
        .replace(/`[^`]+`/g, '')
        // Remove links but keep text
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
        // Remove images
        .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
        // Remove headings markers
        .replace(/#{1,6}\s*/g, '')
        // Remove bold/italic
        .replace(/\*\*([^*]+)\*\*/g, '$1')
        .replace(/\*([^*]+)\*/g, '$1')
        .replace(/__([^_]+)__/g, '$1')
        .replace(/_([^_]+)_/g, '$1')
        // Remove blockquotes
        .replace(/^>\s*/gm, '')
        // Remove horizontal rules
        .replace(/^[-*_]{3,}\s*$/gm, '')
        // Remove list markers
        .replace(/^[\s]*[-*+]\s*/gm, '')
        .replace(/^[\s]*\d+\.\s*/gm, '')
        // Collapse whitespace
        .replace(/\s+/g, ' ')
        .trim();
}

/**
 * Generate a human-readable title from filename or path
 * @param {string} name - Filename or folder name
 * @returns {string} Human-readable title
 */
function generateTitle(name) {
    return name
        .replace(/\.md$/, '')
        .replace(/[-_]/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
}

/**
 * Recursively reads directory structure and builds navigation tree
 * @param {string} dir - Directory path to scan
 * @param {string} relativePath - Relative path from docs root
 * @param {string[]} ignorePatterns - Patterns to ignore
 * @returns {Object} Navigation structure with files and folders
 */
function buildDocsStructure(dir, relativePath = '', ignorePatterns = []) {
    const items = fs.readdirSync(dir, { withFileTypes: true });
    const structure = {
        files: [],
        folders: []
    };

    for (const item of items) {
        const itemPath = path.join(dir, item.name);
        const itemRelativePath = relativePath ? path.join(relativePath, item.name) : item.name;

        // Check if this item should be ignored
        if (shouldIgnore(itemRelativePath, ignorePatterns)) {
            continue;
        }

        if (item.isDirectory()) {
            // Skip hidden directories and node_modules
            if (item.name.startsWith('.') || item.name === 'node_modules') {
                continue;
            }

            const folderStructure = buildDocsStructure(itemPath, itemRelativePath, ignorePatterns);
            
            // Only add folder if it has content
            if (folderStructure.files.length > 0 || folderStructure.folders.length > 0) {
                structure.folders.push({
                    name: item.name,
                    title: generateTitle(item.name),
                    path: itemRelativePath.replace(/\\/g, '/'),
                    ...folderStructure
                });
            }
        } else if (item.isFile() && item.name.endsWith('.md')) {
            // Read markdown content
            const originalMarkdown = fs.readFileSync(itemPath, 'utf-8');
            
            // Extract title from first # heading or use filename
            const titleMatch = originalMarkdown.match(/^#\s+(.+)$/m);
            const title = titleMatch ? titleMatch[1] : generateTitle(item.name);
            
            // Fix links in markdown (for TipTap rendering)
            const processedMarkdown = fixMarkdownLinks(originalMarkdown, itemRelativePath);

            // Process content: fix paths and convert to HTML (for SSR/SEO)
            const htmlContent = processMarkdownContent(originalMarkdown, itemRelativePath);

            // Extract plain text for search
            const plainText = extractPlainText(originalMarkdown);

            // Generate slug for URL
            const slug = itemRelativePath.replace(/\.md$/, '').replace(/\\/g, '/');

            structure.files.push({
                name: item.name,
                title: title,
                path: itemRelativePath.replace(/\\/g, '/'),
                slug: slug,
                content: htmlContent,
                processedMarkdown: processedMarkdown,
                originalMarkdown: originalMarkdown,
                plainText: plainText,
                wordCount: plainText.split(/\s+/).filter(w => w.trim()).length,
                description: extractDescription(plainText, title)
            });
        }
    }

    // Sort folders and files alphabetically
    structure.folders.sort((a, b) => a.name.localeCompare(b.name));
    structure.files.sort((a, b) => a.name.localeCompare(b.name));

    return structure;
}

/**
 * Build search index from documentation structure
 * Returns array of searchable documents
 * @param {Object} structure - Docs structure from buildDocsStructure
 * @param {string} parentPath - Parent path for breadcrumbs
 * @returns {Array} Search index entries
 */
function buildSearchIndex(structure, parentPath = '') {
    const index = [];
    
    for (const file of structure.files) {
        index.push({
            id: file.slug,
            title: file.title,
            path: file.path,
            slug: file.slug,
            content: file.plainText,
            breadcrumbs: parentPath ? `${parentPath} > ${file.title}` : file.title
        });
    }
    
    for (const folder of structure.folders) {
        const folderPath = parentPath ? `${parentPath} > ${folder.title}` : folder.title;
        index.push(...buildSearchIndex(folder, folderPath));
    }
    
    return index;
}

/**
 * Count total files in structure (for logging)
 * @param {Object} structure - Docs structure
 * @returns {number} Total file count
 */
function countFiles(structure) {
    let count = structure.files.length;
    for (const folder of structure.folders) {
        count += countFiles(folder);
    }
    return count;
}

/**
 * Count total folders in structure (for logging)
 * @param {Object} structure - Docs structure
 * @returns {number} Total folder count
 */
function countFolders(structure) {
    let count = structure.folders.length;
    for (const folder of structure.folders) {
        count += countFolders(folder);
    }
    return count;
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
    const docsStructure = buildDocsStructure(DOCS_ROOT, '', ignorePatterns);
    
    // Build search index
    const searchIndex = buildSearchIndex(docsStructure);

    // Create output directory if it doesn't exist
    if (!fs.existsSync(OUTPUT_DIR)) {
        fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    }

    // Write the JSON file
    const output = {
        generated: new Date().toISOString(),
        structure: docsStructure,
        searchIndex: searchIndex
    };

    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));
    
    const fileCount = countFiles(docsStructure);
    const folderCount = countFolders(docsStructure);
    
    console.log(`✅ Documentation processed successfully!`);
    console.log(`📝 Output: ${OUTPUT_FILE}`);
    console.log(`📊 Total files: ${fileCount}`);
    console.log(`📁 Total folders: ${folderCount}`);
    console.log(`🔍 Search index: ${searchIndex.length} entries`);
}

// Execute main function
main().catch(err => {
    console.error('❌ Error processing documentation:', err);
    process.exit(1);
});
