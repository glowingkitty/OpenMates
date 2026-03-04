<!--
Purpose: Display recent incidents and status transitions.
Architecture: Incident feed maps directly to /api/status/history events.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status frontend tests not added yet)
-->
<script>
  let { events = [] } = $props();

  function formatDate(iso) {
    return new Date(iso).toLocaleString();
  }
</script>

<section class="incidents">
  <h2>Recent Incidents</h2>
  {#if events.length === 0}
    <p class="empty">No incidents in the selected time range.</p>
  {:else}
    <div class="list">
      {#each events as event}
        <article class="item">
          <div class="title">
            <strong>{event.service_name}</strong> changed to <code>{event.new_status}</code>
          </div>
          <div class="meta">{formatDate(event.created_at)}</div>
          {#if event.error_message}
            <div class="error">{event.error_message}</div>
          {/if}
        </article>
      {/each}
    </div>
  {/if}
</section>

<style>
  .incidents {
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

  .list {
    display: grid;
    gap: 0.6rem;
    max-height: 340px;
    overflow: auto;
  }

  .item {
    border: 1px solid #e3e9f3;
    border-radius: 10px;
    padding: 0.65rem;
    background: #fbfcff;
  }

  .title {
    color: #24364d;
    font-size: 0.9rem;
  }

  .meta {
    margin-top: 0.25rem;
    color: #678;
    font-size: 0.8rem;
  }

  .error {
    margin-top: 0.35rem;
    color: #a23636;
    font-size: 0.8rem;
  }

  .empty {
    margin: 0;
    color: #5f7288;
    font-size: 0.9rem;
  }

  code {
    background: #edf1f8;
    border-radius: 4px;
    padding: 0.1rem 0.35rem;
  }
</style>
