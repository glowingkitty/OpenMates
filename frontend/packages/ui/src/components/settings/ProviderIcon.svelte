<!-- frontend/packages/ui/src/components/settings/ProviderIcon.svelte
     Dedicated component for displaying provider icons with original colors on white background.
     
     This component displays provider icons without any filters or color inversions,
     showing the original icon colors. The entire element (background + icon) has 0.5 opacity.
-->

<script lang="ts">
    // Import Icon component to ensure its CSS variables are loaded
    import Icon from '../../components/Icon.svelte';
    
    /**
     * Props for ProviderIcon component.
     */
    interface Props {
        name: string;
        size?: string;
    }
    
    let { name, size = '30px' }: Props = $props();
    
    /**
     * Get the CSS variable name for the icon URL.
     * Converts provider name to lowercase with underscores.
     */
    function getIconUrlVar(providerName: string): string {
        const normalized = providerName.toLowerCase()
            .replace(/\s+/g, '_')
            .replace(/\./g, '');
        return `--icon-url-${normalized}`;
    }
    
    /**
     * Get the icon URL CSS variable name.
     */
    let iconUrlVar = $derived(getIconUrlVar(name));
    
    /**
     * Get the computed background image style.
     * This ensures the CSS variable is properly referenced.
     */
    let backgroundImageStyle = $derived(`var(${iconUrlVar})`);
</script>

<!-- Wrapper div with white background and icon at 0.5 opacity (entire element) -->
<div 
    class="provider-icon-wrapper" 
    style={`
        width: ${size};
        height: ${size};
        --provider-bg-image: ${backgroundImageStyle};
    `}
    aria-label={name}
></div>

<style>
    .provider-icon-wrapper {
        border-radius: 6px;
        flex-shrink: 0;
        /* White background */
        background-color: #ffffff;
        /* Use CSS variable for background image */
        background-image: var(--provider-bg-image);
        /* Icon image should be 60% of container size, not edge-to-edge */
        background-size: 60%;
        background-position: center;
        background-repeat: no-repeat;
        /* 0.5 opacity for entire element */
        opacity: 0.5;
        /* No filters - show original colors */
        filter: none !important;
        /* Ensure original colors are preserved */
        -webkit-filter: none !important;
    }
</style>

