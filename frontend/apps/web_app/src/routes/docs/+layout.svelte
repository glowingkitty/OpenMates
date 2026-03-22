<script lang="ts">
	/**
	 * Docs Layout Component
	 *
	 * Provides the layout structure for all documentation pages, matching
	 * the main chat page layout pattern:
	 * - Fixed-position sidebar (325px) with slide transition
	 * - Main content area offset by sidebar width with rounded card container
	 * - Responsive: sidebar slides off-screen on mobile, main content fills viewport
	 *
	 * Architecture: docs/architecture/docs-web-app.md
	 * Mirrors: routes/+page.svelte layout pattern
	 */
	import { onMount, onDestroy } from 'svelte';
	import { browser } from '$app/environment';
	import { page } from '$app/state';
	import { Header, Settings, authStore } from '@repo/ui';
	import DocsSidebar from '$lib/components/docs/DocsSidebar.svelte';
	import { docsPanelState } from '$lib/stores/docsPanelState';

	let { children } = $props();

	let isSidebarOpen = $state(true);
	let isInitialLoad = $state(true);

	// Subscribe to store
	const unsubscribe = docsPanelState.isSidebarOpen.subscribe((v: boolean) => {
		isSidebarOpen = v;
	});

	// Track previous path to close sidebar on mobile navigation
	let previousPath = '';

	$effect(() => {
		const currentPath = page.url.pathname;
		if (browser && currentPath && currentPath !== previousPath) {
			previousPath = currentPath;
			if (docsPanelState.isMobile()) {
				docsPanelState.close();
			}
		}
	});

	// Keyboard shortcuts matching the chat page
	function handleKeydown(event: KeyboardEvent) {
		const isModKey = event.metaKey || event.ctrlKey;
		if (!isModKey) return;

		// Cmd/Ctrl+\ — toggle sidebar
		if (event.code === 'Backslash') {
			event.preventDefault();
			docsPanelState.toggle();
		}
	}

	onMount(() => {
		docsPanelState.init();

		// Handle resize
		const handleResize = () => {
			if (docsPanelState.isMobile()) {
				docsPanelState.close();
			}
		};
		window.addEventListener('resize', handleResize);
		window.addEventListener('keydown', handleKeydown);

		// Remove initial-load class after first paint
		requestAnimationFrame(() => {
			isInitialLoad = false;
		});

		return () => {
			window.removeEventListener('resize', handleResize);
			window.removeEventListener('keydown', handleKeydown);
		};
	});

	onDestroy(() => {
		unsubscribe();
	});
</script>

<div class="sidebar" class:closed={!isSidebarOpen}>
	{#if isSidebarOpen}
		<div class="sidebar-content">
			<DocsSidebar onClose={() => docsPanelState.close()} />
		</div>
	{/if}
</div>

<div class="main-content" class:menu-closed={!isSidebarOpen} class:initial-load={isInitialLoad}>
	<Header
		context="webapp"
		isLoggedIn={$authStore.isAuthenticated}
		docsMode={true}
		onToggleSidebar={() => docsPanelState.toggle()}
		{isSidebarOpen}
	/>
	<div class="docs-container">
		<div class="docs-wrapper">
			<div class="active-docs-container">
				{@render children()}
			</div>
		</div>
		<div class="settings-wrapper">
			<Settings isLoggedIn={$authStore.isAuthenticated} />
		</div>
	</div>
</div>

<style>
	:root {
		--sidebar-width: 325px;
		--sidebar-margin: 10px;
	}

	.sidebar {
		position: fixed;
		inset-inline-start: 0;
		top: 0;
		bottom: 0;
		width: var(--sidebar-width);
		background-color: var(--color-grey-20);
		z-index: 10;
		overflow: hidden;
		box-shadow: inset -6px 0 12px -4px rgba(0, 0, 0, 0.25);
		transition:
			transform 0.3s ease,
			opacity 0.3s ease,
			visibility 0.3s ease;
		transform: translateX(0);
		opacity: 1;
		visibility: visible;
	}

	.sidebar.closed {
		transform: translateX(-100%);
		opacity: 0;
		visibility: hidden;
	}

	:global([dir='rtl']) .sidebar.closed {
		transform: translateX(100%);
	}

	:global([dir='rtl']) .sidebar {
		box-shadow: inset 6px 0 12px -4px rgba(0, 0, 0, 0.25);
	}

	.sidebar-content {
		height: 100%;
		width: 100%;
		overflow: hidden;
	}

	.main-content {
		position: fixed;
		inset-inline-start: calc(var(--sidebar-width) + var(--sidebar-margin));
		inset-inline-end: 0;
		top: 0;
		bottom: 0;
		background-color: var(--color-grey-0);
		z-index: 10;
		transition:
			inset-inline-start 0.3s ease,
			transform 0.3s ease;
	}

	.main-content.menu-closed {
		inset-inline-start: var(--sidebar-margin);
	}

	.main-content.initial-load {
		transition: none;
	}

	.docs-container {
		display: flex;
		flex-direction: row;
		height: calc(100vh - 82px);
		height: calc(100dvh - 82px);
		padding: 10px;
		padding-inline-end: 20px;
	}

	.docs-wrapper {
		flex: 1;
		display: flex;
		min-width: 0;
	}

	.active-docs-container {
		background-color: var(--color-grey-20);
		border-radius: 17px;
		flex-grow: 1;
		position: relative;
		min-height: 0;
		height: 100%;
		box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
		overflow-y: auto;
		overflow-x: hidden;
	}

	/* Scrollbar styling matching main chat */
	.active-docs-container::-webkit-scrollbar {
		width: 8px;
	}

	.active-docs-container::-webkit-scrollbar-track {
		background: transparent;
	}

	.active-docs-container::-webkit-scrollbar-thumb {
		background-color: var(--color-grey-40);
		border-radius: 4px;
		border: 2px solid transparent;
	}

	.active-docs-container::-webkit-scrollbar-thumb:hover {
		background-color: var(--color-grey-50);
	}

	.settings-wrapper {
		display: flex;
		align-items: flex-start;
		min-width: fit-content;
	}

	/* Mobile styles */
	@media (max-width: 600px) {
		.docs-container {
			padding-inline-end: 10px;
			height: calc(100vh - 75px);
			height: calc(100dvh - 75px);
		}

		.sidebar {
			width: 100%;
		}

		.main-content {
			inset-inline-start: 0;
			inset-inline-end: 0;
			z-index: 20;
			transform: translateX(0);
			transition: transform 0.3s ease;
		}

		.main-content:not(.menu-closed) {
			transform: translateX(100%);
		}

		.main-content.menu-closed {
			inset-inline-start: 0;
			transform: translateX(0);
		}
	}

	@media (max-width: 600px) {
		:global([dir='rtl']) .main-content:not(.menu-closed) {
			transform: translateX(-100%);
		}
	}
</style>
