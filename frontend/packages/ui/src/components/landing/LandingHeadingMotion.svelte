<script lang="ts">
  /**
   * LandingHeadingMotion.svelte
   *
   * Shared heading motion envelope for every logged-out landing slide.
   * Parent components own geometry; this wrapper owns consistent vertical
   * entry, continuous center drift, exit, and hidden visual states.
   */

  import type { Snippet } from 'svelte';

  export type LandingHeadingMotionPhase = 'entering' | 'visible' | 'exiting' | 'hidden';

  interface Props {
    phase: LandingHeadingMotionPhase;
    testId: string;
    children: Snippet;
  }

  let { phase, testId, children }: Props = $props();
</script>

<div
  class="landing-heading-motion"
  class:entering={phase === 'entering'}
  class:visible={phase === 'visible'}
  class:exiting={phase === 'exiting'}
  class:hidden={phase === 'hidden'}
  data-testid={testId}
  data-motion-phase={phase}
  data-enter-direction="from-below"
  data-exit-direction="to-above"
>
  {@render children()}
</div>

<style>
  .landing-heading-motion {
    display: flex;
    flex: 1 1 auto;
    flex-direction: inherit;
    align-items: inherit;
    justify-content: inherit;
    gap: inherit;
    width: 100%;
    min-width: 0;
    opacity: 1;
    transform: translate3d(0, 0, 0);
    transition:
      opacity 420ms ease,
      transform 420ms cubic-bezier(0.22, 1, 0.36, 1);
  }

  .landing-heading-motion.entering {
    opacity: 0;
    transform: translate3d(0, 36px, 0) scale(0.96);
  }

  .landing-heading-motion.visible {
    animation: landingHeadingCenterDrift 1800ms ease-in-out infinite alternate;
  }

  .landing-heading-motion.exiting {
    opacity: 0;
    transform: translate3d(0, -36px, 0) scale(0.98);
  }

  .landing-heading-motion.hidden {
    opacity: 0;
    transform: translate3d(0, -20px, 0);
    transition: none;
  }

  @keyframes landingHeadingCenterDrift {
    from { translate: 0 3px; scale: 1; }
    to { translate: 0 -3px; scale: 1.018; }
  }

  @media (prefers-reduced-motion: reduce) {
    .landing-heading-motion {
      transition-duration: 1ms;
      animation: none;
    }
  }
</style>
