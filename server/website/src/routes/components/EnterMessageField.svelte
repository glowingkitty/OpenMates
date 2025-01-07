<script lang="ts">
    import { tick, onDestroy } from 'svelte';
    import Photos from './in_message_previews/Photos.svelte';
    import PDF from './in_message_previews/PDF.svelte';
    import Web from './in_message_previews/Web.svelte';

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

        // Show if:
        // 1. Has content or attachment
        // 2. Is first segment
        // 3. Is last segment (for input)
        // 4. Is between non-attachment segments AND has content
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
            alert(`Total file size would exceed ${FILE_SIZE_LIMITS.TOTAL_MAX_SIZE}MB limit. Current size: ${(currentSize / 1024 / 1024).toFixed(1)}MB, Attempted to add: ${(newFilesSize / 1024 / 1024).toFixed(1)}MB`);
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
            alert(`Total file size would exceed ${FILE_SIZE_LIMITS.TOTAL_MAX_SIZE}MB limit. Current size: ${(currentSize / 1024 / 1024).toFixed(1)}MB, Attempted to add: ${(newFilesSize / 1024 / 1024).toFixed(1)}MB`);
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
                        alert(`Adding this photo would exceed the ${FILE_SIZE_LIMITS.TOTAL_MAX_SIZE}MB limit. Current size: ${(getCurrentAttachmentsSize() / 1024 / 1024).toFixed(1)}MB`);
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
    async function adjustTextareaHeight(textarea: HTMLTextAreaElement) {
        // Reset height to auto to get the correct scrollHeight
        textarea.style.height = 'auto';
        // Set the height to match the content
        textarea.style.height = textarea.scrollHeight + 'px';
    }

    // Modify the existing handleKeydown function to include height adjustment
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

        // Update Backspace handling to include videos
        if (event.key === 'Backspace') {
            if (textarea.selectionStart === 0 && textarea.selectionEnd === 0 && index > 0) {
                event.preventDefault();
                
                const currentText = textarea.value;
                const prevSegment = textSegments[index - 1];
                
                if (prevSegment.webUrl) {
                    const url = prevSegment.webUrl;
                    // Remove the web preview and append URL to previous text segment
                    const prevPrevSegment = index > 1 ? textSegments[index - 2] : null;
                    
                    if (prevPrevSegment) {
                        // Append URL to previous text segment without extra space
                        textSegments = [
                            ...textSegments.slice(0, index - 2),
                            {
                                ...prevPrevSegment,
                                text: (prevPrevSegment.text + ' ' + url + currentText).trim(),
                                isEditing: true
                            },
                            ...textSegments.slice(index + 1)
                        ];
                        activeSegmentId = prevPrevSegment.id;
                    } else {
                        // Create new text segment with URL without extra space
                        textSegments = [
                            {
                                id: crypto.randomUUID(),
                                text: url + currentText,
                                isEditing: true
                            },
                            ...textSegments.slice(index + 1)
                        ];
                        activeSegmentId = textSegments[0].id;
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

    // Add new function to handle input events
    function handleInput(event: Event) {
        const textarea = event.target as HTMLTextAreaElement;
        adjustTextareaHeight(textarea);
        
        const currentIndex = textSegments.findIndex(s => s.id === activeSegmentId);
        if (currentIndex !== -1) {
            handleUrlDetection(textSegments[currentIndex], currentIndex);
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
        // Only proceed if the text ends with a space or if space was just pressed
        if (!segment.text.endsWith(' ')) {
            return;
        }

        const words = segment.text.trim().split(' ');
        const lastWord = words[words.length - 1]; // Get the last word

        // Check if the last word is a valid URL
        if (lastWord && urlRegex.test(lastWord)) {
            const url = lastWord;
            const newSegmentId = crypto.randomUUID();
            const textBeforeUrl = words.slice(0, -1).join(' '); // Everything except URL

            // Update segments to create web preview
            textSegments = [
                ...textSegments.slice(0, index),
                { ...segment, text: textBeforeUrl },
                { id: crypto.randomUUID(), text: '', isEditing: false, webUrl: url },
                { id: newSegmentId, text: '', isEditing: true },
                ...textSegments.slice(index + 1)
            ];

            activeSegmentId = newSegmentId;
        }
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

                // Create new segments
                textSegments = [
                    ...textSegments.slice(0, currentIndex),
                    { ...segment, text: textBefore.trim() },
                    { id: crypto.randomUUID(), text: '', isEditing: false, webUrl: pastedText },
                    { id: crypto.randomUUID(), text: textAfter.trim(), isEditing: true },
                    ...textSegments.slice(currentIndex + 1)
                ];

                // Set focus to the last segment
                activeSegmentId = textSegments[currentIndex + 2].id;

                tick().then(() => {
                    const newTextarea = document.getElementById(activeSegmentId) as HTMLTextAreaElement;
                    if (newTextarea) newTextarea.focus();
                });
            }
        }
    }
</script>

<div class="message-container">
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
                        <textarea
                            id={segment.id}
                            bind:value={segment.text}
                            on:focus={() => activeSegmentId = segment.id}
                            on:keydown={(e) => handleKeydown(e, index)}
                            on:input={handleInput}
                            on:paste={handlePaste}
                            on:blur={() => segment.isEditing = false}
                            placeholder={index === 0 ? "Type your message here..." : ""}
                            rows="1"
                        ></textarea>
                    {:else}
                        <div
                            class="text-display"
                            on:click={(e) => handleTextClick(segment, e)}
                            on:keydown={(e) => handleKeyPress(segment, e)}
                            tabindex="0"
                            role="textbox"
                        >
                            {segment.text || '\u00A0'}
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
                aria-label="Attach files"
            ></button>
            <button 
                class="clickable-icon icon_camera" 
                on:click={handleCameraClick} 
                aria-label="Take photo or video"
            ></button>
        </div>
        
        {#if hasContent}
            <button on:click={handleSend}>Send</button>
        {/if}
    </div>
</div>

<style>
    .message-container {
        width: 100%;
        min-height: 100px;
        max-height: 350px;
        background-color: #FFFFFF;
        border-radius: 24px;
        padding: 1rem 1rem 50px 1rem;
        box-sizing: border-box;
        position: relative;
    }

    .scrollable-content {
        width: 100%;
        height: 100%;
        max-height: 250px;
        overflow-y: auto;
        position: relative;
        padding: 0.5rem 0;
        scrollbar-width: thin;
        scrollbar-color: rgba(0, 0, 0, 0.2) transparent;
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

    textarea {
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
    }

    .action-buttons {
        position: absolute;
        bottom: 1rem;
        left: 1rem;
        right: 1rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .left-buttons {
        display: flex;
        gap: 1rem;
        align-items: center;
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
        min-height: 2em;
        padding: 0.5rem 0;
        white-space: pre-wrap;
        cursor: text;
        line-height: 1.5;
        font-size: 1rem;
    }

    /* Make text-display look similar to textarea */
    .text-display:hover {
        background-color: rgba(0, 0, 0, 0.05);
        border-radius: 4px;
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
        background: #f5f5f5;
        border-radius: 8px;
        overflow: hidden;
    }

    .preview-video {
        width: 100%;
        max-height: 300px;
        object-fit: contain;
        background: #000;
    }
</style>
