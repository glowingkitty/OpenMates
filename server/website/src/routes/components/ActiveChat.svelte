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
        /* Light grey background color */
        background-color: #F2F2F2;
        /* Rounded corners - 17px radius */
        border-radius: 17px;
        /* Make the container fill the entire parent space */
        position: absolute;
        top: 0;
        right: 0;
        bottom: 0;
        left: 0;
    }

    .message-input-wrapper {
        /* Position at bottom of container */
        position: absolute;
        bottom: 15px;
        /* Center horizontally with padding on sides */
        left: 15px;
        right: 15px;
        /* Center alignment for child elements */
        display: flex;
        justify-content: center;
    }

    .message-input-wrapper :global(> *) {
        /* Set maximum width while allowing responsiveness */
        max-width: 629px;
        width: 100%;
    }
</style>
