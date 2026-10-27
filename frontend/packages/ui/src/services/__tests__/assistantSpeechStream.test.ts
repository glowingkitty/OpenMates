import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  AssistantSpeechStream, isAssistantSpeechAudioEvent, supportsAssistantSpeechStream,
  MAX_SPEECH_STREAM_CHUNK_BYTES,
} from "../assistantSpeechStream";
import { audioEvent, installSpeechMedia, TestMediaSource } from "./assistantSpeechMediaHarness";

beforeEach(() => { vi.useFakeTimers(); installSpeechMedia(); });
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

// contract-test: direct surface=gui.web assertions=assistant-speech.execution.first-segment-progressive,video-call.audio.spoken-rich-response
it("appends before provider end and ends the stream only after all append operations drain", () => {
  const failure = vi.fn();
  const stream = new AssistantSpeechStream(failure);
  const media = TestMediaSource.instances[0];
  stream.accept(audioEvent());
  stream.accept(audioEvent({ phase: "chunk", audio_data: btoa("first") }));
  media.open();
  expect(media.buffer.appended.map((bytes) => new TextDecoder().decode(bytes))).toEqual(["first"]);
  expect(stream.complete).toBe(false);
  stream.accept(audioEvent({ phase: "chunk", chunk_index: 1, audio_data: btoa("second") }));
  stream.accept(audioEvent({ phase: "end", chunk_index: 2 }));
  expect(media.endOfStream).not.toHaveBeenCalled();
  media.buffer.flush();
  expect(media.buffer.appended).toHaveLength(2);
  expect(stream.complete).toBe(false);
  media.buffer.flush();
  expect(media.endOfStream).toHaveBeenCalledOnce();
  expect(stream.complete).toBe(true);
  failure.mockClear();
  stream.dispose();
  media.buffer.dispatchEvent(new Event("error"));
  expect(failure).not.toHaveBeenCalled();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.execution.first-segment-progressive,video-call.audio.spoken-rich-response
it("does not expire completed network delivery while a future MediaSource is still unopened", () => {
  const failure = vi.fn();
  const stream = new AssistantSpeechStream(failure);
  const media = TestMediaSource.instances[0];
  stream.accept(audioEvent());
  stream.accept(audioEvent({ phase: "chunk", audio_data: btoa("future") }));
  stream.accept(audioEvent({ phase: "end", chunk_index: 1 }));
  vi.advanceTimersByTime(30_000);
  expect(failure).not.toHaveBeenCalled();
  expect(stream.active).toBe(true);
  expect(stream.complete).toBe(false);
  expect(media.buffer.appended).toHaveLength(0);
  media.open();
  expect(media.buffer.appended).toHaveLength(1);
  expect(stream.complete).toBe(false);
  media.buffer.flush();
  expect(stream.complete).toBe(true);
  expect(media.endOfStream).toHaveBeenCalledOnce();
  stream.dispose();
});

// contract-test: direct surface=gui.web assertions=video-call.privacy,assistant-speech.failure.nonblocking-visible-resumable
it("bounds aggregate retained bytes including drained native buffers and returns budget on disposal", () => {
  const streams: AssistantSpeechStream[] = [];
  const chunk = btoa("x".repeat(MAX_SPEECH_STREAM_CHUNK_BYTES));
  for (let streamIndex = 0; streamIndex < 4; streamIndex++) {
    const stream = new AssistantSpeechStream(() => { throw new Error("Valid aggregate allocation failed"); });
    streams.push(stream);
    const media = TestMediaSource.instances[streamIndex]; media.open();
    for (let chunkIndex = 0; chunkIndex < 32; chunkIndex++) {
      stream.accept(audioEvent({ phase: "chunk", chunk_index: chunkIndex, audio_data: chunk }));
      media.buffer.flush();
    }
  }
  const failure = vi.fn();
  const overflow = new AssistantSpeechStream(failure);
  overflow.accept(audioEvent({ phase: "chunk", audio_data: chunk }));
  expect(failure).toHaveBeenCalledOnce();
  expect(overflow.active).toBe(false);
  expect(overflow.complete).toBe(false);

  streams[0].dispose();
  const replacementFailure = vi.fn();
  const replacement = new AssistantSpeechStream(replacementFailure);
  replacement.accept(audioEvent({ phase: "chunk", audio_data: chunk }));
  expect(replacement.active).toBe(true);
  expect(replacementFailure).not.toHaveBeenCalled();
  for (const stream of streams) stream.dispose();
  replacement.dispose();
});

// contract-test: direct surface=gui.web assertions=assistant-speech.failure.nonblocking-visible-resumable,video-call.audio.intentional-interruption
it.each(["gap", "missing-end-chunk", "provider-error", "malformed-base64", "overflow", "timeout"])(
  "disposes and reports %s without granting complete playback", (failureKind) => {
    const failure = vi.fn();
    const stream = new AssistantSpeechStream(failure);
    const media = TestMediaSource.instances[0];
    stream.accept(audioEvent());
    stream.accept(audioEvent({ phase: "chunk", audio_data: btoa("first") }));
    if (failureKind === "gap") stream.accept(audioEvent({ phase: "chunk", chunk_index: 2, audio_data: btoa("gap") }));
    if (failureKind === "missing-end-chunk") stream.accept(audioEvent({ phase: "end", chunk_index: 2 }));
    if (failureKind === "provider-error") stream.accept(audioEvent({ phase: "error", chunk_index: 1 }));
    if (failureKind === "malformed-base64") stream.accept(audioEvent({ phase: "chunk", chunk_index: 1, audio_data: "$$$" }));
    if (failureKind === "overflow") {
      for (let index = 1; index <= 4; index++) stream.accept(audioEvent({
        phase: "chunk", chunk_index: index, audio_data: btoa("a".repeat(MAX_SPEECH_STREAM_CHUNK_BYTES)),
      }));
    }
    if (failureKind === "timeout") vi.advanceTimersByTime(15_000);
    expect(failure).toHaveBeenCalledOnce();
    expect(stream.complete).toBe(false);
    expect(stream.active).toBe(false);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(stream.url);
    media.open();
    expect(media.buffer.appended).toHaveLength(0);
    stream.fail();
    expect(failure).toHaveBeenCalledOnce();
  },
);

// contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.audio.spoken-rich-response
it("requires supported MP3 MediaSource and validates bounded call/attempt envelopes", () => {
  expect(supportsAssistantSpeechStream()).toBe(true);
  TestMediaSource.isTypeSupported.mockReturnValue(false);
  expect(supportsAssistantSpeechStream()).toBe(false);
  expect(isAssistantSpeechAudioEvent(audioEvent())).toBe(true);
  expect(isAssistantSpeechAudioEvent(audioEvent({ kind: "waiting_confirmation", sequence: -1 }))).toBe(true);
  expect(isAssistantSpeechAudioEvent(audioEvent({ kind: "waiting_confirmation", sequence: 0 }))).toBe(false);
  for (const invalid of [
    { source_version: 0 }, { execution_version: -1 }, { attempt_id: "old" }, { sequence: -1 },
    { kind: "prose_paragraph" }, { phase: "chunk", audio_data: "a".repeat(200_000) },
    { phase: "end", audio_data: "private-bytes" }, { chunk_index: Number.NaN },
  ]) expect(isAssistantSpeechAudioEvent({ ...audioEvent(), ...invalid })).toBe(false);
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.privacy
it('validates bounded text-free continuous clause alignment without accepting finite-stream alignment',()=>{
  const timing={segment_id:'a'.repeat(64),sequence:0,start_ms:0,end_ms:1000};
  const event=audioEvent({kind:'voice_prose_turn',phase:'alignment',clause_timings:[timing]});
  expect(isAssistantSpeechAudioEvent(event)).toBe(true);
  expect(isAssistantSpeechAudioEvent({...event,kind:'voice_prose_clause'})).toBe(false);
  expect(isAssistantSpeechAudioEvent({...event,clause_timings:[{...timing,text:'private'}]})).toBe(false);
  expect(isAssistantSpeechAudioEvent({...event,clause_timings:[{...timing,end_ms:600001}]})).toBe(false);
  expect(isAssistantSpeechAudioEvent({...event,clause_timings:[timing,{...timing,segment_id:'b'.repeat(64),sequence:1,start_ms:500}]})).toBe(false);
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.privacy
it('bounds continuous stream lifetime even while its input keeps producing audio',()=>{
  const failure=vi.fn();const stream=new AssistantSpeechStream(failure,true);
  const turn={kind:'voice_prose_turn' as const};
  stream.accept(audioEvent(turn));
  for(let index=0;index<40;index++){
    stream.accept(audioEvent({...turn,phase:'chunk',chunk_index:index,audio_data:btoa('a')}));
    vi.advanceTimersByTime(14999);
  }
  expect(failure).not.toHaveBeenCalled();
  stream.accept(audioEvent({...turn,phase:'chunk',chunk_index:40,audio_data:btoa('a')}));
  vi.advanceTimersByTime(41);
  expect(failure).toHaveBeenCalledOnce();
  expect(stream.active).toBe(false);
});

// contract-test: supporting surface=gui.web assertions=assistant-speech.playback.live-call-streaming,video-call.privacy
it('permits a continuous turn above the finite-clause bound but rejects above sixteen MiB',()=>{
  const failure=vi.fn();const stream=new AssistantSpeechStream(failure,true);
  const media=TestMediaSource.instances[0];media.open();
  const turn={kind:'voice_prose_turn' as const};stream.accept(audioEvent(turn));
  const bytes=btoa('a'.repeat(MAX_SPEECH_STREAM_CHUNK_BYTES));
  for(let index=0;index<128;index++){
    stream.accept(audioEvent({...turn,phase:'chunk',chunk_index:index,audio_data:bytes}));media.buffer.flush();
  }
  expect(failure).not.toHaveBeenCalled();
  stream.accept(audioEvent({...turn,phase:'chunk',chunk_index:128,audio_data:bytes}));
  expect(failure).toHaveBeenCalledOnce();expect(stream.active).toBe(false);
});
