<!--
  frontend/packages/ui/src/components/embeds/EmbedHeaderCtaButton.svelte

  Shared CTA button for the EmbedHeader peek-out area.
  Renders as <a> (when href is provided) or <button> (when onclick is provided).
  All fullscreen embeds must use this for their header CTA to ensure consistent styling.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import { resolveIconName } from '../../utils/iconNameResolver';
  interface Props {
    /** Button label text, e.g. "Open on ExampleClinicA" */
    label: string;
    /** If set, renders as an <a> tag with target="_blank" */
    href?: string;
    /** If set (and no href), renders as <button> with this click handler */
    onclick?: () => void;
    /** Visual variant: 'primary' (default), 'secondary', 'destructive', 'loading' (spinner), 'fallback' (grey) */
    variant?: 'primary' | 'secondary' | 'destructive' | 'loading' | 'fallback';
    /** Optional data-testid for E2E targeting */
    testId?: string;
    /** Existing icon asset, retaining a spoken label when visible copy is omitted. */
    iconName?: string;
    iconOnly?: boolean;
    pressed?: boolean;
  }

  let {
    label,
    href,
    onclick,
    variant = 'primary',
    testId,
    iconName,
    iconOnly = false,
    pressed,
  }: Props = $props();
</script>

{#if href}
  <a
    class="embed-header-cta {variant}"
    data-testid={testId}
    {href}
    target="_blank"
    rel="noopener noreferrer"
    onclick={onclick}
  >
    {label}
  </a>
{:else if variant === 'loading'}
  <div class="embed-header-cta loading" data-testid={testId}>
    <span class="cta-spinner"></span>
  </div>
{:else}
  <button type="button" class="embed-header-cta {variant}" class:icon-only={iconOnly} class:selected={pressed === true} data-testid={testId} aria-label={iconOnly ? label : undefined} aria-pressed={pressed} onclick={onclick}>
    {#if iconName}<span class="clickable-icon cta-icon" style:--icon-name={iconName} style:--icon-url={`var(--icon-url-${resolveIconName(iconName)})`} style:mask-image="var(--icon-url)" aria-hidden="true"></span>{/if}
    {#if !iconOnly}{label}{/if}
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

  .embed-header-cta.secondary {
    min-width: 120px;
    background-color: var(--color-grey-20);
    color: var(--color-font-primary);
    border: 1px solid var(--color-grey-30);
  }

  .embed-header-cta.secondary:hover {
    background-color: var(--color-grey-30);
  }

  .cta-icon { width: 24px; height: 24px; background: currentColor; cursor: inherit; }
  .embed-header-cta.icon-only {
    width: 48px;
    height: 48px;
    min-width: 48px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-full);
    background: var(--color-font-button);
    color: var(--color-button-secondary);
    transition: background-color var(--duration-normal), color var(--duration-normal), transform var(--duration-fast);
  }
  .embed-header-cta.icon-only.selected { background: var(--color-app-health-start); color: var(--color-font-button); }
  .embed-header-cta.icon-only:hover { filter: brightness(.96); }
  .embed-header-cta.icon-only:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 3px; }

  .embed-header-cta.destructive {
    min-width: 120px;
    background-color: #ffffff;
    color: #b91c1c;
    border: 2px solid #ffffff;
    filter: drop-shadow(0px 4px 8px rgba(0, 0, 0, 0.28));
  }

  .embed-header-cta.destructive:hover {
    background-color: #fee2e2;
    border-color: #fee2e2;
  }

  :global(.embed-header-cta-group) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-wrap: wrap;
    gap: var(--spacing-4);
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
