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
    type === 'default' ? name : `${type}-${name}`,
    type === 'provider' ? 'provider-icon' : '',
    type === 'skill' ? 'skill-icon' : '',
    type === 'focus' ? 'focus-icon' : '',
    poweredByAI ? 'powered_by_ai' : ''
  ].filter(Boolean).join(' ');
</script>

<div class={className} aria-label={name}></div>
