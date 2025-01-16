<script lang="ts">
    import { tick, onDestroy } from 'svelte';
    import Photos from './in_message_previews/Photos.svelte';
    import PDF from './in_message_previews/PDF.svelte';
    import Web from './in_message_previews/Web.svelte';
    import { onMount } from 'svelte';
    import { _ } from 'svelte-i18n';

    // File size limits in MB
    const FILE_SIZE_LIMITS = {
        TOTAL_MAX_SIZE: 100,  // Total size limit for all files combined
        PER_FILE_MAX_SIZE: 100  // Maximum size per individual file
    };

    // Convert MB to bytes for internal use
    const MAX_TOTAL_SIZE = FILE_SIZE_LIMITS.TOTAL_MAX_SIZE * 1024 * 1024;
    const MAX_PER_FILE_SIZE = FILE_SIZE_LIMITS.PER_FILE_MAX_SIZE * 1024 * 1024;

    // Add variable declarations
    let fileInput: HTMLInputElement;

    type TextSegment = {
        id: string;
        text: string;
        isEditing: boolean;
        imageId?: string;  // Reference to associated image
        fileId?: string;   // Reference to associated file
        videoId?: string;  // Reference to associated video
        webUrl?: string;   // Reference to web preview
    }

    type InlineImage = { 
        id: string, 
        blob: Blob, 
        filename: string
    };

    type FileAttachment = {
        id: string,
        file: File,
        filename: string
    };

    type VideoAttachment = {
        id: string,
        blob: Blob,
        filename: string
    };

    type VideoURL = {
        id: string;
        url: string;
    };

    let textSegments: TextSegment[] = [{ id: 'initial', text: '', isEditing: true }];
    let inlineImages: InlineImage[] = [];
    let activeSegmentId = 'initial';
    let fileAttachments: FileAttachment[] = [];
    let videoAttachments: VideoAttachment[] = [];
    let videoURLs: VideoURL[] = [];

    // References for file input and camera input
    let cameraInput: HTMLInputElement;
    let videoElement: HTMLVideoElement;
    let stream: MediaStream | null = null;
    let showCamera = false;

    // Add new reactive variable to track if there's content
    $: hasContent = textSegments.some(segment => segment.text.trim().length > 0) || 
                    inlineImages.length > 0 || 
                    fileAttachments.length > 0;

    // Add new function to check if segment should be visible
    function shouldShowSegment(segment: TextSegment, index: number): boolean {
        const hasContent = Boolean(segment.text.length > 0);
        const hasAttachment = Boolean(segment.imageId || segment.fileId || segment.videoId);
        const isFirstSegment = index === 0;
        const isLastSegment = index === textSegments.length - 1;
        const prevHasAttachment = index > 0 && Boolean(textSegments[index - 1].imageId || textSegments[index - 1].fileId || textSegments[index - 1].videoId);
        const nextHasAttachment = index < textSegments.length - 1 && Boolean(textSegments[index + 1].imageId || textSegments[index + 1].fileId || textSegments[index + 1].videoId);

        return Boolean(
            hasContent || 
            hasAttachment || 
            isFirstSegment || 
            isLastSegment || 
            (!prevHasAttachment && !nextHasAttachment && hasContent)
        );
    }

    // Function to handle clicking on a text div
    function handleTextClick(segment: TextSegment, event: MouseEvent) {
        const textDiv = event.target as HTMLDivElement;
        const clickPosition = getClickPosition(textDiv, event);
        
        // Make all segments non-editable
        textSegments = textSegments.map(s => ({ ...s, isEditing: false }));
        
        // Make clicked segment editable
        const index = textSegments.findIndex(s => s.id === segment.id);
        textSegments[index].isEditing = true;
        activeSegmentId = segment.id;
        
        // Wait for textarea to be created and set cursor position
        tick().then(() => {
            const textarea = document.getElementById(segment.id) as HTMLTextAreaElement;
            if (textarea) {
                // Adjust height before focusing to prevent flicker
                adjustTextareaHeight(textarea);
                textarea.focus();
                textarea.setSelectionRange(clickPosition, clickPosition);
            }
        });
    }

    // Helper function to calculate click position in text
    function getClickPosition(element: HTMLElement, event: MouseEvent): number {
        const range = document.createRange();
        const selection = window.getSelection();
        
        range.setStart(element, 0);
        range.setEnd(element, 0);
        
        const rects = range.getClientRects();
        const clickX = event.clientX;
        const text = element.textContent || '';
        
        // Simple calculation - can be improved for more accuracy
        const charWidth = element.offsetWidth / text.length;
        return Math.round((clickX - element.getBoundingClientRect().left) / charWidth);
    }

    // Modify insertImageAtCursor to handle edit states
    function insertImageAtCursor(imageBlob: Blob) {
        const imageId = crypto.randomUUID();
        const newSegmentId = crypto.randomUUID();
        
        // If imageBlob is a File, use its name, otherwise generate one
        const filename = (imageBlob instanceof File) ? 
            imageBlob.name : 
            `image_${imageId}.jpg`;
        
        const newImage: InlineImage = { 
            id: imageId, 
            blob: imageBlob, 
            filename: filename  // Use original filename or generated one
        };
        
        textSegments = textSegments.map(s => ({ ...s, isEditing: false }));
        const activeIndex = textSegments.findIndex(s => s.id === activeSegmentId);
        
        if (!textSegments[activeIndex].text && !textSegments[activeIndex].imageId) {
            // Use current empty segment for image
            textSegments[activeIndex] = {
                ...textSegments[activeIndex],
                imageId,
                isEditing: false
            };
        } else {
            // Insert new segment for image
            textSegments.splice(activeIndex + 1, 0, {
                id: crypto.randomUUID(),
                text: '',
                isEditing: false,
                imageId,
                fileId: undefined,
                videoId: undefined
            });
        }
        
        // Ensure there's always an empty segment at the end
        if (!textSegments[textSegments.length - 1].text && !textSegments[textSegments.length - 1].imageId) {
            activeSegmentId = textSegments[textSegments.length - 1].id;
            textSegments[textSegments.length - 1].isEditing = true;
        } else {
            textSegments.push({
                id: newSegmentId,
                text: '',
                isEditing: true,
                imageId: undefined,
                fileId: undefined,
                videoId: undefined
            });
            activeSegmentId = newSegmentId;
        }
        
        inlineImages = [...inlineImages, newImage];
        
        tick().then(() => {
            const newTextarea = document.getElementById(activeSegmentId) as HTMLTextAreaElement;
            if (newTextarea) newTextarea.focus();
        });
    }

    // Get complete content in markdown format
    export function getMarkdownContent(): string {
        return textSegments.map(segment => {
            const img = segment.imageId ? inlineImages.find(img => img.id === segment.imageId) : null;
            const file = segment.fileId ? fileAttachments.find(file => file.id === segment.fileId) : null;
            const video = segment.videoId ? videoAttachments.find(video => video.id === segment.videoId) : null;
            
            if (video) {
                return segment.text + `\n[🎥 ${video.filename}](${video.filename})\n`;
            } else if (img) {
                return segment.text + `\n![${img.filename}](${img.filename})\n`;
            } else if (file) {
                return segment.text + `\n[📎 ${file.filename}](${file.filename})\n`;
            }
            return segment.text;
        }).join('');
    }

    // Add helper function to calculate total size of existing attachments
    function getCurrentAttachmentsSize(): number {
        const imageSize = inlineImages.reduce((total, img) => total + img.blob.size, 0);
        const fileSize = fileAttachments.reduce((total, file) => total + file.file.size, 0);
        const videoSize = videoAttachments.reduce((total, video) => total + video.blob.size, 0);
        return imageSize + fileSize + videoSize;
    }

    // Modify file input to accept multiple files
    function handleFileSelect() {
        // Set multiple attribute before clicking
        fileInput.multiple = true;
        fileInput.click();
    }

    // Update file selection handler
    function onFileSelected(event: Event) {
        const input = event.target as HTMLInputElement;
        if (!input.files || input.files.length === 0) return;

        const newFiles = Array.from(input.files);
        
        const newFilesSize = newFiles.reduce((total, file) => total + file.size, 0);
        const currentSize = getCurrentAttachmentsSize();
        const totalSize = currentSize + newFilesSize;

        if (totalSize > MAX_TOTAL_SIZE) {
            alert($_('enter_message.file_size_limits.total_exceeded.text', ({
                size: FILE_SIZE_LIMITS.TOTAL_MAX_SIZE,
                current: (currentSize / 1024 / 1024).toFixed(1),
                attempted: (newFilesSize / 1024 / 1024).toFixed(1)
            } as any)));
            input.value = '';
            return;
        }

        // Process each file
        newFiles.forEach((file) => {
            if (file.type.startsWith('video/')) {
                // Handle video files
                insertVideoAtCursor(file);
            } else if (file.type.startsWith('image/')) {
                insertImageAtCursor(file);
            } else {
                insertFileAtCursor(file);
            }
        });

        input.value = '';
    }

    // Update camera input to match multiple file handling pattern
    function onCameraFileSelected(event: Event) {
        const input = event.target as HTMLInputElement;
        if (!input.files || input.files.length === 0) return;

        const newFiles = Array.from(input.files);
        const newFilesSize = newFiles.reduce((total, file) => total + file.size, 0);
        const currentSize = getCurrentAttachmentsSize();
        const totalSize = currentSize + newFilesSize;

        if (totalSize > MAX_TOTAL_SIZE) {
            alert($_('enter_message.file_size_limits.total_exceeded.text', ({
                size: FILE_SIZE_LIMITS.TOTAL_MAX_SIZE,
                current: (currentSize / 1024 / 1024).toFixed(1),
                attempted: (newFilesSize / 1024 / 1024).toFixed(1)
            } as any)));
            input.value = '';
            return;
        }

        newFiles.forEach(file => {
            insertImageAtCursor(file);
        });

        input.value = '';
    }

    // Update the camera capture function to check size before inserting
    async function capturePhoto() {
        if (!videoElement) return;

        const canvas = document.createElement('canvas');
        canvas.width = videoElement.videoWidth;
        canvas.height = videoElement.videoHeight;
        const ctx = canvas.getContext('2d');
        
        if (ctx) {
            ctx.drawImage(videoElement, 0, 0);
            canvas.toBlob((blob) => {
                if (blob) {
                    // Check size before inserting
                    const totalSize = getCurrentAttachmentsSize() + blob.size;
                    if (totalSize > MAX_TOTAL_SIZE) {
                        alert($_('enter_message.file_size_limits.total_exceeded.text', ({
                            size: FILE_SIZE_LIMITS.TOTAL_MAX_SIZE,
                            current: (getCurrentAttachmentsSize() / 1024 / 1024).toFixed(1),
                            attempted: (blob.size / 1024 / 1024).toFixed(1)
                        } as any)));
                        return;
                    }
                    insertImageAtCursor(blob);
                }
            }, 'image/jpeg');
        }
        closeCamera();
    }

    function closeCamera() {
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
        showCamera = false;
    }

    onDestroy(() => {
        closeCamera();
        // Cleanup video URLs
        videoURLs.forEach(({ url }) => URL.revokeObjectURL(url));
    });

    // Add new function to handle file insertions
    function insertFileAtCursor(file: File) {
        const fileId = crypto.randomUUID();
        const newSegmentId = crypto.randomUUID();
        
        const newFile: FileAttachment = {
            id: fileId,
            file: file,
            filename: file.name
        };
        
        textSegments = textSegments.map(s => ({ ...s, isEditing: false }));
        
        const activeIndex = textSegments.findIndex(s => s.id === activeSegmentId);
        
        if (activeIndex === 0 && !textSegments[0].text) {
            textSegments = [
                { ...textSegments[0], fileId },  // Associate file with first segment
                { id: newSegmentId, text: '', isEditing: true, imageId: undefined, fileId: undefined }
            ];
        } else {
            textSegments = [
                ...textSegments.slice(0, activeIndex + 1),
                { id: newSegmentId, text: '', isEditing: true, imageId: undefined, fileId: undefined }
            ];
            // Associate file with the segment at activeIndex
            textSegments[activeIndex] = { ...textSegments[activeIndex], fileId };
        }
        
        fileAttachments = [...fileAttachments, newFile];
        activeSegmentId = newSegmentId;
        
        tick().then(() => {
            const newTextarea = document.getElementById(newSegmentId) as HTMLTextAreaElement;
            if (newTextarea) newTextarea.focus();
        });
    }

    // Add this new function to adjust textarea height
    function adjustTextareaHeight(textarea: HTMLTextAreaElement) {
        // Reset height temporarily to get the correct scrollHeight
        textarea.style.height = '0';
        // Set to scrollHeight to get the full content height
        textarea.style.height = `${textarea.scrollHeight}px`;
    }

    // Modify the existing handleKeydown function
    function handleKeydown(event: KeyboardEvent, index: number) {
        const textarea = event.target as HTMLTextAreaElement;
        
        // Adjust height on next tick to ensure content is updated
        tick().then(() => adjustTextareaHeight(textarea));

        // Handle Enter key
        if (event.key === 'Enter') {
            if (!event.shiftKey) {
                event.preventDefault();
                if (hasContent) {
                    handleSend();
                }
            }
        }

        // Handle Backspace key
        if (event.key === 'Backspace') {
            if (textarea.selectionStart === 0 && textarea.selectionEnd === 0 && index > 0) {
                event.preventDefault();
                
                const currentText = textarea.value;
                const prevSegment = textSegments[index - 1];
                
                if (prevSegment.webUrl) {
                    const url = prevSegment.webUrl;
                    // Remove the web preview and merge segments
                    const prevPrevSegment = index > 1 ? textSegments[index - 2] : null;
                    
                    if (prevPrevSegment) {
                        // Append URL to previous text segment
                        const newText = prevPrevSegment.text + (prevPrevSegment.text ? ' ' : '') + url + currentText;
                        textSegments = [
                            ...textSegments.slice(0, index - 2),
                            {
                                ...prevPrevSegment,
                                text: newText,
                                isEditing: true
                            },
                            ...textSegments.slice(index + 1)
                        ];
                        activeSegmentId = prevPrevSegment.id;
                        
                        // Set cursor position after URL
                        tick().then(() => {
                            const textarea = document.getElementById(prevPrevSegment.id) as HTMLTextAreaElement;
                            if (textarea) {
                                textarea.focus();
                                const cursorPosition = newText.length - currentText.length;
                                textarea.setSelectionRange(cursorPosition, cursorPosition);
                            }
                        });
                    } else {
                        // Create new text segment with URL
                        const newText = url + currentText;
                        const newSegmentId = crypto.randomUUID();
                        textSegments = [
                            {
                                id: newSegmentId,
                                text: newText,
                                isEditing: true
                            },
                            ...textSegments.slice(index + 1)
                        ];
                        activeSegmentId = newSegmentId;
                        
                        // Set cursor position after URL
                        tick().then(() => {
                            const textarea = document.getElementById(newSegmentId) as HTMLTextAreaElement;
                            if (textarea) {
                                textarea.focus();
                                const cursorPosition = url.length;
                                textarea.setSelectionRange(cursorPosition, cursorPosition);
                            }
                        });
                    }
                } else if (prevSegment.imageId || prevSegment.fileId || prevSegment.videoId) {
                    // Existing attachment handling code...
                    inlineImages = inlineImages.filter(img => img.id !== prevSegment.imageId);
                    fileAttachments = fileAttachments.filter(file => file.id !== prevSegment.fileId);
                    videoAttachments = videoAttachments.filter(video => video.id !== prevSegment.videoId);
                    
                    textSegments = [
                        ...textSegments.slice(0, index - 1),
                        {
                            ...prevSegment,
                            imageId: undefined,
                            fileId: undefined,
                            videoId: undefined,
                            text: prevSegment.text + currentText,
                            isEditing: true
                        },
                        ...textSegments.slice(index + 1)
                    ];
                    
                    activeSegmentId = prevSegment.id;
                } else {
                    // Regular text merge if no attachments
                    textSegments = [
                        ...textSegments.slice(0, index - 1),
                        {
                            ...prevSegment,
                            text: prevSegment.text + currentText,
                            isEditing: true
                        },
                        ...textSegments.slice(index + 1)
                    ];
                    
                    activeSegmentId = prevSegment.id;
                }

                setTimeout(() => {
                    const prevTextarea = document.getElementById(prevSegment.id) as HTMLTextAreaElement;
                    if (prevTextarea) {
                        prevTextarea.focus();
                        const length = prevTextarea.value.length;
                        prevTextarea.setSelectionRange(length, length);
                    }
                }, 0);
            }
        }
    }

    // Update handleInput function to detect spaces using InputEvent
    function handleInput(event: Event, segment: TextSegment, index: number) {
        const textarea = event.target as HTMLTextAreaElement;
        adjustTextareaHeight(textarea);
        
        // Update the segment's text immediately
        segment.text = textarea.value;
        
        // Check if space was typed using InputEvent
        const inputEvent = event as InputEvent;
        if (inputEvent.data === ' ') {
            // console.log('Space detected, checking for URLs in:', textarea.value); // Debug log
            handleUrlDetection(segment, index);
        }
    }

    // Add function to handle sending
    function handleSend() {
        const markdownContent = getMarkdownContent();
        console.log('Sending message with following markdown content:');
        console.log('----------------------------------------');
        console.log(markdownContent);
        console.log('----------------------------------------');

        // Log attachments for debugging
        if (inlineImages.length > 0) {
            console.log('Included images:', inlineImages.map(img => ({
                filename: img.filename,
                size: Math.round(img.blob.size / 1024) + 'KB'
            })));
        }
        
        if (fileAttachments.length > 0) {
            console.log('Included files:', fileAttachments.map(file => ({
                filename: file.filename,
                size: Math.round(file.file.size / 1024) + 'KB'
            })));
        }
    }

    // Update handleKeyPress to properly handle keyboard events
    function handleKeyPress(segment: TextSegment, event: KeyboardEvent) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            // Create a fake mouse event at position 0
            const fakeMouseEvent = {
                clientX: 0,
                target: event.target
            } as MouseEvent;
            handleTextClick(segment, fakeMouseEvent);
        }
    }

    // Add this function back after handleFileSelect
    async function handleCameraClick() {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ 
                video: { facingMode: 'environment' },
                audio: false 
            });
            
            if (stream) {
                showCamera = true;
                await tick();
                if (videoElement) {
                    videoElement.srcObject = stream;
                }
            }
        } catch (err) {
            console.error('Camera access error:', err);
            cameraInput.removeAttribute('capture');
            cameraInput.click();
        }
    }

    // Add function to insert video
    function insertVideoAtCursor(videoFile: File) {
        const videoId = crypto.randomUUID();
        const newSegmentId = crypto.randomUUID();
        
        const newVideo: VideoAttachment = {
            id: videoId,
            blob: videoFile,
            filename: videoFile.name
        };
        
        // Create and store URL
        const videoURL = URL.createObjectURL(videoFile);
        videoURLs = [...videoURLs, { id: videoId, url: videoURL }];
        
        // Make all existing segments non-editable
        textSegments = textSegments.map(s => ({ ...s, isEditing: false }));
        
        const activeIndex = textSegments.findIndex(s => s.id === activeSegmentId);
        
        if (activeIndex === 0 && !textSegments[0].text) {
            textSegments = [
                { ...textSegments[0], videoId },
                { id: newSegmentId, text: '', isEditing: true, imageId: undefined, fileId: undefined, videoId: undefined }
            ];
        } else {
            textSegments = [
                ...textSegments.slice(0, activeIndex + 1),
                { id: newSegmentId, text: '', isEditing: true, imageId: undefined, fileId: undefined, videoId: undefined }
            ];
            textSegments[activeIndex] = { ...textSegments[activeIndex], videoId };
        }
        
        videoAttachments = [...videoAttachments, newVideo];
        activeSegmentId = newSegmentId;
        
        tick().then(() => {
            const newTextarea = document.getElementById(newSegmentId) as HTMLTextAreaElement;
            if (newTextarea) newTextarea.focus();
        });
    }

    // Update URL detection regex (replace existing urlRegex)
    const urlRegex = /https?:\/\/[^\s]+\.[a-z]{2,}(?:\/[^\s]*)?/gi;

    // Replace existing handleUrlDetection function
    function handleUrlDetection(segment: TextSegment, index: number) {
        // Only proceed if a space was just typed in the segment text
        // so that we know the user has potentially finished typing the URL
        if (!segment.text.endsWith(' ')) {
            return;
        }

        // We split the entire current segment text by whitespace
        // to find if there's any newly typed URL anywhere in the text.
        const words = segment.text.split(/\s+/);

        // If there's no text to process or a webUrl is already attached to this segment, do nothing
        if (!words.length || segment.webUrl) {
            return;
        }

        // Find the index of the last URL that appears in the list of words
        // This covers the scenario where the user typed text, inserted a URL, 
        // and then continued typing more text in the same segment.
        let lastURLIndex = -1;
        for (let i = 0; i < words.length; i++) {
            // We test each word against our current urlRegex
            if (urlRegex.test(words[i])) {
                lastURLIndex = i;
            }
        }

        // If there's no URL found, stop here
        if (lastURLIndex === -1) {
            return;
        }

        // If we did find a URL, we extract it
        const url = words[lastURLIndex];
        console.debug("Detected URL for preview:", url); // Debug-style logging

        // Prepare a new segment ID for the final text portion
        const newSegmentId = crypto.randomUUID();

        // Split the text into portions before and after the URL
        // We remove the actual "URL word" from the middle portion, as that goes in its own segment.
        const textBeforeUrl = words.slice(0, lastURLIndex).join(' ');
        const textAfterUrl = words.slice(lastURLIndex + 1).join(' ');

        console.debug("Text before URL:", textBeforeUrl);
        console.debug("Text after URL:", textAfterUrl);

        // We will construct up to three segments:
        // 1. One for the text before the newly detected URL (if any)
        // 2. One for the URL itself (the "web preview" segment)
        // 3. One for any leftover text after the URL, or if there is no text leftover,
        //    we still place an empty segment so users can keep typing.
        const newSegments: TextSegment[] = [];

        // If there is text before the URL, create a non-editing segment for that
        if (textBeforeUrl.trim()) {
            newSegments.push({
                id: crypto.randomUUID(),
                text: textBeforeUrl.trimEnd() + ' ', // preserve trailing space
                isEditing: false
            });
        }

        // The next segment is the "web preview" itself
        newSegments.push({
            id: crypto.randomUUID(),
            text: '',
            isEditing: false,
            webUrl: url
        });

        // Finally, create a new text segment for whatever remains,
        // enabling editing so the user can continue typing immediately.
        newSegments.push({
            id: newSegmentId,
            text: textAfterUrl ? textAfterUrl + ' ' : ' ', // preserve space
            isEditing: true
        });

        // Now we rebuild our textSegments, splicing out the current one,
        // and inserting the newly created segments in its place
        textSegments = [
            ...textSegments.slice(0, index),
            ...newSegments,
            ...textSegments.slice(index + 1)
        ];

        // Give focus to the last new segment (so user can continue typing seamlessly)
        activeSegmentId = newSegmentId;

        tick().then(() => {
            const newTextarea = document.getElementById(newSegmentId) as HTMLTextAreaElement;
            if (newTextarea) {
                newTextarea.focus();
                // If there was leftover text after the URL, place cursor at the end of that text
                const position = newTextarea.value.length;
                newTextarea.setSelectionRange(position, position);
            }
        });
    }

    // Replace existing handlePaste function
    function handlePaste(event: ClipboardEvent) {
        const textarea = event.target as HTMLTextAreaElement;
        const pastedText = event.clipboardData?.getData('text') || '';

        // Check if pasted text is a valid URL
        if (pastedText.match(urlRegex)) {
            event.preventDefault();

            const currentIndex = textSegments.findIndex(s => s.id === activeSegmentId);
            if (currentIndex !== -1) {
                const segment = textSegments[currentIndex];
                const cursorPosition = textarea.selectionStart;

                // Split the current text at cursor position
                const textBefore = segment.text.slice(0, cursorPosition);
                const textAfter = segment.text.slice(textarea.selectionEnd);

                const newSegmentId = crypto.randomUUID();

                // Create new segments
                textSegments = [
                    ...textSegments.slice(0, currentIndex),
                    { ...segment, text: textBefore.trim() },
                    { id: crypto.randomUUID(), text: '', isEditing: false, webUrl: pastedText },
                    { id: newSegmentId, text: textAfter.trim(), isEditing: true },
                    ...textSegments.slice(currentIndex + 1)
                ];

                // Set focus to the last segment
                activeSegmentId = newSegmentId;

                // Ensure focus is set after DOM update
                tick().then(() => {
                    const newTextarea = document.getElementById(newSegmentId) as HTMLTextAreaElement;
                    if (newTextarea) {
                        newTextarea.focus();
                        // If there was text after the cursor, place cursor at start of that text
                        if (textAfter) {
                            newTextarea.setSelectionRange(0, 0);
                        }
                    }
                });
            }
        }
    }

    // First, modify the isMessageFieldFocused variable to track actual text field focus
    let isMessageFieldFocused = false;

    // Add back onMount with focus state
    onMount(() => {
        // Auto-focus the initial textarea on component load
        const initialTextarea = document.getElementById('initial') as HTMLTextAreaElement;
        if (initialTextarea) {
            initialTextarea.focus();
            isMessageFieldFocused = true; // Set focus state to true on initial load
        }
    });

    // Add new prop for the default mention
    export let defaultMention: string | undefined = 'sophia';

    // Add new type for mention display
    type MentionDisplay = {
        mate: string;
        element: HTMLElement | null;
    }

    let currentMention: MentionDisplay | null = defaultMention ? {
        mate: defaultMention,
        element: null
    } : null;
</script>

<div class="message-container {isMessageFieldFocused ? 'focused' : ''}">
    <!-- Hidden file inputs -->
    <input
        bind:this={fileInput}
        type="file"
        on:change={onFileSelected}
        style="display: none"
        multiple
    />
    
    <input
        bind:this={cameraInput}
        type="file"
        accept="image/*"
        capture="environment"
        on:change={onCameraFileSelected}
        style="display: none"
        multiple
    />

    <div class="scrollable-content">
        <div class="content-wrapper">
            {#each textSegments as segment, index}
                {#if shouldShowSegment(segment, index)}
                    {#if segment.isEditing}
                        <div class="input-wrapper">
                            {#if index === 0 && currentMention && (segment.text || isMessageFieldFocused)}
                                <div class="mention-display">
                                    <span class="at-symbol">@</span>
                                    <div class="mate-profile mate-profile-small {currentMention.mate}"></div>
                                </div>
                            {/if}
                            <textarea
                                id={segment.id}
                                bind:value={segment.text}
                                on:focus={() => {
                                    activeSegmentId = segment.id;
                                    isMessageFieldFocused = true;
                                }}
                                on:blur={() => {
                                    segment.isEditing = false;
                                    setTimeout(() => {
                                        const activeElement = document.activeElement;
                                        if (!activeElement || !activeElement.matches('textarea')) {
                                            isMessageFieldFocused = false;
                                        }
                                    }, 0);
                                }}
                                on:keydown={(e) => handleKeydown(e, index)}
                                on:input={(e) => handleInput(e, segment, index)}
                                on:paste={handlePaste}
                                placeholder={index === 0 && !segment.text && !segment.imageId && !segment.fileId && !segment.videoId && !segment.webUrl 
                                    ? $_('enter_message.enter_your_message.text')
                                    : segment.imageId || segment.fileId || segment.videoId || segment.webUrl 
                                        ? $_('enter_message.click_to_add_text.text')
                                        : ""}
                                rows="1"
                                class="message-input {segment.text ? 'has-content' : ''} {(segment.imageId || segment.fileId || segment.videoId || segment.webUrl) ? 'before-attachment' : ''} {index === 0 && currentMention ? 'has-mention' : ''}"
                            ></textarea>
                        </div>
                    {:else}
                        <div
                            class="text-display {!segment.text ? 'empty' : ''} {(segment.imageId || segment.fileId || segment.videoId || segment.webUrl) ? 'before-attachment' : ''}"
                            on:click={(e) => {
                                handleTextClick(segment, e);
                                isMessageFieldFocused = true;
                            }}
                            on:keydown={(e) => handleKeyPress(segment, e)}
                            tabindex="0"
                            role="textbox"
                        >
                            {#if index === 0 && currentMention && segment.text}
                                <div class="mention-display">
                                    <span class="at-symbol">@</span>
                                    <div class="mate-profile mate-profile-small {currentMention.mate}"></div>
                                </div>
                            {/if}
                            {#if index === 0 && !segment.text && !segment.imageId && !segment.fileId && !segment.videoId && !segment.webUrl}
                                <span class="placeholder">
                                    {isMessageFieldFocused ? 
                                        $_('enter_message.enter_your_message.text') : 
                                        $_('enter_message.click_to_enter_message.text')}
                                </span>
                            {:else if !segment.text && (segment.imageId || segment.fileId || segment.videoId || segment.webUrl)}
                                <span class="placeholder">{$_('enter_message.click_to_add_text.text')}</span>
                            {:else}
                                {segment.text || '\u00A0'}
                            {/if}
                        </div>
                    {/if}
                {/if}
                
                {#if segment.imageId}
                    {#if inlineImages.find(img => img.id === segment.imageId)}
                        {@const image = inlineImages.find(img => img.id === segment.imageId)!}
                        <Photos 
                            src={URL.createObjectURL(image.blob)}
                            filename={image.filename}
                            on:delete={() => {
                                // Remove only the specific image
                                inlineImages = inlineImages.filter(img => img.id !== segment.imageId);
                                
                                // Find the current segment index
                                const currentIndex = textSegments.findIndex(s => s.id === segment.id);
                                
                                // Only modify the current segment by removing its image reference
                                textSegments = textSegments.map((seg, idx) => {
                                    if (idx === currentIndex) {
                                        return {
                                            ...seg,
                                            imageId: undefined,
                                            isEditing: true
                                        };
                                    }
                                    return seg;
                                });
                                
                                // Set focus to the current segment
                                activeSegmentId = textSegments[currentIndex].id;
                            }}
                        />
                    {/if}
                {:else if segment.fileId}
                    {#if fileAttachments.find(file => file.id === segment.fileId)}
                        {@const file = fileAttachments.find(file => file.id === segment.fileId)!}
                        {#if file.file.type === 'application/pdf'}
                            <PDF 
                                src={URL.createObjectURL(file.file)}
                                filename={file.filename}
                                on:delete={() => {
                                    fileAttachments = fileAttachments.filter(f => f.id !== segment.fileId);
                                    textSegments = textSegments.map((seg, idx) => {
                                        if (idx === index) {
                                            return {
                                                ...seg,
                                                fileId: undefined,
                                                isEditing: true
                                            };
                                        }
                                        return seg;
                                    });
                                    activeSegmentId = textSegments[index].id;
                                }}
                            />
                        {:else}
                            <div class="file-attachment">
                                <div class="file-icon">📎</div>
                                <div class="file-info">
                                    <div class="file-name">
                                        {file.filename}
                                    </div>
                                </div>
                            </div>
                        {/if}
                    {/if}
                {:else if segment.videoId}
                    {#if videoAttachments.find(video => video.id === segment.videoId)}
                        <div class="video-container">
                            <video 
                                src={videoURLs.find(v => v.id === segment.videoId)?.url}
                                controls
                                preload="metadata"
                                class="preview-video"
                            >
                                <track kind="captions">
                                Your browser does not support the video tag.
                            </video>
                        </div>
                    {/if}
                {:else if segment.webUrl}
                    <Web 
                        url={segment.webUrl} 
                        on:delete={() => {
                            const currentIndex = textSegments.findIndex(s => s.id === segment.id);
                            if (currentIndex !== -1) {
                                const prevSegment = textSegments[currentIndex - 1];
                                const nextSegment = textSegments[currentIndex + 1];
                                
                                textSegments = [
                                    ...textSegments.slice(0, currentIndex - 1),
                                    {
                                        ...prevSegment,
                                        text: (prevSegment.text + ' ' + nextSegment.text).trim(),
                                        isEditing: true
                                    },
                                    ...textSegments.slice(currentIndex + 2)
                                ];
                                
                                activeSegmentId = prevSegment.id;
                            }
                        }}
                    />
                {/if}
            {/each}
        </div>
    </div>

    {#if showCamera}
        <div class="camera-overlay">
            <video
                bind:this={videoElement}
                autoplay
                playsinline
                class="camera-preview"
            >
                <track kind="captions" />
            </video>
            <div class="camera-controls">
                <button class="camera-button" on:click={closeCamera}>
                    ❌
                </button>
                <button class="camera-button" on:click={capturePhoto}>
                    📸
                </button>
            </div>
        </div>
    {/if}

    <!-- Action buttons -->
    <div class="action-buttons">
        <div class="left-buttons">
            <button 
                class="clickable-icon icon_files" 
                on:click={handleFileSelect} 
                aria-label={$_('enter_message.attachments.attach_files.text')}
            ></button>
            <button 
                class="clickable-icon icon_maps" 
                on:click={() => {/* Handle maps click */}} 
                aria-label={$_('enter_message.attachments.share_location.text')}
            ></button>
        </div>
        <div class="right-buttons">
            <button 
                class="clickable-icon icon_camera" 
                on:click={handleCameraClick} 
                aria-label={$_('enter_message.attachments.take_photo.text')}
            ></button>
            <button 
                class="clickable-icon icon_recordaudio" 
                aria-label={$_('enter_message.attachments.record_audio.text')}
            ></button>
            {#if hasContent}
                <button class="send-button" on:click={handleSend}>
                    {$_('enter_message.send.text')}
                </button>
            {/if}
        </div>
    </div>
</div>

<style>
    .message-container {
        width: 100%;
        min-height: 100px;
        max-height: 350px;
        background-color: var(--color-grey-blue);
        border-radius: 24px;
        padding: 0 1rem 50px 1rem;
        box-sizing: border-box;
        position: relative;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        transition: box-shadow 0.2s ease-in-out;
    }

    .message-container.focused {
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
    }

    .scrollable-content {
        width: 100%;
        height: 100%;
        max-height: 250px;
        overflow-y: auto;
        position: relative;
        padding-top: 1em;
        scrollbar-width: thin;
        scrollbar-color: color-mix(in srgb, var(--color-grey-100) 20%, transparent) transparent;
    }

    .scrollable-content::-webkit-scrollbar {
        width: 6px;
    }

    .scrollable-content::-webkit-scrollbar-track {
        background: transparent;
    }

    .scrollable-content::-webkit-scrollbar-thumb {
        background-color: rgba(0, 0, 0, 0.2);
        border-radius: 3px;
    }

    .content-wrapper {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    .message-input {
        width: 100%;
        min-height: 2em;
        border: none;
        outline: none;
        resize: none;
        background: transparent;
        font-family: inherit;
        font-size: 1rem;
        line-height: 1.5;
        padding: 0.5rem 0;
        margin: 0;
        overflow: hidden;
        box-sizing: border-box;
        text-align: left;
        caret-color: var(--color-font-primary);
        animation: blink-caret 1s step-end infinite;
        height: auto;
        word-break: break-word;
        white-space: pre-wrap;
    }

    @keyframes blink-caret {
        from, to { caret-color: var(--color-font-primary); }
        50% { caret-color: transparent; }
    }

    .message-input::placeholder {
        text-align: center;
        transition: opacity 0.2s ease;
        position: absolute;
        left: 0;
        right: 0;
        color: var(--color-font-tertiary);
        font-weight: 500;
    }

    .message-input.has-content::placeholder {
        opacity: 0;
    }

    textarea {
        /* Reset all properties that could affect textarea height */
        margin: 0 !important;
        padding: 0 !important;
        border: none !important;
        line-height: normal !important;
        font-size: unset !important;
        font-family: unset !important;
        font-weight: 500 !important;
        min-height: unset !important;
        max-height: unset !important;
        box-sizing: content-box !important;
        color: var(--color-font-primary);
    }

    .action-buttons {
        position: absolute;
        bottom: 1rem;
        left: 1rem;
        right: 1rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        height: 40px;
    }

    .left-buttons {
        display: flex;
        gap: 1rem;
        align-items: center;
        height: 100%;
    }

    .right-buttons {
        display: flex;
        align-items: center;
        gap: 1rem;
        height: 100%;
    }

    .camera-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.9);
        z-index: 1000;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }

    .camera-preview {
        max-width: 100%;
        max-height: 80vh;
        background: #000;
    }

    .camera-controls {
        position: absolute;
        bottom: 2rem;
        left: 0;
        right: 0;
        display: flex;
        justify-content: center;
        gap: 2rem;
    }

    .camera-button {
        background: rgba(255, 255, 255, 0.2);
        border: none;
        border-radius: 50%;
        width: 60px;
        height: 60px;
        font-size: 1.5rem;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background-color 0.2s;
    }

    .camera-button:hover {
        background: rgba(255, 255, 255, 0.3);
    }

    .text-display {
        width: 100%;
        white-space: pre-wrap;
        cursor: text;
        text-align: left;
        color: var(--color-font-primary);
        font-weight: 500 !important; 
    }

    /* Add a new class for empty text display */
    .text-display.empty {
        text-align: center;
        color: var(--color-font-tertiary);
    }

    .file-attachment {
        display: flex;
        align-items: center;
        background: #f5f5f5;
        border-radius: 8px;
        padding: 0.75rem;
        margin: 0.5rem 0;
        gap: 1rem;
        max-width: 80%;
    }

    .file-icon {
        font-size: 1.5rem;
    }

    .file-info {
        display: flex;
        flex-direction: column;
    }

    .file-name {
        font-weight: 500;
        word-break: break-all;
    }

    .video-container {
        width: 100%;
        max-width: 80%;
        margin: 0.5rem 0;
        position: relative;
        background: var(--color-grey-20);
        border-radius: 8px;
        overflow: hidden;
    }

    .preview-video {
        width: 100%;
        max-height: 300px;
        object-fit: contain;
        background: #000;
    }

    .send-button {
        user-select: none;
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
    }

    /* Update icon styles */
    .clickable-icon {
        display: flex;
        align-items: center;
        height: 50px;
        margin-top: 10px;
    }

    .message-input.before-attachment::placeholder,
    .text-display.before-attachment.empty {
        text-align: left;
        color: var(--color-font-tertiary);
    }

    .text-display.empty:not(.before-attachment) {
        text-align: center;
        color: var(--color-font-tertiary);
    }

    .placeholder {
        user-select: none;
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
        color: var(--color-font-tertiary);
    }

    .icon_maps {
        /* Ensure consistent spacing with other icons */
    }

    /* Update left-buttons style if needed */
    .left-buttons {
        display: flex;
        gap: 1rem;
        align-items: center;
        height: 100%;
    }

    .input-wrapper {
        position: relative;
        display: flex;
        align-items: center;
    }

    .mention-display {
        display: flex;
        align-items: center;
        gap: 4px;
        position: absolute;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
        pointer-events: none;
        z-index: 1;
    }

    .at-symbol {
        color: var(--color-font-primary);
        font-weight: 500;
    }

    .message-input.has-mention {
        padding-left: 64px !important;
    }

    .text-display {
        position: relative;
        padding-left: 0;
    }

    .text-display:has(.mention-display) {
        padding-left: 64px;
    }

    /* Add new style to handle placeholder positioning when mate selection is visible */
    .input-wrapper:has(.mention-display) .message-input::placeholder {
        text-align: left;
        left: 64px;
        right: 0;
        width: calc(100% - 64px);
    }
</style>