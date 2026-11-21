/**
 * Quiet, local-only ambient sounds of a live web voice call: a soft loop while
 * the assistant runs a skill and a chime when a focus mode starts. They use
 * their own output context and are never routed into the microphone PCM or the
 * assistant speech playback. Loudness matches the call cues (voiceCallCues.ts).
 */
export const SKILL_LOOP_NOTES = [
  { frequency: 261.63, offset: 0, duration: 0.5 },
  { frequency: 329.63, offset: 0.22, duration: 0.55 },
] as const;
export const FOCUS_CHIME_NOTES = [
  { frequency: 493.88, offset: 0, duration: 0.12 },
  { frequency: 739.99, offset: 0.11, duration: 0.2 },
] as const;
export const SKILL_LOOP_PEAK = 0.012;
export const FOCUS_CHIME_PEAK = 0.03;
export const SKILL_LOOP_PERIOD_MS = 2_200;
/** A skill whose finish event was lost must not loop forever. */
export const SKILL_LOOP_MAX_MS = 90_000;
const FADE_OUT_S = 0.06;
const SKILL_EMBED_TYPE = 'app-skill-use';

interface Note { readonly frequency: number; readonly offset: number; readonly duration: number }
interface EmbedUpdateDetail { chat_id?: string; embed_id?: string; type?: string; status?: string; isProcessing?: boolean }

export class VoiceCallAmbientSounds {
  private context: AudioContext | null = null;
  private master: GainNode | null = null;
  private running = new Set<string>();
  private loopTimer: ReturnType<typeof setInterval> | null = null;
  private watchdog: ReturnType<typeof setTimeout> | null = null;
  private speaking = false;
  private muted = false;
  private away = false;
  private live = false;

  /** The call is live (true) or over (false, which also stops everything). */
  setLive(live: boolean): void {
    this.live = live;
    if (!live) this.stop(); else this.sync();
  }
  setSpeaking(speaking: boolean): void { this.speaking = speaking; this.sync(); }
  setMuted(muted: boolean): void { this.muted = muted; this.sync(); }
  setAway(away: boolean): void { this.away = away; this.sync(); }
  get looping(): boolean { return this.loopTimer !== null; }

  /** Routes a canonical embed update of the call's chat to the skill loop. */
  handleEmbedUpdate(detail: EmbedUpdateDetail | undefined, chatId: string | null): void {
    if (!detail || !chatId || detail.chat_id !== chatId || typeof detail.embed_id !== 'string') return;
    if (detail.status === 'processing') {
      if (detail.type !== SKILL_EMBED_TYPE) return;
      this.running.add(detail.embed_id);
    } else if (!this.running.delete(detail.embed_id)) {
      // Finish refreshes (embed_update, recovery) carry no `type`: match by id.
      return;
    }
    this.sync();
  }

  /** One soft chime: a focus mode started or continues in this call. */
  focusChime(): void {
    if (!this.live || this.muted || this.away) return;
    const context = this.ensureContext();
    if (context) this.playNotes(context, FOCUS_CHIME_NOTES, FOCUS_CHIME_PEAK, null);
  }

  /** Hangup/failure: no sound may outlive the call. */
  stop(): void {
    this.running.clear();
    this.stopLoop();
    const context = this.context;
    this.context = null;
    this.master = null;
    if (context && context.state !== 'closed') void context.close().catch(() => {});
  }

  private sync(): void {
    const wanted = this.live && this.running.size > 0 && !this.speaking && !this.muted && !this.away;
    if (wanted && !this.looping) this.startLoop();
    else if (!wanted && this.looping) this.stopLoop();
  }

  private startLoop(): void {
    const context = this.ensureContext();
    if (!context) return;
    this.pulse(context);
    this.loopTimer = setInterval(() => { if (this.context === context) this.pulse(context); }, SKILL_LOOP_PERIOD_MS);
    this.watchdog = setTimeout(() => { this.running.clear(); this.stopLoop(); }, SKILL_LOOP_MAX_MS);
  }

  private stopLoop(): void {
    if (this.loopTimer !== null) clearInterval(this.loopTimer);
    if (this.watchdog !== null) clearTimeout(this.watchdog);
    this.loopTimer = null;
    this.watchdog = null;
    const { context, master } = this;
    if (context && master) {
      // Fade the pending pulse out and drop it; later sounds get a fresh master.
      master.gain.cancelScheduledValues(context.currentTime);
      master.gain.setValueAtTime(master.gain.value, context.currentTime);
      master.gain.linearRampToValueAtTime(0, context.currentTime + FADE_OUT_S);
      this.master = null;
      setTimeout(() => master.disconnect(), FADE_OUT_S * 1000 + 20);
    }
  }

  private ensureContext(): AudioContext | null {
    if (this.context) return this.context;
    if (typeof AudioContext === 'undefined') return null;
    try {
      const context = new AudioContext();
      this.context = context;
      if (context.state === 'suspended') void context.resume().catch(() => { if (this.context === context) this.stop(); });
      return context;
    } catch (error) {
      console.warn('[VoiceCallAmbientSounds] audio output unavailable', error);
      return null;
    }
  }

  private pulse(context: AudioContext): void {
    if (!this.master) {
      this.master = context.createGain();
      this.master.gain.value = 1;
      this.master.connect(context.destination);
    }
    this.playNotes(context, SKILL_LOOP_NOTES, SKILL_LOOP_PEAK, this.master);
  }

  private playNotes(context: AudioContext, notes: readonly Note[], peak: number, bus: GainNode | null): void {
    const start = context.currentTime + 0.005;
    for (const note of notes) {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      const at = start + note.offset;
      oscillator.type = 'sine';
      oscillator.frequency.setValueAtTime(note.frequency, at);
      gain.gain.setValueAtTime(0, at);
      gain.gain.linearRampToValueAtTime(peak, at + 0.04);
      gain.gain.linearRampToValueAtTime(0, at + note.duration);
      oscillator.connect(gain);
      gain.connect(bus ?? context.destination);
      oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
      oscillator.start(at);
      oscillator.stop(at + note.duration);
    }
  }
}
