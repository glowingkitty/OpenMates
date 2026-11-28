<!--
    SettingsSectionHeading — Visual section separator for settings sub-pages.

    Renders a prominent heading with a gradient-filled icon square, bold title text,
    and a gradient underline bar. Replaces the old invisible 12px uppercase
    `.section-title` pattern with the Figma "Settings subheading" design.

    Design reference: Figma "settings_menu_elements" frame (node 4946-31663)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import { resolveIconName } from '../../../utils/iconNameResolver';
    let {
        title,
        icon,
        iconClass,
        iconSrc = '',
        iconAlt = '',
    }: {
        /** Heading text displayed next to the icon */
        title: string;
        /** Subsetting icon name from icons.css (e.g., "announcement", "email", "coins").
         *  Ignored when iconClass is provided. */
        icon: string;
        /** Optional full CSS class override for the icon element (e.g., "icon app-ai").
         *  When set, replaces the default "subsetting_icon {icon}" classes. */
        iconClass?: string;
        /** Optional image (e.g. a provider logo) shown instead of the icon mask. */
        iconSrc?: string;
        /** Alt text for iconSrc. */
        iconAlt?: string;
    } = $props();
</script>

<div class="settings-section-heading">
    <div class="heading-row">
        {#if iconSrc}
            <div class="heading-icon heading-image" data-testid="settings-section-heading-image"><img src={iconSrc} alt={iconAlt} /></div>
        {:else}
            <div class="heading-icon {iconClass ?? `subsetting_icon ${icon}`}"
                style={iconClass ? undefined : `--icon-mask-image: var(--icon-url-${resolveIconName(icon)});`}></div>
        {/if}
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

    .heading-image {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0.5rem;
        background: var(--color-grey-10);
        border-radius: var(--radius-3);
        box-sizing: border-box;
    }

    .heading-image img {
        width: 100%;
        height: 100%;
        object-fit: contain;
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
