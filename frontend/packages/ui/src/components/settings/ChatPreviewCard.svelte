<!--
  frontend/packages/ui/src/components/settings/ChatPreviewCard.svelte

  Shared chat preview card for settings surfaces that need to link to a real
  chat. The visual contract intentionally mirrors the large "Continue where you
  left off" card in ActiveChat.svelte so app-store examples do not introduce a
  second preview language.
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import type { Chat } from '../../types/chat';
    import { getContinueGradientColors, getResumeCardGradientStyle } from '../activeChatUtils';
    import { getLucideIcon, getValidIconName } from '../../utils/categoryUtils';

    interface Props {
        chat: Chat;
        appId?: string | null;
        skillId?: string | null;
        memoryCategoryId?: string | null;
        onOpen: (chat: Chat) => void;
    }

    let { chat, appId = null, skillId = null, memoryCategoryId = null, onOpen }: Props = $props();

    let category = $derived(chat.category || 'general_knowledge');
    let gradientColors = $derived(getContinueGradientColors(category, appId));
    let iconName = $derived(getValidIconName(chat.icon || '', category));
    let IconComponent = $derived(getLucideIcon(iconName));
    let title = $derived(chat.title || $text('common.untitled_chat'));
    let summary = $derived(chat.chat_summary || '');
</script>

<button
    class="resume-chat-large-card"
    data-testid="app-store-example-chat-card"
    data-app-id={appId ?? undefined}
    data-skill-id={skillId ?? undefined}
    data-memory-category-id={memoryCategoryId ?? undefined}
    data-chat-id={chat.chat_id}
    type="button"
    style={getResumeCardGradientStyle(gradientColors)}
    onclick={() => onOpen(chat)}
>
    <div class="resume-large-orbs" data-testid="resume-large-orbs" aria-hidden="true">
        <div class="resume-orb resume-orb-1"></div>
        <div class="resume-orb resume-orb-2"></div>
        <div class="resume-orb resume-orb-3"></div>
    </div>
    {#if IconComponent}
        <div class="resume-large-deco resume-large-deco-left">
            <IconComponent size={80} color="white" />
        </div>
        <div class="resume-large-deco resume-large-deco-right">
            <IconComponent size={80} color="white" />
        </div>
    {/if}
    <div class="resume-large-content">
        {#if IconComponent}
            <div class="resume-large-icon">
                <IconComponent size={32} color="white" />
            </div>
        {/if}
        <span class="resume-large-title" data-testid="resume-large-title">{title}</span>
        {#if summary}
            <p class="resume-large-summary">{summary}</p>
        {/if}
    </div>
</button>

<style>
    .resume-chat-large-card {
        position: relative;
        width: 300px;
        min-width: 300px;
        max-width: 300px;
        height: 200px;
        min-height: 200px;
        max-height: 200px;
        border-radius: 30px;
        overflow: hidden;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        user-select: none;
        -webkit-user-select: none;
        -webkit-touch-callout: none;
        border: none;
        padding: 0;
        margin-right: 0;
        filter: none;
        background-color: transparent;
        scale: 1;
        pointer-events: auto;
        box-shadow:
            0 8px 24px rgba(0, 0, 0, 0.16),
            0 2px 6px rgba(0, 0, 0, 0.1);
        transition:
            transform 0.15s ease-out,
            box-shadow 0.2s ease-out;
    }

    .resume-chat-large-card:hover,
    .resume-chat-large-card:active {
        background-color: transparent;
        filter: none;
        scale: 1;
    }

    .resume-chat-large-card:hover {
        transform: scale(0.98);
        box-shadow:
            0 4px 12px rgba(0, 0, 0, 0.12),
            0 1px 3px rgba(0, 0, 0, 0.08);
    }

    .resume-chat-large-card:active {
        transform: scale(0.96) !important;
        transition: transform 0.05s ease-out;
    }

    .resume-chat-large-card:focus {
        outline: 2px solid rgba(255, 255, 255, 0.5);
        outline-offset: 2px;
    }

    .resume-large-content {
        position: relative;
        z-index: var(--z-index-raised-3);
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--spacing-2);
        padding: var(--spacing-8) var(--spacing-12);
        max-width: 260px;
        width: 100%;
        text-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
    }

    .resume-large-icon {
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }

    .resume-large-title {
        display: -webkit-box;
        -webkit-line-clamp: 2;
        line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        font-size: var(--font-size-p);
        font-weight: 700;
        color: var(--color-font-button);
        text-align: center;
        line-height: 1.3;
        max-width: 100%;
    }

    .resume-large-summary {
        margin: 2px 0 0;
        font-size: var(--font-size-xxs);
        font-weight: 500;
        color: rgba(255, 255, 255, 0.85);
        line-height: 1.4;
        text-align: center;
        display: -webkit-box;
        -webkit-line-clamp: 4;
        line-clamp: 4;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }

    .resume-large-orbs {
        position: absolute;
        inset: 0;
        z-index: -1;
        pointer-events: none;
        overflow: hidden;
        border-radius: 30px;
    }

    .resume-orb {
        position: absolute;
        width: 280px;
        height: 240px;
        background: radial-gradient(
            ellipse at center,
            var(--orb-color-b) 0%,
            var(--orb-color-b) 40%,
            transparent 85%
        );
        filter: blur(22px);
        opacity: 0.35;
        will-change: transform, border-radius;
    }

    .resume-orb-1 {
        top: -60px;
        left: -70px;
        background: radial-gradient(ellipse at center, var(--orb-color-a) 0%, var(--orb-color-a) 45%, transparent 85%);
        border-radius: 45% 55% 60% 40%;
    }

    .resume-orb-2 {
        bottom: -70px;
        right: -80px;
        border-radius: 60% 40% 45% 55%;
    }

    .resume-orb-3 {
        top: 30px;
        right: 30px;
        width: 180px;
        height: 160px;
        opacity: 0.25;
        background: radial-gradient(ellipse at center, rgba(255, 255, 255, 0.45) 0%, rgba(255, 255, 255, 0.12) 45%, transparent 85%);
        border-radius: 50% 45% 55% 50%;
    }

    .resume-large-deco {
        position: absolute;
        z-index: var(--z-index-raised-1);
        opacity: 0.14;
        pointer-events: none;
    }

    .resume-large-deco-left {
        left: -16px;
        top: -12px;
        transform: rotate(-18deg);
    }

    .resume-large-deco-right {
        right: -18px;
        bottom: -14px;
        transform: rotate(16deg);
    }
</style>
