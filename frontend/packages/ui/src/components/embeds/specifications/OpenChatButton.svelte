<!--
  OpenChatButton.svelte
  The one button style that opens a sub-chat ("Working chat" / "Checking chat")
  in the Specification and Check fullscreen views; props-driven.
-->
<script lang="ts">
  let { label, testId, onclick }: { label: string; testId: string; onclick: () => void } = $props();
</script>

<button type="button" data-testid={testId} {onclick}>{label}</button>

<style>
  button { margin-left: auto; padding: var(--spacing-2) var(--spacing-5); border-radius: var(--radius-5); border: 1px solid var(--color-grey-30); background: transparent; color: var(--color-font-primary); cursor: pointer; }
</style>
