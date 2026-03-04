<!--
  Purpose: Developer debugging console that intercepts and displays all browser console logs.
  Architecture context: Debug-only tool, activated via /#console-on URL hash (auto-removed).
  Only rendered in +page.svelte when developer console is active.
  Tests: N/A (debug-only utility)
-->
<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	// Use a plain runtime check instead of $app/environment (this component lives in the
	// shared UI package, not inside a SvelteKit app, so $app/* aliases are not available).
	const isBrowser = typeof window !== 'undefined';

	// --- Props ---
	interface Props {
		/** Called when the user closes the console */
		onClose: () => void;
	}

	let { onClose }: Props = $props();

	// --- Types ---
	type LogLevel = 'log' | 'info' | 'warn' | 'error' | 'debug';

	interface LogEntry {
		id: number;
		level: LogLevel;
		args: string;
		timestamp: string;
	}

	// --- State ---
	let entries = $state<LogEntry[]>([]);
	let logIdCounter = 0;
	let scrollContainer: HTMLElement | null = null;
	let autoScroll = $state(true);

	// Store original console methods so we can restore them on destroy
	// and also call through to the real browser console.
	type ConsoleFn = (...args: unknown[]) => void;
	const originalMethods: Record<LogLevel, ConsoleFn> = {
		log: console.log.bind(console),
		info: console.info.bind(console),
		warn: console.warn.bind(console),
		error: console.error.bind(console),
		debug: console.debug.bind(console)
	};

	// --- Helpers ---

	/**
	 * Serialize a single console argument to a human-readable string.
	 * Handles objects, errors, arrays and primitives.
	 */
	function serializeArg(arg: unknown): string {
		if (arg === null) return 'null';
		if (arg === undefined) return 'undefined';
		if (arg instanceof Error) return `${arg.name}: ${arg.message}`;
		if (typeof arg === 'object') {
			try {
				return JSON.stringify(arg, null, 2);
			} catch {
				return String(arg);
			}
		}
		return String(arg);
	}

	/** Append a new log entry and (optionally) scroll to bottom. */
	function addEntry(level: LogLevel, args: unknown[]) {
		const now = new Date();
		const timestamp = now.toLocaleTimeString(undefined, {
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit',
			fractionalSecondDigits: 3
		} as Intl.DateTimeFormatOptions);

		entries.push({
			id: ++logIdCounter,
			level,
			args: args.map(serializeArg).join(' '),
			timestamp
		});

		// Cap buffer at 500 entries to prevent memory bloat
		const MAX_ENTRIES = 500;
		if (entries.length > MAX_ENTRIES) {
			entries.splice(0, entries.length - MAX_ENTRIES);
		}

		if (autoScroll && scrollContainer) {
			// Defer scrolling to let the DOM update first
			requestAnimationFrame(() => {
				if (scrollContainer) {
					scrollContainer.scrollTop = scrollContainer.scrollHeight;
				}
			});
		}
	}

	/** CSS class for a log level badge. */
	function levelClass(level: LogLevel): string {
		switch (level) {
			case 'error':
				return 'level-error';
			case 'warn':
				return 'level-warn';
			case 'info':
				return 'level-info';
			case 'debug':
				return 'level-debug';
			default:
				return 'level-log';
		}
	}

	// --- Lifecycle ---

	onMount(() => {
		if (!isBrowser) return;

		// Intercept each console method
		(['log', 'info', 'warn', 'error', 'debug'] as LogLevel[]).forEach((level) => {
			(console as unknown as Record<string, ConsoleFn>)[level] = (...args: unknown[]) => {
				// Always call through to the real console so DevTools still works
				originalMethods[level](...args);
				addEntry(level, args);
			};
		});
	});

	onDestroy(() => {
		if (!isBrowser) return;

		// Restore original console methods
		(['log', 'info', 'warn', 'error', 'debug'] as LogLevel[]).forEach((level) => {
			(console as unknown as Record<string, ConsoleFn>)[level] = originalMethods[level];
		});
	});

	function handleClear() {
		entries = [];
	}

	function handleClose() {
		onClose();
	}

	/** Toggle auto-scroll when the user manually scrolls up. */
	function handleScroll() {
		if (!scrollContainer) return;
		const atBottom =
			scrollContainer.scrollHeight - scrollContainer.scrollTop <= scrollContainer.clientHeight + 4;
		autoScroll = atBottom;
	}
</script>

<div class="dev-console" role="log" aria-label="Developer console">
	<!-- Header bar -->
	<div class="console-header">
		<span class="console-title">Developer Console</span>
		<div class="console-actions">
			<button class="action-btn clear-btn" onclick={handleClear} title="Clear console">
				Clear
			</button>
			<button class="action-btn close-btn" onclick={handleClose} title="Close console">
				&#x2715;
			</button>
		</div>
	</div>

	<!-- Log entries -->
	<div
		class="console-body"
		bind:this={scrollContainer}
		onscroll={handleScroll}
	>
		{#if entries.length === 0}
			<div class="empty-state">No console output yet.</div>
		{:else}
			{#each entries as entry (entry.id)}
				<div class="log-entry {levelClass(entry.level)}">
					<span class="log-timestamp">{entry.timestamp}</span>
					<span class="log-level-badge">{entry.level.toUpperCase()}</span>
					<pre class="log-args">{entry.args}</pre>
				</div>
			{/each}
		{/if}
	</div>

	<!-- Auto-scroll indicator -->
	{#if !autoScroll}
		<button
			class="scroll-to-bottom"
			onclick={() => {
				autoScroll = true;
				if (scrollContainer) {
					scrollContainer.scrollTop = scrollContainer.scrollHeight;
				}
			}}
		>
			&#x25BC; Jump to bottom
		</button>
	{/if}
</div>

<style>
	/* ------------------------------------------------------------------ */
	/* Container                                                            */
	/* ------------------------------------------------------------------ */
	.dev-console {
		/* Takes up exactly the height assigned by the parent flex layout   */
		display: flex;
		flex-direction: column;
		width: 100%;
		/* Dark terminal look — intentionally high contrast for readability */
		background-color: #1a1a1a;
		color: #d4d4d4;
		font-family: 'Menlo', 'Consolas', 'Monaco', 'Courier New', monospace;
		font-size: 11px;
		line-height: 1.45;
		border-top: 2px solid #333;
		position: relative;
		overflow: hidden;
	}

	/* ------------------------------------------------------------------ */
	/* Header                                                               */
	/* ------------------------------------------------------------------ */
	.console-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 4px 8px;
		background-color: #252526;
		border-bottom: 1px solid #3c3c3c;
		flex-shrink: 0;
		user-select: none;
	}

	.console-title {
		font-size: 11px;
		font-weight: 600;
		color: #cccccc;
		letter-spacing: 0.04em;
	}

	.console-actions {
		display: flex;
		gap: 4px;
		align-items: center;
	}

	.action-btn {
		background: none;
		border: 1px solid #555;
		color: #aaa;
		cursor: pointer;
		padding: 2px 8px;
		border-radius: 3px;
		font-size: 11px;
		font-family: inherit;
		line-height: 1.4;
		transition: background-color 0.15s ease;
	}

	.action-btn:hover {
		background-color: #3c3c3c;
		color: #fff;
	}

	.close-btn {
		font-size: 12px;
		padding: 2px 6px;
	}

	/* ------------------------------------------------------------------ */
	/* Scrollable log body                                                  */
	/* ------------------------------------------------------------------ */
	.console-body {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		padding: 4px 0;
	}

	/* Custom scrollbar (webkit) */
	.console-body::-webkit-scrollbar {
		width: 6px;
	}
	.console-body::-webkit-scrollbar-track {
		background: #1a1a1a;
	}
	.console-body::-webkit-scrollbar-thumb {
		background: #555;
		border-radius: 3px;
	}
	.console-body::-webkit-scrollbar-thumb:hover {
		background: #777;
	}

	/* ------------------------------------------------------------------ */
	/* Empty state                                                          */
	/* ------------------------------------------------------------------ */
	.empty-state {
		padding: 12px 10px;
		color: #555;
		font-style: italic;
	}

	/* ------------------------------------------------------------------ */
	/* Individual log entries                                               */
	/* ------------------------------------------------------------------ */
	.log-entry {
		display: flex;
		align-items: flex-start;
		gap: 6px;
		padding: 1px 8px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.03);
		min-height: 20px;
	}

	.log-entry:hover {
		background-color: rgba(255, 255, 255, 0.04);
	}

	.log-timestamp {
		color: #666;
		flex-shrink: 0;
		font-size: 10px;
		padding-top: 1px;
	}

	.log-level-badge {
		flex-shrink: 0;
		font-size: 9px;
		font-weight: 700;
		width: 36px;
		text-align: center;
		border-radius: 2px;
		padding: 1px 2px;
		line-height: 1.3;
		letter-spacing: 0.03em;
	}

	.log-args {
		flex: 1;
		margin: 0;
		padding: 0;
		white-space: pre-wrap;
		word-break: break-all;
		font-family: inherit;
		font-size: inherit;
		overflow: hidden;
	}

	/* ------------------------------------------------------------------ */
	/* Level-specific colours                                               */
	/* ------------------------------------------------------------------ */
	.level-log {
		color: #d4d4d4;
	}
	.level-log .log-level-badge {
		background-color: #3a3a3a;
		color: #888;
	}

	.level-info {
		color: #9cdcfe;
	}
	.level-info .log-level-badge {
		background-color: #1a3a5c;
		color: #9cdcfe;
	}

	.level-debug {
		color: #888;
	}
	.level-debug .log-level-badge {
		background-color: #2a2a2a;
		color: #666;
	}

	.level-warn {
		color: #ddb100;
		background-color: rgba(221, 177, 0, 0.05);
	}
	.level-warn .log-level-badge {
		background-color: #4a3800;
		color: #ddb100;
	}

	.level-error {
		color: #f14c4c;
		background-color: rgba(241, 76, 76, 0.06);
	}
	.level-error .log-level-badge {
		background-color: #4a1010;
		color: #f14c4c;
	}

	/* ------------------------------------------------------------------ */
	/* Jump-to-bottom button                                                */
	/* ------------------------------------------------------------------ */
	.scroll-to-bottom {
		position: absolute;
		bottom: 8px;
		left: 50%;
		transform: translateX(-50%);
		background-color: #3c3c3c;
		border: 1px solid #555;
		color: #ccc;
		padding: 4px 12px;
		border-radius: 12px;
		font-size: 11px;
		font-family: inherit;
		cursor: pointer;
		transition: background-color 0.15s ease;
	}

	.scroll-to-bottom:hover {
		background-color: #505050;
		color: #fff;
	}
</style>
