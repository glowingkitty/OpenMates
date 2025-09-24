import { tick } from 'svelte';
import type { Editor } from '@tiptap/core';
import {
    insertVideo,
    insertCodeFile,
    insertImage,
    insertFile,
    insertAudio,
    insertEpub
} from './embedHandlers'; // Import the new embed handlers
import { isVideoFile, isCodeOrTextFile, isEpubFile } from './utils'; // Import necessary utils

// File size limits (consider moving to a config file later)
const FILE_SIZE_LIMITS = {
    TOTAL_MAX_SIZE: 100, // MB
    PER_FILE_MAX_SIZE: 100 // MB
};
const MAX_TOTAL_SIZE = FILE_SIZE_LIMITS.TOTAL_MAX_SIZE * 1024 * 1024;
const MAX_PER_FILE_SIZE = FILE_SIZE_LIMITS.PER_FILE_MAX_SIZE * 1024 * 1024;

/**
 * Processes an array of files (from drop, paste, or input selection).
 * Inserts appropriate embeds into the editor.
 */
export async function processFiles(
    files: File[],
    editor: Editor
): Promise<void> {
    const totalSize = files.reduce((sum, file) => sum + file.size, 0);
    if (totalSize > MAX_TOTAL_SIZE) {
        alert(`Total file size exceeds ${FILE_SIZE_LIMITS.TOTAL_MAX_SIZE}MB`);
        return;
    }

    // No need to set initial content - the editor will handle empty state

    for (const file of files) {
        if (file.size > MAX_PER_FILE_SIZE) {
            alert(`File ${file.name} exceeds the size limit of ${FILE_SIZE_LIMITS.PER_FILE_MAX_SIZE}MB`);
            continue; // Skip this file
        }

        editor.commands.focus('end'); // Focus before inserting

        // Determine file type and call appropriate insertion function
        if (isVideoFile(file)) {
            await insertVideo(editor, file, undefined, false);
        } else if (isCodeOrTextFile(file.name)) {
            await insertCodeFile(editor, file);
        } else if (file.type.startsWith('image/')) {
            await insertImage(editor, file, false); // isRecording = false for file uploads
        } else if (file.type === 'application/pdf') {
            await insertFile(editor, file, 'pdf');
        } else if (file.type.startsWith('audio/')) {
            await insertAudio(editor, file);
        } else if (isEpubFile(file)) {
            await insertEpub(editor, file);
        } else {
            // Fallback for other file types
            await insertFile(editor, file, 'file');
        }

        // Add a space after inserting the embed node
        // editor.commands.insertContent(' '); // This is handled within insert functions now
    }
}

/**
 * Handles the drop event for files.
 */
export async function handleDrop(
    event: DragEvent,
    editorElement: HTMLElement | undefined,
    editor: Editor
): Promise<void> {
    event.preventDefault();
    event.stopPropagation();
    editorElement?.classList.remove('drag-over');

    const droppedFiles = Array.from(event.dataTransfer?.files || []);
    if (!droppedFiles.length) return;

    await processFiles(droppedFiles, editor);
}

/**
 * Handles the dragover event.
 */
export function handleDragOver(event: DragEvent, editorElement: HTMLElement | undefined): void {
    event.preventDefault();
    event.stopPropagation();
    editorElement?.classList.add('drag-over');
}

/**
 * Handles the dragleave event.
 */
export function handleDragLeave(event: DragEvent, editorElement: HTMLElement | undefined): void {
    event.preventDefault();
    event.stopPropagation();
    editorElement?.classList.remove('drag-over');
}

/**
 * Handles pasting files into the editor.
 */
export async function handlePaste(
    event: ClipboardEvent,
    editor: Editor
): Promise<void> {
    const files: File[] = [];
    const items = event.clipboardData?.items;
    if (items) {
        for (let i = 0; i < items.length; i++) {
            const item = items[i];
            // Check for image paste or generic file paste
            if (item.type.startsWith('image/') || item.kind === 'file') {
                const file = item.getAsFile();
                if (file) files.push(file);
            }
        }
    }

    if (files.length > 0) {
        event.preventDefault(); // Prevent default paste behavior only if files are found
        await processFiles(files, editor);
    }
    // Allow default paste behavior for text, etc.
}

/**
 * Handles file selection from the hidden file input.
 */
export async function onFileSelected(
    event: Event,
    editor: Editor
): Promise<void> {
    const input = event.target as HTMLInputElement;
    if (!input.files?.length) return;

    const files = Array.from(input.files);
    await processFiles(files, editor);

    input.value = ''; // Clear the input after processing
}