<script lang="ts">
    import Field from './Field.svelte';
    
    // Handler for the email submission
    const handleSubmit = () => {
        // TODO: Implement email submission logic
        console.log('Email submitted');
    };
</script>

<div class="waiting-list-section">
    <p class="waiting-list-text">Join the waiting list:</p>
    <div class="email-input-container">
        <Field 
            type="email" 
            placeholder="Enter your e-mail address..." 
            variant="email"
            withButton={true}
            buttonText="Send"
            onButtonClick={handleSubmit}
            autofocus={true}
        />
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
        position: relative;
        display: flex;
        align-items: center;
        margin: 0 auto;
    }

    .invites-text {
        font-size: 0.9rem;
        color: #888;
        margin-top: 0.5rem;
    }
</style> 