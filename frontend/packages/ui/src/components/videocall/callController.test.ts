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

type TestController = { handleMessage: (message: Record<string, unknown>) => void };
function emit(controller: VideoCallController, message: Record<string, unknown>): void {
  (controller as unknown as TestController).handleMessage(message);
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

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.billing
  it('shows admission rates before usage and accrues only authoritative server usage', () => {
    const controller = new VideoCallController();
    emit(controller, { type: 'ready', max_duration_seconds: 120, audio_credits_per_minute: 27.6, video_credits_per_minute: 1080 });
    expect(get(controller).usage?.audio_credits_per_minute).toBe(27.6);
    expect(get(controller).usage?.video_credits_per_minute).toBe(1080);
    emit(controller, { type: 'usage', credits_accrued: 12.5, credits_charged: 13, audio_credits: 2, video_credits: 10.5, elapsed_seconds: 15, h3_generated_seconds: 5, gemini_input_tokens: 24, gemini_output_tokens: 11, gemini_context_tokens: 24, audio_credits_per_minute: 27.6, video_credits_per_minute: 1080 });
    expect(get(controller).usage?.credits_accrued).toBe(12.5);
    expect(get(controller).usage?.credits_charged).toBe(13);
    controller.dispose();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.generated-visuals
  it('accumulates streamed transcript fragments, keeps voice live on visual failure, and releases clips', () => {
    const controller = new VideoCallController();
    emit(controller, { type: 'ready', max_duration_seconds: 120 });
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
});
