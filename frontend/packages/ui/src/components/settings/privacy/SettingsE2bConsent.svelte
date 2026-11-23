<!--
  frontend/packages/ui/src/components/settings/privacy/SettingsE2bConsent.svelte

  Privacy settings entry "Run code in the E2B cloud sandbox": shows the account
  decision and a toggle that changes it (assertion code-run.e2b.upload-consent).
  Reading and writing go through the client core; this only renders and calls.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../../i18n/translations';
  import SettingsItem from '../../SettingsItem.svelte';
  import { readE2bConsent, writeE2bConsent } from '../../../services/rustCore/e2bConsent/e2bConsentClient';
  import type { E2bConsentRecord, E2bDecision } from '../../../services/rustCore/e2bConsent/e2bConsentProtocol';

  let { read = readE2bConsent, write = writeE2bConsent }: {
    read?: () => Promise<E2bConsentRecord>;
    write?: (decision: E2bDecision) => Promise<E2bConsentRecord>;
  } = $props();

  let decision = $state<E2bDecision | null>(null);
  let loaded = $state(false);
  let failed = $state(false);
  let busy = $state(false);

  onMount(async () => {
    try {
      decision = (await read()).decision;
    } catch (error) {
      console.warn('[SettingsE2bConsent] could not read the decision:', error);
      failed = true;
    }
    loaded = true;
  });

  const statusKey = $derived(
    decision === 'allowed' ? 'e2b_consent.settings.status_allowed'
      : decision === 'declined' ? 'e2b_consent.settings.status_declined'
      : 'e2b_consent.settings.status_undecided',
  );

  async function toggle(): Promise<void> {
    if (busy || !loaded) return;
    busy = true;
    failed = false;
    try {
      decision = (await write(decision === 'allowed' ? 'declined' : 'allowed')).decision;
    } catch (error) {
      console.warn('[SettingsE2bConsent] could not save the decision:', error);
      failed = true;
    } finally {
      busy = false;
    }
  }
</script>

<div data-testid="settings-e2b-consent" data-decision={decision ?? 'none'}>
  <SettingsItem
    type="subsubmenu"
    icon="privacy"
    title={$text('e2b_consent.settings.title')}
    subtitleTop={loaded ? $text(statusKey) : ''}
    hasToggle={true}
    checked={decision === 'allowed'}
    onClick={toggle}
  />
  <div class="settings-note"><p>{$text('e2b_consent.settings.description')}</p></div>
  {#if failed}
    <p class="settings-note" data-testid="settings-e2b-consent-error" role="alert">
      {$text('e2b_consent.settings.error')}
    </p>
  {/if}
</div>
