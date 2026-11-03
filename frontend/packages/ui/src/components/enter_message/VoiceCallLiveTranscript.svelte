<!--
  Live voice-call transcript inside the composer.
  Shows the user's in-progress utterance as translucent text whose new words
  fade in, so the caller sees what the system understood before the final turn
  becomes a regular chat message. Display only: it never edits the draft.
-->
<script lang="ts">
    interface Props {
        text: string;
        /** Final transcript sent for processing; awaiting its chat-history row. */
        submitted: boolean;
        /** Render over an empty editor instead of below an existing draft. */
        overlay: boolean;
    }

    let { text, submitted, overlay }: Props = $props();

    // Index keys keep earlier words mounted while STT appends, so only new
    // words run the fade-in; corrected words update in place.
    const words = $derived(text.trim().split(/\s+/).filter(Boolean));
</script>

<div
    class="call-live-transcript"
    class:overlay
    class:submitted
    data-testid="voice-call-live-transcript"
    data-submitted={submitted}
    aria-live="polite"
>
    {#each words as word, index (index)}
        <span class="call-live-word" data-testid="voice-call-live-word">{word}</span>{index < words.length - 1 ? ' ' : ''}
    {/each}
</div>

<style>
    .call-live-transcript {
        position: relative;
        z-index: 2;
        padding-top: 0.5rem;
        color: var(--color-font-primary);
        opacity: 0.45;
        line-height: 1.6;
        white-space: normal;
        overflow-wrap: anywhere;
        pointer-events: none;
        transition: opacity 200ms ease;
    }

    .call-live-transcript.overlay {
        grid-area: 1 / 1;
    }

    .call-live-transcript.submitted {
        opacity: 0.6;
    }

    .call-live-word {
        animation: call-live-word-in 320ms ease-out both;
    }

    @keyframes call-live-word-in {
        from { opacity: 0; filter: blur(2px); }
        to { opacity: 1; filter: blur(0); }
    }

    @media (prefers-reduced-motion: reduce) {
        .call-live-word { animation: none; }
        .call-live-transcript { transition: none; }
    }
</style>
