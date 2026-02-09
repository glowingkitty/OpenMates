<!--
  frontend/packages/ui/src/components/embeds/SkillsGroup.svelte
  
  A horizontal scrollable container displaying AppStoreCard components
  for available skills across all apps (excluding AI app).
  
  This component is rendered within demo chat messages when the
  [[skills_group]] placeholder is encountered.
  
  Features:
  - Excludes skills from the AI app (always used, focus on other app skills)
  - Limits display to first 10 items
  - Shows "+ N more" badge at the end when items are truncated
  - Supports custom sort order via sortOrder prop
  
  Uses the same AppStoreCard design as the Settings App Store (in skill card mode
  with skillProviders prop) but scaled up for the chat context.
  
  Clicking a card opens the App Store to that skill's detail page.
-->

<script lang="ts">
  import AppStoreCard from '../settings/AppStoreCard.svelte';
  import { getAvailableApps } from '../../services/appSkillsService';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { text } from '@repo/ui';
  import type { AppMetadata, SkillMetadata } from '../../types/apps';
  
  /** Maximum number of items to display before showing "+N more" */
  const MAX_DISPLAY_ITEMS = 10;
  
  /** App ID to exclude (AI app is always used, focus on other app skills) */
  const EXCLUDED_APP_ID = 'ai';
  
  /**
   * Represents a skill with its parent app context,
   * needed to render AppStoreCard with correct gradient and icon.
   */
  interface SkillWithApp {
    skill: SkillMetadata;
    appId: string;
    /** AppMetadata-shaped object for the AppStoreCard component */
    cardApp: AppMetadata;
  }
  
  /**
   * Props interface for SkillsGroup
   */
  interface Props {
    /**
     * Custom sort order for skills. Array of "appId/skillId" strings in desired display order.
     * Skills in this array appear first (in the specified order),
     * followed by any remaining skills sorted alphabetically.
     * If not provided, skills are sorted alphabetically by name translation key.
     */
    sortOrder?: string[];
  }
  
  let {
    sortOrder
  }: Props = $props();
  
  /**
   * Get all skills across all apps (excluding AI app), each wrapped with parent app context.
   * Supports custom sort order via sortOrder prop.
   */
  let filteredSkills = $derived((() => {
    const appsMap = getAvailableApps();
    const skills: SkillWithApp[] = [];
    
    for (const app of Object.values(appsMap)) {
      // Exclude AI app skills
      if (app.id === EXCLUDED_APP_ID) continue;
      
      for (const skill of app.skills) {
        skills.push({
          skill,
          appId: app.id,
          cardApp: {
            id: app.id,
            name_translation_key: skill.name_translation_key,
            description_translation_key: skill.description_translation_key,
            icon_image: app.icon_image,
            icon_colorgradient: app.icon_colorgradient,
            providers: skill.providers || [],
            skills: [],
            focus_modes: [],
            settings_and_memories: []
          }
        });
      }
    }
    
    if (sortOrder && sortOrder.length > 0) {
      // Custom sort: skills in sortOrder come first (in that order), then remaining alphabetically
      const ordered: SkillWithApp[] = [];
      const remaining: SkillWithApp[] = [];
      
      for (const key of sortOrder) {
        const item = skills.find(s => `${s.appId}/${s.skill.id}` === key);
        if (item) ordered.push(item);
      }
      
      for (const item of skills) {
        if (!sortOrder.includes(`${item.appId}/${item.skill.id}`)) {
          remaining.push(item);
        }
      }
      
      remaining.sort((a, b) => 
        (a.skill.name_translation_key || a.skill.id).localeCompare(b.skill.name_translation_key || b.skill.id)
      );
      return [...ordered, ...remaining];
    }
    
    // Default: sort by skill name translation key
    return skills.sort((a, b) => 
      (a.skill.name_translation_key || a.skill.id).localeCompare(b.skill.name_translation_key || b.skill.id)
    );
  })());
  
  /** Skills to display (limited to MAX_DISPLAY_ITEMS) */
  let displaySkills = $derived(filteredSkills.slice(0, MAX_DISPLAY_ITEMS));
  
  /** Count of remaining skills not shown */
  let remainingCount = $derived(Math.max(0, filteredSkills.length - MAX_DISPLAY_ITEMS));
  
  /**
   * Handle skill card click - open the App Store to the skill's detail page.
   * Uses settingsDeepLink store + panelState.openSettings() to navigate.
   */
  async function handleSkillSelect(appId: string, skillId: string) {
    console.debug('[SkillsGroup] Skill selected:', appId, skillId);
    
    // Set the deep link to the skill's detail page
    settingsDeepLink.set(`app_store/${appId}/skill/${skillId}`);
    
    // Open the settings panel (which will pick up the deep link)
    const { panelState } = await import('../../stores/panelStateStore');
    panelState.openSettings();
  }
  
  /**
   * Handle "+N more" badge click - open the App Store overview
   */
  async function handleMoreClick() {
    settingsDeepLink.set('app_store');
    const { panelState } = await import('../../stores/panelStateStore');
    panelState.openSettings();
  }
</script>

{#if displaySkills.length > 0}
  <div class="skills-group-wrapper">
    <div class="skills-group">
      {#each displaySkills as { skill, appId, cardApp } (`${appId}-${skill.id}`)}
        <div class="skill-card-scaled">
          <AppStoreCard 
            app={cardApp} 
            skillProviders={skill.providers}
            onSelect={() => handleSkillSelect(appId, skill.id)} 
          />
        </div>
      {/each}
      
      <!-- Show "+ N more" badge when there are more items than displayed -->
      {#if remainingCount > 0}
        <button
          class="more-badge"
          onclick={handleMoreClick}
          type="button"
          aria-label={$text('app_store.plus_n_more.text', { values: { count: remainingCount } })}
        >
          <span class="more-text">+ {remainingCount}</span>
        </button>
      {/if}
    </div>
  </div>
{/if}

<style>
  .skills-group-wrapper {
    width: 100%;
    margin: 16px 0;
    overflow: hidden;
  }
  
  .skills-group {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 4px 0;
    scrollbar-width: thin;
    scrollbar-color: var(--color-grey-60) transparent;
  }
  
  .skills-group::-webkit-scrollbar {
    height: 4px;
  }
  
  .skills-group::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .skills-group::-webkit-scrollbar-thumb {
    background-color: var(--color-grey-60);
    border-radius: 2px;
  }
  
  /* Scale up the AppStoreCard for chat context.
     Original: 223x129px, scaled 1.15x: ~256x148px */
  .skill-card-scaled {
    flex-shrink: 0;
    transform: scale(1.15);
    transform-origin: top left;
    width: 256px;
    height: 148px;
  }
  
  .skills-group > :global(*) {
    flex-shrink: 0;
  }
  
  /* "+N more" badge at the end of the scrollable list */
  .more-badge {
    display: flex;
    align-items: center;
    justify-content: center;
    min-width: 80px;
    height: 148px;
    padding: 0 16px;
    background-color: var(--color-grey-30);
    border-radius: 12px;
    border: 1px solid var(--color-grey-40);
    cursor: pointer;
    flex-shrink: 0;
    transition: background-color 0.2s ease, transform 0.2s ease;
  }
  
  .more-badge:hover {
    background-color: var(--color-grey-35);
    transform: translateY(-2px);
  }
  
  .more-badge:active {
    transform: scale(0.96);
  }
  
  .more-text {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-70);
    white-space: nowrap;
  }
</style>
