<!--
  Sized host for the fictional memory-consent history proof.
  ChatHistory is a flex child in the application and needs a bounded parent.
  The generic component mount sizes to content, which collapses that child.
  This fixture restores the application layout contract without product CSS changes.
  Architecture: docs/plans/memory-consent-convergence/plan.yml
-->
<script lang="ts">
  import ChatHistory from './ChatHistory.svelte';
  import history, { variants } from './ChatHistory.preview';
  let { reversed = false }: { reversed?: boolean } = $props();
</script>

<div class="history-proof-host" data-testid="memory-history-proof-host">
  <ChatHistory {...(reversed ? variants.reversed : history)} />
</div>

<style>
  .history-proof-host {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: calc(100dvh - 64px);
    min-height: 400px;
  }
</style>
