import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SKILL_LOOP_MAX_MS, SKILL_LOOP_PERIOD_MS, SKILL_LOOP_PEAK, VoiceCallAmbientSounds } from '../voiceCallAmbientSounds';
import { readFileSync } from 'node:fs';

class Param { value = 1; setValueAtTime = vi.fn(); linearRampToValueAtTime = vi.fn(); cancelScheduledValues = vi.fn(); }
class Ctx {
  static instances: Ctx[] = [];
  state = 'running'; currentTime = 1; destination = { id: 'speakers' };
  oscillators: Array<{ start: ReturnType<typeof vi.fn>; connect: ReturnType<typeof vi.fn> }> = [];
  resume = vi.fn(async () => {});
  close = vi.fn(async () => { this.state = 'closed'; });
  createOscillator = vi.fn(() => {
    const node = { type: '', frequency: new Param(), connect: vi.fn(), disconnect: vi.fn(), start: vi.fn(), stop: vi.fn(), onended: null };
    this.oscillators.push(node); return node;
  });
  createGain = vi.fn(() => ({ gain: new Param(), connect: vi.fn(), disconnect: vi.fn() }));
  constructor() { Ctx.instances.push(this); }
}
const skill = (id: string, status: string) => ({ chat_id: 'c1', embed_id: id, type: 'app-skill-use', status });

describe('voice call ambient sounds', () => {
  let sounds: VoiceCallAmbientSounds;
  beforeEach(() => {
    vi.useFakeTimers();
    Ctx.instances.length = 0;
    vi.stubGlobal('AudioContext', Ctx);
    sounds = new VoiceCallAmbientSounds();
    sounds.setLive(true);
  });
  afterEach(() => { sounds.stop(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds,video-call.sounds.ambient-skill-loop,video-call.sounds.ambient-focus-chime,video-call.sounds.local-only
  it('loops softly while a skill of the call chat runs and stops when it finishes', () => {
    sounds.handleEmbedUpdate(skill('e1', 'processing'), 'c1');
    expect(sounds.looping).toBe(true);
    const context = Ctx.instances[0];
    const first = context.oscillators.length;
    vi.advanceTimersByTime(SKILL_LOOP_PERIOD_MS);
    expect(context.oscillators.length).toBeGreaterThan(first);
    sounds.handleEmbedUpdate(skill('e1', 'finished'), 'c1');
    expect(sounds.looping).toBe(false);
    const count = context.oscillators.length;
    vi.advanceTimersByTime(SKILL_LOOP_PERIOD_MS * 3);
    expect(context.oscillators.length).toBe(count);
    expect(SKILL_LOOP_PEAK).toBeLessThanOrEqual(0.035);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds,video-call.sounds.ambient-skill-loop,video-call.sounds.ambient-focus-chime,video-call.sounds.local-only
  it('stops on a finish refresh that carries no embed type', () => {
    sounds.handleEmbedUpdate(skill('e1', 'processing'), 'c1');
    expect(sounds.looping).toBe(true);
    sounds.handleEmbedUpdate({ chat_id: 'c1', embed_id: 'e1', status: 'finished' }, 'c1');
    expect(sounds.looping).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds,video-call.sounds.ambient-skill-loop,video-call.sounds.ambient-focus-chime,video-call.sounds.local-only
  it('ignores other chats and other embed types, and keeps looping until all skills finish', () => {
    sounds.handleEmbedUpdate({ ...skill('x', 'processing'), chat_id: 'other' }, 'c1');
    sounds.handleEmbedUpdate({ ...skill('y', 'processing'), type: 'code' }, 'c1');
    expect(sounds.looping).toBe(false);
    sounds.handleEmbedUpdate(skill('a', 'processing'), 'c1');
    sounds.handleEmbedUpdate(skill('b', 'processing'), 'c1');
    sounds.handleEmbedUpdate(skill('a', 'finished'), 'c1');
    expect(sounds.looping).toBe(true);
    sounds.handleEmbedUpdate(skill('b', 'error'), 'c1');
    expect(sounds.looping).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds,video-call.sounds.ambient-skill-loop,video-call.sounds.ambient-focus-chime,video-call.sounds.local-only
  it('stops on speech start, mute, away and hangup', () => {
    sounds.handleEmbedUpdate(skill('e1', 'processing'), 'c1');
    sounds.setSpeaking(true); expect(sounds.looping).toBe(false);
    sounds.setSpeaking(false); expect(sounds.looping).toBe(true);
    sounds.setMuted(true); expect(sounds.looping).toBe(false);
    sounds.setMuted(false); expect(sounds.looping).toBe(true);
    sounds.setAway(true); expect(sounds.looping).toBe(false);
    sounds.setAway(false); expect(sounds.looping).toBe(true);
    sounds.setLive(false);
    expect(sounds.looping).toBe(false);
    expect(Ctx.instances[0].close).toHaveBeenCalled();
    sounds.handleEmbedUpdate(skill('e2', 'processing'), 'c1');
    expect(sounds.looping).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds,video-call.sounds.ambient-skill-loop,video-call.sounds.ambient-focus-chime,video-call.sounds.local-only
  it('gives up on a skill whose finish event was lost', () => {
    sounds.handleEmbedUpdate(skill('e1', 'processing'), 'c1');
    vi.advanceTimersByTime(SKILL_LOOP_MAX_MS + 1);
    expect(sounds.looping).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds,video-call.sounds.ambient-skill-loop,video-call.sounds.ambient-focus-chime,video-call.sounds.local-only
  it('plays the focus chime once, not while muted/away/ended', () => {
    sounds.focusChime();
    expect(Ctx.instances[0].oscillators).toHaveLength(2);
    sounds.setMuted(true); sounds.focusChime();
    expect(Ctx.instances[0].oscillators).toHaveLength(2);
    sounds.setMuted(false); sounds.setLive(false); sounds.focusChime();
    expect(Ctx.instances).toHaveLength(1);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds,video-call.sounds.ambient-skill-loop,video-call.sounds.ambient-focus-chime,video-call.sounds.local-only
  it('uses its own output context only: no stream, worklet or PCM routing', () => {
    const source = readFileSync(new URL('../voiceCallAmbientSounds.ts', import.meta.url), 'utf8');
    expect(source).not.toMatch(/MediaStream|createMediaStreamDestination|AudioWorklet|assistantSpeechController|setMicEnabled/);
    sounds.focusChime();
    const node = Ctx.instances[0].oscillators[0];
    expect(node.connect).toHaveBeenCalled();
  });
});
