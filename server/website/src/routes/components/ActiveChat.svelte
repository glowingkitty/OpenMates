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
        background-color: var(--color-grey-20);
        border-radius: 17px;
        flex-grow: 1;
        position: relative;
        min-height: 0;
        height: 100%;

        /* Add drop shadow on all sides */
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
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
