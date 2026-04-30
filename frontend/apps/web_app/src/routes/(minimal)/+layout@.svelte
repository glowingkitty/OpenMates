<!--
	frontend/apps/web_app/src/routes/(minimal)/+layout.svelte

	Minimal layout for routes that must NOT inherit the root +layout.svelte.

	WHY THIS EXISTS:
	  The root +layout.svelte initializes the full SPA: theme, auth, WebSocket,
	  ChatDatabase, i18n, stores, service workers, etc. Routes like /status are
	  public, standalone pages that don't need any of that infrastructure.

	  By placing them in this (minimal) route group, they get only the base
	  CSS (theme + fonts) without any client-side app initialization.
	  This prevents ERR_HTTP2_PROTOCOL_ERROR from WebSocket connections and
	  avoids ChatDatabase/auth store initialization on public pages.
-->
<script lang="ts">
	let { children } = $props();
</script>

{@render children()}
