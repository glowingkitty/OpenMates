/** Quiet, local-only confirmations; never routed into call PCM or playback. */
export type VoiceCallCue = 'connected' | 'muted' | 'unmuted' | 'ended';
interface CueNote { frequency: number; offset: number; duration: number }
export const VOICE_CALL_CUE_NOTES: Readonly<Record<VoiceCallCue, readonly CueNote[]>> = {
  connected: [{ frequency: 523.25, offset: 0, duration: 0.07 }, { frequency: 783.99, offset: 0.09, duration: 0.09 }],
  muted: [{ frequency: 440, offset: 0, duration: 0.06 }, { frequency: 329.63, offset: 0.09, duration: 0.06 }],
  unmuted: [{ frequency: 659.25, offset: 0, duration: 0.06 }, { frequency: 880, offset: 0.09, duration: 0.06 }],
  ended: [{ frequency: 392, offset: 0, duration: 0.055 }, { frequency: 293.66, offset: 0.075, duration: 0.055 }, { frequency: 196, offset: 0.15, duration: 0.075 }],
};
const CUE_PEAK = 0.035;
const ATTACK = 0.008;
const RELEASE = 0.018;
const MAX_CUE_LIFETIME_MS = 750;

/** One isolated output context, unlocked by the initiating user gesture. */
export class VoiceCallCuePlayer {
  private context: AudioContext | null = null;
  private generation = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private nodes: Array<{ oscillator: OscillatorNode; gain: GainNode }> = [];

  /** No sound: activate output synchronously before asynchronous admission. */
  prepare(): void {
    if (this.context || typeof AudioContext === 'undefined') return;
    try {
      const context = new AudioContext();
      this.context = context;
      if (context.state === 'suspended') {
        void context.resume().catch(() => { if (this.context === context) this.stop(); });
      }
    } catch { this.stop(); }
  }

  play(cue: VoiceCallCue): void {
    this.prepare();
    const context = this.context;
    if (!context) return;
    this.clearNotes();
    const generation = ++this.generation;
    const current = () => this.context === context && generation === this.generation;
    // Also bounds a suspended audio clock or a resume promise that never settles.
    this.timer = setTimeout(() => {
      if (!current()) return;
      if (cue === 'ended' || context.state !== 'running') this.stop();
      else this.clearNotes();
    }, MAX_CUE_LIFETIME_MS);
    const schedule = () => {
      if (!current()) return;
      try {
        const notes = VOICE_CALL_CUE_NOTES[cue];
        let remaining = notes.length;
        const start = context.currentTime + 0.005;
        for (const note of notes) {
          const oscillator = context.createOscillator();
          const gain = context.createGain();
          this.nodes.push({ oscillator, gain });
          const at = start + note.offset;
          oscillator.type = 'sine';
          oscillator.frequency.setValueAtTime(note.frequency, at);
          gain.gain.setValueAtTime(0, at);
          gain.gain.linearRampToValueAtTime(CUE_PEAK, at + ATTACK);
          gain.gain.setValueAtTime(CUE_PEAK, at + note.duration - RELEASE);
          gain.gain.linearRampToValueAtTime(0, at + note.duration);
          oscillator.connect(gain);
          gain.connect(context.destination);
          oscillator.onended = () => {
            if (!current() || --remaining > 0) return;
            if (cue === 'ended') this.stop();
            else this.clearNotes();
          };
          oscillator.start(at);
          oscillator.stop(at + note.duration);
        }
      } catch { if (current()) this.stop(); }
    };
    try {
      if (context.state === 'running') schedule();
      else void context.resume().then(schedule).catch(() => { if (current()) this.stop(); });
    } catch { this.stop(); }
  }

  private clearNotes(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    for (const { oscillator, gain } of this.nodes.splice(0)) {
      oscillator.onended = null;
      try { oscillator.stop(); } catch { /* Already ended. */ }
      oscillator.disconnect();
      gain.disconnect();
    }
  }

  /** Failed admission/new call: stop immediately; terminal play cleans itself. */
  stop(): void {
    ++this.generation;
    this.clearNotes();
    const context = this.context;
    this.context = null;
    if (context && context.state !== 'closed') void context.close().catch(() => {});
  }
}
