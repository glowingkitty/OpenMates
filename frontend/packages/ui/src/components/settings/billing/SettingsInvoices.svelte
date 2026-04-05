<!--
Invoices Settings - View and download past invoices
-->

<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../../config/api';
    import SettingsItem from '../../SettingsItem.svelte';
    import { notificationStore } from '../../../stores/notificationStore';
    import * as cryptoService from '../../../services/cryptoService';
    import { webSocketService } from '../../../services/websocketService';
    import { pendingInvoiceStore } from '../../../stores/pendingInvoiceStore';
    import { replaceState } from '$app/navigation';

    // Invoice interface
    interface Invoice {
        id: string;
        date: string;
        amount: string;
        credits_purchased: number;
        filename: string;
        is_gift_card?: boolean;  // Whether this invoice is for a gift card purchase
        refunded_at?: string | null;  // ISO timestamp when refund was processed (null if not refunded)
        refund_status?: string | null;  // Status of refund: 'none', 'pending', 'completed', 'failed'
        currency?: string | null;  // ISO currency code lowercase (e.g. "usd", "eur"). Null for legacy invoices.
    }

    let isLoading = $state(false);
    let errorMessage: string | null = $state(null);
    let invoices: Invoice[] = $state([]);
    let refundingInvoiceId: string | null = $state(null);  // Track which invoice is being refunded
    let creditNoteReadyInvoices = $state<Set<string>>(new Set());  // Track which invoices have credit note PDFs ready
    let isInitialLoad = $state(true);  // Track if this is the initial page load
    // Optimistic "processing" invoices — shown immediately after payment succeeds,
    // before the Celery task creates the real invoice in DB.
    let pendingInvoices: Invoice[] = $state([]);

    // Format date for display
    function formatDate(dateStr: string): string {
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });
        } catch {
            return dateStr;
        }
    }

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Zero-decimal currencies where amount is NOT in cents but in whole units.
    // For these currencies we skip the /100 conversion and show no decimal places.
    const ZERO_DECIMAL_CURRENCIES = new Set([
        'jpy', 'krw', 'vnd', 'clp', 'gnf', 'mga', 'pyg', 'rwf', 'ugx', 'xaf', 'xof'
    ]);

    // Format amount from smallest currency unit to display string with currency code.
    // Uses the invoice's actual currency if available, falls back to "eur" for legacy invoices.
    function formatAmount(amountStr: string, currency?: string | null): string {
        try {
            const amountInSmallest = parseInt(amountStr, 10);
            if (isNaN(amountInSmallest)) {
                return amountStr;
            }
            const curr = (currency || 'eur').toLowerCase();
            const isZeroDecimal = ZERO_DECIMAL_CURRENCIES.has(curr);

            // Convert to display amount
            const displayAmount = isZeroDecimal ? amountInSmallest : amountInSmallest / 100;
            const decimals = isZeroDecimal ? 0 : 2;

            return `${displayAmount.toFixed(decimals)} ${curr.toUpperCase()}`;
        } catch {
            return amountStr;
        }
    }

    // Parse month from date for grouping
    function getMonthYear(dateStr: string): string {
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'long'
            });
        } catch {
            return 'Unknown';
        }
    }

    // Group invoices by month
    function groupInvoicesByMonth(invoices: Invoice[]): Record<string, Invoice[]> {
        return invoices.reduce((groups, invoice) => {
            const monthYear = getMonthYear(invoice.date);
            if (!groups[monthYear]) {
                groups[monthYear] = [];
            }
            groups[monthYear].push(invoice);
            return groups;
        }, {} as Record<string, Invoice[]>);
    }

    // Fetch invoices from API
    async function fetchInvoices() {
        isLoading = true;
        errorMessage = null;

        try {
            const endpoint = getApiEndpoint(apiEndpoints.payments.getInvoices);
            console.log('Fetching invoices from:', endpoint);
            
            const response = await fetch(endpoint, {
                credentials: 'include'
            });

            console.log('Response status:', response.status, response.statusText);

            if (!response.ok) {
                // Try to get error details from response body
                // Clone the response so we can read it multiple times if needed
                const responseClone = response.clone();
                let errorDetail = '';
                try {
                    const errorData = await responseClone.json();
                    errorDetail = errorData.detail || errorData.message || '';
                    console.error('Error response body:', errorData);
                } catch (_e) {
                    // If JSON parsing fails, try to get text from original response
                    try {
                        errorDetail = await response.text();
                        console.error('Error response text:', errorDetail);
                    } catch (_e2) {
                        console.error('Could not parse error response');
                    }
                }
                throw new Error(`Failed to fetch invoices: ${response.status} ${response.statusText}${errorDetail ? ` - ${errorDetail}` : ''}`);
            }

            const data = await response.json();
            console.log('Received invoices data:', data);
            
            // Validate response structure
            if (!data || typeof data !== 'object') {
                throw new Error('Invalid response format: expected object');
            }
            
            if (!Array.isArray(data.invoices)) {
                console.warn('Response does not contain invoices array:', data);
                invoices = [];
            } else {
                invoices = data.invoices;
                console.log(`Loaded ${invoices.length} invoices`);
                
                // Remove pending (optimistic) invoices that now have real DB counterparts.
                // Match by order_id which is used as the invoice id for pending invoices.
                if (pendingInvoices.length > 0) {
                    const realIds = new Set(invoices.map(inv => inv.id));
                    // Also match by date proximity — the real invoice may have a different ID
                    // but same credits_purchased amount within a 5-minute window
                    const now = Date.now();
                    pendingInvoices = pendingInvoices.filter(pending => {
                        // Remove if a real invoice with matching ID exists
                        if (realIds.has(pending.id)) return false;
                        // Remove if pending invoice is older than 5 minutes (task should be done)
                        const pendingTime = new Date(pending.date).getTime();
                        if (now - pendingTime > 5 * 60 * 1000) return false;
                        // Keep — still waiting for the real invoice to appear
                        return true;
                    });
                }
                
                // Only mark invoices as ready on initial load (not after refresh)
                // Invoices that were already refunded before page load should have credit notes ready
                // Newly refunded invoices will be marked ready via websocket event
                if (isInitialLoad) {
                    // Collect all refunded invoice IDs first
                    const refundedInvoiceIds = invoices
                        .filter(invoice => isInvoiceRefunded(invoice))
                        .map(invoice => invoice.id);
                    
                    // Create a new Set with all refunded invoice IDs to trigger reactivity
                    // In Svelte 5, we must reassign the Set rather than mutating it
                    if (refundedInvoiceIds.length > 0) {
                        creditNoteReadyInvoices = new Set([...creditNoteReadyInvoices, ...refundedInvoiceIds]);
                    }
                    isInitialLoad = false;
                }
            }
        } catch (error) {
            console.error('Error fetching invoices:', error);
            // Show more detailed error message
            if (error instanceof Error) {
                errorMessage = error.message;
            } else {
                errorMessage = $text('settings.billing.invoices_error_loading');
            }
        } finally {
            isLoading = false;
        }
    }

    // Check if invoice is eligible for refund
    // Eligible if: within 14 days, not a gift card purchase (or gift card not used), and not already refunded
    function isInvoiceEligibleForRefund(invoice: Invoice): boolean {
        try {
            // Don't show refund button if already refunded
            if (isInvoiceRefunded(invoice)) {
                return false;
            }
            
            // Check if gift card purchase - gift cards cannot be refunded once used
            // (backend will check if gift card still exists)
            if (invoice.is_gift_card) {
                // Still show button - backend will check if gift card was used
                return true;
            }
            
            // Check if within 14 days
            const invoiceDate = new Date(invoice.date);
            const now = new Date();
            const daysSincePurchase = Math.floor((now.getTime() - invoiceDate.getTime()) / (1000 * 60 * 60 * 24));
            
            return daysSincePurchase <= 14;
        } catch (error) {
            console.error('Error checking refund eligibility:', error);
            return false;
        }
    }

    // Request refund for invoice
    async function requestRefund(invoice: Invoice) {
        // Prevent multiple refund requests for the same invoice
        if (refundingInvoiceId === invoice.id) {
            return;
        }
        
        // Don't allow refund if already refunded
        if (isInvoiceRefunded(invoice)) {
            return;
        }
        
        refundingInvoiceId = invoice.id;
        
        try {
            notificationStore.info($text('settings.billing.invoices_refund_processing'));

            // Get email encryption key for server to decrypt email (same as invoice/purchase confirmation)
            const emailEncryptionKey = cryptoService.getEmailEncryptionKeyForApi();
            if (!emailEncryptionKey) {
                throw new Error('Email encryption key not found. Please refresh the page and try again.');
            }

            const response = await fetch(getApiEndpoint(apiEndpoints.payments.requestRefund), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    invoice_id: invoice.id,
                    email_encryption_key: emailEncryptionKey
                })
            });

            const data = await response.json();

            if (!response.ok) {
                const errorMessage = data.detail || data.message || $text('settings.billing.invoices_refund_error');
                throw new Error(errorMessage);
            }

            if (data.success) {
                notificationStore.success(
                    data.message || $text('settings.billing.invoices_refund_success')
                );
                
                // Update credits if provided in response
                if (data.unused_credits !== undefined && data.total_credits !== undefined) {
                    // The backend will broadcast the credit update via WebSocket
                    // Settings.svelte already listens for 'user_credits_updated' events
                    console.log(`Refund processed: ${data.unused_credits} credits refunded`);
                }
                
                // Refresh invoices to update UI
                await fetchInvoices();
            } else {
                throw new Error(data.message || $text('settings.billing.invoices_refund_error'));
            }
        } catch (error) {
            console.error('Error requesting refund:', error);
            const errorMessage = error instanceof Error ? error.message : $text('settings.billing.invoices_refund_error');
            notificationStore.error(errorMessage);
        } finally {
            refundingInvoiceId = null;
        }
    }
    
    // Check if invoice is refunded
    function isInvoiceRefunded(invoice: Invoice): boolean {
        return invoice.refund_status === 'completed' || invoice.refunded_at !== null;
    }
    
    // Format refund date for display
    function _formatRefundDate(refundedAt: string | null | undefined): string {
        if (!refundedAt) {
            return '';
        }
        try {
            const date = new Date(refundedAt);
            return date.toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch {
            return refundedAt;
        }
    }

    // Download invoice
    async function downloadInvoice(invoice: Invoice) {
        try {
            notificationStore.info($text('settings.billing.invoices_downloading'));

            const downloadUrl = getApiEndpoint(
                apiEndpoints.payments.downloadInvoice.replace('{id}', invoice.id)
            );

            const response = await fetch(downloadUrl, {
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Failed to download invoice');
            }

            // Get filename from Content-Disposition header - NO FALLBACK
            // Fail if filename cannot be extracted so we know there's an issue
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename: string | null = null;
            
            if (!contentDisposition) {
                throw new Error('Content-Disposition header missing in invoice download response');
            }
            
            // Try multiple patterns to extract filename
            // Pattern 1: filename*=UTF-8''value (RFC 5987 format, preferred for UTF-8)
            let filenameMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
            if (filenameMatch && filenameMatch[1]) {
                // Decode the filename (it may be URL-encoded)
                try {
                    filename = decodeURIComponent(filenameMatch[1]);
                } catch (_e) {
                    filename = filenameMatch[1];
                }
            } else {
                // Pattern 2: filename="value" or filename='value' (quoted)
                filenameMatch = contentDisposition.match(/filename\s*=\s*["']([^"']+)["']/i);
                if (filenameMatch && filenameMatch[1]) {
                    filename = filenameMatch[1];
                } else {
                    // Pattern 3: filename=value (unquoted)
                    filenameMatch = contentDisposition.match(/filename\s*=\s*([^;\s]+)/i);
                    if (filenameMatch && filenameMatch[1]) {
                        filename = filenameMatch[1];
                    }
                }
            }
            
            if (!filename) {
                throw new Error(`Failed to extract filename from Content-Disposition header: ${contentDisposition}`);
            }

            // Create blob and download
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);

            notificationStore.success($text('settings.billing.invoices_download_success'));
        } catch (error) {
            console.error('Error downloading invoice:', error);
            notificationStore.error($text('settings.billing.invoices_download_error'));
        }
    }

    // Download credit note for refunded invoice
    async function downloadCreditNote(invoice: Invoice) {
        try {
            notificationStore.info($text('settings.billing.invoices_downloading_credit_note'));

            // Use invoice ID to download the associated credit note
            // The backend endpoint will find the credit note by invoice_id
            const downloadUrl = getApiEndpoint(
                apiEndpoints.payments.downloadCreditNote.replace('{id}', invoice.id)
            );

            const response = await fetch(downloadUrl, {
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Failed to download credit note');
            }

            // Get filename from Content-Disposition header - NO FALLBACK
            // Fail if filename cannot be extracted so we know there's an issue
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename: string | null = null;
            
            if (!contentDisposition) {
                throw new Error('Content-Disposition header missing in credit note download response');
            }
            
            // Try multiple patterns to extract filename
            // Pattern 1: filename*=UTF-8''value (RFC 5987 format, preferred for UTF-8)
            let filenameMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
            if (filenameMatch && filenameMatch[1]) {
                // Decode the filename (it may be URL-encoded)
                try {
                    filename = decodeURIComponent(filenameMatch[1]);
                } catch (_e) {
                    filename = filenameMatch[1];
                }
            } else {
                // Pattern 2: filename="value" or filename='value' (quoted)
                filenameMatch = contentDisposition.match(/filename\s*=\s*["']([^"']+)["']/i);
                if (filenameMatch && filenameMatch[1]) {
                    filename = filenameMatch[1];
                } else {
                    // Pattern 3: filename=value (unquoted)
                    filenameMatch = contentDisposition.match(/filename\s*=\s*([^;\s]+)/i);
                    if (filenameMatch && filenameMatch[1]) {
                        filename = filenameMatch[1];
                    }
                }
            }
            
            if (!filename) {
                throw new Error(`Failed to extract filename from Content-Disposition header: ${contentDisposition}`);
            }

            // Create blob and download
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);

            notificationStore.success($text('settings.billing.invoices_download_credit_note_success'));
        } catch (error) {
            console.error('Error downloading credit note:', error);
            notificationStore.error($text('settings.billing.invoices_download_credit_note_error'));
        }
    }

    // Handle deep link refund - format: #settings/billing/invoices/{invoice_id}/refund
    // Check URL for refund deep link when component mounts or when invoices are loaded
    $effect(() => {
        // Only process refund deep link if invoices are loaded
        if (invoices.length > 0 && !isLoading) {
            // Check for refund deep link in URL hash (e.g., #settings/billing/invoices/{invoice_id}/refund)
            const hash = window.location.hash;
            const refundMatch = hash.match(/^#settings\/billing\/invoices\/([^/]+)\/refund$/);
            
            if (refundMatch) {
                const refundInvoiceId = refundMatch[1];
                console.debug(`[SettingsInvoices] Deep link refund detected for invoice: ${refundInvoiceId}`);
                
                // Find the invoice with matching ID
                const invoiceToRefund = invoices.find(inv => inv.id === refundInvoiceId);
                
                if (invoiceToRefund) {
                    // Check if invoice is eligible for refund
                    if (isInvoiceEligibleForRefund(invoiceToRefund)) {
                        console.debug(`[SettingsInvoices] Invoice ${refundInvoiceId} is eligible for refund, triggering refund...`);
                        
                        // Small delay to ensure UI is ready
                        setTimeout(() => {
                            requestRefund(invoiceToRefund);
                        }, 500);
                    } else {
                        console.warn(`[SettingsInvoices] Invoice ${refundInvoiceId} is not eligible for refund`);
                        notificationStore.info(
                            $text('settings.billing.invoices_refund_not_eligible'),
                            5000
                        );
                    }
                    
                    // Clear the refund deep link from URL after processing
                    // Remove hash completely to keep URL clean (as per deep link processing requirements)
                    replaceState(window.location.pathname + window.location.search, {});
                } else {
                    console.warn(`[SettingsInvoices] Invoice ${refundInvoiceId} not found in invoices list`);
                    notificationStore.error(
                        $text('settings.billing.invoices_refund_not_found'),
                        5000
                    );
                    
                    // Clear the refund deep link from URL even if invoice not found
                    // Remove hash completely to keep URL clean (as per deep link processing requirements)
                    replaceState(window.location.pathname + window.location.search, {});
                }
            }
        }
    });

    // Handle credit note ready websocket event
    // Note: In Svelte 5, we must reassign the Set to trigger reactivity
    // Direct mutation (.add()) doesn't trigger reactivity updates
    function handleCreditNoteReady(payload: { invoice_id: string }) {
        console.log('Credit note PDF ready for invoice:', payload.invoice_id);
        // Create a new Set with the existing values plus the new invoice ID
        // This reassignment triggers Svelte 5's reactivity system
        creditNoteReadyInvoices = new Set([...creditNoteReadyInvoices, payload.invoice_id]);
    }

    // Handle payment_completed websocket event — re-fetch invoices so the new one appears
    // immediately instead of requiring a manual page refresh.
    function handlePaymentCompleted(payload: { order_id: string; credits_purchased: number }) {
        console.log('Payment completed, refreshing invoices. Order:', payload.order_id);
        fetchInvoices();
    }

    onMount(() => {
        // Check if a payment just completed — if so, add an optimistic pending invoice
        // so the user sees it immediately while the Celery task generates the real one.
        const unsubscribe = pendingInvoiceStore.subscribe((pending) => {
            if (pending) {
                addPendingInvoice(pending.orderId, pending.creditsAmount, pending.amountSmallestUnit, pending.currency, pending.isGiftCard);
                pendingInvoiceStore.set(null);  // Consume — only process once
            }
        });
        unsubscribe();  // Synchronous read — unsubscribe immediately

        fetchInvoices();
        
        // Listen for credit note ready events
        webSocketService.on('credit_note_ready', handleCreditNoteReady);
        // Listen for payment completed — auto-refresh invoices when a purchase finishes
        webSocketService.on('payment_completed', handlePaymentCompleted);
    });

    onDestroy(() => {
        // Clean up websocket listeners
        webSocketService.off('credit_note_ready', handleCreditNoteReady);
        webSocketService.off('payment_completed', handlePaymentCompleted);
    });

    // Merge real invoices with pending (optimistic) ones for display.
    // Pending invoices appear at the top until the real invoice arrives from the DB.
    const allInvoices = $derived([...pendingInvoices, ...invoices]);

    // Group invoices by month for display
    // Using $derived to reactively compute grouped invoices whenever invoices change
    const groupedInvoices = $derived(groupInvoicesByMonth(allInvoices));

    /**
     * Add an optimistic "processing" invoice to the list.
     * Called by SettingsBuyCreditsPayment after confirmCardPayment succeeds,
     * so the invoice appears immediately in the invoices page even before
     * the backend Celery task creates the real invoice in the DB.
     */
    export function addPendingInvoice(orderId: string, creditsAmount: number, amountSmallestUnit: number, currency: string, isGiftCard = false) {
        // Don't add if already exists (e.g. double-click)
        if (pendingInvoices.some(p => p.id === orderId) || invoices.some(i => i.id === orderId)) {
            return;
        }
        pendingInvoices = [...pendingInvoices, {
            id: orderId,
            date: new Date().toISOString(),
            amount: String(amountSmallestUnit),
            credits_purchased: creditsAmount,
            filename: '',  // No file yet — invoice PDF is being generated
            currency: currency.toLowerCase(),
            is_gift_card: isGiftCard,
            refunded_at: null,
            refund_status: null,
        }];
    }
</script>

<!-- TODO add info about how long invoices are kept before being automatically deleted (10 years?) -->
<!-- Header -->
<div class="invoices-header">
    <p class="header-description">{$text('settings.billing.invoices_description')}</p>
</div>

{#if isLoading}
    <div class="loading-state">
        <div class="loading-spinner"></div>
        <span>{$text('settings.billing.invoices_loading')}</span>
    </div>
{:else if errorMessage}
    <div class="error-message">{errorMessage}</div>
    <SettingsItem
        type="quickaction"
        icon="subsetting_icon reload"
        title={$text('common.retry')}
        onClick={fetchInvoices}
    />
{:else if invoices.length === 0}
    <div class="empty-state">
        <div class="empty-icon"></div>
        <h4>{$text('settings.billing.invoices_no_invoices_title')}</h4>
        <p>{$text('settings.billing.invoices_no_invoices_description')}</p>
    </div>
{:else}
    <!-- Invoices grouped by month -->
    {#each Object.entries(groupedInvoices) as [monthYear, monthInvoices]}
        <div class="month-group">
            <h4 class="month-header">{monthYear}</h4>

            {#each monthInvoices as invoice}
                <div class="invoice-item" data-testid="invoice-item">
                    <div class="invoice-info">
                        <div class="invoice-header">
                            <div class="invoice-date" data-testid="invoice-date">
                                {formatDate(invoice.date)}
                            </div>
                            {#if invoice.is_gift_card}
                                <span class="gift-card-badge">
                                    {$text('settings.billing.invoices_gift_card_badge')}
                                </span>
                            {/if}
                        </div>
                        <div class="invoice-details">
                            <span class="invoice-amount">{formatAmount(invoice.amount, invoice.currency)}</span>
                            <span class="invoice-credits">
                                {formatCredits(invoice.credits_purchased)} {$text('common.credits')}
                            </span>
                        </div>
                    </div>

                    <div class="invoice-actions">
                        {#if isInvoiceRefunded(invoice)}
                            <!-- When refunded, show Download Invoice and Download Credit Note buttons -->
                            <button
                                class="download-button"
                                onclick={() => downloadInvoice(invoice)}
                                title={$text('settings.billing.invoices_download_invoice')}
                            >
                                <div class="download-icon"></div>
                                <span>{$text('settings.billing.invoices_download_invoice')}</span>
                            </button>
                            {#if creditNoteReadyInvoices.has(invoice.id)}
                                <!-- Only show download button when credit note PDF is ready -->
                                <button
                                    class="download-button"
                                    onclick={() => downloadCreditNote(invoice)}
                                    title={$text('settings.billing.invoices_download_credit_note')}
                                >
                                    <div class="download-icon"></div>
                                    <span>{$text('settings.billing.invoices_download_credit_note')}</span>
                                </button>
                            {:else}
                                <!-- Show loading state while credit note PDF is being generated -->
                                <button
                                    class="download-button"
                                    disabled
                                    title={$text('settings.billing.invoices_credit_note_generating')}
                                >
                                    <div class="loading-spinner-small"></div>
                                    <span>{$text('settings.billing.invoices_credit_note_generating')}</span>
                                </button>
                            {/if}
                        {:else}
                            <!-- When not refunded, show Download (or Processing) and Refund buttons -->
                            {#if !invoice.filename}
                                <!-- Invoice PDF is still being generated (optimistic/pending invoice) -->
                                <button
                                    class="download-button processing"
                                    disabled
                                    title={$text('settings.billing.invoices_generating')}
                                >
                                    <div class="loading-spinner-small"></div>
                                    <span>{$text('settings.billing.invoices_generating')}</span>
                                </button>
                            {:else}
                                <button
                                    class="download-button"
                                    onclick={() => downloadInvoice(invoice)}
                                    title={$text('settings.billing.invoices_download_invoice')}
                                >
                                    <div class="download-icon"></div>
                                    <span>{$text('common.download')}</span>
                                </button>
                            {/if}
                            {#if isInvoiceEligibleForRefund(invoice)}
                                <button
                                    class="refund-button"
                                    class:disabled={refundingInvoiceId === invoice.id}
                                    disabled={refundingInvoiceId === invoice.id}
                                    onclick={() => requestRefund(invoice)}
                                    title={$text('settings.billing.invoices_refund_tooltip')}
                                >
                                    {#if refundingInvoiceId === invoice.id}
                                        <div class="loading-spinner-small"></div>
                                        <span>{$text('settings.billing.invoices_refund_processing')}</span>
                                    {:else}
                                        <div class="refund-icon"></div>
                                        <span>{$text('settings.billing.invoices_refund')}</span>
                                    {/if}
                                </button>
                            {/if}
                        {/if}
                    </div>
                </div>
            {/each}
        </div>
    {/each}
{/if}
<style>

    .invoices-header {
        padding: var(--spacing-5);
        margin-bottom: var(--spacing-8);
        text-align: center;
    }

    .header-description {
        margin: 0;
        color: var(--color-grey-60);
        font-size: var(--font-size-small);
        line-height: 1.4;
    }

    .loading-state {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--spacing-6);
        padding: var(--spacing-20);
        color: var(--color-grey-60);
    }

    .loading-spinner {
        width: 20px;
        height: 20px;
        border: 2px solid var(--color-grey-20);
        border-top: 2px solid var(--color-accent);
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .error-message {
        background: rgba(223, 27, 65, 0.1);
        color: #df1b41;
        padding: var(--spacing-6);
        border-radius: var(--radius-3);
        font-size: var(--font-size-xs);
        border: 1px solid rgba(223, 27, 65, 0.3);
        margin-bottom: var(--spacing-8);
    }

    .empty-state {
        text-align: center;
        padding: var(--spacing-20) var(--spacing-10);
    }

    .empty-icon {
        width: 48px;
        height: 48px;
        margin: 0 auto 16px;
        background-image: url('@openmates/ui/static/icons/docs.svg');
        background-size: contain;
        background-repeat: no-repeat;
        opacity: 0.3;
        filter: invert(1);
    }

    .empty-state h4 {
        margin: 0 0 8px 0;
        color: var(--color-grey-100);
        font-size: var(--font-size-p);
        font-weight: 600;
    }

    .empty-state p {
        margin: 0;
        color: var(--color-grey-60);
        font-size: var(--font-size-small);
        line-height: 1.4;
    }

    .month-group {
        margin-bottom: var(--spacing-12);
    }

    .month-header {
        color: var(--color-grey-80);
        font-size: var(--font-size-p);
        font-weight: 600;
        margin: 0 0 12px 0;
        padding: 0 10px;
        border-bottom: 1px solid var(--color-grey-20);
        padding-bottom: var(--spacing-4);
    }

    .invoice-item {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: var(--spacing-6);
        padding: var(--spacing-8);
        margin-bottom: var(--spacing-4);
        background: var(--color-grey-10);
        border-radius: var(--radius-5);
        border: 1px solid var(--color-grey-20);
        transition: all var(--duration-normal) var(--easing-default);
    }

    .invoice-item:hover {
        background: var(--color-grey-15);
        border-color: var(--color-grey-30);
    }

    .invoice-info {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-3);
        flex: 1;
    }

    .invoice-header {
        display: flex;
        align-items: center;
        gap: var(--spacing-6);
        flex-wrap: wrap;
    }

    .invoice-date {
        color: var(--color-grey-100);
        font-size: 15px;
        font-weight: 500;
    }

    .gift-card-badge {
        display: inline-flex;
        align-items: center;
        padding: var(--spacing-2) var(--spacing-5);
        background: var(--color-accent);
        color: white;
        border-radius: var(--radius-5);
        font-size: var(--font-size-tiny);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .invoice-details {
        display: flex;
        gap: var(--spacing-8);
        align-items: center;
    }

    .invoice-amount {
        color: var(--color-grey-80);
        font-size: var(--font-size-small);
        font-weight: 600;
    }

    .invoice-credits {
        color: var(--color-grey-60);
        font-size: var(--font-size-xs);
    }

    .invoice-actions {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
        width: 100%;
    }

    .download-button {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
        padding: var(--spacing-4) var(--spacing-8);
        background: var(--color-accent);
        color: white;
        border: none;
        border-radius: var(--radius-3);
        font-size: var(--font-size-xs);
        font-weight: 500;
        cursor: pointer;
        transition: all var(--duration-normal) var(--easing-default);
    }

    .download-button:hover {
        background: var(--color-accent-hover);
        transform: translateY(-1px);
    }

    .download-icon {
        width: 16px;
        height: 16px;
        background-image: url('@openmates/ui/static/icons/download.svg');
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
    }

    .refund-button {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
        padding: var(--spacing-4) var(--spacing-8);
        background: var(--color-grey-20);
        color: var(--color-grey-100);
        border: 1px solid var(--color-grey-30);
        border-radius: var(--radius-3);
        font-size: var(--font-size-xs);
        font-weight: 500;
        cursor: pointer;
        transition: all var(--duration-normal) var(--easing-default);
    }

    .refund-button:hover:not(:disabled) {
        background: var(--color-grey-30);
        border-color: var(--color-grey-40);
        transform: translateY(-1px);
    }
    
    .refund-button:disabled,
    .refund-button.disabled {
        opacity: 0.6;
        cursor: not-allowed;
        pointer-events: none;
    }
    
    .refund-button:disabled:hover,
    .refund-button.disabled:hover {
        background: var(--color-grey-20);
        border-color: var(--color-grey-30);
        transform: none;
    }

    .refund-icon {
        width: 16px;
        height: 16px;
        background-image: url('@openmates/ui/static/icons/reload.svg');
        background-size: contain;
        background-repeat: no-repeat;
        filter: invert(1);
        transform: rotate(180deg); /* Rotate to make it look like a return/refund arrow */
    }
    
    .loading-spinner-small {
        width: 14px;
        height: 14px;
        border: 2px solid var(--color-grey-30);
        border-top: 2px solid var(--color-grey-100);
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    /* Responsive Styles */
    @media (max-width: 768px) {
        .invoice-actions {
            flex-wrap: wrap;
        }

        .download-button,
        .refund-button {
            flex: 1;
            min-width: 120px;
            justify-content: center;
        }
    }

    @media (max-width: 480px) {
        .invoice-item {
            padding: var(--spacing-6);
        }

        .invoice-details {
            flex-direction: column;
            align-items: flex-start;
            gap: var(--spacing-2);
        }
    }
</style>