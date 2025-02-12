<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { slide } from 'svelte/transition';
    import { tooltip } from '../../actions/tooltip';
    import { _ } from 'svelte-i18n';
    import { resizeImage } from './utils/imageHelpers';
    const dispatch = createEventDispatcher();

    let isMobile: boolean = false;
    export let videoElement: HTMLVideoElement;
    let isRecording = false;
    let stream: MediaStream | null = null;
    let mediaRecorder: MediaRecorder | null = null;
    let recordedChunks: Blob[] = [];
    let recordingTime = 0;
    let recordingInterval: ReturnType<typeof setInterval>;
    let showOverlay = false;
    let pendingPhoto: Blob | null = null;

    // Logger using console.debug for debugging.
    const logger = {
        debug: (...args: any[]) => console.debug('[CameraView]', ...args),
        info: (...args: any[]) => console.info('[CameraView]', ...args)
    };

    // Reference to the fallback file input element.
    let fallbackInput: HTMLInputElement;

    onMount(() => {
        // Detect if we're on mobile via a simple user agent test.
        isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
        logger.debug('isMobile:', isMobile);

        // For desktop, trigger the overlay transition.
        if (!isMobile) {
            showOverlay = true;
        }

        // For desktops or non-mobile devices, request camera access.
        if (!isMobile && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            navigator.mediaDevices.getUserMedia({ 
                video: { facingMode: 'environment' },
                audio: false 
            })
            .then(mediaStream => {
                stream = mediaStream;
                if (videoElement) {
                    videoElement.srcObject = stream;
                }
            })
            .catch(err => {
                console.error('Camera access error:', err);
            });
        }
    });

    onDestroy(() => {
        stopCamera();
        stopRecordingTimer();
    });

    function initiateClose() {
        if (isMobile) {
            dispatch('close');
        } else {
            if (showOverlay) {
                showOverlay = false;
            }
        }
    }

    function onOutroEnd() {
        if (pendingPhoto) {
            dispatch('photocaptured', { blob: pendingPhoto });
            pendingPhoto = null;
        }
        dispatch('close');
    }

    function stopCamera() {
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
        if (mediaRecorder && isRecording) {
            mediaRecorder.stop();
        }
        dispatch('focusEditor');
        initiateClose();
    }

    function startRecordingTimer() {
        recordingTime = 0;
        recordingInterval = setInterval(() => {
            recordingTime++;
            const duration = formatTime(recordingTime);
            console.debug('Recording time:', duration);
        }, 1000);
    }

    function stopRecordingTimer() {
        if (recordingInterval) {
            clearInterval(recordingInterval);
        }
    }

    function formatTime(seconds: number): string {
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    }

    async function toggleRecording() {
        if (!stream) return;
        if (!isRecording) {
            try {
                recordingTime = 0;
                const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const tracks = [...stream.getTracks(), ...audioStream.getTracks()];
                stream = new MediaStream(tracks);
                videoElement.srcObject = stream;

                recordedChunks = [];
                mediaRecorder = new MediaRecorder(stream);
                mediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0) {
                        recordedChunks.push(e.data);
                    }
                };
                mediaRecorder.onstop = () => {
                    const blob = new Blob(recordedChunks, { type: 'video/webm' });
                    const finalDuration = formatTime(recordingTime);
                    logger.debug('Stopping recording:', { duration: finalDuration, recordingTime, blobSize: blob.size });
                    dispatch('videorecorded', { blob, duration: finalDuration });
                    recordingTime = 0;
                    initiateClose();
                };

                mediaRecorder.start();
                isRecording = true;
                startRecordingTimer();
            } catch (err) {
                console.error('Audio permission denied:', err);
            }
        } else {
            isRecording = false;
            const finalDuration = formatTime(recordingTime);
            logger.debug('Recording stopped:', { duration: finalDuration, recordingTime });
            stopRecordingTimer();
            if (mediaRecorder) {
                const finalRecordingTime = recordingTime;
                setTimeout(() => {
                    if (mediaRecorder) {
                        mediaRecorder.onstop = () => {
                            const blob = new Blob(recordedChunks, { type: 'video/webm' });
                            const finalDuration = formatTime(finalRecordingTime);
                            logger.debug('Final recording details:', { duration: finalDuration, recordingTime: finalRecordingTime, blobSize: blob.size });
                            dispatch('videorecorded', { blob, duration: finalDuration });
                            recordingTime = 0;
                            initiateClose();
                        };
                        mediaRecorder.stop();
                    }
                }, 300);
            }
        }
    }

    async function capturePhoto() {
        if (!videoElement) return;

        const canvas = document.createElement('canvas');
        canvas.width = videoElement.videoWidth;
        canvas.height = videoElement.videoHeight;
        const ctx = canvas.getContext('2d');

        if (ctx) {
            ctx.drawImage(videoElement, 0, 0);
            canvas.toBlob(async (blob) => {
                if (blob) {
                    try {
                        // Create preview version
                        const { previewBlob, previewUrl } = await resizeImage(blob);
                        
                        // Send both original and preview
                        dispatch('photocaptured', { 
                            blob, // Original for sending
                            previewBlob, // Smaller version for preview
                            previewUrl // Ready to use URL for immediate display
                        });
                        
                        pendingPhoto = previewBlob;
                        setTimeout(() => {
                            initiateClose();
                        }, 150);
                    } catch (error) {
                        console.error('Error creating preview:', error);
                        // Fallback to original if preview creation fails
                        dispatch('photocaptured', { blob, previewBlob: blob, previewUrl: URL.createObjectURL(blob) });
                    }
                }
            }, 'image/jpeg');
        }
    }

    function handleFallbackChange(event: Event) {
        const target = event.target as HTMLInputElement;
        if (target.files && target.files.length > 0) {
            const file = target.files[0];
            console.debug('[CameraView] Fallback media captured:', file);
            // Process the captured file as needed.
        }
    }

    /**
     * Triggered by the main camera button click.
     * Now, it directly opens the hidden fallback input (with 'capture' attribute) on mobile.
     */
    function onCameraButtonClick() {
        if (fallbackInput) {
            fallbackInput.value = "";
            console.debug('[CameraView] Opening fallback file input');
            fallbackInput.click();
        } else {
            console.error('[CameraView] Fallback file input is not available.');
        }
    }
</script>

{#if isMobile}
    <!-- For mobile devices, no extra "Open Camera" button is needed.
         The camera is triggered directly from EnterMessageField.svelte. -->
    <input
        bind:this={fallbackInput}
        type="file"
        accept="image/*,video/*"
        capture="user"
        on:change={handleFallbackChange}
        style="display: none;"
    />
{:else}
    <!-- For non-mobile devices, render the custom camera overlay -->
    {#if showOverlay}
        <div class="camera-overlay" transition:slide={{ duration: 300, axis: 'y' }} on:outroend={onOutroEnd}>
            <video
                bind:this={videoElement}
                autoplay
                playsinline
                muted
                class="camera-preview"
            >
                <track kind="captions" />
            </video>
            <div class="bottom-bar">
                <div class="camera-controls">
                    <button 
                        class="clickable-icon icon_close" 
                        on:click={stopCamera}
                        aria-label={$_('cameraview.close.text')}
                        use:tooltip
                    ></button>
                    {#if isRecording}
                        <div class="recording-timer" transition:slide={{ duration: 300 }}>
                            {formatTime(recordingTime)}
                        </div>
                    {/if}
                    <div class="main-controls">
                        <button 
                            class="control-button video-button"
                            class:recording={isRecording}
                            on:click={toggleRecording}
                            aria-label={isRecording ? $_('cameraview.stoprecording.text') : $_('cameraview.startrecording.text')}
                            use:tooltip
                        >
                            <div class="video-button-inner"></div>
                        </button>

                        <button 
                            class="control-button photo-button"
                            on:click={capturePhoto}
                            disabled={isRecording}
                            class:disabled={isRecording}
                            aria-label={$_('cameraview.takephoto.text')}
                            use:tooltip
                        >
                            <div class="photo-button-inner"></div>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    {/if}
{/if}

<style>
    .camera-overlay {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 400px;
        background: #000;
        z-index: 1000;
        display: flex;
        flex-direction: column;
        border-radius: 24px;
        overflow: hidden;
    }

    .camera-preview {
        width: 100%;
        height: 100%;
        object-fit: cover;
        background: #000;
    }

    .bottom-bar {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 53px;
        background: #000;
        border-radius: 24px;
    }

    .camera-controls {
        height: 100%;
        padding: 0 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        max-width: 100%;
    }

    .control-button {
        border: none;
        padding: 0;
        background: transparent;
        cursor: pointer;
        transition: all 0.3s ease;
    }

    .main-controls {
        display: flex;
        gap: 20px;
        align-items: center;
        margin-left: auto;
        min-width: fit-content;
    }

    .photo-button, .video-button {
        min-width: 35px;
        max-width: 35px;
        min-height: 35px;
        max-height: 35px;
        border-radius: 50%;
        position: relative;
        padding: 0;
        margin: 0;
        flex-shrink: 0;
        flex-basis: 42px;
    }

    .photo-button::before, .video-button::before {
        content: '';
        position: absolute;
        top: -4px;
        left: -4px;
        right: -4px;
        bottom: -4px;
        border: 2px solid white;
        border-radius: 50%;
        opacity: 0.8;
    }

    .photo-button-inner {
        width: 100%;
        height: 100%;
        background: white;
        border-radius: 50%;
        transform: scale(0.93);
        transition: transform 0.15s ease;
    }

    .video-button-inner {
        width: 100%;
        height: 100%;
        background: #ff4444;
        border-radius: 50%;
        transform: scale(0.93);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .video-button.recording .video-button-inner {
        border-radius: 8px;
        transform: scale(0.7);
    }

    /* Hover effects */
    .control-button:hover {
        transform: scale(1.05);
    }

    .control-button:active {
        transform: scale(0.95);
    }

    .clickable-icon {
        width: 25px;
        height: 25px;
        color: white;
    }

    .photo-button:active .photo-button-inner {
        transform: scale(0.7);
    }

    .recording-timer {
        left: 50%;
        transform: translateX(-50%);
        background-color: #FF0000;
        color: white;
        height: 30px;
        padding: 0 15px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 15px;
        font-weight: bold;
        font-family: monospace;
        font-size: 16px;
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
    }

    .photo-button.disabled {
        opacity: 0.5;
        pointer-events: none;
        transition: opacity 0.3s ease;
    }

    .photo-button.disabled::before {
        opacity: 0.4;
    }

    .photo-button.disabled .photo-button-inner {
        opacity: 0.5;
    }

    /* Styling for the main camera button */
    .camera-button {
        padding: 10px 20px;
        background-color: #007bff;
        color: white;
        border: none;
        border-radius: 4px;
        font-size: 16px;
        cursor: pointer;
    }

    .camera-button:hover {
        background-color: #0056b3;
    }
</style> 