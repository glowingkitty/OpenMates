<!--
Purpose: Visual badge for status values (operational/degraded/down/unknown).
Architecture: Shared UI primitive for status cards and section headers.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status frontend tests not added yet)
-->
<script>
  let { status = "unknown" } = $props();

  const labels = {
    operational: "Operational",
    degraded: "Degraded",
    down: "Down",
    unknown: "Unknown"
  };
</script>

<span class={`badge badge-${status}`}>{labels[status] ?? labels.unknown}</span>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.2rem 0.6rem;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .badge-operational {
    background: #e4fce8;
    color: #0c6d2a;
  }

  .badge-degraded {
    background: #fff6db;
    color: #8f6500;
  }

  .badge-down {
    background: #ffe3e3;
    color: #9d1111;
  }

  .badge-unknown {
    background: #ecf0f5;
    color: #48566a;
  }
</style>
