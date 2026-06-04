<!--
  frontend/packages/ui/src/components/interactive_questions/renderers/SwipeQuestion.svelte

  Swipe-type interactive question component (binary card stack decision).
  Renders a visual stack of cards where users swipe right (like) or left (dislike).
  Uses Svelte 5 Runes for properties and reactivity.

  Architecture: Svelte 5 Socratic assessment UI
-->

<script lang="ts">
  import type { SwipeQuestionData } from '../types';

  let {
    data,
    value = $bindable(null),
    isValid = $bindable(false),
    disabled = false,
    answeredValue = null
  } = $props<{
    data: SwipeQuestionData;
    value: { id: string; swipes: Record<string, 'like' | 'dislike'> } | null;
    isValid: boolean;
    disabled?: boolean;
    answeredValue?: Record<string, 'like' | 'dislike'> | null;
  }>();

  // Internal swipe state records: { [cardId]: 'like' | 'dislike' }
  let swipesRecord = $state<Record<string, 'like' | 'dislike'>>({});
  let activeCardIndex = $state(0);

  // Sync if locked/answered
  $effect(() => {
    if (disabled && answeredValue) {
      swipesRecord = answeredValue;
      activeCardIndex = data.cards.length; // Exhaust the stack
      isValid = true;
    }
  });

  // Reset swipes if parent clears the value
  $effect(() => {
    if (value === null && !disabled) {
      swipesRecord = {};
      activeCardIndex = 0;
    }
  });

  // Handle Swipe/Decision on active card
  function handleDecision(decision: 'like' | 'dislike') {
    if (disabled || activeCardIndex >= data.cards.length) return;

    const activeCard = data.cards[activeCardIndex];
    swipesRecord = { ...swipesRecord, [activeCard.id]: decision };
    activeCardIndex += 1;

    // Stack is fully swiped
    if (activeCardIndex >= data.cards.length) {
      isValid = true;
      value = { id: data.id, swipes: swipesRecord };
    }
  }

  // Reset/Rewind swipes
  function handleRewind() {
    if (disabled) return;
    swipesRecord = {};
    activeCardIndex = 0;
    isValid = false;
    value = null;
  }
</script>

<div class="swipe-question" class:disabled>
  <div class="cards-stack">
    {#if activeCardIndex < data.cards.length}
      {#each data.cards as card, idx (card.id)}
        {#if idx >= activeCardIndex}
          <div
            class="swipe-card"
            class:top-card={idx === activeCardIndex}
            style="transform: scale({1 - (idx - activeCardIndex) * 0.05}) translateY({(idx - activeCardIndex) * -8}px); z-index: {100 - idx};"
          >
            {#if card.image_url}
              <img src={card.image_url} alt={card.text} class="card-image" />
            {/if}
            <div class="card-content">
              <p class="card-text">{card.text}</p>
            </div>
          </div>
        {/if}
      {/each}
    {:else}
      <div class="stack-end-card">
        <svg viewBox="0 0 24 24" class="check-badge">
          <path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
        </svg>
        <p class="stack-end-text">All cards reviewed!</p>
        {#if !disabled}
          <button class="btn-rewind" onclick={handleRewind}>Start Over</button>
        {/if}
      </div>
    {/if}
  </div>

  {#if activeCardIndex < data.cards.length && !disabled}
    <div class="action-buttons">
      <button class="btn-action btn-dislike" onclick={() => handleDecision('dislike')}>
        <svg viewBox="0 0 24 24" class="action-icon">
          <path fill="currentColor" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
        </svg>
        <span>Dislike</span>
      </button>

      <button class="btn-action btn-like" onclick={() => handleDecision('like')}>
        <svg viewBox="0 0 24 24" class="action-icon">
          <path fill="currentColor" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
        </svg>
        <span>Like</span>
      </button>
    </div>
  {/if}
</div>

<style>
  .cards-stack {
    position: relative;
    height: 200px;
    width: 100%;
    margin-bottom: var(--spacing-20, 20px);
  }

  .swipe-card {
    position: absolute;
    top: 15px;
    left: 0;
    right: 0;
    bottom: 0;
    background: var(--color-grey-0, #ffffff);
    border: 1px solid var(--color-grey-20, #e9ecef);
    border-radius: var(--radius-12, 12px);
    box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.1));
    overflow: hidden;
    display: flex;
    flex-direction: column;
    transition: transform 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.15), border-color 0.2s ease;
  }

  .swipe-card.top-card {
    border-color: var(--color-grey-30, #dee2e6);
    box-shadow: var(--shadow-md, 0 4px 6px rgba(0,0,0,0.08));
  }

  .card-image {
    width: 100%;
    height: 100px;
    object-fit: cover;
    border-bottom: 1px solid var(--color-grey-20, #e9ecef);
  }

  .card-content {
    padding: var(--spacing-12, 12px);
    flex-grow: 1;
    overflow-y: auto;
    display: flex;
    align-items: center;
  }

  .card-text {
    font-size: var(--font-size-p, 14px);
    line-height: 1.4;
    color: var(--color-font-primary, #212529);
    margin: 0;
  }

  .stack-end-card {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: var(--color-grey-10, #f8f9fa);
    border: 1px dashed var(--color-grey-30, #dee2e6);
    border-radius: var(--radius-12, 12px);
  }

  .check-badge {
    width: 48px;
    height: 48px;
    color: var(--color-success, #40c057);
    margin-bottom: var(--spacing-8, 8px);
  }

  .stack-end-text {
    font-size: var(--font-size-p, 15px);
    font-weight: 500;
    color: var(--color-font-secondary, #495057);
    margin-bottom: var(--spacing-12, 12px);
  }

  .btn-rewind {
    background: none;
    border: 1px solid var(--color-grey-35, #ced4da);
    border-radius: var(--radius-8, 8px);
    padding: var(--spacing-6, 6px) var(--spacing-12, 12px);
    font-size: var(--font-size-small, 13px);
    cursor: pointer;
    color: var(--color-font-primary, #212529);
    transition: all 0.15s ease;
  }

  .btn-rewind:hover {
    background: var(--color-grey-15, #e9ecef);
  }

  .action-buttons {
    display: flex;
    justify-content: center;
    gap: var(--spacing-16, 16px);
    width: 100%;
  }

  .btn-action {
    display: flex;
    align-items: center;
    gap: var(--spacing-6, 6px);
    padding: var(--spacing-10, 10px) var(--spacing-20, 20px);
    border-radius: var(--radius-full, 24px);
    border: 1px solid var(--color-grey-30, #dee2e6);
    font-size: var(--font-size-p, 14px);
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
  }

  .btn-dislike {
    background: var(--color-grey-0, #ffffff);
    color: var(--color-error, #fa5252);
  }

  .btn-dislike:hover {
    background: #fff5f5;
    border-color: #ffc9c9;
  }

  .btn-like {
    background: var(--color-primary, #4dabf7);
    border-color: var(--color-primary, #4dabf7);
    color: white;
  }

  .btn-like:hover {
    background: #339af0;
  }

  .action-icon {
    width: 16px;
    height: 16px;
  }

  .disabled {
    opacity: 0.9;
  }
</style>
