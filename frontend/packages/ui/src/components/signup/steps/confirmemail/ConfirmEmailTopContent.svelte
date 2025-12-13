<script lang="ts">
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { signupStore } from '../../../../stores/signupStore';
    import { get } from 'svelte/store';
</script>

<div class="content">
    <div class="main-content">
        <div class="icon-container">
            <div class="clickable-icon icon_mail signup"></div>
            <div class="notification-counter" transition:fade={{ delay: 800 }}>1</div>
        </div>
        <span class="color-grey-80">{@html $text('signup.you_received_a_one_time_code_via_email.text')}</span>
        <mark>{get(signupStore)?.email}</mark>
    </div>
    <a href="mailto:" class="text-button">
        {$text('signup.open_mail_app.text')}
    </a>
</div>

<style>
    /**
     * Content container - uses flexbox for responsive layout
     * Changed from absolute positioning to relative for better compatibility
     * across all viewport sizes, especially desktop where parent has height: auto
     */
    .content {
        position: relative;
        width: 100%;
        min-height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: space-between;
        padding: 20px;
        text-align: center;
        box-sizing: border-box;
    }

    /**
     * Main content area - centered vertically when there's space
     * Uses auto margin to center when content is smaller than container
     */
    .main-content {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 16px;
        min-height: 0; /* Allow shrinking in flex container */
    }

    .icon-container {
        position: relative;
    }

    .notification-counter {
        position: absolute;
        top: -8px;
        right: -8px;
        width: 35px;
        height: 35px;
        background-color: var(--color-button-primary);
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 24px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
    }

    .clickable-icon.icon_mail.signup {
        cursor: unset;
        width: 75px;
        height: 75px;
    }

    /**
     * Text button - positioned at bottom
     * On mobile, use relative positioning to stay in document flow
     * On desktop, can use absolute if needed but relative works better
     */
    .text-button {
        position: relative;
        margin-top: auto;
        padding-top: 20px;
        width: 100%;
    }

    
</style>
