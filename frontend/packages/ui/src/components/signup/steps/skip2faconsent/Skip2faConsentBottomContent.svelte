<!--
Purpose: Requires explicit consent before continuing signup without 2FA setup.
Architecture: Mirrors the limited-refund consent gating pattern with a toggle gate.
Architecture Doc: See docs/architecture/app-skills.md for broader auth execution model.
Tests: frontend/apps/web_app/tests/signup-skip-2fa-flow.spec.ts
-->
<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import Toggle from '../../../Toggle.svelte';

    const dispatch = createEventDispatcher();

    let consented = $state(false);

    function handleContinue() {
        if (!consented) {
            return;
        }
        dispatch('step', { step: 'recovery_key' });
    }
</script>

<div class="bottom-content">
    <div class="confirmation-row">
        <Toggle bind:checked={consented} id="skip-2fa-consent-toggle" />
        <label for="skip-2fa-consent-toggle" class="confirmation-text">
            {$text('signup.skip_2fa_consent_toggle')}
        </label>
    </div>

    <button id="signup-skip-2fa-continue" class="buy-button" onclick={handleContinue} disabled={!consented}>
        {$text('common.continue')}
    </button>
</div>

<style>
    .bottom-content {
        padding: 24px;
        display: flex;
        flex-direction: column;
        gap: 18px;
    }

    .confirmation-row {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .confirmation-text {
        color: var(--color-grey-60);
        font-size: 16px;
        line-height: 1.4;
        cursor: pointer;
    }

    .buy-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
