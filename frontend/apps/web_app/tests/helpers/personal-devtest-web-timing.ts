// Read-only in-page timing probes for the private Personal DevTest workflow.
interface SelectedFrameResult {
	outcome: 'visible' | 'missing_click' | 'visible_text_timeout' | 'cancelled';
	click_to_readable_frame_ms: number | null;
}

type ProbeWindow = Window & {
	__devTestSelectedFrame?: {
		result: Promise<SelectedFrameResult>;
		stop: () => void;
	};
};

/** Browser-side and self-contained for page.evaluate. No account data leaves the page. */
export function armSelectedFrameProbe({ rowSelector, chatId, timeoutMs }: {
	rowSelector: string; chatId: string; timeoutMs: number;
}): void {
	const browser = window as ProbeWindow;
	browser.__devTestSelectedFrame?.stop();
	const activeSelector = '[data-testid="active-chat-container"]';
	const historySelector = '[data-testid="chat-history-content"]';
	const messageSelector = ':is([data-testid="message-user"], [data-testid="message-assistant"])[data-message-id]';
	let clickAt: number | null = null;
	let animation = 0;
	let finished = false;
	const oldMessages = new Set<string>();
	let complete!: (result: SelectedFrameResult) => void;
	const result = new Promise<SelectedFrameResult>(resolve => { complete = resolve; });
	const finish = (outcome: SelectedFrameResult['outcome'], elapsed: number | null = null) => {
		if (finished) return;
		finished = true;
		window.clearTimeout(timer);
		cancelAnimationFrame(animation);
		document.removeEventListener('click', onClick, true);
		oldMessages.clear();
		complete({ outcome, click_to_readable_frame_ms: elapsed });
	};

	const hasVisibleText = (body: Element, viewport: DOMRect) => {
		if (!body.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
		const bounds = body.getBoundingClientRect();
		if (bounds.bottom <= Math.max(0, viewport.top) || bounds.top >= Math.min(innerHeight, viewport.bottom)) return false;
		const text = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
		const range = document.createRange();
		for (let i = 0; i < 128; i++) {
			const node = text.nextNode();
			if (!node) return false;
			if (!node.nodeValue?.trim() || !node.parentElement
				|| node.parentElement.closest('[data-embed-id], [aria-hidden="true"], [role="status"], button')
				|| !node.parentElement.checkVisibility({ opacityProperty: true, visibilityProperty: true })) continue;
			range.selectNodeContents(node);
			const rects = range.getClientRects();
			for (let index = 0; index < Math.min(rects.length, 128); index++) {
				const rect = rects[index];
				const left = Math.max(rect.left, viewport.left, 0);
				const right = Math.min(rect.right, viewport.right, innerWidth);
				const top = Math.max(rect.top, viewport.top, 0);
				const bottom = Math.min(rect.bottom, viewport.bottom, innerHeight);
				if (right - left < 2 || bottom - top < 6) continue;
				const hit = document.elementFromPoint((left + right) / 2, (top + bottom) / 2);
				if (hit && body.contains(hit)) return true;
			}
		}
		return false;
	};
	const checkFrame = () => {
		if (clickAt === null || finished) return;
		const active = document.querySelector<HTMLElement>(activeSelector);
		if (active?.dataset.authenticated === 'true' && active.dataset.currentChatId === chatId
			&& active.dataset.currentMessageChatConsistent === 'true') {
			const history = active.querySelector<HTMLElement>(historySelector + '[data-current-chat-id="' + CSS.escape(chatId) + '"]');
			const scroll = history?.closest('[data-testid="chat-history-container"]');
			if (history && scroll) {
				const viewport = scroll.getBoundingClientRect();
				const messages = history.querySelectorAll<HTMLElement>(messageSelector);
				// Saved chats mount a bounded window when virtualized. Scan the
				// tail first because it usually occupies the initial viewport.
				for (let index = messages.length - 1; index >= Math.max(0, messages.length - 256); index--) {
					const message = messages[index];
					if (!message.dataset.messageId || oldMessages.has(message.dataset.messageId)
						|| message.dataset.status === 'processing' || message.dataset.streaming === 'true') continue;
					const body = message.querySelector('[data-testid="message-content"]');
					if (body && hasVisibleText(body, viewport)) {
						finish('visible', Math.round(performance.now() - clickAt));
						return;
					}
				}
			}
		}
		animation = requestAnimationFrame(checkFrame);
	};
	const onClick = (event: MouseEvent) => {
		if (!event.isTrusted || !(event.target instanceof Element)) return;
		if (event.target.closest<HTMLElement>(rowSelector)?.dataset.chatId !== chatId) return;
		clickAt = performance.now();
		document.removeEventListener('click', onClick, true);
		// Fail closed if a previous chat's DOM survives its route transition.
		for (const history of document.querySelectorAll<HTMLElement>(historySelector)) {
			if (history.dataset.currentChatId === chatId) continue;
			const rows = history.querySelectorAll<HTMLElement>(messageSelector);
			for (let index = rows.length - 1; index >= Math.max(0, rows.length - 256); index--) {
				const row = rows[index];
				if (row.dataset.messageId) oldMessages.add(row.dataset.messageId);
			}
		}
		animation = requestAnimationFrame(checkFrame);
	};
	const timer = window.setTimeout(
		() => finish(clickAt === null ? 'missing_click' : 'visible_text_timeout'), timeoutMs,
	);
	document.addEventListener('click', onClick, true);
	browser.__devTestSelectedFrame = { result, stop: () => finish('cancelled') };
}

export async function takeSelectedFrameProbe(): Promise<SelectedFrameResult> {
	return await (window as ProbeWindow).__devTestSelectedFrame?.result
		?? { outcome: 'missing_click', click_to_readable_frame_ms: null };
}

export function clearSelectedFrameProbe(): void {
	const browser = window as ProbeWindow;
	browser.__devTestSelectedFrame?.stop();
	delete browser.__devTestSelectedFrame;
}

/** Navigation elapsed times and bytes only, with no route or resource names. */
export function browserNavigationTimings() {
	const navigation = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
	const millis = (time: number | undefined) => time != null && time > 0 ? Math.round(time) : null;
	return navigation ? {
		response_start_ms: millis(navigation.responseStart),
		response_end_ms: millis(navigation.responseEnd),
		dom_interactive_ms: millis(navigation.domInteractive),
		dom_content_loaded_end_ms: millis(navigation.domContentLoadedEventEnd),
		load_event_end_ms: millis(navigation.loadEventEnd),
	} : null;
}
