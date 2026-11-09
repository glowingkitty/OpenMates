<!--
  frontend/packages/ui/src/components/embeds/code/ProgressiveHtmlFrame.svelte

  Read-only preview of HTML that is still being streamed. The partial document
  is rendered in an iframe whose sandbox has no tokens (no scripts) after all
  script elements, including an unterminated trailing one, are stripped.
  Re-renders are throttled. Once the embed finishes, the parent switches to
  InteractiveHtmlFrame (unchanged sandbox and CSP).
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import {
    buildProgressiveHtmlDocument,
    createThrottle,
    PROGRESSIVE_HTML_SANDBOX,
    PROGRESSIVE_RENDER_INTERVAL_MS
  } from './progressiveRender';

  interface Props {
    /** Partial HTML source */
    code: string;
    /** Accessible title for the frame */
    title: string;
  }

  let { code, title }: Props = $props();

  let srcdoc = $state<string | null>(null);
  const throttle = createThrottle(PROGRESSIVE_RENDER_INTERVAL_MS);

  $effect(() => {
    const source = code;
    throttle.schedule(() => {
      const doc = buildProgressiveHtmlDocument(source);
      if (doc !== null) srcdoc = doc; // keep the last good frame otherwise
    });
  });

  $effect(() => () => throttle.cancel());
</script>

<div class="progressive-html-frame" inert data-testid="progressive-html-frame">
  {#if srcdoc}
    <iframe
      {title}
      {srcdoc}
      sandbox={PROGRESSIVE_HTML_SANDBOX}
      allow=""
      referrerpolicy="no-referrer"
      data-testid="progressive-html-iframe"
    ></iframe>
  {:else}
    <div class="progressive-html-pending" data-testid="progressive-html-pending">
      {$text('common.processing')}
    </div>
  {/if}
</div>

<style>
  .progressive-html-frame {
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
    pointer-events: none;
    background-color: var(--color-grey-0);
  }

  iframe {
    display: block;
    width: 100%;
    height: 100%;
    border: 0;
    background-color: var(--color-grey-0);
  }

  .progressive-html-pending {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--color-font-secondary);
  }
</style>
