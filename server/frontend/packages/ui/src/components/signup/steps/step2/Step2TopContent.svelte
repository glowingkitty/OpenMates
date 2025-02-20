<script lang="ts">
    import { _ } from 'svelte-i18n';
    export let email: string;
</script>

<div class="content">
    <div class="clickable-icon icon_mail"></div>
    <span class="color-grey-80">{$_('signup.you_received_a_one_time_code_via_email.text')}</span>
    <mark>{email}</mark>
    <a href="mailto:" class="text-button">
        {$_('signup.open_mail_app.text')}
    </a>
</div>

<style>
    .content {
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 20px;
        text-align: center;
        gap: 16px;
    }
</style>
