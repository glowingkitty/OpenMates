<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { slide } from 'svelte/transition';
    
    const dispatch = createEventDispatcher();
    
    export let videoElement: HTMLVideoElement;
    let isRecording = false;
    let stream: MediaStream | null = null;
    let mediaRecorder: MediaRecorder | null = null;
    let recordedChunks: Blob[] = [];
    let recordingTime = 0;
    let recordingInterval: ReturnType<typeof setInterval>;
    
    onMount(() => {
        // Only request camera permission initially
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
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

    function stopCamera() {
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
        if (mediaRecorder && isRecording) {
            mediaRecorder.stop();
        }
        dispatch('focusEditor');
        dispatch('close');
    }

    function startRecordingTimer() {
        recordingTime = 0;
        recordingInterval = setInterval(() => {
            recordingTime++;
        }, 1000);
    }

    function stopRecordingTimer() {
        if (recordingInterval) {
            clearInterval(recordingInterval);
            recordingTime = 0;
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
                // Request audio permission only when starting recording
                const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const tracks = [...stream.getTracks(), ...audioStream.getTracks()];
                stream = new MediaStream(tracks);
                videoElement.srcObject = stream;
                
                // Start recording
                recordedChunks = [];
                mediaRecorder = new MediaRecorder(stream);
                
                mediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0) {
                        recordedChunks.push(e.data);
                    }
                };
                
                mediaRecorder.onstop = () => {
                    const blob = new Blob(recordedChunks, { type: 'video/webm' });
                    dispatch('videorecorded', { blob });
                    isRecording = false;
                    dispatch('close');
                };
                
                mediaRecorder.start();
                isRecording = true;
                startRecordingTimer();
            } catch (err) {
                console.error('Audio permission denied:', err);
            }
        } else {
            mediaRecorder?.stop();
            stopRecordingTimer();
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
                    // Dispatch the event with the photo blob
                    dispatch('photocaptured', { blob });
                    
                    // Add a small delay to allow the button animation to complete
                    await new Promise(resolve => setTimeout(resolve, 150));
                    
                    // Close the camera view
                    dispatch('close');
                }
            }, 'image/jpeg');
        }
    }
</script>

<div class="camera-overlay" transition:slide={{ duration: 300, axis: 'y' }}>
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
        transition: all 0.3s ease;
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