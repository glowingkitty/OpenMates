import { derived, type Readable } from 'svelte/store';

/**
 * After a reload the session is authenticated before the profile (the owner id
 * every send fence compares against) is hydrated. A send that snapshots the
 * owner in that window is rejected as an owner change once the profile lands,
 * so wait for the owner to exist. Event-driven; resolves at once when no wait is needed.
 */
export function waitForSendOwner(
    auth: Readable<{ isAuthenticated: boolean }>,
    profile: Readable<{ user_id?: string | null }>
): Promise<void> {
    return new Promise((resolve) => {
        const unsubscribe = derived([auth, profile], ([a, p]) => !a.isAuthenticated || !!p.user_id).subscribe((ready) => {
            if (!ready) return;
            resolve();
            queueMicrotask(() => unsubscribe());
        });
    });
}

/** Send accepts a click while the saved model preference is restoring. */
export function isComposerSendBusy(
    sendInProgress: boolean,
    _modelSelectionReady: boolean,
    _queuedEditActive = false
): boolean {
    return sendInProgress;
}

/** A completed send may close only the empty composer focus it began with. */
export function shouldDismissComposerAfterSend(input: {
    focusGenerationAtSend: number;
    currentFocusGeneration: number;
    hasNewDraft: boolean;
    sameOwner: boolean;
}): boolean {
    return input.sameOwner && !input.hasNewDraft && input.focusGenerationAtSend === input.currentFocusGeneration;
}

/** Resolve the preference for the click that already entered local history. */
export async function resolveSavedModelForAcceptedSend(options: {
    settled: Promise<boolean>;
    readyAtClick: boolean;
    selectionAtClick: string;
    readRestoredSelection: () => string;
    stillOwned: () => boolean;
    recover: (selection: string) => Promise<string>;
}): Promise<string> {
    if (!await options.settled) throw new Error('Chat model selection could not be restored');
    if (!options.stillOwned()) throw new Error('Composer owner changed during model restoration');
    const selection = options.readyAtClick ? options.selectionAtClick : options.readRestoredSelection();
    if (selection === 'auto') return selection;
    const recoveredSelection = await options.recover(selection);
    if (!options.stillOwned()) throw new Error('Composer owner changed during model recovery');
    return recoveredSelection;
}
