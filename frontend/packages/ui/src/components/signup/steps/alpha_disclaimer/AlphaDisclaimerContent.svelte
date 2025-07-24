<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';

    const dispatch = createEventDispatcher();

    function handleContinue() {
        dispatch('continue');
    }
</script>

<div class="content-area">
    <h1><mark>{@html $text('signup.version_title.text')}</mark></h1>
    
    <div class="disclaimer-items">
        <div class="disclaimer-item">
            <div class="clickable-icon icon_project"></div>
            <div class="disclaimer-text">
                <p>{@html $text('signup.is_alpha_disclaimer.text')}</p>
            </div>
        </div>
        
        <div class="disclaimer-item">
            <div class="clickable-icon icon_thumbsup"></div>
            <div class="disclaimer-text">
                <p>{@html $text('signup.decent_stable.text')}</p>
            </div>
        </div>
        
        <div class="disclaimer-item">
            <div class="clickable-icon icon_task"></div>
            <div class="disclaimer-text">
                <p>{@html $text('signup.not_all_core_features_implemented.text')}</p>
            </div>
        </div>
        
        <div class="disclaimer-item">
            <div class="clickable-icon icon_bug"></div>
            <div class="disclaimer-text">
                <p>{@html $text('signup.expect_bugs_and_missing_features.text')}</p>
            </div>
        </div>
        
        <div class="disclaimer-item clickable" on:click={() => window.open('https://github.com/glowingkitty/OpenMates', '_blank')}>
            <div class="clickable-icon icon_github"></div>
            <div class="disclaimer-text">
                <p class="link-title">{@html $text('signup.view_on_github.text')}</p>
                <p class="subtext">{@html $text('signup.view_on_github_description.text')}</p>
            </div>
        </div>
        
        <div class="disclaimer-item clickable" on:click={() => window.open('https://instagram.com/openmates_official', '_blank')}>
            <div class="clickable-icon icon_instagram"></div>
            <div class="disclaimer-text">
                <p class="link-title">{@html $text('signup.view_on_instagram.text')}</p>
                <p class="subtext">{@html $text('signup.view_on_instagram_description.text')}</p>
            </div>
        </div>
    </div>
    <button
        on:click={handleContinue}
    >
        {@html $text('signup.continue_with_alpha.text', { values: { version: $text('signup.version_title.text') } })}
    </button>
</div>

<style>
    .disclaimer-items {
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin-bottom: 10px;
        text-align: left;
        margin: 10px;
    }

    .disclaimer-item {
        display: flex;
        align-items: flex-start;
        gap: 15px;
        padding: 0.5rem;
        border-radius: 8px;
        transition: background-color 0.2s ease;
    }

    .disclaimer-item.clickable {
        cursor: pointer;
    }

    .disclaimer-item.clickable:hover {
        background-color: var(--hover-bg-color, rgba(99, 102, 241, 0.1));
    }

    .clickable-icon {
        width: 24px;
        height: 24px;
    }

    .disclaimer-text {
        flex: 1;
    }

    .disclaimer-text p {
        margin: 0 0 0.5rem 0;
        font-size: 1rem;
        line-height: 1.5;
    }

    .disclaimer-text p:last-child {
        margin-bottom: 0;
    }


    .disclaimer-text .link-title {
        color: var(--primary-color, #6366f1);
        font-weight: 500;
    }

    /* Responsive Design */
    @media (max-width: 768px) {
        .alpha-disclaimer-container {
            padding: 1rem;
            min-height: calc(100vh - 2rem);
        }
    }

    @media (max-width: 480px) {
        .disclaimer-text p {
            font-size: 0.9rem;
        }
    }
</style>
