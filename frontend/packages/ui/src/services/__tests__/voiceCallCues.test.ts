import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VoiceCallCuePlayer, VOICE_CALL_CUE_NOTES, type VoiceCallCue } from '../voiceCallCues';

class AudioParamStub {
  setValueAtTime = vi.fn();
  linearRampToValueAtTime = vi.fn();
}
class OscillatorStub {
  type = 'sine';
  frequency = new AudioParamStub();
  connect = vi.fn();
  disconnect = vi.fn();
  start = vi.fn();
  stop = vi.fn();
  onended: (() => void) | null = null;
}
class ContextStub {
  static instances: ContextStub[] = [];
  state = 'running';
  currentTime = 5;
  destination = {};
  oscillators: OscillatorStub[] = [];
  gains: Array<{ gain: AudioParamStub; connect: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> }> = [];
  resume = vi.fn(async () => { this.state = 'running'; });
  close = vi.fn(async () => { this.state = 'closed'; });
  createOscillator = vi.fn(() => { const node = new OscillatorStub(); this.oscillators.push(node); return node; });
  createGain = vi.fn(() => {
    const node = { gain: new AudioParamStub(), connect: vi.fn(), disconnect: vi.fn() };
    this.gains.push(node); return node;
  });
  constructor() { ContextStub.instances.push(this); }
}
const finish = (context: ContextStub) => context.oscillators.forEach(node => node.onended?.());

describe('local voice call confirmation sounds', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    ContextStub.instances.length = 0;
    vi.stubGlobal('AudioContext', ContextStub);
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds
  it('prepares one silent context synchronously and reuses it for distinct quiet short cues', () => {
    const player = new VoiceCallCuePlayer();
    player.prepare(); player.prepare();
    expect(ContextStub.instances).toHaveLength(1);
    const context = ContextStub.instances[0];
    expect(context.oscillators).toHaveLength(0);
    const signatures = new Set<string>();
    for (const cue of ['connected', 'muted', 'unmuted', 'ended'] as VoiceCallCue[]) {
      const before = context.oscillators.length;
      player.play(cue);
      const nodes = context.oscillators.slice(before);
      signatures.add(JSON.stringify(nodes.map(node => node.frequency.setValueAtTime.mock.calls)));
      expect(nodes).toHaveLength(VOICE_CALL_CUE_NOTES[cue].length);
      for (const [index, node] of nodes.entries()) {
        const note = VOICE_CALL_CUE_NOTES[cue][index];
        expect(node.start).toHaveBeenCalledWith(5.005 + note.offset);
        expect(node.stop).toHaveBeenCalledWith(5.005 + note.offset + note.duration);
        expect(note.offset + note.duration).toBeLessThan(.35);
        const gain = context.gains[before + index];
        expect(gain.connect).toHaveBeenCalledWith(context.destination);
        expect(gain.gain.linearRampToValueAtTime.mock.calls.map(call => call[0])).toEqual([.035, 0]);
      }
      finish(context);
    }
    expect(signatures.size).toBe(4);
    expect(context.close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds
  it('requests unlock during preparation before any connected confirmation', async () => {
    const player = new VoiceCallCuePlayer();
    player.prepare();
    const context = ContextStub.instances[0];
    player.stop();
    vi.stubGlobal('AudioContext', class extends ContextStub { state = 'suspended'; });
    player.prepare();
    const unlocked = ContextStub.instances[1];
    expect(unlocked.resume).toHaveBeenCalledOnce();
    expect(unlocked.oscillators).toHaveLength(0);
    await Promise.resolve();
    player.play('connected');
    expect(unlocked.oscillators).toHaveLength(2);
    expect(context.close).toHaveBeenCalledOnce();
    player.stop();
    expect(vi.getTimerCount()).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds,video-call.audio.single-owner
  it('lets the terminal sound finish independently of call playback teardown', () => {
    const player = new VoiceCallCuePlayer();
    player.prepare();
    const context = ContextStub.instances[0];
    const assistantContext = new ContextStub();
    player.play('ended');
    void assistantContext.close();
    expect(context.close).not.toHaveBeenCalled();
    expect(context.oscillators.every(node => node.onended !== null)).toBe(true);
    finish(context);
    expect(context.close).toHaveBeenCalledOnce();
    expect(context.oscillators.every(node => node.disconnect.mock.calls.length === 1)).toBe(true);
    expect(context.gains.every(node => node.disconnect.mock.calls.length === 1)).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds
  it('bounds output nodes and timers when rapid manual changes replace a cue', () => {
    const player = new VoiceCallCuePlayer();
    player.play('muted');
    const context = ContextStub.instances[0];
    const oldNodes = [...context.oscillators];
    player.play('unmuted');
    expect(ContextStub.instances).toHaveLength(1);
    expect(oldNodes.every(node => node.onended === null && node.disconnect.mock.calls.length === 1)).toBe(true);
    expect(vi.getTimerCount()).toBe(1);
    finish(context);
    expect(vi.getTimerCount()).toBe(0);
    expect(context.close).not.toHaveBeenCalled();
    player.stop(); player.stop();
    expect(context.close).toHaveBeenCalledOnce();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds
  it('closes a suspended terminal context at the hard lifetime even when resume hangs', async () => {
    const player = new VoiceCallCuePlayer();
    player.prepare();
    const context = ContextStub.instances[0];
    context.state = 'suspended';
    let release!: () => void;
    context.resume.mockImplementation(() => new Promise<void>(resolve => { release = resolve; }));
    player.play('ended');
    vi.advanceTimersByTime(750);
    expect(context.close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
    release(); await Promise.resolve();
    expect(context.oscillators).toHaveLength(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds
  it('cleans ordinary cue nodes if native completion never arrives', () => {
    const player = new VoiceCallCuePlayer();
    player.play('connected');
    const context = ContextStub.instances[0];
    vi.advanceTimersByTime(750);
    expect(context.oscillators.every(node => node.onended === null && node.disconnect.mock.calls.length === 1)).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    player.stop();
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds
  it('fails silently and releases output when autoplay rejects', async () => {
    const player = new VoiceCallCuePlayer();
    player.prepare();
    const context = ContextStub.instances[0];
    context.state = 'suspended';
    context.resume.mockRejectedValueOnce(new Error('autoplay unavailable'));
    expect(() => player.play('connected')).not.toThrow();
    await Promise.resolve(); await Promise.resolve();
    expect(context.close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.confirmation-sounds
  it('fails silently for missing output support and releases a partial graph on construction errors', () => {
    const player = new VoiceCallCuePlayer();
    vi.stubGlobal('AudioContext', undefined);
    expect(() => player.play('connected')).not.toThrow();
    vi.stubGlobal('AudioContext', ContextStub);
    player.prepare();
    const context = ContextStub.instances[0];
    context.createGain.mockImplementationOnce(() => { throw new Error('output unavailable'); });
    expect(() => player.play('muted')).not.toThrow();
    expect(context.close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });
});
