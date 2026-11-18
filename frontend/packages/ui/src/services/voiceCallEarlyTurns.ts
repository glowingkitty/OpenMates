/**
 * Early-end preparation of voice-call turns (Rust core builds only). The call
 * socket's `turn.likely_end` hint lets the core prepare the text-independent
 * half of the turn (privacy snapshot + core stage) while the user may still
 * finish the sentence; `turn.resumed`, another turn or hangup drops it without
 * sending anything. Calls no model and grants no authority: the final
 * transcript alone admits a turn (feature.video-call complete-turn-admission).
 */
import type { EarlyVoiceTurn } from './rustCore/voice/voiceTurnDelivery';

type Delivery = Pick<typeof import('./rustCore/voice/voiceTurnDelivery'),
	'prepareVoiceTurnThroughCore' | 'discardEarlyVoiceTurn'>;
const EARLY_TURNS_ENABLED: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

// Behind the flag so flag-off builds emit no Rust core chunk.
const loadDelivery = (): Promise<Delivery> => EARLY_TURNS_ENABLED
	? import('./rustCore/voice/voiceTurnDelivery')
	: Promise.reject(new Error('rust_core_off'));

export class VoiceCallEarlyTurns {
	private early = new Map<string, Promise<EarlyVoiceTurn>>();

	constructor(private readonly enabled = EARLY_TURNS_ENABLED, private readonly load = loadDelivery) {}

	/** Start preparing `turnId`; any other prepared turn is dropped first. */
	hint(chatId: string, turnId: string): void {
		if (!this.enabled || this.early.has(turnId)) return;
		for (const id of [...this.early.keys()]) this.withdraw(id);
		const prepared = this.load()
			.then((delivery) => delivery.prepareVoiceTurnThroughCore(chatId, turnId));
		// An early failure only means the final send prepares again.
		prepared.catch(() => undefined);
		this.early.set(turnId, prepared);
	}

	/** Continued speech: drop the preparation of `turnId`. */
	withdraw(turnId: string): void {
		const prepared = this.early.get(turnId);
		if (!prepared) return;
		this.early.delete(turnId);
		void this.load().then((delivery) => delivery.discardEarlyVoiceTurn(prepared));
	}

	/** Hand the preparation of `turnId` to its final send (at most once). */
	take(turnId: string): Promise<EarlyVoiceTurn> | undefined {
		const prepared = this.early.get(turnId);
		this.early.delete(turnId);
		return prepared;
	}

	/** Hangup or a new attempt: drop every preparation. */
	clear(): void {
		for (const id of [...this.early.keys()]) this.withdraw(id);
	}
}
