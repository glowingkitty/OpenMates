<!--
Invoices Settings - View and download past invoices
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../../config/api';
    import SettingsItem from '../../SettingsItem.svelte';
    import { notificationStore } from '../../../stores/notificationStore';

    // Invoice interface
    interface Invoice {
        id: string;
        date: string;
        amount: string;
        credits_purchased: number;
        filename: string;
        is_gift_card?: boolean;  // Whether this invoice is for a gift card purchase
    }

    let isLoading = $state(false);
    let errorMessage: string | null = $state(null);
    let invoices: Invoice[] = $state([]);

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

    // Format amount from cents to EUR (e.g., 200 -> "2.00 EUR")
    function formatAmount(amountStr: string): string {
        try {
            // Parse amount as number (it's stored as cents)
            const amountInCents = parseInt(amountStr, 10);
            if (isNaN(amountInCents)) {
                return amountStr; // Return as-is if parsing fails
            }
            // Convert cents to EUR and format with 2 decimal places
            const amountInEur = (amountInCents / 100).toFixed(2);
            return `${amountInEur} EUR`;
        } catch {
            return amountStr; // Return as-is if formatting fails
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
                } catch (e) {
                    // If JSON parsing fails, try to get text from original response
                    try {
                        errorDetail = await response.text();
                        console.error('Error response text:', errorDetail);
                    } catch (e2) {
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
            }
        } catch (error) {
            console.error('Error fetching invoices:', error);
            // Show more detailed error message
            if (error instanceof Error) {
                errorMessage = error.message;
            } else {
                errorMessage = $text('settings.billing.invoices_error_loading.text');
            }
        } finally {
            isLoading = false;
        }
    }

    // Download invoice
    async function downloadInvoice(invoice: Invoice) {
        try {
            notificationStore.info($text('settings.billing.invoices_downloading.text'));

            const downloadUrl = getApiEndpoint(
                apiEndpoints.payments.downloadInvoice.replace('{id}', invoice.id)
            );

            const response = await fetch(downloadUrl, {
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Failed to download invoice');
            }

            // Create blob and download
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = invoice.filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);

            notificationStore.success($text('settings.billing.invoices_download_success.text'));
        } catch (error) {
            console.error('Error downloading invoice:', error);
            notificationStore.error($text('settings.billing.invoices_download_error.text'));
        }
    }

    onMount(() => {
        fetchInvoices();
    });

    // Group invoices by month for display
    // Using $derived to reactively compute grouped invoices whenever invoices change
    const groupedInvoices = $derived(groupInvoicesByMonth(invoices));
</script>

<!-- TODO add info about how long invoices are kept before being automatically deleted (10 years?) -->
<!-- Header -->
<div class="invoices-header">
    <p class="header-description">{$text('settings.billing.invoices_description.text')}</p>
</div>

{#if isLoading}
    <div class="loading-state">
        <div class="loading-spinner"></div>
        <span>{$text('settings.billing.invoices_loading.text')}</span>
    </div>
{:else if errorMessage}
    <div class="error-message">{errorMessage}</div>
    <SettingsItem
        type="quickaction"
        icon="subsetting_icon subsetting_icon_reload"
        title={$text('retry.text')}
        onClick={fetchInvoices}
    />
{:else if invoices.length === 0}
    <div class="empty-state">
        <div class="empty-icon"></div>
        <h4>{$text('settings.billing.invoices_no_invoices_title.text')}</h4>
        <p>{$text('settings.billing.invoices_no_invoices_description.text')}</p>
    </div>
{:else}
    <!-- Invoices grouped by month -->
    {#each Object.entries(groupedInvoices) as [monthYear, monthInvoices]}
        <div class="month-group">
            <h4 class="month-header">{monthYear}</h4>

            {#each monthInvoices as invoice}
                <div class="invoice-item">
                    <div class="invoice-info">
                        <div class="invoice-header">
                            <div class="invoice-date">
                                {formatDate(invoice.date)}
                            </div>
                            {#if invoice.is_gift_card}
                                <span class="gift-card-badge">
                                    {$text('settings.billing.invoices_gift_card_badge.text')}
                                </span>
                            {/if}
                        </div>
                        <div class="invoice-details">
                            <span class="invoice-amount">{formatAmount(invoice.amount)}</span>
                            <span class="invoice-credits">
                                {formatCredits(invoice.credits_purchased)} {$text('settings.billing.credits.text')}
                            </span>
                        </div>
                    </div>

                    <div class="invoice-actions">
                        <button
                            class="download-button"
                            onclick={() => downloadInvoice(invoice)}
                            title={$text('settings.billing.invoices_download_invoice.text')}
                        >
                            <div class="download-icon"></div>
                            <span>{$text('settings.billing.invoices_download.text')}</span>
                        </button>
                    </div>
                </div>
            {/each}
        </div>
    {/each}
{/if}
<style>

    .invoices-header {
        padding: 10px;
        margin-bottom: 16px;
        text-align: center;
    }

    .header-description {
        margin: 0;
        color: var(--color-grey-60);
        font-size: 14px;
        line-height: 1.4;
    }

    .loading-state {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
        padding: 40px;
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
        padding: 12px;
        border-radius: 8px;
        font-size: 13px;
        border: 1px solid rgba(223, 27, 65, 0.3);
        margin-bottom: 16px;
    }

    .empty-state {
        text-align: center;
        padding: 40px 20px;
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
        font-size: 16px;
        font-weight: 600;
    }

    .empty-state p {
        margin: 0;
        color: var(--color-grey-60);
        font-size: 14px;
        line-height: 1.4;
    }

    .month-group {
        margin-bottom: 24px;
    }

    .month-header {
        color: var(--color-grey-80);
        font-size: 16px;
        font-weight: 600;
        margin: 0 0 12px 0;
        padding: 0 10px;
        border-bottom: 1px solid var(--color-grey-20);
        padding-bottom: 8px;
    }

    .invoice-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px;
        margin-bottom: 8px;
        background: var(--color-grey-10);
        border-radius: 12px;
        border: 1px solid var(--color-grey-20);
        transition: all 0.2s ease;
    }

    .invoice-item:hover {
        background: var(--color-grey-15);
        border-color: var(--color-grey-30);
    }

    .invoice-info {
        display: flex;
        flex-direction: column;
        gap: 6px;
        flex: 1;
    }

    .invoice-header {
        display: flex;
        align-items: center;
        gap: 12px;
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
        padding: 4px 10px;
        background: var(--color-accent);
        color: white;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .invoice-details {
        display: flex;
        gap: 16px;
        align-items: center;
    }

    .invoice-amount {
        color: var(--color-grey-80);
        font-size: 14px;
        font-weight: 600;
    }

    .invoice-credits {
        color: var(--color-grey-60);
        font-size: 13px;
    }

    .invoice-actions {
        display: flex;
        align-items: center;
    }

    .download-button {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 16px;
        background: var(--color-accent);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
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

    /* Responsive Styles */
    @media (max-width: 768px) {
        .invoice-item {
            flex-direction: column;
            align-items: flex-start;
            gap: 12px;
        }

        .invoice-actions {
            width: 100%;
        }

        .download-button {
            width: 100%;
            justify-content: center;
        }

        .invoice-details {
            flex-wrap: wrap;
        }
    }

    @media (max-width: 480px) {
        .invoice-item {
            padding: 12px;
        }

        .invoice-details {
            flex-direction: column;
            align-items: flex-start;
            gap: 4px;
        }
    }
</style>