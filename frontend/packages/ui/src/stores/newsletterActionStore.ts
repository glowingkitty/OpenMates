import { writable } from 'svelte/store';

/**
 * Store for newsletter actions triggered from email links.
 * Used to pass action data (confirm token, unsubscribe token, block email) 
 * from URL hash parameters to the SettingsNewsletter component.
 */
export type NewsletterAction = 
    | { type: 'confirm'; token: string }
    | { type: 'unsubscribe'; token: string }
    | { type: 'block'; email: string }
    | null;

export const newsletterActionStore = writable<NewsletterAction>(null);

/**
 * Set a newsletter action to be processed by SettingsNewsletter component.
 */
export function setNewsletterAction(action: NewsletterAction): void {
    newsletterActionStore.set(action);
}

/**
 * Clear the newsletter action after it has been processed.
 */
export function clearNewsletterAction(): void {
    newsletterActionStore.set(null);
}

