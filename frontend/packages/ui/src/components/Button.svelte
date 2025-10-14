<script lang="ts">
  // Props using Svelte 5 runes
  let { 
    variant = 'primary',
    type = 'button',
    disabled = false,
    onclick = () => {},
    children
  }: {
    variant?: 'primary' | 'secondary';
    type?: 'button' | 'submit' | 'reset';
    disabled?: boolean;
    onclick?: (event: MouseEvent) => void;
    children: any;
  } = $props();
</script>

<button 
  class:btn-secondary={variant === 'secondary'}
  {type}
  {disabled}
  onclick={onclick}
>
  {@render children()}
</button>