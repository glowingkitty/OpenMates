<!--
Purpose: Shows the warning copy when a user chooses to skip 2FA during signup.
Architecture: Part of the signup step flow in Signup.svelte for password-based accounts.
Architecture Doc: See docs/architecture/app-skills.md for broader auth execution model.
Tests: frontend/apps/web_app/tests/signup-skip-2fa-flow.spec.ts
-->
<script lang="ts">
    import { text } from '@repo/ui';
</script>

<div class="content">
    <div class="signup-header">
        <div class="icon header_size warning"></div>
        <h2 class="signup-menu-title">{$text('signup.skip_2fa_warning_title')}</h2>
    </div>

    <p class="description">{$text('signup.skip_2fa_warning_intro')}</p>

    <ul class="warning-list">
        <li>{$text('signup.skip_2fa_warning_rule_1')}</li>
        <li>{$text('signup.skip_2fa_warning_rule_2')}</li>
        <li>{$text('signup.skip_2fa_warning_rule_3')}</li>
        <li>{$text('signup.skip_2fa_warning_rule_4')}</li>
        <li>{$text('signup.skip_2fa_warning_rule_5')}</li>
    </ul>
</div>

<style>
    .content {
        padding: var(--spacing-12);
        display: flex;
        flex-direction: column;
        align-items: flex-start;
    }

    .signup-header {
        display: flex;
        align-items: center;
        gap: var(--spacing-8);
        margin-bottom: 14px;
    }

    .description {
        color: var(--color-grey-70);
        text-align: left;
        max-width: 640px;
        margin: 0 0 12px 0;
        line-height: 1.45;
    }

    .warning-list {
        margin: 0;
        padding-left: 18px;
        max-width: 640px;
        color: var(--color-grey-70);
        line-height: 1.5;
    }

    .warning-list li {
        margin-bottom: var(--spacing-5);
    }

    .warning-list li:last-child {
        margin-bottom: 0;
    }
</style>
