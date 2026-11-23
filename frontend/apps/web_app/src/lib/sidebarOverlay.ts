/**
 * Chat sidebar overlay behaviour (TASK-4266).
 *
 * Pure DOM helpers for the web shell's chat sidebar: which viewports use the
 * overlay layout, how wide the overlay is while a touch drag follows the finger,
 * and the keyboard/focus rules (focus into the sidebar on a user-initiated open,
 * back to the menu button on close, Escape closes it). No state is kept here
 * beyond the "the user just pressed the menu button" flag.
 *
 * Geometry and easing live in the CSS of `routes/+page.svelte`
 * (`--sidebar-duration`, `--sidebar-ease`, `--sidebar-overlay-width`); the
 * numbers below must match it.
 */

/** Viewport width (px, inclusive) up to which the sidebar is an overlay. */
export const SIDEBAR_OVERLAY_MAX_WIDTH_PX = 600;
/** Side-by-side sidebar width on larger viewports. */
export const SIDEBAR_DESKTOP_WIDTH_PX = 325;
/** Overlay width: `min(88vw, 360px)`, mirrored from `--sidebar-overlay-width`. */
export const SIDEBAR_OVERLAY_MAX_PX = 360;
export const SIDEBAR_OVERLAY_VIEWPORT_RATIO = 0.88;
/** Animation length in ms, mirrored from `--sidebar-duration`. */
export const SIDEBAR_ANIMATION_MS = 300;

const MENU_BUTTON_SELECTOR = '[data-testid="sidebar-toggle"]';
const SIDEBAR_CLOSE_SELECTOR = '[data-testid="chats-close-button"]';

/** True when the sidebar is shown as an overlay with a backdrop. */
export function isSidebarOverlayViewport(viewportWidth: number): boolean {
	return viewportWidth > 0 && viewportWidth <= SIDEBAR_OVERLAY_MAX_WIDTH_PX;
}

/** Width the sidebar occupies when fully open at this viewport width. */
export function getSidebarOpenWidthPx(viewportWidth: number): number {
	if (!isSidebarOverlayViewport(viewportWidth)) return SIDEBAR_DESKTOP_WIDTH_PX;
	return Math.min(viewportWidth * SIDEBAR_OVERLAY_VIEWPORT_RATIO, SIDEBAR_OVERLAY_MAX_PX);
}

/** Milliseconds the closing animation takes; zero for reduced motion. */
export function getSidebarAnimationMs(): number {
	if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
		return SIDEBAR_ANIMATION_MS;
	}
	return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : SIDEBAR_ANIMATION_MS;
}

// Set when the user presses the header menu button, consumed by the next open.
// Auto-opens (wide viewport on load, shortcuts, edge swipes) must not steal focus.
let menuButtonPressed = false;

/** Starts tracking presses of the header menu button. Returns the cleanup. */
export function trackMenuButtonPress(): () => void {
	const onClick = (event: MouseEvent): void => {
		const target = event.target;
		menuButtonPressed = target instanceof Element && target.closest(MENU_BUTTON_SELECTOR) !== null;
	};
	window.addEventListener('click', onClick, true);
	return () => window.removeEventListener('click', onClick, true);
}

/**
 * After a user-initiated open: moves focus into the sidebar (its close button,
 * else the sidebar itself) unless focus is already inside, e.g. on the search field.
 */
export function focusSidebarAfterOpen(sidebar: HTMLElement | undefined): void {
	const initiatedByMenuButton = menuButtonPressed;
	menuButtonPressed = false;
	if (!sidebar || !initiatedByMenuButton) return;
	if (sidebar.contains(document.activeElement)) return;
	const target = sidebar.querySelector<HTMLElement>(SIDEBAR_CLOSE_SELECTOR) ?? sidebar;
	target.focus({ preventScroll: true });
}

/** Frames to keep retrying: the menu button fades back in while the sidebar slides out. */
const MENU_FOCUS_RETRY_FRAMES = 30;

/**
 * After a close: returns focus to the menu button, but only when focus was lost
 * with the sidebar (on the body, the backdrop, or inside the sidebar) so a
 * deliberate focus elsewhere, such as the message input, is never overridden.
 * The button is still `visibility: hidden` on the first frame of its fade-in and
 * cannot take focus yet, so the call is retried for a few frames. Returns a cancel function.
 */
export function restoreMenuButtonFocus(sidebar: HTMLElement | undefined): () => void {
	let frame = 0;
	let attempts = 0;
	const attempt = (): void => {
		const active = document.activeElement;
		const focusLost =
			!active ||
			active === document.body ||
			(sidebar?.contains(active) ?? false) ||
			(active instanceof HTMLElement && active.dataset.testid === 'sidebar-backdrop');
		const button = document.querySelector<HTMLElement>(MENU_BUTTON_SELECTOR);
		if (!focusLost || !button) return;
		button.focus({ preventScroll: true });
		if (document.activeElement === button) return;
		attempts += 1;
		if (attempts < MENU_FOCUS_RETRY_FRAMES) frame = requestAnimationFrame(attempt);
	};
	frame = requestAnimationFrame(attempt);
	return () => cancelAnimationFrame(frame);
}

/** DOM facts the Escape rule needs. */
export interface SidebarEscapeContext {
	focusInsideSidebar: boolean;
	fullscreenEmbedOpen: boolean;
}

/** Reads the DOM facts for {@link shouldCloseSidebarOnEscape}. */
export function readSidebarEscapeContext(sidebar: HTMLElement | undefined): SidebarEscapeContext {
	return {
		focusInsideSidebar: sidebar?.contains(document.activeElement) ?? false,
		fullscreenEmbedOpen: document.querySelector('.unified-embed-fullscreen-overlay') !== null
	};
}

/**
 * Whether an Escape keydown should close the sidebar. Other layers (search
 * field, fullscreen embeds, menus) that handled the key win; on side-by-side
 * layouts Escape only counts while focus is inside the sidebar, so it never
 * steals the key from the message input.
 */
export function shouldCloseSidebarOnEscape(
	event: { key: string; defaultPrevented: boolean },
	overlayLayout: boolean,
	context: SidebarEscapeContext
): boolean {
	if (event.key !== 'Escape' || event.defaultPrevented) return false;
	if (context.fullscreenEmbedOpen) return false;
	return overlayLayout || context.focusInsideSidebar;
}
