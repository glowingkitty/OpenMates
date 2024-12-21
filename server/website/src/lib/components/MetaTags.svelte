<script lang="ts">
    import type { MetaTagConfig } from '$lib/config/meta';
    import { defaultMeta } from '$lib/config/meta';

    // Use the interface for type safety
    export let title: string = defaultMeta.title;
    export let description: string = defaultMeta.description;
    export let image: string = defaultMeta.image;
    export let url: string = defaultMeta.url;
    export let type: string = defaultMeta.type;
</script>

<svelte:head>
    <!-- Basic Meta Tags -->
    <title>{title}</title>
    <meta name="description" content={description} />

    <!-- Open Graph / Facebook -->
    <meta property="og:type" content={type} />
    <meta property="og:url" content={url} />
    <meta property="og:title" content={title} />
    <meta property="og:description" content={description} />
    <meta property="og:image" content={image} />

    <!-- Twitter -->
    <meta property="twitter:card" content="summary_large_image" />
    <meta property="twitter:url" content={url} />
    <meta property="twitter:title" content={title} />
    <meta property="twitter:description" content={description} />
    <meta property="twitter:image" content={image} />

    <!-- Additional Meta Tags -->
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="canonical" href={url} />
</svelte:head>