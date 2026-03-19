<script lang="ts">
    // frontend/apps/web_app/src/routes/+error.svelte
    /**
     * @file +error.svelte
     * @description SvelteKit error boundary. Rendered when the client-side router
     * cannot match a URL to any route (404). Immediately redirects to the SPA root
     * with a #404=<path> hash fragment so the main +page.svelte can display the
     * Not404Screen recovery UI.
     *
     * Architecture: SvelteKit's router intercepts unknown paths during hydration
     * and renders this component instead of +page.svelte. We use onMount to detect
     * this and navigate to / with the #404= hash so the SPA's onMount can pick it up.
     *
     * Test reference: tests/not-found-404-flow.spec.ts
     */
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';

    onMount(() => {
        // Only handle 404 errors — let other errors render normally
        if ($page.status === 404) {
            const failedPath = $page.url.pathname + ($page.url.search || '');
            const hash = `#404=${encodeURIComponent(failedPath)}`;
            // Use goto to navigate to root with the 404 hash.
            // replaceState: true so back-button doesn't return to the broken path.
            goto(`/${hash}`, { replaceState: true });
        }
    });
</script>

{#if $page.status !== 404}
    <!-- Non-404 errors: render a minimal error UI -->
    <div class="error-page">
        <h1>{$page.status}</h1>
        <p>{$page.error?.message ?? 'An error occurred'}</p>
    </div>
{/if}
<!-- 404: render nothing while the redirect fires -->

<style>
    .error-page {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100vh;
        font-family: sans-serif;
        color: var(--color-font-primary, #000);
        background: var(--color-grey-0, #fff);
    }

    .error-page h1 {
        font-size: 4rem;
        margin: 0;
    }
</style>
