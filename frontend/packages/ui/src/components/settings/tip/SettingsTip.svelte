<!--
    SettingsTip Component
    
    This component provides the UI for tipping creators (video creators or website owners).
    Features:
    - Slider for tip amount (50-20000 credits)
    - Tip creator button
    - Shows current credit balance
    - Success/error notifications
    
    The tip creates a creator_income entry that will be available for the creator
    to claim when they sign up for a creator account.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher, onMount } from 'svelte';
    import { notificationStore } from '../../../stores/notificationStore';
    import { userProfile } from '../../../stores/userProfile';
    import { tipStore } from '../../../stores/tipStore';
    import { get } from 'svelte/store';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    
    // Event dispatcher for navigation
    const dispatch = createEventDispatcher();
    
    // Props
    let { 
        activeSettingsView = 'tip'
    }: {
        activeSettingsView?: string;
    } = $props();
    
    // State variables
    let tipAmount = $state(100);  // Default tip amount (credits)
    let isTipping = $state(false);
    let ownerId = $state<string | undefined>(undefined);
    let contentType = $state<'video' | 'website'>('video');
    let videoUrl = $state<string | undefined>(undefined);
    // TODO: Re-enable when preview server is implemented
    // let isLoadingChannelId = $state(false);
    let currentCredits = $derived(get(userProfile).credits || 0);
    
    // Get tip data from store
    let tipData = $derived($tipStore);
    
    // Tip amount slider configuration
    const MIN_TIP = 50;
    const MAX_TIP = 20000;
    const STEP = 50;
    
    // Format credits for display
    function formatCredits(credits: number): string {
        return credits.toLocaleString();
    }
    
    // NOTE: Channel ID will be provided by the embed data once the preview server is implemented.
    // The preview server will auto-replace YouTube URLs with proper metadata including channel IDs.
    // For now, channel ID must be provided directly via tipStore.setTipData({ ownerId: channelId, ... })
    
    /**
     * Send tip to creator
     * Creates a creator_income entry with the tip amount
     */
    async function sendTip() {
        if (!ownerId || tipAmount < MIN_TIP || tipAmount > MAX_TIP) {
            notificationStore.error('Invalid tip amount or missing creator information');
            return;
        }
        
        if (currentCredits < tipAmount) {
            notificationStore.error(`Insufficient credits. You have ${formatCredits(currentCredits)} credits, but trying to tip ${formatCredits(tipAmount)}.`);
            return;
        }
        
        if (isTipping) {
            return; // Prevent double submission
        }
        
        try {
            isTipping = true;
            
            console.debug('[SettingsTip] Sending tip:', {
                ownerId,
                contentType,
                tipAmount
            });
            
            const response = await fetch(getApiEndpoint(apiEndpoints.creators.tip), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify({
                    owner_id: ownerId,
                    content_type: contentType,
                    credits: tipAmount
                }),
                credentials: 'include'
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
                notificationStore.error(errorData.detail || 'Failed to send tip. Please try again.');
                return;
            }
            
            const data = await response.json();
            
            if (data.success) {
                notificationStore.success(`Successfully tipped ${formatCredits(tipAmount)} credits to creator!`);
                
                // Update user profile credits
                const profile = get(userProfile);
                userProfile.set({
                    ...profile,
                    credits: data.current_credits || (currentCredits - tipAmount)
                });
                
                // Close the tip dialog after a short delay
                setTimeout(() => {
                    dispatch('close');
                }, 1500);
            } else {
                notificationStore.error(data.message || 'Failed to send tip. Please try again.');
            }
        } catch (error) {
            console.error('[SettingsTip] Error sending tip:', error);
            notificationStore.error('Network error. Please check your connection and try again.');
        } finally {
            isTipping = false;
        }
    }
    
    // Update from tip store
    $effect(() => {
        if (tipData.ownerId) {
            ownerId = tipData.ownerId;
        }
        if (tipData.contentType) {
            contentType = tipData.contentType;
        }
        if (tipData.videoUrl) {
            videoUrl = tipData.videoUrl;
        }
    });
    
    // NOTE: Channel ID will be provided by the embed data once the preview server is implemented.
    // No need to fetch it - it will be available in the embed metadata.
</script>

<div class="settings-tip-container">
    <!-- Show message if ownerId is missing for videos -->
    {#if !ownerId && contentType === 'video'}
        <div class="info-message">
            <div class="info-icon">ℹ️</div>
            <p>
                {$text('settings.tip.channel_id_required.text', { 
                    default: 'Channel ID is required to tip video creators. This feature will be available once the preview server is implemented, which will automatically provide channel information from video URLs.' 
                })}
            </p>
        </div>
    {:else}
    
    <!-- Tip description -->
    <div class="tip-description">
        <p>{$text('settings.tip.description.text', { default: 'Tip the creator to support their work. 100% of your tip goes directly to the creator.' })}</p>
    </div>
    
    <!-- Tip amount section -->
    <div class="tip-amount-section">
        <h3 class="section-title">{$text('settings.tip.amount.text', { default: 'Tip Amount' })}</h3>
        
        <!-- Slider container -->
        <div class="slider-container">
            <input
                type="range"
                min={MIN_TIP}
                max={MAX_TIP}
                step={STEP}
                bind:value={tipAmount}
                class="tip-slider"
                aria-label="Tip amount slider"
            />
            
            <!-- Slider labels -->
            <div class="slider-labels">
                <span class="slider-label-min">{formatCredits(MIN_TIP)}</span>
                <span class="slider-label-max">{formatCredits(MAX_TIP)}</span>
            </div>
        </div>
        
        <!-- Current tip amount display -->
        <div class="tip-amount-display">
            <span class="tip-amount-value">{formatCredits(tipAmount)}</span>
            <span class="tip-amount-label">{$text('settings.tip.credits.text', { default: 'credits' })}</span>
        </div>
    </div>
    
    <!-- Current balance info -->
    <div class="balance-info">
        <div class="info-icon">💰</div>
        <p>
            {$text('settings.tip.current_balance.text', { default: 'Your balance' })}: 
            <strong>{formatCredits(currentCredits)}</strong> {$text('settings.tip.credits.text', { default: 'credits' })}
        </p>
    </div>
    
    <!-- Insufficient balance warning -->
    {#if currentCredits < tipAmount}
        <div class="insufficient-balance-warning">
            <div class="warning-icon">⚠️</div>
            <p>
                {$text('settings.tip.insufficient_balance.text', { 
                    default: 'Insufficient credits. You need {needed} more credits.',
                    values: { needed: formatCredits(tipAmount - currentCredits) }
                })}
            </p>
        </div>
    {/if}
    
    <!-- Tip creator button -->
    <button
        class="tip-creator-button"
        onclick={sendTip}
        disabled={isTipping || !ownerId || currentCredits < tipAmount || tipAmount < MIN_TIP || tipAmount > MAX_TIP}
    >
        {#if isTipping}
            {$text('settings.tip.tipping.text', { default: 'Sending tip...' })}
        {:else}
            {$text('settings.tip.tip_creator.text', { default: 'Tip Creator' })}
        {/if}
    </button>
    
    <!-- Info about tips -->
    <div class="tip-info">
        <div class="info-icon">ℹ️</div>
        <p>{$text('settings.tip.tip_info.text', { default: 'Tips are reserved for creators and can be claimed when they sign up for a creator account. Tips remain available for 6 months.' })}</p>
    </div>
    {/if}
</div>

<style>
    .settings-tip-container {
        padding: 0 10px;
        display: flex;
        flex-direction: column;
        gap: 20px;
    }
    
    /* Tip description */
    .tip-description {
        padding: 12px 16px;
        background-color: var(--color-grey-10);
        border-radius: 8px;
    }
    
    .tip-description p {
        font-size: 14px;
        color: var(--color-grey-80);
        margin: 0;
        line-height: 1.5;
    }
    
    /* Tip amount section */
    .tip-amount-section {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }
    
    .section-title {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-grey-100);
        margin: 0;
    }
    
    /* Slider container */
    .slider-container {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 12px 0;
    }
    
    .tip-slider {
        width: 100%;
        height: 8px;
        border-radius: 4px;
        background: var(--color-grey-20);
        outline: none;
        -webkit-appearance: none;
        appearance: none;
    }
    
    .tip-slider::-webkit-slider-thumb {
        -webkit-appearance: none;
        appearance: none;
        width: 20px;
        height: 20px;
        border-radius: 50%;
        background: var(--color-primary);
        cursor: pointer;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
    }
    
    .tip-slider::-moz-range-thumb {
        width: 20px;
        height: 20px;
        border-radius: 50%;
        background: var(--color-primary);
        cursor: pointer;
        border: none;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
    }
    
    .slider-labels {
        display: flex;
        justify-content: space-between;
        font-size: 12px;
        color: var(--color-grey-60);
    }
    
    /* Tip amount display */
    .tip-amount-display {
        display: flex;
        align-items: baseline;
        justify-content: center;
        gap: 8px;
        padding: 16px;
        background-color: var(--color-grey-5);
        border-radius: 8px;
        border: 2px solid var(--color-primary);
    }
    
    .tip-amount-value {
        font-size: 32px;
        font-weight: 700;
        color: var(--color-primary);
    }
    
    .tip-amount-label {
        font-size: 16px;
        color: var(--color-grey-70);
    }
    
    /* Balance info */
    .balance-info {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 16px;
        background-color: var(--color-grey-5);
        border-radius: 8px;
        border: 1px solid var(--color-grey-20);
    }
    
    .info-icon {
        font-size: 16px;
        line-height: 1;
    }
    
    .balance-info p {
        font-size: 13px;
        color: var(--color-grey-80);
        margin: 0;
        line-height: 1.4;
    }
    
    .balance-info strong {
        color: var(--color-grey-100);
        font-weight: 600;
    }
    
    /* Insufficient balance warning */
    .insufficient-balance-warning {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 16px;
        background-color: var(--color-warning-light, #fef3c7);
        border: 1px solid var(--color-warning, #f59e0b);
        border-radius: 8px;
    }
    
    .warning-icon {
        font-size: 16px;
        line-height: 1;
    }
    
    .insufficient-balance-warning p {
        font-size: 13px;
        color: var(--color-warning-dark, #92400e);
        margin: 0;
        line-height: 1.4;
    }
    
    /* Tip creator button */
    .tip-creator-button {
        width: 100%;
        padding: 14px 20px;
        background-color: var(--color-primary);
        color: white;
        border: none;
        border-radius: 10px;
        font-size: 15px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    
    .tip-creator-button:hover:not(:disabled) {
        background-color: var(--color-primary-dark, #5a36b2);
        transform: translateY(-1px);
    }
    
    .tip-creator-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    /* Tip info */
    .tip-info {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 16px;
        background-color: var(--color-grey-5);
        border-radius: 8px;
        border: 1px solid var(--color-grey-20);
    }
    
    .tip-info p {
        font-size: 12px;
        color: var(--color-grey-70);
        margin: 0;
        line-height: 1.4;
    }
    
    /* Info message for missing channel ID */
    .info-message {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 16px;
        background-color: var(--color-grey-5);
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
        margin-bottom: 16px;
    }
    
    .info-message .info-icon {
        font-size: 16px;
        line-height: 1;
        flex-shrink: 0;
    }
    
    .info-message p {
        font-size: 13px;
        color: var(--color-grey-70);
        margin: 0;
        line-height: 1.4;
    }
</style>
