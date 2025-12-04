<!--
  frontend/packages/ui/src/components/embeds/WebsiteEmbedPreview.svelte
  
  Preview component for Website embeds.
  Uses UnifiedEmbedPreview as base and provides website-specific details content.
  
  Details content structure:
  - Processing: URL hostname
  - Finished: title + hostname + preview image (if available)
-->

<script lang="ts">
  import UnifiedEmbedPreview from './UnifiedEmbedPreview.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  
  /**
   * Props for website embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Website URL */
    url: string;
    /** Website title */
    title?: string;
    /** Website description */
    description?: string;
    /** Favicon URL */
    favicon?: string;
    /** Preview image URL */
    image?: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }
  
  let {
    id,
    url,
    title,
    description,
    favicon,
    image,
    status,
    taskId,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Map skillId to icon name
  const skillIconName = 'website';
  
  // Get display values
  let displayTitle = $derived(title || new URL(url).hostname);
  let hostname = $derived(new URL(url).hostname);
  let faviconUrl = $derived(
    favicon || 
    `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(url)}`
  );
  let imageUrl = $derived(
    image || 
    `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(url)}`
  );
  
  // Handle stop button click (not applicable for websites, but included for consistency)
  async function handleStop() {
    // Websites don't have cancellable tasks, but we include this for API consistency
    console.debug('[WebsiteEmbedPreview] Stop requested (not applicable for websites)');
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="web"
  skillId="website"
  skillIconName={skillIconName}
  {status}
  skillName={displayTitle}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={false}
  faviconUrl={faviconUrl}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="website-details" class:mobile={isMobileLayout}>
      {#if status === 'processing'}
        <!-- Processing state: show hostname only -->
        <div class="website-hostname">{hostname}</div>
      {:else if status === 'finished'}
        <!-- Finished state: description on left, image on right (if available) -->
        <!-- Title and favicon are shown in BasicInfosBar, not here -->
        <div class="website-content-row">
          {#if description}
            <div class="website-description">{description}</div>
          {/if}
          
          {#if imageUrl && !isMobileLayout}
            <!-- Preview image on the right (desktop only) -->
            <div class="website-preview-image">
              <img 
                src={imageUrl} 
                alt={displayTitle}
                loading="lazy"
                onerror={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                }}
              />
            </div>
          {/if}
        </div>
      {:else}
        <!-- Error state -->
        <div class="website-error">{hostname}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Website Details Content
     =========================================== */
  
  .website-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .website-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .website-details.mobile {
    justify-content: flex-start;
  }
  
  /* Website content row: description on left, image on right */
  .website-content-row {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    margin-top: 8px;
    flex: 1;
    min-height: 0;
  }
  
  /* Website description on the left */
  .website-description {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.4;
    flex: 1;
    min-width: 0;
    /* Limit to 3 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  .website-details.mobile .website-description {
    font-size: 12px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }
  
  /* Preview image on the right (desktop only) */
  .website-preview-image {
    width: 100px;
    min-width: 100px;
    height: 100px;
    border-radius: 8px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    flex-shrink: 0;
  }
  
  .website-preview-image img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
  }
  
  /* When no image, description takes full width */
  .website-content-row:not(:has(.website-preview-image)) .website-description {
    flex: 1;
    max-width: 100%;
  }
  
  /* Website hostname (for processing state) */
  .website-hostname {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .website-details.mobile .website-hostname {
    font-size: 12px;
  }
  
  /* Error state */
  .website-error {
    font-size: 14px;
    color: var(--color-error);
    line-height: 1.3;
  }
</style>

