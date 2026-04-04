<!--
    SettingsSectionHeading — Visual section separator for settings sub-pages.

    Renders a prominent heading with a gradient-filled icon square, bold title text,
    and a gradient underline bar. Replaces the old invisible 12px uppercase
    `.section-title` pattern with the Figma "Settings subheading" design.

    Design reference: Figma "settings_menu_elements" frame (node 4946-31663)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    let {
        title,
        icon,
        iconClass,
    }: {
        /** Heading text displayed next to the icon */
        title: string;
        /** Subsetting icon name from icons.css (e.g., "announcement", "email", "coins").
         *  Ignored when iconClass is provided. */
        icon: string;
        /** Optional full CSS class override for the icon element (e.g., "icon app-ai").
         *  When set, replaces the default "subsetting_icon {icon}" classes. */
        iconClass?: string;
    } = $props();
</script>

<div class="settings-section-heading">
    <div class="heading-row">
        <div class="heading-icon {iconClass ?? `subsetting_icon ${icon}`}"></div>
        <h3 class="heading-text">{title}</h3>
    </div>
    <div class="heading-bar"></div>
</div>

<style>
    .settings-section-heading {
        padding: 0 0.625rem;
        margin: 1.5rem 0 1rem 0;
    }

    .heading-row {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.5rem;
    }

    /* Keep subsetting_icon dimensions, gradient icon is the default behavior */
    .heading-icon {
        width: 44px;
        height: 44px;
        min-width: 44px;
    }

    .heading-text {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 1rem;
        font-weight: 700;
        color: var(--color-grey-100);
        margin: 0;
    }

    .heading-bar {
        height: 4px;
        width: 100%;
        border-radius: 11px;
        background: var(--color-primary);
    }
</style>
