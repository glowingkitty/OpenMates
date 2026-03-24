<script lang="ts">
    /**
     * Dynamic Docs Page
     *
     * Renders individual documentation pages using ChatHeader + DocsMessage,
     * matching the chat UI pattern. Content is rendered as a single assistant
     * message via ReadOnlyMessage/TipTap.
     *
     * URL patterns:
     * - /docs/architecture -> Shows architecture folder index or README
     * - /docs/architecture/chats -> Shows specific document
     *
     * Architecture: docs/architecture/docs-web-app.md
     */
    import { page } from '$app/state';
    import { ChatHeader, text } from '@repo/ui';
    import DocsMessage from '$lib/components/docs/DocsMessage.svelte';
    import DocsActionBar from '$lib/components/docs/DocsActionBar.svelte';
    import docsData from '$lib/generated/docs-data.json';
    import type { DocFile, DocFolder, DocStructure } from '$lib/types/docs';
    import { getDocCategoryInfo } from '$lib/utils/docsCategoryMap';

    let currentSlug = $derived(page.params.slug || '');
    let pageData = $derived(findPageData(currentSlug));

    /** Category info derived from the slug's top-level folder */
    let catInfo = $derived(getDocCategoryInfo(currentSlug));

    /** First paragraph of content as summary for ChatHeader */
    let summary = $derived.by(() => {
        if (pageData?.type !== 'file') return null;
        const file = pageData.data as DocFile;
        const plain = file.plainText || '';
        // Skip the title line, get the first real paragraph
        const lines = plain.split('\n').filter((l: string) => l.trim());
        const firstPara = lines.find((l: string) =>
            l.trim() && l.trim() !== file.title
        ) || '';
        return firstPara.length > 150 ? firstPara.substring(0, 150) + '...' : firstPara;
    });

    function findPageData(slug: string): { type: 'file' | 'folder'; data: DocFile | DocFolder } | null {
        const parts = slug.split('/').filter(Boolean);
        if (parts.length === 0) return null;

        let current: DocStructure | DocFolder = docsData.structure as DocStructure;

        for (let i = 0; i < parts.length; i++) {
            const part = parts[i];
            const isLast = i === parts.length - 1;

            const file = current.files.find(
                (f: DocFile) => f.slug === slug || f.name.replace('.md', '') === part
            );
            if (file && isLast) return { type: 'file', data: file };

            const folder: DocFolder | undefined = current.folders.find((f: DocFolder) => f.name === part);
            if (folder) {
                if (isLast) {
                    const indexFile = folder.files.find(
                        (f: DocFile) => f.name === 'README.md' || f.name === 'index.md'
                    );
                    if (indexFile) return { type: 'file', data: indexFile };
                    return { type: 'folder', data: folder };
                }
                current = folder;
            } else {
                return null;
            }
        }
        return null;
    }

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
        const plain = file.plainText || '';
        const lines = plain.split('\n').filter((l: string) => l.trim());
        const desc = lines.find((l: string) => l.trim() && l.trim() !== file.title) || '';
        return desc.length > 160 ? desc.substring(0, 157) + '...' : desc || 'OpenMates documentation';
    });
</script>

<svelte:head>
    <title>{pageTitle} | OpenMates Docs</title>
    <meta name="description" content={pageDescription} />
    <meta property="og:title" content="{pageTitle} | OpenMates Docs" />
    <meta property="og:description" content={pageDescription} />
    <meta property="og:type" content="article" />
    <link rel="canonical" href="https://openmates.org/docs/{currentSlug}" />
</svelte:head>

{#if pageData?.type === 'file'}
    {@const file = pageData.data as DocFile}
    {#key currentSlug}
        <div class="docs-page-content">
            <DocsActionBar title={file.title} />
            <ChatHeader
                title={file.title}
                category={catInfo.category}
                icon={catInfo.icon}
                summary={summary}
            />
            <DocsMessage
                content={file.processedMarkdown}
                category={catInfo.category}
            />
        </div>
    {/key}
{:else if pageData?.type === 'folder'}
    {@const folder = pageData.data as DocFolder}
    <div class="docs-page-content">
        <ChatHeader
            title={folder.title}
            category={catInfo.category}
            icon={catInfo.icon}
        />
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
