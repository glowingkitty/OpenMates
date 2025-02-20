<script lang="ts">
    import { _ } from 'svelte-i18n';
    import { fade } from 'svelte/transition';
    export let email: string;
</script>

<div class="content">
    <div class="main-content">
        <div class="icon-container">
            <div class="clickable-icon icon_mail signup"></div>
            <div class="notification-counter" transition:fade={{ delay: 300 }}>1</div>
        </div>
        <span class="color-grey-80">{$_('signup.you_received_a_one_time_code_via_email.text')}</span>
        <mark>{email}</mark>
    </div>
    <a href="mailto:" class="text-button">
        {$_('signup.open_mail_app.text')}
    </a>
</div>

<style>
    .content {
        position: absolute;
        top: 0;
        bottom: 0;
        left: 0;
        right: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 20px;
        text-align: center;
    }

    .main-content {
        margin: auto 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
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
    }

    .clickable-icon.icon_mail.signup {
        cursor: unset;
        width: 75px;
        height: 75px;
    }

    .text-button {
        position: absolute;
        bottom: 20px;
        left: 0;
        right: 0;
    }
</style>
