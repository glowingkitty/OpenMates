<script lang="ts">
  import LandingExistingEmbed from './LandingExistingEmbed.svelte';
  import PublicAnimation from '@repo/public-site/components/landing/LandingFeatureAnimation.svelte';
  // standalone: the UI-free public website path, with the public package's own event embed.
  let { section = 'actionable', active = true, language = 'en', standalone = false }: {
    section?: 'actionable' | 'privacy'; active?: boolean; language?: string; standalone?: boolean;
  } = $props();
  let completed = $state(false);
</script>

<div data-testid="landing-animation-fixture" data-completed={completed ? 'true' : 'false'}>
  {#if standalone}
    <PublicAnimation {section} {active} {language} onComplete={() => { completed = true; }} />
  {:else}
  <PublicAnimation {section} {active} {language} onComplete={() => { completed = true; }}>
    {#snippet eventPreview(activate, onFullscreen, previewLanguage)}
      <LandingExistingEmbed mode="preview" {activate} {onFullscreen} language={previewLanguage} />
    {/snippet}
    {#snippet eventFullscreen(fullscreenLanguage, showCalendar)}
      <LandingExistingEmbed mode="fullscreen" language={fullscreenLanguage} {showCalendar} />
    {/snippet}
  </PublicAnimation>
  {/if}
</div>

<style>
  /* The production story-stage supplies this width. Size containment means
     the bare fixture cannot derive an intrinsic width from absolute scenes. */
  [data-testid="landing-animation-fixture"] { width: min(100%, 58rem); min-width: 0; }
</style>
