// Read-only in-page timing probes for the private Personal DevTest workflow.
interface SelectedFrameResult {
	outcome: 'visible' | 'missing_click' | 'visible_text_timeout' | 'cancelled';
	click_to_readable_frame_ms: number | null;
}

type ProbeWindow = Window & {
	__devTestSelectedFrame?: {
		result: Promise<SelectedFrameResult>;
		stop: () => void;
		clickEpoch: () => number | null;
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
	browser.__devTestSelectedFrame = {
		result,
		stop: () => finish('cancelled'),
		clickEpoch: () => clickAt === null ? null : performance.timeOrigin + clickAt,
	};
}

export async function takeSelectedFrameProbe(): Promise<SelectedFrameResult> {
	return await (window as ProbeWindow).__devTestSelectedFrame?.result
		?? { outcome: 'missing_click', click_to_readable_frame_ms: null };
}

/** Compare the trusted click to browser request timing without adding it to the report. */
export function selectedFrameClickEpoch(): number | null {
	return (window as ProbeWindow).__devTestSelectedFrame?.clickEpoch() ?? null;
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


interface ColdChatScan {
	chatId: string | null;
	checked: number;
	missingMetadata: number;
	ineligibleMetadata: number;
	positiveHistory: number;
	retained: number;
}

/** Inspect only keyed saved rows and their bounded set of transcript counts. */
export function inspectColdChatRows(chatIds: string[]): Promise<ColdChatScan | null> {
	return new Promise(resolve => {
		let db: IDBDatabase | null = null;
		let tx: IDBTransaction | null = null;
		let settled = false;
		const finish = (result: ColdChatScan | null) => {
			if (settled) return;
			settled = true;
			window.clearTimeout(timer);
			if (!result) {
				try { tx?.abort(); } catch { /* The readonly transaction already ended. */ }
			}
			db?.close();
			resolve(result);
		};
		const timer = window.setTimeout(() => finish(null), 3000);
		const request = indexedDB.open('chats_db');
		request.onupgradeneeded = () => { request.transaction?.abort(); finish(null); };
		request.onblocked = request.onerror = () => finish(null);
		request.onsuccess = () => {
			db = request.result;
			if (settled) { db.close(); return; }
			db.onversionchange = () => finish(null);
			const messageStores = ['messages', 'saved_messages_v34'].filter(store => db!.objectStoreNames.contains(store));
			if (!messageStores.length) { finish(null); return; }
			const ids = [...new Set(chatIds)].slice(0, 48);
			const scan: ColdChatScan = { chatId: null, checked: ids.length, missingMetadata: 0,
				ineligibleMetadata: 0, positiveHistory: 0, retained: 0 };
			const counts = new Map<string, number>();
			try {
				tx = db.transaction(['chats', ...messageStores], 'readonly');
				const chats = tx.objectStore('chats');
				const indexes = messageStores.map(store => tx!.objectStore(store).index('chat_id'));
				for (const id of ids) {
					const chat = chats.get(id);
					chat.onsuccess = () => {
						const meta = chat.result;
						if (!meta) { scan.missingMetadata++; return; }
						if (meta.chat_id !== id || meta.is_incognito || meta.is_anonymous || meta.team_id || meta.hashed_team_id
							|| meta.chat_visibility === 'direct' || !Number.isSafeInteger(meta.messages_v) || meta.messages_v <= 0) {
							scan.ineligibleMetadata++;
							return;
						}
						scan.positiveHistory++;
						counts.set(id, 0);
						for (const index of indexes) {
							const count = index.count(id);
							count.onsuccess = () => counts.set(id, (counts.get(id) ?? 0) + count.result);
						}
					};
				}
				tx.oncomplete = () => {
					scan.retained = [...counts.values()].filter(count => count > 0).length;
					scan.chatId = ids.find(id => counts.get(id) === 0) ?? null;
					finish(scan);
				};
				tx.onerror = tx.onabort = () => finish(null);
			} catch { finish(null); }
		};
	});
}


/** Only an exact, bounded authenticated Personal startup offer can classify a selection. */
export function readPersonalOpenedOffer(payload: unknown, receivedAt: number) {
	if (typeof payload !== 'object' || payload === null || !Number.isFinite(receivedAt)) return null;
	const { team_id, chat_id, offline_chat_ids } = payload as Record<string, unknown>;
	const validId = (id: unknown): id is string => typeof id === 'string'
		&& /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(id);
	if (team_id !== null || !Array.isArray(offline_chat_ids) || offline_chat_ids.length > 11
		|| !offline_chat_ids.every(validId) || new Set(offline_chat_ids).size !== offline_chat_ids.length
		|| chat_id !== (offline_chat_ids[0] ?? null)) return null;
	return { ids: offline_chat_ids as string[], head: chat_id as string | null, receivedAt };
}

/** Only numeric and boolean evidence leaves the in-memory offer comparison. */
export function personalOpenedOfferEvidence(
	offer: ReturnType<typeof readPersonalOpenedOffer>, chatId: string, observedAt: number | null,
) {
	const seen = offer !== null && observedAt !== null && offer.receivedAt <= observedAt;
	return {
		personal_offer_observed_before_click: seen,
		selected_in_personal_offer: seen ? offer.ids.includes(chatId) : null,
		selected_is_offered_head: seen ? offer.head === chatId : null,
		offer_received_before_click_ms: seen ? Math.round(observedAt - offer.receivedAt) : null,
	};
}

/** The current physical store only, queried by the selected chat's exact index. */
export function countSelectedDurableMessages(chatId: string): Promise<number | null> {
	return new Promise(resolve => {
		let db: IDBDatabase | null = null;
		let settled = false;
		const finish = (count: number | null) => {
			if (settled) return;
			settled = true;
			clearTimeout(deadline);
			db?.close();
			resolve(count);
		};
		const deadline = window.setTimeout(() => finish(null), 1500);
		const request = indexedDB.open('chats_db');
		request.onupgradeneeded = () => { request.transaction?.abort(); finish(null); };
		request.onblocked = request.onerror = () => finish(null);
		request.onsuccess = () => {
			db = request.result;
			if (settled) { db.close(); return; }
			db.onversionchange = () => finish(null);
			try {
				const store = db.objectStoreNames.contains('saved_messages_v34') ? 'saved_messages_v34' : 'messages';
				const tx = db.transaction(store, 'readonly');
				const count = tx.objectStore(store).index('chat_id').count(chatId);
				tx.oncomplete = () => finish(count.result);
				tx.onabort = tx.onerror = () => finish(null);
			} catch { finish(null); }
		};
	});
}
