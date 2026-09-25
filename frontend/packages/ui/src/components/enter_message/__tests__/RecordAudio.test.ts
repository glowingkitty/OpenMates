// @vitest-environment jsdom

import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import RecordAudio from '../RecordAudio.svelte';

const realtimeMocks = vi.hoisted(() => ({
    finish: vi.fn(),
    cancel: vi.fn(),
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
        correction: new Promise(() => undefined),
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

function mountRecorder(options: { externalStream?: MediaStream; realtime?: boolean } = {}) {
    const close = vi.fn();
    const cancel = vi.fn();
    const audioRecorded = vi.fn();
    const target = document.createElement('div');
    document.body.appendChild(target);
    const component = mount(RecordAudio, {
        target,
        props: {
            initialPosition: { x: 0, y: 0 },
            externalStream: options.externalStream,
            enableRealtime: options.realtime ?? false,
            previewTranscript: null,
        },
        events: {
            close,
            cancel,
            audiorecorded: audioRecorded,
        },
    });
    return { component, target, close, cancel, audioRecorded };
}

describe('RecordAudio finalization', () => {
    let ownedTrackStop: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        vi.useFakeTimers();
        FakeMediaRecorder.instances = [];
        realtimeMocks.finish.mockReset();
        realtimeMocks.cancel.mockReset();
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
