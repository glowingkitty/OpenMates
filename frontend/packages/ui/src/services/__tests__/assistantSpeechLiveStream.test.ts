import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import {
  audioEvent, flushSpeechPromises, installSpeechMedia, TestMediaSource, TestSpeechAudio,
} from "./assistantSpeechMediaHarness";

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (payload: unknown) => unknown>(), send: vi.fn(),
  resolve: vi.fn(), decrypt: vi.fn(),
}));
vi.mock("../websocketService", () => ({ webSocketService: {
  on: (name: string, callback: (payload: unknown) => unknown) => mocks.handlers.set(name, callback),
  sendMessage: mocks.send,
} }));
vi.mock("../chatSyncService", () => ({ chatSyncService: { addEventListener() {} } }));
vi.mock("../embedResolver", () => ({ resolveEmbed: mocks.resolve, decodeToonContent: vi.fn() }));
vi.mock("../../utils/audioWaveform", () => ({ buildWaveformFromAudioUrl: vi.fn().mockResolvedValue({ samples: [], duration_seconds: 1 }) }));
vi.mock("../../components/embeds/audio/audioEmbedCrypto", () => ({ fetchAndDecryptAudio: mocks.decrypt, releaseCachedAudio: vi.fn() }));

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  installSpeechMedia();
  mocks.handlers.clear();
  mocks.send.mockReset().mockResolvedValue(undefined);
  mocks.resolve.mockReset().mockResolvedValue({ files: { original: { s3_key: "manual-key" } }, aes_key: "key" });
  mocks.decrypt.mockReset().mockResolvedValue("blob:manual-file");
});
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const status = async (overrides: Record<string, unknown> = {}) => {
  mocks.handlers.get("assistant_speech_status")?.({
    ...audioEvent(), phase: undefined, chunk_index: undefined,
    status: "queued", ...overrides,
  });
  await flushSpeechPromises();
};
const audio = (overrides: Parameters<typeof audioEvent>[0] = {}) => mocks.handlers.get("assistant_speech_audio")?.(audioEvent(overrides));
const controllerForCall = async () => {
  const { assistantSpeechController: controller } = await import("../assistantSpeechController");
  controller.setCallOwner("chat", "call");
  controller.registerSource("chat", "message", "A short live reply.");
  return controller;
};
const beginAudio = async (overrides: Parameters<typeof audioEvent>[0] = {}) => {
  audio(overrides); audio({ ...overrides, phase: "chunk", audio_data: btoa("mp3-first") });
  const media = TestMediaSource.instances.at(-1)!;
  media.open();
  await flushSpeechPromises();
  return media;
};
const sealedMember = (segment_id: string, sequence: number) => ({ segment_id, sequence, kind: "voice_prose_clause", source_version: 1 });
const seal = async (segments: unknown[], overrides: Record<string, unknown> = {}) => {
  mocks.handlers.get("assistant_speech_status")?.({ status: "sealed", voice_call_id: "call", chat_id: "chat",
    message_id: "message", source_version: 1, segments, ...overrides });
  await flushSpeechPromises();
};

// contract-test: direct surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.audio.spoken-rich-response,video-call.audio.intentional-interruption,video-call.privacy
it("completes monotonically when a durable seal arrives after native playback and tolerates late ready/queued events", async () => {
  const controller = await controllerForCall();
  const clause = { segment_id: "a".repeat(64), sequence: 0 };
  await status(clause); const media = await beginAudio(clause);
  const player = TestSpeechAudio.instances[0];
  audio({ ...clause, phase: "end", chunk_index: 1 }); media.buffer.flush(); player.emit("ended");
  await status({ ...clause, status: "ready" });
  expect(get(controller.player).status).toBe("waiting_for_more");
  await seal([sealedMember(clause.segment_id, 0)]);
  expect(get(controller.player).status).toBe("completed");
  await status({ ...clause, status: "queued" });
  await status({ ...clause, status: "ready" });
  await seal([sealedMember(clause.segment_id, 0)]);
  expect(get(controller.player).status).toBe("completed");
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0]);
  expect(player.play).toHaveBeenCalledOnce();
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(mocks.decrypt).not.toHaveBeenCalled();
  expect(mocks.send).not.toHaveBeenCalled();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.audio.single-owner,video-call.audio.intentional-interruption,video-call.privacy
it("removes the completed source between responses without inducing a native source error and reuses the element for the next stream", async () => {
  const controller = await controllerForCall();
  const first = { segment_id: "a".repeat(64), sequence: 0 };
  await status(first);
  const firstMedia = await beginAudio(first);
  const player = TestSpeechAudio.instances[0];
  const staleError = [...player.listeners.get("error")!][0];
  const nativeError = vi.fn();
  player.addEventListener("error", nativeError);
  audio({ ...first, phase: "end", chunk_index: 1 });
  firstMedia.buffer.flush();
  await seal([sealedMember(first.segment_id, 0)]);
  player.emit("ended");
  expect(get(controller.player).status).toBe("completed");

  const next = { message_id: "next-message", segment_id: "b".repeat(64), sequence: 0 };
  controller.registerSource("chat", next.message_id, "A second live response.");
  await status(next); // New queued status precedes its provider's audio start.
  expect(player.getAttribute("src")).toBeNull();
  expect(player.load).toHaveBeenCalledOnce();
  expect(player.error).toBeNull();
  expect(nativeError).not.toHaveBeenCalled();
  expect(get(controller.player).status).toBe("waiting_for_segment");
  expect(TestSpeechAudio.instances).toHaveLength(1);
  const nextMedia = await beginAudio(next);
  expect(player.src).toBe("blob:live-2");
  expect(get(controller.player).status).toBe("playing");
  staleError(); // A detached source callback cannot fail this new source.
  expect(get(controller.player).status).toBe("playing");
  expect(controller.playbackBoundary?.completed_sequences).toEqual([]);
  audio({ ...next, phase: "end", chunk_index: 1 });
  nextMedia.buffer.flush();
  await seal([sealedMember(next.segment_id, 0)], { message_id: next.message_id });
  player.emit("ended");
  expect(get(controller.player).status).toBe("completed");
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0]);
  expect(nativeError).not.toHaveBeenCalled();
  expect(TestSpeechAudio.instances).toHaveLength(1);
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(mocks.decrypt).not.toHaveBeenCalled();
  expect(mocks.send.mock.calls.every(([type, payload]) => type === "assistant_speech" && payload.action === "cancel")).toBe(true);
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.audio.intentional-interruption,video-call.privacy
it("keeps a buffering live source held through provider end, seal and late status without another play", async () => {
  const controller = await controllerForCall();
  const clause = { segment_id: "a".repeat(64), sequence: 0 };
  await status(clause);
  const media = await beginAudio(clause);
  const player = TestSpeechAudio.instances[0];
  player.currentTime = 0.4;
  player.emit("waiting");
  player.pause(); // A native hold must survive automatic status processing.
  audio({ ...clause, phase: "end", chunk_index: 1 });
  media.buffer.flush();
  await seal([sealedMember(clause.segment_id, 0)]);
  await status({ ...clause, status: "ready" });
  await status({ ...clause, status: "queued" });
  expect(player.play).toHaveBeenCalledOnce();
  expect(player.src).toBe("blob:live-1");
  expect(player.currentTime).toBe(0.4);
  expect(controller.playbackBoundary).toMatchObject({ completed_sequences: [], active_sequence: 0, active_offset_ms: 400 });
  await controller.play();
  expect(player.play).toHaveBeenCalledTimes(2);
  player.emit("ended");
  expect(get(controller.player).status).toBe("completed");
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0]);
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(mocks.send).not.toHaveBeenCalled();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.playback.live-call-streaming,assistant-speech.failure.nonblocking-visible-resumable,video-call.audio.intentional-interruption,video-call.privacy
it.each(["before-audio", "mid-stream", "after-end"])("keeps a failed handoff seal terminal %s while preserving only actual heard progress", async (timing) => {
  const controller = await controllerForCall();
  const zero = { segment_id: "a".repeat(64), sequence: 0 };
  const ghost = { segment_id: "b".repeat(64), sequence: 1 };
  const members = [sealedMember(zero.segment_id, 0), sealedMember(ghost.segment_id, 1)];
  await status(zero);
  let media: TestMediaSource | undefined;
  if (timing !== "before-audio") {
    media = await beginAudio(zero);
    TestSpeechAudio.instances[0].currentTime = 0.6;
    if (timing === "after-end") {
      audio({ ...zero, phase: "end", chunk_index: 1 }); media.buffer.flush();
      TestSpeechAudio.instances[0].emit("ended");
    }
  }
  await seal(members, { error: "Speech is temporarily unavailable." });
  expect(get(controller.player)).toMatchObject({ status: "failed", error: "Speech is temporarily unavailable." });
  if (timing === "mid-stream") {
    expect(controller.playbackBoundary).toMatchObject({ completed_sequences: [], active_sequence: 0, active_offset_ms: 600 });
    expect(TestSpeechAudio.instances[0].src).toBe("");
  }
  const expectedHeard = timing === "after-end" ? [0] : [];
  expect(controller.playbackBoundary?.completed_sequences ?? []).toEqual(expectedHeard);
  const mediaCount = TestMediaSource.instances.length;
  const playCount = TestSpeechAudio.instances[0]?.play.mock.calls.length ?? 0;
  audio({ ...zero, phase: "end", chunk_index: 1 });
  audio(ghost); audio({ ...ghost, phase: "chunk", audio_data: btoa("late") });
  await status({ ...ghost, status: "queued" });
  await status({ ...ghost, status: "ready", generated_asset_id: "must-not-fetch" });
  media?.buffer.flush(); TestSpeechAudio.instances[0]?.emit("ended");
  await seal(members); // A conflicting successful duplicate cannot clear failure.
  await seal(members, { error: "Speech is temporarily unavailable." });
  await controller.play(); await controller.previous(); await controller.selectSegment(ghost.segment_id);
  expect(get(controller.player)).toMatchObject({ status: "failed", error: "Speech is temporarily unavailable." });
  expect(controller.playbackBoundary?.completed_sequences ?? []).toEqual(expectedHeard);
  expect(TestMediaSource.instances).toHaveLength(mediaCount);
  expect(TestSpeechAudio.instances[0]?.play.mock.calls.length ?? 0).toBe(playCount);
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(mocks.decrypt).not.toHaveBeenCalled();
  expect(mocks.send).not.toHaveBeenCalled();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.audio.spoken-rich-response,video-call.audio.intentional-interruption,video-call.privacy
it("installs every sealed member before early audio and late queued events without completing unheard successors", async () => {
  const controller = await controllerForCall();
  const zero = { segment_id: "a".repeat(64), sequence: 0 };
  const one = { segment_id: "b".repeat(64), sequence: 1 };
  audio(zero); audio({ ...zero, phase: "chunk", audio_data: btoa("early") });
  audio({ ...zero, phase: "end", chunk_index: 1 });
  expect(TestMediaSource.instances).toHaveLength(0);
  await seal([sealedMember(zero.segment_id, 0), sealedMember(one.segment_id, 1)]);
  expect(get(controller.player).regions).toHaveLength(2);
  const first = TestMediaSource.instances[0]; first.open(); first.buffer.flush();
  const player = TestSpeechAudio.instances[0];
  expect(controller.playbackBoundary?.completed_sequences).toEqual([]);
  player.emit("ended");
  expect(get(controller.player).status).toBe("waiting_for_more");
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0]);
  await status({ ...zero, status: "ready" });
  await status({ ...one, status: "queued" });
  const second = await beginAudio(one);
  audio({ ...one, phase: "end", chunk_index: 1 }); second.buffer.flush();
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0]);
  player.emit("ended");
  expect(get(controller.player).status).toBe("completed");
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0, 1]);
  await status({ ...one, status: "ready" });
  expect(get(controller.player).status).toBe("completed");
  expect(player.play).toHaveBeenCalledTimes(2);
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(mocks.send).not.toHaveBeenCalled();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.privacy
it("validates seal identities and immutable membership, ignores excluded or stale events, and permits an empty seal", async () => {
  const controller = await controllerForCall();
  const id = "a".repeat(64);
  for (const [rows, overrides] of [
    [[sealedMember(id, 0)], { voice_call_id: "old-call" }],
    [[sealedMember(id, 0)], { chat_id: "other-chat" }],
    [[sealedMember(id, 0)], { source_version: 2 }],
    [[sealedMember(id, 0)], { error: "raw server details must not render" }],
    [[sealedMember(id, 0)], { error: null }],
    [[{ ...sealedMember(id, 0), generated_asset_id: "private" }], {}],
    [[sealedMember(id, 0), sealedMember(id, 1)], {}],
    [[sealedMember(id, 1), sealedMember("b".repeat(64), 0)], {}],
    [[sealedMember("invalid-id", 0)], {}],
  ] as Array<[unknown[], Record<string, unknown>]>) {
    await seal(rows, overrides);
    expect(get(controller.player).status).toBe("idle");
  }
  await seal([]);
  expect(get(controller.player).status).toBe("completed");
  await seal([sealedMember(id, 0)]);
  await status({ segment_id: id, sequence: 0 });
  audio({ segment_id: id, sequence: 0 });
  expect(get(controller.player).status).toBe("completed");
  expect(TestMediaSource.instances).toHaveLength(0);
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(mocks.send).not.toHaveBeenCalled();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.audio.intentional-interruption,video-call.privacy
it("prunes superseded prose from authoritative membership and never counts its interrupted audio as heard", async () => {
  const controller = await controllerForCall();
  const stale = { segment_id: "a".repeat(64), sequence: 0 };
  const replacement = { segment_id: "b".repeat(64), sequence: 0 };
  await status(stale); await beginAudio(stale);
  const player = TestSpeechAudio.instances[0]; player.currentTime = 0.5;
  await seal([sealedMember(replacement.segment_id, 0)]);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:live-1");
  expect(get(controller.player).regions.map((region) => region.segmentId)).toEqual([replacement.segment_id]);
  expect(controller.playbackBoundary?.completed_sequences ?? []).toEqual([]);
  audio({ ...stale, phase: "end", chunk_index: 1 });
  await status({ ...stale, status: "ready" });
  const media = await beginAudio(replacement);
  audio({ ...replacement, phase: "end", chunk_index: 1 }); media.buffer.flush(); player.emit("ended");
  expect(get(controller.player).status).toBe("completed");
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0]);
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.privacy,assistant-speech.on-demand.generate-missing-only
it.each(["queued", "registered"])("never converts %s live speech without chunks into manual generation", async (initialStatus) => {
  const controller = await controllerForCall();
  await status({ status: initialStatus });
  await controller.play();
  await controller.selectSegment("clause-0");
  controller.registerSource("chat", "message", "An updated canonical live reply.");
  await flushSpeechPromises();
  expect(mocks.send).not.toHaveBeenCalled();
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(TestMediaSource.instances).toHaveLength(0);
  expect(controller.playbackBoundary).toBeNull();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=video-call.audio.single-owner,video-call.privacy,assistant-speech.on-demand.generate-missing-only
it("blocks same-chat manual Speak while the call owns playback and permits separately cached Speak after release", async () => {
  const controller = await controllerForCall();
  await status(); await beginAudio();
  const player = TestSpeechAudio.instances[0]; player.currentTime = 0.7;
  const liveSource = player.src;
  await controller.request("chat", "message", "Read this manually instead.");
  expect(mocks.send).not.toHaveBeenCalled();
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(mocks.decrypt).not.toHaveBeenCalled();
  expect(controller.getCurrentSourceText()).toBe("A short live reply.");
  expect(player.src).toBe(liveSource);
  expect(player.currentTime).toBe(0.7);
  expect(player.play).toHaveBeenCalledOnce();

  controller.setCallOwner(null);
  await controller.request("chat", "message", "Read the saved text later.");
  expect(mocks.send).toHaveBeenCalledWith("assistant_speech", expect.objectContaining({ action: "request" }));
  await status({ voice_call_id: undefined, status: "accepted", segments: [{
    segment_id: "manual-cached-clause-0", sequence: 0, kind: "voice_prose_clause", status: "ready", generated_asset_id: "new-manual-asset",
  }] });
  await vi.waitFor(() => expect(mocks.decrypt).toHaveBeenCalledOnce());
  await vi.waitFor(() => expect(get(controller.player).status).toBe("playing"));
  expect(player.src).toBe("blob:manual-file");
  expect(mocks.resolve).toHaveBeenCalledWith("new-manual-asset");
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.execution.first-segment-progressive,video-call.audio.spoken-rich-response,video-call.privacy
it("plays live bytes before provider end, ignores stored assets, and grants heard coverage only at drained EOS + audio ended", async () => {
  const controller = await controllerForCall();
  await status();
  const media = await beginAudio();
  const player = TestSpeechAudio.instances[0];
  expect(player.src).toBe("blob:live-1");
  expect(player.play).toHaveBeenCalledOnce();
  expect(media.endOfStream).not.toHaveBeenCalled();
  expect(media.buffer.appended).toHaveLength(1);
  player.currentTime = 0.65;
  expect(controller.playbackBoundary).toMatchObject({ active_offset_ms: 650, completed_sequences: [] });
  const source = player.src;
  await status({ status: "ready", generated_asset_id: "must-not-fetch-call-audio" });
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(mocks.decrypt).not.toHaveBeenCalled();
  expect(player.src).toBe(source);
  expect(player.play).toHaveBeenCalledOnce();
  audio({ phase: "end", chunk_index: 1 });
  expect(media.endOfStream).not.toHaveBeenCalled();
  media.buffer.flush();
  expect(media.endOfStream).toHaveBeenCalledOnce();
  expect(controller.playbackBoundary?.completed_sequences).toEqual([]);
  expect(player.play).toHaveBeenCalledOnce();
  player.emit("ended");
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0]);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith(source);
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.intentional-interruption,video-call.privacy
it("buffers early clause one until authoritative ordering and clause zero playback", async () => {
  const controller = await controllerForCall();
  const clauseOne = { segment_id: "clause-1", sequence: 1 };
  audio(clauseOne);
  audio({ ...clauseOne, phase: "chunk", audio_data: btoa("one") });
  expect(TestMediaSource.instances).toHaveLength(0);
  await status(clauseOne);
  expect(TestMediaSource.instances).toHaveLength(1);
  expect(TestSpeechAudio.instances).toHaveLength(0);
  await status();
  const mediaZero = await beginAudio();
  const player = TestSpeechAudio.instances[0];
  expect(player.src).toBe("blob:live-2");
  audio({ phase: "end", chunk_index: 1 }); mediaZero.buffer.flush();
  player.emit("ended");
  await flushSpeechPromises();
  expect(player.src).toBe("blob:live-1");
  expect(TestSpeechAudio.instances).toHaveLength(1);
  expect(player.play).toHaveBeenCalledTimes(2);
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.execution.first-segment-progressive,video-call.audio.spoken-rich-response,video-call.audio.intentional-interruption
it("retains twelve complete future clauses beyond network idle timeout and plays them in order", async () => {
  const controller = await controllerForCall();
  await status(); const zero = await beginAudio();
  audio({ phase: "end", chunk_index: 1 }); zero.buffer.flush();
  for (let sequence = 1; sequence <= 12; sequence++) {
    const clause = { segment_id: `clause-${sequence}`, sequence };
    await status(clause); audio(clause);
    audio({ ...clause, phase: "chunk", audio_data: btoa(`future-${sequence}`) });
    audio({ ...clause, phase: "end", chunk_index: 1 });
  }
  expect(TestMediaSource.instances).toHaveLength(13);
  expect(TestMediaSource.instances.slice(1).every((media) => media.buffer.appended.length === 0)).toBe(true);
  vi.advanceTimersByTime(30_000);
  expect(get(controller.player).status).toBe("playing");
  const player = TestSpeechAudio.instances[0];
  for (let sequence = 0; sequence <= 12; sequence++) {
    expect(player.src).toBe(`blob:live-${sequence + 1}`);
    if (sequence > 0) {
      const media = TestMediaSource.instances[sequence]; media.open(); media.buffer.flush();
      expect(media.endOfStream).toHaveBeenCalledOnce();
    }
    expect(controller.playbackBoundary?.completed_sequences).toEqual(Array.from({ length: sequence }, (_, index) => index));
    player.emit("ended"); await flushSpeechPromises();
  }
  expect(controller.playbackBoundary?.completed_sequences).toEqual(Array.from({ length: 13 }, (_, index) => index));
  expect(TestSpeechAudio.instances).toHaveLength(1);
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(13);
  expect(mocks.resolve).not.toHaveBeenCalled();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=video-call.privacy,video-call.audio.intentional-interruption,assistant-speech.failure.nonblocking-visible-resumable
it("bounds the pending window at sixteen MiB, rejects overflow without allocation, and frees capacity on disposal", async () => {
  const controller = await controllerForCall();
  const chunk = btoa("x".repeat(128 * 1024));
  for (let sequence = 1; sequence <= 32; sequence++) {
    const clause = { segment_id: `clause-${sequence}`, sequence };
    await status(clause); audio(clause);
    for (let index = 0; index < 4; index++) audio({ ...clause, phase: "chunk", chunk_index: index, audio_data: chunk });
    audio({ ...clause, phase: "end", chunk_index: 4 });
  }
  expect(TestMediaSource.instances).toHaveLength(32);
  expect(TestSpeechAudio.instances).toHaveLength(0);
  const overflow = { segment_id: "clause-33", sequence: 33 };
  await status(overflow); audio(overflow);
  expect(TestMediaSource.instances).toHaveLength(32);
  expect(get(controller.player).regions.find((region) => region.segmentId === overflow.segment_id)?.status).toBe("failed");
  expect(controller.playbackBoundary).toBeNull();

  await status({ segment_id: "clause-1", sequence: 1, status: "invalidated" });
  const replacement = { segment_id: "clause-34", sequence: 34 };
  await status(replacement); audio(replacement);
  audio({ ...replacement, phase: "chunk", audio_data: btoa("replacement") });
  audio({ ...replacement, phase: "end", chunk_index: 1 });
  expect(TestMediaSource.instances).toHaveLength(33);
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  await controller.close();
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(33);
  for (const media of TestMediaSource.instances) media.open();
  expect(TestMediaSource.instances.every((media) => media.buffer.appended.length === 0)).toBe(true);
  expect(controller.playbackBoundary).toBeNull();
  expect(mocks.resolve).not.toHaveBeenCalled();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.execution.first-segment-progressive,video-call.audio.spoken-rich-response,video-call.audio.intentional-interruption,video-call.privacy
it("flushes a complete early successor stream when its first status is ready on an existing response", async () => {
  const controller = await controllerForCall();
  await status(); const zero = await beginAudio();
  const player = TestSpeechAudio.instances[0];
  const one = { segment_id: "clause-1", sequence: 1 };
  audio(one);
  audio({ ...one, phase: "chunk", audio_data: btoa("complete-successor") });
  audio({ ...one, phase: "end", chunk_index: 1 });
  expect(TestMediaSource.instances).toHaveLength(1);
  await status({ ...one, status: "ready" });
  expect(TestMediaSource.instances).toHaveLength(2);
  expect(player.src).toBe("blob:live-1");
  expect(player.play).toHaveBeenCalledOnce();
  expect(controller.playbackBoundary?.completed_sequences).toEqual([]);

  audio({ phase: "end", chunk_index: 1 }); zero.buffer.flush(); player.emit("ended");
  await flushSpeechPromises();
  expect(player.src).toBe("blob:live-2");
  const successor = TestMediaSource.instances[1]; successor.open(); successor.buffer.flush();
  expect(successor.endOfStream).toHaveBeenCalledOnce();
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0]);
  await status({ ...one, status: "ready" });
  expect(player.play).toHaveBeenCalledTimes(2);
  player.emit("ended");
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0, 1]);
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(mocks.decrypt).not.toHaveBeenCalled();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.privacy,assistant-speech.playback.single-queue-segment-control
it("disallows replay and previous/select navigation to disposed live sources without waiting or regenerating", async () => {
  const controller = await controllerForCall();
  await status(); const zero = await beginAudio();
  const one = { segment_id: "clause-1", sequence: 1 };
  await status(one); audio(one); audio({ ...one, phase: "chunk", audio_data: btoa("one") });
  const player = TestSpeechAudio.instances[0];
  audio({ phase: "end", chunk_index: 1 }); zero.buffer.flush(); player.emit("ended");
  await flushSpeechPromises();
  const successor = TestMediaSource.instances[1]; successor.open();
  expect(get(controller.player)).toMatchObject({ status: "playing", activeSegmentId: "clause-1" });
  await controller.previous();
  await controller.selectSegment("clause-0");
  expect(get(controller.player)).toMatchObject({ status: "playing", activeSegmentId: "clause-1" });
  expect(player.play).toHaveBeenCalledTimes(2);

  audio({ ...one, phase: "end", chunk_index: 1 }); successor.buffer.flush(); player.emit("ended");
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0, 1]);
  for (const action of [
    () => controller.play(), () => controller.selectSegment("clause-1"),
    () => controller.previous(), () => controller.selectSegment("clause-0"),
  ]) {
    await action();
    expect(get(controller.player).status).toBe("completed");
    expect(controller.playbackBoundary?.completed_sequences).toEqual([0, 1]);
    expect(player.play).toHaveBeenCalledTimes(2);
  }
  expect(mocks.send).not.toHaveBeenCalled();
  expect(mocks.resolve).not.toHaveBeenCalled();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=video-call.audio.localized-waiting,video-call.audio.intentional-interruption,video-call.privacy
it("streams a waiting confirmation without persisting audio or granting prose heard coverage", async () => {
  const controller = await controllerForCall();
  const waiting = { segment_id: "waiting", sequence: -1, kind: "waiting_confirmation" as const };
  await status(waiting);
  audio(waiting);
  audio({ ...waiting, phase: "chunk", audio_data: btoa("waiting-mp3") });
  const media = TestMediaSource.instances[0]; media.open();
  await flushSpeechPromises();
  expect(get(controller.player).presentationMode).toBe("passive_clip");
  expect(TestSpeechAudio.instances[0].play).toHaveBeenCalledOnce();
  expect(controller.playbackBoundary).toBeNull();
  audio({ ...waiting, phase: "end", chunk_index: 1 }); media.buffer.flush();
  await status({ ...waiting, status: "ready" });
  expect(TestSpeechAudio.instances[0].play).toHaveBeenCalledOnce();
  TestSpeechAudio.instances[0].emit("ended");
  expect(controller.playbackBoundary).toBeNull();
  expect(mocks.resolve).not.toHaveBeenCalled();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=video-call.audio.localized-waiting,video-call.privacy
it("retains an opening clip before text or status while requiring matching authoritative status before playback", async () => {
  const { assistantSpeechController: controller } = await import("../assistantSpeechController");
  controller.setCallOwner("chat", "call");
  const waiting = { segment_id: "waiting", sequence: -1, kind: "waiting_confirmation" as const };
  audio(waiting); audio({ ...waiting, phase: "chunk", audio_data: btoa("opening") });
  expect(TestSpeechAudio.instances).toHaveLength(0);
  audio({ ...waiting, voice_call_id: "old-call" });
  await status(waiting);
  expect(TestMediaSource.instances).toHaveLength(1);
  expect(TestSpeechAudio.instances[0].src).toBe("blob:live-1");
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.intentional-interruption
it("keeps pause/resume on one source and does not skip a missing automatic clause", async () => {
  const controller = await controllerForCall();
  await status(); const zero = await beginAudio();
  const player = TestSpeechAudio.instances[0];
  player.currentTime = 0.4;
  controller.pause();
  await controller.play();
  expect(player.src).toBe("blob:live-1");
  expect(player.currentTime).toBe(0.4);
  const oldEnded = [...player.listeners.get("ended")!][0];
  await status({ segment_id: "clause-2", sequence: 2 });
  audio({ segment_id: "clause-2", sequence: 2 });
  audio({ segment_id: "clause-2", sequence: 2, phase: "chunk", audio_data: btoa("two") });
  audio({ phase: "end", chunk_index: 1 }); zero.buffer.flush(); player.emit("ended");
  await status({ segment_id: "clause-2", sequence: 2, status: "ready" });
  expect(player.src).toBe("blob:live-1");
  expect(get(controller.player).status).toBe("waiting_for_segment");
  await status({ segment_id: "clause-1", sequence: 1 });
  audio({ segment_id: "clause-1", sequence: 1 });
  audio({ segment_id: "clause-1", sequence: 1, phase: "chunk", audio_data: btoa("one") });
  await flushSpeechPromises();
  expect(player.src).toBe("blob:live-3");
  oldEnded();
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0]);
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=video-call.privacy,assistant-speech.failure.nonblocking-visible-resumable
it("bounds early stream data and fails visibly instead of retaining or waiting indefinitely", async () => {
  const controller = await controllerForCall();
  audio();
  for (let index = 0; index < 4; index++) audio({ phase: "chunk", chunk_index: index, audio_data: btoa("x".repeat(128 * 1024)) });
  await status();
  expect(TestMediaSource.instances).toHaveLength(0);
  expect(get(controller.player).status).toBe("failed");
  expect(get(controller.player).error).toBeTruthy();
  expect(mocks.resolve).not.toHaveBeenCalled();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.failure.nonblocking-visible-resumable,video-call.audio.intentional-interruption,video-call.privacy
it.each(["gap", "provider-error", "premature-ended"])("makes %s visible without file lookup, hidden regeneration, or false heard completion", async (failure) => {
  const controller = await controllerForCall();
  await status(); await beginAudio();
  const player = TestSpeechAudio.instances[0];
  player.currentTime = 0.8;
  if (failure === "gap") audio({ phase: "chunk", chunk_index: 2, audio_data: btoa("missing") });
  if (failure === "provider-error") audio({ phase: "error", chunk_index: 1 });
  if (failure === "premature-ended") player.emit("ended");
  await flushSpeechPromises();
  expect(get(controller.player).status).toBe("failed");
  expect(get(controller.player).error).toBeTruthy();
  expect(controller.playbackBoundary).toMatchObject({ completed_sequences: [], active_offset_ms: 800 });
  await status({ status: "ready", generated_asset_id: "ignored" });
  expect(get(controller.player).status).toBe("failed");
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(mocks.send).not.toHaveBeenCalled();
  expect(player.play).toHaveBeenCalledOnce();
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.execution.web-paragraph-demand,video-call.privacy
it("fails unsupported MP3 MediaSource visibly while later manual Speak still generates and decrypts its own file", async () => {
  TestMediaSource.isTypeSupported.mockReturnValue(false);
  const controller = await controllerForCall();
  await status(); audio();
  await status({ status: "ready", generated_asset_id: "ignored-call-asset" });
  expect(get(controller.player).status).toBe("failed");
  expect(get(controller.player).error).toContain("not supported");
  expect(TestSpeechAudio.instances).toHaveLength(0);
  expect(mocks.resolve).not.toHaveBeenCalled();
  controller.setCallOwner(null);
  await controller.request("chat", "message", "Read the saved text later.");
  await status({ voice_call_id: undefined, status: "accepted", segments: [{
    segment_id: "manual-0", sequence: 0, kind: "prose_paragraph", status: "ready", generated_asset_id: "manual-asset",
  }] });
  await vi.waitFor(() => expect(mocks.decrypt).toHaveBeenCalledOnce());
  await vi.waitFor(() => expect(get(controller.player).status).toBe("playing"));
  expect(TestSpeechAudio.instances[0].src).toBe("blob:manual-file");
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.privacy
it("fences old attempts, old source/execution versions, and disposed source callbacks", async () => {
  const controller = await controllerForCall();
  await status(); const oldMedia = await beginAudio();
  const newer = { execution_version: 2, attempt_id: "87654321-1234-4123-8123-123456789012" };
  audio(newer);
  audio({ ...newer, phase: "chunk", audio_data: btoa("new") });
  const media = TestMediaSource.instances[1];
  media.open();
  audio({ phase: "error", chunk_index: 1 });
  audio({ ...newer, source_version: 0, phase: "chunk", chunk_index: 1, audio_data: btoa("stale") });
  audio({ ...newer, attempt_id: "99999999-1234-4123-8123-123456789012", phase: "start" });
  oldMedia.buffer.dispatchEvent(new Event("error"));
  oldMedia.buffer.flush();
  await status({ status: "error", execution_version: 1 });
  await flushSpeechPromises();
  expect(get(controller.player).status).toBe("playing");
  expect(TestMediaSource.instances).toHaveLength(2);
  expect(media.buffer.appended.map((bytes) => new TextDecoder().decode(bytes))).toEqual(["new"]);
  expect(controller.playbackBoundary?.completed_sequences).toEqual([]);
  await controller.close();
});

// contract-test: direct surface=gui.web assertions=video-call.audio.intentional-interruption,video-call.lifecycle.recovery-and-billing,video-call.privacy
it.each(["invalidated", "close", "release"])("disposes live audio on %s and ignores subsequent chunks and ready events", async (action) => {
  const controller = await controllerForCall();
  await status(); await beginAudio();
  const player = TestSpeechAudio.instances[0];
  const source = player.src;
  if (action === "invalidated") await status({ status: "invalidated" });
  if (action === "close") await controller.close();
  if (action === "release") controller.setCallOwner(null);
  const count = player.play.mock.calls.length;
  audio({ phase: "chunk", chunk_index: 1, audio_data: btoa("late") });
  await status({ status: "ready", generated_asset_id: "late-asset" });
  expect(URL.revokeObjectURL).toHaveBeenCalledWith(source);
  expect(player.pause).toHaveBeenCalled();
  expect(player.src).toBe("");
  expect(player.play).toHaveBeenCalledTimes(count);
  expect(mocks.resolve).not.toHaveBeenCalled();
  expect(controller.playbackBoundary?.completed_sequences ?? []).toEqual([]);
  if (action === "invalidated") await controller.close();
});

const turnTrack = { kind: 'voice_prose_turn' as const, segment_id: 'd'.repeat(64), sequence: 0 };
const turnMembers = [sealedMember('a'.repeat(64),0), sealedMember('b'.repeat(64),1)];
const beginTurn = async () => {
  const controller = await controllerForCall();
  await status(turnTrack);
  for (const member of turnMembers) await status(member);
  const media = await beginAudio(turnTrack);
  return {controller,media,player:TestSpeechAudio.instances[0]};
};

// contract-test: supporting surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.audio.spoken-rich-response
it('plays multiple immutable clauses on exactly one continuous source and completes only after seal, drain and native ended',async()=>{
  const {controller,media,player}=await beginTurn();
  expect(TestMediaSource.instances).toHaveLength(1);
  expect(player.play).toHaveBeenCalledOnce();
  player.currentTime=2;
  expect(controller.playbackBoundary).toEqual({assistant_message_id:'message',completed_sequences:[],active_sequence:null,active_offset_ms:0});
  await seal(turnMembers,{turn_track_id:turnTrack.segment_id});
  audio({...turnTrack,phase:'end',chunk_index:1});media.buffer.flush();
  expect(controller.playbackBoundary?.completed_sequences).toEqual([]);
  player.emit('ended');await flushSpeechPromises();
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0,1]);
  expect(get(controller.player).status).toBe('completed');
  expect(TestMediaSource.instances).toHaveLength(1);
  audio({...turnTrack,phase:'error',chunk_index:1});
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0,1]);
  await controller.close();
});

// contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.audio.intentional-interruption
it('uses validated native source time rather than received bytes to report completed and partial clauses',async()=>{
  const {controller,player}=await beginTurn();
  audio({...turnTrack,phase:'alignment',chunk_index:1,clause_timings:[
    {segment_id:turnMembers[0].segment_id,sequence:0,start_ms:0,end_ms:1000},
    {segment_id:turnMembers[1].segment_id,sequence:1,start_ms:1000,end_ms:2500},
  ]});
  expect(controller.playbackBoundary?.completed_sequences).toEqual([]);
  player.currentTime=1.25;
  expect(controller.playbackBoundary).toEqual({assistant_message_id:'message',completed_sequences:[0],active_sequence:1,active_offset_ms:250});
  audio({...turnTrack,phase:'error',chunk_index:1});
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0]);
  await seal(turnMembers,{turn_track_id:turnTrack.segment_id});
  player.emit('ended');
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0]);
  await controller.close();
});

// contract-test: supporting surface=gui.web assertions=video-call.audio.intentional-interruption,assistant-speech.playback.live-call-streaming
it('rejects wrong turn attempts and canceled finalization without claiming unheard clauses',async()=>{
  const {controller,media,player}=await beginTurn();
  audio({...turnTrack,attempt_id:'99999999-9999-4999-8999-999999999999',phase:'end',chunk_index:1});
  audio({...turnTrack,execution_version:2,phase:'end',chunk_index:1});
  audio({...turnTrack,source_version:2,phase:'end',chunk_index:1});
  expect(media.endOfStream).not.toHaveBeenCalled();
  await status({...turnTrack,status:'cancelled'});
  await seal(turnMembers,{turn_track_id:turnTrack.segment_id,error:'Speech is temporarily unavailable.'});
  player.emit('ended');
  expect(controller.playbackBoundary?.completed_sequences).toEqual([]);
  expect(get(controller.player).status).toBe('failed');
  await controller.close();
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.playback.live-call-streaming,assistant-speech.on-demand.generate-missing-only
it('keeps later manual Speak independent of the consumed continuous call source',async()=>{
  const {controller,media,player}=await beginTurn();
  audio({...turnTrack,phase:'end',chunk_index:1});media.buffer.flush();player.emit('ended');
  await seal(turnMembers,{turn_track_id:turnTrack.segment_id});
  await controller.stop();controller.setCallOwner(null);
  await controller.request('chat','manual-message','A normal manual response.');
  expect(mocks.send).toHaveBeenCalledWith('assistant_speech',expect.objectContaining({action:'request',assistant_message_id:'manual-message'}));
  await controller.close();
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.audio.spoken-rich-response
it('waits for successful immutable membership when continuous native playback finishes before the seal',async()=>{
  const {controller,media,player}=await beginTurn();
  audio({...turnTrack,phase:'end',chunk_index:1});media.buffer.flush();player.emit('ended');
  expect(controller.playbackBoundary?.completed_sequences).toEqual([]);
  await seal(turnMembers,{turn_track_id:turnTrack.segment_id});
  expect(controller.playbackBoundary?.completed_sequences).toEqual([0,1]);
  await status({...turnTrack,status:'ready'});
  expect(get(controller.player).status).toBe('completed');
  expect(player.play).toHaveBeenCalledOnce();
  await controller.close();
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.audio.spoken-rich-response
it('refuses unbound finite membership seals for a continuous response rather than creating phantom clause sources',async()=>{
  const {controller,media,player}=await beginTurn();
  audio({...turnTrack,phase:'end',chunk_index:1});media.buffer.flush();player.emit('ended');
  await seal(turnMembers);
  expect(get(controller.player).status).toBe('failed');
  expect(controller.playbackBoundary?.completed_sequences).toEqual([]);
  expect(TestMediaSource.instances).toHaveLength(1);
  await controller.close();
});
