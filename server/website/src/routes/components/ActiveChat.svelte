<script>
    import EnterMessageField from './enter_message/EnterMessageField.svelte';
</script>

<div class="active-chat-container">
    <!-- Existing ActiveChat content would go here -->

    <!-- Message input field positioned at bottom center -->
    <div class="message-input-wrapper">
        <EnterMessageField />
    </div>
</div>

<style>
    .active-chat-container {
        /* Use theme variables instead of hard-coded colors */
        background-color: var(--color-grey-20);
        border-radius: 17px;
        position: absolute;
        top: 0;
        right: 0;
        bottom: 0;
        left: 0;
    }

    .message-input-wrapper {
        position: absolute;
        bottom: 15px;
        left: 15px;
        right: 15px;
        display: flex;
        justify-content: center;
    }

    .message-input-wrapper :global(> *) {
        max-width: 629px;
        width: 100%;
    }
</style>
