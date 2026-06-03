<script lang="ts">
    /**
     * Dynamic Docs Page
     *
     * Renders individual documentation pages using a lightweight docs header
     * and static HTML content styled as a single assistant message.
     *
     * URL patterns:
     * - /docs/architecture -> Shows architecture folder index or README
     * - /docs/architecture/chats -> Shows specific document
     *
     * Architecture: docs/architecture/docs-web-app.md
     */
    import { text } from '@openmates/ui/src/i18n/translations';
    import { getCategoryGradientColors, getLucideIcon } from '@openmates/ui/src/utils/categoryUtils';
    import DocsMessage from '$lib/components/docs/DocsMessage.svelte';
    import DocsActionBar from '$lib/components/docs/DocsActionBar.svelte';
    import DocsBreadcrumb from '$lib/components/docs/DocsBreadcrumb.svelte';
    import type { DocFile, DocManifestFolder, DocsManifest } from '$lib/types/docs';
    import { getDocCategoryInfo } from '$lib/utils/docsCategoryMap';

    interface Props {
        data: {
            slug: string;
            pageData: { type: 'file'; data: DocFile } | { type: 'folder'; data: DocManifestFolder } | null;
            manifest: DocsManifest;
        };
    }

    let { data }: Props = $props();
    let currentSlug = $derived(data.slug || '');
    let pageData = $derived(data.pageData);

    /** Category info derived from the slug's top-level folder */
    let catInfo = $derived(getDocCategoryInfo(currentSlug));
    let gradColors = $derived(getCategoryGradientColors(catInfo.category));
    let HeaderIcon = $derived(getLucideIcon(catInfo.icon));

    /** First paragraph of content as summary for the docs header */
    let summary = $derived.by(() => {
        if (pageData?.type !== 'file') return null;
        const file = pageData.data as DocFile;
        return file.description || null;
    });

    let pageTitle = $derived(
        pageData?.type === 'file'
            ? pageData.data.title
            : pageData?.type === 'folder'
                ? pageData.data.title
                : $text('documentation.page_not_found')
    );

    /** SEO description from first paragraph */
    let pageDescription = $derived.by(() => {
        if (pageData?.type !== 'file') return 'OpenMates documentation';
        const file = pageData.data as DocFile;
        return file.description || 'OpenMates documentation';
    });
</script>

<svelte:head>
    <title>{pageTitle} | OpenMates Docs</title>
    <meta name="description" content={pageDescription} />
    <meta name="robots" content="index, follow" />
    <link rel="canonical" href="https://openmates.org/docs/{currentSlug}" />

    <!-- Open Graph -->
    <meta property="og:type" content="article" />
    <meta property="og:url" content="https://openmates.org/docs/{currentSlug}" />
    <meta property="og:title" content="{pageTitle} | OpenMates Docs" />
    <meta property="og:description" content={pageDescription} />
    <meta property="og:image" content="https://openmates.org/images/og-image.jpg" />
    <meta property="og:site_name" content="OpenMates" />

    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:url" content="https://openmates.org/docs/{currentSlug}" />
    <meta name="twitter:title" content="{pageTitle} | OpenMates Docs" />
    <meta name="twitter:description" content={pageDescription} />
    <meta name="twitter:image" content="https://openmates.org/images/og-image.jpg" />
</svelte:head>

{#if pageData?.type === 'file'}
    {@const file = pageData.data as DocFile}
    {#key currentSlug}
        <div class="docs-page-content">
            <DocsActionBar title={file.title} originalMarkdown={file.originalMarkdown} fileName={file.name} />
            <DocsBreadcrumb slug={currentSlug} />
            <header class="docs-header" style="background: linear-gradient(135deg, {gradColors?.start ?? '#6366f1'}, {gradColors?.end ?? '#4f46e5'});">
                <div class="docs-header-icon">
                    <HeaderIcon size={34} color="white" strokeWidth={2} />
                </div>
                <h1>{file.title}</h1>
                {#if summary}
                    <p>{summary}</p>
                {/if}
            </header>
            <DocsMessage
                content={file.content}
                category={catInfo.category}
            />
        </div>
    {/key}
{:else if pageData?.type === 'folder'}
    {@const folder = pageData.data as DocManifestFolder}
    <div class="docs-page-content">
        <DocsBreadcrumb slug={currentSlug} />
        <header class="docs-header" style="background: linear-gradient(135deg, {gradColors?.start ?? '#6366f1'}, {gradColors?.end ?? '#4f46e5'});">
            <div class="docs-header-icon">
                <HeaderIcon size={34} color="white" strokeWidth={2} />
            </div>
            <h1>{folder.title}</h1>
        </header>
        <div class="folder-index">
            {#if folder.files.length > 0}
                <div class="folder-section">
                    {#each folder.files as file (file.slug)}
                        <a href="/docs/{file.slug}" class="folder-link">
                            <span class="link-title">{file.title}</span>
                        </a>
                    {/each}
                </div>
            {/if}
            {#if folder.folders.length > 0}
                <div class="folder-section">
                    {#each folder.folders as subfolder (subfolder.path)}
                        <a href="/docs/{subfolder.path}" class="folder-link">
                            <span class="link-title">{subfolder.title}</span>
                            <span class="link-count">{subfolder.files.length} docs</span>
                        </a>
                    {/each}
                </div>
            {/if}
        </div>
    </div>
{:else}
    <div class="not-found">
        <h1>{$text('documentation.page_not_found')}</h1>
        <a href="/docs">{$text('documentation.back_to_docs')}</a>
    </div>
{/if}

<style>
    .docs-page-content {
        min-height: 100%;
        position: relative;
    }

    .docs-header {
        margin: 0 1rem 1rem;
        min-height: 190px;
        border-radius: 14px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        color: white;
        padding: 2rem;
        overflow: hidden;
    }

    .docs-header-icon {
        margin-bottom: 0.75rem;
        opacity: 0.95;
    }

    .docs-header h1 {
        margin: 0;
        font-size: 1.4rem;
        line-height: 1.25;
        font-weight: 700;
        max-width: 760px;
    }

    .docs-header p {
        margin: 0.75rem 0 0;
        max-width: 720px;
        font-size: 0.95rem;
        line-height: 1.45;
        opacity: 0.85;
    }

    .folder-index {
        padding: 1.5rem;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    .folder-section {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .folder-link {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.75rem 1rem;
        border-radius: 10px;
        text-decoration: none;
        color: var(--color-font-primary);
        background-color: var(--color-grey-10);
        transition: background-color 0.15s ease;
    }

    .folder-link:hover {
        background-color: var(--color-grey-30);
    }

    .link-title {
        font-weight: 500;
        font-size: 0.9375rem;
    }

    .link-count {
        font-size: 0.75rem;
        color: var(--color-font-secondary);
    }

    .not-found {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 4rem 1rem;
        gap: 1rem;
        min-height: 50vh;
    }

    .not-found h1 {
        font-size: 1.5rem;
        font-weight: 600;
        color: var(--color-font-primary);
    }

    .not-found a {
        color: var(--color-primary);
        text-decoration: none;
        font-weight: 500;
    }

    .not-found a:hover {
        text-decoration: underline;
    }
</style>
