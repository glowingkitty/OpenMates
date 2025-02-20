<script lang="ts">
    import { _ } from 'svelte-i18n';
    import { onMount } from 'svelte';
    
    let otpCode = '';
    let otpInput: HTMLInputElement;

    onMount(() => {
        // Check if device is touch-enabled
        const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
        
        // Only auto-focus on non-touch devices
        if (otpInput && !isTouchDevice) {
            otpInput.focus();
        }
    });

    function handleInput(event: Event) {
        const input = event.target as HTMLInputElement;
        // Only allow numbers and limit to 6 digits
        otpCode = input.value.replace(/\D/g, '').slice(0, 6);
    }

    function handleResend() {
        // TODO: Implement resend functionality
    }
</script>

<div class="bottom-content">
    <div class="input-group">
        <div class="input-wrapper">
            <span class="clickable-icon icon_secret"></span>
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
        <span class="color-grey-60">{$_('signup.havent_received_a_code.text')}</span>
        <button class="text-button" on:click={handleResend}>
            {$_('signup.click_to_resend.text')}
        </button>
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
