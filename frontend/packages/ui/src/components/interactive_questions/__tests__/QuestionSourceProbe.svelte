<script lang="ts">
  import { getContext } from 'svelte';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../../types/embedFullscreen';
  let { value = $bindable(null), isValid = $bindable(false) } = $props();
  const source = getContext<EmbedSourceChatContext>(EMBED_SOURCE_CHAT_CONTEXT);
</script>
<span data-testid="source-chat">{source?.chatId ?? 'none'}</span>
