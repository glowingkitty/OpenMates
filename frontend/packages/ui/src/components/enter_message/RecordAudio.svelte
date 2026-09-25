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
    import { createEventDispatcher, onMount, onDestroy, tick } from 'svelte';
    import { fade } from 'svelte/transition';
    import { text } from '@repo/ui';
    import { buildWaveformFromLevels, type AudioWaveformData } from '../../utils/audioWaveform';
    import {
        startAudioRealtimeTranscription,
        type AudioRealtimeTranscriptionHandle,
    } from '../../services/audioRealtimeTranscription';

    const dispatch = createEventDispatcher<{
        audiorecorded: {
            blob: Blob;
            duration: number;
            mimeType: string;
            waveform?: AudioWaveformData;
            realtime?: AudioRealtimeTranscriptionHandle;
            liveTranscript?: string;
        };
        close: void;
        cancel: void;
        recordingStateChange: { active: boolean };
        prepareassistantplayback: void;
    }>();

    // --- Props ---
    interface Props {
        initialPosition: { x: number; y: number };
        externalStream?: MediaStream | null;
        enableRealtime?: boolean;
        previewTranscript?: string | null;
    }
    let {
        initialPosition,
        externalStream = null,
        enableRealtime = false,
        previewTranscript = null,
    }: Props = $props();

    // --- Internal State ---
    let isRecording = $state(false);
    let internalStream: MediaStream | null = null;
    let mediaRecorder: MediaRecorder | null = null;
    let recordedChunks: Blob[] = [];
    let recordingTime = $state(0);
    let recordingInterval: ReturnType<typeof setInterval> | null = null;
    let isCancelled = false;
    // A stop request and final cleanup are deliberately separate. Some browsers
    // can accept MediaRecorder.stop() without ever delivering `stop`; cancel must
    // still be able to escalate a pending finish and release the microphone.
    let stopIntent = $state<'finish' | 'cancel' | null>(null);
    let finalized = $state(false);
    let finalizationCompleted = false;
    let stopFallbackTimer: ReturnType<typeof setTimeout> | null = null;
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
    // A recorder started without a timeslice may not emit its only data chunk
    // until the asynchronous stop flush. Keep the watchdog conservative so a
    // slow Safari flush is not mistaken for a missing stop event.
    const MEDIA_RECORDER_STOP_TIMEOUT_MS = 10_000;

    let waveformSamples = $state<number[]>(createEmptyWaveform());
    let recordedWaveformLevels: number[] = [];
    let waveformContext: AudioContext | null = null;
    let waveformSource: MediaStreamAudioSourceNode | null = null;
    let waveformAnalyser: AnalyserNode | null = null;
    let waveformAnimationFrame: number | null = null;
    let lastWaveformSampleAt = 0;
    let recordOverlayElement: HTMLDivElement | null = null;
    let liveTranscript = $state('');
    let liveTranscriptViewportElement = $state<HTMLSpanElement | null>(null);
    let liveTranscriptFlowElement = $state<HTMLSpanElement | null>(null);
    let liveTranscriptLineHeight = $state(0);
    let liveTranscriptLineCount = $state(1);
    let transcriptMeasurementFrame: number | null = null;
    let transcriptResizeObserver: ResizeObserver | null = null;
    let liveTranscriptOffset = $derived(
        Math.max(0, liveTranscriptLineCount - 1) * liveTranscriptLineHeight,
    );
    let realtimeStatus = $state<'connecting' | 'listening' | 'correcting' | 'failed'>('connecting');
    let realtimeHandle: AudioRealtimeTranscriptionHandle | null = null;
    let realtimeHandedOff = false;
    let realtimeFinishRequested = false;
    let realtimeCancelled = false;
    let realtimeFinishFailed = false;

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

        requestAnimationFrame(() => {
            recordOverlayElement?.focus({ preventScroll: true });
        });

        if (previewTranscript !== null) {
            setLiveTranscript(previewTranscript);
            isRecording = true;
        } else {
            initializeAndStartRecording();
        }
        dispatch('recordingStateChange', { active: true });
    });

    onDestroy(() => {
        logger.debug('Component destroying.');
        stopWaveform();
        stopTranscriptMeasurement();
        if (!finalizationCompleted) {
            stopInternal(true);
        }
        document.removeEventListener('keydown',   handleKeyDown);
        dispatch('recordingStateChange', { active: false });
    });

    // --- Recording Logic ---
    async function initializeAndStartRecording() {
        isCancelled = false;
        stopIntent = null;
        finalized = false;
        finalizationCompleted = false;
        clearStopFallback();
        recordedChunks = [];
        recordedWaveformLevels = [];
        realtimeFinishRequested = false;
        realtimeCancelled = false;
        realtimeFinishFailed = false;

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
                if (finalizationCompleted) {
                    releaseInternalStream();
                    return;
                }
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

            if (enableRealtime) {
                realtimeHandle = startAudioRealtimeTranscription(streamToUse, {
                    onTranscript: setLiveTranscript,
                    onStatus: (value) => { realtimeStatus = value; },
                });
            }

            mediaRecorder.ondataavailable = (e) => {
                if (!finalizationCompleted && e.data && e.data.size > 0) recordedChunks.push(e.data);
            };

            mediaRecorder.onstop = () => {
                logger.debug('MediaRecorder stopped.');
                finalizeRecording(stopIntent ?? (isCancelled ? 'cancel' : 'finish'));
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
            releaseInternalStream();
            if (!finalizationCompleted) {
                finalizationCompleted = true;
                finalized = true;
                finishRealtime(true);
                dispatch('close');
            }
        }
    }

    // --- Live transcript line ticker ---

    function setLiveTranscript(value: string) {
        liveTranscript = value;
        scheduleTranscriptMeasurement();
    }

    function scheduleTranscriptMeasurement() {
        if (transcriptMeasurementFrame !== null) return;
        transcriptMeasurementFrame = requestAnimationFrame(() => {
            transcriptMeasurementFrame = null;
            void measureTranscriptLines();
        });
    }

    async function measureTranscriptLines() {
        await tick();
        const viewport = liveTranscriptViewportElement;
        const flow = liveTranscriptFlowElement;
        if (!viewport || !flow || !liveTranscript) return;

        if (!transcriptResizeObserver && typeof ResizeObserver !== 'undefined') {
            transcriptResizeObserver = new ResizeObserver(scheduleTranscriptMeasurement);
            transcriptResizeObserver.observe(viewport);
        }

        const lineHeight = Number.parseFloat(getComputedStyle(flow).lineHeight);
        if (!Number.isFinite(lineHeight) || lineHeight <= 0) return;
        liveTranscriptLineHeight = lineHeight;
        liveTranscriptLineCount = Math.max(1, Math.round(flow.scrollHeight / lineHeight));
    }

    function stopTranscriptMeasurement() {
        if (transcriptMeasurementFrame !== null) {
            cancelAnimationFrame(transcriptMeasurementFrame);
            transcriptMeasurementFrame = null;
        }
        transcriptResizeObserver?.disconnect();
        transcriptResizeObserver = null;
    }

    function clearStopFallback() {
        if (stopFallbackTimer !== null) {
            clearTimeout(stopFallbackTimer);
            stopFallbackTimer = null;
        }
    }

    function releaseInternalStream() {
        if (!internalStream) return;
        const stream = internalStream;
        internalStream = null;
        for (const track of stream.getTracks()) {
            try {
                track.stop();
            } catch (error) {
                logger.error('Failed to stop microphone track:', error);
            }
        }
    }

    function finishRealtime(cancelled: boolean) {
        if (!realtimeHandle || realtimeHandedOff) return;
        if (cancelled) {
            if (realtimeCancelled) return;
            realtimeCancelled = true;
        } else {
            if (realtimeFinishRequested) return;
            realtimeFinishRequested = true;
        }
        try {
            if (cancelled) realtimeHandle.cancel();
            else realtimeHandle.finish();
        } catch (error) {
            // Realtime transcription is an optimization. A broken socket/audio
            // graph must never prevent the MediaRecorder and microphone cleanup.
            logger.error(`Failed to ${cancelled ? 'cancel' : 'finish'} realtime transcription:`, error);
            if (!cancelled) {
                realtimeFinishFailed = true;
                finishRealtime(true);
            }
        }
    }

    function finalizeRecording(intent: 'finish' | 'cancel') {
        if (finalizationCompleted) {
            logger.debug('finalizeRecording: already finalized, ignoring late event.');
            return;
        }
        finalizationCompleted = true;
        finalized = true;
        clearStopFallback();
        stopRecordingTimer();
        stopWaveform();
        releaseInternalStream();
        isRecording = false;
        readyForRelease = false;

        if (intent === 'finish' && recordedChunks.length > 0) {
            const finalMimeType = mediaRecorder?.mimeType || recordedChunks[0]?.type || 'audio/webm';
            const blob = new Blob(recordedChunks, { type: finalMimeType });
            const finalDuration = recordingTime;
            const waveform = buildWaveformFromLevels(recordedWaveformLevels, finalDuration);
            logger.info('Recording finished:', {
                blobSize: `${(blob.size / 1024).toFixed(2)} KB`,
                duration:  `${finalDuration}s`,
                mimeType:  blob.type,
                waveformSamples: waveform?.samples.length ?? 0,
            });
            realtimeHandedOff = !!realtimeHandle && !realtimeFinishFailed;
            dispatch('audiorecorded', {
                blob,
                duration: finalDuration,
                mimeType: finalMimeType,
                waveform,
                realtime: realtimeHandedOff ? realtimeHandle ?? undefined : undefined,
                liveTranscript: liveTranscript || undefined,
            });
        } else {
            logger.info(intent === 'cancel' ? 'Recording cancelled.' : 'Recording stopped with no data.');
            finishRealtime(true);
            dispatch('cancel');
        }

        recordedChunks = [];
        recordedWaveformLevels = [];
        recordingTime = 0;
        mediaRecorder = null;
        dispatch('close');
    }

    /** Core stop/cancel — all paths converge here. */
    function stopInternal(cancelled = false) {
        if (finalizationCompleted) {
            logger.debug('stopInternal: already finalized, ignoring duplicate.');
            return;
        }

        if (stopIntent === 'cancel' || (stopIntent === 'finish' && !cancelled)) {
            logger.debug('stopInternal: request already pending, ignoring duplicate.');
            return;
        }

        isCancelled = isCancelled || cancelled;
        stopIntent = isCancelled ? 'cancel' : 'finish';
        logger.info(`Stopping recording. Cancelled: ${isCancelled}`);

        stopRecordingTimer();
        stopWaveform();
        isRecording = false;

        finishRealtime(isCancelled);

        // Cancellation is terminal and must release an owned microphone even if
        // MediaRecorder never acknowledges stop. External streams remain owned
        // by their provider and are intentionally not stopped here.
        if (isCancelled) releaseInternalStream();

        if (mediaRecorder && (mediaRecorder.state === 'recording' || mediaRecorder.state === 'paused')) {
            try {
                mediaRecorder.stop(); // fires onstop → dispatches events
            } catch (e) {
                logger.error('Error calling mediaRecorder.stop():', e);
            }
        }

        if (isCancelled) {
            finalizeRecording('cancel');
            return;
        }

        if (finalizationCompleted) return;
        stopFallbackTimer = setTimeout(() => {
            logger.error('MediaRecorder stop event timed out; finalizing available audio.');
            finalizeRecording('finish');
        }, MEDIA_RECORDER_STOP_TIMEOUT_MS);
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
            dispatch('prepareassistantplayback');
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
        dispatch('prepareassistantplayback');
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
    data-recording-finalized={finalized}
    data-recording-stop-intent={stopIntent ?? ''}
    tabindex="-1"
    transition:fade={{ duration: 150 }}
>
    <div class="record-content">
        <!-- Top: explicit completion/cancellation shortcuts. -->
        <div class="record-header">
            <span class="release-text" data-testid="release-text">
                {#if liveTranscript}
                    <span
                        bind:this={liveTranscriptViewportElement}
                        class="live-transcript-viewport"
                        class:has-previous-line={liveTranscriptLineCount > 1}
                        data-testid="recording-live-transcript"
                        data-line-count={liveTranscriptLineCount}
                        aria-live="polite"
                    >
                        <span
                            bind:this={liveTranscriptFlowElement}
                            class="live-transcript-flow"
                            data-testid="recording-live-transcript-flow"
                            style:transform={`translateY(-${liveTranscriptOffset}px)`}
                        >{liveTranscript.trim()}</span>
                    </span>
                {:else}
                    {$text('enter_message.record_audio.recording')}
                {/if}
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
        {#if !liveTranscript && enableRealtime && realtimeStatus === 'connecting'}
            <span class="live-transcript-placeholder" aria-hidden="true">•••</span>
        {/if}
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
        min-height: 220px;
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
        width: min(100%, 560px);
        font-size: var(--font-size-p);
        font-weight: 700;
        color: white;
        letter-spacing: 0.01em;
        line-height: 1.3;
        display: block;
    }

    .live-transcript-viewport {
        display: block;
        width: 100%;
        height: 1.3em;
        overflow: hidden;
    }

    .live-transcript-viewport.has-previous-line {
        -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 4px, #000 100%);
        mask-image: linear-gradient(to bottom, transparent 0, #000 4px, #000 100%);
    }

    .live-transcript-flow {
        display: block;
        width: 100%;
        line-height: 1.3;
        overflow-wrap: anywhere;
        transition: transform 220ms cubic-bezier(0.22, 1, 0.36, 1);
        will-change: transform;
    }

    @media (prefers-reduced-motion: reduce) {
        .live-transcript-flow {
            transition-duration: 0ms;
        }
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

    .live-transcript-placeholder {
        color: rgba(255, 255, 255, 0.72);
        letter-spacing: 0.18em;
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
