// @vitest-environment jsdom

import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import RecordAudio from '../RecordAudio.svelte';

const realtimeMocks = vi.hoisted(() => ({
    finish: vi.fn(),
    cancel: vi.fn(),
    correction: null as Promise<unknown> | null,
}));

vi.mock('@repo/ui', async () => {
    const { readable } = await import('svelte/store');
    return { text: readable((key: string) => key) };
});

vi.mock('svelte/transition', () => ({
    fade: () => ({ duration: 0 }),
}));

vi.mock('../../../services/audioRealtimeTranscription', () => ({
    startAudioRealtimeTranscription: vi.fn(() => ({
        transcription: new Promise(() => undefined),
        correction: realtimeMocks.correction ?? new Promise(() => undefined),
        finish: realtimeMocks.finish,
        cancel: realtimeMocks.cancel,
        setChatId: vi.fn(),
    })),
}));

class FakeMediaRecorder {
    static instances: FakeMediaRecorder[] = [];
    static isTypeSupported = vi.fn(() => true);

    state: RecordingState = 'inactive';
    mimeType = 'audio/mp4';
    ondataavailable: ((event: BlobEvent) => void) | null = null;
    onstop: (() => void) | null = null;
    onerror: ((event: Event) => void) | null = null;

    constructor() {
        FakeMediaRecorder.instances.push(this);
    }

    start() {
        this.state = 'recording';
    }

    stop() {
        this.state = 'inactive';
    }

    emitData(value: string) {
        this.ondataavailable?.({ data: new Blob([value], { type: this.mimeType }) } as BlobEvent);
    }

    emitStop() {
        this.onstop?.();
    }
}

async function flushMount() {
    for (let index = 0; index < 4; index += 1) await Promise.resolve();
    await tick();
}

function mountRecorder(options: { externalStream?: MediaStream; realtime?: boolean; retainUntilCorrection?: boolean; retainUntilSend?: boolean; allowSend?: boolean } = {}) {
    const close = vi.fn();
    const cancel = vi.fn();
    const audioRecorded = vi.fn();
    const sendRequested = vi.fn();
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(RecordAudio, {
        target,
        props: {
            initialPosition: { x: 0, y: 0 },
            externalStream: options.externalStream,
            enableRealtime: options.realtime ?? false,
            retainUntilCorrection: options.retainUntilCorrection ?? true,
            retainUntilSend: options.retainUntilSend ?? false,
            previewTranscript: null,
            allowSend: options.allowSend ?? false,
        },
        events: {
            close,
            cancel,
            audiorecorded: audioRecorded,
            sendrequested: sendRequested,
        },
    });
    return { component, target, close, cancel, audioRecorded, sendRequested };
}

describe('RecordAudio finalization', () => {
    let ownedTrackStop: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        vi.useFakeTimers();
        FakeMediaRecorder.instances = [];
        realtimeMocks.finish.mockReset();
        realtimeMocks.cancel.mockReset();
        realtimeMocks.correction = null;
        ownedTrackStop = vi.fn();
        Object.defineProperty(navigator, 'mediaDevices', {
            configurable: true,
            value: {
                getUserMedia: vi.fn(async () => ({
                    getTracks: () => [{ stop: ownedTrackStop }],
                })),
            },
        });
        vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
        vi.spyOn(console, 'error').mockImplementation(() => undefined);
    });

    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
        vi.useRealTimers();
        document.body.innerHTML = '';
    });

    // contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    it('uses a bounded finish fallback when MediaRecorder never emits stop', async () => {
        realtimeMocks.finish.mockImplementationOnce(() => {
            throw new Error('realtime finish failed');
        });
        const mounted = mountRecorder({ realtime: true });
        await flushMount();
        const recorder = FakeMediaRecorder.instances[0];
        recorder.emitData('fallback-audio');

        mounted.target.querySelector<HTMLButtonElement>('[data-testid="record-finish-button"]')!.click();
        expect(mounted.close).not.toHaveBeenCalled();

        await vi.advanceTimersByTimeAsync(10_000);
        expect(mounted.audioRecorded).toHaveBeenCalledTimes(1);
        expect(realtimeMocks.finish).toHaveBeenCalledTimes(1);
        expect(realtimeMocks.cancel).toHaveBeenCalledTimes(1);
        const event = mounted.audioRecorded.mock.calls[0][0] as CustomEvent<{ realtime?: unknown }>;
        expect(event.detail.realtime).toBeUndefined();
        expect(mounted.cancel).not.toHaveBeenCalled();
        expect(mounted.close).toHaveBeenCalledTimes(1);
        expect(ownedTrackStop).toHaveBeenCalledTimes(1);

        recorder.emitStop();
        expect(mounted.audioRecorded).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
        await unmount(mounted.component, { outro: false });
        expect(mounted.audioRecorded).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
    });

    // contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle
    it('cancels immediately when stop is omitted even if realtime cleanup throws', async () => {
        realtimeMocks.cancel.mockImplementationOnce(() => {
            throw new Error('realtime cancel failed');
        });
        const mounted = mountRecorder({ realtime: true });
        await flushMount();
        const recorder = FakeMediaRecorder.instances[0];

        mounted.target.querySelector<HTMLButtonElement>('[data-testid="record-cancel-button"]')!.click();
        expect(realtimeMocks.cancel).toHaveBeenCalledTimes(1);
        expect(ownedTrackStop).toHaveBeenCalledTimes(1);
        expect(mounted.cancel).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);

        recorder.emitData('late-discarded-audio');
        recorder.emitStop();
        expect(mounted.cancel).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
        expect(mounted.audioRecorded).not.toHaveBeenCalled();
        await unmount(mounted.component, { outro: false });
        expect(mounted.cancel).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
    });

    // contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle
    it('lets cancel synchronously escalate a pending finish without duplicate events', async () => {
        const mounted = mountRecorder({ realtime: true });
        await flushMount();
        const recorder = FakeMediaRecorder.instances[0];
        recorder.emitData('discarded-audio');

        mounted.target.querySelector<HTMLButtonElement>('[data-testid="record-finish-button"]')!.click();
        mounted.target.querySelector<HTMLButtonElement>('[data-testid="record-cancel-button"]')!.click();

        expect(realtimeMocks.finish).toHaveBeenCalledTimes(1);
        expect(realtimeMocks.cancel).toHaveBeenCalledTimes(1);
        expect(ownedTrackStop).toHaveBeenCalledTimes(1);
        expect(mounted.cancel).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
        expect(mounted.audioRecorded).not.toHaveBeenCalled();

        recorder.emitStop();
        await vi.advanceTimersByTimeAsync(10_000);
        expect(mounted.cancel).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
        await unmount(mounted.component, { outro: false });
        expect(mounted.cancel).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
    });

    // contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    it('keeps final data ordering on the normal delayed stop path', async () => {
        const mounted = mountRecorder();
        await flushMount();
        const recorder = FakeMediaRecorder.instances[0];

        mounted.target.querySelector<HTMLButtonElement>('[data-testid="record-finish-button"]')!.click();
        await vi.advanceTimersByTimeAsync(5_000);
        expect(mounted.audioRecorded).not.toHaveBeenCalled();
        recorder.emitData('final-chunk');
        recorder.emitStop();

        expect(mounted.audioRecorded).toHaveBeenCalledTimes(1);
        const event = mounted.audioRecorded.mock.calls[0][0] as CustomEvent<{ blob: Blob; mimeType: string }>;
        expect(event.detail.blob.size).toBe(new Blob(['final-chunk']).size);
        expect(event.detail.mimeType).toBe('audio/mp4');
        expect(mounted.cancel).not.toHaveBeenCalled();
        expect(mounted.close).toHaveBeenCalledTimes(1);
        expect(ownedTrackStop).toHaveBeenCalledTimes(1);

        await vi.advanceTimersByTimeAsync(10_000);
        expect(mounted.audioRecorded).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
        await unmount(mounted.component, { outro: false });
        expect(mounted.cancel).not.toHaveBeenCalled();
        expect(mounted.close).toHaveBeenCalledTimes(1);
    });

    for (const sendDuringCorrection of [false, true]) {
        // contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.embeds.gated-send
        it(`requests Send once ${sendDuringCorrection ? 'during correction' : 'while recording'} and waits for correction`, async () => {
            let resolveCorrection!: (value: unknown) => void;
            realtimeMocks.correction = new Promise((resolve) => { resolveCorrection = resolve; });
            const mounted = mountRecorder({ realtime: true, allowSend: true });
            await flushMount();
            const recorder = FakeMediaRecorder.instances[0];
            recorder.emitData('recorded-audio');
            if (sendDuringCorrection) {
                mounted.component.stop();
                recorder.emitStop();
                await tick();
                expect(mounted.sendRequested).not.toHaveBeenCalled();
            }
            const send = mounted.target.querySelector<HTMLButtonElement>('[data-testid="record-send-button"]')!;
            expect(send.disabled).toBe(false);
            send.click();
            send.click();
            await tick();
            expect(mounted.sendRequested).toHaveBeenCalledTimes(1);
            expect(realtimeMocks.finish).toHaveBeenCalledTimes(1);
            expect(send.disabled).toBe(true);
            expect(mounted.close).not.toHaveBeenCalled();
            if (!sendDuringCorrection) recorder.emitStop();
            expect(mounted.audioRecorded).toHaveBeenCalledTimes(1);
            resolveCorrection({ transcript: 'Corrected text' });
            await flushMount();
            expect(mounted.close).toHaveBeenCalledTimes(1);
            await unmount(mounted.component, { outro: false });
        });
    }

    for (const directSend of [false, true]) {
        // contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.recording.lifecycle
        it(`${directSend ? 'Send retains processing through admission' : 'Finish closes after correction'} with send retention enabled`, async () => {
            let resolveCorrection!: (value: unknown) => void;
            realtimeMocks.correction = new Promise((resolve) => { resolveCorrection = resolve; });
            const mounted = mountRecorder({ realtime: true, retainUntilSend: true, allowSend: true });
            await flushMount();
            const recorder = FakeMediaRecorder.instances[0];
            recorder.emitData('recorded-audio');
            if (directSend) mounted.target.querySelector<HTMLButtonElement>('[data-testid="record-send-button"]')!.click();
            else mounted.component.stop();
            recorder.emitStop();
            resolveCorrection({ transcript: 'Corrected text' });
            await flushMount();
            if (directSend) {
                expect(mounted.close).not.toHaveBeenCalled();
                expect(mounted.target.querySelector('[data-testid="recording-processing-text"]')).not.toBeNull();
                const cancel = mounted.target.querySelector<HTMLButtonElement>('[data-testid="record-cancel-button"]')!;
                expect(cancel.disabled).toBe(true);
                cancel.click();
                mounted.component.cancel();
                expect(mounted.close).not.toHaveBeenCalled();
                const completed = mounted.component.completeSend();
                expect(mounted.close).toHaveBeenCalledTimes(1);
                await unmount(mounted.component, { outro: false });
                await completed;
            } else {
                expect(mounted.close).toHaveBeenCalledTimes(1);
                await unmount(mounted.component, { outro: false });
            }
            expect(realtimeMocks.cancel).not.toHaveBeenCalled();
        });
    }

    // contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.recording.lifecycle
    it('keeps processing visible until correction and cycles labels every three seconds', async () => {
        let resolveCorrection!: (value: unknown) => void;
        realtimeMocks.correction = new Promise((resolve) => { resolveCorrection = resolve; });
        const mounted = mountRecorder({ realtime: true });
        await flushMount();
        const recorder = FakeMediaRecorder.instances[0];
        recorder.emitData('recorded-audio');
        mounted.component.stop();
        await tick();
        const status = () => mounted.target.querySelector('[data-testid="recording-processing-text"]')?.textContent;
        expect(status()).toContain('improving_transcript');
        recorder.emitStop();
        await tick();
        expect(ownedTrackStop).toHaveBeenCalledTimes(1);
        expect(mounted.audioRecorded).toHaveBeenCalledTimes(1);
        expect(mounted.close).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(2999);
        expect(status()).toContain('improving_transcript');
        await vi.advanceTimersByTimeAsync(1);
        expect(status()).toContain('removing_filler_words');
        await vi.advanceTimersByTimeAsync(3000);
        expect(status()).toContain('making_more_concise');
        await vi.advanceTimersByTimeAsync(3000);
        expect(status()).toContain('improving_transcript');
        mounted.component.stop();
        expect(realtimeMocks.finish).toHaveBeenCalledTimes(1);
        resolveCorrection({ transcript: 'Corrected text' });
        await flushMount();
        expect(mounted.close).toHaveBeenCalledTimes(1);
        expect(status()).toBeUndefined();
        await unmount(mounted.component, { outro: false });
    });

    // contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.recording.lifecycle
    it('closes processing on correction failure without an unhandled rejection', async () => {
        let rejectCorrection!: (reason: Error) => void;
        realtimeMocks.correction = new Promise((_, reject) => { rejectCorrection = reject; });
        const mounted = mountRecorder({ realtime: true });
        await flushMount();
        const recorder = FakeMediaRecorder.instances[0];
        recorder.emitData('recorded-audio');
        mounted.component.stop();
        recorder.emitStop();
        expect(mounted.close).not.toHaveBeenCalled();
        rejectCorrection(new Error('Correction failed'));
        await flushMount();
        expect(mounted.close).toHaveBeenCalledTimes(1);
        await unmount(mounted.component, { outro: false });
    });

    // contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle
    it('leaves viewer shortcuts and handled editor keys alone while capture continues', async () => {
        const mounted = mountRecorder({ realtime: true });
        await flushMount();
        const recorder = FakeMediaRecorder.instances[0];
        const viewer = document.createElement('div');
        viewer.className = 'unified-embed-fullscreen-overlay';
        document.body.appendChild(viewer);
        for (const key of ['Enter', 'Escape']) {
            const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
            document.dispatchEvent(event);
            expect(event.defaultPrevented).toBe(false);
            expect(recorder.state).toBe('recording');
        }
        expect(realtimeMocks.finish).not.toHaveBeenCalled();
        expect(realtimeMocks.cancel).not.toHaveBeenCalled();
        viewer.remove();
        const handled = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true });
        handled.preventDefault();
        document.dispatchEvent(handled);
        expect(recorder.state).toBe('recording');
        await unmount(mounted.component, { outro: false });
    });

    // contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.recording.lifecycle
    it('Escape cancels processing and a late correction cannot close twice', async () => {
        let resolveCorrection!: (value: unknown) => void;
        realtimeMocks.correction = new Promise((resolve) => { resolveCorrection = resolve; });
        const mounted = mountRecorder({ realtime: true });
        await flushMount();
        const recorder = FakeMediaRecorder.instances[0];
        recorder.emitData('recorded-audio');
        mounted.component.stop();
        recorder.emitStop();
        await tick();
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(realtimeMocks.cancel).toHaveBeenCalledTimes(1);
        expect(mounted.cancel).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
        resolveCorrection({ transcript: 'Discarded text' });
        await flushMount();
        expect(mounted.close).toHaveBeenCalledTimes(1);
        await unmount(mounted.component, { outro: false });
    });

    // contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle
    it('cancels a pending correction when the overlay is forcibly removed', async () => {
        const mounted = mountRecorder({ realtime: true });
        await flushMount();
        const recorder = FakeMediaRecorder.instances[0];
        recorder.emitData('recorded-audio');
        mounted.component.stop();
        recorder.emitStop();
        await unmount(mounted.component, { outro: false });
        expect(realtimeMocks.cancel).toHaveBeenCalledTimes(1);
        expect(mounted.close).not.toHaveBeenCalled();
    });

    // contract-test: supporting surface=gui.web assertions=message-input.recording.lifecycle
    it('preserves asynchronous handoff for existing audio embed consumers', async () => {
        const mounted = mountRecorder({ realtime: true, retainUntilCorrection: false });
        await flushMount();
        const recorder = FakeMediaRecorder.instances[0];
        recorder.emitData('recorded-audio');
        mounted.component.stop();
        recorder.emitStop();
        expect(mounted.audioRecorded).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
        await unmount(mounted.component, { outro: false });
        expect(realtimeMocks.cancel).not.toHaveBeenCalled();
    });

    // contract-test: supporting surface=gui.web assertions=message-input.recording.lifecycle
    it('never stops a caller-owned external stream on cancel', async () => {
        const externalTrackStop = vi.fn();
        const externalStream = { getTracks: () => [{ stop: externalTrackStop }] } as unknown as MediaStream;
        const mounted = mountRecorder({ externalStream });
        await flushMount();

        mounted.target.querySelector<HTMLButtonElement>('[data-testid="record-cancel-button"]')!.click();
        expect(externalTrackStop).not.toHaveBeenCalled();
        expect(ownedTrackStop).not.toHaveBeenCalled();
        expect(mounted.cancel).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
        await unmount(mounted.component, { outro: false });
        expect(mounted.cancel).toHaveBeenCalledTimes(1);
        expect(mounted.close).toHaveBeenCalledTimes(1);
    });
});
