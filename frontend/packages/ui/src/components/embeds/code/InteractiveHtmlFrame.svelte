<!--
  frontend/packages/ui/src/components/embeds/code/InteractiveHtmlFrame.svelte

  Live, sandboxed rendering of an HTML code embed (inline CSS + JavaScript).
  Security model: see interactiveHtmlSandbox.ts. The frame is mounted only
  while it is near the viewport, so long chats do not run every animation at
  once. In preview cards it is inert (no focus, no pointer input) so a click
  opens the fullscreen view; in fullscreen it is interactive.
  If the frame ever loads a second document (a navigation slipped past the
  guards), it is removed and replaced by a notice.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import { buildInteractiveHtmlSrcdoc, INTERACTIVE_HTML_SANDBOX } from './interactiveHtmlSandbox';

  interface Props {
    /** Raw HTML source from the code embed */
    code: string;
    /** Accessible title for the frame */
    title: string;
    /** Interactive (fullscreen) or inert (preview card) */
    interactive: boolean;
  }

  let { code, title, interactive }: Props = $props();

  let host: HTMLDivElement | undefined = $state();
  let nearViewport = $state(false);
  let blocked = $state(false);
  let loadCount = 0;

  let srcdoc = $derived(buildInteractiveHtmlSrcdoc(code));

  $effect(() => {
    // A new source is a new document: reset the navigation detector.
    void srcdoc;
    loadCount = 0;
    blocked = false;
  });

  $effect(() => {
    if (!host) return;
    const observer = new IntersectionObserver(
      (entries) => {
        nearViewport = entries.some((entry) => entry.isIntersecting);
      },
      { rootMargin: '200px' }
    );
    observer.observe(host);
    return () => observer.disconnect();
  });

  function handleLoad() {
    loadCount += 1;
    if (loadCount > 1) blocked = true;
  }
</script>

<div
  class="interactive-html-frame"
  class:inert-preview={!interactive}
  bind:this={host}
  inert={!interactive}
  data-testid="interactive-html-frame"
>
  {#if blocked}
    <div class="interactive-html-blocked" data-testid="interactive-html-blocked">
      {$text('app_skills.code.interactive_html_blocked')}
    </div>
  {:else if nearViewport}
    <iframe
      {title}
      {srcdoc}
      sandbox={INTERACTIVE_HTML_SANDBOX}
      allow=""
      referrerpolicy="no-referrer"
      loading="lazy"
      data-testid="interactive-html-iframe"
      onload={handleLoad}
    ></iframe>
  {/if}
</div>

<style>
  .interactive-html-frame {
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
    background-color: var(--color-grey-0);
  }

  .interactive-html-frame.inert-preview {
    pointer-events: none;
  }

  iframe {
    display: block;
    width: 100%;
    height: 100%;
    border: 0;
    background-color: var(--color-grey-0);
  }

  .interactive-html-blocked {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    padding: var(--spacing-8);
    color: var(--color-font-secondary);
    text-align: center;
  }
</style>
