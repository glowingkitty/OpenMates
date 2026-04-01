<!--
    SettingsFork Component

    Settings panel view for the "Fork Conversation" feature.

    This component allows the user to:
    - Enter a name for the forked chat (pre-filled with source chat title)
    - See how many messages will be included in the fork
    - Start the fork operation (which runs in the background via forkChatService)
    - See live progress while the fork is running

    The fork is disabled for incognito chats.

    Context is passed via window.__forkContext (same pattern as __embedShareContext):
        { sourceChatId: string, upToMessageId: string, defaultTitle: string, messageCount: number }

    The fork runs entirely client-side (zero-knowledge) — see forkChatService.ts.
-->
<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount, createEventDispatcher } from 'svelte';
    import { settingsDeepLink } from '../../../stores/settingsDeepLinkStore';
    import { startFork } from '../../../services/forkChatService';
    import { forkProgressStore, isForkRunning } from '../../../stores/forkProgressStore';

    const dispatch = createEventDispatcher();

    // ---------------------------------------------------------------------------
    // Props
    // ---------------------------------------------------------------------------

    let {
        activeSettingsView = 'fork'
    }: {
        activeSettingsView?: string;
    } = $props();

    // ---------------------------------------------------------------------------
    // Fork context (passed via window.__forkContext from ChatMessage.svelte)
    // ---------------------------------------------------------------------------

    interface ForkContext {
        sourceChatId: string;
        upToMessageId: string;
        defaultTitle: string;
        /** Number of messages that will be included (up to and including the selected one). */
        messageCount: number;
    }

    interface ForkWindow extends Window {
        __forkContext?: ForkContext | null;
    }

    let forkContext = $state<ForkContext | null>(null);

    // ---------------------------------------------------------------------------
    // State
    // ---------------------------------------------------------------------------

    /** Editable fork name — pre-filled from context. */
    let forkName = $state('');

    /** Whether we've already started the fork (to prevent double-clicks). */
    let started = $state(false);

    // Live progress from the global store
    let forkState = $derived($forkProgressStore);
    let isRunning = $derived($isForkRunning);

    // ---------------------------------------------------------------------------
    // Lifecycle — load context when the view becomes active
    // ---------------------------------------------------------------------------

    $effect(() => {
        // Re-check context whenever this view becomes active or deepLink changes
        const deepLink = $settingsDeepLink;
        const isActive = activeSettingsView === 'fork';

        if (deepLink === 'fork' || isActive) {
            const ctx = (window as ForkWindow).__forkContext;
            if (ctx && ctx.sourceChatId) {
                forkContext = ctx;
                forkName = ctx.defaultTitle;
                // Clear the global context after reading (same pattern as embedShareContext)
                (window as ForkWindow).__forkContext = null;
                console.debug('[SettingsFork] Fork context loaded:', forkContext);
            }
        }
    });

    onMount(() => {
        // Also check on mount in case context was set before component mounted
        const ctx = (window as ForkWindow).__forkContext;
        if (ctx && ctx.sourceChatId) {
            forkContext = ctx;
            forkName = ctx.defaultTitle;
            (window as ForkWindow).__forkContext = null;
            console.debug('[SettingsFork] Fork context loaded on mount:', forkContext);
        }

        // If a fork is already running for this context, reflect that in UI
        const current = forkProgressStore.getSnapshot();
        if (current.status === 'running' || current.status === 'complete') {
            started = true;
        }
    });

    // ---------------------------------------------------------------------------
    // Auto-navigate back when fork completes
    // When the fork finishes successfully, close the fork panel so the user
    // is not left stuck in it. We navigate back to the main settings menu
    // (same pattern as SettingsServer.svelte / SettingsInterface.svelte).
    // ---------------------------------------------------------------------------

    $effect(() => {
        if (forkState.status === 'complete' && started) {
            // Small delay so the user sees "100%" for a moment before the panel closes
            setTimeout(() => {
                dispatch('navigateBack');
            }, 800);
        }
    });

    // ---------------------------------------------------------------------------
    // Actions
    // ---------------------------------------------------------------------------

    async function handleFork() {
        if (!forkContext || started || isRunning) return;
        if (!forkName.trim()) return;

        started = true;
        console.debug('[SettingsFork] Starting fork:', forkContext.sourceChatId, forkContext.upToMessageId);

        try {
            await startFork(
                forkContext.sourceChatId,
                forkContext.upToMessageId,
                forkName.trim(),
            );
        } catch (err) {
            console.error('[SettingsFork] Fork failed to start:', err);
            // Allow retrying if fork failed to even start
            started = false;
        }
    }

    // ---------------------------------------------------------------------------
    // Derived helpers
    // ---------------------------------------------------------------------------

    /** True when fork is running AND belongs to the current context. */
    let isForkingThisChat = $derived(
        forkContext !== null &&
        forkState.status === 'running' &&
        forkState.sourceChatId === forkContext.sourceChatId,
    );

    let progressPercent = $derived(forkState.progress);
    let messageCount = $derived(forkContext?.messageCount ?? 0);
</script>

<div class="fork-container" data-testid="fork-container">
    {#if forkContext}
        <!-- Name input -->
        <div class="fork-field">
            <label class="fork-label" for="fork-name">
                {$text('chats.fork.name_label')}
            </label>
            <input
                id="fork-name"
                class="fork-input"
                data-testid="fork-input"
                type="text"
                bind:value={forkName}
                placeholder={$text('chats.fork.name_placeholder')}
                disabled={started || isRunning}
                maxlength={120}
            />
        </div>

        <!-- Message count info -->
        <div class="fork-meta">
            <span class="fork-meta-count">{messageCount}</span>
            <span class="fork-meta-label">{$text('chats.fork.messages_label')}</span>
        </div>

        <!-- Progress bar — visible while running -->
        {#if isForkingThisChat}
            <div class="fork-progress-wrapper">
                <div class="fork-progress-bar">
                    <div class="fork-progress-fill" style="width: {progressPercent}%"></div>
                </div>
                <span class="fork-progress-text">
                    {$text('chats.fork.forking_progress', { progress: progressPercent })}
                </span>
            </div>
        {/if}

        <!-- Fork button -->
        {#if !isForkingThisChat}
            <button
                class="fork-button"
                data-testid="fork-button"
                onclick={handleFork}
                disabled={started || isRunning || !forkName.trim()}
            >
                {$text('chats.fork.fork_button')}
            </button>
        {/if}
    {:else}
        <!-- No context: stale open or arrived without a message selected -->
        <p class="fork-no-context">
            {$text('chats.fork.fork_button')}
        </p>
    {/if}
</div>

<style>
    .fork-container {
        display: flex;
        flex-direction: column;
        gap: 20px;
        padding: 20px 16px 32px;
    }

    /* ---- Name field ---- */
    .fork-field {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .fork-label {
        font-size: 13px;
        font-weight: 500;
        color: var(--color-text-secondary, #8a9bb0);
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .fork-input {
        width: 100%;
        box-sizing: border-box;
        background: var(--color-input-bg, rgba(255, 255, 255, 0.06));
        border: 1px solid var(--color-border, rgba(255, 255, 255, 0.12));
        border-radius: 10px;
        color: var(--color-text-primary, #ffffff);
        font-size: 15px;
        padding: 12px 14px;
        transition: border-color 0.2s ease;
    }

    .fork-input:focus {
        border-color: var(--color-primary, #4f8ef7);
    }

    .fork-input:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    /* ---- Meta info (message count) ---- */
    .fork-meta {
        display: flex;
        align-items: center;
        gap: 6px;
        color: var(--color-text-secondary, #8a9bb0);
        font-size: 13px;
    }

    .fork-meta-count {
        font-weight: 600;
        color: var(--color-text-primary, #ffffff);
    }

    /* ---- Progress bar ---- */
    .fork-progress-wrapper {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .fork-progress-bar {
        height: 6px;
        background: var(--color-border, rgba(255, 255, 255, 0.12));
        border-radius: 3px;
        overflow: hidden;
    }

    .fork-progress-fill {
        height: 100%;
        background: var(--color-primary, #4f8ef7);
        border-radius: 3px;
        transition: width 0.3s ease;
    }

    .fork-progress-text {
        font-size: 13px;
        color: var(--color-text-secondary, #8a9bb0);
    }

    /* ---- Fork button ---- */
    .fork-button {
        all: unset;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--color-primary, #4f8ef7);
        color: white;
        border-radius: 10px;
        font-size: 15px;
        font-weight: 500;
        padding: 14px 20px;
        cursor: pointer;
        transition: opacity 0.2s ease;
        text-align: center;
    }

    .fork-button:hover:not(:disabled) {
        opacity: 0.9;
    }

    .fork-button:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }

    /* ---- No context placeholder ---- */
    .fork-no-context {
        color: var(--color-text-secondary, #8a9bb0);
        font-size: 14px;
        text-align: center;
        padding: 32px 0;
    }
</style>
