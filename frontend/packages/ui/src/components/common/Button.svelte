<script lang="ts">
    import { tooltip } from '../../actions/tooltip';
    
    // Props using Svelte 5 runes
    let { 
        ariaLabel = '',
        onClick = () => {},
        className = ''
    }: {
        ariaLabel?: string;
        onClick?: () => void;
        className?: string;
    } = $props();
</script>

<button
    class={className}
    onclick={onClick}
    aria-label={ariaLabel}
    use:tooltip
>
    <slot></slot>
</button> 