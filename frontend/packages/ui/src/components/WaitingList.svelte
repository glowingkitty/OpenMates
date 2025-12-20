<script lang="ts">
    import InstagramButton from './InstagramButton.svelte';
    import MastodonButton from './MastodonButton.svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../config/api';
    import { fade } from 'svelte/transition';

    // Props using Svelte 5 runes mode
    let { showPersonalInviteMessage = false }: { showPersonalInviteMessage?: boolean } = $props();

    // Newsletter signup state
    let newsletterEmail = $state('');
    let isSubscribing = $state(false);
    let subscribeSuccess = $state(false);
    let subscribeError = $state<string | null>(null);
    let showNewsletterForm = $state(true);

    // Get user language from browser or default to 'en'
    function getUserLanguage(): string {
        if (typeof window !== 'undefined' && window.navigator) {
            return window.navigator.language.split('-')[0] || 'en';
        }
        return 'en';
    }

    async function handleNewsletterSubscribe() {
        if (!newsletterEmail || !newsletterEmail.includes('@')) {
            subscribeError = $text('newsletter.invalid_email.text');
            return;
        }

        isSubscribing = true;
        subscribeError = null;
        subscribeSuccess = false;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.newsletter.subscribe), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Origin': window.location.origin
                },
                credentials: 'include',
                body: JSON.stringify({
                    email: newsletterEmail.toLowerCase().trim(),
                    language: getUserLanguage()
                })
            });

            const result = await response.json();

            if (response.ok && result.success) {
                subscribeSuccess = true;
                newsletterEmail = '';
                // Hide form after 3 seconds
                setTimeout(() => {
                    showNewsletterForm = false;
                }, 3000);
            } else {
                subscribeError = result.message || $text('newsletter.subscribe_error.text');
            }
        } catch (error) {
            console.error('Newsletter subscription error:', error);
            subscribeError = $text('newsletter.subscribe_error.text');
        } finally {
            isSubscribing = false;
        }
    }
</script>

<div class="waiting-list-section">
    <div class="content-wrapper">
        <div class="discord-content">
            <p class="discord-text">
                {#if showPersonalInviteMessage}
                <mark><bold>{$text('signup.dont_have_personal_invite_code.text')}</bold></mark><br>
                {/if}
                {@html $text('signup.follow_us.text')}
            </p>
            <InstagramButton />
            <MastodonButton />
        </div>
    </div>

    <!-- Newsletter Signup Form -->
    {#if showNewsletterForm}
    <div class="newsletter-section" transition:fade>
        <div class="newsletter-content">
            <p class="newsletter-text">
                {$text('newsletter.subscribe_text.text')}
            </p>
            
            {#if subscribeSuccess}
                <div class="newsletter-success" transition:fade>
                    {$text('newsletter.subscribe_success.text')}
                </div>
            {:else}
                <form class="newsletter-form" onsubmit={(e) => { e.preventDefault(); handleNewsletterSubscribe(); }}>
                    <div class="newsletter-input-group">
                        <input
                            type="email"
                            bind:value={newsletterEmail}
                            placeholder={$text('newsletter.email_placeholder.text')}
                            disabled={isSubscribing}
                            class="newsletter-input"
                            required
                        />
                        <button
                            type="submit"
                            disabled={isSubscribing || !newsletterEmail}
                            class="newsletter-button"
                            class:loading={isSubscribing}
                        >
                            {isSubscribing ? $text('newsletter.subscribing.text') : $text('newsletter.subscribe_button.text')}
                        </button>
                    </div>
                    {#if subscribeError}
                        <div class="newsletter-error" transition:fade>
                            {subscribeError}
                        </div>
                    {/if}
                </form>
            {/if}
        </div>
    </div>
    {/if}
</div>

<style>
    .waiting-list-section {
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.5rem;
        margin-top: 2rem;
    }

    @media (max-width: 600px) {
        .waiting-list-section {
            margin-top: 0px;
        }
    }

    .content-wrapper {
        width: 100%;
        min-height: 120px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .discord-content {
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 1rem;
    }

    .discord-text {
        color: var(--color-grey-60);
        margin: 0;
        text-align: center;
    }

    .newsletter-section {
        width: 100%;
        margin-top: 2rem;
        padding-top: 1.5rem;
        border-top: 1px solid var(--color-grey-20);
    }

    .newsletter-content {
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 1rem;
    }

    .newsletter-text {
        color: var(--color-grey-60);
        margin: 0;
        text-align: center;
        font-size: 14px;
    }

    .newsletter-form {
        width: 100%;
        max-width: 400px;
    }

    .newsletter-input-group {
        display: flex;
        gap: 0.5rem;
        width: 100%;
    }

    .newsletter-input {
        flex: 1;
        padding: 10px 15px;
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        font-size: 14px;
        background-color: var(--color-background);
        color: var(--color-text);
    }

    .newsletter-input:focus {
        outline: none;
        border-color: var(--color-primary);
    }

    .newsletter-input:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .newsletter-button {
        padding: 10px 20px;
        background-color: var(--color-primary);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: opacity 0.2s;
    }

    .newsletter-button:hover:not(:disabled) {
        opacity: 0.9;
    }

    .newsletter-button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .newsletter-button.loading {
        opacity: 0.6;
        cursor: wait;
    }

    .newsletter-success {
        color: var(--color-success, #28a745);
        text-align: center;
        font-size: 14px;
        padding: 10px;
    }

    .newsletter-error {
        color: var(--color-error, #dc3545);
        text-align: center;
        font-size: 13px;
        padding: 5px;
        margin-top: 0.5rem;
    }

    @media (max-width: 600px) {
        .newsletter-input-group {
            flex-direction: column;
        }

        .newsletter-button {
            width: 100%;
        }
    }
</style>