<script lang="ts">
  import { onMount } from 'svelte';

  // TODO later replace all existing icons with this component

  // Props for the component using Svelte 5 runes mode
  let { 
    name = '',
    type = 'default',
    inline = false,
    poweredByAI = false,
    size = undefined,
    in_header = false,
    element = 'div',
    color = undefined,
    borderColor = undefined,
    onClick = undefined,
    className = '',
    noMargin = false
  }: {
    name?: string;
    type?: 'default' | 'app' | 'skill' | 'provider' | 'focus' | 'clickable' | 'subsetting' | 'placeholder';
    inline?: boolean;
    poweredByAI?: boolean;
    size?: string | undefined;
    in_header?: boolean;
    element?: 'div' | 'button' | 'span';
    color?: string | undefined;
    borderColor?: string | null | undefined;
    onClick?: (() => void) | undefined;
    className?: string;
    noMargin?: boolean;
  } = $props();

  // Create a reactive variable for the lowercase name using $derived (Svelte 5 runes mode)
  let lowerCaseName = $derived(name ? name.toLowerCase().replace(/\s+/g, '_') : 'placeholder');
  
  // Set type to placeholder if name is empty or null using $effect (Svelte 5 runes mode)
  $effect(() => {
    if (!name && type !== 'placeholder') {
      type = 'placeholder';
    }
  });

  // Constants for icon mappings and provider-specific settings
  const iconMappings: Record<string, string> = {
    'health': 'heart',
    'plants': 'plant',
    'jobs': 'job',
    'events': 'event',
    'photos': 'image',
    'books': 'book',
    'finance': 'money',
    'code': 'coding',
    'hosting': 'server',
    'diagrams': 'diagram',
    'whiteboards': 'whiteboard',
    'messages': 'chat',
    'pdfeditor': 'pdf',
    'anthropic': 'claude',
    'insights': 'insight',
    'privacy': 'lock',
    'apps': 'app',
    'shared': 'share',
    'messengers': 'chat',
    'developers': 'coding',
    'interface': 'language',
    'contacts': 'contact',
    // Add more mappings as needed
  };

  // Constants for provider icon background sizes (default is 55%)
  const providerBackgroundSizes: Record<string, string> = {
    'mistral': '50%',
    // All others use the default 55%
  };

  // Constants for icons that need color inversion in dark mode
  const darkModeInvertIcons: string[] = ['openai'];

  // Function to map icon names to their corresponding icon URL variables
  function getIconUrlName(iconName: string): string {
    // Return the mapped name if it exists, otherwise use the original lowercase name
    return iconMappings[iconName] || iconName;
  }

  // Get the actual icon URL variable name based on the input name using $derived (Svelte 5 runes mode)
  let iconUrlName = $derived(getIconUrlName(lowerCaseName));

  // Special handling for mates icon only using $derived (Svelte 5 runes mode)
  let isSpecialIcon = $derived(lowerCaseName === 'mates');

  // Compute the final class name using $derived (Svelte 5 runes mode)
  let computedClassName = $derived([
    // Base icon class
    'icon',
    // Add settings_size for subsetting type
    type === 'subsetting' ? 'settings_size' : '',
    // Add subsetting_icon for subsetting type
    type === 'subsetting' ? 'subsetting_icon' : '',
    // Add specific icon class for subsetting type
    type === 'subsetting' ? `subsetting_icon_${lowerCaseName}` : '',
    // Add placeholder class
    type === 'placeholder' ? 'placeholder-icon' : '',
    // The rest remains unchanged
    in_header ? 'in_header' : '',
    inline ? 'inline' : '',
    lowerCaseName === 'mates' ? 'mates' : '',
    type === 'provider' ? `provider-icon ${type === 'provider' && ['openai'].includes(lowerCaseName) ? `provider-${lowerCaseName}` : ''}` : 
      (type === 'default' ? lowerCaseName : (type === 'clickable') ? lowerCaseName : type === 'subsetting' ? '' : type === 'placeholder' ? '' : `${type}-${lowerCaseName}`),
    type === 'skill' ? 'skill-icon' : '',
    type === 'focus' ? 'focus-icon' : '',
    poweredByAI ? 'powered_by_ai' : '',
    type === 'clickable' ? `icon_${lowerCaseName}` : '',
    className // Add any custom classes
  ].filter(Boolean).join(' '));

  // Calculate border radius based on size
  function getBorderRadius(): string {
    if (!size) return '';
    
    // Extract numeric value and unit from size
    const match = size.match(/^([\d.]+)([a-z%]*)$/i);
    if (!match) return '';
    
    const [, value, unit] = match;
    const numValue = parseFloat(value);
    
    // Calculate border radius proportionally (approximately 20% of size)
    // This maintains the same proportion as the default 19px radius for 95px icon
    return `border-radius: ${Math.round(numValue * 0.25)}${unit};`;
  }

  // Calculate border thickness based on size
  function getBorderStyle(): string {
    if (!size) return '';
    
    // Extract numeric value and unit from size
    const match = size.match(/^([\d.]+)([a-z%]*)$/i);
    if (!match) return '';
    
    const [, value, unit] = match;
    const numValue = parseFloat(value);
    
    // Reference: 67px has 2.17px border (3.2% of size)
    // Calculate border thickness proportionally
    const borderThickness = `border-width: ${(numValue * 0.032).toFixed(2)}${unit};`;
    
    return borderThickness;
  }

  // Determine which element to render using $derived (Svelte 5 runes mode)
  let actualElement = $derived(onClick && element === 'div' ? 'button' : element);

  // Create a style element for provider icons
  let styleElement: HTMLStyleElement | null = null;

  // Update the style element when the component mounts
  onMount(() => {
    if (type === 'provider' && ['openai'].includes(lowerCaseName)) {
      // Create a style element for the provider icons
      styleElement = document.createElement('style');
      
      // Determine the background size based on the provider
      const bgSize = providerBackgroundSizes[lowerCaseName] || '55%';
      
      // Generate the CSS for the provider icon
      const iconPath = getIconUrlName(lowerCaseName);
      
      // Basic CSS with just the background image and size
      const css = `.icon.provider-icon.provider-${lowerCaseName}::before { 
        background-image: var(--icon-url-${iconPath}); 
        background-size: ${bgSize};
      }`;
      
      // Add dark mode specific styles if needed
      const needsInversion = darkModeInvertIcons.includes(lowerCaseName);
      const darkModeCss = needsInversion ? 
        `@media (prefers-color-scheme: dark) {
          .icon.provider-icon.provider-${lowerCaseName}::before {
            filter: invert(1);
          }
        }` : '';
      
      // Set the style element content
      styleElement.textContent = css + darkModeCss;
      
      // Append the style element to the document head
      document.head.appendChild(styleElement);
    }
    
    // Clean up when the component is destroyed
    return () => {
      if (styleElement) {
        document.head.removeChild(styleElement);
      }
    };
  });

  // Compute the inline style for the icon using $derived (Svelte 5 runes mode)
  let style = $derived([
    size ? `width: ${size}; height: ${size}; min-width: ${size}; min-height: ${size};` : '',
    getBorderStyle(),
    getBorderRadius(), // Keep the existing border radius calculation
    color ? `--icon-color: ${color};` : '',
    borderColor === null ? 'border: none;' : (borderColor ? `border-color: ${borderColor};` : ''),
    // Skip setting these properties for special icons that rely on CSS classes
    (lowerCaseName !== 'mates' && type !== 'subsetting') ? [
      `--icon-name: ${lowerCaseName};`,
      `--icon-url: var(--icon-url-${iconUrlName});`,
      type === 'clickable' ? `--icon-mask-image: var(--icon-url-${iconUrlName});` : '',
      type === 'app' ? `--icon-background: var(--color-app-${lowerCaseName});` : '',
      type === 'focus' ? `--icon-background: var(--icon-focus-background);` : '',
    ].filter(Boolean).join(' ') : '',
  ].filter(Boolean).join(' '));

  // Handle keyboard events for accessibility (keeping for potential future use)
  function handleKeyDown(event: KeyboardEvent) {
    // Trigger click on Enter or Space key
    if (onClick && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      onClick();
    }
  }
</script>

{#if actualElement === 'div'}
  <div 
    class="icon-container {computedClassName}"
    class:no-margin={noMargin} 
    aria-label={name || 'placeholder'} 
    style={style}
  ></div>
{:else if actualElement === 'button'}
  <button 
    class="icon-container {computedClassName}"
    class:no-margin={noMargin} 
    aria-label={name || 'placeholder'} 
    style={style} 
    onclick={onClick}
    type="button"
  ></button>
{:else if actualElement === 'span'}
  <span 
    class="icon-container {computedClassName}"
    class:no-margin={noMargin} 
    aria-label={name || 'placeholder'} 
    style={style}
  ></span>
{/if}

<style>
  /* Define all icon URLs as CSS variables */
  :root {
    /* Clickable and subsetting icons */
    --icon-url-2fa: url('@openmates/ui/static/icons/2fa.svg');
    --icon-url-3dmodels: url('@openmates/ui/static/icons/3dmodels.svg');
    --icon-url-activism: url('@openmates/ui/static/icons/activism.svg');
    --icon-url-ai: url('@openmates/ui/static/icons/ai.svg');
    --icon-url-announcement: url('@openmates/ui/static/icons/announcement.svg');
    --icon-url-anonym: url('@openmates/ui/static/icons/anonym.svg');
    --icon-url-app: url('@openmates/ui/static/icons/app.svg');
    --icon-url-audio: url('@openmates/ui/static/icons/audio.svg');
    --icon-url-audiocall: url('@openmates/ui/static/icons/audiocall.svg');
    --icon-url-authy: url('@openmates/ui/static/icons/authy.svg');
    --icon-url-back: url('@openmates/ui/static/icons/back.svg');
    --icon-url-beauty: url('@openmates/ui/static/icons/beauty.svg');
    --icon-url-bias: url('@openmates/ui/static/icons/bias.svg');
    --icon-url-billing: url('@openmates/ui/static/icons/billing.svg');
    --icon-url-book: url('@openmates/ui/static/icons/book.svg');
    --icon-url-brave: url('@openmates/ui/static/icons/brave.svg');
    --icon-url-business: url('@openmates/ui/static/icons/business.svg');
    --icon-url-calculator: url('@openmates/ui/static/icons/calculator.svg');
    --icon-url-calendar: url('@openmates/ui/static/icons/calendar.svg');
    --icon-url-camera: url('@openmates/ui/static/icons/camera.svg');
    --icon-url-cerebras: url('@openmates/ui/static/icons/cerebras.svg');
    --icon-url-chat: url('@openmates/ui/static/icons/chat.svg');
    --icon-url-check: url('@openmates/ui/static/icons/check.svg');
    --icon-url-claude: url('@openmates/ui/static/icons/claude.svg');
    --icon-url-close: url('@openmates/ui/static/icons/close.svg');
    --icon-url-cloud: url('@openmates/ui/static/icons/cloud.svg');
    --icon-url-coding: url('@openmates/ui/static/icons/coding.svg');
    --icon-url-coins: url('@openmates/ui/static/icons/coins.svg');
    --icon-url-contact: url('@openmates/ui/static/icons/contact.svg');
    --icon-url-copy: url('@openmates/ui/static/icons/copy.svg');
    --icon-url-create: url('@openmates/ui/static/icons/create.svg');
    --icon-url-current_location: url('@openmates/ui/static/icons/current_location.svg');
    --icon-url-cv: url('@openmates/ui/static/icons/cv.svg');
    --icon-url-delete: url('@openmates/ui/static/icons/delete.svg');
    --icon-url-design: url('@openmates/ui/static/icons/design.svg');
    --icon-url-desktop: url('@openmates/ui/static/icons/desktop.svg');
    --icon-url-diagram: url('@openmates/ui/static/icons/diagram.svg');
    --icon-url-discord: url('@openmates/ui/static/icons/discord.svg');
    --icon-url-docs: url('@openmates/ui/static/icons/docs.svg');
    --icon-url-down: url('@openmates/ui/static/icons/down.svg');
    --icon-url-download: url('@openmates/ui/static/icons/download.svg');
    --icon-url-dropdown: url('@openmates/ui/static/icons/dropdown.svg');
    --icon-url-dummyqr: url('@openmates/ui/static/icons/dummyqr.svg');
    --icon-url-eu: url('@openmates/ui/static/icons/eu.svg');
    --icon-url-eu: url('@openmates/ui/static/icons/us.svg');
    --icon-url-event: url('@openmates/ui/static/icons/event.svg');
    --icon-url-fashion: url('@openmates/ui/static/icons/fashion.svg');
    --icon-url-files: url('@openmates/ui/static/icons/files.svg');
    --icon-url-filter: url('@openmates/ui/static/icons/filter.svg');
    --icon-url-firecrawl: url('@openmates/ui/static/icons/firecrawl.svg');
    --icon-url-fitness: url('@openmates/ui/static/icons/fitness.svg');
    --icon-url-fullscreen: url('@openmates/ui/static/icons/fullscreen.svg');
    --icon-url-games: url('@openmates/ui/static/icons/games.svg');
    --icon-url-github: url('@openmates/ui/static/icons/github.svg');
    --icon-url-good: url('@openmates/ui/static/icons/good.svg');
    --icon-url-google: url('@openmates/ui/static/icons/google.svg');
    --icon-url-google-authenticator: url('@openmates/ui/static/icons/google-authenticator.svg');
    --icon-url-guest: url('@openmates/ui/static/icons/guest.svg');
    --icon-url-heart: url('@openmates/ui/static/icons/heart.svg');
    --icon-url-home: url('@openmates/ui/static/icons/home.svg');
    --icon-url-image: url('@openmates/ui/static/icons/image.svg');
    --icon-url-insight: url('@openmates/ui/static/icons/insight.svg');
    --icon-url-introduction: url('@openmates/ui/static/icons/introduction.svg');
    --icon-url-job: url('@openmates/ui/static/icons/job.svg');
    --icon-url-language: url('@openmates/ui/static/icons/language.svg');
    --icon-url-laptop: url('@openmates/ui/static/icons/laptop.svg');
    --icon-url-legal: url('@openmates/ui/static/icons/legal.svg');
    --icon-url-library: url('@openmates/ui/static/icons/library.svg');
    --icon-url-lifecoaching: url('@openmates/ui/static/icons/lifecoaching.svg');
    --icon-url-lock: url('@openmates/ui/static/icons/lock.svg');
    --icon-url-log: url('@openmates/ui/static/icons/log.svg');
    --icon-url-logout: url('@openmates/ui/static/icons/logout.svg');
    --icon-url-mail: url('@openmates/ui/static/icons/mail.svg');
    --icon-url-maps: url('@openmates/ui/static/icons/maps.svg');
    --icon-url-mattermost: url('@openmates/ui/static/icons/mattermost.svg');
    --icon-url-menu: url('@openmates/ui/static/icons/menu.svg');
    --icon-url-meta: url('@openmates/ui/static/icons/meta.svg');
    --icon-url-microsoft-authenticator: url('@openmates/ui/static/icons/microsoft-authenticator.svg');
    --icon-url-proton-authenticator: url('@openmates/ui/static/icons/proton-authenticator.svg');
    --icon-url-minus: url('@openmates/ui/static/icons/minus.svg');
    --icon-url-mistral: url('@openmates/ui/static/icons/mistral.svg');
    --icon-url-modify: url('@openmates/ui/static/icons/create.svg');
    --icon-url-money: url('@openmates/ui/static/icons/money.svg');
    --icon-url-movies: url('@openmates/ui/static/icons/movies.svg');
    --icon-url-news: url('@openmates/ui/static/icons/news.svg');
    --icon-url-notes: url('@openmates/ui/static/icons/notes.svg');
    --icon-url-nutrition: url('@openmates/ui/static/icons/nutrition.svg');
    --icon-url-offline: url('@openmates/ui/static/icons/offline.svg');
    --icon-url-open: url('@openmates/ui/static/icons/open.svg');
    --icon-url-openai: url('@openmates/ui/static/icons/openai.svg');
    --icon-url-opencollective: url('@openmates/ui/static/icons/opencollective.svg');
    --icon-url-opensource: url('@openmates/ui/static/icons/opensource.svg');
    --icon-url-otp-auth: url('@openmates/ui/static/icons/otp-auth.svg');
    --icon-url-patreon: url('@openmates/ui/static/icons/patreon.svg');
    --icon-url-pause: url('@openmates/ui/static/icons/pause.svg');
    --icon-url-pcbdesign: url('@openmates/ui/static/icons/pcbdesign.svg');
    --icon-url-pdf: url('@openmates/ui/static/icons/pdf.svg');
    --icon-url-phone: url('@openmates/ui/static/icons/phone.svg');
    --icon-url-planning: url('@openmates/ui/static/icons/planning.svg');
    --icon-url-plant: url('@openmates/ui/static/icons/plant.svg');
    --icon-url-play: url('@openmates/ui/static/icons/play.svg');
    --icon-url-plus: url('@openmates/ui/static/icons/plus.svg');
    --icon-url-politics: url('@openmates/ui/static/icons/politics.svg');
    --icon-url-project: url('@openmates/ui/static/icons/project.svg');
    --icon-url-projectmanagement: url('@openmates/ui/static/icons/projectmanagement.svg');
    --icon-url-publishing: url('@openmates/ui/static/icons/publishing.svg');
    --icon-url-question: url('@openmates/ui/static/icons/question.svg');
    --icon-url-rating: url('@openmates/ui/static/icons/rating.svg');
    --icon-url-reasoning: url('@openmates/ui/static/icons/reasoning.svg');
    --icon-url-record_video: url('@openmates/ui/static/icons/record_video.svg');
    --icon-url-recordaudio: url('@openmates/ui/static/icons/recordaudio.svg');
    --icon-url-reminder: url('@openmates/ui/static/icons/reminder.svg');
    --icon-url-restore: url('@openmates/ui/static/icons/restore.svg');
    --icon-url-safety: url('@openmates/ui/static/icons/safety.svg');
    --icon-url-search: url('@openmates/ui/static/icons/search.svg');
    --icon-url-secret: url('@openmates/ui/static/icons/secret.svg');
    --icon-url-server: url('@openmates/ui/static/icons/server.svg');
    --icon-url-settings: url('@openmates/ui/static/icons/settings.svg');
    --icon-url-share: url('@openmates/ui/static/icons/share.svg');
    --icon-url-sheets: url('@openmates/ui/static/icons/sheets.svg');
    --icon-url-shipping: url('@openmates/ui/static/icons/shipping.svg');
    --icon-url-shopping: url('@openmates/ui/static/icons/shopping.svg');
    --icon-url-skill: url('@openmates/ui/static/icons/skill.svg');
    --icon-url-slack: url('@openmates/ui/static/icons/slack.svg');
    --icon-url-slides: url('@openmates/ui/static/icons/slides.svg');
    --icon-url-socialmedia: url('@openmates/ui/static/icons/socialmedia.svg');
    --icon-url-sort: url('@openmates/ui/static/icons/sort.svg');
    --icon-url-stop_video: url('@openmates/ui/static/icons/stop_video.svg');
    --icon-url-study: url('@openmates/ui/static/icons/study.svg');
    --icon-url-systemprompt: url('@openmates/ui/static/icons/systemprompt.svg');
    --icon-url-take_photo: url('@openmates/ui/static/icons/take_photo.svg');
    --icon-url-task: url('@openmates/ui/static/icons/task.svg');
    --icon-url-team: url('@openmates/ui/static/icons/team.svg');
    --icon-url-tfas: url('@openmates/ui/static/icons/tfas.svg');
    --icon-url-time: url('@openmates/ui/static/icons/time.svg');
    --icon-url-travel: url('@openmates/ui/static/icons/travel.svg');
    --icon-url-tv: url('@openmates/ui/static/icons/tv.svg');
    --icon-url-up: url('@openmates/ui/static/icons/up.svg');
    --icon-url-upload: url('@openmates/ui/static/icons/upload.svg');
    --icon-url-usage: url('@openmates/ui/static/icons/usage.svg');
    --icon-url-user: url('@openmates/ui/static/icons/user.svg');
    --icon-url-videocall: url('@openmates/ui/static/icons/videocall.svg');
    --icon-url-videos: url('@openmates/ui/static/icons/videos.svg');
    --icon-url-warning: url('@openmates/ui/static/icons/warning.svg');
    --icon-url-weather: url('@openmates/ui/static/icons/weather.svg');
    --icon-url-web: url('@openmates/ui/static/icons/web.svg');
    --icon-url-whiteboard: url('@openmates/ui/static/icons/whiteboard.svg');
    --icon-url-workflow: url('@openmates/ui/static/icons/workflow.svg');
    --icon-url-youtube: url('@openmates/ui/static/icons/youtube.svg');
  }

  /* Base icon container with common styles */
  .icon {
    width: 95px;
    height: 95px;
    border-radius: 19px; /* Default border radius for 95px icons */
    position: relative;
    background: var(--icon-background, var(--icon-background-default));
    border: 2.17px solid var(--icon-border-color, var(--icon-border-color-default));

    /* Add fade-in animation */
    opacity: 0;
    animation: fadeInIcon 0.3s ease-in forwards;
    animation-delay: 800ms;

    /* Common ::before styles for all icons */
    &::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background-position: center;
      background-repeat: no-repeat;
      background-size: 50%;
      background-image: var(--icon-url);
    }
  }

  /* Dynamic icon image based on name */
  .icon[style*="--icon-name"] {
    &::before {
      background-image: var(--icon-url);
    }
  }

  /* App icons */
  .icon[class*="app-"] {
    background: var(--icon-background);
    &::before {
      background-image: var(--icon-mask-image, var(--icon-url));
    }
  }

  .icon.settings_size {
    width: 44px;
    height: 44px;
    border-radius: 10px; /* Keep your existing border radius */
    animation: unset;
    animation-delay: unset;
    opacity: 1;
    border-width: 1.4px; /* 3.2% of 44px = ~1.4px */
  }

  /* Updated subsetting icon - simplified approach */
  .subsetting_icon {
    width: 44px;
    height: 44px;
    position: relative;
    border-radius: 10px; /* Adding border-radius for consistency */
    
    &::after {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: var(--icon-color, var(--color-primary));
      -webkit-mask-size: 50%;
      mask-size: 50%;
      -webkit-mask-repeat: no-repeat;
      mask-repeat: no-repeat;
      -webkit-mask-position: center;
      mask-position: center;
      -webkit-mask-image: var(--icon-mask-image);
      mask-image: var(--icon-mask-image);
    }
  }

  button.clickable-icon {
    /* Reset all previous properties from button css*/
    all: unset;

    /* Define new base properties for clickable icons */
    display: block;
    align-items: center;
    justify-content: center;
    width: 25px;
    height: 25px;
    cursor: pointer;
    background: var(--icon-color, var(--color-primary));
    -webkit-mask-position: center;
    -webkit-mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-position: center;
    mask-repeat: no-repeat;
    mask-size: contain;
    -webkit-mask-image: var(--icon-mask-image);
    mask-image: var(--icon-mask-image);
    background-position: center;
    background-repeat: no-repeat;
    background-size: 60%;
    filter: brightness(0) invert(1);
  }

  /* New class for non-button clickable icons */
  span.clickable-icon,
  div.clickable-icon {
    /* Base properties for div icons */
    display: inline-block;
    width: 20px;
    height: 20px;
    cursor: pointer;
    background: var(--icon-color, var(--color-primary));
    vertical-align: middle;
    -webkit-mask-position: center;
    -webkit-mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-position: center;
    mask-repeat: no-repeat;
    mask-size: contain;
    -webkit-mask-image: var(--icon-mask-image);
    mask-image: var(--icon-mask-image);
  }

  /* Animation for icon fade-in */
  @keyframes fadeInIcon {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  /* Skill icons */
  .icon.skill-icon {
    /* Use custom border color if provided, otherwise use the skill border color */
    border-color: var(--icon-border-color, var(--color-skill-border));
  }

  /* Focus icons */
  .icon.focus-icon {
    /* Use custom border color if provided, otherwise use the focus border color */
    border-color: var(--icon-border-color, var(--color-focus-border));
  }

  /* Powered by AI indicator */
  .icon.powered_by_ai::after {
    content: '';
    position: absolute;
    bottom: -5px;
    right: -5px;
    width: 25px;
    height: 25px;
    border-radius: 50%;
    background: var(--color-app-ai);
    border: 2px solid var(--color-background);
    background-image: var(--icon-url-ai);
    background-position: center;
    background-repeat: no-repeat;
    background-size: 60%;
    filter: brightness(0) invert(1);
  }

  /* Inline icon style */
  .icon.inline {
    display: inline-block;
    vertical-align: middle;
    margin: 0 5px;
  }

  /* Header icon style - smooth opacity transition without delay */
  .icon.in_header {
    width: 67.98px;
    height: 67.98px;
    border-radius: 10px; /* Keep your existing border radius */
    border-width: 1.4px; /* 3.2% of 44px = ~1.4px */
    /* Use fade-in animation but start immediately (no delay) */
    opacity: 0;
    animation: fadeInIcon 0.3s ease-in forwards;
    animation-delay: 0;
  }

  /* Add a style to remove margins when needed */
  .no-margin {
    margin: 0 !important;
    padding: 0 !important;
  }
  
  .no-margin :global(*) {
    margin: 0 !important;
    padding: 0 !important;
  }

  /* Placeholder icon style */
  .icon.placeholder-icon {
    opacity: 0 !important;
  }
  
  .icon.placeholder-icon::before {
    background-image: none;
  }
</style>