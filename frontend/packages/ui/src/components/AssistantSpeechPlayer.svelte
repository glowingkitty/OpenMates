<!-- frontend/packages/ui/src/components/AssistantSpeechPlayer.svelte -->
<!--
  Pinned player for one assistant response at a time.
  Renders duration-proportional paragraph regions and browser playback controls.
  The parent places this in normal composer flow so transcript space is reserved.
  Audio URLs and plaintext are intentionally absent from rendered state.
-->
<script lang="ts">
  import { assistantSpeechController } from '../services/assistantSpeechController';

  const player = assistantSpeechController.player;
  let isPlaying = $derived($player.status === 'playing');
  let isVisible = $derived(
    $player.responseId !== null &&
    !['idle', 'stopped'].includes($player.status),
  );
  let statusLabel = $derived.by(() => {
    if ($player.error) return $player.error;
    if ($player.status === 'waiting_for_segment') return 'Preparing voice response';
    if ($player.status === 'blocked_by_autoplay') return 'Tap play to continue';
    if ($player.status === 'paused') return 'Voice response paused';
    if ($player.status === 'failed') return 'Voice response unavailable';
    return 'Playing voice response';
  });
</script>

{#if isVisible}
  <section class="assistant-speech-player" data-testid="assistant-speech-player" aria-label="Voice response player">
    <div class="assistant-speech-heading">
      <span class="assistant-speech-pulse" class:playing={isPlaying} aria-hidden="true"></span>
      <span data-testid="assistant-speech-status">{statusLabel}</span>
    </div>

    <div class="assistant-speech-waveform" data-testid="assistant-speech-waveform" aria-label="Response paragraphs">
      {#each $player.regions as region (region.segmentId)}
        <button
          type="button"
          class="assistant-speech-region"
          class:active={region.active}
          class:ready={region.status === 'ready'}
          class:failed={region.status === 'failed'}
          style:flex-grow={Math.max(0.04, region.end - region.start)}
          aria-label="Play paragraph"
          onclick={() => void assistantSpeechController.selectSegment(region.segmentId)}
        ></button>
      {/each}
    </div>

    <div class="assistant-speech-controls">
      <button type="button" aria-label="Previous paragraph" onclick={() => void assistantSpeechController.previous()}>Previous</button>
      {#if $player.status === 'blocked_by_autoplay'}
        <button class="primary" type="button" data-testid="assistant-speech-continue" onclick={() => void assistantSpeechController.continueAfterUserGesture()}>Continue</button>
      {:else if isPlaying}
        <button class="primary" type="button" aria-label="Pause voice response" onclick={() => assistantSpeechController.pause()}>Pause</button>
      {:else}
        <button class="primary" type="button" aria-label="Play voice response" onclick={() => void assistantSpeechController.play()}>Play</button>
      {/if}
      <button type="button" aria-label="Next paragraph" onclick={() => void assistantSpeechController.next()}>Next</button>
      <button type="button" aria-label="Stop voice response" onclick={() => void assistantSpeechController.stop()}>Stop</button>
    </div>
  </section>
{/if}

<style>
  .assistant-speech-player {
    width: min(629px, calc(100% - 24px));
    margin: 0 auto var(--spacing-5);
    padding: var(--spacing-5) var(--spacing-6);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-12);
    background: color-mix(in srgb, var(--color-grey-10) 92%, transparent);
    box-shadow: 0 8px 28px color-mix(in srgb, var(--color-grey-100) 8%, transparent);
    backdrop-filter: blur(16px);
  }

  .assistant-speech-heading {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    color: var(--color-grey-70);
    font-size: var(--font-size-small);
  }

  .assistant-speech-pulse {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--color-grey-40);
  }

  .assistant-speech-pulse.playing {
    background: var(--color-accent);
    box-shadow: 0 0 0 5px color-mix(in srgb, var(--color-accent) 15%, transparent);
  }

  .assistant-speech-waveform {
    display: flex;
    gap: 3px;
    height: 30px;
    margin: var(--spacing-5) 0;
    align-items: stretch;
  }

  .assistant-speech-region {
    min-width: 8px;
    border: 0;
    border-radius: var(--radius-4);
    background: var(--color-grey-20);
    cursor: pointer;
  }

  .assistant-speech-region.ready { background: var(--color-grey-40); }
  .assistant-speech-region.active { background: var(--color-accent); }
  .assistant-speech-region.failed { background: var(--color-error); }

  .assistant-speech-controls {
    display: flex;
    gap: var(--spacing-3);
    align-items: center;
    justify-content: center;
  }

  .assistant-speech-controls button {
    min-height: 34px;
    padding: 0 var(--spacing-4);
    border: 1px solid var(--color-grey-20);
    border-radius: 999px;
    color: var(--color-grey-70);
    background: transparent;
    cursor: pointer;
    font: inherit;
    font-size: var(--font-size-xxs);
  }

  .assistant-speech-controls button.primary {
    color: white;
    border-color: var(--color-accent);
    background: var(--color-accent);
  }

  @media (max-width: 560px) {
    .assistant-speech-player {
      width: calc(100% - 16px);
      padding: var(--spacing-4);
    }

    .assistant-speech-controls {
      gap: 4px;
    }

    .assistant-speech-controls button {
      padding: 0 9px;
      font-size: var(--font-size-xxs);
    }
  }
</style>
