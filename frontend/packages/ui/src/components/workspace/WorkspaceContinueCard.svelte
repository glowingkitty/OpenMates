<!--
  WorkspaceContinueCard.svelte
  Shared large continuation card used by workspace landing screens and linked
  workspace context inside read-only detail views. It preserves the established
  gradient, icon, badge, and animated-orb treatment without duplicating markup.
  Links use native navigation while workspace buttons use an activation callback.
-->

<script lang="ts">
  import { getResumeLargeCardStyle, getContinueGradientColors } from '../activeChatUtils';
  import { getLucideIcon, getValidIconName } from '../../utils/categoryUtils';

  let {
    title,
    summary,
    badge,
    category,
    appId,
    icon,
    testId,
    href,
    source,
    fluid,
    onActivate,
  }: {
    title: string;
    summary: string | null;
    badge: string | null;
    category: string;
    appId: string;
    icon: string;
    testId: string;
    href: string | null;
    source: 'recent' | 'example' | null;
    fluid: boolean;
    onActivate: (() => void) | null;
  } = $props();

  let iconName = $derived(getValidIconName(icon, category));
  let IconComponent = $derived(getLucideIcon(iconName));
  let cardStyle = $derived(getResumeLargeCardStyle(getContinueGradientColors(category, appId)));
</script>

{#snippet content()}
  <div class="resume-large-orbs" aria-hidden="true">
    <div class="resume-orb resume-orb-1"></div>
    <div class="resume-orb resume-orb-2"></div>
    <div class="resume-orb resume-orb-3"></div>
  </div>
  <div class="resume-large-deco resume-large-deco-left"><IconComponent size={80} color="white" /></div>
  <div class="resume-large-deco resume-large-deco-right"><IconComponent size={80} color="white" /></div>
  <div class="resume-large-content">
    {#if badge}<span class="resume-chat-kind-badge">{badge}</span>{/if}
    <div class="resume-large-icon"><IconComponent size={32} color="white" /></div>
    <span class="resume-large-title">{title}</span>
    {#if summary}<p class="resume-large-summary">{summary}</p>{/if}
  </div>
{/snippet}

{#if href}
  <a class="workspace-continue-card" class:fluid data-testid={testId} data-card-source={source ?? undefined} data-category={category} data-icon={iconName} style={cardStyle} {href} onclick={onActivate ?? undefined}>
    {@render content()}
  </a>
{:else}
  <button class="workspace-continue-card" class:fluid data-testid={testId} data-card-source={source ?? undefined} data-category={category} data-icon={iconName} style={cardStyle} type="button" onclick={onActivate ?? undefined}>
    {@render content()}
  </button>
{/if}

<style>
  .workspace-continue-card {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 300px;
    min-width: 300px;
    max-width: 300px;
    height: 200px;
    min-height: 200px;
    max-height: 200px;
    padding: 0;
    overflow: hidden;
    border: 0;
    border-radius: 30px;
    background-color: transparent;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16), 0 2px 6px rgba(0, 0, 0, 0.1);
    color: var(--color-font-button);
    cursor: pointer;
    text-decoration: none;
    transition: transform 0.15s ease-out, box-shadow 0.2s ease-out;
  }

  .workspace-continue-card:hover { transform: scale(0.98); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12), 0 1px 3px rgba(0, 0, 0, 0.08); }
  .workspace-continue-card.fluid { width: min(100%, 300px); min-width: 0; }
  .workspace-continue-card:active { transform: scale(0.96); transition: transform 0.05s ease-out; }
  .workspace-continue-card:focus-visible { outline: 2px solid rgba(255, 255, 255, 0.5); outline-offset: 2px; }
  .resume-large-content { position: relative; z-index: var(--z-index-raised-3); display: flex; flex-direction: column; align-items: center; gap: var(--spacing-2); width: 100%; max-width: 260px; padding: var(--spacing-8) var(--spacing-12); text-shadow: 0 1px 4px rgba(0, 0, 0, 0.3); }
  .resume-chat-kind-badge { display: inline-flex; align-items: center; width: fit-content; padding: 3px 7px; border-radius: var(--radius-full); background: rgba(255, 255, 255, 0.18); color: rgba(255, 255, 255, 0.94); font-size: 0.66rem; font-weight: 700; line-height: 1; backdrop-filter: blur(10px); }
  .resume-large-icon { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; flex-shrink: 0; }
  .resume-large-title { display: -webkit-box; max-width: 100%; overflow: hidden; color: var(--color-font-button); font-size: var(--font-size-p); font-weight: 700; line-height: 1.3; text-align: center; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; }
  .resume-large-summary { display: -webkit-box; margin: 2px 0 0; overflow: hidden; color: rgba(255, 255, 255, 0.85); font-size: var(--font-size-xxs); font-weight: 500; line-height: 1.4; text-align: center; -webkit-box-orient: vertical; -webkit-line-clamp: 4; line-clamp: 4; }
  .resume-large-orbs { position: absolute; inset: 0; z-index: -1; overflow: hidden; border-radius: 30px; pointer-events: none; }
  .resume-orb { position: absolute; width: 280px; height: 240px; background: radial-gradient(ellipse at center, var(--orb-color-b) 0%, var(--orb-color-b) 40%, transparent 85%); filter: blur(22px); opacity: 0.35; }
  .resume-orb-1 { top: -60px; left: -70px; animation: orbMorph1 11s ease-in-out infinite, resumeOrbDrift1 19s ease-in-out infinite; }
  .resume-orb-2 { right: -80px; bottom: -80px; width: 260px; height: 220px; animation: orbMorph2 13s ease-in-out infinite, resumeOrbDrift2 23s ease-in-out infinite; }
  .resume-orb-3 { top: -10px; left: 25%; width: 200px; height: 180px; opacity: 0.38; animation: orbMorph3 17s ease-in-out infinite, resumeOrbDrift3 29s ease-in-out infinite; }
  .resume-large-deco { position: absolute; z-index: var(--z-index-raised); bottom: -8px; display: flex; align-items: center; justify-content: center; width: 80px; height: 80px; pointer-events: none; opacity: 0.3; }
  .resume-large-deco-left { left: -10px; transform: rotate(-15deg); }
  .resume-large-deco-right { right: -10px; transform: rotate(15deg); }
  @media (prefers-reduced-motion: reduce) { .resume-orb { animation: none !important; } }
</style>
