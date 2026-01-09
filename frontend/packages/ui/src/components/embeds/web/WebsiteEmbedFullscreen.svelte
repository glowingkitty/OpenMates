<!--
  frontend/packages/ui/src/components/embeds/web/WebsiteEmbedFullscreen.svelte
  
  Fullscreen view for Website embeds.
  Uses UnifiedEmbedFullscreen as base and provides website-specific content.
  
  Design based on Figma: https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3643-50967
  
  Features:
  - Receives metadata from WebsiteEmbedPreview when user clicks to open fullscreen
  - Proxies images through preview server for privacy and optimization
  
  Layout Structure:
  - Header image (large rounded preview)
  - Favicon + Title
  - Date metadata
  - "Open on [hostname]" CTA button
  - Description text
  - Snippets section with quote-decorated cards
  
  Bottom bar shows:
  - Web app gradient icon
  - Favicon + truncated title
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  
  /**
   * Props for website embed fullscreen
   */
  interface Props {
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
    /** Extra snippets from backend TOON (pipe-delimited string or array) */
    extra_snippets?: string | string[];
    /** Meta URL favicon (alternative source) */
    meta_url_favicon?: string;
    /** Thumbnail original (alternative image source) */
    thumbnail_original?: string;
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing (from embed:{embed_id} contentRef) */
    embedId?: string;
    /** Optional: Date when data was fetched */
    dataDate?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Whether to show the "chat" button to restore chat visibility (ultra-wide forceOverlayMode) */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button to restore chat visibility */
    onShowChat?: () => void;
  }
  
  let {
    url,
    title,
    description,
    favicon,
    image,
    extra_snippets,
    meta_url_favicon,
    thumbnail_original,
    onClose,
    embedId,
    dataDate,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat
  }: Props = $props();
  
  // ===========================================
  // HTML Sanitization
  // ===========================================
  
  /**
   * List of allowed HTML tags that are safe for text formatting.
   * These tags don't pose XSS risks when their attributes are stripped.
   */
  const ALLOWED_TAGS = new Set([
    'strong', 'b', 'em', 'i', 'u', 's', 'strike', 'del', 'ins',
    'mark', 'small', 'sub', 'sup', 'br', 'wbr'
  ]);
  
  /**
   * Sanitize HTML content to only allow safe formatting tags.
   * Removes all attributes from allowed tags and strips disallowed tags entirely.
   * This prevents XSS attacks while preserving text formatting like <strong>, <em>, etc.
   * 
   * @param html - HTML string that may contain unsafe content
   * @returns Sanitized HTML string safe for rendering with {@html}
   */
  function sanitizeHtml(html: string | undefined): string {
    if (!html) return '';
    
    // Replace allowed tags (keeping only the tag, no attributes)
    // and remove disallowed tags entirely (keeping their text content)
    let result = html;
    
    // Process opening tags: either keep them (without attributes) or remove them
    // We use a non-capturing group (?:...) for attributes since we strip them all for security
    result = result.replace(/<(\/?)([\w-]+)(?:[^>]*)>/gi, (_match, slash, tagName) => {
      const tag = tagName.toLowerCase();
      
      if (ALLOWED_TAGS.has(tag)) {
        // Keep the tag but strip all attributes for security
        return `<${slash}${tag}>`;
      }
      
      // Remove disallowed tags entirely (their content remains)
      return '';
    });
    
    // Decode common HTML entities that might have been double-encoded
    result = result
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&apos;/g, "'");
    
    // Re-encode < and > that aren't part of our allowed tags to prevent injection
    // This handles cases where &lt;script&gt; was decoded above
    result = result.replace(/<(\/?)([\w-]+)([^>]*)>/gi, (match, slash, tagName) => {
      const tag = tagName.toLowerCase();
      if (ALLOWED_TAGS.has(tag)) {
        return `<${slash}${tag}>`;
      }
      // Encode back to prevent rendering
      return match.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    });
    
    return result;
  }
  
  // Debug: Log all props when component is initialized
  // This helps trace data flow issues with extra_snippets and page_age
  $effect(() => {
    console.debug('[WebsiteEmbedFullscreen] Props received:', {
      url,
      title,
      description,
      image,
      extra_snippets,
      extra_snippets_type: typeof extra_snippets,
      extra_snippets_length: typeof extra_snippets === 'string' ? extra_snippets.length : (Array.isArray(extra_snippets) ? extra_snippets.length : 'N/A'),
      dataDate,
      embedId
    });
  });
  
  /**
   * Parse extra_snippets from backend TOON format:
   * - Pipe-delimited string: "snippet1|snippet2|snippet3"
   * - Or already an array: ["snippet1", "snippet2"]
   * Returns a normalized array of snippet strings
   * 
   * Note: Brave Search sometimes includes a " *" marker at the end of snippets
   * which indicates truncated content - we preserve this as-is.
   */
  let snippets = $derived.by(() => {
    console.debug('[WebsiteEmbedFullscreen] Processing extra_snippets:', {
      type: typeof extra_snippets,
      value: extra_snippets,
      isArray: Array.isArray(extra_snippets)
    });
    
    if (!extra_snippets) {
      console.debug('[WebsiteEmbedFullscreen] No extra_snippets provided');
      return [];
    }
    
    // If it's already an array, use it directly
    if (Array.isArray(extra_snippets)) {
      console.debug('[WebsiteEmbedFullscreen] Using extra_snippets array:', extra_snippets.length, 'items');
      return extra_snippets;
    }
    
    // If it's a pipe-delimited string, split it
    if (typeof extra_snippets === 'string' && extra_snippets.trim()) {
      const parsed = extra_snippets.split('|').filter(s => s.trim());
      console.debug('[WebsiteEmbedFullscreen] Parsed extra_snippets string:', parsed.length, 'items', parsed);
      return parsed;
    }
    
    console.debug('[WebsiteEmbedFullscreen] extra_snippets is empty or invalid');
    return [];
  });
  
  /**
   * Extract the main domain from a hostname, stripping subdomains.
   * Examples:
   * - www.theverge.com → theverge.com
   * - docs.openai.com → openai.com
   * - api.example.co.uk → example.co.uk
   * 
   * Handles common two-part TLDs like .co.uk, .com.au, .co.nz, etc.
   */
  function getMainDomain(fullHostname: string): string {
    const parts = fullHostname.split('.');
    
    // If 2 or fewer parts, return as-is (already a main domain)
    if (parts.length <= 2) {
      return fullHostname;
    }
    
    // Check for common two-part TLDs (e.g., .co.uk, .com.au, .co.nz, .org.uk)
    // These need 3 parts: domain + two-part TLD
    const twoPartTLDs = ['co.uk', 'com.au', 'co.nz', 'org.uk', 'com.br', 'co.jp', 'co.kr', 'co.in', 'com.mx', 'com.cn'];
    const lastTwoParts = parts.slice(-2).join('.');
    
    if (twoPartTLDs.includes(lastTwoParts)) {
      // Take last 3 parts (domain + two-part TLD)
      return parts.slice(-3).join('.');
    }
    
    // Default: take last 2 parts (domain + single TLD)
    return parts.slice(-2).join('.');
  }
  
  // Get display values
  let hostname = $derived(() => {
    try {
      const fullHostname = new URL(url).hostname;
      return getMainDomain(fullHostname);
    } catch {
      return url;
    }
  });
  
  let displayTitle = $derived(title || hostname());
  let displayDescription = $derived(description || '');
  
  // Sanitized HTML versions for safe rendering with {@html}
  let sanitizedDescription = $derived(sanitizeHtml(displayDescription));
  
  // Sanitize each snippet for safe HTML rendering
  let sanitizedSnippets = $derived(snippets.map(snippet => sanitizeHtml(snippet)));
  
  // Favicon URL with fallback chain
  let faviconUrl = $derived(
    meta_url_favicon || 
    favicon || 
    `https://preview.openmates.org/api/v1/favicon?url=${encodeURIComponent(url)}`
  );
  
  // Header image URL - proxy through preview server with max_width for optimization
  // The header image container is max 511px wide, so we request 1024px for retina displays
  // Note: We only proxy if we have an actual image URL (not the webpage URL itself)
  // If no image URL is available, we simply don't show a header image
  const HEADER_IMAGE_MAX_WIDTH = 1024; // 2x for retina displays (container is 511px max)
  
  let imageUrl = $derived.by(() => {
    const originalImageUrl = thumbnail_original || image;
    if (!originalImageUrl) {
      return null;
    }
    // Proxy through preview server with max_width to optimize image size
    // This also provides caching and privacy benefits
    return `https://preview.openmates.org/api/v1/image?url=${encodeURIComponent(originalImageUrl)}&max_width=${HEADER_IMAGE_MAX_WIDTH}`;
  });
  
  /**
   * Parse relative time strings from Brave Search API (e.g., "2 weeks ago", "3 days ago")
   * and convert to actual Date objects.
   * 
   * Brave Search returns human-readable strings, not ISO dates, so we need to parse them.
   * 
   * @param relativeTime - String like "2 weeks ago", "3 days ago", "1 month ago"
   * @returns Date object or null if parsing fails
   */
  function parseRelativeTime(relativeTime: string): Date | null {
    if (!relativeTime || typeof relativeTime !== 'string') {
      return null;
    }
    
    const trimmed = relativeTime.trim().toLowerCase();
    
    // Try to parse as ISO date first (fallback for any ISO dates)
    const isoDate = new Date(relativeTime);
    if (!isNaN(isoDate.getTime())) {
      return isoDate;
    }
    
    // Parse relative time patterns like "2 weeks ago", "3 days ago", etc.
    // Patterns: X second(s)/minute(s)/hour(s)/day(s)/week(s)/month(s)/year(s) ago
    const relativePattern = /^(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago$/i;
    const match = trimmed.match(relativePattern);
    
    if (!match) {
      // Handle special cases
      if (trimmed === 'yesterday') {
        const date = new Date();
        date.setDate(date.getDate() - 1);
        return date;
      }
      if (trimmed === 'today' || trimmed === 'just now') {
        return new Date();
      }
      
      console.debug('[WebsiteEmbedFullscreen] Could not parse relative time:', relativeTime);
      return null;
    }
    
    const amount = parseInt(match[1], 10);
    const unit = match[2].toLowerCase();
    const now = new Date();
    
    switch (unit) {
      case 'second':
        now.setSeconds(now.getSeconds() - amount);
        break;
      case 'minute':
        now.setMinutes(now.getMinutes() - amount);
        break;
      case 'hour':
        now.setHours(now.getHours() - amount);
        break;
      case 'day':
        now.setDate(now.getDate() - amount);
        break;
      case 'week':
        now.setDate(now.getDate() - (amount * 7));
        break;
      case 'month':
        now.setMonth(now.getMonth() - amount);
        break;
      case 'year':
        now.setFullYear(now.getFullYear() - amount);
        break;
      default:
        return null;
    }
    
    return now;
  }
  
  // Format the data date for display (e.g., "Data from 2025/01/05")
  // Only shows a date when dataDate is explicitly provided (e.g., from web search results)
  // Returns null when no date is available - we don't want to mislead users by showing
  // the current date when we don't actually know when the data was fetched
  //
  // Brave Search API returns relative time strings like "2 weeks ago", "3 days ago"
  // which we parse into actual dates and display in YYYY/MM/DD format
  let formattedDate = $derived(() => {
    if (!dataDate) {
      // No date provided - don't show anything rather than showing potentially incorrect date
      return null;
    }
    
    try {
      // Parse the relative time string from Brave Search (e.g., "2 weeks ago")
      const date = parseRelativeTime(dataDate);
      
      if (!date) {
        console.debug('[WebsiteEmbedFullscreen] Could not parse dataDate:', dataDate);
        return null;
      }
      
      // Format as YYYY/MM/DD - language-neutral format
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const day = String(date.getDate()).padStart(2, '0');
      return `Data from ${year}/${month}/${day}`;
    } catch (error) {
      console.warn('[WebsiteEmbedFullscreen] Error parsing dataDate:', dataDate, error);
      return null;
    }
  });
  
  // Handle opening website in new tab
  function handleOpenInNewTab() {
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  }
  
  // Handle share - opens share settings menu for this specific website embed
  async function handleShare() {
    try {
      console.debug('[WebsiteEmbedFullscreen] Opening share settings for website embed:', {
        embedId,
        url,
        title: displayTitle,
        description: displayDescription
      });

      // Check if we have embed_id for proper sharing
      if (!embedId) {
        console.warn('[WebsiteEmbedFullscreen] No embed_id available - cannot create encrypted share link');
        const { notificationStore } = await import('../../../stores/notificationStore');
        notificationStore.error('Unable to share this website embed. Missing embed ID.');
        return;
      }

      // Import required modules
      const { navigateToSettings } = await import('../../../stores/settingsNavigationStore');
      const { settingsDeepLink } = await import('../../../stores/settingsDeepLinkStore');
      const { panelState } = await import('../../../stores/panelStateStore');

      // Set embed context with embed_id for proper encrypted sharing
      const embedContext = {
        type: 'website',
        embed_id: embedId,
        url: url,
        title: displayTitle,
        description: displayDescription,
        favicon: faviconUrl,
        image: imageUrl,
        snippets: snippets
      };

      // Store embed context for SettingsShare
      (window as unknown as { __embedShareContext?: unknown }).__embedShareContext = embedContext;

      // Navigate to share settings
      navigateToSettings('shared/share', 'Share Website', 'share', 'settings.share.share_website.text');
      
      // Also set settingsDeepLink to ensure Settings component navigates properly
      settingsDeepLink.set('shared/share');

      // Open settings panel
      panelState.openSettings();

      console.debug('[WebsiteEmbedFullscreen] Opened share settings for website embed');
    } catch (error) {
      console.error('[WebsiteEmbedFullscreen] Error opening share settings:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to open share menu. Please try again.');
    }
  }
  
  // Track image loading error to hide broken images
  let imageError = $state(false);
</script>

<!-- 
  WebsiteEmbedFullscreen uses UnifiedEmbedFullscreen as base
  Title is set to empty string because we display the title in the content area
  
  Layout matches Figma design:
  - Large header image at top
  - Favicon + Title + Date
  - CTA button
  - Description
  - Snippets with quote cards
-->
<UnifiedEmbedFullscreen
  appId="web"
  skillId="website"
  title=""
  {onClose}
  onShare={handleShare}
  skillIconName="website"
  skillName={displayTitle}
  faviconUrl={faviconUrl}
  showSkillIcon={false}
  showStatus={false}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  <!-- eslint-disable-next-line @typescript-eslint/no-unused-vars -->
  {#snippet content(_)}
    <div class="website-fullscreen-content">
      <!-- Header Image - large rounded preview at top -->
      {#if imageUrl && !imageError}
        <div class="header-image-container">
          <img 
            src={imageUrl} 
            alt={displayTitle}
            class="header-image"
            loading="lazy"
            onerror={() => { imageError = true; }}
          />
        </div>
      {/if}
      
      <!-- Title Section: Favicon + Title -->
      <div class="title-section">
        {#if faviconUrl}
          <img 
            src={faviconUrl} 
            alt="" 
            class="title-favicon"
            onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
          />
        {/if}
        <h1 class="website-title">{displayTitle}</h1>
      </div>
      
      <!-- Date metadata - only shown when we have a specific date from backend (e.g., web search results) -->
      {#if formattedDate()}
        <div class="date-info">{formattedDate()}</div>
      {/if}
      
      <!-- CTA Button - "Open on [hostname]" -->
      <button class="cta-button" onclick={handleOpenInNewTab}>
        Open on {hostname()}
      </button>
      
      <!-- Description - rendered as sanitized HTML to support formatting tags like <strong>, <em> -->
      {#if displayDescription}
        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
        <p class="description">{@html sanitizedDescription}</p>
      {/if}
      
      <!-- Snippets Section -->
      {#if snippets.length > 0}
        <div class="snippets-section">
          <h2 class="snippets-title">Snippets</h2>
          <div class="snippets-source">via Brave Search</div>
          
          <div class="snippets-list">
            {#each sanitizedSnippets as snippet}
              <div class="snippet-card">
                <!-- Opening quote icon (bottom-left) - uses quote.svg from icons system -->
                <div class="quote-icon quote-open clickable-icon icon_quote"></div>
                
                <!-- Closing quote icon (top-right) - rotated 180deg -->
                <div class="quote-icon quote-close clickable-icon icon_quote"></div>
                
                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                <p class="snippet-text">{@html snippet}</p>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Website Fullscreen Content Container
     =========================================== */
  
  .website-fullscreen-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 80px 40px 40px; /* Top padding for action buttons */
    max-width: 600px;
    margin: 0 auto;
    width: 100%;
    box-sizing: border-box;
  }
  
  /* ===========================================
     Header Image
     =========================================== */
  
  .header-image-container {
    width: 100%;
    max-width: 511px;
    border-radius: 30px;
    overflow: hidden;
    margin-bottom: 24px;
    background-color: var(--color-grey-30);
  }
  
  .header-image {
    width: 100%;
    height: auto;
    min-height: 168px;
    max-height: 250px;
    display: block;
    object-fit: cover;
  }
  
  /* ===========================================
     Title Section
     =========================================== */
  
  .title-section {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    width: 100%;
    max-width: 500px;
    margin-bottom: 25px;
  }
  
  .title-favicon {
    width: 28.5px;
    height: 28.5px;
    border-radius: 14.25px;
    flex-shrink: 0;
    border: 1.5px solid white;
    background-color: white;
    object-fit: cover;
    margin-top: 2px;
  }
  
  .website-title {
    font-family: 'Lexend Deca', sans-serif;
    font-size: 22px;
    font-weight: 700;
    color: var(--color-grey-100);
    line-height: 1.3;
    margin: 0;
    word-break: break-word;
  }
  
  /* ===========================================
     Date Info
     =========================================== */
  
  .date-info {
    font-family: 'Lexend Deca', sans-serif;
    font-weight: 700;
    color: #858585;
    width: 100%;
    max-width: 500px;
    margin-bottom: 16px;
    /* Align with title text (accounting for favicon width + gap) */
    padding-left: 40.5px;
  }
  
  /* ===========================================
     CTA Button
     =========================================== */
  
  .cta-button {
    background-color: var(--color-button-primary);
    color: white;
    border: none;
    border-radius: 15px;
    padding: 12px 24px;
    font-family: 'Lexend Deca', sans-serif;
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s, transform 0.15s;
    margin-bottom: 24px;
    min-width: 200px;
  }
  
  .cta-button:hover {
    background-color: var(--color-button-primary-hover);
    transform: translateY(-1px);
  }
  
  .cta-button:active {
    background-color: var(--color-button-primary-pressed);
    transform: translateY(0);
  }
  
  /* ===========================================
     Description
     =========================================== */
  
  .description {
    font-family: 'Lexend Deca', sans-serif;
    font-size: 16px;
    font-weight: 500;
    color: var(--color-grey-100);
    line-height: 1.5;
    width: 100%;
    max-width: 500px;
    margin: 0 0 32px 0;
    word-break: break-word;
  }
  
  /* ===========================================
     Snippets Section
     =========================================== */
  
  .snippets-section {
    width: 100%;
    max-width: 500px;
  }
  
  .snippets-title {
    font-family: 'Lexend Deca', sans-serif;
    font-size: 22px;
    font-weight: 700;
    color: var(--color-grey-100);
    margin: 0 0 4px 0;
  }
  
  .snippets-source {
    font-family: 'Lexend Deca', sans-serif;
    font-weight: 700;
    color: #858585;
    margin-bottom: 16px;
  }
  
  .snippets-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  
  /* ===========================================
     Snippet Card
     =========================================== */
  
  .snippet-card {
    position: relative;
    background-color: var(--color-grey-0);
    border-radius: 30px;
    padding: 24px 50px;
    min-height: 60px;
  }
  
  /* Quote icons positioning - uses CSS mask with quote.svg from icons system */
  .quote-icon {
    position: absolute;
    width: 20px;
    height: 20px;
    /* Override default clickable-icon color to black */
    background: var(--color-grey-100) !important;
    cursor: default;
  }
  
  .quote-open {
    left: 12px;
    bottom: 12px;
  }
  
  .quote-close {
    right: 12px;
    top: 12px;
    /* Rotate 180 degrees to create closing quote appearance */
    transform: rotate(180deg);
  }
  
  .snippet-text {
    font-family: 'Lexend Deca', sans-serif;
    font-size: 16px;
    font-weight: 500;
    color: var(--color-grey-100);
    line-height: 1.5;
    margin: 0;
    word-break: break-word;
  }
  
  /* ===========================================
     Responsive Adjustments
     =========================================== */
  
  /* Smaller screens */
  @container fullscreen (max-width: 600px) {
    .website-fullscreen-content {
      padding: 70px 20px 30px;
    }
    
    .header-image-container {
      border-radius: 20px;
    }
    
    .website-title {
      font-size: 18px;
    }
    
    .date-info {
      font-size: 12px;
      padding-left: 36px;
    }
    
    .title-favicon {
      width: 24px;
      height: 24px;
      border-radius: 12px;
    }
    
    .cta-button {
      padding: 10px 20px;
      min-width: 160px;
    }
    
    .snippets-title {
      font-size: 18px;
    }
    
    .snippet-card {
      padding: 20px 50px;
      border-radius: 20px;
    }
  }
  
  /* Very small screens */
  @container fullscreen (max-width: 400px) {
    .website-fullscreen-content {
      padding: 60px 16px 24px;
    }
    
    .header-image {
      min-height: 120px;
      max-height: 180px;
    }
    
    .title-section {
      gap: 8px;
    }
    
    .website-title {
      font-size: 16px;
    }
    
    .date-info {
      padding-left: 32px;
    }
    
    .snippet-card {
      padding: 16px 40px;
    }
    
    .quote-icon {
      width: 16px;
      height: 16px;
    }
  }
</style>
