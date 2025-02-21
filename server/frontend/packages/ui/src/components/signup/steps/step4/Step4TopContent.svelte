<script lang="ts">
    import { _ } from 'svelte-i18n';
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size tfa"></div>
        <h2 class="menu-title">{$_('signup.secure_your_account.text')}</h2>
    </div>
    <div class="prevent-access-text">{$_('signup.prevent_access.text')}</div>
    
    <div class="features">
        <div class="feature">
            <div class="check-icon"></div>
            <span>{$_('signup.free.text')}</span>
        </div>
        <div class="feature">
            <div class="check-icon"></div>
            <span>{$_('signup.fast_to_setup.text')}</span>
        </div>
        <div class="feature">
            <div class="check-icon"></div>
            <span>{$_('signup.max_security.text')}</span>
        </div>
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

    .signup-header {
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

    .prevent-access-text {
        margin: 24px 0 32px 0;
        text-align: center;
    }

    .features {
        display: flex;
        gap: 32px;
        justify-content: center;
        align-items: flex-start;
    }

    .feature {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        width: 110px;
        text-align: center;
    }

    .check-icon {
        width: 35px;
        height: 35px;
        -webkit-mask: url('@openmates/ui/static/icons/check.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/check.svg') no-repeat center;
        -webkit-mask-size: contain;
        mask-size: contain;
        background-color: #58BC00;
    }
</style>
