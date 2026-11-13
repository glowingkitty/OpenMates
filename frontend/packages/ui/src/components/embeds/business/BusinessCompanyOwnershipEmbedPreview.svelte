<!--
  frontend/packages/ui/src/components/embeds/business/BusinessCompanyOwnershipEmbedPreview.svelte

  Preview card for Business / Company ownership: subject name, country, legal
  form and status, owner / holding / officer counts and the top owners with their
  share. The records live in the parent embed content; there are no child embeds.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { normalizeCompanyOwnership } from './companyOwnershipContent';
  type Status = 'processing' | 'finished' | 'error' | 'cancelled';
  interface Props {
    id: string;
    data?: Record<string, unknown>;
    query?: string;
    status: Status;
    taskId?: string;
    isMobile?: boolean;
    presentationOnly?: boolean;
    onFullscreen: (content?: Record<string, unknown>) => void;
  }
  let { id, data = {}, query = '', status, taskId, isMobile = false,
    presentationOnly = false, onFullscreen }: Props = $props();
  const prefix = 'embeds.business.company_ownership.';
  // The card fits six text lines: two owners when a "+N more" line follows, else three.
  const SHOWN = 3;
  let content = $derived(data);
  let result = $derived(normalizeCompanyOwnership(content));
  let effectiveStatus = $derived(result.error ? 'error' : status);
  let first = $derived(result.records[0]);
  let facts = $derived(first ? [first.subject.country, first.subject.legalForm, first.subject.status].filter(Boolean).join(' · ') : '');
  let owners = $derived(first ? first.owners.slice(0, result.records.length > 1 ? SHOWN - 1 : SHOWN) : []);
  let firstError = $derived(result.errors[0]);
  function updated(value: { status: string; decodedContent: Record<string, unknown> }) {
    data = value.decodedContent;
    if (['processing', 'finished', 'error', 'cancelled'].includes(value.status)) status = value.status as Status;
  }
</script>

<UnifiedEmbedPreview {id} appId="business" skillId="company_ownership" skillIconName="business"
  status={effectiveStatus} skillName={$text('app_skills.business.company_ownership')}
  {taskId} {isMobile} {presentationOnly} showStatus={effectiveStatus === 'processing'}
  onFullscreen={() => onFullscreen(content)} onEmbedDataUpdated={updated}>
  {#snippet details()}
    <div class="summary" data-testid="company-ownership-preview">
      <strong class="query">{first ? first.subject.name : (result.query || query || $text('app_skills.business.company_ownership'))}</strong>
      {#if effectiveStatus === 'error'}
        <p class="notice" data-testid="company-ownership-preview-error">{$text(prefix + 'failed')}</p>
      {:else if effectiveStatus === 'cancelled'}
        <p class="notice">{$text('embeds.cancelled')}</p>
      {:else if first}
        {#if facts}<p class="meta" data-testid="company-ownership-preview-facts">{facts}</p>{/if}
        <p class="counts" data-testid="company-ownership-preview-counts">
          {[$text(prefix + 'owners_count', { values: { count: first.owners.length } }),
            $text(prefix + 'holdings_count', { values: { count: first.holdings.length } }),
            $text(prefix + 'officers_count', { values: { count: first.officers.length } })].join(' · ')}
        </p>
        {#if owners.length}
          <ul class="names" data-testid="company-ownership-preview-owners">
            {#each owners as owner}
              <li><span class="name">{owner.name}</span>{#if owner.share}<span class="share">{owner.share}</span>{/if}</li>
            {/each}
          </ul>
        {/if}
        {#if result.records.length > 1}
          <p class="meta">{$text(prefix + 'more_records', { values: { count: result.records.length - 1 } })}</p>
        {/if}
      {:else if result.hasData || firstError}
        <p class="notice" data-testid="company-ownership-preview-empty">
          {firstError ? $text(prefix + (firstError.code === 'ambiguous' ? 'error_ambiguous' : firstError.code === 'coverage_gap' ? 'error_coverage_gap' : firstError.code === 'not_found' ? 'error_not_found' : 'error_other')) : $text(prefix + 'empty')}
        </p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .summary { display: flex; flex-direction: column; justify-content: center; gap: var(--spacing-3); min-height: 100%; min-width: 0; }
  .query { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; color: var(--color-font-primary); font-size: var(--font-size-small); }
  p { margin: 0; }
  .counts { color: var(--color-font-primary); font-size: var(--font-size-small); }
  .meta, .notice { color: var(--color-font-tertiary); font-size: var(--font-size-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .names { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; }
  .names li { display: flex; align-items: baseline; gap: var(--spacing-3); min-width: 0; font-size: var(--font-size-xs); }
  .name { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-font-primary); }
  .share { flex: 0 0 auto; color: var(--color-font-tertiary); white-space: nowrap; }
</style>
