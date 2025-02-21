<script lang="ts">
    import { _ } from 'svelte-i18n';
</script>

<div class="content">
    <div class="settings-header">
        <div class="icon header_size tfa"></div>
        <h2 class="menu-title">{$_('signup.secure_your_account.text')}</h2>
    </div>
</div>

<style>
    .content {
        padding: 24px;
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
    }

    .settings-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
    }

    .icon.header_size {
        width: 65px;
        height: 65px;
        border-radius: 14px;
        transition: none;
        animation: none;
        opacity: 1;
    }

    .menu-title {
        font-size: 24px;
        color: var(--color-grey-100);
        margin: 0;
    }
</style>
