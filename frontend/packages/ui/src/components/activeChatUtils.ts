// ActiveChat utility helpers.
//
// Extracted from ActiveChat.svelte to keep pure formatting and route-derived
// helpers out of the large interactive component. These helpers deliberately do
// not import Svelte stores or services, so they can be tested independently and
// reused by future welcome/resume-card refactors.

import type { Chat } from '../types/chat';
import type { OpenMatesEvent } from '../data/openmatesEvents';
import { getCategoryGradientColors } from '../utils/categoryUtils';

const OG_EXAMPLE_SHARED_CHAT_CUTTLEFISH = 'shared_chat_cuttlefish';
const DEFAULT_RESUME_CARD_GRADIENT_START = '#4867cd';
const DEFAULT_RESUME_CARD_GRADIENT_END = '#a0beff';

export type GradientColors = { start: string; end: string };

export const AUTHENTICATED_ONLY_DAILY_INSPIRATION_FEATURE_IDS = new Set([
    'export-data',
    'incognito-mode',
]);

export function isOgExampleSharedChatCuttlefish(search = typeof window === 'undefined' ? '' : window.location.search): boolean {
    if (!search) {
        return false;
    }
    const searchParams = new URLSearchParams(search);
    return searchParams.get('og') === '1' && searchParams.get('og_example') === OG_EXAMPLE_SHARED_CHAT_CUTTLEFISH;
}

export function getOgExampleResumeChat(nowTs = Math.floor(Date.now() / 1000)): Chat {
    return {
        chat_id: 'c3343b34-c645-4576-be38-87bef9d0b899',
        encrypted_title: null,
        messages_v: 0,
        title_v: 0,
        last_edited_overall_timestamp: nowTs,
        unread_count: 0,
        created_at: nowTs,
        updated_at: nowTs,
        title: 'Cuttlefish Camouflage Mechanism',
        chat_summary: 'Exploring cuttlefish camouflage mechanisms and examples.',
        category: 'general_knowledge',
        icon: 'sparkles',
    };
}

export function hasOpenMatesEventEnded(event: OpenMatesEvent, nowMs = Date.now()): boolean {
    const endDate = new Date(event.date_end || event.date_start);
    return Number.isNaN(endDate.getTime()) || endDate.getTime() < nowMs;
}

export function formatOpenMatesEventSummary(event: OpenMatesEvent): string | null {
    const start = new Date(event.date_start);
    const date = Number.isNaN(start.getTime())
        ? ''
        : start.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
    const time = Number.isNaN(start.getTime())
        ? ''
        : start.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    return [date, time, event.venue?.city].filter(Boolean).join(' · ') || event.summary || null;
}

export function formatOpenMatesEventContinueTitle(event: OpenMatesEvent): string {
    const start = new Date(event.date_start);
    const date = Number.isNaN(start.getTime())
        ? ''
        : start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    return date ? `${date}: ${event.title}` : event.title;
}

export function getResumeCardGradientStyle(orbColors?: GradientColors | null): string {
    const start = orbColors?.start ?? DEFAULT_RESUME_CARD_GRADIENT_START;
    const end = orbColors?.end ?? DEFAULT_RESUME_CARD_GRADIENT_END;

    return [
        `background: linear-gradient(135deg, ${start}, ${end})`,
        `--orb-color-a: ${start}`,
        `--orb-color-b: ${end}`,
    ].join('; ');
}

export function getResumeLargeCardStyle(
    orbColors?: GradientColors | null,
    tiltTransform?: string,
): string {
    const parts = [getResumeCardGradientStyle(orbColors)];
    if (tiltTransform) {
        parts.push(`transform: ${tiltTransform}`);
    }
    return parts.join('; ');
}

export function getAppGradientColors(appId: string | null | undefined): GradientColors | null {
    if (!appId || !/^[a-z0-9_-]+$/.test(appId)) return null;
    return {
        start: `var(--color-app-${appId}-start, ${DEFAULT_RESUME_CARD_GRADIENT_START})`,
        end: `var(--color-app-${appId}-end, ${DEFAULT_RESUME_CARD_GRADIENT_END})`,
    };
}

export function getContinueGradientColors(
    category: string | null | undefined,
    appId?: string | null,
): GradientColors | null {
    return getAppGradientColors(appId) ?? (category ? getCategoryGradientColors(category) : null);
}

export function getReplayDelay(baseMs: number, speed: number): number {
    return Math.max(40, Math.round(baseMs / Math.max(0.1, speed)));
}

export function splitReplayContent(content: string): string[] {
    const paragraphs = content
        .split(/\n{2,}/)
        .map((part) => part.trim())
        .filter(Boolean);

    if (paragraphs.length > 1) {
        return paragraphs.map((_, index) => paragraphs.slice(0, index + 1).join('\n\n'));
    }

    const sentences = content.match(/[^.!?]+[.!?]+(?:\s+|$)|[^.!?]+$/g)?.map((part) => part.trim()).filter(Boolean) ?? [];
    if (sentences.length > 1) {
        return sentences.map((_, index) => sentences.slice(0, index + 1).join(' '));
    }

    return [content];
}
