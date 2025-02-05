<script lang="ts">
	import { MyCounterButton, Map } from '@repo/ui';
</script>

<h1>Web</h1>
<MyCounterButton />
<div class="map-container">
	<Map />
</div>
<p>Visit <a href="https://kit.svelte.dev">kit.svelte.dev</a> to read the documentation</p>

<style>
	.map-container {
		margin: 20px 0;
		border: 1px solid #ccc;
		border-radius: 4px;
		overflow: hidden;
	}
</style>
