/**
 * Transient store for pending invoice data between payment confirmation and invoice page.
 *
 * When a payment succeeds (confirmCardPayment), SettingsBuyCreditsPayment writes
 * the pending invoice info here. When SettingsInvoices mounts, it reads and clears
 * this store, displaying an optimistic "generating" row until the real invoice
 * appears from the DB (via the payment_completed WebSocket event).
 *
 * Architecture context: see docs/architecture/payment-processing.md
 */

import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export interface PendingInvoiceData {
	orderId: string;
	creditsAmount: number;
	amountSmallestUnit: number;
	currency: string;
	isGiftCard?: boolean;
}

// SSR-safe writable — only active in the browser.
export const pendingInvoiceStore = browser
	? writable<PendingInvoiceData | null>(null)
	: ({
			subscribe: () => () => {},
			set: () => {},
			update: () => {}
		} as ReturnType<typeof writable<PendingInvoiceData | null>>);
