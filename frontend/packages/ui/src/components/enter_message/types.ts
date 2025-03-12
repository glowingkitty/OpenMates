// src/components/MessageInput/types.ts

/**
 * Represents metadata extracted from an EPUB file.
 */
export interface EpubMetadata {
    title?: string;
    creator?: string;
}

/**
 * Represents an EPUB object (currently a placeholder, as we're using JSZip directly).
 */
export interface EPub {
    metadata: {
        title?: string;
        creator?: string;
    };
    on(event: string, callback: () => void): void;
    parse(): void;
}

// Add any other shared types here, as needed.  For example, if you had a
// common structure for file attachments, you could define it here:
//
// export interface Attachment {
//     id: string;
//     filename: string;
//     url: string;
//     type: string; // e.g., "image", "video", "pdf"
// }

// TODO what to use this for ?