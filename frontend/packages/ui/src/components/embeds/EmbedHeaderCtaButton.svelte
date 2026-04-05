<!--
  frontend/packages/ui/src/components/embeds/EmbedHeaderCtaButton.svelte

  Shared CTA button for the EmbedHeader peek-out area.
  Renders as <a> (when href is provided) or <button> (when onclick is provided).
  All fullscreen embeds must use this for their header CTA to ensure consistent styling.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  interface Props {
    /** Button label text, e.g. "Open on Doctolib" */
    label: string;
    /** If set, renders as an <a> tag with target="_blank" */
    href?: string;
    /** If set (and no href), renders as <button> with this click handler */
    onclick?: () => void;
    /** Visual variant: 'primary' (default), 'loading' (spinner), 'fallback' (grey) */
    variant?: 'primary' | 'loading' | 'fallback';
  }

  let {
    label,
    href,
    onclick,
    variant = 'primary',
  }: Props = $props();
</script>

{#if href}
  <a
    class="embed-header-cta {variant}"
    {href}
    target="_blank"
    rel="noopener noreferrer"
  >
    {label}
  </a>
{:else if variant === 'loading'}
  <div class="embed-header-cta loading">
    <span class="cta-spinner"></span>
  </div>
{:else}
  <button class="embed-header-cta {variant}" onclick={onclick}>
    {label}
  </button>
{/if}

<style>
  .embed-header-cta {
    background-color: var(--color-button-primary);
    color: white;
    border: none;
    border-radius: 15px;
    padding: var(--spacing-6) var(--spacing-12);
    font-family: 'Lexend Deca', sans-serif;
    font-size: var(--font-size-p);
    font-weight: 500;
    cursor: pointer;
    transition: background-color var(--duration-normal), transform var(--duration-fast);
    min-width: 200px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    text-decoration: none;
    filter: drop-shadow(0px 4px 4px rgba(0, 0, 0, 0.25));
  }

  .embed-header-cta:hover {
    background-color: var(--color-button-primary-hover);
    transform: translateY(-1px);
  }

  .embed-header-cta:active {
    background-color: var(--color-button-primary-pressed);
    transform: translateY(0);
  }

  /* Fallback variant (grey) for error states */
  .embed-header-cta.fallback {
    background-color: var(--color-grey-70, #555);
  }

  .embed-header-cta.fallback:hover {
    background-color: var(--color-grey-80, #444);
  }

  /* Loading variant (disabled spinner) */
  .embed-header-cta.loading {
    background-color: var(--color-grey-30, #e0e0e0);
    cursor: default;
    filter: none;
  }

  .embed-header-cta.loading:hover {
    background-color: var(--color-grey-30, #e0e0e0);
    transform: none;
  }

  .cta-spinner {
    width: 20px;
    height: 20px;
    border: 2.5px solid var(--color-grey-50, #999);
    border-top-color: var(--color-grey-80, #444);
    border-radius: 50%;
    animation: cta-spin 0.8s linear infinite;
  }

  @keyframes cta-spin {
    to { transform: rotate(360deg); }
  }

  @container fullscreen (max-width: 600px) {
    .embed-header-cta {
      padding: var(--spacing-5) var(--spacing-10);
      min-width: 160px;
    }
  }
</style>
