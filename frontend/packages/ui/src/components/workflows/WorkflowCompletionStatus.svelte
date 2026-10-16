<!-- Status shown while a Workflow completion link resolves its encrypted chat message. -->
<script lang="ts">
  import { text } from '../../i18n/translations';
  let { status, onRetry }: {
    status: 'checking' | 'waiting' | 'unavailable';
    onRetry: () => void;
  } = $props();
</script>

{#if status === 'unavailable'}
  <div class="completion-status unavailable" data-testid="workflow-completion-chat-unavailable" role="alert">
    <span>{$text('workflows.completion.message_unavailable')}</span>
    <span>{$text('workflows.completion.review_run_or')} <button type="button" onclick={onRetry}>{$text('workflows.completion.retry_message')}</button></span>
  </div>
{:else}
  <div class="completion-status" data-testid="workflow-completion-chat-loading" role="status">{$text('workflows.completion.opening_message')}</div>
{/if}

<style>
  .completion-status { box-sizing: border-box; width: 100%; padding: .75rem 1rem; color: var(--color-font-primary); }
  .unavailable { color: var(--color-font-primary); background: var(--color-grey-0); border-radius: .5rem; }
  .unavailable span { display: block; }
  button { color: inherit; font: inherit; text-decoration: underline; background: none; border: 0; padding: .15rem .2rem; cursor: pointer; }
  button:hover, button:focus-visible { text-decoration-thickness: 2px; }
  button:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; border-radius: .2rem; }
</style>
