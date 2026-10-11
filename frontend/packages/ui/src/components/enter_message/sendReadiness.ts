/** Queued edits update an existing message and do not need model restoration. */
export function isComposerSendBusy(
    sendInProgress: boolean,
    modelSelectionReady: boolean,
    queuedEditActive = false
): boolean {
    return sendInProgress || (!queuedEditActive && !modelSelectionReady);
}
