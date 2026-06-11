<!-- frontend/packages/ui/src/components/settings/ProviderIcon.svelte
     Dedicated component for displaying provider icons with original colors on white background.
     
     This component displays provider icons without any filters or color inversions,
     showing the original icon colors. The entire element (background + icon) has 0.5 opacity.
-->

<script lang="ts">
    import { findProviderByName } from '../../data/providersMetadata';
    import { getProviderIconUrl } from '../../data/providerIcons';

    /**
     * Props for ProviderIcon component.
     */
    interface Props {
        name: string;
        size?: string;
    }
    
    let { name, size = '30px' }: Props = $props();
    
    let providerMeta = $derived(findProviderByName(name));
    let iconUrl = $derived(providerMeta ? getProviderIconUrl(providerMeta.logo_svg) : getProviderIconUrl('icons/server.svg'));
    let providerDisplayName = $derived(providerMeta?.name || name);
    let isOpenMatesProvider = $derived(providerMeta?.id === 'openmates');
</script>

<!-- Wrapper keeps all provider logos readable on gradients and dark themes. -->
<div 
    class="provider-icon-wrapper" 
    class:openmates-provider={isOpenMatesProvider}
    data-testid="provider-icon"
    data-provider-name={providerDisplayName}
    style={`
        width: ${size};
        height: ${size};
    `}
    aria-label={providerDisplayName}
>
    <img
        src={iconUrl}
        alt={providerDisplayName}
        data-testid="provider-icon-image"
        data-provider-name={providerDisplayName}
    />
</div>

<style>
    .provider-icon-wrapper {
        border-radius: var(--radius-2);
        flex-shrink: 0;
        /* Always-white background (theme-independent — provider logos need light bg in both themes) */
        background-color: #ffffff;
        /* No filters - show original colors */
        filter: none !important;
        /* Ensure original colors are preserved */
        -webkit-filter: none !important;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        padding: 4px;
        box-sizing: border-box;
    }

    .provider-icon-wrapper img {
        width: 100%;
        height: 100%;
        object-fit: contain;
        display: block;
        filter: none !important;
        -webkit-filter: none !important;
    }

    .provider-icon-wrapper.openmates-provider {
        background-color: transparent;
        padding: 0;
    }

    .provider-icon-wrapper.openmates-provider img {
        object-fit: cover;
    }
</style>
