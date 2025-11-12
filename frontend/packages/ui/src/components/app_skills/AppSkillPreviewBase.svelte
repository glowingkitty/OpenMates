<!--
  frontend/packages/ui/src/components/app_skills/AppSkillPreviewBase.svelte
  
  Base component for all app skill previews.
  Provides common structure and behavior that can be customized per skill type.
  
  This component handles:
  - Common layout structure (mobile/desktop responsive)
  - Click handling for fullscreen view
  - Status indicators (processing/finished)
  - Base styling and animations
-->

<script lang="ts">
  import type { BaseSkillPreviewData } from '../../types/appSkills';
  
  // Props using Svelte 5 runes
  // Using 'any' for previewData to allow subtypes (e.g., WebSearchSkillPreviewData extends BaseSkillPreviewData)
  // Snippets are typed as 'any' to avoid TypeScript issues with Svelte 5 snippet types
  let {
    id,
    previewData,
    isMobile = false,
    onFullscreen,
    content
  }: {
    id: string;
    previewData: BaseSkillPreviewData | any; // Allow subtypes
    isMobile?: boolean;
    onFullscreen?: () => void;
    content: any; // Snippet type with params
  } = $props();
  
  // Determine if we should use mobile layout
  // Mobile layout: vertical card with button below
  // Desktop layout: horizontal card with button inline
  let useMobileLayout = $derived(isMobile || (typeof window !== 'undefined' && window.innerWidth <= 500));
  
  // Handle click to open fullscreen
  function handleClick() {
    if (previewData.status === 'finished' && onFullscreen) {
      onFullscreen();
    }
  }
  
  // Handle keyboard navigation
  function handleKeydown(e: KeyboardEvent) {
    if ((e.key === 'Enter' || e.key === ' ') && previewData.status === 'finished') {
      e.preventDefault();
      handleClick();
    }
  }
  
  // Create div props with interactive attributes (using type assertion for Svelte 5 onclick syntax)
  // TypeScript doesn't recognize onclick as a valid HTML attribute, but it's valid in Svelte 5
  // Only include interactive attributes when the element is finished and clickable
  const divProps = $derived(
    previewData.status === 'finished' 
      ? ({
          role: 'button',
          tabindex: 0,
          onclick: handleClick,
          onkeydown: handleKeydown
        } as any)
      : {}
  );
</script>

<div
  class="app-skill-preview"
  class:mobile={useMobileLayout}
  class:desktop={!useMobileLayout}
  class:processing={previewData.status === 'processing'}
  class:finished={previewData.status === 'finished'}
  class:error={previewData.status === 'error'}
  {...divProps}
  data-skill-id="{previewData.app_id}.{previewData.skill_id}"
  data-status={previewData.status}
>
  <!-- Main content snippet - skill-specific content goes here -->
  {@render content({ useMobileLayout })}
  
  <!-- Status indicator (processing state) -->
  {#if previewData.status === 'processing'}
    <div class="status-indicator">
      <div class="processing-dot"></div>
    </div>
  {/if}
</div>

<style>
  .app-skill-preview {
    position: relative;
    background-color: var(--color-grey-20);
    border-radius: 30px;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
    transition: background-color 0.2s, transform 0.2s;
    overflow: hidden;
  }
  
  /* Mobile layout: vertical card */
  .app-skill-preview.mobile {
    width: 100%;
    max-width: 100%;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  
  /* Desktop layout: horizontal card */
  .app-skill-preview.desktop {
    width: 100%;
    max-width: 100%;
    padding: 16px 20px;
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 16px;
  }
  
  /* Interactive state for finished previews */
  .app-skill-preview.finished {
    cursor: pointer;
  }
  
  .app-skill-preview.finished:hover {
    background-color: var(--color-grey-15);
    transform: translateY(-2px);
    box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
  }
  
  .app-skill-preview.finished:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }
  
  /* Status indicator for processing state */
  .status-indicator {
    position: absolute;
    top: 16px;
    right: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  
  .processing-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background-color: var(--color-error);
    animation: pulse 1.5s ease-in-out infinite;
  }
  
  @keyframes pulse {
    0%, 100% {
      opacity: 1;
      transform: scale(1);
    }
    50% {
      opacity: 0.5;
      transform: scale(0.8);
    }
  }
  
  /* Error state */
  .app-skill-preview.error {
    border: 1px solid var(--color-error);
    background-color: rgba(var(--color-error-rgb), 0.1);
  }
</style>

