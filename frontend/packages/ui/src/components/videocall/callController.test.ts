/**
 * Tests the ephemeral session state machine without a provider call.
 * Server messages are fed directly to isolate visual and billing behavior.
 * Blob URL cleanup and recoverable errors are asserted on in-memory state.
 * This remains a focused companion to browser-level route coverage.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { init } from 'svelte-i18n';

vi.mock('../../stores/authSessionActions', () => ({ checkAuth: vi.fn(async () => true) }));
vi.mock('../../services/audioRealtimeTranscription', () => ({ websocketTokenNeedsRefresh: () => false }));
import { VideoCallController } from './callController';
import { CallAudio } from './callAudio';

type TestController = { handleMessage: (message: Record<string, unknown>) => void; handleBinaryVideo: (data: ArrayBuffer) => void };
function emit(controller: VideoCallController, message: Record<string, unknown>): void {
  (controller as unknown as TestController).handleMessage(message);
}
function emitBinary(controller: VideoCallController, data: Uint8Array): void {
  (controller as unknown as TestController).handleBinaryVideo(data.buffer as ArrayBuffer);
}

describe('video call session state', () => {
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  let createUrl: typeof URL.createObjectURL;
  let revokeUrl: typeof URL.revokeObjectURL;
  beforeEach(() => {
    init({ initialLocale: 'en', fallbackLocale: 'en' });
    createUrl = vi.fn<typeof URL.createObjectURL>().mockReturnValueOnce('blob:clip-1').mockReturnValueOnce('blob:clip-2');
    revokeUrl = vi.fn<typeof URL.revokeObjectURL>();
    URL.createObjectURL = createUrl;
    URL.revokeObjectURL = revokeUrl;
  });
  afterEach(() => {
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
    vi.restoreAllMocks();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.audio-mix
  it('unlocks the output graph before awaiting microphone permission', async () => {
    const order: string[] = [];
    vi.spyOn(CallAudio.prototype, 'unlock').mockImplementation(() => { order.push('unlock'); });
    vi.spyOn(CallAudio.prototype, 'start').mockImplementation(async function (this: CallAudio) { this.unlock(); order.push('microphone'); throw new Error('capture unavailable'); });
    vi.spyOn(CallAudio.prototype, 'stop').mockImplementation(() => {});
    const controller = new VideoCallController();
    await controller.start();
    expect(order).toEqual(['unlock', 'microphone']);
    expect(get(controller).status).toBe('error');
    controller.dispose();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.billing
  it('shows admission rates before usage and accrues only authoritative server usage', () => {
    const controller = new VideoCallController();
    emit(controller, { type: 'ready', audio_credits_per_minute: 27.6, video_credits_per_minute: 1080 });
    expect(get(controller).usage?.audio_credits_per_minute).toBe(27.6);
    expect(get(controller).usage?.video_credits_per_minute).toBe(1080);
    emit(controller, { type: 'usage', credits_accrued: 12.5, credits_charged: 13, audio_credits: 2, video_credits: 10.5, elapsed_seconds: 15, h3_generated_seconds: 5, gemini_input_tokens: 24, gemini_output_tokens: 11, gemini_context_tokens: 24, audio_credits_per_minute: 27.6, video_credits_per_minute: 1080 });
    expect(get(controller).usage?.credits_accrued).toBe(12.5);
    expect(get(controller).usage?.credits_charged).toBe(13);
    controller.dispose();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.user-stop
  it('keeps counting past two minutes and one hour until Hang up releases the call', () => {
    vi.useFakeTimers();
    try {
      const ongoing = new VideoCallController();
      emit(ongoing, { type: 'ready' });
      const socket = { readyState: WebSocket.OPEN, send: vi.fn(), close: vi.fn(), onclose: null };
      const audio = { stop: vi.fn() };
      Object.assign(ongoing, { socket, audio });
      emit(ongoing, { type: 'video.ready', clip_id: 'long-call', data: btoa('abcd') });
      emit(ongoing, { type: 'error', code: 'video_unavailable' });
      vi.advanceTimersByTime(3_661_000);
      expect(get(ongoing)).toMatchObject({ status: 'live', elapsedSeconds: 3661, error: 'A visual is unavailable. Voice continues.' });
      ongoing.hangup();
      expect(get(ongoing)).toMatchObject({ status: 'ended', elapsedSeconds: 3661, error: null, clips: [] });
      expect(socket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'hangup' }));
      expect(socket.close).toHaveBeenCalledOnce();
      expect(audio.stop).toHaveBeenCalledOnce();
      expect(revokeUrl).toHaveBeenCalledWith('blob:clip-1');
      vi.advanceTimersByTime(10_000);
      expect(get(ongoing).elapsedSeconds).toBe(3661);
    } finally { vi.useRealTimers(); }
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.user-stop
  it('preserves terminal errors and allows Hang up', () => {
    const failed = new VideoCallController();
    emit(failed, { type: 'ready' });
    emit(failed, { type: 'error', code: 'provider_failure' });
    expect(get(failed)).toMatchObject({ status: 'error', error: 'The call is unavailable right now. Please try again.' });

    const hungUp = new VideoCallController();
    emit(hungUp, { type: 'ready' });
    hungUp.hangup();
    expect(get(hungUp)).toMatchObject({ status: 'ended', error: null });
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.generated-visuals,video-call.experiment.live-voice
  it('clears a recoverable visual warning when a later clip succeeds', () => {
    const controller = new VideoCallController();
    emit(controller, { type: 'ready' });
    emit(controller, { type: 'error', code: 'video_unavailable' });
    expect(get(controller)).toMatchObject({ status: 'live', videoStatus: 'off', error: 'A visual is unavailable. Voice continues.' });
    emit(controller, { type: 'video.ready', clip_id: 'recovered', data: btoa('abcd') });
    expect(get(controller)).toMatchObject({ status: 'live', videoStatus: 'playing', error: null });
    expect(get(controller).clips.map((clip) => clip.id)).toEqual(['recovered']);
    controller.dispose();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.generated-visuals
  it('accumulates streamed transcript fragments, keeps voice live on visual failure, and releases clips', () => {
    const controller = new VideoCallController();
    emit(controller, { type: 'ready' });
    emit(controller, { type: 'transcript', role: 'model', text: 'Charged ', final: false });
    emit(controller, { type: 'transcript', role: 'model', text: 'particles', final: false });
    emit(controller, { type: 'transcript', role: 'model', text: '', final: true });
    expect(get(controller).transcripts).toEqual([{ role: 'model', text: 'Charged particles', final: true }]);
    emit(controller, { type: 'video.ready', clip_id: '1', duration_seconds: 5, data: btoa('abcd') });
    emit(controller, { type: 'video.queued' });
    expect(get(controller).videoStatus).toBe('playing');
    expect(get(controller).videoPending).toBe(true);
    emit(controller, { type: 'error', code: 'video_unavailable', message: 'Visual unavailable; voice continues.' });
    expect(get(controller).status).toBe('live');
    expect(get(controller).error).toBe('A visual is unavailable. Voice continues.');
    emit(controller, { type: 'video.ready', clip_id: '2', duration_seconds: 5, data: btoa('efgh') });
    expect(get(controller).clips).toHaveLength(2);
    controller.stopVisuals();
    expect(get(controller).clips).toHaveLength(0);
    expect(get(controller).status).toBe('live');
    expect(revokeUrl).toHaveBeenCalledWith('blob:clip-1');
    expect(revokeUrl).toHaveBeenCalledWith('blob:clip-2');
    controller.dispose();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.generated-visuals,video-call.experiment.user-stop
  it('pairs binary MP4 bytes with clip metadata across voice messages and fences bytes after stop', () => {
    const controller = new VideoCallController();
    emit(controller, { type: 'ready' });
    emit(controller, { type: 'video.ready', clip_id: 'binary-1', duration_seconds: 1.5, encoding: 'binary' });
    emit(controller, { type: 'transcript', role: 'model', text: 'Continuing voice', final: true });
    expect(get(controller).clips).toHaveLength(0);
    emitBinary(controller, new Uint8Array([0, 1, 2, 3]));
    expect(get(controller).clips).toMatchObject([{ id: 'binary-1', durationSeconds: 1.5 }]);
    expect(get(controller).transcripts[0].text).toBe('Continuing voice');
    emit(controller, { type: 'video.ready', clip_id: 'binary-2', encoding: 'binary' });
    controller.stopVisuals();
    controller.allowVisuals();
    emitBinary(controller, new Uint8Array([4, 5, 6, 7]));
    expect(get(controller).clips).toHaveLength(0);
    expect(createUrl).toHaveBeenCalledTimes(1);
    controller.dispose();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.generated-visuals,video-call.experiment.audio-mix
  it('keeps accepted visuals during idle drain and concurrent voice, including a pending clip', () => {
    const controller = new VideoCallController();
    emit(controller, { type: 'ready' });
    emit(controller, { type: 'video.ready', clip_id: '1', data: btoa('abcd') });
    emit(controller, { type: 'video.stopped', reason: 'idle', finish_playback: true, pending_clip: true });
    expect(get(controller)).toMatchObject({ status: 'live', visualsAllowed: true, videoDraining: true, videoPending: true, videoStatus: 'playing' });
    emit(controller, { type: 'audio_chunk', data: 'AAAA' });
    emit(controller, { type: 'audio.interrupted' });
    expect(get(controller).clips.map((clip) => clip.id)).toEqual(['1']);
    expect(revokeUrl).not.toHaveBeenCalled();
    controller.videoPlaybackEnded('1');
    expect(get(controller).clips).toHaveLength(1);
    emit(controller, { type: 'video.ready', clip_id: '2', data: btoa('efgh') });
    emit(controller, { type: 'video.drain_complete' });
    expect(get(controller).clips.map((clip) => clip.id)).toEqual(['1', '2']);
    controller.videoPlaybackEnded('2');
    expect(get(controller)).toMatchObject({ status: 'live', visualsAllowed: true, videoStatus: 'off', videoDraining: false });
    expect(get(controller).clips.map((clip) => clip.id)).toEqual(['1', '2']);
    expect(revokeUrl).not.toHaveBeenCalled();
    controller.dispose();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.user-stop,video-call.experiment.generated-visuals
  it('retains a completed frame across visual requests and fences late clips after explicit stop', () => {
    const controller = new VideoCallController();
    const send = vi.spyOn(controller as unknown as { send: (message: Record<string, unknown>) => void }, 'send');
    emit(controller, { type: 'ready' });
    emit(controller, { type: 'video.ready', clip_id: '1', data: btoa('abcd') });
    emit(controller, { type: 'video.stopped', reason: 'idle', finish_playback: true, pending_clip: false });
    emit(controller, { type: 'video.drain_complete' });
    expect(get(controller).clips).toHaveLength(1);
    controller.videoPlaybackEnded('1');
    expect(get(controller).videoStatus).toBe('off');
    expect(get(controller).visualsAllowed).toBe(true);
    controller.sendContinuationFrame('1', 'last-frame-1');
    expect(send).toHaveBeenCalledWith({ type: 'continuation_frame', clip_id: '1', data: 'last-frame-1', source: 'continuation' });
    emit(controller, { type: 'error', code: 'video_unavailable' });
    expect(get(controller)).toMatchObject({ status: 'live', visualsAllowed: true, videoStatus: 'off', videoPending: false });
    expect(get(controller).clips.map((clip) => clip.id)).toEqual(['1']);
    emit(controller, { type: 'video.queued' });
    expect(get(controller)).toMatchObject({ status: 'live', videoStatus: 'queued', videoPending: true });
    emit(controller, { type: 'video.ready', clip_id: '2', data: btoa('efgh') });
    emit(controller, { type: 'video.complete', clip_id: '2' });
    expect(get(controller).clips.map((clip) => clip.id)).toEqual(['1', '2']);
    controller.sendVideoFrame('displayed-frame');
    expect(send).toHaveBeenCalledWith({ type: 'video_frame', data: 'displayed-frame', mime_type: 'image/jpeg' });
    controller.videoPlaybackEnded('2');
    expect(get(controller)).toMatchObject({ status: 'live', visualsAllowed: true, videoStatus: 'off', videoPending: false });
    controller.sendContinuationFrame('2', 'last-frame-2');
    expect(send).toHaveBeenCalledWith({ type: 'continuation_frame', clip_id: '2', data: 'last-frame-2', source: 'continuation' });
    controller.stopVisuals();
    send.mockClear();
    controller.sendVideoFrame('after-close');
    expect(send).not.toHaveBeenCalled();
    emit(controller, { type: 'video.complete', clip_id: '2' });
    emit(controller, { type: 'video.ready', clip_id: 'late', data: btoa('ijkl') });
    expect(get(controller)).toMatchObject({ clips: [], videoDraining: false });
    expect(createUrl).toHaveBeenCalledTimes(2);
    controller.dispose();
  });
});
