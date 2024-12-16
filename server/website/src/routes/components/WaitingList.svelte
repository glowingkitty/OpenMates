<script lang="ts">
    // Component for the waiting list section with email signup
</script>

<div class="waiting-list-section">
    <p class="waiting-list-text">Join the waiting list:</p>
    <div class="email-input-container">
        <input class="icon-field email-field" 
            type="email" 
            placeholder="Enter your e-mail address" 
        />
        <button class="send-button">Send</button>
    </div>
    <p class="invites-text">First invites in Jan 2025</p>
</div>

<style>
    .waiting-list-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 1rem;
        margin-top: 2rem;
    }

    .waiting-list-text {
        font-size: 1.2rem;
        color: #666;
        margin: 0;
    }

    .email-input-container {
        width: 100%;
        max-width: 400px;
        position: relative;
        display: flex;
        align-items: center;
    }

    /* Style for the input field to accommodate the button */
    :global(.email-input-container .email-field) {
        border-radius: 50px;
        padding-right: 120px; /* Make room for the button */
    }

    /* Position the button to overlap the input */
    :global(.email-input-container .send-button) {
        position: absolute;
        right: 5px;
        padding: 12px 24px;
        height: auto;
        border-radius: 25px;
        margin: 0;
        z-index: 1;
    }

    .invites-text {
        font-size: 0.9rem;
        color: #888;
        margin-top: 0.5rem;
    }
</style> 