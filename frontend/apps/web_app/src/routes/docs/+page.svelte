<script lang="ts">
    /**
     * Docs Welcome Page
     *
     * Landing page for /docs, styled as a welcome screen matching the chat
     * welcome pattern. Shows a greeting and quick-start cards for each docs section.
     *
     * Architecture: docs/architecture/docs-web-app.md
     */
    import { text } from '@repo/ui';
    import docsData from '$lib/generated/docs-data.json';
    import type { DocFolder } from '$lib/types/docs';
    import { DOCS_FOLDER_CATEGORY, DOCS_FOLDER_ICON } from '$lib/utils/docsCategoryMap';

    const { structure } = docsData;

    /** Count all files recursively in a folder */
    function countFiles(folder: DocFolder): number {
        let count = folder.files.length;
        for (const sub of folder.folders) {
            count += countFiles(sub);
        }
        return count;
    }
</script>

<svelte:head>
    <title>Documentation | OpenMates</title>
    <meta name="description" content="OpenMates documentation — guides, architecture documentation, and API reference for OpenMates." />
    <meta property="og:title" content="OpenMates Documentation" />
    <meta property="og:description" content="Guides, architecture documentation, and API reference for OpenMates." />
    <meta property="og:type" content="website" />
    <link rel="canonical" href="https://openmates.org/docs" />
</svelte:head>

<div class="welcome-container">
    <div class="welcome-hero">
        <h1 class="welcome-title">{$text('documentation.welcome.title')}</h1>
        <p class="welcome-subtitle">{$text('documentation.welcome.subtitle')}</p>
    </div>

    <div class="quick-links">
        <!-- API Reference card -->
        <a href="/docs/api" class="section-card api-card">
            <div class="card-icon">
                <svg width="24" height="24" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M4.75 1A1.75 1.75 0 003 2.75v10.5c0 .966.784 1.75 1.75 1.75h6.5A1.75 1.75 0 0013 13.25v-10.5A1.75 1.75 0 0011.25 1h-6.5zM4.5 2.75a.25.25 0 01.25-.25h6.5a.25.25 0 01.25.25v10.5a.25.25 0 01-.25.25h-6.5a.25.25 0 01-.25-.25V2.75zM6 5a.75.75 0 000 1.5h4A.75.75 0 0010 5H6zm0 3a.75.75 0 000 1.5h4A.75.75 0 0010 8H6zm0 3a.75.75 0 000 1.5h4a.75.75 0 000-1.5H6z"/>
                </svg>
            </div>
            <div class="card-content">
                <span class="card-title">{$text('documentation.api_reference')}</span>
                <span class="card-desc">Interactive Swagger UI</span>
            </div>
        </a>

        <!-- Folder section cards -->
        {#each structure.folders as folder (folder.path)}
            {@const category = DOCS_FOLDER_CATEGORY[folder.path] || 'general_knowledge'}
            {@const fileCount = countFiles(folder)}
            <a href="/docs/{folder.path}" class="section-card">
                <div class="card-icon mate-profile {category}" style="width: 36px; height: 36px; margin: 0; animation: none; opacity: 1;"></div>
                <div class="card-content">
                    <span class="card-title">{folder.title}</span>
                    <span class="card-desc">{$text('documentation.documents_count', { values: { count: fileCount } })}</span>
                </div>
            </a>
        {/each}
    </div>
</div>

<style>
    .welcome-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 3rem 1.5rem;
        min-height: 100%;
    }

    .welcome-hero {
        text-align: center;
        margin-bottom: 2.5rem;
        max-width: 600px;
    }

    .welcome-title {
        font-size: 2rem;
        font-weight: 700;
        color: var(--color-font-primary);
        margin: 0 0 0.75rem 0;
        background: linear-gradient(135deg, var(--color-primary), var(--color-primary-dark, var(--color-primary)));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }

    .welcome-subtitle {
        font-size: 1.0625rem;
        color: var(--color-font-secondary);
        margin: 0;
        line-height: 1.5;
    }

    .quick-links {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
        gap: 0.75rem;
        width: 100%;
        max-width: 800px;
    }

    .section-card {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 1rem 1.25rem;
        border-radius: 12px;
        background-color: var(--color-grey-10);
        text-decoration: none;
        color: var(--color-font-primary);
        transition: all 0.2s ease;
        border: 1px solid var(--color-grey-25);
    }

    .section-card:hover {
        background-color: var(--color-grey-0);
        border-color: var(--color-grey-40);
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }

    /* Hide mate-profile AI badges on welcome cards */
    .section-card :global(.mate-profile::after),
    .section-card :global(.mate-profile::before) {
        display: none !important;
    }

    .card-icon {
        flex-shrink: 0;
        width: 36px;
        height: 36px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--color-primary);
        background-color: var(--color-grey-20);
        border-radius: 8px;
    }

    .api-card .card-icon {
        background-color: var(--color-primary);
        background-image: linear-gradient(135deg, #155D91, #42ABF4);
        color: var(--color-grey-0);
        border-radius: 50%;
    }

    .card-content {
        display: flex;
        flex-direction: column;
        min-width: 0;
    }

    .card-title {
        font-size: 0.9375rem;
        font-weight: 600;
    }

    .card-desc {
        font-size: 0.8125rem;
        color: var(--color-font-secondary);
    }

    @media (max-width: 600px) {
        .welcome-container {
            padding: 2rem 1rem;
        }

        .welcome-title {
            font-size: 1.5rem;
        }

        .quick-links {
            grid-template-columns: 1fr;
        }
    }
</style>
