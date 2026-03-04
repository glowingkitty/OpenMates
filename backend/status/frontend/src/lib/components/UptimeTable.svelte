<!--
Purpose: Tabular uptime summary for each monitored service.
Architecture: Uses precomputed backend percentages for quick rendering.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status frontend tests not added yet)
-->
<script>
  import UptimeBar from "./UptimeBar.svelte";

  let { services = [] } = $props();
</script>

<section class="uptime-table">
  <h2>Uptime Summary</h2>
  <div class="rows">
    {#each services as service}
      <article class="row">
        <div class="name">{service.service_name}</div>
        <UptimeBar uptime={service.uptime} />
      </article>
    {/each}
  </div>
</section>

<style>
  .uptime-table {
    background: #fff;
    border: 1px solid #d9e2ef;
    border-radius: 14px;
    padding: 1rem;
  }

  h2 {
    margin: 0 0 0.8rem;
    color: #23364b;
    font-size: 1rem;
  }

  .rows {
    display: grid;
    gap: 0.75rem;
  }

  .row {
    border-top: 1px dashed #e0e8f3;
    padding-top: 0.75rem;
  }

  .row:first-child {
    border-top: none;
    padding-top: 0;
  }

  .name {
    margin-bottom: 0.4rem;
    color: #1f3349;
    font-size: 0.9rem;
    font-weight: 600;
  }
</style>
