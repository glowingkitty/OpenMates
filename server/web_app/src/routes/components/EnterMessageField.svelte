<script lang="ts">
    // State for the input text
    let messageText = '';
    
    // Track the height of the input field for auto-resizing
    let textareaElement: HTMLTextAreaElement;
    
    // Function to handle auto-resizing of the textarea
    function adjustHeight() {
        if (textareaElement) {
            // Reset height to auto to get the correct scrollHeight
            textareaElement.style.height = 'auto';
            // Set new height based on scrollHeight, with max of 250px
            textareaElement.style.height = Math.min(textareaElement.scrollHeight, 250) + 'px';
        }
    }
</script>

<div class="message-container">
    <textarea
        bind:this={textareaElement}
        bind:value={messageText}
        on:input={adjustHeight}
        placeholder="Type your message here..."
        rows="1"
    ></textarea>
</div>

<style>
    .message-container {
        /* Container styling */
        width: 100%;
        min-height: 100px;
        max-height: 250px;
        background-color: #FFFFFF;
        border-radius: 24px;
        padding: 1rem;
        box-sizing: border-box;
        /* Remove container scroll */
        overflow-y: hidden;
    }

    textarea {
        /* Input field styling */
        width: 100%;
        min-height: 60px;
        max-height: 218px; /* 250px - 2rem padding */
        border: none;
        outline: none;
        resize: none;
        background: transparent;
        font-family: inherit;
        font-size: 1rem;
        line-height: 1.5;
        padding: 0.5rem 0;
        margin: 0;

        /* Enable textarea scrolling */
        overflow-y: auto;
    }

    textarea::placeholder {
        color: #888;
    }
</style>
