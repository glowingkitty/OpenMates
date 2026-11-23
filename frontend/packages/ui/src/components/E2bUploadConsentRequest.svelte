<!--
  frontend/packages/ui/src/components/E2bUploadConsentRequest.svelte

  Chat-history card for the system message type e2b_upload_consent_request
  (assertion code-run.e2b.upload-consent). Pure presentation: the client core
  builds the message, decides whether it is answered (is_request_answered) and
  sends the answer; this component shows the plain text, the privacy policy
  link, the own-machine alternative and the three choices, or the chosen answer
  read-only. Wire contract: docs/plans/e2b-upload-consent/plan.yml.
-->
<script module lang="ts">
  export type E2bConsentChoice = 'allow' | 'own_machine' | 'not_now';

  export interface E2bConsentRequestContent {
    request_id: string;
    privacy_policy_url?: string;
    remote_access_command?: string;
  }

  /** Shapes the decrypted request system message for the card; the core builds and pairs the messages. */
  export function parseE2bConsentRequest(content: unknown): E2bConsentRequestContent | null {
    if (typeof content !== 'string' || !content.includes('e2b_upload_consent_request')) return null;
    try {
      const value = JSON.parse(content) as Record<string, unknown> | null;
      if (!value || value.type !== 'e2b_upload_consent_request' || typeof value.request_id !== 'string') return null;
      return {
        request_id: value.request_id,
        privacy_policy_url: typeof value.privacy_policy_url === 'string' ? value.privacy_policy_url : undefined,
        remote_access_command: typeof value.remote_access_command === 'string' ? value.remote_access_command : undefined,
      };
    } catch {
      return null;
    }
  }

  /** True for the response system message, which the card absorbs instead of showing a bubble. */
  export function isE2bConsentResponseContent(content: unknown): boolean {
    return typeof content === 'string' && content.includes('"e2b_upload_consent_response"');
  }
</script>

<script lang="ts">
  import { text } from '../i18n/translations';

  let {
    requestId,
    privacyPolicyUrl = 'https://openmates.org/privacy',
    remoteAccessCommand = 'openmates remote-access',
    answeredChoice = null,
    busy = false,
    onAnswer,
  }: {
    requestId: string;
    privacyPolicyUrl?: string;
    remoteAccessCommand?: string;
    /** Choice of the e2b_upload_consent_response, or null while unanswered. */
    answeredChoice?: E2bConsentChoice | null;
    busy?: boolean;
    onAnswer: (choice: E2bConsentChoice, requestId: string) => void;
  } = $props();

  const labelKeys: Record<E2bConsentChoice, string> = {
    allow: 'e2b_consent.request.allow',
    own_machine: 'e2b_consent.request.own_machine',
    not_now: 'e2b_consent.request.not_now',
  };
</script>

<div class="e2b-consent" data-testid="e2b-consent-request" data-request-id={requestId}
  data-answered={answeredChoice ?? 'none'}>
  <p class="body" data-testid="e2b-consent-text">{$text('e2b_consent.request.body')}</p>
  <a class="policy" data-testid="e2b-consent-privacy-link" href={privacyPolicyUrl} target="_blank"
    rel="noopener noreferrer">{$text('e2b_consent.request.privacy_policy')}</a>
  <p class="body" data-testid="e2b-consent-own-machine-hint">
    {$text('e2b_consent.request.own_machine_hint')} <code>{remoteAccessCommand}</code>
  </p>
  {#if answeredChoice}
    <p class="answered" data-testid="e2b-consent-answered" data-choice={answeredChoice}>
      {$text('e2b_consent.request.answered')} <strong>{$text(labelKeys[answeredChoice])}</strong>
    </p>
  {:else}
    <div class="actions">
      <button type="button" class="primary" data-testid="e2b-consent-allow" disabled={busy}
        onclick={() => onAnswer('allow', requestId)}>{$text(labelKeys.allow)}</button>
      <button type="button" class="secondary" data-testid="e2b-consent-own-machine" disabled={busy}
        onclick={() => onAnswer('own_machine', requestId)}>{$text(labelKeys.own_machine)}</button>
      <button type="button" class="secondary" data-testid="e2b-consent-not-now" disabled={busy}
        onclick={() => onAnswer('not_now', requestId)}>{$text(labelKeys.not_now)}</button>
    </div>
  {/if}
</div>

<style>
  .e2b-consent {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    width: 100%;
    max-width: 520px;
    margin: var(--spacing-6) auto;
    padding: var(--spacing-8);
    border-radius: var(--radius-5);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
  }
  .body, .answered { margin: 0; line-height: 1.4; }
  code {
    padding: 0 var(--spacing-2);
    border-radius: var(--radius-2);
    background: var(--color-grey-20);
    font-family: monospace;
    /* A shell command is copied as a whole; never break it inside a word. */
    white-space: nowrap;
  }
  .policy { color: var(--color-primary-start); width: fit-content; }
  .actions { display: flex; flex-wrap: wrap; gap: var(--spacing-4); }
  .actions button {
    flex: 1 1 auto;
    padding: var(--spacing-5) var(--spacing-8);
    border: none;
    border-radius: 50px;
    font-size: var(--font-size-small);
    font-weight: 600;
    cursor: pointer;
  }
  .primary { background: var(--color-button-primary, #ff553b); color: white; }
  .secondary { background: var(--color-grey-20); color: var(--color-font-primary); }
  .actions button:disabled { opacity: 0.5; cursor: not-allowed; }
  .actions button:focus-visible { outline: 2px solid var(--color-primary-start); outline-offset: 2px; }
</style>
