<!--
Purpose: Main status dashboard for production and development environments.
Architecture: Independent SPA reading from backend/status JSON endpoints.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status frontend tests not added yet)
-->
<script>
  import IncidentList from "./lib/components/IncidentList.svelte";
  import ResponseTimeChart from "./lib/components/ResponseTimeChart.svelte";
  import ServiceGroup from "./lib/components/ServiceGroup.svelte";
  import StatusBadge from "./lib/components/StatusBadge.svelte";
  import UptimeTable from "./lib/components/UptimeTable.svelte";
  import { fetchHistory, fetchResponseTimes, fetchStatus, fetchUptime } from "./lib/api";

  const pathname = window.location.pathname;
  const selectedEnv = pathname.startsWith("/dev") ? "dev" : "prod";

  let loading = $state(true);
  let statusPayload = $state(null);
  let historyPayload = $state({ events: [] });
  let uptimePayload = $state({ services: [] });
  let responseTimesPayload = $state({ points: [] });
  let chartPeriod = $state("24h");
  let loadError = $state("");

  let pageTitle = $derived(selectedEnv === "dev" ? "OpenMates Status - Development" : "OpenMates Status");
  let statusLabel = $derived(selectedEnv === "dev" ? "Development" : "Production");
  let overallStatus = $derived(statusPayload?.status ?? "unknown");

  async function load() {
    loading = true;
    loadError = "";
    try {
      const [status, history, uptime, responseTimes] = await Promise.all([
        fetchStatus(selectedEnv),
        fetchHistory(selectedEnv),
        fetchUptime(selectedEnv),
        fetchResponseTimes(selectedEnv, "core_api", chartPeriod)
      ]);
      statusPayload = status;
      historyPayload = history;
      uptimePayload = uptime;
      responseTimesPayload = responseTimes;
    } catch (error) {
      console.error("Failed loading status page", error);
      loadError = "Could not load status data.";
    } finally {
      loading = false;
    }
  }

  async function onPeriodChange(period) {
    chartPeriod = period;
    try {
      responseTimesPayload = await fetchResponseTimes(selectedEnv, "core_api", period);
    } catch (error) {
      console.error("Failed loading response time series", error);
    }
  }

  $effect(() => {
    document.title = pageTitle;
  });

  $effect(() => {
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  });
</script>

<main>
  <header class="hero">
    <div class="hero-content">
      <p class="eyebrow">OpenMates Service Health</p>
      <h1>{statusLabel} Status</h1>
      <p class="description">
        Live availability for the web app, core API, upload/preview servers, and provider infrastructure.
      </p>
      <div class="summary">
        <StatusBadge status={overallStatus} />
      </div>
      <div class="links">
        <a href="/">Production</a>
        <a href="/dev">Development</a>
      </div>
    </div>
  </header>

  <section class="content">
    {#if loading}
      <p class="state">Loading status data...</p>
    {:else if loadError}
      <p class="state error">{loadError}</p>
    {:else}
      <div class="groups-grid">
        {#each statusPayload.groups as group}
          <ServiceGroup {group} />
        {/each}
      </div>

      <section class="chart-panel">
        <div class="chart-header">
          <h2>Core API Response Time</h2>
          <div class="periods">
            <button class:active={chartPeriod === "24h"} onclick={() => onPeriodChange("24h")}>24h</button>
            <button class:active={chartPeriod === "7d"} onclick={() => onPeriodChange("7d")}>7d</button>
            <button class:active={chartPeriod === "30d"} onclick={() => onPeriodChange("30d")}>30d</button>
          </div>
        </div>
        <ResponseTimeChart points={responseTimesPayload.points} />
      </section>

      <div class="bottom-grid">
        <UptimeTable services={uptimePayload.services} />
        <IncidentList events={historyPayload.events} />
      </div>
    {/if}
  </section>
</main>

<style>
  :global(body) {
    margin: 0;
    font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    background: radial-gradient(circle at 20% -10%, #dcecff 0%, #f4f8ff 40%, #f6f8fb 100%);
    color: #1d2f44;
  }

  main {
    min-height: 100vh;
  }

  .hero {
    padding: 2.3rem 1rem 1.1rem;
  }

  .hero-content {
    max-width: 1060px;
    margin: 0 auto;
    background: linear-gradient(145deg, #0f2f55, #1c5489);
    border-radius: 18px;
    padding: 1.4rem;
    color: #f3f8ff;
    box-shadow: 0 14px 40px rgba(16, 47, 86, 0.35);
  }

  .eyebrow {
    margin: 0;
    font-size: 0.74rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    opacity: 0.88;
  }

  h1 {
    margin: 0.2rem 0 0.35rem;
    font-size: clamp(1.5rem, 2.8vw, 2.25rem);
  }

  .description {
    margin: 0;
    max-width: 60ch;
    opacity: 0.93;
    font-size: 0.96rem;
  }

  .summary {
    margin-top: 0.75rem;
  }

  .links {
    margin-top: 0.9rem;
    display: inline-flex;
    gap: 0.65rem;
  }

  .links a {
    background: rgba(255, 255, 255, 0.15);
    color: white;
    text-decoration: none;
    border: 1px solid rgba(255, 255, 255, 0.3);
    border-radius: 999px;
    padding: 0.3rem 0.7rem;
    font-size: 0.8rem;
  }

  .content {
    max-width: 1060px;
    margin: 0 auto;
    padding: 0 1rem 2rem;
  }

  .groups-grid {
    display: grid;
    gap: 0.8rem;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  }

  .chart-panel {
    margin-top: 0.95rem;
    background: #fff;
    border: 1px solid #d9e2ef;
    border-radius: 14px;
    padding: 1rem;
  }

  .chart-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    margin-bottom: 0.8rem;
  }

  .chart-header h2 {
    margin: 0;
    font-size: 1rem;
  }

  .periods {
    display: inline-flex;
    gap: 0.3rem;
  }

  .periods button {
    border: 1px solid #cfd9e7;
    border-radius: 7px;
    background: #f7f9fd;
    color: #3a4f67;
    font-size: 0.78rem;
    padding: 0.24rem 0.52rem;
    cursor: pointer;
  }

  .periods button.active {
    background: #284f83;
    border-color: #284f83;
    color: #fff;
  }

  .bottom-grid {
    margin-top: 0.95rem;
    display: grid;
    gap: 0.8rem;
    grid-template-columns: 1fr;
  }

  .state {
    background: #fff;
    border: 1px solid #dbe4f2;
    padding: 0.8rem;
    border-radius: 10px;
  }

  .state.error {
    color: #a23535;
  }

  @media (min-width: 920px) {
    .bottom-grid {
      grid-template-columns: 1fr 1fr;
    }
  }
</style>
