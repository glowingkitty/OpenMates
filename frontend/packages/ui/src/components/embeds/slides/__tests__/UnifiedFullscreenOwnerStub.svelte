<!-- Test stand-in for UnifiedEmbedFullscreen: exposes the owning chat the deck passes. -->
<script lang="ts">
  let { owningChatId }: { owningChatId?: string } = $props();
</script>
<div data-testid="owner-probe" data-owning-chat-id={owningChatId ?? ''}></div>
