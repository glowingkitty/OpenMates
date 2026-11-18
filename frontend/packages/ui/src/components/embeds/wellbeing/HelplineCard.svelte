<!--
  frontend/packages/ui/src/components/embeds/wellbeing/HelplineCard.svelte

  Calm helpline card for the `helplines` embed (wellbeing layer, owner decision 10).
  Shows an encouraging title, one row per helpline (name, hours, call / text / chat
  actions), the local emergency number and a link to a helpline directory. With no
  lines (directory key not configured) only the emergency number and the directory
  link are shown. Presentational only: the HelplinesRenderer decodes the embed payload.

  Payload contract: docs/plans/safety-decisions-build/wellbeing-contract.md
  Native counterpart: apple/OpenMates/Sources/Features/Chat/Views/HelplineCardView.swift
-->
<script lang="ts">
  import { text } from '../../../i18n/translations';

  import type { HelplineLine } from '../../../types/helplines';

  interface Props {
    lines: HelplineLine[];
    emergency_number: string;
    directory_url: string;
    country?: string;
    language?: string;
    source?: 'throughline' | 'emergency_only';
  }
  let { lines, emergency_number, directory_url, country = '', language = '' }: Props = $props();

  /** Keep only characters valid in a dialable number so a payload cannot inject URL parts. */
  function dialable(value: string): string {
    return value.replace(/[^+0-9]/g, '');
  }

  /** Only https links are rendered as links; anything else is dropped. */
  function safeHttps(value: string | null): string | null {
    if (!value) return null;
    try {
      return new URL(value).protocol === 'https:' ? value : null;
    } catch {
      return null;
    }
  }

  let directoryHref = $derived(safeHttps(directory_url));
  let emergencyTel = $derived(dialable(emergency_number));
</script>

<section class="helpline-card" data-testid="helpline-card" data-country={country} data-language={language}
  data-line-count={lines.length} aria-label={$text('helplines.title')}>
  <h3 class="title">{$text('helplines.title')}</h3>

  {#if lines.length > 0}
    <ul class="lines">
      {#each lines as line, position (position)}
        {@const phone = line.phone ? dialable(line.phone) : ''}
        {@const sms = line.sms ? dialable(line.sms) : ''}
        {@const chat = safeHttps(line.chat_url)}
        <li class="line" data-testid="helpline-entry">
          <div class="line-info">
            <span class="line-name">{line.name}</span>
            {#if line.hours}<span class="line-hours">{line.hours}</span>{/if}
          </div>
          {#if phone || sms || chat}
            <div class="actions">
              {#if phone}
                <a class="action" data-testid="helpline-call" href={`tel:${phone}`}
                  aria-label={`${$text('helplines.call')}: ${line.name}`}>{$text('helplines.call')}</a>
              {/if}
              {#if sms}
                <a class="action" data-testid="helpline-sms" href={`sms:${sms}`}
                  aria-label={`${$text('helplines.send_text')}: ${line.name}`}>{$text('helplines.send_text')}</a>
              {/if}
              {#if chat}
                <a class="action" data-testid="helpline-chat" href={chat} target="_blank" rel="noopener noreferrer"
                  aria-label={`${$text('helplines.chat')}: ${line.name}`}>{$text('helplines.chat')}</a>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  <p class="emergency" data-testid="helpline-emergency">
    {#if emergencyTel}
      <a class="emergency-call" href={`tel:${emergencyTel}`}>{$text('helplines.emergency', { values: { emergency_number } })}</a>
    {:else}
      {$text('helplines.emergency', { values: { emergency_number } })}
    {/if}
  </p>

  {#if directoryHref}
    <a class="directory" data-testid="helpline-directory-link" href={directoryHref} target="_blank"
      rel="noopener noreferrer">{$text('helplines.find_more')}</a>
  {/if}
</section>

<style>
  .helpline-card {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
    width: 100%;
    max-width: 28rem;
    box-sizing: border-box;
    padding: var(--spacing-6);
    border-radius: var(--radius-6);
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-25);
    color: var(--color-font-primary);
  }
  .title {
    margin: 0;
    font-size: var(--font-size-p);
    font-weight: 600;
    line-height: 1.3;
  }
  .lines { display: flex; flex-direction: column; gap: var(--spacing-3); margin: 0; padding: 0; list-style: none; }
  .line {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
    padding: var(--spacing-4);
    border-radius: var(--radius-4);
    background: var(--color-grey-0);
    border: 1px solid var(--color-grey-20);
  }
  .line-info { display: flex; flex-direction: column; gap: var(--spacing-1); min-width: 0; }
  .line-name { font-size: var(--font-size-p); font-weight: 600; overflow-wrap: anywhere; }
  .line-hours { font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .actions { display: flex; flex-wrap: wrap; gap: var(--spacing-3); }
  /* Anchors styled as soft pill buttons; reset global button/link rules explicitly. */
  .action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 2.5rem;
    padding: var(--spacing-2) var(--spacing-6);
    border-radius: var(--radius-full);
    background: var(--color-primary);
    color: var(--color-font-button);
    font-size: var(--font-size-small);
    font-weight: 600;
    text-decoration: none;
  }
  .action:hover { filter: brightness(1.06); }
  .emergency { margin: 0; font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .emergency-call { color: var(--color-font-primary); font-weight: 600; text-decoration: none; }
  .emergency-call:hover { text-decoration: underline; }
  .directory {
    align-self: flex-start;
    font-size: var(--font-size-small);
    font-weight: 600;
    color: var(--color-primary);
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .helpline-card a:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
</style>
