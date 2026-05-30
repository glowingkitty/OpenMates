<!--
  frontend/packages/ui/src/components/interactive_questions/renderers/RatingQuestion.svelte

  Rating-type interactive question component (star ratings with comments).
  Displays hoverable stars and an optional text area for reviews.
  Uses Svelte 5 Runes for properties and reactivity.

  Architecture: Svelte 5 Socratic assessment UI
-->

<script lang="ts">
  import type { RatingQuestionData } from '../types';

  let {
    data,
    value = $bindable(null),
    isValid = $bindable(false),
    disabled = false,
    answeredValue = null
  } = $props<{
    data: RatingQuestionData;
    value: { id: string; rating: number; comment?: string } | null;
    isValid: boolean;
    disabled?: boolean;
    answeredValue?: { rating: number; comment?: string } | null;
  }>();

  // Internal reactive states
  let rating = $state<number>(0);
  let comment = $state<string>('');
  let hoverRating = $state<number | null>(null);

  // Sync if locked/answered
  $effect(() => {
    if (disabled && answeredValue) {
      rating = answeredValue.rating;
      comment = answeredValue.comment || '';
      isValid = true;
    }
  });

  function handleSetRating(starNum: number) {
    if (disabled) return;
    rating = starNum;
    updatePayload();
  }

  function handleCommentInput(val: string) {
    if (disabled) return;
    comment = val;
    updatePayload();
  }

  function updatePayload() {
    // Validate: must have at least 1 star (and if required_comment, must have comment)
    const hasStars = rating > 0;
    const hasCommentIfRequired = !data.require_comment || (comment && comment.trim().length > 0);

    isValid = hasStars && hasCommentIfRequired;
    value = isValid ? { id: data.id, rating, comment: comment.trim() || undefined } : null;
  }
</script>

<div class="rating-question" class:disabled>
  <div class="stars-row">
    {#each Array(data.max_stars ?? 5) as _, i}
      {@const starNum = i + 1}
      {@const isHighlighted = hoverRating !== null ? starNum <= hoverRating : starNum <= rating}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div
        class="star-wrapper"
        role="button"
        tabindex="0"
        onmouseenter={() => !disabled && (hoverRating = starNum)}
        onmouseleave={() => !disabled && (hoverRating = null)}
        onclick={() => handleSetRating(starNum)}
      >
        <svg
          viewBox="0 0 24 24"
          class="star-icon"
          class:highlighted={isHighlighted}
          class:interactive={!disabled}
        >
          <path fill="currentColor" d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/>
        </svg>
      </div>
    {/each}
  </div>

  <div class="comment-section">
    <textarea
      value={comment}
      placeholder={data.comment_placeholder || 'Leave a comment...'}
      {disabled}
      oninput={(e) => handleCommentInput((e.target as HTMLTextAreaElement).value)}
      class="comment-textarea"
      rows="3"
    ></textarea>
  </div>
</div>

<style>
  .stars-row {
    display: flex;
    justify-content: center;
    gap: var(--spacing-8, 8px);
    margin-bottom: var(--spacing-16, 16px);
    width: 100%;
  }

  .star-wrapper {
    cursor: pointer;
    outline: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .star-icon {
    width: 32px;
    height: 32px;
    color: var(--color-grey-30, #dee2e6);
    transition: transform 0.15s cubic-bezier(0.175, 0.885, 0.32, 1.275), color 0.1s ease;
  }

  .star-icon.interactive {
    cursor: pointer;
  }

  .star-wrapper:hover .star-icon.interactive {
    transform: scale(1.15);
  }

  .star-icon.highlighted {
    color: var(--color-warning, #fab005);
  }

  .comment-section {
    width: 100%;
  }

  .comment-textarea {
    width: 100%;
    padding: var(--spacing-10, 10px) var(--spacing-12, 12px);
    font-size: var(--font-size-p, 14px);
    background: var(--color-grey-0, #ffffff);
    border: 1px solid var(--color-grey-30, #ced4da);
    border-radius: var(--radius-8, 8px);
    resize: none;
    transition: all 0.2s ease;
    box-sizing: border-box;
  }

  .comment-textarea:focus {
    outline: none;
    border-color: var(--color-primary, #4dabf7);
    box-shadow: 0 0 0 3px rgba(77, 171, 247, 0.22);
  }

  .comment-textarea:disabled {
    background: var(--color-grey-10, #f8f9fa);
    border-color: var(--color-grey-20, #dee2e6);
    cursor: not-allowed;
    color: var(--color-font-secondary, #495057);
  }

  .disabled {
    opacity: 0.9;
  }
</style>
