<script lang="ts">
  // Props using Svelte 5 runes
  let { 
    size = 'small',
    type,
    title = undefined,
    subtitle = undefined,
    top,
    bottom,
    secondary
  }: {
    size?: 'small' | 'large';
    type: string;
    title?: string | undefined;
    subtitle?: string | undefined;
    top: any;
    bottom: any;
    secondary: any;
  } = $props();
</script>

<div class="app-card {size} {type}">
  {@render top()}
  
  <div class="app-card-header">
    {#if title}
      <div class="app-card-h1">{title}</div>
    {/if}
    {#if subtitle}
      <div class="app-card-h3">{subtitle}</div>
    {/if}
  </div>

  {@render bottom()}
  {@render secondary()}
</div> 