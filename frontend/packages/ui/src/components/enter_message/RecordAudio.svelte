<!-- frontend/packages/ui/src/components/enter_message/RecordAudio.svelte -->
<!--
  Audio recording UI — renders as a full overlay inside .message-field.
  Replaces the normal message field appearance while recording is in progress.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Chat/Views/VoiceRecordingView.swift

  ┌──────────────────────────────────────────────────────┐
  │              Recording...                           │
  │                                                      │
  │  [00:01]                  [Cancel] [Finish]          │  ← controls row
  └──────────────────────────────────────────────────────┘

  Finish / cancel behaviour:
  ─────────────────────────
  The overlay covers the entire message field (inset:0, z-index:200). Recording
  starts on the initial mic press and then stays active until an explicit finish
  or cancel action:

    • Finish button / Enter → stop()  (complete recording → audiorecorded event)
    • Cancel button / Escape → cancel()  (discard recording)
    • keydown Escape → cancel()  (discard recording)

  Exported methods (called by parent as fallback):
    stop()   — complete the recording
    cancel() — discard the recording
-->
<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';
    import { buildWaveformFromLevels, type AudioWaveformData } from '../../utils/audioWaveform';

    const dispatch = createEventDispatcher<{
        audiorecorded: { blob: Blob; duration: number; mimeType: string; waveform?: AudioWaveformData };
        close: void;
        cancel: void;
        recordingStateChange: { active: boolean };
    }>();

    // --- Props ---
    interface Props {
    initialPosition: { x: number; y: number };
        externalStream?: MediaStream | null;
        startedFromKeyboard?: boolean;
    }
    let {
        initialPosition,
        externalStream = null,
        startedFromKeyboard = false
    }: Props = $props();

    // --- Internal State ---
    let isRecording = $state(false);
    let internalStream: MediaStream | null = null;
    let mediaRecorder: MediaRecorder | null = null;
    let recordedChunks: Blob[] = [];
    let recordingTime = $state(0);
    let recordingInterval: ReturnType<typeof setInterval> | null = null;
    let isCancelled = false;
    // Whether stop() has already been called (prevents double-stop from both
    // document mouseup and parent's onRecordMouseUp after tick()).
    let stopAlreadyCalled = false;
    // Guard: ignore pointer-release events until the MediaRecorder has actually
    // started. Without this, a queued/bubbled mouseup from the original press
    // interaction fires before getUserMedia resolves, causing stopInternal to see
    // mediaRecorder=null and immediately dispatch 'close'.
    let readyForRelease = false;
    // If a release event arrives while readyForRelease is false, we record that
    // fact here so we can stop immediately once the recorder becomes ready.
    // null = no pending release; false = complete; true = cancel.
    let pendingReleaseCancel: boolean | null = null;

    const WAVEFORM_SAMPLE_COUNT = 64;
    const WAVEFORM_FFT_SIZE = 256;
    const WAVEFORM_SAMPLE_INTERVAL_MS = 50;
    const WAVEFORM_NOISE_FLOOR = 0.005;
    const WAVEFORM_MIN_DECIBELS = -46;
    const WAVEFORM_MAX_DECIBELS = -18;
    const WAVEFORM_MIN_VISIBLE_LEVEL = 0.04;

    let waveformSamples = $state<number[]>(createEmptyWaveform());
    let recordedWaveformLevels: number[] = [];
    let waveformContext: AudioContext | null = null;
    let waveformSource: MediaStreamAudioSourceNode | null = null;
    let waveformAnalyser: AnalyserNode | null = null;
    let waveformAnimationFrame: number | null = null;
    let lastWaveformSampleAt = 0;
    let recordOverlayElement: HTMLDivElement | null = null;

    const logger = {
        debug: (...args: unknown[]) => console.debug('[RecordAudio]', ...args),
        info:  (...args: unknown[]) => console.info('[RecordAudio]',  ...args),
        error: (...args: unknown[]) => console.error('[RecordAudio]', ...args),
    };

    // --- Lifecycle ---
    onMount(() => {
        logger.debug('Component mounted, starting recording.');
        void initialPosition;

        // Attach document-level key handling so Enter/Escape work while the
        // overlay owns focus and pointer events.
        document.addEventListener('keydown',   handleKeyDown);

        if (startedFromKeyboard) {
            requestAnimationFrame(() => {
                recordOverlayElement?.focus({ preventScroll: true });
            });
        }

        initializeAndStartRecording();
        dispatch('recordingStateChange', { active: true });
    });

    onDestroy(() => {
        logger.debug('Component destroying.');
        stopWaveform();
        // Guard: don't double-stop if stop/cancel already ran
        if (!stopAlreadyCalled) {
            stopInternal(true);
        }
        document.removeEventListener('keydown',   handleKeyDown);
        dispatch('recordingStateChange', { active: false });
    });

    // --- Recording Logic ---
    async function initializeAndStartRecording() {
        isCancelled = false;
        stopAlreadyCalled = false;
        recordedChunks = [];
        recordedWaveformLevels = [];

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
                stopWaveform();

                // Release the mic track
                if (internalStream) {
                    internalStream.getTracks().forEach(track => track.stop());
                    internalStream = null;
                }

                if (!isCancelled && recordedChunks.length > 0) {
                    const finalMimeType = mediaRecorder?.mimeType || mimeType;
                    const blob = new Blob(recordedChunks, { type: finalMimeType });
                    const finalDuration = recordingTime;
                    const waveform = buildWaveformFromLevels(recordedWaveformLevels, finalDuration);
                    logger.info('Recording finished:', {
                        blobSize: `${(blob.size / 1024).toFixed(2)} KB`,
                        duration:  `${finalDuration}s`,
                        mimeType:  blob.type,
                        waveformSamples: waveform?.samples.length ?? 0,
                    });
                    dispatch('audiorecorded', { blob, duration: finalDuration, mimeType: finalMimeType, waveform });
                } else {
                    logger.info(isCancelled ? 'Recording cancelled.' : 'Recording stopped with no data.');
                    dispatch('cancel');
                }

                isRecording = false;
                recordedChunks = [];
                recordedWaveformLevels = [];
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
            readyForRelease = true;
            logger.info('MediaRecorder started.');
            startRecordingTimer();
            startWaveform(streamToUse);

            // If a pointer-release or Escape arrived while we were waiting for
            // getUserMedia + MediaRecorder init, honour it now.
            if (pendingReleaseCancel !== null) {
                const shouldCancel = pendingReleaseCancel;
                pendingReleaseCancel = null;
                logger.info(`Executing deferred ${shouldCancel ? 'cancel' : 'stop'}.`);
                stopInternal(shouldCancel);
                return;
            }

        } catch (err) {
            logger.error('Failed to initialize recording:', err);
            isRecording = false;
            stopRecordingTimer();
            stopWaveform();
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
        stopWaveform();
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

    // --- Live waveform ---

    function createEmptyWaveform(): number[] {
        return Array.from({ length: WAVEFORM_SAMPLE_COUNT }, () => 0);
    }

    function startWaveform(stream: MediaStream) {
        stopWaveform();

        try {
            const audioWindow = window as unknown as {
                AudioContext?: typeof AudioContext;
                webkitAudioContext?: typeof AudioContext;
            };
            const AudioContextConstructor = audioWindow.AudioContext ?? audioWindow.webkitAudioContext;
            if (!AudioContextConstructor) {
                throw new Error('Web Audio API is unavailable.');
            }

            waveformContext = new AudioContextConstructor();
            waveformSource = waveformContext.createMediaStreamSource(stream);
            waveformAnalyser = waveformContext.createAnalyser();
            waveformAnalyser.fftSize = WAVEFORM_FFT_SIZE;
            waveformSource.connect(waveformAnalyser);

            if (waveformContext.state === 'suspended') {
                void waveformContext.resume().catch((error) => {
                    logger.error('Failed to resume waveform AudioContext:', error);
                });
            }

            const timeDomainData = new Uint8Array(waveformAnalyser.frequencyBinCount);
            lastWaveformSampleAt = 0;

            const sampleWaveform = (timestamp: number) => {
                if (!waveformAnalyser || !waveformContext || !isRecording) return;

                if (timestamp - lastWaveformSampleAt >= WAVEFORM_SAMPLE_INTERVAL_MS) {
                    waveformAnalyser.getByteTimeDomainData(timeDomainData);
                    const level = normalizeWaveformLevel(timeDomainData);
                    recordedWaveformLevels.push(level);
                    waveformSamples = [...waveformSamples.slice(1), level];
                    lastWaveformSampleAt = timestamp;
                }

                waveformAnimationFrame = requestAnimationFrame(sampleWaveform);
            };

            waveformAnimationFrame = requestAnimationFrame(sampleWaveform);
        } catch (error) {
            logger.error('Failed to initialize live waveform:', error);
            stopWaveform();
        }
    }

    function normalizeWaveformLevel(timeDomainData: Uint8Array): number {
        let sumOfSquares = 0;
        for (const sample of timeDomainData) {
            const centeredSample = (sample - 128) / 128;
            sumOfSquares += centeredSample * centeredSample;
        }

        const rms = Math.sqrt(sumOfSquares / timeDomainData.length);
        if (rms <= WAVEFORM_NOISE_FLOOR) return 0;

        const decibels = 20 * Math.log10(rms);
        return Math.min(
            1,
            Math.max(0, (decibels - WAVEFORM_MIN_DECIBELS) / (WAVEFORM_MAX_DECIBELS - WAVEFORM_MIN_DECIBELS))
        );
    }

    function stopWaveform() {
        if (waveformAnimationFrame !== null) {
            cancelAnimationFrame(waveformAnimationFrame);
            waveformAnimationFrame = null;
        }

        waveformSource?.disconnect();
        waveformAnalyser?.disconnect();

        const contextToClose = waveformContext;
        waveformSource = null;
        waveformAnalyser = null;
        waveformContext = null;
        lastWaveformSampleAt = 0;
        waveformSamples = createEmptyWaveform();

        if (contextToClose && contextToClose.state !== 'closed') {
            void contextToClose.close().catch((error) => {
                logger.error('Failed to close waveform AudioContext:', error);
            });
        }
    }

    // --- Keyboard shortcuts ---
    function handleKeyDown(event: KeyboardEvent) {
        if (event.key === 'Enter') {
            event.preventDefault();
            if (!readyForRelease) {
                logger.debug('Enter pressed — deferred finish (not ready yet).');
                pendingReleaseCancel = false;
                return;
            }
            logger.debug('Enter pressed — finishing recording.');
            stopInternal(false);
        }
        if (event.key === 'Escape') {
            event.preventDefault();
            if (!readyForRelease) {
                logger.debug('Escape pressed — deferred cancel (not ready yet).');
                pendingReleaseCancel = true;
                return;
            }
            logger.debug('Escape pressed — cancelling recording.');
            stopInternal(true); // cancelled
        }
    }

    // --- Exported Methods (called by parent as fallback via bind:this) ---

    /** Complete the recording (produces audiorecorded event). */
    export function stop() {
        if (!readyForRelease) {
            logger.debug('stop() called by parent — deferred (not ready for release yet).');
            pendingReleaseCancel = false;
            return;
        }
        logger.debug('stop() called by parent.');
        stopInternal(false);
    }

    /** Cancel the recording (no audiorecorded event). */
    export function cancel() {
        if (!readyForRelease) {
            logger.debug('cancel() called by parent — deferred (not ready for release yet).');
            pendingReleaseCancel = true;
            return;
        }
        logger.debug('cancel() called by parent.');
        stopInternal(true);
    }
</script>

<!--
  Full overlay covering .message-field.
  pointer-events: none on the overlay itself so clicks/taps fall through to
  document-level listeners — no need to intercept on the div.
-->
<div
    bind:this={recordOverlayElement}
    class="record-overlay"
    data-testid="record-overlay"
    tabindex="-1"
    transition:fade={{ duration: 150 }}
>
    <div class="record-content">
        <!-- Top: explicit completion/cancellation shortcuts. -->
        <div class="record-header">
            <span class="release-text" data-testid="release-text">
                {$text('enter_message.record_audio.recording')}
            </span>
            <span class="record-shortcuts" data-testid="record-shortcuts">
                {$text('enter_message.record_audio.enter_to_finish_escape_to_cancel')}
            </span>
        </div>

        <!-- Recent microphone levels enter on the right and roll left. -->
        <div class="recording-waveform" data-testid="recording-waveform" aria-hidden="true">
            {#each waveformSamples as level, index (index)}
                <span
                    class="recording-waveform-bar"
                    data-testid="recording-waveform-bar"
                    data-level={level.toFixed(3)}
                    style:height={`${Math.max(WAVEFORM_MIN_VISIBLE_LEVEL, level) * 100}%`}
                ></span>
            {/each}
        </div>
    </div>

    <!-- Bottom controls: timer | explicit actions -->
    <div class="record-controls" data-testid="record-controls">
        <div class="timer-pill" data-testid="timer-pill">
            {formatTime(recordingTime)}
        </div>

        <div class="record-action-buttons" data-testid="record-action-buttons">
            <button type="button" class="record-action-button cancel" data-testid="record-cancel-button" onclick={cancel}>
                {$text('enter_message.record_audio.cancel')}
            </button>
            <button type="button" class="record-action-button finish" data-testid="record-finish-button" onclick={stop}>
                {$text('enter_message.record_audio.finish')}
            </button>
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
        z-index: var(--z-index-sticky);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: space-between;
        padding: 20px 20px 18px;
        box-sizing: border-box;
        color: white;
        overflow: hidden;
    }

    .record-overlay:focus,
    .record-overlay:focus-visible {
        outline: none;
    }

    :global(html[data-recording-shortcut-active='true'] [data-testid='active-chat-container']:focus-visible),
    :global(html[data-recording-shortcut-active='true'] [data-testid='active-chat-container'] :focus-visible) {
        outline: none !important;
    }

    .record-content {
        width: 100%;
        min-height: 0;
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-4);
    }

    /* Recording heading and keyboard shortcut hint */
    .record-header {
        width: 100%;
        text-align: center;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-1);
    }

    .release-text {
        font-size: var(--font-size-p);
        font-weight: 700;
        color: white;
        letter-spacing: 0.01em;
    }

    .record-shortcuts {
        color: rgba(255, 255, 255, 0.72);
        font-size: var(--font-size-xs);
        font-weight: 500;
    }

    .recording-waveform {
        width: min(100%, 480px);
        height: 64px;
        min-height: 64px;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: clamp(1px, 0.4vw, 4px);
        padding-inline: var(--spacing-2);
        box-sizing: border-box;
        color: white;
        overflow: hidden;
    }

    .recording-waveform-bar {
        width: clamp(1px, 0.25vw, 3px);
        min-height: 2px;
        max-height: 100%;
        flex: 0 1 3px;
        background-color: currentColor;
        border-radius: var(--radius-full);
    }

    /* Bottom controls row */
    .record-controls {
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--spacing-4);
    }

    .timer-pill {
        background-color: #ff4444;
        color: white;
        padding: 6px 14px;
        border-radius: var(--radius-8);
        font-weight: 700;
        font-size: var(--font-size-small);
        min-width: 60px;
        text-align: center;
        flex-shrink: 0;
        letter-spacing: 0.02em;
    }

    .record-action-buttons {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: var(--spacing-3);
        flex: 1;
    }

    .record-action-button {
        border: 0;
        border-radius: var(--radius-8);
        padding: var(--spacing-4) var(--spacing-8);
        color: white;
        font: inherit;
        font-size: var(--font-size-small);
        font-weight: 700;
        cursor: pointer;
    }

    .record-action-button.cancel {
        background: rgba(255, 255, 255, 0.18);
    }

    .record-action-button.finish {
        background: var(--color-button-primary);
        color: white;
    }

    .record-action-button.finish:hover {
        background: var(--color-button-primary-hover);
    }

    .record-action-button.finish:active {
        background: var(--color-button-primary-pressed);
    }

    @media (max-width: 520px) {
        .record-controls {
            align-items: stretch;
        }

        .record-action-buttons {
            gap: var(--spacing-2);
        }

        .record-action-button {
            padding-inline: var(--spacing-6);
        }
    }
</style>
