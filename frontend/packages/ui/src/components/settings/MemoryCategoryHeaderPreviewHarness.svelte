<!--
  Isolated public Memories category shell. Uses the production category to register
  its sibling navigation store and the production AppDetailsHeader to render it.
  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Settings/Views/SettingsView.swift
  - apple/OpenMates/Sources/Features/Settings/Views/SettingsMemoriesFull.swift
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { appSkillsStore } from '../../stores/appSkillsStore';
  import AppDetailsHeader from './AppDetailsHeader.svelte';
  import AppSettingsMemoriesCategory from './AppSettingsMemoriesCategory.svelte';

  interface Props { appId?: string; categoryId?: string; scrollTop?: number; }
  let { appId = 'books', categoryId = 'favorite_books', scrollTop = 0 }: Props = $props();
  // Navigation can override this selection until the category prop changes.
  let selectedCategory = $derived(categoryId);
  let app = $derived(appSkillsStore.getState().apps[appId]);
  let category = $derived(app?.settings_and_memories.find(item => item.id === selectedCategory));
  function navigate(event: CustomEvent<{ settingsPath: string }>) {
    const parts = event.detail.settingsPath.split('/');
    const index = parts.indexOf('settings_memories');
    if (index >= 0 && parts[index + 1]) selectedCategory = parts[index + 1];
  }
</script>

<div class="memory-category-preview">
<AppDetailsHeader
  {appId}
  {app}
  {scrollTop}
  breadcrumbLabel={$text('settings.settings_memories')}
  fullBreadcrumbLabel={$text('settings.settings_memories')}
  onBack={() => { selectedCategory = categoryId; }}
  subItem={{
    name: category?.name_translation_key ? $text(category.name_translation_key) : selectedCategory,
    typeLabel: $text('settings.app_settings_memories.settings_and_memories'),
    description: category?.description_translation_key ? $text(category.description_translation_key) : '',
    iconName: category?.icon_image?.replace(/\.svg$/, '') ?? 'book',
    iconType: 'memory',
  }}
/>
{#key selectedCategory}
  <AppSettingsMemoriesCategory {appId} categoryId={selectedCategory} on:openSettings={navigate} />
{/key}

</div>

<style>
  .memory-category-preview :global(.app-details-header) { opacity: 1; }
  .memory-category-preview { display: flex; flex-direction: column; width: 100%; min-width: 0; }
</style>
