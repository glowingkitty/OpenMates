<!-- App icon corner shared by live result previews and public illustrations. -->
<script lang="ts">
  let { background, iconUrl, compact = false }: { background: string; iconUrl: string; compact?: boolean } = $props();
</script>

<div class="result-corner" class:compact style:background aria-hidden="true">
  <span style:mask-image={iconUrl}></span>
</div>

<style>
  .result-corner { position: absolute; z-index: 2; top: 0; left: 0; width: 44px; height: 44px; border-end-end-radius: 22px; display: grid; place-items: center; }
  .result-corner.compact { position: static; flex: none; width: 38px; height: 38px; border-radius: var(--radius-3); }
  .result-corner > span { width: 21px; height: 21px; mask-size: contain; mask-position: center; mask-repeat: no-repeat; background: var(--color-font-button); }
</style>
