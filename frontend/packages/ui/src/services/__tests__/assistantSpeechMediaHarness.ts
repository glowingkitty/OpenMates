import { vi } from "vitest";
import type { AssistantSpeechAudioEvent } from "../assistantSpeechStream";

export class TestSourceBuffer extends EventTarget {
  updating = false;
  readonly appended: Uint8Array[] = [];
  appendBuffer(bytes: Uint8Array) { this.updating = true; this.appended.push(bytes); }
  flush() { this.updating = false; this.dispatchEvent(new Event("updateend")); }
  abort() { this.updating = false; }
}

export class TestMediaSource extends EventTarget {
  static instances: TestMediaSource[] = [];
  static isTypeSupported = vi.fn(() => true);
  readonly buffer = new TestSourceBuffer();
  readyState = "closed";
  endOfStream = vi.fn(() => { this.readyState = "ended"; });
  constructor() { super(); TestMediaSource.instances.push(this); }
  addSourceBuffer(type: string) {
    if (type !== "audio/mpeg") throw new Error("Unexpected codec");
    return this.buffer;
  }
  open() { this.readyState = "open"; this.dispatchEvent(new Event("sourceopen")); }
}

export class TestSpeechAudio {
  static instances: TestSpeechAudio[] = [];
  readonly listeners = new Map<string, Set<() => void>>();
  currentTime = 0;
  duration = Number.NaN;
  private source: string;
  get src() { return this.source; }
  set src(value: string) { this.source = value; this.currentTime = 0; }
  playbackRate = 1;
  pause = vi.fn();
  play = vi.fn(async () => undefined);
  load = vi.fn();
  constructor(url: string) { this.source = url; TestSpeechAudio.instances.push(this); }
  addEventListener(event: string, listener: () => void) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(listener);
  }
  removeEventListener(event: string, listener: () => void) { this.listeners.get(event)?.delete(listener); }
  emit(event: string) { for (const listener of [...this.listeners.get(event) ?? []]) listener(); }
}

export function installSpeechMedia() {
  TestMediaSource.instances = [];
  TestSpeechAudio.instances = [];
  TestMediaSource.isTypeSupported.mockReset().mockReturnValue(true);
  vi.stubGlobal("MediaSource", TestMediaSource);
  vi.stubGlobal("Audio", TestSpeechAudio);
  const create = vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:live-${TestMediaSource.instances.length}`);
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  return { create, revoke };
}

export const audioEvent = (overrides: Partial<AssistantSpeechAudioEvent> = {}): AssistantSpeechAudioEvent => ({
  chat_id: "chat", message_id: "message", voice_call_id: "call", segment_id: "clause-0",
  sequence: 0, kind: "voice_prose_clause", source_version: 1, execution_version: 1,
  attempt_id: "12345678-1234-4123-8123-123456789012", phase: "start", chunk_index: 0,
  mime_type: "audio/mpeg", ...overrides,
});

export const flushSpeechPromises = async () => { await Promise.resolve(); await Promise.resolve(); };
