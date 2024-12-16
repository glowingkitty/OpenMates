<script lang="ts">
  // Props for the component
  export let name: string = ''; // e.g., 'app', 'chat', 'billing'
  export let type: 'default' | 'app' | 'skill' | 'provider' | 'focus' = 'default';
  export let inline: boolean = false;
  export let poweredByAI: boolean = false;
  export let size: string | undefined = undefined; // Add size prop

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

  // Compute styles including size if provided
  $: style = size ? `width: ${size}; height: ${size}; min-width: ${size}; min-height: ${size};` : '';
</script>

<div class={className} aria-label={name} style={style}></div>