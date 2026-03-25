<!--
  ThemeScope — forces a dark or light theme within a scoped container.

  Instead of setting data-theme on <html> (which affects the entire page),
  this component applies the theme CSS variables directly on a wrapper div.
  All child components that use var(--color-*) will inherit the correct values.

  Usage:
    <ThemeScope theme="dark">
      <ChatMessage ... />
    </ThemeScope>

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		theme = 'dark',
		children
	}: {
		theme?: 'dark' | 'light';
		children: Snippet;
	} = $props();
</script>

<div class="theme-scope" data-theme={theme}>
	{@render children()}
</div>

<style>
	.theme-scope {
		width: 100%;
		height: 100%;
	}

	/* Dark theme: mirrors [data-theme="dark"] from theme.css */
	.theme-scope[data-theme='dark'] {
		--color-grey-0: #171717;
		--color-grey-10: #1c1c1c;
		--color-grey-20: #212121;
		--color-grey-25: #252525;
		--color-grey-30: #2c2c2c;
		--color-grey-40: #404040;
		--color-grey-50: #606060;
		--color-grey-60: #808080;
		--color-grey-70: #a0a0a0;
		--color-grey-80: #c0c0c0;
		--color-grey-90: #e0e0e0;
		--color-grey-100: #ffffff;
		--color-grey-blue: #2d2f35;
		--color-font-primary: #e6e6e6;
		--color-font-secondary: #cfcfcf;
		--color-font-tertiary: #c0c0c0;
		--color-bold-text: #c9bbff;
		--color-error: #ff6b6b;
		--color-error-light: rgba(255, 107, 107, 0.15);
		--color-warning: #f0a050;
		--color-warning-bg: rgba(240, 160, 80, 0.15);
	}

	/* Light theme: mirrors :root from theme.css */
	.theme-scope[data-theme='light'] {
		--color-grey-0: #ffffff;
		--color-grey-10: #f9f9f9;
		--color-grey-20: #f3f3f3;
		--color-grey-25: #e8e8e8;
		--color-grey-30: #e3e3e3;
		--color-grey-40: #c4c4c4;
		--color-grey-50: #a6a6a6;
		--color-grey-60: #888888;
		--color-grey-70: #666666;
		--color-grey-80: #444444;
		--color-grey-90: #222222;
		--color-grey-100: #000000;
		--color-grey-blue: #e6eaff;
		--color-font-primary: #000;
		--color-font-secondary: #a9a9a9;
		--color-font-tertiary: #6b6b6b;
		--color-bold-text: #503ba0;
		--color-error: #e74c3c;
		--color-error-light: rgba(231, 76, 60, 0.15);
		--color-warning: #f39c12;
		--color-warning-bg: rgba(243, 156, 18, 0.15);
	}
</style>
