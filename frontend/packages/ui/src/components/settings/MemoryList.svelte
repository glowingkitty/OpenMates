<!-- frontend/packages/ui/src/components/settings/MemoryList.svelte
     Settings > Memories list: Create memory button, search + sort (default most recently
     modified), one SettingsItem row per memory (app icon in the app colour or the Memories
     icon; second line Private/Project and the modified date), Renew for expired memories
     and the character budget. Rows open the memory's own page.
     Spec: specifications/features/app-memories. Preview: /dev/preview/settings/MemoryList
     Native Swift counterparts:
     - apple/OpenMates/Sources/Features/Settings/Views/SettingsMemoriesFull.swift
     - apple/OpenMates/Sources/Features/Settings/Memories/SettingsMemoryDocuments.swift
-->
<script lang="ts">
  import { locale } from 'svelte-i18n';
  import { text } from '../../i18n/translations';
  import SearchSortBar from './SearchSortBar.svelte';
  import {
    SettingsButton, SettingsButtonGroup, SettingsInfoBox, SettingsItem, SettingsLoadingState, SettingsProgressBar,
  } from './elements';
  import { MAX_RULE_CATALOG_CHARS } from '../../utils/ruleDocuments';
  import {
    DEFAULT_MEMORY_SORT, filterMemoryEntries, formatMemoryDate, memoryModifiedAt, sortMemoryEntries,
    type MemoryListEntry, type MemorySort,
  } from '../../utils/memoryListEntries';

  interface Props {
    entries: MemoryListEntry[];
    loading: boolean;
    saving: boolean;
    /** Characters used by every stored memory of this source. */
    usedChars: number;
    /** Private or Project, shown on each row. */
    sourceLabel: string;
    /** Confirmation after the last save, '' for none. */
    notice: string;
    /** Icon class of a known app, null for an unknown or missing app id. */
    appIcon: (appId: string | undefined) => string | null;
    onCreate: () => void;
    onOpen: (entry: MemoryListEntry) => void;
    onRenew: (entry: MemoryListEntry) => void;
  }
  let { entries, loading, saving, usedChars, sourceLabel, notice, appIcon, onCreate, onOpen, onRenew }: Props = $props();

  let searchQuery = $state('');
  let sortBy = $state<string>(DEFAULT_MEMORY_SORT);

  const sortOptions = $derived([
    { value: 'modified', label: $text('memories.sort_recently_modified') },
    { value: 'added', label: $text('memories.sort_recently_added') },
    { value: 'title', label: $text('memories.sort_title') },
  ]);
  const visible = $derived(sortMemoryEntries(filterMemoryEntries(entries, searchQuery), sortBy as MemorySort, $locale || 'en'));
  const budgetPercent = $derived(Math.min(100, Math.round((usedChars / MAX_RULE_CATALOG_CHARS) * 100)));

  function subtitle(entry: MemoryListEntry): string {
    const date = formatMemoryDate(memoryModifiedAt(entry.fields), $locale || 'en');
    return [
      sourceLabel,
      date ? $text('memories.modified_on', { values: { date } }) : '',
      entry.expired ? $text('memories.expired') : '',
    ].filter(Boolean).join(' · ');
  }
</script>

<div data-testid="memory-list-page">
<SettingsButtonGroup align="right">
  <SettingsButton dataTestid="memory-create" disabled={saving || loading} onClick={onCreate}>{$text('memories.create')}</SettingsButton>
</SettingsButtonGroup>

{#if notice}
  <SettingsInfoBox type="success"><p role="status" data-testid="rule-saved-notice">{notice}</p></SettingsInfoBox>
{/if}

{#if loading}
  <SettingsLoadingState text={$text('common.loading')} />
{:else if entries.length === 0}
  <SettingsLoadingState variant="empty" text={$text('memories.empty')} />
{:else}
  <SearchSortBar bind:searchQuery bind:sortBy {sortOptions} searchPlaceholder={$text('common.search')}
    sortLabel={$text('memories.sort_label')} searchTestid="memory-search" sortTestid="memory-sort" />
  <div data-testid="memory-list">
    {#each visible as entry (entry.document.id)}
      <SettingsItem
        type="submenu"
        icon={appIcon(entry.fields.app_id) ?? 'settings_memories'}
        title={entry.fields.title}
        subtitleTop={subtitle(entry)}
        disabled={saving}
        data-testid="memory-row"
        onClick={() => onOpen(entry)}
      />
      {#if entry.expired}
        <SettingsButtonGroup align="left">
          <SettingsButton variant="secondary" size="sm" disabled={saving} dataTestid="memory-renew" onClick={() => onRenew(entry)}>
            {$text('memories.renew')}
          </SettingsButton>
        </SettingsButtonGroup>
      {/if}
    {/each}
  </div>
{/if}

<div data-testid="memory-char-budget">
  <SettingsProgressBar value={budgetPercent} variant={budgetPercent >= 90 ? 'warning' : 'default'}
    label={$text('memories.character_budget', { values: { used: usedChars, max: MAX_RULE_CATALOG_CHARS } })} />
</div>
</div>
