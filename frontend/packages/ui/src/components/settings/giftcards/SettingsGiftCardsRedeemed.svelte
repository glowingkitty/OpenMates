<!--
Gift Cards Redeemed - View all gift cards redeemed by the user
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../../config/api';
    import SettingsItem from '../../SettingsItem.svelte';
    import { notificationStore } from '../../../stores/notificationStore';

    interface RedeemedGiftCard {
        gift_card_code: string;
        credits_value: number;
        redeemed_at: string;
    }

    let isLoading = $state(false);
    let errorMessage: string | null = $state(null);
    let redeemedCards: RedeemedGiftCard[] = $state([]);

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Format date for display
    function formatDate(dateStr: string): string {
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch {
            return dateStr;
        }
    }

    // Fetch redeemed gift cards from API
    async function fetchRedeemedCards() {
        isLoading = true;
        errorMessage = null;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.getRedeemedGiftCards), {
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch redeemed gift cards: ${response.statusText}`);
            }

            const data = await response.json();
            redeemedCards = data.redeemed_cards || [];
        } catch (error) {
            console.error('Error fetching redeemed gift cards:', error);
            errorMessage = $text('settings.gift_cards.error_fetch_failed');
            notificationStore.error(errorMessage);
        } finally {
            isLoading = false;
        }
    }

    onMount(() => {
        fetchRedeemedCards();
    });
</script>

{#if isLoading}
    <div class="loading-message">{$text('common.loading')}</div>
{:else if errorMessage}
    <div class="error-message">{errorMessage}</div>
    <button class="retry-button" onclick={fetchRedeemedCards}>
        {$text('common.retry')}
    </button>
{:else if redeemedCards.length === 0}
    <div class="empty-state">
        <p>{$text('settings.gift_cards.redeemed_empty')}</p>
    </div>
{:else}
    <!-- List of redeemed gift cards -->
    {#each redeemedCards as card}
        <SettingsItem
            type="nested"
            icon="subsetting_icon coins"
            title={card.gift_card_code}
            subtitle={`${formatCredits(card.credits_value)} ${$text('common.credits')} - ${formatDate(card.redeemed_at)}`}
        />
    {/each}
{/if}

<style>
    .loading-message,
    .error-message,
    .empty-state {
        padding: var(--spacing-10);
        text-align: center;
        color: var(--color-grey-60);
    }

    .error-message {
        color: #df1b41;
        background: rgba(223, 27, 65, 0.1);
        padding: var(--spacing-6);
        border-radius: var(--radius-3);
        margin-bottom: var(--spacing-6);
    }

    .retry-button {
        width: 100%;
        padding: var(--spacing-6);
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: var(--radius-3);
        cursor: pointer;
        font-size: var(--font-size-small);
    }

    .retry-button:hover {
        opacity: 0.9;
    }
</style>
