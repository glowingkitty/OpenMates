<!--
    SettingsPageHeader — Page title and description for settings sub-pages.

    Replaces custom `.page-title` + `.page-description`, `.export-header`
    patterns across settings pages with a single canonical component.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    let {
        title,
        description = '',
    }: {
        title: string;
        description?: string;
    } = $props();
</script>

<div class="settings-page-header">
    <h2 class="page-title">{title}</h2>
    {#if description}
        <p class="page-description">{description}</p>
    {/if}
</div>

<style>
    .settings-page-header {
        padding: 0 0.625rem;
        margin-bottom: 1.5rem;
    }

    .page-title {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: var(--font-size-h2, 1.5rem);
        font-weight: 600;
        color: var(--color-font-primary);
        margin: 0 0 0.5rem 0;
    }

    .page-description {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: var(--font-size-p, 0.875rem);
        color: var(--color-font-secondary);
        line-height: 1.5;
        margin: 0;
    }
</style>
