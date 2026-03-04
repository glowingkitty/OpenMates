<!--
Purpose: Group card that renders status rows for related services.
Architecture: Shared grouped rendering for core/platform/provider categories.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status frontend tests not added yet)
-->
<script>
  import StatusBadge from "./StatusBadge.svelte";

  let { group } = $props();

  function prettyName(groupName) {
    return groupName.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
  }
</script>

<section class="group-card">
  <header>
    <h2>{prettyName(group.group_name)}</h2>
    <StatusBadge status={group.status} />
  </header>

  <div class="services">
    {#each group.services as service}
      <article class="service-row">
        <div class="name">{service.service_name}</div>
        <div class="meta">
          {#if service.response_time_ms !== null}
            <span>{service.response_time_ms.toFixed(0)} ms</span>
          {/if}
          <StatusBadge status={service.status} />
        </div>
      </article>
    {/each}
  </div>
</section>

<style>
  .group-card {
    background: #ffffff;
    border: 1px solid #d7e1ef;
    border-radius: 14px;
    padding: 1rem;
    box-shadow: 0 6px 26px rgba(20, 40, 70, 0.04);
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.8rem;
  }

  h2 {
    margin: 0;
    color: #213349;
    font-size: 1rem;
  }

  .services {
    display: grid;
    gap: 0.5rem;
  }

  .service-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    border-top: 1px dashed #e0e7f1;
    padding-top: 0.5rem;
  }

  .service-row:first-child {
    border-top: none;
    padding-top: 0;
  }

  .name {
    color: #1c2f45;
    font-weight: 600;
    font-size: 0.95rem;
  }

  .meta {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    color: #65788e;
    font-size: 0.82rem;
  }
</style>
