<script lang="ts">
    import type { MetaTagConfig } from '$lib/config/meta';
    import { defaultMeta } from '$lib/config/meta';

    export let title: string = defaultMeta.title;
    export let description: string = defaultMeta.description;
    export let image: string = defaultMeta.image;
    export let imageWidth: number = defaultMeta.imageWidth;
    export let imageHeight: number = defaultMeta.imageHeight;
    export let url: string = defaultMeta.url;
    export let type: string = defaultMeta.type;
    export let keywords: string[] = defaultMeta.keywords;
    export let author: string = defaultMeta.author;
    export let locale: string = defaultMeta.locale;
    export let siteName: string = defaultMeta.siteName;
    export let logo: string = defaultMeta.logo;
    export let logoWidth: number = defaultMeta.logoWidth;
    export let logoHeight: number = defaultMeta.logoHeight;
</script>

<svelte:head>
    <!-- Basic Meta Tags -->
    <title>{title}</title>

    <!-- Add favicon links -->
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link rel="alternate icon" type="image/jpeg" href="/favicon.jpg" />

    <meta name="description" content={description} />
    <meta name="keywords" content={keywords.join(', ')} />
    <meta name="author" content={author} />
    <meta name="robots" content="index, follow" />
    <meta name="language" content={locale.split('_')[0]} />

    <!-- Open Graph / Facebook -->
    <meta property="og:type" content={type} />
    <meta property="og:url" content={url} />
    <meta property="og:title" content={title} />
    <meta property="og:description" content={description} />
    <meta property="og:image" content={image} />
    <meta property="og:image:width" content={imageWidth.toString()} />
    <meta property="og:image:height" content={imageHeight.toString()} />
    <meta property="og:site_name" content={siteName} />
    <meta property="og:locale" content={locale} />

    <!-- Twitter -->
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:url" content={url} />
    <meta name="twitter:title" content={title} />
    <meta name="twitter:description" content={description} />
    <meta name="twitter:image" content={image} />

    <!-- Additional Meta Tags -->
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
    <link rel="canonical" href={url} />

    <!-- JSON-LD for rich snippets -->
    {@html `
        <script type="application/ld+json">
        {
            "@context": "http://schema.org",
            "@type": "${type === 'article' ? 'Article' : 'WebSite'}",
            "name": "${title}",
            "headline": "${title}",
            "description": "${description}",
            "author": {
                "@type": "Organization",
                "name": "${author}",
                "url": "${defaultMeta.url}"
            },
            "url": "${url}",
            "image": {
                "@type": "ImageObject",
                "url": "${image}",
                "width": "${imageWidth}",
                "height": "${imageHeight}"
            },
            "publisher": {
                "@type": "Organization",
                "name": "${siteName}",
                "logo": {
                    "@type": "ImageObject",
                    "url": "${logo}",
                    "width": "${logoWidth}",
                    "height": "${logoHeight}"
                }
            },
            "datePublished": "${new Date().toISOString()}",
            "dateModified": "${new Date().toISOString()}",
            "mainEntityOfPage": {
                "@type": "WebPage",
                "@id": "${url}"
            }
        }
        </script>
    `}
</svelte:head>