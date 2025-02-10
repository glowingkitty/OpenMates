<script lang="ts">
    import { tooltip } from '../../actions/tooltip';
    
    export let ariaLabel: string = '';
    export let onClick: () => void = () => {};
    export let className: string = '';
</script>

<button
    class={className}
    on:click={onClick}
    aria-label={ariaLabel}
    use:tooltip
>
    <slot></slot>
</button> 