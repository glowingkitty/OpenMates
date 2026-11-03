// frontend/packages/ui/src/components/enter_message/services/composerInteractionFocusHold.ts
//
// Short-lived "keep the composer open" window. Tapping a PII highlight, the
// PII banner's "Undo all" link or a suggestion rail can unmount the tapped
// node or blur the editor on mobile (iOS) between pointerdown and click.
// While the hold is active, delayed blur handling and outside-pointer
// dismissal must not collapse the draft; only a later tap on the chat
// background does.

export const COMPOSER_INTERACTION_FOCUS_HOLD_MS = 800;

export interface ComposerInteractionFocusHold {
    start(): void;
    isHeld(): boolean;
}

export function createComposerInteractionFocusHold(
    durationMs: number = COMPOSER_INTERACTION_FOCUS_HOLD_MS,
    now: () => number = () => performance.now(),
): ComposerInteractionFocusHold {
    let heldUntil = 0;
    return {
        start() {
            heldUntil = now() + durationMs;
        },
        isHeld() {
            return now() < heldUntil;
        },
    };
}
