<script lang="ts">
    import Field from './Field.svelte';
    import { fade } from 'svelte/transition';
    import { browser } from '$app/environment';

    // State management
    let email: string = '';
    let isSubmitting: boolean = false;
    let isSubmitted: boolean = false;
    let errorMessage: string = '';

    // TODO check API server for previous submission

    // TODO if not submitted, show form

    // Check localStorage for previous submission
    const hasSubmittedBefore = browser && localStorage.getItem('newsletter_submitted');
    if (hasSubmittedBefore) {
        isSubmitted = true;
    }

    // Generate a simple request token
    const requestToken = Math.random().toString(36).substring(2);

    // Handler for the email submission
    const handleSubmit = async () => {
        try {
            // Prevent double submission
            if (isSubmitting || isSubmitted) {
                console.debug('Preventing double submission');
                return;
            }

            isSubmitting = true;
            errorMessage = '';

            // const response = await fetch('https://your-server.com/api/subscribe', {
            //     method: 'POST',
            //     headers: {
            //         'Content-Type': 'application/json',
            //         'X-Request-Token': requestToken
            //     },
            //     body: JSON.stringify({ 
            //         email,
            //         timestamp: Date.now(),
            //         // Add a hash to prevent tampering
            //         hash: await generateHash(email, requestToken)
            //     })
            // });

            // if (!response.ok) {
            //     const data = await response.json();
            //     throw new Error(data.message || 'Subscription failed');
            // }

            console.info('Email subscription initiated');
            isSubmitted = true;

            // Store submission in localStorage
            if (browser) {
                localStorage.setItem('newsletter_submitted', 'true');
                localStorage.setItem('newsletter_email', email);
            }

        } catch (error) {
            console.error(error);
            errorMessage = error instanceof Error ? error.message : 'Something went wrong. Please try again later.';
        } finally {
            isSubmitting = false;
        }
    };

    // Simple hash function for request validation
    async function generateHash(email: string, token: string): Promise<string> {
        const data = `${email}:${token}:${Date.now()}`;
        const encoder = new TextEncoder();
        const hashBuffer = await crypto.subtle.digest('SHA-256', encoder.encode(data));
        return Array.from(new Uint8Array(hashBuffer))
            .map(b => b.toString(16).padStart(2, '0'))
            .join('');
    }
</script>

<div class="waiting-list-section">
    <div class="content-wrapper">
        {#if !isSubmitted}
            <div class="form-content" transition:fade={{ duration: 200 }}>
                <p class="waiting-list-text">Join the waiting list:</p>
                <form 
                    class="email-input-container" 
                    on:submit|preventDefault={handleSubmit}
                >
                    <Field
                        type="email"
                        id="newsletter-email"
                        name="newsletter-email"
                        placeholder="Enter your e-mail address..."
                        variant="email"
                        withButton={true}
                        buttonText="Send"
                        onButtonClick={handleSubmit}
                        bind:value={email}
                        autofocus={false}
                        autocomplete="email"
                    />
                </form>
            </div>
        {:else}
            <div class="confirmation-content" transition:fade={{ duration: 200 }}>
                <p style="text-align: center;"><mark><bold>You are on the waiting list</bold></mark> for <strong><mark>Open</mark><span style="color: black;">Mates</span></strong>.<br>We let you know via e-mail once you can sign up.</p>
            </div>
        {/if}
    </div>

    <p class="invites-text">
        <span class="calendar-icon"></span>
        First invites in Jan 2025
    </p>
</div>

<style>
    .waiting-list-section {
        width: 420px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.5rem;
        margin-top: 2rem;
    }

    .waiting-list-text {
        color: #666;
        margin: 0 0 1rem 0;
        text-align: center;
        width: 100%;
    }

    .email-input-container {
        width: 100%;
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
        margin: 0 auto;
    }

    .confirmation-message {
        text-align: center;
        color: #888;
    }

    .invites-text {
        color: #888;
        margin-top: 0;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .calendar-icon {
        display: inline-block;
        filter: opacity(40%);
        vertical-align: middle;
    }

    /* Target the error message specifically within the email-input-container */
    .email-input-container :global(.error-message) {
        text-align: center;
        width: 100%;
    }

    .content-wrapper {
        width: 100%;
        min-height: 120px; /* Adjust this value based on your content */
        display: flex;
        align-items: center;
        justify-content: center;
        position: relative;
    }

    .form-content,
    .confirmation-content {
        position: absolute;
        width: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
    }
</style>