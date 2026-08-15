<script lang="ts">
  /**
   * LandingSubslideMotion.svelte
   *
   * Reusable keyed enter, dwell, and exit envelope for landing-story scenes.
   * It preserves the approved Actionable slide rhythm while allowing privacy
   * and later stories to provide their own deterministic scene content.
   */

  import type { Snippet } from 'svelte';

  interface Props {
    playing: boolean;
    durationMs: number;
    stage: string;
    children: Snippet;
  }

  let { playing, durationMs, stage, children }: Props = $props();
</script>

<div
  class="landing-subslide-motion"
  class:playing
  data-testid="landing-subslide-motion"
  data-stage={stage}
  style={`--landing-subslide-duration: ${durationMs}ms`}
>
  {@render children()}
</div>

<style>
  .landing-subslide-motion {
    display: grid;
    place-items: center;
    width: 100%;
    height: 100%;
    min-width: 0;
    transform-origin: center;
  }

  .landing-subslide-motion.playing {
    animation: landingSubslideFlow var(--landing-subslide-duration) linear both;
  }

  .landing-subslide-motion:not(.playing) {
    opacity: 0;
  }

  @keyframes landingSubslideFlow {
    0% {
      opacity: 0;
      transform: translate3d(0, 24px, 0) scale(0.96);
      animation-timing-function: cubic-bezier(0.16, 1, 0.3, 1);
    }
    30% {
      opacity: 1;
      transform: translate3d(0, 4px, 0) scale(0.96);
      animation-timing-function: linear;
    }
    68% {
      opacity: 1;
      transform: translate3d(0, -4px, 0) scale(1);
      animation-timing-function: cubic-bezier(0.7, 0, 1, 0.5);
    }
    100% {
      opacity: 0;
      transform: translate3d(0, -36px, 0) scale(0.78);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .landing-subslide-motion.playing {
      animation-name: landingSubslideFade;
    }
  }

  @keyframes landingSubslideFade {
    0%, 100% { opacity: 0; }
    16%, 84% { opacity: 1; }
  }
</style>
