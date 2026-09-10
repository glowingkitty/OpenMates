// Controller regressions for asynchronous assistant speech delivery.
// Uses real projection and queue state with isolated transport and media doubles.
// Covers acceptance ordering, delayed encrypted embed availability and recovery.
// No API, provider, account, or private audio is accessed by this unit suite.
// Browser and first-party transport evidence remain separate CI checks.
import { beforeEach, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (payload: unknown) => unknown>(),
  events: new Map<string, (event: unknown) => unknown>(),
  send: vi.fn().mockResolvedValue(undefined),
  resolve: vi.fn(),
  play: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("../websocketService", () => ({ webSocketService: {
  on: (name: string, callback: (payload: unknown) => unknown) => mocks.handlers.set(name, callback),
  sendMessage: mocks.send,
} }));
vi.mock("../chatSyncService", () => ({ chatSyncService: {
  addEventListener: (name: string, callback: (event: unknown) => unknown) => mocks.events.set(name, callback),
} }));
vi.mock("../embedResolver", () => ({ resolveEmbed: mocks.resolve, decodeToonContent: vi.fn() }));
vi.mock("../../utils/audioWaveform", () => ({ buildWaveformFromAudioUrl: vi.fn().mockResolvedValue({ samples: [20, 80], duration_seconds: 1 }) }));
vi.mock("../../components/embeds/audio/audioEmbedCrypto", () => ({
  fetchAndDecryptAudio: vi.fn().mockResolvedValue("blob:ready-audio"), releaseCachedAudio: vi.fn(),
}));

beforeEach(() => {
  vi.useRealTimers();
  vi.resetModules();
  mocks.handlers.clear();
  mocks.events.clear();
  mocks.resolve.mockReset().mockResolvedValue({ files: { original: { s3_key: "audio-key" } }, aes_key: "test-key" });
  mocks.send.mockReset().mockResolvedValue(undefined);
  mocks.play.mockClear();
  vi.stubGlobal("Audio", class {
    play = mocks.play;
    pause() {}
    addEventListener() {}
  });
});
const accepted = (segments: unknown[]) => mocks.handlers.get("assistant_speech_status")?.({ status: "accepted", segments });
const ready = { segment_id: "segment-0", sequence: 0, status: "ready", generated_asset_id: "asset-0", message_id: "message", chat_id: "chat" };

// contract-test: supporting surface=gui.web assertions=assistant-speech.playback.two-second-idle-grace,assistant-speech.failure.nonblocking-visible-resumable
it("shows pending feedback immediately and exposes request failures", async () => {
  const { assistantSpeechController: controller } = await import("../assistantSpeechController");
  await controller.request("chat", "message", "First paragraph.");
  expect(get(controller.player).status).toBe("waiting_for_segment");
  await mocks.handlers.get("assistant_speech_status")?.({ status: "error" });
  expect(get(controller.player).error).toBeTruthy();
  expect(get(controller.player).status).toBe("failed");
  await controller.close();
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.execution.first-segment-progressive
it("retains readiness delivered before the queued acceptance", async () => {
  const { assistantSpeechController: controller } = await import("../assistantSpeechController");
  await controller.request("chat", "message", "First paragraph.");
  await mocks.handlers.get("assistant_speech_status")?.(ready);
  await accepted([{ segment_id: "segment-0", sequence: 0, status: "queued" }]);
  await vi.waitFor(() => expect(get(controller.player).status).toBe("playing"));
  expect(get(controller.player).regions[0].status).toBe("ready");
  await controller.close();
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.playback.deterministic-chapter-labels
it("maps mixed cached and queued acceptance rows by sequence", async () => {
  const { assistantSpeechController: controller } = await import("../assistantSpeechController");
  await controller.request("chat", "message", "## First\nParagraph one.\n\n## Second\nParagraph two.");
  await accepted([
    { ...ready, segment_id: "segment-1", sequence: 1 },
    { segment_id: "segment-0", sequence: 0, status: "queued" },
  ]);
  await vi.waitFor(() => expect(get(controller.player).regions).toHaveLength(2));
  expect(get(controller.player).regions.map((region) => region.chapter)).toEqual([
    { kind: "heading", text: "First" }, { kind: "heading", text: "Second" },
  ]);
  await controller.close();
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.on-demand.generate-missing-only
it("recovers when the encrypted embed arrives after the lookup window", async () => {
  vi.useFakeTimers();
  mocks.resolve.mockResolvedValue(null);
  const { assistantSpeechController: controller } = await import("../assistantSpeechController");
  await controller.request("chat", "message", "First paragraph.");
  void accepted([ready]);
  await vi.advanceTimersByTimeAsync(4000);
  expect(get(controller.player).error).toBeTruthy();
  mocks.resolve.mockResolvedValue({ files: { original: { s3_key: "audio-key" } }, aes_key: "test-key" });
  await vi.waitFor(() => expect(mocks.events.has("embedUpdated")).toBe(true));
  mocks.events.get("embedUpdated")?.({ detail: { embed_id: "asset-0" } });
  await vi.advanceTimersByTimeAsync(100);
  expect(get(controller.player).status).toBe("playing");
  expect(get(controller.player).error).toBeNull();
  expect(mocks.send).toHaveBeenCalledTimes(1);
  await controller.close();
  vi.useRealTimers();
});
