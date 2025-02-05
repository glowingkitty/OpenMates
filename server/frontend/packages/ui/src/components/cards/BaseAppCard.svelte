<script lang="ts">
  // Base props that all cards share
  export let size: 'small' | 'large' = 'small';
  export let type: string;
  
  // Optional common props
  export let title: string | undefined = undefined;
  export let subtitle: string | undefined = undefined;
</script>

<div class="app-card {size} {type}">
  <slot name="top"></slot>
  
  <div class="app-card-header">
    {#if title}
      <div class="app-card-h1">{title}</div>
    {/if}
    {#if subtitle}
      <div class="app-card-h3">{subtitle}</div>
    {/if}
  </div>

  <slot name="bottom"></slot>
  <slot name="secondary"></slot>
</div> 