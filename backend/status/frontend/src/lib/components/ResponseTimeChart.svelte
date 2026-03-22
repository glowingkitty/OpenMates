<!--
Purpose: SVG line chart for response-time trends over time.
Architecture: Dependency-free rendering to keep status app lightweight.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status frontend tests not added yet)
-->
<script>
  let { points = [] } = $props();

  const width = 900;
  const height = 220;
  const padding = 16;

  let polyline = $derived.by(() => {
    if (points.length < 2) {
      return "";
    }
    const values = points.map((point) => point.response_time_ms ?? 0);
    const maxValue = Math.max(...values, 1);
    const minValue = Math.min(...values, 0);
    const span = Math.max(maxValue - minValue, 1);

    return points
      .map((point, index) => {
        const x = padding + (index / (points.length - 1)) * (width - 2 * padding);
        const normalized = ((point.response_time_ms ?? 0) - minValue) / span;
        const y = height - padding - normalized * (height - 2 * padding);
        return `${x},${y}`;
      })
      .join(" ");
  });
</script>

<div class="chart">
  {#if points.length < 2}
    <div class="empty">Not enough data yet.</div>
  {:else}
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Response time trend">
      <polyline points={polyline} fill="none" stroke="#2b69d2" stroke-width="3" />
    </svg>
  {/if}
</div>

<style>
  .chart {
    background: white;
    border: 1px solid #d9e2ef;
    border-radius: 14px;
    padding: 0.6rem;
    min-height: 140px;
  }

  .chart svg {
    width: 100%;
    height: 220px;
    display: block;
  }

  .empty {
    color: #62758b;
    font-size: 0.9rem;
    padding: 1rem;
  }
</style>
