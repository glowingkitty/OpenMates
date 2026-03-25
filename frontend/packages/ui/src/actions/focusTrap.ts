/**
 * focusTrap — Svelte action that traps keyboard focus inside a DOM node.
 *
 * Usage:
 *   <div use:focusTrap={{ onEscape: close }}>…</div>
 *
 * Behaviour:
 *   - On mount: stores the previously-focused element, then focuses the first
 *     focusable child (or the node itself if none found).
 *   - Tab / Shift+Tab wrap around inside the node.
 *   - Escape calls the optional `onEscape` callback.
 *   - On destroy: removes the keydown listener and restores focus to the
 *     element that was focused before the trap was activated.
 *
 * Architecture context: docs/architecture/accessibility.md
 */

/** Selector that matches all natively-focusable elements. */
const FOCUSABLE_SELECTOR = [
	'a[href]',
	'button:not([disabled])',
	'input:not([disabled]):not([type="hidden"])',
	'textarea:not([disabled])',
	'select:not([disabled])',
	'[tabindex]:not([tabindex="-1"])'
].join(', ');

export interface FocusTrapOptions {
	/** Called when the user presses Escape inside the trap. */
	onEscape?: () => void;
}

export function focusTrap(node: HTMLElement, options?: FocusTrapOptions) {
	// Browser-only guard for SSR compatibility
	if (typeof window === 'undefined') {
		return { destroy() {} };
	}

	const previouslyFocused = document.activeElement as HTMLElement | null;

	// Focus the first focusable child, or the node itself
	const firstFocusable = node.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
	if (firstFocusable) {
		firstFocusable.focus();
	} else {
		// Ensure the node itself can receive focus
		if (!node.hasAttribute('tabindex')) {
			node.setAttribute('tabindex', '-1');
		}
		node.focus();
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			options?.onEscape?.();
			return;
		}

		if (event.key !== 'Tab') return;

		const focusables = Array.from(
			node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
		);
		if (focusables.length === 0) return;

		const first = focusables[0];
		const last = focusables[focusables.length - 1];

		if (event.shiftKey && document.activeElement === first) {
			event.preventDefault();
			last.focus();
		} else if (!event.shiftKey && document.activeElement === last) {
			event.preventDefault();
			first.focus();
		}
	}

	node.addEventListener('keydown', handleKeydown);

	return {
		destroy() {
			node.removeEventListener('keydown', handleKeydown);
			previouslyFocused?.focus();
		}
	};
}
