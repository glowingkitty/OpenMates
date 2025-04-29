import type { Editor } from '@tiptap/core';
import { getLanguageFromFilename } from './utils'; // Assuming utils are accessible
import { extractEpubCover, getEpubMetadata } from './utils';
import { resizeImage } from './utils';

/**
 * Inserts a video embed into the editor.
 */
export async function insertVideo(editor: Editor, file: File, duration?: string, isRecording: boolean = false): Promise<void> {
    const url = URL.createObjectURL(file);
    editor.commands.insertContent([
        {
            type: 'videoEmbed',
            attrs: {
                type: 'video',
                src: url,
                filename: file.name,
                duration: duration || '00:00',
                id: crypto.randomUUID(),
                isRecording
            }
        },
        {
            type: 'text',
            text: ' '
        }
    ]);
    // Use setTimeout to ensure focus happens after potential DOM updates
    setTimeout(() => {
        editor.commands.focus('end');
    }, 50);
}

/**
 * Inserts an image embed into the editor, creating a preview.
 */
export async function insertImage(editor: Editor, file: File, isRecording: boolean = false, previewUrl?: string, originalUrl?: string): Promise<void> {
    // If no previewUrl provided, create one
    if (!previewUrl) {
        try {
            const { previewUrl: newPreviewUrl, originalUrl: newOriginalUrl } = await resizeImage(file);
            previewUrl = newPreviewUrl;
            originalUrl = newOriginalUrl;
        } catch (error) {
            console.error('Error creating image preview:', error);
            // Fallback to original file URL if resizing fails
            const url = URL.createObjectURL(file);
            previewUrl = url;
            originalUrl = url;
        }
    }

    editor.commands.insertContent([
        {
            type: 'imageEmbed',
            attrs: {
                type: 'image',
                src: previewUrl,
                originalUrl: originalUrl,
                originalFile: file, // Keep original file reference if needed later
                filename: file.name,
                id: crypto.randomUUID(),
                isRecording
            }
        },
        {
            type: 'text',
            text: ' '
        }
    ]);
    setTimeout(() => {
        editor.commands.focus('end');
    }, 50);
}

/**
 * Inserts a generic file or PDF embed into the editor.
 */
export async function insertFile(editor: Editor, file: File, type: 'pdf' | 'file'): Promise<void> {
    const url = URL.createObjectURL(file);
    editor.commands.insertContent([
            {
                type: type === 'pdf' ? 'pdfEmbed' : 'fileEmbed',
                attrs: {
                    type,
                    src: url,
                    filename: file.name,
                    id: crypto.randomUUID()
                }
            },
            {
                type: 'text',
                text: ' '
            }
        ]);
    setTimeout(() => {
        editor.commands.focus('end');
    }, 50);
}

/**
 * Inserts an audio embed into the editor.
 */
export async function insertAudio(editor: Editor, file: File): Promise<void> {
    const url = URL.createObjectURL(file);
    editor.chain()
        .focus() // Ensure editor has focus before inserting
        .insertContent([
            {
                type: 'audioEmbed',
                attrs: {
                    type: 'audio',
                    src: url,
                    filename: file.name,
                    id: crypto.randomUUID()
                }
            },
            {
                type: 'text',
                text: ' '
            }
        ])
        .run();
    setTimeout(() => {
        editor.commands.focus('end');
    }, 50);
}

/**
 * Inserts a code file embed into the editor.
 */
export async function insertCodeFile(editor: Editor, file: File): Promise<void> {
    const url = URL.createObjectURL(file);
    const language = getLanguageFromFilename(file.name);

    editor
        .chain()
        .focus()
        .insertContent({
            type: 'codeEmbed',
            attrs: {
                type: 'code',
                src: url,
                filename: file.name,
                language: language,
                id: crypto.randomUUID()
            }
        })
        .insertContent(' ') // Add space after
        .run();
    setTimeout(() => {
        editor.commands.focus('end');
    }, 50);
}

/**
 * Inserts an EPUB file embed into the editor.
 */
export async function insertEpub(editor: Editor, file: File): Promise<void> {
    try {
        const coverUrl = await extractEpubCover(file);
        const epubMetadata = await getEpubMetadata(file);
        const { title, creator } = epubMetadata;

        const bookEmbed = {
            type: 'bookEmbed',
            attrs: {
                type: 'book',
                src: URL.createObjectURL(file),
                filename: file.name,
                id: crypto.randomUUID(),
                bookname: title || undefined,
                author: creator || undefined,
                coverUrl: coverUrl || undefined
            }
        };
        editor.commands.insertContent([bookEmbed, { type: 'text', text: ' ' }]);
        setTimeout(() => {
            editor.commands.focus('end');
        }, 50);
    } catch (error) {
        console.error('Error inserting EPUB:', error);
        // Fallback to generic file embed if EPUB processing fails
        await insertFile(editor, file, 'file');
    }
}

/**
 * Inserts a recording embed (audio) into the editor.
 */
export function insertRecording(editor: Editor, url: string, filename: string, duration: string): void {
     editor.chain()
        .focus()
        .insertContent([
            {
                type: 'recordingEmbed',
                attrs: {
                    type: 'recording',
                    src: url,
                    filename: filename,
                    duration: duration, // Already formatted
                    id: crypto.randomUUID()
                }
            },
            { type: 'text', text: ' ' }
        ])
        .run();
    setTimeout(() => {
        editor.commands.focus('end');
    }, 50);
}

/**
 * Inserts a map embed into the editor.
 */
export function insertMap(editor: Editor, previewData: { type: string; attrs: any }): void {
    editor.commands.insertContent([
        previewData,
        { type: 'text', text: ' ' }
    ]);
    setTimeout(() => {
        editor.commands.focus('end');
    }, 50);
}