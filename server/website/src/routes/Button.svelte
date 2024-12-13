<script lang="ts">
  export let variant: 'primary' | 'secondary' = 'primary';
  export let type: 'button' | 'submit' | 'reset' = 'button';
  export let disabled: boolean = false;
</script>

<button 
  class:btn-secondary={variant === 'secondary'}
  {type}
  {disabled}
  on:click
>
  <slot />
</button>