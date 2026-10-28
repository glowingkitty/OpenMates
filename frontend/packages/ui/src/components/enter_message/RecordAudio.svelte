<!-- frontend/packages/ui/src/components/enter_message/RecordAudio.svelte -->
<!--
  Audio recording UI — renders as a full overlay inside .message-field.
  Replaces the normal message field appearance while recording is in progress.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Chat/Views/VoiceRecordingView.swift

  ┌──────────────────────────────────────────────────────┐
  │ [×]          Recording / transcript        [■] [↑]  │  ← compact composer
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
    import CompactSendButton from './CompactSendButton.svelte';
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
        transcriptionerror: Error;
        overlayremoved: { recordingGeneration: number };
        recordingStateChange: { active: boolean };
        prepareassistantplayback: void;
        sendrequested: void;
    }>();

    // --- Props ---
    interface Props {
        initialPosition: { x: number; y: number };
        externalStream?: MediaStream | null;
        enableRealtime?: boolean;
        anonymous?: boolean;
        previewTranscript?: string | null;
        previewProcessing?: boolean;
        /** Text composers keep the overlay until corrected text is available. */
        retainUntilCorrection?: boolean;
        /** Direct Send keeps processing visible through composer submission. */
        retainUntilSend?: boolean;
        compact?: boolean;
        correctionContext?: 'workflow';
        recordingGeneration?: number;
        /** Only composers that handle sendrequested offer direct submission. */
        allowSend?: boolean;
    }
    let {
        initialPosition,
        externalStream = null,
        enableRealtime = false,
        anonymous = false,
        previewTranscript = null,
        previewProcessing = false,
        retainUntilCorrection = false,
        retainUntilSend = false,
        compact = false,
        correctionContext,
        recordingGeneration = 0,
        allowSend = false,
    }: Props = $props();
    let overlayGeneration = 0;

    // --- Internal State ---
    let isRecording = $state(false);
    let internalStream: MediaStream | null = null;
    let mediaRecorder: MediaRecorder | null = null;
    let recordedChunks: Blob[] = [];
    let recordingTime = $state(0);
    let recordingInterval: ReturnType<typeof setInterval> | null = null;
    let isCancelled = false;
    let sendRequested = $state(false);
    let isCompact = $derived(compact || sendRequested);
    let sendAdmissionStarted = $state(false);
    // A stop request and final cleanup are deliberately separate. Some browsers
    // can accept MediaRecorder.stop() without ever delivering `stop`; cancel must
    // still be able to escalate a pending finish and release the microphone.
    let stopIntent = $state<'finish' | 'cancel' | null>(null);
    let finalized = $state(false);
    let finalizationCompleted = false;
    let overlayRemovalNotified = false;
    // Teardown may read a pre-close reactive snapshot; notification is synchronous.
    let overlayCloseNotified = false;
    let resolveOverlayRemoval = () => {};
    const overlayRemoved = new Promise<void>((resolve) => { resolveOverlayRemoval = resolve; });
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
    let liveTranscriptLineCount = $state(1);
    let transcriptMeasurementFrame: number | null = null;
    let transcriptResizeObserver: ResizeObserver | null = null;
    let liveTranscriptOffset = $state(0);
    let realtimeStatus = $state<'connecting' | 'listening' | 'correcting' | 'failed'>('connecting');
    let realtimeHandle: AudioRealtimeTranscriptionHandle | null = null;
    let realtimeHandedOff = false;
    let realtimeFinishRequested = false;
    let realtimeCancelled = false;
    let realtimeFinishFailed = false;
    let overlayCloseRequested = $state(false);
    let processingMessageIndex = $state(0);
    const processingMessageKeys = [
        'enter_message.record_audio.improving_transcript',
        'enter_message.record_audio.removing_filler_words',
        'enter_message.record_audio.making_more_concise',
    ];
    let isProcessing = $derived(
        !overlayCloseRequested && (previewProcessing || (retainUntilCorrection && (stopIntent === 'finish' || sendRequested))),
    );

    $effect(() => {
        if (!isProcessing) return;
        processingMessageIndex = 0;
        const interval = setInterval(() => {
            processingMessageIndex = (processingMessageIndex + 1) % processingMessageKeys.length;
        }, 3000);
        return () => clearInterval(interval);
    });

    function closeOverlay() {
        if (overlayCloseNotified) return;
        overlayCloseNotified = true;
        overlayCloseRequested = true;
        dispatch('close');
    }

    function cancelPendingCorrection() {
        if (!retainUntilCorrection || !realtimeHandedOff || overlayCloseRequested) return false;
        isCancelled = true;
        stopIntent = 'cancel';
        try {
            realtimeHandle?.cancel();
        } catch (error) {
            logger.error('Failed to cancel transcript correction:', error);
        }
        dispatch('cancel');
        closeOverlay();
        return true;
    }

    const logger = {
        debug: (...args: unknown[]) => console.debug('[RecordAudio]', ...args),
        info:  (...args: unknown[]) => console.info('[RecordAudio]',  ...args),
        error: (...args: unknown[]) => console.error('[RecordAudio]', ...args),
    };

    // --- Lifecycle ---
    onMount(() => {
        overlayGeneration = recordingGeneration;
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
        notifyOverlayRemoved();
        if (retainUntilCorrection && realtimeHandedOff && !overlayCloseNotified) {
            try {
                realtimeHandle?.cancel();
            } catch (error) {
                logger.error('Failed to cancel transcript correction on destroy:', error);
            }
        }
        overlayCloseNotified = true;
        overlayCloseRequested = true;
        logger.debug('Component destroying.');
        stopWaveform();
        stopTranscriptMeasurement();
        if (!finalizationCompleted) {
            stopInternal(true);
        }
        document.removeEventListener('keydown',   handleKeyDown);
        dispatch('recordingStateChange', { active: false });
    });

    function notifyOverlayRemoved() {
        if (overlayRemovalNotified) return;
        overlayRemovalNotified = true;
        dispatch('overlayremoved', { recordingGeneration: overlayGeneration });
        resolveOverlayRemoval();
    }

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
                    anonymous,
                    onTranscript: setLiveTranscript,
                    onStatus: (value) => { realtimeStatus = value; },
                    correctionContext,
                });
                void realtimeHandle.correction.catch((error: Error) => {
                    if (isCancelled || realtimeHandedOff || overlayCloseNotified) return;
                    dispatch('transcriptionerror', error);
                    stopInternal(true);
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
                closeOverlay();
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
            transcriptResizeObserver.observe(flow);
        }

        const lineHeight = Number.parseFloat(getComputedStyle(flow).lineHeight);
        if (!Number.isFinite(lineHeight) || lineHeight <= 0) return;
        // Keep fractional line geometry: scrollHeight rounds to integer pixels.
        // Snap directly to the last line; animating this offset exposes clipped
        // parts of two lines while a long transcript advances or reflows.
        const height = flow.getBoundingClientRect().height;
        liveTranscriptLineCount = Math.max(1, Math.round(height / lineHeight));
        liveTranscriptOffset = Math.max(0, height - lineHeight);
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
        mediaRecorder = null;
        if (retainUntilCorrection && realtimeHandedOff && realtimeHandle) {
            // The parent registers its correction await during audiorecorded.
            // It inserts the text before this later continuation closes the
            // overlay, then restores focus after overlayremoved.
            void realtimeHandle.correction.then(() => {
                if (overlayCloseNotified) return;
                if (retainUntilSend && sendRequested) sendAdmissionStarted = true;
                else closeOverlay();
            }, closeOverlay);
        } else {
            closeOverlay();
        }
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
        // An open embed viewer owns its keyboard shortcuts while capture
        // continues behind it. Also respect native editor/control handling.
        if (event.defaultPrevented || document.querySelector('.unified-embed-fullscreen-overlay')) return;
        if (event.key === 'Enter') {
            // Let focused controls perform their native keyboard activation.
            if (event.target instanceof Element && event.target.closest('button')) return;
            event.preventDefault();
            stop();
        }
        if (event.key === 'Escape') {
            event.preventDefault();
            cancel();
        }
    }

    // --- Exported Methods (called by parent as fallback via bind:this) ---

    function requestSend() {
        if (!allowSend || sendRequested || stopIntent === 'cancel' || overlayCloseRequested) return;
        sendRequested = true;
        dispatch('sendrequested');
        recordOverlayElement?.focus({ preventScroll: true });
        stop();
    }

    /** Close after composer admission, waiting for actual overlay removal. */
    export async function completeSend(): Promise<void> {
        closeOverlay();
        await overlayRemoved;
    }

    /** Complete the recording (produces audiorecorded event). */
    export function stop() {
        if (stopIntent !== null || finalized || previewProcessing) return;
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
        if (sendAdmissionStarted) return;
        if (cancelPendingCorrection()) return;
        if (overlayCloseRequested) return;
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
{#snippet cancelButton()}
    <button type="button" class="record-action-button cancel" data-testid="record-cancel-button" aria-label={$text('enter_message.record_audio.cancel')} disabled={sendAdmissionStarted} onclick={cancel}>
        <span class="cancel-label">{$text('enter_message.record_audio.cancel')}</span>
        <span class="clickable-icon icon_close cancel-icon" data-testid="record-cancel-icon" aria-hidden="true"></span>
    </button>
{/snippet}

<div
    bind:this={recordOverlayElement}
    class="record-overlay"
    class:compact={isCompact}
    class:compact-processing={sendRequested}
    class:with-send={allowSend}
    class:has-transcript={!!liveTranscript.trim()}
    data-testid="record-overlay"
    data-recording-finalized={finalized}
    data-recording-processing={isProcessing}
    data-recording-stop-intent={stopIntent ?? ''}
    tabindex="-1"
    transition:fade={{ duration: 150 }}
    onoutroend={notifyOverlayRemoved}
>
    {#if isCompact}
        {@render cancelButton()}
    {/if}
    <div class="record-content">
        <!-- Top: explicit completion/cancellation shortcuts. -->
        <div class="record-header">
            <span class="release-text" data-testid="release-text">
                {#if isProcessing}
                    <span role="status" aria-live="polite" aria-atomic="true">
                        {#key processingMessageIndex}
                            <span class="processing-text" data-testid="recording-processing-text">
                                {$text(processingMessageKeys[processingMessageIndex])}
                            </span>
                        {/key}
                    </span>
                {:else if liveTranscript}
                    <span
                        bind:this={liveTranscriptViewportElement}
                        class="live-transcript-viewport"
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
            {#if !isProcessing}
                <span class="record-shortcuts" data-testid="record-shortcuts">
                    {$text('enter_message.record_audio.enter_to_finish_escape_to_cancel')}
                </span>
            {/if}
        </div>

        <!-- Recent microphone levels enter on the right and roll left. -->
        {#if !isProcessing}
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
        {/if}
        {#if !isProcessing && !liveTranscript && enableRealtime && realtimeStatus === 'connecting'}
            <span class="live-transcript-placeholder" aria-hidden="true">•••</span>
        {/if}
    </div>

    <!-- Bottom controls: timer | explicit actions -->
    <div class="record-controls" data-testid="record-controls">
        <div class="timer-pill" data-testid="timer-pill">
            {formatTime(recordingTime)}
        </div>

        <div class="record-action-buttons" data-testid="record-action-buttons">
            {#if !isCompact}
                {@render cancelButton()}
            {/if}
            <button type="button" class="record-action-button finish" data-testid="record-finish-button" aria-label={$text('enter_message.record_audio.finish')} disabled={isProcessing || finalized} onclick={stop}>
                <span class="finish-label">{$text('enter_message.record_audio.finish')}</span>
                <span class="finish-icon" data-testid="record-finish-icon" aria-hidden="true"></span>
            </button>
            {#if allowSend}
                <CompactSendButton
                    testId="record-send-button"
                    disabled={sendRequested || overlayCloseRequested}
                    busy={sendRequested && isProcessing}
                    onclick={requestSend}
                />
            {/if}
        </div>
    </div>
</div>

<style>
    /* Full overlay that covers the entire .message-field */
    .record-overlay {
        position: absolute;
        inset: 0;
        container-type: inline-size;
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

    .record-overlay.compact {
        min-height: 48px;
        display: grid;
        grid-template-columns: 40px minmax(0, 1fr) 40px;
        gap: var(--spacing-2);
        padding: 0 var(--spacing-4);
    }

    /* Balance the two right-hand actions so the preview stays centered. */
    .record-overlay.compact.with-send[data-recording-processing='false'] {
        grid-template-columns: calc(80px + var(--spacing-2)) minmax(0, 1fr) calc(80px + var(--spacing-2));
    }

    .compact .record-content {
        grid-column: 2;
        width: 100%;
        min-width: 0;
        flex-direction: row;
        justify-content: center;
        gap: var(--spacing-2);
    }

    .compact .record-header {
        min-width: 0;
        flex: 1;
        align-items: center;
        text-align: center;
    }

    .compact .release-text {
        font-size: var(--font-size-small);
    }

    .compact .record-controls {
        grid-column: 3;
        justify-self: end;
        width: auto;
        flex-wrap: nowrap;
    }

    .compact .record-shortcuts,
    .compact:not(.has-transcript)[data-recording-processing='false'] .record-header,
    .compact .live-transcript-placeholder,
    .compact .timer-pill,
    .compact.has-transcript .recording-waveform,
    .compact[data-recording-processing='true'] .finish,
    .compact-processing .timer-pill,
    .compact-processing .finish,
    .compact-processing .record-action-buttons :global([data-testid='record-send-button']) {
        display: none;
    }

    .cancel-icon, .finish-icon { display: none; }

    .compact .cancel-label, .compact .finish-label { display: none; }
    .compact .cancel-icon {
        display: block;
        width: 20px;
        height: 20px;
        background: var(--color-font-button);
    }
    .compact .cancel,
    .compact .finish {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        height: 40px;
        padding: 0;
    }
    .compact .cancel { justify-self: start; }
    .compact .record-action-button.finish {
        background: color-mix(in srgb, var(--color-font-button) 18%, transparent);
    }
    .compact .finish-icon {
        display: block;
        width: 16px;
        height: 16px;
        border-radius: var(--radius-1);
        background: var(--color-font-button);
    }
    .compact .cancel:hover,
    .compact .record-action-button.finish:hover {
        background: color-mix(in srgb, var(--color-font-button) 28%, transparent);
    }
    .compact .cancel:active,
    .compact .record-action-button.finish:active {
        background: color-mix(in srgb, var(--color-font-button) 36%, transparent);
    }
    .compact .record-action-buttons { gap: var(--spacing-2); }
    .compact .recording-waveform {
        width: 100%;
        height: 20px;
        min-height: 20px;
        flex: 1;
        padding: 0;
        gap: 1px;
        -webkit-mask-image: linear-gradient(to right, transparent, currentColor var(--spacing-4));
        mask-image: linear-gradient(to right, transparent, currentColor var(--spacing-4));
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
        height: 1lh;
        overflow: hidden;
    }

    .live-transcript-flow {
        display: block;
        width: 100%;
        line-height: 1.3;
        overflow-wrap: anywhere;
        transition: none;
    }

    .processing-text {
        display: block;
        animation: recording-processing-pulse 1.5s ease-in-out infinite;
    }

    @keyframes recording-processing-pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
    }

    .record-action-button:disabled {
        opacity: 0.5;
        cursor: default;
    }

    @media (prefers-reduced-motion: reduce) {
        .processing-text { animation: none; }
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
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: var(--spacing-4);
    }

    .timer-pill {
        align-self: center;
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
        /* The control row owns spacing and sizing, including narrow composers. */
        min-width: 0;
        margin: 0;
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
        background: color-mix(in srgb, var(--color-font-button) 18%, transparent);
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

    @container (max-width: 520px) {
        .compact[data-recording-processing='false'] .record-header { display: none; }
        .compact.has-transcript .recording-waveform { display: flex; }
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
