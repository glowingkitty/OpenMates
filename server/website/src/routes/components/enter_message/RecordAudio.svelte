<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { slide } from 'svelte/transition';
    import { _ } from 'svelte-i18n';
    
    const dispatch = createEventDispatcher();
    
    let isRecording = false;
    let stream: MediaStream | null = null;
    let mediaRecorder: MediaRecorder | null = null;
    let recordedChunks: Blob[] = [];
    let recordingTime = 0;
    let recordingInterval: ReturnType<typeof setInterval>;
    let startPosition = { x: 0, y: 0 };
    let currentPosition = { x: 0, y: 0 };
    let isDragging = false;
    let circleSize = 0;
    let growthInterval: ReturnType<typeof setInterval>;
    let recordingStartTimeout: ReturnType<typeof setTimeout> = setTimeout(() => {}, 0);
    let isCancelled = false;
    let isAudioPermissionGranted = false;
    let microphonePosition = { x: 0, y: 0 };

    // Add logger
    const logger = {
        debug: (...args: any[]) => console.debug('[RecordAudio]', ...args),
        info: (...args: any[]) => console.info('[RecordAudio]', ...args)
    };

    export let initialPosition: { x: number; y: number };

    onMount(() => {
        logger.debug('Initializing audio recorder');
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('touchmove', handleTouchMove);
        startPosition = initialPosition;
        currentPosition = { ...startPosition };
        startRecording();
    });

    onDestroy(() => {
        stopRecording();
        stopRecordingTimer();
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('touchmove', handleTouchMove);
        clearInterval(growthInterval);
        clearTimeout(recordingStartTimeout);
    });

    function startRecordingTimer() {
        recordingTime = 0;
        recordingInterval = setInterval(() => {
            recordingTime++;
            console.log('Recording time:', recordingTime);
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

    async function startRecording() {
        try {
            console.log('Requesting audio permission...');
            const audioStream = await navigator.mediaDevices.getUserMedia({ 
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true
                }
            });
            stream = audioStream;
            
            // Start timer and animation first
            startRecordingTimer();
            isRecording = true;
            isAudioPermissionGranted = true;
            
            // Start growing circle animation
            circleSize = 0;
            growthInterval = setInterval(() => {
                if (circleSize < 60) {
                    circleSize += 2;
                }
            }, 16);

            // Setup recording
            recordedChunks = [];
            const mimeType = MediaRecorder.isTypeSupported('audio/webm')
                ? 'audio/webm'
                : 'audio/ogg';

            mediaRecorder = new MediaRecorder(stream, {
                mimeType,
                audioBitsPerSecond: 128000
            });
            
            mediaRecorder.ondataavailable = (e) => {
                if (e.data && e.data.size > 0) {
                    recordedChunks.push(e.data);
                }
            };
            
            mediaRecorder.onstop = () => {
                if (!isCancelled) {
                    const blob = new Blob(recordedChunks, { type: mimeType });
                    console.log('Audio recording finished:', { 
                        blobSize: blob.size,
                        duration: recordingTime,
                        chunks: recordedChunks.length,
                        mimeType: blob.type
                    });
                    dispatch('audiorecorded', { blob });
                }
                if (stream) {
                    stream.getTracks().forEach(track => track.stop());
                }
                dispatch('close');
            };

            mediaRecorder.start(100);
            console.log('Recording started successfully');

        } catch (err) {
            console.error('Audio permission denied or error:', err);
            dispatch('close');
        }
    }

    function stopRecording() {
        clearInterval(growthInterval);
        clearTimeout(recordingStartTimeout);
        
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            isRecording = false;
            stopRecordingTimer();
            
            // Only stop and save if not cancelled
            if (!isCancelled) {
                mediaRecorder.stop();
            } else {
                // If cancelled, stop recording and clear chunks
                mediaRecorder.stop();
                recordedChunks = [];
                if (stream) {
                    stream.getTracks().forEach(track => track.stop());
                }
                dispatch('close');
            }
        } else {
            dispatch('close');
        }
    }

    function handleMouseMove(event: MouseEvent) {
        if (!isRecording && !recordingStartTimeout) return;
        
        currentPosition = { x: event.clientX, y: event.clientY };
        checkCancelThreshold();
    }

    function handleTouchMove(event: TouchEvent) {
        if (!isRecording && !recordingStartTimeout) return;
        
        currentPosition = { 
            x: event.touches[0].clientX, 
            y: event.touches[0].clientY 
        };
        checkCancelThreshold();
    }

    function checkCancelThreshold() {
        const deltaX = currentPosition.x - startPosition.x;
        const deltaY = currentPosition.y - startPosition.y;
        // Calculate total distance moved using Pythagorean theorem
        const distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
        
        // Update microphone visual position
        microphonePosition = { x: deltaX, y: deltaY };
        
        // If moved more than 100px in any direction, cancel recording
        if (distance > 100) {
            logger.debug('Recording cancelled - distance threshold reached');
            isCancelled = true;
            stopRecording();
        }
    }
</script>

<div class="record-overlay" transition:slide={{ duration: 300, axis: 'y' }}>
    <div class="record-content">
        <h2 class="header-text">{$_('enter_message.record_audio.release_to_finish.text')}</h2>
        
        <div class="controls-row">
            {#if isRecording}
                <div class="timer-pill" transition:slide={{ duration: 300 }}>
                    {formatTime(recordingTime)}
                </div>
            {/if}
            
            <div class="cancel-indicator">
                <div class="cancel-x">✕</div>
                <span>{$_('enter_message.record_audio.slide_left_to_cancel.text')}</span>
            </div>

            <div class="record-button-wrapper"
                 role="button"
                 tabindex="0"
                 style="transform: translate({microphonePosition.x}px, {microphonePosition.y}px)">
                <div class="microphone-icon" class:recording={isRecording}></div>
            </div>
        </div>
    </div>
</div>

<style>
    .record-overlay {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        background: var(--color-record-audio-background);
        z-index: 900;
        border-radius: 24px;
        overflow: hidden;
        padding: 16px;
    }

    .record-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
    }

    .header-text {
        color: white;
        font-size: 18px;
        margin: 0;
    }

    .controls-row {
        width: 100%;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 16px;
    }

    .timer-pill {
        background-color: #FF0000;
        color: white;
        padding: 8px 16px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 16px;
    }

    .cancel-indicator {
        color: white;
        opacity: 0.5;
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 16px;
        transition: color 0.1s ease-out;
    }

    .cancel-x {
        font-size: 20px;
    }

    .record-button-wrapper {
        position: relative;
        width: 48px;
        height: 48px;
        transition: transform 0.1s ease-out;
        will-change: transform;
        cursor: grab;
    }

    .microphone-icon {
        position: relative;
        width: 48px;
        height: 48px;
        /* Remove the background from here */
        /* Add a pseudo-element for the background circle */
    }
</style> 