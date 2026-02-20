<!-- frontend/packages/ui/src/components/enter_message/RecordAudio.svelte -->
<!--
  Audio recording UI — renders as a full overlay inside .message-field.
  Replaces the normal message field appearance with a purple/blue gradient
  while recording is in progress, matching the Figma design:

  ┌──────────────────────────────────────────────────────┐
  │              Release to finish                       │  ← bold, centered
  │                                                      │
  │  [00:01]   ← Slide left to cancel     [●mic]         │  ← controls row
  └──────────────────────────────────────────────────────┘

  Release / stop behaviour:
  ─────────────────────────
  The overlay covers the entire message field (inset:0, z-index:200), so the
  original mic button underneath can never receive mouseup/touchend after the
  overlay mounts. We therefore own ALL pointer-release and keyboard events here,
  via document-level listeners attached on mount and removed on destroy:

    • mouseup   → stop()  (complete recording → audiorecorded event)
    • touchend  → stop()  (complete recording on mobile)
    • keydown Escape → cancel()  (discard recording)

  Drag-left-to-cancel:
  ────────────────────
  mousemove / touchmove track horizontal displacement from the start position.
  Dragging left >100px triggers cancel(). The mic circle follows the drag so
  the user gets visual feedback.

  Exported methods (called by parent as fallback):
    stop()   — complete the recording
    cancel() — discard the recording
-->
<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';

    const dispatch = createEventDispatcher<{
        audiorecorded: { blob: Blob; duration: number; mimeType: string };
        close: void;
        cancel: void;
        recordingStateChange: { active: boolean };
    }>();

    // --- Props ---
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
    let internalStream: MediaStream | null = null;
    let mediaRecorder: MediaRecorder | null = null;
    let recordedChunks: Blob[] = [];
    let recordingTime = $state(0);
    let recordingInterval: ReturnType<typeof setInterval> | null = null;
    let startPosition = { x: 0, y: 0 };
    let currentPosition = { x: 0, y: 0 };
    let isCancelled = false;
    // Whether stop() has already been called (prevents double-stop from both
    // document mouseup and parent's onRecordMouseUp after tick()).
    let stopAlreadyCalled = false;
    // Horizontal drag offset for the cancel animation (negative = dragging left)
    let dragOffsetX = $state(0);

    const logger = {
        debug: (...args: any[]) => console.debug('[RecordAudio]', ...args),
        info:  (...args: any[]) => console.info('[RecordAudio]',  ...args),
        error: (...args: any[]) => console.error('[RecordAudio]', ...args),
    };

    // --- Lifecycle ---
    onMount(() => {
        logger.debug('Component mounted, starting recording.');
        startPosition = { ...initialPosition };
        currentPosition = { ...startPosition };

        // Attach document-level listeners so release / Escape work even though
        // the overlay completely covers the original mic button.
        document.addEventListener('mouseup',   handleDocumentMouseUp);
        document.addEventListener('touchend',  handleDocumentTouchEnd);
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('touchmove', handleTouchMove, { passive: false });
        document.addEventListener('keydown',   handleKeyDown);

        initializeAndStartRecording();
        dispatch('recordingStateChange', { active: true });
    });

    onDestroy(() => {
        logger.debug('Component destroying.');
        // Guard: don't double-stop if stop/cancel already ran
        if (!stopAlreadyCalled) {
            stopInternal(true);
        }
        document.removeEventListener('mouseup',   handleDocumentMouseUp);
        document.removeEventListener('touchend',  handleDocumentTouchEnd);
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('touchmove', handleTouchMove);
        document.removeEventListener('keydown',   handleKeyDown);
        dispatch('recordingStateChange', { active: false });
    });

    // --- Recording Logic ---
    async function initializeAndStartRecording() {
        isCancelled = false;
        stopAlreadyCalled = false;
        recordedChunks = [];

        try {
            let streamToUse: MediaStream;
            if (externalStream) {
                logger.info('Using external stream provided from parent.');
                streamToUse = externalStream;
            } else {
                logger.debug('Requesting audio via getUserMedia...');
                internalStream = await navigator.mediaDevices.getUserMedia({
                    audio: { echoCancellation: true, noiseSuppression: true }
                });
                streamToUse = internalStream;
                logger.info('Internal audio stream acquired.');
            }

            // Prefer mp4 on iOS; fall back to webm or ogg
            let mimeType = 'audio/webm';
            if (MediaRecorder.isTypeSupported('audio/mp4')) {
                mimeType = 'audio/mp4';
            } else if (!MediaRecorder.isTypeSupported('audio/webm')) {
                mimeType = 'audio/ogg';
                logger.info('Using fallback mimeType:', mimeType);
            }

            mediaRecorder = new MediaRecorder(streamToUse, {
                mimeType: mimeType || undefined,
                audioBitsPerSecond: 128000
            });

            mediaRecorder.ondataavailable = (e) => {
                if (e.data && e.data.size > 0) recordedChunks.push(e.data);
            };

            mediaRecorder.onstop = () => {
                logger.debug('MediaRecorder stopped.');

                // Release the mic track
                if (internalStream) {
                    internalStream.getTracks().forEach(track => track.stop());
                    internalStream = null;
                }

                if (!isCancelled && recordedChunks.length > 0) {
                    const finalMimeType = mediaRecorder?.mimeType || mimeType;
                    const blob = new Blob(recordedChunks, { type: finalMimeType });
                    const finalDuration = recordingTime;
                    logger.info('Recording finished:', {
                        blobSize: `${(blob.size / 1024).toFixed(2)} KB`,
                        duration:  `${finalDuration}s`,
                        mimeType:  blob.type,
                    });
                    dispatch('audiorecorded', { blob, duration: finalDuration, mimeType: finalMimeType });
                } else {
                    logger.info(isCancelled ? 'Recording cancelled.' : 'Recording stopped with no data.');
                    dispatch('cancel');
                }

                isRecording = false;
                recordedChunks = [];
                recordingTime = 0;
                stopRecordingTimer();
                dispatch('close');
            };

            mediaRecorder.onerror = (event) => {
                logger.error('MediaRecorder error:', event);
                stopInternal(true);
            };

            mediaRecorder.start();
            isRecording = true;
            logger.info('MediaRecorder started.');
            startRecordingTimer();

        } catch (err) {
            logger.error('Failed to initialize recording:', err);
            isRecording = false;
            stopRecordingTimer();
            if (internalStream) {
                internalStream.getTracks().forEach(track => track.stop());
                internalStream = null;
            }
            dispatch('close');
        }
    }

    /**
     * Core stop/cancel — all paths converge here.
     * Guards against double-invocation via stopAlreadyCalled.
     */
    function stopInternal(cancelled = false) {
        if (stopAlreadyCalled) {
            logger.debug('stopInternal: already called, ignoring duplicate.');
            return;
        }
        stopAlreadyCalled = true;

        isCancelled = isCancelled || cancelled;
        logger.info(`Stopping recording. Cancelled: ${isCancelled}`);

        stopRecordingTimer();
        isRecording = false;

        if (mediaRecorder && (mediaRecorder.state === 'recording' || mediaRecorder.state === 'paused')) {
            try {
                mediaRecorder.stop(); // fires onstop → dispatches events
            } catch (e) {
                logger.error('Error calling mediaRecorder.stop():', e);
                if (internalStream) {
                    internalStream.getTracks().forEach(track => track.stop());
                    internalStream = null;
                }
                dispatch('close');
            }
        } else {
            // Recorder was never started or already stopped (e.g. error path)
            if (internalStream) {
                internalStream.getTracks().forEach(track => track.stop());
                internalStream = null;
            }
            dispatch('close');
        }
    }

    // --- Timer ---
    function startRecordingTimer() {
        stopRecordingTimer();
        recordingTime = 0;
        recordingInterval = setInterval(() => { recordingTime++; }, 1000);
    }

    function stopRecordingTimer() {
        if (recordingInterval) {
            clearInterval(recordingInterval);
            recordingInterval = null;
        }
    }

    function formatTime(seconds: number): string {
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }

    // --- Document-level pointer release → complete recording ---

    /**
     * mouseup anywhere on the document completes the recording.
     * This fires even though the overlay covers the original mic button.
     */
    function handleDocumentMouseUp(_event: MouseEvent) {
        logger.debug('Document mouseup — completing recording.');
        stopInternal(false); // not cancelled
    }

    /**
     * touchend anywhere on the document completes the recording on mobile.
     */
    function handleDocumentTouchEnd(_event: TouchEvent) {
        logger.debug('Document touchend — completing recording.');
        stopInternal(false);
    }

    // --- Escape key → cancel recording ---
    function handleKeyDown(event: KeyboardEvent) {
        if (event.key === 'Escape') {
            logger.debug('Escape pressed — cancelling recording.');
            event.preventDefault();
            stopInternal(true); // cancelled
        }
    }

    // --- Drag / Cancel Logic ---
    function handleMouseMove(event: MouseEvent) {
        if (!isRecording) return;
        currentPosition = { x: event.clientX, y: event.clientY };
        updateDragState();
    }

    function handleTouchMove(event: TouchEvent) {
        if (!isRecording) return;
        event.preventDefault();
        if (event.touches.length > 0) {
            currentPosition = { x: event.touches[0].clientX, y: event.touches[0].clientY };
            updateDragState();
        }
    }

    function updateDragState() {
        const deltaX = currentPosition.x - startPosition.x;
        const deltaY = currentPosition.y - startPosition.y;
        const distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);

        // Only show leftward drag visually
        dragOffsetX = Math.min(0, deltaX);

        // Cancel when dragged left >100px total distance AND mostly horizontal
        if (distance > 100 && deltaX < -60) {
            logger.debug('Recording cancelled by drag.');
            stopInternal(true);
        }
    }

    // --- Exported Methods (called by parent as fallback via bind:this) ---

    /** Complete the recording (produces audiorecorded event). */
    export function stop() {
        logger.debug('stop() called by parent.');
        stopInternal(false);
    }

    /** Cancel the recording (no audiorecorded event). */
    export function cancel() {
        logger.debug('cancel() called by parent.');
        stopInternal(true);
    }
</script>

<!--
  Full overlay covering .message-field.
  pointer-events: none on the overlay itself so clicks/taps fall through to
  document-level listeners — no need to intercept on the div.
-->
<div class="record-overlay" transition:fade={{ duration: 150 }}>
    <!-- Top: "Release to finish" heading -->
    <div class="record-header">
        <span class="release-text">{@html $text('enter_message.record_audio.release_to_finish')}</span>
    </div>

    <!-- Bottom controls: timer | cancel hint | mic circle -->
    <div class="record-controls">
        <!-- Red timer pill -->
        <div class="timer-pill">
            {formatTime(recordingTime)}
        </div>

        <!-- "← Slide left to cancel" hint, fades as user drags left -->
        <div class="cancel-hint" style="opacity: {Math.max(0.3, 1 + dragOffsetX / 80)}">
            <span class="cancel-arrow">‹</span>
            <span class="cancel-text">{@html $text('enter_message.record_audio.slide_left_to_cancel')}</span>
        </div>

        <!-- Green mic circle follows horizontal drag -->
        <div
            class="mic-button"
            class:recording={isRecording}
            style="transform: translateX({Math.max(-120, dragOffsetX)}px)"
        >
            <div class="mic-icon icon_recordaudio"></div>
        </div>
    </div>
</div>

<style>
    /* Full overlay that covers the entire .message-field */
    .record-overlay {
        position: absolute;
        inset: 0;
        border-radius: 24px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        z-index: 200;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: space-between;
        padding: 20px 20px 18px;
        box-sizing: border-box;
        color: white;
        overflow: hidden;
    }

    /* "Release to finish" heading */
    .record-header {
        width: 100%;
        text-align: center;
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .release-text {
        font-size: 16px;
        font-weight: 700;
        color: white;
        letter-spacing: 0.01em;
    }

    /* Bottom controls row */
    .record-controls {
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
    }

    /* Red timer pill */
    .timer-pill {
        background-color: #ff4444;
        color: white;
        padding: 6px 14px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 14px;
        min-width: 60px;
        text-align: center;
        flex-shrink: 0;
        letter-spacing: 0.02em;
    }

    /* "Slide left to cancel" hint */
    .cancel-hint {
        display: flex;
        align-items: center;
        gap: 4px;
        color: rgba(255, 255, 255, 0.7);
        font-size: 13px;
        font-weight: 400;
        flex: 1;
        justify-content: center;
        transition: opacity 0.1s ease-out;
        user-select: none;
    }

    .cancel-arrow {
        font-size: 18px;
        line-height: 1;
        color: rgba(255, 255, 255, 0.5);
    }

    /* Green mic button circle */
    .mic-button {
        width: 44px;
        height: 44px;
        background-color: #4caf50;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: transform 0.05s ease-out, background-color 0.15s ease;
        cursor: grabbing;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
        will-change: transform;
    }

    .mic-button.recording {
        background-color: #43a047;
        animation: mic-pulse 1.8s ease-in-out infinite;
    }

    @keyframes mic-pulse {
        0%, 100% { box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25); }
        50%       { box-shadow: 0 2px 16px rgba(76, 175, 80, 0.6), 0 0 0 6px rgba(76, 175, 80, 0.2); }
    }

    /* Mic icon (mask-based CSS icon, white) */
    .mic-icon {
        width: 22px;
        height: 22px;
        background-color: white;
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
    }
</style>
