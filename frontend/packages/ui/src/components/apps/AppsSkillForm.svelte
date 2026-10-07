<script lang="ts">
  import { text } from '../../i18n/translations';
  import WorkflowSchemaFields from '../workflows/WorkflowSchemaFields.svelte';
  import SettingsTextarea from '../settings/elements/SettingsTextarea.svelte';
  import type { AppsSkillDetails, AppsSkillGuestEligibility } from '../../types/appsWorkspace';
  import { getAnonymousAppsSkillAvailability } from '../../services/appsWorkspaceService';
  import { isCachePricingDisplayActive, supportsOneHourCacheWrites, type CachePricingAvailability } from '../../utils/cachePricingAvailability';
  import {
    expandCompositeSkillPaths, getSkillPath, prepareSkillInput, remainingSkillPaths, schemaForPath,
    selectSkillSchema, setSkillPath, showAllSkillSchema, skillLeafPaths,
    validateSkillInput, type SkillSchema, type SkillValidationIssue,
  } from './appsSkillFormUtils';

  let {
    metadata, onSubmit, submitting = false, disabled = false, guest = false,
    guestEligibility, onSignup, showManualIntro = true, timezone = Intl.DateTimeFormat().resolvedOptions().timeZone,
  }: {
    metadata: AppsSkillDetails;
    onSubmit: (input: Record<string, unknown>) => void | Promise<void>;
    submitting?: boolean;
    disabled?: boolean;
    guest?: boolean;
    guestEligibility?: AppsSkillGuestEligibility;
    onSignup?: () => void;
    /** Workspace supplies its own compact context disclosure above the form. */
    showManualIntro?: boolean;
    timezone?: string;
  } = $props();

  let input = $state<Record<string, unknown>>({});
  let settingsOpen = $state(false);
  let issues = $state<SkillValidationIssue[]>([]);
  let submissionError = $state(false);
  let locallySubmitting = $state(false);
  let quoteEligibility = $state<AppsSkillGuestEligibility | null>(null);
  let checkingQuote = $state(false);
  let quoteRevision = $state(0);
  let loadedKey = '';
  const tr = (key: string) => $text(`apps.skill_form.${key}`);
  const data = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const amount = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
  const names = (items: Record<string, unknown>[]): string[] => [...new Set(items.flatMap(item => typeof item.name === 'string' && item.name.trim() ? [item.name.trim()] : []))];

  function pricingLines(value: unknown, cachePricingValue?: unknown, defaultHost?: string): string[] {
    const pricing = data(value);
    const credits = $text('common.credits');
    const lines: string[] = [];
    const fixed = amount(pricing.fixed);
    const perSecond = amount(pricing.per_second);
    const perMinute = amount(pricing.per_minute);
    const perUnit = data(pricing.per_unit);
    const unitCredits = amount(perUnit.credits);
    if (fixed !== null) lines.push(`${fixed} ${credits} ${tr('per_request')}`);
    if (perSecond !== null) lines.push(`${perSecond} ${credits} ${tr('per_second')}`);
    if (perMinute !== null) lines.push(`${perMinute} ${credits} ${tr('per_minute')}`);
    if (unitCredits !== null) {
      const unit = typeof perUnit.unit_name === 'string' && perUnit.unit_name.trim() ? perUnit.unit_name.trim() : tr('request');
      lines.push(`${unitCredits} ${credits} ${$text('apps.skill_form.per_unit', { values: { unit } })}`);
    }
    const tokens = data(pricing.tokens);
    for (const direction of ['input', 'output'] as const) {
      const count = amount(data(tokens[direction]).per_credit_unit);
      if (count !== null && count > 0) lines.push(`${tr('one_credit_per')} ${count} ${tr(`${direction}_tokens`)}`);
    }
    const cachePricing = data(cachePricingValue);
    if (isCachePricingDisplayActive(cachePricing as CachePricingAvailability, defaultHost, {
      cache_read: amount(data(tokens.cache_read).per_credit_unit) ?? undefined,
      cache_write: amount(data(tokens.cache_write).per_credit_unit) ?? undefined,
      cache_write_1h: amount(data(tokens.cache_write_1h).per_credit_unit) ?? undefined,
    })) {
      for (const direction of ['cache_read', 'cache_write', 'cache_write_1h'] as const) {
        if (direction === 'cache_write_1h' && !supportsOneHourCacheWrites(cachePricing as CachePricingAvailability, defaultHost)) continue;
        const count = amount(data(tokens[direction]).per_credit_unit);
        const label = direction === 'cache_write'
          ? cachePricing.write_billing === 'included_in_input' ? 'cache_write' : 'cache_write_5m'
          : direction;
        if (direction === 'cache_write' && cachePricing.write_billing === 'included_in_input') {
          lines.push(`${$text(`settings.ai_ask.ai_ask_model_details.${label}`)}: ${$text('settings.ai_ask.ai_ask_model_details.included_in_input')}`);
        } else if (count !== null && count > 0) {
          lines.push(`${$text(`settings.ai_ask.ai_ask_model_details.${label}`)}: ${tr('one_credit_per')} ${count} ${tr('input_tokens')}`);
        }
      }
    }
    return lines;
  }

  $effect(() => {
    const key = `${metadata.app_id}/${metadata.skill_id}`;
    if (key !== loadedKey) {
      loadedKey = key;
      input = $state.snapshot(metadata.defaults ?? {});
      settingsOpen = false;
      issues = [];
      submissionError = false;
      quoteEligibility = null;
    }
  });

  $effect(() => {
    const revision = quoteRevision;
    const selectedInput = prepareSkillInput(metadata.input_schema as SkillSchema, $state.snapshot(input), timezone);
    const appId = metadata.app_id;
    const skillId = metadata.skill_id;
    if (!guest || !metadata.anonymous_allowed || metadata.execution_mode !== 'sync' || validateSkillInput(metadata.input_schema as SkillSchema, selectedInput).length) {
      quoteEligibility = null;
      checkingQuote = false;
      return;
    }
    void revision;
    const controller = new AbortController();
    quoteEligibility = null;
    checkingQuote = true;
    const timer = setTimeout(() => {
      getAnonymousAppsSkillAvailability(appId, skillId, selectedInput, controller.signal)
        .then(result => { if (!controller.signal.aborted) quoteEligibility = result; })
        .catch(() => { if (!controller.signal.aborted) quoteEligibility = { allowed: false, reason: 'availability_unavailable' }; })
        .finally(() => { if (!controller.signal.aborted) checkingQuote = false; });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  });

  const schema = $derived(metadata.input_schema as SkillSchema);
  const primaryPaths = $derived(metadata.primary_fields.slice(0, 2));
  const displayedPrimaryPaths = $derived(expandCompositeSkillPaths(schema, primaryPaths));
  const primarySchema = $derived(selectSkillSchema(schema, displayedPrimaryPaths));
  const requirementsPath = $derived(skillLeafPaths(schema).find(path => {
    if (!path.endsWith('.relevance_criteria') && path !== 'relevance_criteria') return false;
    const field = schemaForPath(schema, path);
    return field?.type === 'string' && !field.enum && !displayedPrimaryPaths.includes(path);
  }));
  const requirementsField = $derived(requirementsPath ? schemaForPath(schema, requirementsPath) : null);
  const advancedPaths = $derived(remainingSkillPaths(schema, [...displayedPrimaryPaths, ...(requirementsPath ? [requirementsPath] : [])]));
  const advancedSchema = $derived(selectSkillSchema(schema, advancedPaths));
  const showSignup = $derived(guest && metadata.execution_available && (!metadata.anonymous_allowed || metadata.execution_mode !== 'sync' || quoteEligibility?.allowed === false || (!checkingQuote && !quoteEligibility && !guestEligibility?.allowed)));
  const unavailable = $derived(!metadata.execution_available);
  const busy = $derived(submitting || locallySubmitting);
  const inputIsValid = $derived(validateSkillInput(schema, prepareSkillInput(schema, $state.snapshot(input), timezone)).length === 0);
  const providerNames = $derived(names(metadata.providers));
  const modelNames = $derived(names(metadata.models));
  const rateLines = $derived(pricingLines(metadata.pricing));
  const modelRateLines = $derived(metadata.models.flatMap(model => pricingLines(model.pricing, model.cache_pricing,
    typeof model.default_server === 'string' ? model.default_server : undefined)
    .filter(line => !rateLines.includes(line))
    .map(line => `${String(model.name ?? model.id ?? '')}: ${line}`)));

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (busy || disabled || unavailable || showSignup) return;
    submissionError = false;
    const prepared = prepareSkillInput(schema, $state.snapshot(input), timezone);
    issues = validateSkillInput(schema, prepared);
    if (issues.length) {
      // Hidden required values must be exposed for correction.
      settingsOpen = true;
      return;
    }
    if (checkingQuote || (guest && quoteEligibility?.allowed !== true)) return;
    locallySubmitting = true;
    try { await onSubmit(prepared); }
    catch { submissionError = true; }
    finally { locallySubmitting = false; if (guest) quoteRevision += 1; }
  }

  function issueLabel(issue: SkillValidationIssue): string {
    const field = issue.path.replace(/\[\d+\]/g, '').split('.').at(-1)?.replace(/_/g, ' ') ?? '';
    return `${field}: ${tr(`validation_${issue.code}`)}`;
  }
</script>

<form class="apps-skill-form" data-testid="apps-skill-form" onsubmit={submit}>
  {#if showManualIntro}<p class="manual-intro" data-testid="apps-skill-manual-intro">{tr('manual_intro')}</p>{/if}
  {#if primarySchema}
    <div class="primary-fields" data-testid="apps-skill-primary-fields">
      <WorkflowSchemaFields schema={showAllSkillSchema(primarySchema)} value={input} onChange={next => input = next as Record<string, unknown>} path="apps-primary" appId={metadata.app_id} {timezone} appsMode />
    </div>
  {/if}
  {#if requirementsPath}
    <div class="requirements-field" data-testid="apps-skill-requirements">
      <label for="apps-skill-relevance-criteria">{tr('requirements')} <span class="optional">{tr('optional')}</span></label>
      <SettingsTextarea
        id="apps-skill-relevance-criteria"
        ariaLabel={`${tr('requirements')} ${tr('optional')}`}
        value={String(getSkillPath(input, requirementsPath) ?? '')}
        placeholder={tr('requirements_placeholder')}
        maxlength={requirementsField?.maxLength}
        rows={4}
        dataTestid="apps-skill-relevance-criteria"
        onInput={value => input = setSkillPath(input, requirementsPath, value || undefined)}
      />
    </div>
  {/if}

  {#if issues.length}
    <div class="errors" role="alert" data-testid="apps-skill-validation-errors">
      <p>{tr('check_fields')}</p>
      <ul>{#each issues as issue}<li>{issueLabel(issue)}</li>{/each}</ul>
    </div>
  {/if}
  {#if submissionError}<p class="errors" role="alert">{tr('execution_failed')}</p>{/if}
  {#if unavailable}<p class="unavailable" role="status">{tr('unavailable')}</p>{/if}

  <div class="action-row">
    {#if advancedSchema}
      <button class="settings-toggle" type="button" aria-expanded={settingsOpen} aria-controls="apps-skill-settings" data-testid="apps-skill-settings-toggle" onclick={() => settingsOpen = !settingsOpen}>
        <span class="settings-icon" aria-hidden="true"></span>
        {tr(settingsOpen ? 'hide_settings' : 'show_settings')}
      </button>
    {/if}
    {#if showSignup}
      <button class="action" type="button" data-testid="apps-skill-signup" onclick={() => onSignup?.()}>{tr('signup')}</button>
    {:else}
      <button class="action" type="submit" data-testid="apps-skill-submit" disabled={busy || disabled || unavailable || (inputIsValid && (checkingQuote || (guest && quoteEligibility?.allowed !== true)))}>
        {tr(busy ? 'running' : checkingQuote ? 'checking' : 'run')}
      </button>
    {/if}
  </div>
  {#if advancedSchema && settingsOpen}
    <section class="settings" id="apps-skill-settings" aria-label={tr('settings')} data-testid="apps-skill-settings">
      <WorkflowSchemaFields schema={showAllSkillSchema(advancedSchema)} value={input} onChange={next => input = next as Record<string, unknown>} path="apps-settings" appId={metadata.app_id} {timezone} appsMode />
    </section>
  {/if}
  {#if providerNames.length || modelNames.length || rateLines.length || modelRateLines.length}
    <div class="execution-meta" data-testid="apps-skill-execution-meta">
      {#if providerNames.length}
        <p data-testid="apps-skill-providers">{providerNames.length === 1 ? tr('via') : tr('providers')} <strong>{providerNames.join(', ')}</strong></p>
      {/if}
      {#each rateLines as line}<p data-testid="apps-skill-pricing">{line}</p>{/each}
      {#if modelNames.length}<p data-testid="apps-skill-models">{tr(modelNames.length === 1 ? 'model' : 'models')} <strong>{modelNames.join(', ')}</strong></p>{/if}
      {#each modelRateLines as line}<p data-testid="apps-skill-model-pricing">{line}</p>{/each}
    </div>
  {/if}
</form>

<style>
  .apps-skill-form { display:grid; gap:var(--spacing-8); width:100%; max-width:48rem; min-width:0; margin:0 auto; }
  .manual-intro { margin:0; text-align:center; color:var(--color-font-secondary); line-height:1.5; }
  .primary-fields,.settings { min-width:0; }
  .requirements-field { display:grid; gap:var(--spacing-2); min-width:0; }
  .requirements-field label { font-size:max(16px, 1rem); font-weight:650; line-height:1.35; }
  .requirements-field .optional { color:var(--color-font-secondary); font-weight:400; }
  .requirements-field :global(.settings-textarea-wrapper) { padding:0; }
  .requirements-field :global(.settings-textarea) { min-height:7rem; background:var(--color-grey-20); }
  .primary-fields :global(.schema-fields),.settings :global(.schema-fields) { gap:var(--spacing-8); }
  .settings { display:grid; gap:var(--spacing-8); padding:var(--spacing-8); border:1px solid var(--color-grey-20); border-radius:var(--radius-8); }
  .action-row { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); align-items:center; gap:var(--spacing-4); min-width:0; }
  .settings-toggle { grid-column:1; justify-self:start; display:inline-flex; align-items:center; gap:var(--spacing-2); border:0; background:transparent; color:var(--color-primary-start); font:inherit; font-weight:650; cursor:pointer; }
  .settings-icon { flex:none; width:1rem; height:1rem; background:currentColor; -webkit-mask:url('@openmates/ui/static/icons/settings.svg') center/contain no-repeat; mask:url('@openmates/ui/static/icons/settings.svg') center/contain no-repeat; }
  .action { grid-column:2; justify-self:center; min-width:11rem; min-height:3rem; max-width:100%; padding:.7rem 1.5rem; border:0; border-radius:var(--radius-8); background:var(--color-button-primary); color:var(--color-font-button); font:inherit; font-weight:650; cursor:pointer; box-shadow:0 .2rem .35rem rgba(0,0,0,.14); }
  .action:hover:not(:disabled) { background:var(--color-button-primary-hover); }
  .action:disabled { opacity:.55; cursor:default; }
  .execution-meta { display:grid; justify-items:center; gap:var(--spacing-2); color:var(--color-font-secondary); text-align:center; font-size:var(--font-size-small); }
  .execution-meta p { margin:0; }
  .execution-meta strong { color:var(--color-primary); font-weight:650; }
  .errors { color:var(--color-error); }
  .errors p { margin:0; }
  .errors ul { margin:.25rem 0 0; padding-inline-start:1.5rem; }
  .unavailable { color:var(--color-font-secondary); }
  button:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:2px; }
  @media(max-width:600px) { .action-row { grid-template-columns:1fr; justify-items:center; } .settings-toggle,.action { grid-column:1; justify-self:center; } }
</style>
