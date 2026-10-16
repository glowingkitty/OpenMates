<script lang="ts">
  let { levels }: { levels: readonly number[] } = $props();
  // Interpolate the actual sixteen RMS bins for the reference's dense envelope.
  // No autonomous animation: silence remains a flat baseline.
  const bars = $derived(Array.from({ length: 48 }, (_, index) => {
    const position = index / 47 * Math.max(0, levels.length - 1);
    const first = Math.floor(position);
    const level = (levels[first] ?? 0) * (1 - position + first) + (levels[Math.ceil(position)] ?? 0) * (position - first);
    return Math.max(0, Math.min(1, Number.isFinite(level) ? level : 0));
  }));
</script>
<div class="waveform" data-testid="voice-call-waveform" aria-hidden="true">
  {#each bars as level, index (index)}<span style:height={`${Math.max(8, level * 100)}%`} data-level={level}></span>{/each}
</div>
<style>
  .waveform { display:flex; align-items:center; justify-content:center; gap:var(--spacing-1); height:2rem; width:100%; min-width:0; }
  span { display:block; flex:1; min-width:0; border-radius:var(--radius-full); background:currentColor; transition:height 80ms linear; }
  @media(max-width:700px) { span:nth-child(2n) { display:none; } }
  @media(prefers-reduced-motion:reduce) { span { transition:none; } }
</style>
