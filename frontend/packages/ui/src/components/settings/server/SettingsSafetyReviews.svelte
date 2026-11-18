<!--
  SettingsSafetyReviews: admin page "Safety reviews" (admin only, first-party session).
  Lists suspended accounts waiting for a decision with category, check, scores, threshold,
  purpose verdict, account age, plan, earlier strikes and appeals. Request text only appears
  when the user consented in an appeal; an attached photo opens with a click (no blur).
  Actions: Restore, Delete (with confirmation) and Ask the user.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { getApiEndpoint, text } from '@repo/ui';

  interface Appeal { id: string; status: string; explanation: string; flagged_requests: string[] | null; attachment_data_url: string | null; user_reply: string | null }
  interface Review { user_id: string; category: string; started_at: string; check: { stage?: string; reason?: string }; scores: Record<string, number>; threshold?: number | null; purpose_verdict?: string | null; account_created?: string; plan: string; earlier_strikes?: number | null; appeals: Appeal[] }

  let reviews = $state<Review[]>([]);
  let loading = $state(true);
  let questions = $state<Record<string, string>>({});
  let openPhoto = $state<string | null>(null);

  const base = '/v1/admin/safety-reviews';

  async function load(): Promise<void> {
    const response = await fetch(getApiEndpoint(base), { credentials: 'include' });
    reviews = response.ok ? (await response.json()).pending : [];
    loading = false;
  }

  async function act(userId: string, action: 'restore' | 'delete' | 'ask'): Promise<void> {
    if (action === 'delete' && !window.confirm($text('safety_appeal.admin_delete_confirm'))) return;
    await fetch(getApiEndpoint(`${base}/${userId}/${action}`), {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: action === 'ask' ? JSON.stringify({ question: questions[userId] ?? '' }) : undefined,
    });
    await load();
  }

  onMount(load);
</script>

<div class="reviews" data-testid="safety-reviews">
  <h2>{$text('safety_appeal.admin_title')}</h2>
  {#if !loading && reviews.length === 0}<p data-testid="safety-reviews-empty">{$text('safety_appeal.admin_empty')}</p>{/if}
  {#each reviews as review (review.user_id)}
    <section class="review" data-testid="safety-review">
      <h3>{review.category} ({review.user_id.slice(0, 8)})</h3>
      <p>{review.check.stage ?? ''} {review.check.reason ?? ''} | threshold {review.threshold ?? 'n/a'} | {review.purpose_verdict ?? ''}</p>
      <p>{Object.entries(review.scores).map(([k, v]) => `${k}=${v}`).join(', ')}</p>
      <p>plan {review.plan} | account {review.account_created ?? 'unknown'} | earlier strikes {review.earlier_strikes ?? 'n/a'}</p>
      {#each review.appeals as appeal (appeal.id)}
        <div class="appeal" data-testid="safety-review-appeal">
          <p>{appeal.explanation}</p>
          {#if appeal.user_reply}<p>{appeal.user_reply}</p>{/if}
          {#if appeal.flagged_requests}<ul>{#each appeal.flagged_requests as request}<li>{request}</li>{/each}</ul>{/if}
          {#if appeal.attachment_data_url}
            <button onclick={() => (openPhoto = appeal.attachment_data_url)}>photo</button>
          {/if}
        </div>
      {/each}
      <textarea maxlength="1000" bind:value={questions[review.user_id]} data-testid="safety-review-question"></textarea>
      <div class="actions">
        <button data-testid="safety-review-restore" onclick={() => act(review.user_id, 'restore')}>{$text('safety_appeal.admin_restore')}</button>
        <button data-testid="safety-review-ask" onclick={() => act(review.user_id, 'ask')}>{$text('safety_appeal.admin_ask')}</button>
        <button data-testid="safety-review-delete" onclick={() => act(review.user_id, 'delete')}>{$text('safety_appeal.admin_delete')}</button>
      </div>
    </section>
  {/each}
  {#if openPhoto}<button class="photo" onclick={() => (openPhoto = null)}><img src={openPhoto} alt="" /></button>{/if}
</div>

<style>
  .reviews { display: flex; flex-direction: column; gap: 16px; padding: 16px; }
  .review { border: 1px solid var(--color-grey-30, #ccc); border-radius: 12px; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; }
  textarea { width: 100%; border-radius: 8px; padding: 8px; }
  .photo img { max-width: 100%; }
</style>
