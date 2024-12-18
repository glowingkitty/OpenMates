<script lang="ts">
    import Field from './Field.svelte';
    import { fade } from 'svelte/transition';

    // State management
    let email: string = '';
    let isSubmitted: boolean = false;

    // Handler for the email submission
    const handleSubmit = () => {
        // Log the valid email (validation is handled in Field component)
        console.log('Valid email submitted:', email);
        
        // Update UI state to show confirmation
        isSubmitted = true;
    };
</script>

<div class="waiting-list-section">
    {#if !isSubmitted}
        <div transition:fade>
            <p class="waiting-list-text">Join the waiting list:</p>
            <div class="email-input-container">
                <Field
                    type="email"
                    placeholder="Enter your e-mail address..."
                    variant="email"
                    withButton={true}
                    buttonText="Send"
                    onButtonClick={handleSubmit}
                    bind:value={email}
                    autofocus={true}
                />
            </div>
        </div>
    {:else}
        <div class="confirmation-message" transition:fade>
            <p>Thank you for joining! We'll be in touch soon.</p>
        </div>
    {/if}
    
    <p class="invites-text">
        <span class="calendar-icon"></span>
        First invites in Jan 2025
    </p>
</div>

<style>
    .waiting-list-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.5rem;
        margin-top: 2rem;
    }

    .waiting-list-text {
        font-size: 1.2rem;
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
        color: #2ecc71;
        font-size: 1.1rem;
        margin: 1rem 0;
    }

    .invites-text {
        font-size: 0.9rem;
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
</style> 