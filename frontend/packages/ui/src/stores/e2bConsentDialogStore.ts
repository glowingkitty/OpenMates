/**
 * Pending "allow E2B upload?" dialog for runs the user starts themselves.
 * Pure UI state: the gate (services/e2bConsentGate.ts) requests the dialog and
 * records the decision; E2bConsentRunHost.svelte renders it and answers.
 * Specification: assertion code-run.e2b.upload-consent.
 */
import { writable } from 'svelte/store';

export type E2bDialogChoice = 'allow' | 'own_machine' | 'not_now' | 'dismissed';

export const e2bConsentDialogOpen = writable(false);

let pending: { promise: Promise<E2bDialogChoice>; resolve: (choice: E2bDialogChoice) => void } | null = null;

/** Open the dialog (one at a time; concurrent callers share the answer). */
export function requestE2bConsentDialog(): Promise<E2bDialogChoice> {
  if (pending) return pending.promise;
  let resolve!: (choice: E2bDialogChoice) => void;
  const promise = new Promise<E2bDialogChoice>((r) => { resolve = r; });
  pending = { promise, resolve };
  e2bConsentDialogOpen.set(true);
  return promise;
}

/** Close the dialog with the user's answer. */
export function answerE2bConsentDialog(choice: E2bDialogChoice): void {
  const current = pending;
  pending = null;
  e2bConsentDialogOpen.set(false);
  current?.resolve(choice);
}
