<script lang="ts">
  let { onSubmit }: { onSubmit: (value: string, files: File[]) => Promise<boolean> } = $props();
</script>
<button onclick={() => void onSubmit('Find another option', [])}>Follow up</button>
