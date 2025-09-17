<script lang="ts">
    import { defaultMeta } from '../config/meta';

    // Props using Svelte 5 runes
    let { 
        title = defaultMeta.title,
        description = defaultMeta.description,
        image = defaultMeta.image,
        imageWidth = defaultMeta.imageWidth,
        imageHeight = defaultMeta.imageHeight,
        url = defaultMeta.url,
        type = defaultMeta.type,
        keywords = defaultMeta.keywords,
        author = defaultMeta.author,
        locale = defaultMeta.locale,
        siteName = defaultMeta.siteName,
        logo = defaultMeta.logo,
        logoWidth = defaultMeta.logoWidth,
        logoHeight = defaultMeta.logoHeight
    }: {
        title?: string;
        description?: string;
        image?: string;
        imageWidth?: number;
        imageHeight?: number;
        url?: string;
        type?: string;
        keywords?: string[];
        author?: string;
        locale?: string;
        siteName?: string;
        logo?: string;
        logoWidth?: number;
        logoHeight?: number;
    } = $props();
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