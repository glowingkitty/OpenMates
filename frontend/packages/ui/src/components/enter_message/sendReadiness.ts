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
