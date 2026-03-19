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
    noMargin = false,
    noAnimation = false
  }: {
    name?: string;
    type?: 'default' | 'app' | 'skill' | 'provider' | 'focus' | 'memory' | 'clickable' | 'subsetting' | 'placeholder';
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
    noAnimation?: boolean;
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

  /**
   * Map icon names to app IDs for CSS variable construction.
   * This handles cases where the icon name differs from the app ID.
   * For example: icon name "image" maps to app ID "images" for --color-app-images CSS variable.
   * 
   * @param iconName - The lowercase icon name
   * @returns The app ID to use for CSS variable construction
   */
  function getAppIdForCssVariable(iconName: string): string {
    // Map icon names to their corresponding app IDs
    if (iconName === 'image') {
      return 'images'; // Icon name "image" maps to app ID "images"
    }
    if (iconName === 'book') {
      return 'books'; // Icon name "book" maps to app ID "books"
    }
    if (iconName === 'heart') {
      return 'health'; // Icon name "heart" maps to app ID "health" (icon file is heart.svg)
    }
    // For all other cases, use the icon name as-is
    return iconName;
  }

  // Compute the final class name using $derived (Svelte 5 runes mode)
  let computedClassName = $derived([
    // Base icon class
    'icon',
    // Add settings_size for subsetting type
    type === 'subsetting' ? 'settings_size' : '',
    // Add subsetting_icon for subsetting type
    type === 'subsetting' ? 'subsetting_icon' : '',
    // Add specific icon class for subsetting type
    type === 'subsetting' ? lowerCaseName : '',
    // Add placeholder class
    type === 'placeholder' ? 'placeholder-icon' : '',
    // Add no-animation class to disable fade-in animation
    noAnimation ? 'no-animation' : '',
    // The rest remains unchanged
    in_header ? 'in_header' : '',
    inline ? 'inline' : '',
    lowerCaseName === 'mates' ? 'mates' : '',
    type === 'provider' ? `provider-icon ${type === 'provider' && ['openai'].includes(lowerCaseName) ? `provider-${lowerCaseName}` : ''}` : 
      (type === 'default' ? lowerCaseName : (type === 'clickable') ? lowerCaseName : type === 'subsetting' ? '' : type === 'placeholder' ? '' : `${type}-${lowerCaseName}`),
    type === 'skill' ? 'skill-icon' : '',
    type === 'focus' ? 'focus-icon' : '',
    type === 'memory' ? 'memory-icon' : '',
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
      type === 'app' ? `--icon-background: var(--color-app-${getAppIdForCssVariable(lowerCaseName)});` : '',
      type === 'focus' ? `--icon-background: var(--icon-focus-background);` : '',
      type === 'skill' ? `--icon-background: var(--icon-skill-background);` : '',
      type === 'memory' ? `--icon-background: var(--icon-memory-background);` : '',
    ].filter(Boolean).join(' ') : '',
  ].filter(Boolean).join(' '));


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
  /*
   * Icon URL CSS variables (--icon-url-{name}) are now auto-generated by
   * scripts/generate-icon-urls.js → src/styles/icon-urls.generated.css
   * and imported globally via index.ts / +layout.svelte.
   * No manual :root block needed here.
   */

  /* Alias mappings for icons whose CSS var name differs from the SVG filename.
   * These supplement the auto-generated vars (which use the exact filename).
   * E.g. Icon.svelte maps name "health" → "heart" in JS, but we also need
   * --icon-url-modify to point to create.svg, --icon-url-openmates to mate.svg, etc.
   */
  :root {
    --icon-url-bfl: var(--icon-url-blackforestlabs);
    --icon-url-modify: var(--icon-url-create);
    --icon-url-openmates: var(--icon-url-mate);
    --icon-url-mistral_ai: var(--icon-url-mistral);
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

  /* Memory / settings icons — pink gradient background, white icon tint */
  .icon.memory-icon {
    border-color: var(--icon-border-color, transparent);
    /* Tint the icon white so it's visible on the pink background */
    &::before {
      filter: brightness(0) invert(1);
    }
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

  /* No animation - icon is immediately visible without fade-in */
  .icon.no-animation {
    opacity: 1 !important;
    animation: none !important;
    animation-delay: 0 !important;
  }
</style>