/**
 * Dynamic Docs Page Loader
 * 
 * Loads documentation data for the requested slug path.
 * This runs at build time for static generation and at request time for dynamic pages.
 */

import type { PageLoad } from './$types';
import { error } from '@sveltejs/kit';
import docsData from '$lib/generated/docs-data.json';

export const prerender = true; // Enable static generation for all doc pages

/**
 * Find a document by its slug path in the docs structure
 * @param structure - The docs structure to search
 * @param slug - The slug path (e.g., "architecture/ai_model_selection")
 * @returns The matching document or null
 */
function findDocBySlug(structure: any, slug: string): any {
    // Check files in current structure
    for (const file of structure.files) {
        if (file.slug === slug) {
            return file;
        }
    }

    // Recursively check folders
    for (const folder of structure.folders) {
        const found = findDocBySlug(folder, slug);
        if (found) return found;
    }

    return null;
}

/**
 * Get all files from a folder (for folder-level operations like copy/download all)
 * @param structure - The folder structure
 * @returns Array of all files in the folder and subfolders
 */
function getAllFilesInFolder(structure: any): any[] {
    let files = [...structure.files];
    
    for (const folder of structure.folders) {
        files = files.concat(getAllFilesInFolder(folder));
    }
    
    return files;
}

/**
 * Find folder by path
 */
function findFolderByPath(structure: any, pathParts: string[]): any {
    if (pathParts.length === 0) return structure;
    
    const [currentPart, ...remainingParts] = pathParts;
    const folder = structure.folders.find((f: any) => f.name === currentPart);
    
    if (!folder) return null;
    if (remainingParts.length === 0) return folder;
    
    return findFolderByPath(folder, remainingParts);
}

export const load: PageLoad = ({ params }) => {
    const slug = params.slug || '';
    
    console.log('🔍 [...slug] route loaded with slug:', slug);
    
    // If slug is empty, return the root docs structure
    if (!slug) {
        console.log('📄 Returning index structure');
        return {
            type: 'index',
            structure: docsData.structure
        };
    }

    // Try to find a specific document
    const doc = findDocBySlug(docsData.structure, slug);
    
    if (doc) {
        console.log('📄 Found document:', doc.title);
        return {
            type: 'document',
            doc,
            structure: docsData.structure // Include full structure for navigation
        };
    }

    // Check if it's a folder path
    const pathParts = slug.split('/');
    const folder = findFolderByPath(docsData.structure, pathParts);
    
    if (folder) {
        return {
            type: 'folder',
            folder,
            allFiles: getAllFilesInFolder(folder),
            structure: docsData.structure
        };
    }

    // Document not found
    throw error(404, `Documentation page not found: ${slug}`);
};

