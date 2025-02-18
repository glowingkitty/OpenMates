<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { _ } from 'svelte-i18n';

    const dispatch = createEventDispatcher();

    function handleLoginClick() {
        dispatch('switchToLogin');
    }
</script>

<div class="signup-container">
    <button class="back-link" on:click={handleLoginClick}>
        <div class="clickable-icon icon_back"></div>
        {$_('login.login_button.text')}
    </button>
    
    <h1><mark>{$_('signup.sign_up.text')}</mark></h1>
    <h3>{$_('login.to_chat_to_your.text')}<br><mark>{$_('login.digital_team_mates.text')}</mark></h3>
    
    <!-- Form content will go here in future implementation -->
</div>

<style>
    .signup-container {
        position: relative;
        width: 100%;
    }

    .back-link {
        all: unset;
        position: absolute;
        top: 0;
        left: 0;
        font-size: 14px;
        color: #858585;
        background: none;
        border: none;
        cursor: pointer;
        padding: 0;
    }
</style>
