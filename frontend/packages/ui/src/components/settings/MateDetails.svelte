<!-- frontend/packages/ui/src/components/settings/MateDetails.svelte
     Detail view for a single AI mate, rendered inside the settings panel.

     Layout (mirrors FocusModeDetails.svelte pattern):
     - The mate profile image + name header is rendered by Settings.svelte
       (submenu-info block), not here. This component renders only the body.
     - Description section: plain text.
     - Instructions section: bullet-point summary from process_translation_key,
       plus a collapsible "Show full system prompt" button.
     - "Chat with this mate" CTA button: inserts "@mate:{mateId}" into the
       message input via pendingMentionStore and closes the settings panel.

     Data source: static matesMetadata.ts — no store or API call needed.
     Navigation: dispatches 'openSettings' events for back-navigation.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { matesMetadata } from '../../data/matesMetadata';
    import { pendingMentionStore } from '../../stores/pendingMentionStore';
    import { panelState } from '../../stores/panelStateStore';
    import SettingsItem from '../SettingsItem.svelte';
    import { SettingsSectionHeading } from './elements';

    // Event dispatcher for Settings.svelte navigation
    const dispatch = createEventDispatcher();

    interface Props {
        mateId: string;
    }

    let { mateId }: Props = $props();

    // Look up this mate from the static metadata list
    let mate = $derived(matesMetadata.find(m => m.id === mateId));

    // Translated strings derived from metadata keys
    let mateDescription = $derived(
        mate?.description_translation_key
            ? $text(mate.description_translation_key)
            : ''
    );

    /**
     * Full system prompt for this mate, resolved from the translation key.
     * Shown/hidden via the "Show full system prompt" toggle.
     */
    let mateSystemPrompt = $derived(
        mate?.system_prompt_translation_key
            ? $text(mate.system_prompt_translation_key)
            : ''
    );

    /**
     * Bullet-point process summary from process_translation_key.
     * Each line starting with "- " becomes one bullet.
     */
    let mateProcess = $derived(
        mate?.process_translation_key
            ? $text(mate.process_translation_key)
            : ''
    );

    /**
     * Parse process text into individual bullet strings.
     */
    let processBullets = $derived(
        mateProcess
            ? mateProcess
                .split('\n')
                .map((line: string) => line.trim())
                .filter((line: string) => line.startsWith('- '))
                .map((line: string) => line.slice(2).trim())
            : []
    );

    /** Whether there is any instruction content to show. */
    let hasInstructions = $derived(
        processBullets.length > 0 || mateSystemPrompt.length > 0
    );

    /** Controls visibility of the full system prompt block. */
    let showFullPrompt = $state(false);

    /** Display name for the mate (resolved from translation). */
    let mateName = $derived(
        mate?.name_translation_key ? $text(mate.name_translation_key) : mateId
    );

    /**
     * Navigate back to the mates list.
     */
    function goBack() {
        dispatch('openSettings', {
            settingsPath: 'mates',
            direction: 'back',
            icon: 'mates',
            title: $text('settings.mates'),
        });
    }

    /**
     * Insert "@mate:{mateId}" into the message input and close settings.
     * The pendingMentionStore is watched by MessageInput.svelte which will
     * pick up the value and insert it into the TipTap editor.
     */
    function chatWithMate() {
        pendingMentionStore.set(`@mate:${mateId}`);
        panelState.closeSettings();
    }
</script>

<div class="mate-details">
    {#if !mate}
        <div class="error">
            <p>{$text('settings.mates.mate_not_found')}</p>
            <button class="back-button" onclick={goBack}>
                ← {$text('settings.mates')}
            </button>
        </div>
    {:else}
        <!-- Description section -->
        {#if mateDescription}
            <div class="description-section">
                <p class="mate-description">{mateDescription}</p>
            </div>
        {:else}
            <div class="description-section">
                <p class="mate-description no-description">
                    {$text('settings.mates.no_description')}
                </p>
            </div>
        {/if}

        <!-- Instructions section: process bullets + collapsible system prompt -->
        <div class="section">
            <SettingsSectionHeading title={$text('settings.mates.system_prompt_heading')} icon="ai" />
            {#if hasInstructions}
                <!-- Bullet-point summary from process_translation_key -->
                {#if processBullets.length > 0}
                    <ul class="process-bullets">
                        {#each processBullets as bullet}
                            <li class="process-bullet">{bullet}</li>
                        {/each}
                    </ul>
                {/if}

                <!-- Full system prompt: hidden by default, revealed on toggle -->
                {#if mateSystemPrompt}
                    {#if showFullPrompt}
                        <div class="instructions-block">
                            <svg
                                class="quote-icon"
                                width="20"
                                height="20"
                                viewBox="0 0 48 48"
                                fill="none"
                                xmlns="http://www.w3.org/2000/svg"
                            >
                                <path
                                    d="M15 3a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.717-3.35 3 3 0 012.259-2.47C11.952 37.416 15 33.606 15 26.998v-3H6a6 6 0 01-5.985-5.549L0 17.998V9A5.999 5.999 0 016 3h9zm27 0a6 6 0 016 6v17.997c0 9.389-4.95 15.577-14.271 17.908a3.001 3.001 0 01-3.716-3.35 2.998 2.998 0 012.258-2.47C38.952 37.416 42 33.606 42 26.998v-3h-9a6 6 0 01-5.985-5.549l-.015-.45V9A5.999 5.999 0 0133 3h9z"
                                    fill="currentColor"
                                />
                            </svg>
                            <pre class="instructions-text">{mateSystemPrompt}</pre>
                        </div>
                    {/if}
                    <button
                        type="button"
                        class="instructions-toggle"
                        onclick={() => (showFullPrompt = !showFullPrompt)}
                    >
                        {showFullPrompt
                            ? $text('settings.mates.hide_full_prompt')
                            : $text('settings.mates.show_full_prompt')}
                    </button>
                {/if}
            {:else}
                <div class="no-instructions">
                    <p>{$text('settings.mates.no_description')}</p>
                </div>
            {/if}
        </div>

        <!-- "Chat with this mate" CTA -->
        <div class="cta-section">
            <button type="button" class="chat-cta-button" onclick={chatWithMate}>
                {$text('settings.mates.chat_with_mate').replace('{mate_name}', mateName)}
            </button>
        </div>
    {/if}
</div>

<style>
    .mate-details {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }

    /* Description section — matches FocusModeDetails */
    .description-section {
        margin-bottom: 2rem;
        padding-left: 0;
    }

    .mate-description {
        margin: 0;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
        text-align: left;
    }

    .mate-description.no-description {
        color: var(--color-grey-60);
        font-style: italic;
    }

    .section {
        margin-top: 2rem;
    }

    /* Bullet-point process summary list — matches FocusModeDetails */
    .process-bullets {
        margin: 0.75rem 0 0 10px;
        padding: 0 0 0 1.25rem;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
    }

    .process-bullet {
        position: relative;
        padding-left: 1.25rem;
        font-size: 0.95rem;
        line-height: 1.5;
        color: var(--color-grey-100);
    }

    .process-bullet::before {
        content: '•';
        position: absolute;
        left: 0;
        color: var(--color-primary-start, #5856d6);
        font-weight: 700;
        font-size: 1rem;
        line-height: 1.5;
    }

    /* System prompt block — quote-style, matching FocusModeDetails */
    .instructions-block {
        position: relative;
        margin-top: 0.75rem;
        padding: 1rem 1.25rem 1rem 2.5rem;
        background: var(--color-grey-10, #f5f5f5);
        border-radius: 12px;
        border: 1px solid var(--color-grey-20);
    }

    .quote-icon {
        position: absolute;
        top: 10px;
        left: 12px;
        width: 20px;
        height: 20px;
        color: var(--color-grey-50);
        opacity: 0.6;
        pointer-events: none;
    }

    .instructions-text {
        margin: 0;
        padding: 0;
        font-size: 0.9rem;
        line-height: 1.5;
        white-space: pre-wrap;
        word-break: break-word;
        color: var(--color-grey-100);
        overflow-x: auto;
    }

    /* Toggle button for showing/hiding the full system prompt */
    .instructions-toggle {
        display: block;
        margin-top: 0.75rem;
        margin-left: 10px;
        padding: 0.35rem 0.6rem;
        font-size: 0.875rem;
        color: var(--color-primary, #0066cc);
        background: transparent;
        border: none;
        cursor: pointer;
        border-radius: 4px;
        font-weight: 500;
    }

    .instructions-toggle:hover {
        text-decoration: underline;
    }

    .no-instructions {
        padding: 1.25rem 0 0 10px;
        color: var(--color-grey-60);
        font-size: 0.95rem;
    }

    .no-instructions p {
        margin: 0;
    }

    /* "Chat with this mate" CTA button */
    .cta-section {
        margin-top: 2.5rem;
        padding-bottom: 2rem;
    }

    .chat-cta-button {
        display: block;
        width: 100%;
        padding: 0.75rem 1.25rem;
        font-size: 1rem;
        font-weight: 600;
        color: #ffffff;
        background: linear-gradient(
            135deg,
            var(--color-primary-start, #5856d6),
            var(--color-primary-end, #a78bfa)
        );
        border: none;
        border-radius: 12px;
        cursor: pointer;
        text-align: center;
        transition: opacity 0.15s ease, transform 0.1s ease;
    }

    .chat-cta-button:hover {
        opacity: 0.9;
    }

    .chat-cta-button:active {
        transform: scale(0.98);
    }

    /* Error state */
    .error {
        padding: 3rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }

    .back-button {
        background: var(--button-background, #f0f0f0);
        border: 1px solid var(--border-color, #e0e0e0);
        border-radius: 6px;
        padding: 0.5rem 1rem;
        margin-top: 1rem;
        cursor: pointer;
        font-size: 0.9rem;
        color: var(--text-primary, #000000);
        transition: background 0.2s ease;
    }

    .back-button:hover {
        background: var(--button-hover-background, #e0e0e0);
    }
</style>
