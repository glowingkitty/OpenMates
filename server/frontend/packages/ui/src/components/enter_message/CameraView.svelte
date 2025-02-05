<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { slide } from 'svelte/transition';
    import NativeCamera from './NativeCamera.svelte'; // Import our native camera component
    
    const dispatch = createEventDispatcher();
    
    // Flag to detect if we're on a mobile device (iOS/Android)
    let isMobile: boolean = false;
    
    export let videoElement: HTMLVideoElement;
    let isRecording = false;
    let stream: MediaStream | null = null;
    let mediaRecorder: MediaRecorder | null = null;
    let recordedChunks: Blob[] = [];
    let recordingTime = 0;
    let recordingInterval: ReturnType<typeof setInterval>;
    
    // New flag to control when the custom overlay is rendered.
    // By default it is false so that when we set it to true on mount,
    // the overlay is newly inserted in the DOM (triggering the slide transition).
    let showOverlay = false;
    
    // New variable to store a captured photo until the closing transition completes.
    let pendingPhoto: Blob | null = null;
    
    // Logger using console.debug (as per Svelte logging best practices)
    const logger = {
        debug: (...args: any[]) => console.debug('[CameraView]', ...args),
        info: (...args: any[]) => console.info('[CameraView]', ...args)
    };

    // onMount to initialize things. We check for mobile device here.
    onMount(() => {
        // Simple user agent check for mobile platforms.
        isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
        logger.debug('isMobile:', isMobile);

        // For non-mobile devices, trigger the slide transition by setting
        // showOverlay to true so that the custom overlay gets added after mount.
        if (!isMobile) {
            showOverlay = true;
        }

        // Only request camera permission when not on mobile.
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

    /**
     * Triggered when the slide-out (exit) transition completes.
     * If a photo was captured, dispatches the 'photocaptured' event,
     * then dispatches the 'close' event.
     */
    function onOutroEnd() {
        // If a photo was captured, dispatch the photocaptured event.
        if (pendingPhoto) {
            dispatch('photocaptured', { blob: pendingPhoto });
            pendingPhoto = null;
        }
        // Finally, dispatch the close event to let the parent unmount the component.
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
            // Log formatted recording time for debugging
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
                // Reset the recording time for a new recording session.
                recordingTime = 0;
                // Request audio permission when starting a recording.
                const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const tracks = [...stream.getTracks(), ...audioStream.getTracks()];
                stream = new MediaStream(tracks);
                videoElement.srcObject = stream;
                
                // Prepare for recording by clearing previous chunks.
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
                    logger.debug('Stopping recording:', {
                        duration: finalDuration,
                        recordingTime,
                        blobSize: blob.size
                    });
                    
                    dispatch('videorecorded', { 
                        blob,
                        duration: finalDuration
                    });
                    
                    // Reset recording time and close view.
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
            logger.debug('Recording stopped:', {
                duration: finalDuration,
                recordingTime
            });
            
            // Stop the timer while retaining the final recordingTime.
            stopRecordingTimer();

            if (mediaRecorder) {
                const finalRecordingTime = recordingTime;
                setTimeout(() => {
                    if (mediaRecorder) {
                        mediaRecorder.onstop = () => {
                            const blob = new Blob(recordedChunks, { type: 'video/webm' });
                            const finalDuration = formatTime(finalRecordingTime);
                            logger.debug('Final recording details:', {
                                duration: finalDuration,
                                recordingTime: finalRecordingTime,
                                blobSize: blob.size
                            });
                            
                            dispatch('videorecorded', { 
                                blob,
                                duration: finalDuration
                            });
                            
                            recordingTime = 0;
                            initiateClose();
                        };
                        mediaRecorder.stop();
                    }
                }, 300);
            }
        }
    }

    /**
     * Captures a photo from the video preview.
     * Instead of dispatching the event immediately, stores the photo in pendingPhoto,
     * then triggers the smooth close transition.
     */
    async function capturePhoto() {
        if (!videoElement) return;

        // Create a canvas that matches the video dimensions.
        const canvas = document.createElement('canvas');
        canvas.width = videoElement.videoWidth;
        canvas.height = videoElement.videoHeight;
        const ctx = canvas.getContext('2d');

        if (ctx) {
            // Draw the current frame of the video into the canvas.
            ctx.drawImage(videoElement, 0, 0);
            // Convert the drawn frame into a JPEG blob.
            canvas.toBlob((blob) => {
                if (blob) {
                    // Store the blob in pendingPhoto instead of dispatching immediately.
                    pendingPhoto = blob;
                    // Optional delay to allow button animation to complete.
                    setTimeout(() => {
                        initiateClose();
                    }, 150);
                }
            }, 'image/jpeg');
        }
    }

    /**
     * Handler for media captured using the native camera controls.
     * The event.detail.file contains the captured media file (image or video).
     *
     * @param event The custom event from the NativeCamera component.
     */
    function handleMediaCaptured(event) {
        const { file } = event.detail;
        console.debug('[CameraView] Native media captured:', file);
        // Dispatch an event so that parent components know a file has been captured.
        dispatch('mediaCaptured', { file });
        // Optionally close the camera view.
        initiateClose();
    }
</script>

<!-- Conditionally render based on the platform -->
{#if isMobile}
    <!-- On mobile devices, use the native camera which shows the device's regular camera controls -->
    <div class="native-camera-container">
        <NativeCamera on:mediaCaptured={handleMediaCaptured} />
    </div>
{:else}
    <!-- On desktop or non-mobile devices, use the custom camera overlay -->
    {#if showOverlay}
    <div class="camera-overlay" transition:slide={{ duration: 300, axis: 'y' }} on:outroend={onOutroEnd}>
        <video
            bind:this={videoElement}
            autoplay
            playsinline
            class="camera-preview"
        >
            <track kind="captions" />
        </video>
        
        <div class="bottom-bar">
            <div class="camera-controls">
                <button 
                    class="clickable-icon icon_close" 
                    on:click={stopCamera}
                    aria-label="Close camera"
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
                        aria-label={isRecording ? "Stop recording" : "Start recording"}
                    >
                        <div class="video-button-inner"></div>
                    </button>
                    
                    <button 
                        class="control-button photo-button"
                        on:click={capturePhoto}
                        disabled={isRecording}
                        class:disabled={isRecording}
                        aria-label="Take photo"
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
</style> 