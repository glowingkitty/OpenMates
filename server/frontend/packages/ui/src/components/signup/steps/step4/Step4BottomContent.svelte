<script lang="ts">
    import { _ } from 'svelte-i18n';
    import { onMount } from 'svelte';
    import { createEventDispatcher } from 'svelte';
    import { routes } from '../../../../config/links';
    
    let otpCode = '';
    let otpInput: HTMLInputElement;
    const dispatch = createEventDispatcher();

    onMount(() => {
        const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
        if (otpInput && !isTouchDevice) {
            otpInput.focus();
        }
    });

    function handleInput(event: Event) {
        const input = event.target as HTMLInputElement;
        otpCode = input.value.replace(/\D/g, '').slice(0, 6);
        
        if (otpCode.length === 6) {
            dispatch('step', { step: 5 });
        }
    }
</script>

<div class="bottom-content">
    <div class="input-group">
        <div class="input-wrapper">
            <span class="clickable-icon icon_2fa"></span>
            <input
                bind:this={otpInput}
                type="text"
                bind:value={otpCode}
                on:input={handleInput}
                placeholder={$_('signup.enter_one_time_code.text')}
                inputmode="numeric"
                maxlength="6"
            />
        </div>
    </div>
    
    <div class="resend-section">
        <span class="color-grey-60">{$_('signup.dont_have_2fa_app.text')}</span>
        <a href={routes.docs.userGuide_signup_4} class="text-button">
            {$_('signup.click_here_to_show_free_2fa_apps.text')}
        </a>
    </div>
</div>

<style>
    .bottom-content {
        padding: 24px;
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .resend-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
    }
</style>
