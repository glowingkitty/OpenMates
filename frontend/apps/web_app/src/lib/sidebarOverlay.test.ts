import { describe, expect, it } from 'vitest';
import {
	getSidebarOpenWidthPx,
	isSidebarOverlayViewport,
	shouldCloseSidebarOnEscape
} from './sidebarOverlay';

describe('sidebar overlay geometry', () => {
	// contract-test: direct surface=gui.web assertions=chat-navigation.sidebar.overlay-motion,chat-navigation.sidebar.width-transition
	it('uses the overlay up to 600px and side-by-side above', () => {
		expect(isSidebarOverlayViewport(390)).toBe(true);
		expect(isSidebarOverlayViewport(600)).toBe(true);
		expect(isSidebarOverlayViewport(601)).toBe(false);
		expect(isSidebarOverlayViewport(0)).toBe(false);
	});

	// contract-test: direct surface=gui.web assertions=chat-navigation.sidebar.overlay-motion
	it('sizes the overlay to 88% of the viewport, capped at 360px', () => {
		expect(getSidebarOpenWidthPx(390)).toBeCloseTo(343.2);
		expect(getSidebarOpenWidthPx(600)).toBe(360);
		expect(getSidebarOpenWidthPx(1280)).toBe(325);
	});
});

describe('sidebar Escape rule', () => {
	const escape = { key: 'Escape', defaultPrevented: false };
	const idle = { focusInsideSidebar: false, fullscreenEmbedOpen: false };

	// contract-test: direct surface=gui.web assertions=chat-navigation.sidebar.keyboard-focus
	it('ignores other keys and already handled Escape presses', () => {
		expect(shouldCloseSidebarOnEscape({ key: 'a', defaultPrevented: false }, true, idle)).toBe(false);
		expect(shouldCloseSidebarOnEscape({ key: 'Escape', defaultPrevented: true }, true, idle)).toBe(false);
		expect(shouldCloseSidebarOnEscape(escape, true, { ...idle, fullscreenEmbedOpen: true })).toBe(false);
	});

	// contract-test: direct surface=gui.web assertions=chat-navigation.sidebar.keyboard-focus
	it('closes the overlay from anywhere on small viewports', () => {
		expect(shouldCloseSidebarOnEscape(escape, true, idle)).toBe(true);
	});

	// contract-test: direct surface=gui.web assertions=chat-navigation.sidebar.keyboard-focus
	it('on side-by-side layouts only closes while focus is inside the sidebar', () => {
		expect(shouldCloseSidebarOnEscape(escape, false, idle)).toBe(false);
		expect(shouldCloseSidebarOnEscape(escape, false, { ...idle, focusInsideSidebar: true })).toBe(true);
	});
});
