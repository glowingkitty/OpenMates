/**
 * frontend/packages/ui/src/components/embeds/slides/slidesPresentation.ts
 *
 * Pure logic of presenting a deck locally: the (slide, build step) position and
 * how keys and clicks move it, plus the BroadcastChannel messages that keep the
 * presenter window and the audience window in sync. Deck content travels in a
 * message (never in a URL); only a random session id is in the audience URL.
 * Speaker notes are part of the deck markup the audience window receives but
 * the audience view never renders them (SlideCanvas has no notes output).
 */

import { maxStep, type Slide } from './slidesMarkup';

export interface PresentPosition {
  index: number;
  step: number;
}

export type PresentAction = 'next' | 'previous' | 'first' | 'last' | 'exit';

export function clampPosition(slides: Slide[], position: PresentPosition): PresentPosition {
  if (slides.length === 0) return { index: 0, step: 0 };
  const index = Math.min(Math.max(Math.trunc(position.index) || 0, 0), slides.length - 1);
  const step = Math.min(Math.max(Math.trunc(position.step) || 0, 0), maxStep(slides[index]));
  return { index, step };
}

/** Build steps of the current slide come first, then the next slide. */
export function nextPosition(slides: Slide[], position: PresentPosition): PresentPosition {
  const { index, step } = clampPosition(slides, position);
  if (slides.length === 0) return { index, step };
  if (step < maxStep(slides[index])) return { index, step: step + 1 };
  if (index < slides.length - 1) return { index: index + 1, step: 0 };
  return { index, step };
}

/** Going back shows the previous slide with all its build steps revealed. */
export function previousPosition(slides: Slide[], position: PresentPosition): PresentPosition {
  const { index, step } = clampPosition(slides, position);
  if (step > 0) return { index, step: step - 1 };
  if (index > 0) return { index: index - 1, step: maxStep(slides[index - 1]) };
  return { index, step };
}

export function firstPosition(): PresentPosition {
  return { index: 0, step: 0 };
}

export function lastPosition(slides: Slide[]): PresentPosition {
  if (slides.length === 0) return firstPosition();
  const index = slides.length - 1;
  return { index, step: maxStep(slides[index]) };
}

export function applyAction(slides: Slide[], position: PresentPosition, action: PresentAction): PresentPosition {
  switch (action) {
    case 'next':
      return nextPosition(slides, position);
    case 'previous':
      return previousPosition(slides, position);
    case 'first':
      return firstPosition();
    case 'last':
      return lastPosition(slides);
    default:
      return position;
  }
}

export function actionForKey(key: string): PresentAction | null {
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
    case 'PageDown':
    case ' ':
      return 'next';
    case 'ArrowLeft':
    case 'ArrowUp':
    case 'PageUp':
      return 'previous';
    case 'Home':
      return 'first';
    case 'End':
      return 'last';
    case 'Escape':
      return 'exit';
    default:
      return null;
  }
}

/** Keys typed into a field must never drive the presentation. */
export function isTypingTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return !!element && (element.isContentEditable || /^(input|textarea|select)$/i.test(element.tagName ?? ''));
}

export type PresentMessage =
  | { type: 'hello' }
  | { type: 'deck'; markup: string; index: number; step: number }
  | { type: 'goto'; index: number; step: number }
  | { type: 'bye' };

export function presentChannelName(sessionId: string): string {
  return `openmates-slides-present:${sessionId}`;
}

export function isPresentMessage(data: unknown): data is PresentMessage {
  if (!data || typeof data !== 'object') return false;
  const message = data as Record<string, unknown>;
  const hasPosition = Number.isFinite(message.index) && Number.isFinite(message.step);
  switch (message.type) {
    case 'hello':
    case 'bye':
      return true;
    case 'goto':
      return hasPosition;
    case 'deck':
      return hasPosition && typeof message.markup === 'string';
    default:
      return false;
  }
}

export function newPresentSessionId(): string {
  return crypto.randomUUID();
}

export const AUDIENCE_WINDOW_NAME = 'openmates-slides-audience';

export function audienceUrl(sessionId: string): string {
  return `/present?${new URLSearchParams({ session: sessionId })}`;
}

/**
 * Opens the audience window. Must run inside the click handler of the user
 * gesture; returns null when the browser blocked the popup.
 */
export function openAudienceWindow(sessionId: string): Window | null {
  return window.open(audienceUrl(sessionId), AUDIENCE_WINDOW_NAME, 'popup,width=1280,height=720');
}

/** mm:ss, or h:mm:ss from one hour on. */
export function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const two = (n: number) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${two(m)}:${two(s)}` : `${two(m)}:${two(s)}`;
}
