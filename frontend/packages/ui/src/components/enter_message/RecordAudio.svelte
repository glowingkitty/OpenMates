<!-- frontend/packages/ui/src/components/enter_message/RecordAudio.svelte -->
<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { slide } from 'svelte/transition';
    import { text } from '@repo/ui'; // Assuming this is your text store import

    // Define dispatched events more precisely
    const dispatch = createEventDispatcher<{
        // blob: raw audio data; duration: in seconds; mimeType: e.g. 'audio/webm'
        audiorecorded: { blob: Blob; duration: number; mimeType: string };
        close: void; // Dispatched when the component should close (after recording/cancel)
        cancel: void; // Dispatched specifically on cancellation (drag or external call)
        recordingStateChange: { active: boolean }; // Renamed from layoutChange
    }>();

    // --- Props using Svelte 5 $props() ---
    interface Props {
        initialPosition: { x: number; y: number };
        externalStream?: MediaStream | null;
    }
    let { 
        initialPosition,
        externalStream = null
    }: Props = $props();

    // --- Internal State ---
    let isRecording = $state(false);
    let internalStream: MediaStream | null = null; // Stream created internally if externalStream is null
    let mediaRecorder: MediaRecorder | null = null;
    let recordedChunks: Blob[] = [];
    let recordingTime = $state(0);
    let recordingInterval: ReturnType<typeof setInterval> | null = null;
    let startPosition = { x: 0, y: 0 };
    let currentPosition = { x: 0, y: 0 };
    // let isDragging = false; // Not explicitly used, remove?
    // let circleSize = 0; // Not used in template, remove?
    // let growthInterval: ReturnType<typeof setInterval>; // Not used in template, remove?
    let isCancelled = false; // Flag to indicate cancellation by dragging or external call
    let microphonePosition = $state({ x: 0, y: 0 }); // For visual feedback

    // Simple logger
    const logger = {
        debug: (...args: any[]) => console.debug('[RecordAudio]', ...args),
        info: (...args: any[]) => console.info('[RecordAudio]', ...args),
        error: (...args: any[]) => console.error('[RecordAudio]', ...args),
    };

    // --- Lifecycle ---
    onMount(() => {
        logger.debug('Component mounted, initializing audio recorder.');
        // Use the provided initial position
        startPosition = { ...initialPosition };
        currentPosition = { ...startPosition };
        microphonePosition = { x: 0, y: 0 }; // Reset visual position

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('touchmove', handleTouchMove, { passive: false }); // Allow preventDefault

        // Start the recording process
        initializeAndStartRecording();

        // Notify parent that the recording UI is active
        dispatch('recordingStateChange', { active: true });
    });

    onDestroy(() => {
        logger.debug('Component destroying.');
        // Ensure recording is stopped and resources are cleaned up
        // Pass true to indicate potential cancellation if destroyed mid-recording
        stopInternal(true);

        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('touchmove', handleTouchMove);

        // Notify parent that the recording UI is inactive
        dispatch('recordingStateChange', { active: false });
    });

    // --- Recording Logic ---

    async function initializeAndStartRecording() {
        isCancelled = false; // Reset cancellation flag
        recordedChunks = []; // Reset chunks

        try {
            let streamToUse: MediaStream;
            if (externalStream) {
                logger.info('Using external stream provided from parent.');
                streamToUse = externalStream;
                // We don't manage this stream's tracks
            } else {
                logger.debug('Requesting audio permission via getUserMedia...');
                internalStream = await navigator.mediaDevices.getUserMedia({
                    audio: { echoCancellation: true, noiseSuppression: true }
                });
                streamToUse = internalStream;
                logger.info('Internal audio stream acquired.');
            }

            // Determine MIME type
            let mimeType = 'audio/webm'; // Default preference
            if (MediaRecorder.isTypeSupported('audio/mp4')) { // iOS often prefers mp4
                mimeType = 'audio/mp4';
            } else if (!MediaRecorder.isTypeSupported('audio/webm')) { // Fallback if webm not supported
                 mimeType = 'audio/ogg'; // Or even default ''
                 logger.info('Using fallback mimeType:', mimeType || 'default');
            }

            mediaRecorder = new MediaRecorder(streamToUse, {
                mimeType: mimeType || undefined, // Use determined type or let browser decide
                audioBitsPerSecond: 128000
            });

            mediaRecorder.ondataavailable = (e) => {
                if (e.data && e.data.size > 0) {
                    recordedChunks.push(e.data);
                }
            };

            mediaRecorder.onstop = () => {
                logger.debug('MediaRecorder stopped.');
                // This handler executes *after* stop() is called

                // Clean up the internally created stream only
                if (internalStream) {
                    logger.debug('Stopping internal stream tracks.');
                    internalStream.getTracks().forEach(track => track.stop());
                    internalStream = null; // Clear reference
                } else {
                     logger.debug('External stream used, not stopping tracks.');
                }

                if (!isCancelled && recordedChunks.length > 0) {
                    const finalMimeType = mediaRecorder?.mimeType || mimeType;
                    const blob = new Blob(recordedChunks, { type: finalMimeType });
                    const finalDuration = recordingTime; // Use time captured before stop
                    logger.info('Audio recording finished successfully:', {
                        blobSize: `${(blob.size / 1024).toFixed(2)} KB`,
                        duration: `${finalDuration}s (${formatTime(finalDuration)})`,
                        mimeType: blob.type,
                    });
                    dispatch('audiorecorded', { blob, duration: finalDuration, mimeType: finalMimeType });
                } else if (isCancelled) {
                    logger.info('Recording was cancelled, not dispatching audiorecorded.');
                    dispatch('cancel'); // Dispatch specific cancel event
                } else {
                    logger.info('Recording stopped with no data or was cancelled before data.');
                     if (!isCancelled) dispatch('cancel'); // Treat no data as cancellation unless already cancelled
                }

                // Reset state after processing
                isRecording = false;
                recordedChunks = [];
                recordingTime = 0;
                stopRecordingTimer(); // Ensure timer is stopped

                // Signal component closure AFTER processing is done
                dispatch('close');
            };

            mediaRecorder.onerror = (event) => {
                logger.error('MediaRecorder error:', event);
                // Handle error appropriately, maybe dispatch an error event
                stopInternal(true); // Attempt cleanup on error
            };

            // Start recording
            mediaRecorder.start(); // Record continuously
            isRecording = true;
            logger.info('MediaRecorder started successfully.');
            startRecordingTimer(); // Start UI timer

        } catch (err) {
            logger.error('Failed to initialize or start recording:', err);
            isRecording = false;
            stopRecordingTimer();
            // Clean up potentially created internal stream on error
            if (internalStream) {
                internalStream.getTracks().forEach(track => track.stop());
                internalStream = null;
            }
            dispatch('close'); // Close component on error
        }
    }

    /** Internal function to stop recording, handles state checks */
    function stopInternal(cancelled = false) {
        if (!isRecording && mediaRecorder?.state !== 'recording' && mediaRecorder?.state !== 'paused') {
            logger.debug('stopInternal called but not recording.');
            // Ensure cleanup if called redundantly after stop
            stopRecordingTimer();
            if (internalStream) {
                internalStream.getTracks().forEach(track => track.stop());
                internalStream = null;
            }
            return; // Already stopped or never started properly
        }

        isCancelled = isCancelled || cancelled; // Mark as cancelled if requested
        logger.info(`Stopping recording. Cancelled: ${isCancelled}`);

        // Stop the UI timer immediately to capture final duration
        stopRecordingTimer();
        isRecording = false; // Update state variable

        if (mediaRecorder && (mediaRecorder.state === 'recording' || mediaRecorder.state === 'paused')) {
             try {
                mediaRecorder.stop(); // Triggers the 'onstop' handler
             } catch (e) {
                logger.error("Error stopping MediaRecorder:", e);
                // Force cleanup if stop fails
                if (internalStream) {
                    internalStream.getTracks().forEach(track => track.stop());
                    internalStream = null;
                }
                dispatch('close');
             }
        } else {
            logger.error('MediaRecorder not found or not in a stoppable state.');
            // Manually clean up if recorder is missing or in wrong state
            if (internalStream) {
                internalStream.getTracks().forEach(track => track.stop());
                internalStream = null;
            }
            dispatch('close'); // Close if recorder wasn't active
        }
    }

    // --- Timer ---
    function startRecordingTimer() {
        stopRecordingTimer(); // Clear existing interval if any
        recordingTime = 0;
        recordingInterval = setInterval(() => {
            recordingTime++;
            // logger.debug('Recording time:', formatTime(recordingTime)); // Can be noisy
        }, 1000);
    }

    function stopRecordingTimer() {
        if (recordingInterval) {
            clearInterval(recordingInterval);
            recordingInterval = null;
        }
    }

    function formatTime(seconds: number): string {
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    }

    // --- Drag/Cancel Logic ---
    function handleMouseMove(event: MouseEvent) {
        if (!isRecording) return; // Only track while actively recording
        currentPosition = { x: event.clientX, y: event.clientY };
        checkCancelThreshold();
    }

    function handleTouchMove(event: TouchEvent) {
        if (!isRecording) return;
        // Prevent default scroll/zoom behavior while dragging for recording
        event.preventDefault();
        if (event.touches.length > 0) {
            currentPosition = {
                x: event.touches[0].clientX,
                y: event.touches[0].clientY
            };
            checkCancelThreshold();
        }
    }

    function checkCancelThreshold() {
        const deltaX = currentPosition.x - startPosition.x;
        const deltaY = currentPosition.y - startPosition.y;
        const distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);

        // Update visual position (limited for safety)
        const maxOffset = 50; // Limit visual drag distance
        microphonePosition = {
            x: Math.max(-maxOffset, Math.min(maxOffset, deltaX)),
            y: Math.max(-maxOffset, Math.min(maxOffset, deltaY))
        };

        // Check cancellation threshold
        const cancelDistance = 100; // Pixels to drag to cancel
        if (distance > cancelDistance) {
            logger.debug('Recording cancelled - distance threshold reached');
            stopInternal(true); // Stop and mark as cancelled
        }
    }

    // --- Exported Methods for Parent Control ---
    /** Stops the recording and dispatches the 'audiorecorded' event if successful. */
    export function stop() {
        logger.debug('stop() called externally.');
        stopInternal(false); // Not cancelled by this call itself
    }

    /** Cancels the recording, preventing the 'audiorecorded' event. */
    export function cancel() {
        logger.debug('cancel() called externally.');
        stopInternal(true); // Mark as cancelled
    }

</script>

<div class="record-overlay" transition:slide={{ duration: 200, axis: 'y' }}>
    <div class="record-content">
        <!-- Use $text for translation -->
        <h2 class="header-text">{@html $text('enter_message.record_audio.release_to_finish')}</h2>

        <div class="controls-row">
            {#if isRecording}
                <!-- Timer Pill -->
                <div class="timer-pill" transition:slide={{ duration: 200 }}>
                    {formatTime(recordingTime)}
                </div>
            {:else}
                 <!-- Placeholder for alignment -->
                <div class="timer-pill placeholder">00:00</div>
            {/if}

            <!-- Cancel Indicator -->
            <div class="cancel-indicator">
                <div class="cancel-x">✕</div>
                <span>{@html $text('enter_message.record_audio.slide_left_to_cancel')}</span>
            </div>

            <!-- Draggable Microphone -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <!-- svelte-ignore a11y_missing_attribute -->
            <div class="record-button-wrapper"
                 role="button"
                 style="transform: translate({microphonePosition.x}px, {microphonePosition.y}px); touch-action: none;"
                 >
                 <!-- touch-action: none prevents scrolling on touch devices while dragging -->
                <div class="microphone-icon icon_recordaudio" class:recording={isRecording}></div>
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
        background: var(--color-record-audio-background, rgba(0, 0, 0, 0.8)); /* Fallback color */
        z-index: 900; /* Ensure it's above action buttons but below modals */
        border-radius: 24px 24px 0 0; /* Rounded top corners */
        overflow: hidden;
        padding: 16px;
        box-sizing: border-box;
        color: white; /* Default text color */
    }

    .record-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
    }

    .header-text {
        color: inherit;
        font-size: 16px; /* Slightly smaller */
        font-weight: 500;
        margin: 0;
        text-align: center;
    }

    .controls-row {
        width: 100%;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 8px; /* Reduced padding */
        box-sizing: border-box;
        min-height: 48px; /* Ensure row has height */
    }

    .timer-pill {
        background-color: var(--color-app-audio, #FF0000); /* Use theme color */
        color: white;
        padding: 6px 12px; /* Slightly smaller */
        border-radius: 16px;
        font-weight: 600;
        font-size: 14px;
        min-width: 50px; /* Ensure space */
        text-align: center;
        box-sizing: border-box;
    }
    .timer-pill.placeholder {
        opacity: 0;
        pointer-events: none;
    }


    .cancel-indicator {
        color: inherit;
        opacity: 0.6; /* Slightly more visible */
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 13px; /* Smaller text */
        transition: opacity 0.2s ease-out;
        text-align: center;
        flex-grow: 1; /* Allow it to take space */
        justify-content: center; /* Center text */
        padding: 0 10px; /* Add some padding */
    }

    .cancel-x {
        font-size: 16px;
        line-height: 1;
    }

    .record-button-wrapper {
        position: relative; /* Keep relative for transform */
        width: 48px;
        height: 48px;
        transition: transform 0.1s ease-out;
        will-change: transform;
        cursor: grabbing; /* Indicate draggable state */
        flex-shrink: 0; /* Prevent shrinking */
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .microphone-icon {
        width: 24px; /* Adjust icon size */
        height: 24px;
        background-color: white; /* Use CSS mask for icon */
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
        /* Assuming icon_recordaudio provides the mask */
    }

    /* Add styles for the recording state if needed, e.g., pulsing */
    .microphone-icon.recording {
       /* Example: animation: pulse 1.5s infinite; */
    }

    /* Example pulse animation */
    @keyframes pulse {
        0% { transform: scale(1); }
        50% { transform: scale(1.1); }
        100% { transform: scale(1); }
    }
</style>