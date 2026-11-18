<!--
  SafetyAppealForm: appeal against a safety suspension.
  Explanation up to 1,000 characters plus consent to share ONLY the flagged requests.
  The flagged requests are decrypted on the user's own device by the client core and passed
  in as `flaggedRequests`; this component only displays and submits them.
  Preview: /dev/preview/safety/SafetyAppealForm
-->
<script lang="ts">
  import { text } from '@repo/ui';

  interface Props {
    flaggedRequests?: string[];
    allowPhoto?: boolean;
    onsubmit: (payload: { explanation: string; consent_share_requests: boolean; flagged_requests: string[]; attachment_data_url: string | null }) => void;
    submitting?: boolean;
    errorMessage?: string | null;
  }
  let { flaggedRequests = [], allowPhoto = false, onsubmit, submitting = false, errorMessage = null }: Props = $props();

  const MAX_CHARS = 1000;
  let explanation = $state('');
  let consent = $state(false);
  let photo = $state<string | null>(null);

  let canSubmit = $derived(explanation.trim().length > 0 && explanation.length <= MAX_CHARS && !submitting);

  function readPhoto(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) { photo = null; return; }
    const reader = new FileReader();
    reader.onload = () => { photo = typeof reader.result === 'string' ? reader.result : null; };
    reader.readAsDataURL(file);
  }

  function submit(event: Event): void {
    event.preventDefault();
    if (!canSubmit) return;
    onsubmit({
      explanation: explanation.trim(),
      consent_share_requests: consent,
      flagged_requests: consent ? flaggedRequests : [],
      attachment_data_url: consent ? photo : null,
    });
  }
</script>

<form class="appeal-form" data-testid="safety-appeal-form" onsubmit={submit}>
  <label for="safety-appeal-explanation">{$text('safety_appeal.explanation_label')}</label>
  <textarea id="safety-appeal-explanation" data-testid="safety-appeal-explanation" rows="6" maxlength={MAX_CHARS} bind:value={explanation}></textarea>
  <span class="counter" data-testid="safety-appeal-counter">{explanation.length}/{MAX_CHARS}</span>

  <label class="consent">
    <input type="checkbox" data-testid="safety-appeal-consent" bind:checked={consent} />
    <span>{$text('safety_appeal.consent_label')}</span>
  </label>

  {#if consent && flaggedRequests.length > 0}
    <ul class="flagged" data-testid="safety-appeal-flagged">
      {#each flaggedRequests as request}<li>{request}</li>{/each}
    </ul>
  {/if}
  {#if consent && allowPhoto}
    <label class="photo-picker" data-testid="safety-appeal-photo-button">
      <input type="file" accept="image/*" class="visually-hidden" data-testid="safety-appeal-photo" onchange={readPhoto} />
      <span>{photo ? $text('safety_appeal.photo_added') : $text('safety_appeal.add_photo')}</span>
    </label>
  {/if}
  {#if errorMessage}<p class="error" role="alert" data-testid="safety-appeal-error">{errorMessage}</p>{/if}
  <button type="submit" class="primary" data-testid="safety-appeal-submit" disabled={!canSubmit}>{$text('safety_appeal.submit')}</button>
</form>

<style>
  .appeal-form { display: flex; flex-direction: column; gap: var(--spacing-4, 12px); text-align: start; width: 100%; }
  textarea { width: 100%; padding: 10px; border-radius: 12px; border: 1px solid var(--color-grey-30, #ccc); background: var(--color-grey-0, #fff); color: inherit; font: inherit; resize: vertical; }
  .counter { align-self: flex-end; font-size: 0.8em; opacity: 0.7; }
  .consent { display: flex; gap: 8px; align-items: flex-start; }
  .flagged { margin: 0; padding-inline-start: 1.2em; font-size: 0.9em; max-height: 8em; overflow: auto; }
  .photo-picker { align-self: flex-start; padding: 8px 14px; border-radius: 12px; border: 1px solid var(--color-primary, #4867cd); color: var(--color-primary, #4867cd); background: var(--color-grey-0, #fff); font-weight: 600; cursor: pointer; }
  .photo-picker:focus-within { outline: 2px solid var(--color-primary, #4867cd); outline-offset: 2px; }
  .visually-hidden { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
  .error { color: var(--color-error, #c0392b); margin: 0; }
  .primary { padding: 10px 16px; border-radius: 12px; border: 0; cursor: pointer; background: var(--color-primary, #4867cd); color: #fff; font-weight: 600; }
  .primary:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
