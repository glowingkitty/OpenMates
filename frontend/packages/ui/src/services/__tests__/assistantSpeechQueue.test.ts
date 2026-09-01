// frontend/packages/ui/src/services/__tests__/assistantSpeechQueue.test.ts
// Contract coverage for client-side assistant response speech playback.
// The queue owns one response at a time and never generates or mutates audio.
// It turns ordered ready-segment events into progressive playback and waveform state.
// Product implementation: frontend/packages/ui/src/services/assistantSpeechQueue.ts

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AssistantSpeechQueue,
  type AssistantSpeechSegment,
} from "../assistantSpeechQueue";

type AudioListener = () => void;

class FakeAudio {
  readonly listeners = new Map<string, AudioListener[]>();
  readonly pause = vi.fn();
  readonly play = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);

  constructor(readonly src: string) {}

  addEventListener(event: string, listener: AudioListener) {
    this.listeners.set(event, [...(this.listeners.get(event) ?? []), listener]);
  }

  emit(event: string) {
    for (const listener of this.listeners.get(event) ?? []) {
      listener();
    }
  }
}

const segment = (
  sequence: number,
  status: AssistantSpeechSegment["status"],
  durationMs = 1_000,
): AssistantSpeechSegment => ({
  id: `segment-${sequence}`,
  sequence,
  status,
  durationMs,
  audioUrl: status === "ready" ? `blob:segment-${sequence}` : undefined,
});

describe("AssistantSpeechQueue", () => {
  const audioByUrl = new Map<string, FakeAudio>();
  const audioFactory = vi.fn((url: string) => {
    const audio = new FakeAudio(url);
    audioByUrl.set(url, audio);
    return audio;
  });

  beforeEach(() => {
    audioByUrl.clear();
    audioFactory.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.execution.first-segment-progressive
  it("starts the first ready segment without waiting for later segments", async () => {
    const queue = new AssistantSpeechQueue({ audioFactory });

    queue.start("response-1", [segment(0, "ready"), segment(1, "generating")]);

    await vi.waitFor(() => {
      expect(audioByUrl.get("blob:segment-0")?.play).toHaveBeenCalledOnce();
    });
    expect(queue.state).toMatchObject({
      responseId: "response-1",
      status: "playing",
      activeSegmentId: "segment-0",
    });
    expect(audioFactory).toHaveBeenCalledTimes(1);
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.acknowledgement.deterministic-free,assistant-speech.execution.first-segment-progressive,assistant-speech.playback.pinned-full-response-waveform
  it("plays a prerecorded acknowledgement before paragraphs without adding it to the waveform", async () => {
    const queue = new AssistantSpeechQueue({ audioFactory });
    const acknowledgement: AssistantSpeechSegment = {
      id: "acknowledgement-1",
      sequence: -1,
      status: "ready",
      durationMs: 0,
      audioUrl: "/audio/assistant-acknowledgements/hiro/en-US/general-1.mp3",
      excludeFromWaveform: true,
    };

    queue.start("response-1", [acknowledgement]);
    queue.upsertSegment(segment(0, "ready"));

    await vi.waitFor(() => expect(audioByUrl.get(acknowledgement.audioUrl!)?.play).toHaveBeenCalledOnce());
    expect(queue.waveformRegions).toEqual([
      { segmentId: "segment-0", start: 0, end: 1, status: "ready", active: false },
    ]);

    audioByUrl.get(acknowledgement.audioUrl!)?.emit("ended");
    await vi.waitFor(() => expect(audioByUrl.get("blob:segment-0")?.play).toHaveBeenCalledOnce());
    expect(queue.state.activeSegmentId).toBe("segment-0");
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.execution.first-segment-progressive,assistant-speech.playback.single-queue-segment-control
  it("waits for sequence zero when worker readiness arrives out of order", async () => {
    const queue = new AssistantSpeechQueue({ audioFactory });

    queue.start("response-1", [segment(1, "ready")]);
    await Promise.resolve();
    expect(audioByUrl.get("blob:segment-1")?.play).not.toHaveBeenCalled();

    queue.upsertSegment(segment(0, "ready"));
    await vi.waitFor(() => expect(audioByUrl.get("blob:segment-0")?.play).toHaveBeenCalledOnce());
    expect(queue.state.activeSegmentId).toBe("segment-0");
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.lifecycle.disable-delete-invalidate
  it("does not restart from a delayed segment after stop", async () => {
    const queue = new AssistantSpeechQueue({ audioFactory });
    queue.start("response-1", [segment(0, "generating")]);

    queue.stop();
    queue.upsertSegment(segment(0, "ready"));
    await Promise.resolve();

    expect(queue.state.status).toBe("stopped");
    expect(audioByUrl.get("blob:segment-0")?.play).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.execution.first-segment-progressive,assistant-speech.playback.single-queue-segment-control
  it("waits for the next ordered segment instead of skipping ahead", async () => {
    const queue = new AssistantSpeechQueue({ audioFactory });

    queue.start("response-1", [
      segment(0, "ready"),
      segment(1, "generating"),
      segment(2, "ready"),
    ]);
    audioByUrl.get("blob:segment-0")?.emit("ended");

    expect(queue.state).toMatchObject({
      status: "waiting_for_segment",
      activeSegmentId: "segment-0",
    });
    expect(audioByUrl.get("blob:segment-2")?.play).toBeUndefined();

    queue.upsertSegment(segment(1, "ready"));

    await vi.waitFor(() => {
      expect(audioByUrl.get("blob:segment-1")?.play).toHaveBeenCalledOnce();
    });
    expect(queue.state.activeSegmentId).toBe("segment-1");
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.playback.single-queue-segment-control
  it("stops the prior response when another response becomes active", async () => {
    const queue = new AssistantSpeechQueue({ audioFactory });

    queue.start("response-1", [segment(0, "ready")]);
    const firstAudio = audioByUrl.get("blob:segment-0");
    await vi.waitFor(() => expect(firstAudio?.play).toHaveBeenCalledOnce());
    queue.start("response-2", [segment(1, "ready")]);

    expect(firstAudio?.pause).toHaveBeenCalledOnce();
    await vi.waitFor(() => {
      expect(queue.state).toMatchObject({
        responseId: "response-2",
        activeSegmentId: "segment-1",
      });
    });
    expect(audioFactory).toHaveBeenCalledTimes(2);
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.playback.single-queue-segment-control
  it("moves previous and next controls across paragraph boundaries", async () => {
    const queue = new AssistantSpeechQueue({ audioFactory });

    queue.start("response-1", [segment(0, "ready"), segment(1, "ready"), segment(2, "ready")]);
    await vi.waitFor(() => expect(queue.state.activeSegmentId).toBe("segment-0"));

    await queue.next();
    expect(queue.state.activeSegmentId).toBe("segment-1");
    await queue.next();
    expect(queue.state.activeSegmentId).toBe("segment-2");
    await queue.previous();
    expect(queue.state.activeSegmentId).toBe("segment-1");
    await queue.previous();
    expect(queue.state.activeSegmentId).toBe("segment-0");
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.playback.os-controls-best-effort
  it("feature-detects Media Session while retaining queue controls when absent", () => {
    expect(() => new AssistantSpeechQueue({ audioFactory, mediaSession: undefined })).not.toThrow();

    const setActionHandler = vi.fn();
    new AssistantSpeechQueue({
      audioFactory,
      mediaSession: { setActionHandler },
    });

    expect(setActionHandler).toHaveBeenCalledWith("previoustrack", expect.any(Function));
    expect(setActionHandler).toHaveBeenCalledWith("nexttrack", expect.any(Function));
    expect(setActionHandler).toHaveBeenCalledWith("play", expect.any(Function));
    expect(setActionHandler).toHaveBeenCalledWith("pause", expect.any(Function));
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.playback.autoplay-recovery-visible
  it("preserves ready audio after autoplay rejection and resumes it from one user gesture", async () => {
    const queue = new AssistantSpeechQueue({ audioFactory });
    const blockedAudio = new FakeAudio("blob:segment-0");
    blockedAudio.play.mockRejectedValueOnce(new DOMException("Blocked", "NotAllowedError"));
    audioFactory.mockImplementationOnce(() => blockedAudio);

    queue.start("response-1", [segment(0, "ready")]);

    await vi.waitFor(() => expect(queue.state.status).toBe("blocked_by_autoplay"));
    expect(queue.state.activeSegmentId).toBe("segment-0");
    expect(audioFactory).toHaveBeenCalledTimes(1);

    await queue.continueAfterUserGesture();

    expect(blockedAudio.play).toHaveBeenCalledTimes(2);
    expect(audioFactory).toHaveBeenCalledTimes(1);
    expect(queue.state.status).toBe("playing");
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.playback.pinned-full-response-waveform
  it("builds duration-proportional waveform regions for the full response", () => {
    const queue = new AssistantSpeechQueue({ audioFactory });

    queue.start("response-1", [segment(0, "ready", 2_000), segment(1, "ready", 6_000)]);

    expect(queue.waveformRegions).toEqual([
      { segmentId: "segment-0", start: 0, end: 0.25, status: "ready", active: true },
      { segmentId: "segment-1", start: 0.25, end: 1, status: "ready", active: false },
    ]);
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.playback.pinned-full-response-waveform
  it("keeps the active paragraph highlighted while later segments arrive", async () => {
    const queue = new AssistantSpeechQueue({ audioFactory });

    queue.start("response-1", [segment(0, "ready", 1_000), segment(1, "generating")]);
    await vi.waitFor(() => expect(queue.state.activeSegmentId).toBe("segment-0"));
    queue.upsertSegment(segment(1, "ready", 3_000));
    queue.upsertSegment(segment(2, "ready", 2_000));

    expect(queue.state.activeSegmentId).toBe("segment-0");
    expect(queue.waveformRegions).toEqual([
      { segmentId: "segment-0", start: 0, end: 1 / 6, status: "ready", active: true },
      { segmentId: "segment-1", start: 1 / 6, end: 4 / 6, status: "ready", active: false },
      { segmentId: "segment-2", start: 4 / 6, end: 1, status: "ready", active: false },
    ]);
  });

  // contract-test: direct surface=gui.web assertions=assistant-speech.playback.pinned-full-response-waveform,assistant-speech.playback.single-queue-segment-control
  it("selects and plays the exact paragraph chosen from the waveform", async () => {
    const queue = new AssistantSpeechQueue({ audioFactory });

    queue.start("response-1", [segment(0, "ready"), segment(1, "ready"), segment(2, "ready")]);
    await queue.selectSegment("segment-2");

    expect(queue.state).toMatchObject({ activeSegmentId: "segment-2", status: "playing" });
    expect(audioByUrl.get("blob:segment-2")?.play).toHaveBeenCalledOnce();
  });
});
