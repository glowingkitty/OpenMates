<!--
Purpose: Compact uptime visualization for 24h/7d/30d/90d percentages.
Architecture: Lightweight, dependency-free chart replacement.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status frontend tests not added yet)
-->
<script>
  let { uptime } = $props();

  function colorFor(value) {
    if (value >= 99.5) return "#29a55a";
    if (value >= 95) return "#c89a1d";
    return "#d54b4b";
  }

  const windows = ["24h", "7d", "30d", "90d"];
</script>

<div class="bars">
  {#each windows as window}
    <div class="bar-block">
      <div class="bar-label">{window}</div>
      <div class="bar-track">
        <div
          class="bar-fill"
          style={`width: ${uptime?.[window] ?? 0}%; background: ${colorFor(uptime?.[window] ?? 0)};`}
        ></div>
      </div>
      <div class="bar-value">{(uptime?.[window] ?? 0).toFixed(2)}%</div>
    </div>
  {/each}
</div>

<style>
  .bars {
    display: grid;
    gap: 0.3rem;
  }

  .bar-block {
    display: grid;
    grid-template-columns: 2.8rem 1fr 4.2rem;
    align-items: center;
    gap: 0.45rem;
    font-size: 0.78rem;
  }

  .bar-label,
  .bar-value {
    color: #5d6f84;
  }

  .bar-track {
    height: 0.45rem;
    background: #e8edf3;
    border-radius: 999px;
    overflow: hidden;
  }

  .bar-fill {
    height: 100%;
    border-radius: 999px;
  }
</style>
