<!--
  ProcessingWheel provides the compact chat organization/activity surface.
  Uses shared design tokens and accessible native controls.
  Navigation stays readable within the narrow sidebar.
  Global lifecycle stores remain separate from rendering.
  Colocated fixtures provide isolated component verification.
-->
<script lang="ts">
  import { text } from '@repo/ui';
</script>

<span class="processing-wheel" role="img" aria-label={$text('common.processing')} data-testid="chat-processing-wheel"></span>

<style>
  .processing-wheel {
    display: inline-block;
    inline-size: 1.5rem;
    block-size: 1.5rem;
    flex: 0 0 1.5rem;
    box-sizing: border-box;
    border: 2px solid var(--color-grey-30);
    border-block-start-color: var(--color-font-primary);
    border-radius: var(--radius-full);
    animation: processing-wheel-rotate 900ms linear infinite;
  }
  @keyframes processing-wheel-rotate { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .processing-wheel { animation: none; } }
</style>
