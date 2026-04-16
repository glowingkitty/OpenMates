<script lang="ts">
    import { Header, Footer } from '@repo/ui';
    import type { PageData } from './$types';

    let { data }: { data: PageData } = $props();
    const newsletter = $derived(data.newsletter);
</script>

<svelte:head>
    <title>{newsletter.title}</title>
    <meta name="description" content={newsletter.subtitle ?? newsletter.title} />
    <meta name="robots" content="noindex" />
</svelte:head>

<div class="page-container">
    <Header context="website" />

    <main class="main-content">
        <article class="content-wrapper">
            <h1>{newsletter.title}</h1>
            {#if newsletter.subtitle}
                <p class="subtitle">{newsletter.subtitle}</p>
            {/if}

            {#if newsletter.video}
                <div class="video-wrapper">
                    <video
                        controls
                        preload="metadata"
                        playsinline
                        poster={newsletter.video.poster}
                    >
                        <source
                            src={newsletter.video.src}
                            type={newsletter.video.mimeType ?? 'video/mp4'}
                        />
                        Your browser does not support the video tag.
                    </video>
                </div>
            {/if}

            {#if newsletter.cta}
                <a class="cta" href={newsletter.cta.url}>{newsletter.cta.label}</a>
            {/if}
        </article>
    </main>

    <Footer />
</div>

<style>
    .page-container {
        min-height: 100vh;
        display: flex;
        flex-direction: column;
    }

    .main-content {
        flex: 1;
        display: flex;
        align-items: flex-start;
        justify-content: center;
        padding: 2rem 1rem 4rem;
    }

    .content-wrapper {
        max-width: 820px;
        width: 100%;
    }

    h1 {
        margin: 0 0 0.5rem 0;
        font-size: 2rem;
        line-height: 1.2;
    }

    .subtitle {
        margin: 0 0 2rem 0;
        font-size: 1.125rem;
        color: var(--ds-text-muted, #555);
    }

    .video-wrapper {
        width: 100%;
        aspect-ratio: 16 / 9;
        background: #000;
        border-radius: 12px;
        overflow: hidden;
        margin: 0 0 2rem 0;
    }

    .video-wrapper video {
        width: 100%;
        height: 100%;
        display: block;
        object-fit: contain;
    }

    .cta {
        display: inline-block;
        padding: 0.75rem 1.5rem;
        background-color: var(--ds-brand, #6364FF);
        color: #fff;
        border-radius: 8px;
        text-decoration: none;
        font-weight: 600;
    }

    .cta:hover {
        opacity: 0.9;
    }
</style>
