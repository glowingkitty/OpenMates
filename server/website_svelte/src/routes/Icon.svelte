<script lang="ts">
  // Props for the component
  export let name: string = ''; // e.g., 'app', 'chat', 'billing'
  export let type: 'default' | 'app' | 'skill' | 'provider' | 'focus' = 'default';
  export let inline: boolean = false;
  export let poweredByAI: boolean = false;

  // Compute the final class name
  $: className = [
    'icon',
    inline ? 'inline' : '',
    type === 'provider' ? `provider-${name}` :
    type === 'default' ? name : `${type}-${name}`,
    poweredByAI ? 'powered_by_ai' : ''
  ].filter(Boolean).join(' ');
</script>

<div class={className} aria-label={name}>
  <slot />
</div>