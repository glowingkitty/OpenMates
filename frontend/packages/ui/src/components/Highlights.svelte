<script lang="ts">
    import Highlight from './Highlight.svelte';
    import { _, waitLocale } from 'svelte-i18n';
    import { onMount } from 'svelte';
    // Props using Svelte 5 runes
    let { target = '' }: { target?: string } = $props();

    let loaded = $state(false);
    let mounted = $state(false);

    // Initialize on mount
    onMount(async () => {
        mounted = true;
        await waitLocale();
        loaded = true;
    });

    // Watch for locale changes using Svelte 5 runes
    $effect(() => {
        if (mounted) {
            waitLocale().then(() => {
                loaded = true;
            });
        }
    });
</script>

<!-- Show loading state or placeholder while waiting -->
{#if !loaded}
    <div class="loading-highlights">
        <!-- Optional: Add loading skeleton or placeholder here -->
    </div>
{:else}
    {#if target === 'for_all'}
        <Highlight
            sub_heading="Ask"
            main_heading={`<mark>${$_('highlight.sections.ask.main_heading_1')}</mark><br>${$_('highlight.sections.ask.main_heading_2')}`}
            paragraph={$_('highlight.sections.ask.paragraph')}
            text_side="left"
            {target}
        />
        <Highlight
            sub_heading="Tasks"
            main_heading={`${$_('highlight.sections.tasks.main_heading_1')}<br><mark>${$_('highlight.sections.tasks.main_heading_2')}</mark>`}
            paragraph={$_('highlight.sections.tasks.paragraph')}
            text_side="right"
            {target}
        />
        <Highlight
            sub_heading="Apps"
            main_heading={`<mark>${$_('highlight.sections.apps.main_heading_1')}</mark><br>${$_('highlight.sections.apps.main_heading_2')}`}
            paragraph={$_('highlight.sections.apps.paragraph')}
            text_side="left"
            {target}
        />
    {/if}

    {#if target === 'for_developers'}
        <Highlight
            sub_heading="Ask"
            main_heading={`<mark>${$_('highlight.sections.ask.main_heading')}</mark>`}
            paragraph={$_('highlight.sections.ask.paragraph')}
            text_side="left"
            target="for_developers"
        />
        <Highlight
            sub_heading="Tasks"
            main_heading={`<mark>${$_('highlight.sections.tasks.main_heading')}</mark>`}
            paragraph={$_('highlight.sections.tasks.paragraph')}
            text_side="right"
            target="for_developers"
        />
        <Highlight
            sub_heading="Apps"
            main_heading={`<mark>${$_('highlight.sections.apps.main_heading')}</mark>`}
            paragraph={$_('highlight.sections.apps.paragraph')}
            text_side="left"
            target="for_developers"
        />
    {/if}
{/if}

<style>
    .loading-highlights {
        min-height: 200px; /* Adjust based on your needs */
        width: 100%;
        /* Optional: Add loading animation styles */
    }
</style>
