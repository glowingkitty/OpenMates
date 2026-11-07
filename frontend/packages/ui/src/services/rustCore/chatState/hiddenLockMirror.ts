/**
 * Page-side view mirror of the Worker hidden-chat vault (flag-on only). It has no
 * imports so `hiddenChatService.ts` can read `isUnlocked()` / the lockout
 * synchronously without pulling the Rust adapter into default builds, where the
 * flag-guarded reads are dead code and this module is dropped.
 */
export const hiddenLockMirror = {
	unlocked: false,
	lockoutUntilMs: 0,
	/** Remaining lockout in seconds from the last Worker reply. */
	lockoutSeconds(): number {
		return this.lockoutUntilMs > Date.now() ? Math.ceil((this.lockoutUntilMs - Date.now()) / 1000) : 0;
	},
};
