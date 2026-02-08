<!--
  frontend/packages/ui/src/components/embeds/SkillsGroup.svelte
  
  A horizontal scrollable container displaying AppStoreCard components
  for all available skills across all apps.
  
  This component is rendered within demo chat messages when the
  [[skills_group]] placeholder is encountered.
  
  Uses the same AppStoreCard design as the Settings App Store (in skill card mode
  with skillProviders prop) but scaled up for the chat context.
  
  Clicking a card opens the App Store to that skill's detail page.
-->

<script lang="ts">
  import AppStoreCard from '../settings/AppStoreCard.svelte';
  import { getAvailableApps } from '../../services/appSkillsService';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import type { AppMetadata, SkillMetadata } from '../../types/apps';
  
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
   * Get all skills across all apps, each wrapped with parent app context.
   * Sorted alphabetically by skill name translation key for consistent display.
   */
  let allSkills = $derived((() => {
    const appsMap = getAvailableApps();
    const skills: SkillWithApp[] = [];
    
    for (const app of Object.values(appsMap)) {
      for (const skill of app.skills) {
        skills.push({
          skill,
          appId: app.id,
          cardApp: {
            id: app.id, // Use appId so gradient matches the app
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
    
    // Sort by skill name translation key for consistent ordering
    return skills.sort((a, b) => 
      (a.skill.name_translation_key || a.skill.id).localeCompare(b.skill.name_translation_key || b.skill.id)
    );
  })());
  
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
</script>

{#if allSkills.length > 0}
  <div class="skills-group-wrapper">
    <div class="skills-group">
      {#each allSkills as { skill, appId, cardApp } (`${appId}-${skill.id}`)}
        <div class="skill-card-scaled">
          <AppStoreCard 
            app={cardApp} 
            skillProviders={skill.providers}
            onSelect={() => handleSkillSelect(appId, skill.id)} 
          />
        </div>
      {/each}
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
</style>
