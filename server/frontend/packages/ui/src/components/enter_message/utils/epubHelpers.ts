// src/components/MessageInput/utils/epubHelpers.ts
import JSZip from 'jszip';
import type { EpubMetadata } from '../types.ts'; // Corrected relative path

/**
 * Extracts the cover image URL from an EPUB file.
 */
export async function extractEpubCover(file: File): Promise<string | null> {
    try {
        const zip = new JSZip();
        const contents = await zip.loadAsync(file);

        const commonCoverPaths = [
            'OEBPS/images/cover.jpg', 'OEBPS/images/cover.jpeg', 'OEBPS/images/cover.png',
            'OPS/images/cover.jpg', 'OPS/images/cover.jpeg', 'OPS/images/cover.png',
            'cover.jpg', 'cover.jpeg', 'cover.png'
        ];

        for (const path of commonCoverPaths) {
            const coverFile = contents.file(path);
            if (coverFile) {
                const blob = await coverFile.async('blob');
                return URL.createObjectURL(blob);
            }
        }

        const containerXml = await contents.file('META-INF/container.xml')?.async('text');
        if (containerXml) {
            const parser = new DOMParser();
            const containerDoc = parser.parseFromString(containerXml, 'text/xml');
            const opfPath = containerDoc.querySelector('rootfile')?.getAttribute('full-path');

            if (opfPath) {
                const opfContent = await contents.file(opfPath)?.async('text');
                // Check if opfContent is undefined
                if (opfContent) {
                    const opfDoc = parser.parseFromString(opfContent, 'text/xml');
                    const coverId = opfDoc.querySelector('meta[name="cover"]')?.getAttribute('content');

                    if (coverId) {
                        const coverItem = opfDoc.querySelector(`item[id="${coverId}"]`);
                        if (coverItem) {
                            const coverPath = coverItem.getAttribute('href');
                             // Check if coverPath is null
                            if(coverPath) {
                                const fullPath = opfPath.split('/').slice(0, -1).concat(coverPath).join('/');
                                const coverFile = contents.file(fullPath);
                                if (coverFile) {
                                    const blob = await coverFile.async('blob');
                                    return URL.createObjectURL(blob);
                                }
                            }
                        }
                    }
                }
            }
        }
        return null;
    } catch (error) {
        console.error('Error extracting EPUB cover:', error);
        return null;
    }
}

/**
 * Extracts metadata (title, creator) from an EPUB file.
 */
export async function getEpubMetadata(file: File): Promise<EpubMetadata> {
    try {
        const zip = await JSZip.loadAsync(file);
        const containerFile = zip.file("META-INF/container.xml");
        if (!containerFile) {
            throw new Error("container.xml not found in EPUB file");
        }
        const containerXml = await containerFile.async("text");

        const parser = new DOMParser();
        const containerDoc = parser.parseFromString(containerXml, "application/xml");
        const rootfileElement = containerDoc.querySelector("rootfile");
        if (!rootfileElement) {
            throw new Error("rootfile element not found in container.xml");
        }

        const opfPath = rootfileElement.getAttribute("full-path");
        if (!opfPath) {
            throw new Error("OPF path not specified in container.xml");
        }

        const opfFile = zip.file(opfPath);
        if (!opfFile) {
            throw new Error("OPF file not found in EPUB file");
        }
        const opfXml = await opfFile.async("text");

        const opfDoc = parser.parseFromString(opfXml, "application/xml");
        const titleEl = opfDoc.querySelector("metadata > title");
        const creatorEl = opfDoc.querySelector("metadata > creator");

        return {
            title: titleEl ? titleEl.textContent?.trim() || undefined : undefined,
            creator: creatorEl ? creatorEl.textContent?.trim() || undefined : undefined,
        };
    } catch (error) {
        console.error("Error extracting EPUB metadata:", error);
        throw error;
    }
}

/**
 * Checks if a file is an EPUB file.
 */
export function isEpubFile(file: File): boolean {
    return (
        file.type === 'application/epub+zip' ||
        file.name.toLowerCase().endsWith('.epub') ||
        file.type === 'application/x-epub+zip'
    );
}