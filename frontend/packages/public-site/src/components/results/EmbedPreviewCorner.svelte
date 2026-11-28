<!-- App icon corner shared by live result previews and public illustrations. -->
<script lang="ts">
  let { background, iconUrl, inFlow = false }: { background: string; iconUrl: string; inFlow?: boolean } = $props();
</script>

<div class="result-corner" class:in-flow={inFlow} style:background aria-hidden="true" data-testid="embed-preview-corner">
  <span style:mask-image={iconUrl}></span>
</div>

<style>
  .result-corner { position: absolute; z-index: 2; top: 0; left: 0; width: 44px; height: 44px; border-bottom-right-radius: 22px; display: grid; place-items: center; }
  .result-corner.in-flow { position: static; flex: none; align-self: start; }
  .result-corner > span { width: 21px; height: 21px; mask-size: contain; mask-position: center; mask-repeat: no-repeat; background: var(--color-font-button); }
</style>
